"""AftersaleApplyMixin —— 由 AftersaleService 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ValidationError
from app.core.timeutil import utcnow
from app.models.aftersale import (
    AftReturnApply,
    AftReturnApplyItem,
    AftReturnApplyLog,
)
from app.models.order import OrdOrder, OrdOrderItem
from app.modules.m6_aftersale.service.aftersale_codes import (
    AFTERSALE_TYPE_LABEL,
    ALLOWED_TRANSITIONS,
    APPLY_CLOSED_STATUSES,
    APPLY_STATUS_LABEL,
    DEFAULT_DEADLINE_HOURS,
    GOODS_UNSHIPPED,
    OP_MANUAL,
    ST_CLOSED,
    ST_PENDING_LINK,
    ST_REFUNDING,
    ST_REJECTED,
    ST_WAIT_AUDIT,
    ST_WAIT_RECEIVE,
    ST_WAIT_REFUND,
    ST_WAIT_RETURN,
    TYPE_EXCHANGE,
    TYPE_REFUND_ONLY,
)


class AftersaleApplyMixin:
    """AftersaleService 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Any

    async def create_apply(
        self,
        *,
        aftersale_type: int,
        platform: str = "",
        shop_id: int = 0,
        platform_aftersale_bn: str = "",
        platform_order_bn: str = "",
        order_id: int = 0,
        items: list[dict[str, Any]] | None = None,
        reason_code: str = "",
        reason_raw: str = "",
        buyer_claim: str = "",
        apply_amount_customer: float = 0,
        apply_amount_platform_bear: float = 0,
        source: str = "platform",
        operator: str = "",
        goods_status: int = GOODS_UNSHIPPED,
    ) -> tuple[AftReturnApply, bool]:
        """创建售后申请单（FR-02a）

        返回 (申请单, 是否新建)。平台单按 `(platform, shop_id, platform_aftersale_bn)`
        幂等（FR-01b）；手工单每次新建。
        """
        if aftersale_type not in AFTERSALE_TYPE_LABEL:
            raise ValidationError(f"非法售后类型: {aftersale_type}")
        if source == "manual" and not operator:
            raise ValidationError("手工建单须填操作人（FR-03a）")

        # 幂等（FR-01b）：平台单按三键唯一
        if platform_aftersale_bn:
            existing = await self.s.scalar(
                select(AftReturnApply).where(
                    AftReturnApply.platform == platform,
                    AftReturnApply.shop_id == shop_id,
                    AftReturnApply.platform_aftersale_bn == platform_aftersale_bn,
                )
            )
            if existing is not None:
                return existing, False

        # 原单关联（FR-01e）：订单缺失 → 落「待关联」异常态
        order: OrdOrder | None = None
        if order_id:
            order = await self.s.scalar(
                select(OrdOrder).where(
                    OrdOrder.id == order_id, OrdOrder.is_deleted == 0
                )
            )
        elif platform_order_bn:
            order = await self.s.scalar(
                select(OrdOrder).where(
                    OrdOrder.platform_order_bn == platform_order_bn,
                    OrdOrder.is_deleted == 0,
                )
            )
        status = ST_WAIT_AUDIT if order is not None else ST_PENDING_LINK

        # 行校验（FR-02f）：数量上限 Σ(本单+历史处理中+历史完成) ≤ 行购买数量
        norm_items = await self._validate_items(order, items or [])

        apply_bn = (
            f"RA{utcnow():%Y%m%d}{uuid.uuid4().hex[:6].upper()}"
            if source != "manual"
            else f"MA{utcnow():%Y%m%d}{uuid.uuid4().hex[:6].upper()}"
        )
        now = utcnow()
        deadline_hours = DEFAULT_DEADLINE_HOURS.get(aftersale_type, 72)
        row = AftReturnApply(
            tenant_id=order.tenant_id if order else 1,
            owner_id=order.owner_id if order else 0,
            apply_bn=apply_bn,
            source=source,
            platform=platform,
            shop_id=shop_id or (order.shop_id if order else 0),
            platform_aftersale_bn=platform_aftersale_bn or None,
            aftersale_type=aftersale_type,
            status=status,
            goods_status=goods_status,
            order_id=order.id if order else 0,
            order_bn=order.order_bn if order else "",
            apply_amount_customer=apply_amount_customer,
            apply_amount_platform_bear=apply_amount_platform_bear,
            reason_code=reason_code,
            reason_raw=reason_raw,
            buyer_claim=buyer_claim,
            deadline=now + timedelta(hours=deadline_hours),
            operator=operator,
            version=0,
        )
        self.s.add(row)
        await self.s.flush()

        for it in norm_items:
            self.s.add(
                AftReturnApplyItem(
                    tenant_id=row.tenant_id,
                    owner_id=row.owner_id,
                    apply_id=row.id,
                    order_item_id=int(it.get("order_item_id") or 0),
                    oid=str(it.get("oid") or ""),
                    bm_id=int(it.get("bm_id") or 0),
                    sku_name=str(it.get("sku_name") or ""),
                    sku_spec=str(it.get("sku_spec") or ""),
                    apply_num=int(it.get("apply_num") or 0),
                    approved_num=0,
                    apply_amount_customer_line=float(
                        it.get("apply_amount_customer_line") or 0
                    ),
                    apply_amount_platform_bear_line=float(
                        it.get("apply_amount_platform_bear_line") or 0
                    ),
                    approved_amount_customer_line=0,
                    gift_flag=int(it.get("gift_flag") or 0),
                    combo_ref=str(it.get("combo_ref") or ""),
                    version=0,
                    is_deleted=0,
                )
            )

        # 状态变迁日志（FR-02c）
        await self._log(row.id, "create", 0, status, operator=operator or "system")
        # 订单售后中标记（FR-05a）
        if order is not None:
            await self._mark_order_in_aftersale(order, add=True)
        await self.s.commit()
        await self.s.refresh(row)
        return row, True

    async def _validate_items(
        self, order: OrdOrder | None, items: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """行校验（FR-02f）：数量上限 Σ(本单+历史) ≤ 行购买数量"""
        if not items:
            return []
        if order is None:
            raise ValidationError("订单未关联，不能提交申请行")
        out: list[dict[str, Any]] = []
        for it in items:
            item_id = int(it.get("order_item_id") or 0)
            want = int(it.get("apply_num") or 0)
            if want <= 0:
                raise ValidationError("申请数量必须大于 0")
            oi = await self.s.scalar(
                select(OrdOrderItem).where(
                    OrdOrderItem.id == item_id, OrdOrderItem.is_deleted == 0
                )
            )
            if oi is None:
                raise ValidationError(f"订单行不存在: {item_id}")
            if oi.order_id != order.id:
                raise ValidationError(f"订单行 {item_id} 不属于订单 {order.id}")
            # 历史已申请数量（处理中 + 完成，排除拒绝/关闭）
            hist = await self.s.scalar(
                select(func.coalesce(func.sum(AftReturnApplyItem.apply_num), 0))
                .select_from(
                    AftReturnApplyItem.__table__.join(
                        AftReturnApply.__table__,
                        AftReturnApplyItem.apply_id == AftReturnApply.id,
                    )
                )
                .where(
                    AftReturnApplyItem.order_item_id == item_id,
                    AftReturnApplyItem.is_deleted == 0,
                    AftReturnApply.status.notin_(
                        (ST_REJECTED, ST_CLOSED, ST_PENDING_LINK)
                    ),
                )
            )
            used = int(hist or 0)
            if used + want > int(oi.nums or 0):
                raise ValidationError(
                    f"申请数量超限：行 {item_id} 购买 {oi.nums}，"
                    f"历史已申请 {used}，本次 {want}"
                )
            out.append(
                {
                    **it,
                    "order_item_id": item_id,
                    "bm_id": int(it.get("bm_id") or oi.bm_id or 0),
                    "sku_name": str(it.get("sku_name") or oi.bm_name or ""),
                    "apply_num": want,
                }
            )
        return out

    async def transit(
        self,
        apply_id: int,
        to_status: int,
        *,
        trigger: str = "manual",
        operator: str = "system",
        operator_type: int = OP_MANUAL,
        detail: dict | None = None,
    ) -> AftReturnApply:
        """状态推进唯一入口（FR-02c）

        校验 §5.1 流转表合法性 + **类型裁剪**（仅退款无待退货/待收货；
        换货无待退款/退款中）；非法流转拒绝 + 写日志。
        """
        row = await self._get(apply_id)
        from_status = int(row.status)
        if to_status == from_status:
            return row
        allowed = ALLOWED_TRANSITIONS.get(from_status, ())
        if to_status not in allowed:
            raise ConflictError(
                f"售后单状态不可从 {APPLY_STATUS_LABEL.get(from_status, from_status)} "
                f"流转到 {APPLY_STATUS_LABEL.get(to_status, to_status)}"
                f"（允许: {', '.join(APPLY_STATUS_LABEL.get(s, str(s)) for s in allowed) or '无'}）",
                code="AFTERSALE_STATUS_INVALID",
            )
        # 类型裁剪（FR-02b）
        if not self._type_allowed(int(row.aftersale_type), to_status):
            raise ConflictError(
                f"类型 {AFTERSALE_TYPE_LABEL.get(row.aftersale_type)} "
                f"不允许流转到 {APPLY_STATUS_LABEL.get(to_status, to_status)}"
                "（仅退款无待退货/待收货，换货无待退款/退款中）",
                code="AFTERSALE_TYPE_STATUS_MISMATCH",
            )
        row.status = to_status
        await self._log(
            row.id,
            trigger,
            from_status,
            to_status,
            operator=operator,
            operator_type=operator_type,
            detail=detail,
        )
        # 闭环 → 清除订单售后中标记（FR-05a）
        if to_status in APPLY_CLOSED_STATUSES:
            order = await self._order_of(row)
            if order is not None:
                await self._mark_order_in_aftersale(order, add=False)
        await self.s.commit()
        await self.s.refresh(row)
        return row

    @staticmethod
    def _type_allowed(aftersale_type: int, to_status: int) -> bool:
        """类型裁剪（FR-02b）"""
        if aftersale_type == TYPE_REFUND_ONLY and to_status in (
            ST_WAIT_RETURN,
            ST_WAIT_RECEIVE,
        ):
            return False
        if aftersale_type == TYPE_EXCHANGE and to_status in (
            ST_WAIT_REFUND,
            ST_REFUNDING,
        ):
            return False
        return True

    async def _log(
        self,
        apply_id: int,
        action: str,
        from_status: int,
        to_status: int,
        *,
        operator: str = "system",
        operator_type: int = OP_MANUAL,
        detail: dict | None = None,
    ) -> None:
        """写状态变迁日志（FR-02c）"""
        seq = int(
            await self.s.scalar(
                select(AftReturnApplyLog.seq)
                .where(AftReturnApplyLog.apply_id == apply_id)
                .order_by(AftReturnApplyLog.seq.desc())
                .limit(1)
            )
            or 0
        ) + 1
        self.s.add(
            AftReturnApplyLog(
                tenant_id=1,
                owner_id=0,
                apply_id=apply_id,
                seq=seq,
                action=action,
                from_status=from_status,
                to_status=to_status,
                operator_type=operator_type,
                operator=operator,
                detail_json=detail or {},
            )
        )
