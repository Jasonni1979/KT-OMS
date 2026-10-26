"""售后服务服务（D05.01 售后申请 + D05.03 仅退款与退款单 · W9-1）

本期做**最小闭环**：申请落库 → 审核 → 状态推进 → 退款单生成/受理 → 订单联动。

| SRS 条款 | 实现 |
|---|---|
| D05.01 FR-01b 落库幂等 | 唯一键 `(platform, shop_id, platform_aftersale_bn)`；重复事件复用 |
| D05.01 FR-01d 类型判定 | 1=仅退款 / 2=退货退款 / 3=换货 / 4=补发 |
| D05.01 FR-01e 原单关联 | 按 platform_order_bn 关联；订单缺失 → 落「待关联」异常态 |
| D05.01 FR-02a 申请单头 | RA/MA 单号 + 双口径金额 + 原因 + 时限 |
| D05.01 FR-02b/02c 状态机 | 11 条合法迁移，**唯一入口 transit**，非法流转拒绝 + 写日志 |
| D05.01 FR-02e 审核 | 同意/拒绝 + 拒绝原因码；审核动作原子编排 = 状态推进 + 退款单生成 |
| D05.01 FR-02f 部分售后 | 行级申请数量 + 双口径金额；数量上限校验（Σ ≤ 行购买数量） |
| D05.01 FR-03a 手工建单 | source=manual，operator 必填 |
| D05.01 FR-05a 售后中标记 | 申请单落库 → 订单打售后中标记；全部闭环 → 清除 |
| D05.01 FR-05b pay_status 联动 | 退款单受理 → 退款中；退款成功 → 部分/全额退款 |
| D05.01 FR-06a 时效 | 落单即算 deadline |
| D05.03 FR-01 退款单 | 审核同意涉钱 → 生成退款单（待退款） |
| D05.03 FR-02 退款执行 | 平台受理 → 退款中 → 已退款；失败可重试 |

⚠ **平台回传（FR-02d）本期为扩展位**：`sync_status` 记录状态但不真正下发平台指令
（D02.04 `SyncService::submitAftersaleAction` 未实现）→ 明确返回 `pending`。
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.timeutil import utcnow
from app.models.aftersale import (
    AftRefund,
    AftReturnApply,
    AftReturnApplyItem,
    AftReturnApplyLog,
)
from app.models.order import OrdOrder, OrdOrderItem

# ============ 枚举（DDL COMMENT 为权威）============

#: 售后类型
TYPE_REFUND_ONLY = 1  # 仅退款（不动货）
TYPE_RETURN_REFUND = 2  # 退货退款
TYPE_EXCHANGE = 3  # 换货
TYPE_RESHIPMENT = 4  # 补发

AFTERSALE_TYPE_LABEL: dict[int, str] = {
    TYPE_REFUND_ONLY: "仅退款",
    TYPE_RETURN_REFUND: "退货退款",
    TYPE_EXCHANGE: "换货",
    TYPE_RESHIPMENT: "补发",
}

#: 申请单状态
ST_PENDING_LINK = 0  # 待关联（订单缺失异常态）
ST_WAIT_AUDIT = 1  # 待审核
ST_WAIT_RETURN = 2  # 待退货
ST_WAIT_RECEIVE = 3  # 待收货
ST_WAIT_REFUND = 4  # 待退款
ST_REFUNDING = 5  # 退款中
ST_EXCHANGING = 6  # 换货执行中
ST_DONE = 7  # 完成
ST_REJECTED = 8  # 拒绝（可 reopen）
ST_CLOSED = 9  # 关闭

APPLY_STATUS_LABEL: dict[int, str] = {
    ST_PENDING_LINK: "待关联",
    ST_WAIT_AUDIT: "待审核",
    ST_WAIT_RETURN: "待退货",
    ST_WAIT_RECEIVE: "待收货",
    ST_WAIT_REFUND: "待退款",
    ST_REFUNDING: "退款中",
    ST_EXCHANGING: "换货执行中",
    ST_DONE: "完成",
    ST_REJECTED: "拒绝",
    ST_CLOSED: "关闭",
}

#: 终态（FR-05a：全部闭环才清除订单售后中标记）
APPLY_CLOSED_STATUSES = (ST_DONE, ST_REJECTED, ST_CLOSED)

#: 货物状态
GOODS_UNSHIPPED = 0
GOODS_SHIPPED = 1
GOODS_RECEIVED = 2

#: 退款单状态
REFUND_WAIT = 1
REFUNDING = 2
REFUNDED = 3
REFUND_FAILED = 4
REFUNDED_OFFLINE = 5
REFUND_CANCELLED = 6

REFUND_STATUS_LABEL: dict[int, str] = {
    REFUND_WAIT: "待退款",
    REFUNDING: "退款中",
    REFUNDED: "已退款",
    REFUND_FAILED: "退款失败",
    REFUNDED_OFFLINE: "已退款-线下",
    REFUND_CANCELLED: "已取消",
}

#: 退款渠道
CHANNEL_PLATFORM = 1
CHANNEL_OFFLINE = 2

#: 平台回传状态
SYNC_NONE = 0
SYNC_DOING = 1
SYNC_SUCCESS = 2
SYNC_RETRY = 3
SYNC_MANUAL = 4

#: 审核通道
AUDIT_MANUAL = 1
AUDIT_AUTO = 2
AUDIT_OA = 3

#: 操作者类型
OP_MANUAL = 1
OP_SYSTEM = 2
OP_PLATFORM = 3

# ============ 状态流转表（D05.01 §5.1 权威）============
#: (当前状态, 目标状态) → 允许
#: 类型裁剪在 `_type_allowed` 里做（仅退款无待退货/待收货；换货无待退款/退款中）
ALLOWED_TRANSITIONS: dict[int, tuple[int, ...]] = {
    ST_WAIT_AUDIT: (ST_WAIT_RETURN, ST_REFUNDING, ST_EXCHANGING, ST_REJECTED, ST_CLOSED),
    ST_REJECTED: (ST_WAIT_AUDIT,),
    ST_WAIT_RETURN: (ST_WAIT_RECEIVE,),
    ST_WAIT_RECEIVE: (ST_WAIT_REFUND,),
    ST_WAIT_REFUND: (ST_DONE, ST_CLOSED),
    ST_REFUNDING: (ST_DONE, ST_CLOSED),
    ST_EXCHANGING: (ST_DONE, ST_CLOSED),
    ST_PENDING_LINK: (ST_WAIT_AUDIT, ST_CLOSED),
}

#: 默认处理时限（小时）—— FR-06a 按平台×类型×店铺配置，本期用缺省值
DEFAULT_DEADLINE_HOURS = {
    TYPE_REFUND_ONLY: 48,
    TYPE_RETURN_REFUND: 120,  # 淘系退货申请 5 天
    TYPE_EXCHANGE: 120,
    TYPE_RESHIPMENT: 72,
}


class AftersaleService:
    """售后服务服务（D05）"""

    def __init__(self, session: AsyncSession, redis: Any = None) -> None:
        self.s = session
        self.r = redis

    # ============ 落单（FR-01b/01d/01e/02a/02f）============

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

    # ============ 状态推进（FR-02b/02c 唯一入口）============

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

    # ============ 审核（FR-02e）============

    async def audit(
        self,
        apply_id: int,
        *,
        agree: bool,
        operator: str,
        audit_channel: int = AUDIT_MANUAL,
        reject_reason_code: str = "",
        approved_amount_customer: float | None = None,
        approved_amount_platform_bear: float | None = None,
        approved_items: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """审核（FR-02e）

        原子编排 = 状态推进 + 退款单生成（涉钱类型）。
        拒绝 → 状态到「拒绝」+ 记录拒绝原因码。
        """
        row = await self._get(apply_id)
        if int(row.status) != ST_WAIT_AUDIT:
            raise ConflictError(
                f"仅「待审核」可审核，当前状态 "
                f"{APPLY_STATUS_LABEL.get(int(row.status), row.status)}",
                code="AFTERSALE_STATUS_INVALID",
            )
        row.audit_channel = audit_channel
        row.auditor = operator
        row.audit_time = utcnow()

        if not agree:
            await self.transit(
                apply_id,
                ST_REJECTED,
                trigger="audit_reject",
                operator=operator,
                detail={"reject_reason_code": reject_reason_code},
            )
            return {
                "ok": True,
                "apply_id": apply_id,
                "decision": "reject",
                "status": ST_REJECTED,
                "reject_reason_code": reject_reason_code,
                # 平台回传未实现（D02.04）→ 明确 pending，不伪造成功
                "sync_status": SYNC_NONE,
                "sync_pending": True,
            }

        # 同意：落同意金额与同意数量（支持行级部分同意 FR-02f）
        if approved_amount_customer is not None:
            row.approved_amount_customer = approved_amount_customer
        if approved_amount_platform_bear is not None:
            row.approved_amount_platform_bear = approved_amount_platform_bear
        if approved_items:
            for ai in approved_items:
                it = await self.s.scalar(
                    select(AftReturnApplyItem).where(
                        AftReturnApplyItem.id == int(ai.get("id") or 0),
                        AftReturnApplyItem.apply_id == apply_id,
                    )
                )
                if it is not None:
                    it.approved_num = int(ai.get("approved_num") or 0)
                    it.approved_amount_customer_line = float(
                        ai.get("approved_amount_customer_line") or 0
                    )
        if row.approved_amount_customer in (None, 0) and not approved_amount_customer:
            row.approved_amount_customer = row.apply_amount_customer
        if (
            row.approved_amount_platform_bear in (None, 0)
            and not approved_amount_platform_bear
        ):
            row.approved_amount_platform_bear = row.apply_amount_platform_bear

        refund_id = 0
        refund_bn = ""
        # 涉钱类型（仅退款 / 退货退款 / 补发差价）→ 生成退款单（D05.03）
        if int(row.aftersale_type) in (TYPE_REFUND_ONLY, TYPE_RETURN_REFUND):
            refund = await self.create_refund(row, operator=operator)
            refund_id = refund.id
            refund_bn = refund.refund_bn

        # 状态推进：仅退款 → 退款中；退货退款 → 待退货
        if int(row.aftersale_type) == TYPE_REFUND_ONLY:
            await self.transit(
                apply_id,
                ST_REFUNDING,
                trigger="audit_agree",
                operator=operator,
                detail={"refund_id": refund_id},
            )
        elif int(row.aftersale_type) == TYPE_RETURN_REFUND:
            await self.transit(
                apply_id,
                ST_WAIT_RETURN,
                trigger="audit_agree",
                operator=operator,
                detail={"refund_id": refund_id},
            )
        else:
            await self.transit(
                apply_id,
                ST_EXCHANGING,
                trigger="audit_agree",
                operator=operator,
            )
        return {
            "ok": True,
            "apply_id": apply_id,
            "decision": "agree",
            "refund_id": refund_id,
            "refund_bn": refund_bn,
            # 平台回传未实现（D02.04）→ 明确 pending
            "sync_status": SYNC_NONE,
            "sync_pending": True,
        }

    # ============ 退款单（D05.03）============

    async def create_refund(
        self, apply: AftReturnApply, *, operator: str = "system"
    ) -> AftRefund:
        """生成退款单（D05.03 FR-01：由审核同意触发）"""
        refund_bn = f"RF{utcnow():%Y%m%d}{uuid.uuid4().hex[:6].upper()}"
        row = AftRefund(
            tenant_id=apply.tenant_id,
            owner_id=apply.owner_id,
            shop_id=apply.shop_id,
            refund_bn=refund_bn,
            apply_id=apply.id,
            order_id=apply.order_id,
            order_bn=apply.order_bn,
            source="apply_audit",
            status=REFUND_WAIT,
            channel=CHANNEL_PLATFORM,
            refund_customer=apply.approved_amount_customer or apply.apply_amount_customer,
            refund_platform_bear=(
                apply.approved_amount_platform_bear or apply.apply_amount_platform_bear
            ),
            platform=apply.platform,
            auditor=operator,
            audit_channel=AUDIT_MANUAL,
            version=0,
        )
        self.s.add(row)
        await self.s.flush()
        await self.s.commit()
        await self.s.refresh(row)
        return row

    async def refund_transit(
        self,
        refund_id: int,
        to_status: int,
        *,
        operator: str = "system",
        fail_reason_code: str = "",
        platform_refund_no: str = "",
    ) -> AftRefund:
        """退款单状态推进（D05.03 FR-02）

        合法迁移：待退款→退款中→已退款；退款中→退款失败→退款中（重试）；
        任意未打款态→已取消。
        """
        row = await self.s.scalar(
            select(AftRefund).where(AftRefund.id == refund_id)
        )
        if row is None:
            raise NotFoundError(f"退款单不存在: {refund_id}")
        from_status = int(row.status)
        allowed = {
            REFUND_WAIT: (REFUNDING, REFUND_CANCELLED),
            REFUNDING: (REFUNDED, REFUND_FAILED, REFUND_CANCELLED),
            REFUND_FAILED: (REFUNDING, REFUND_CANCELLED),
            REFUNDED: (),
            REFUNDED_OFFLINE: (),
            REFUND_CANCELLED: (),
        }.get(from_status, ())
        if to_status not in allowed:
            raise ConflictError(
                f"退款单状态不可从 {REFUND_STATUS_LABEL.get(from_status, from_status)} "
                f"流转到 {REFUND_STATUS_LABEL.get(to_status, to_status)}"
                f"（允许: {', '.join(REFUND_STATUS_LABEL.get(s, str(s)) for s in allowed) or '无'}）",
                code="REFUND_STATUS_INVALID",
            )
        row.status = to_status
        if to_status == REFUNDED:
            row.refund_time = utcnow()
            row.platform_executed_amount = row.refund_customer
        if to_status == REFUNDING:
            row.refund_time = None
        if to_status == REFUND_FAILED:
            row.fail_reason_code = fail_reason_code
        if platform_refund_no:
            row.platform_refund_no = platform_refund_no
        await self.s.commit()
        await self.s.refresh(row)

        # 退款成功 → 订单 pay_status 联动（FR-05b）
        if to_status in (REFUNDED, REFUNDED_OFFLINE):
            await self._link_order_pay_status(row)
        return row

    async def _link_order_pay_status(self, refund: AftRefund) -> None:
        """退款成功 → 订单 pay_status 派生（FR-05b）

        部分退款 → pay_status=part_refunded；全额 → refunded。
        """
        if not refund.order_id:
            return
        order = await self.s.scalar(
            select(OrdOrder).where(
                OrdOrder.id == refund.order_id, OrdOrder.is_deleted == 0
            )
        )
        if order is None:
            return
        paid = float(order.paid_amount or 0)
        refunded = float(refund.refund_customer or 0)
        if paid > 0 and refunded >= paid - 0.01:
            order.pay_status = "refunded"
        else:
            order.pay_status = "part_refunded"
        order.update_time = utcnow()
        order.version = int(order.version or 0) + 1
        await self.s.commit()

    # ============ 订单联动（FR-05a）============

    async def _mark_order_in_aftersale(self, order: OrdOrder, *, add: bool) -> None:
        """订单售后中标记（FR-05a）

        有在途售后 → 标记；全部闭环 → 清除。
        """
        if add:
            open_cnt = int(
                await self.s.scalar(
                    select(func.count())
                    .select_from(AftReturnApply.__table__)
                    .where(
                        AftReturnApply.order_id == order.id,
                        AftReturnApply.status.notin_(APPLY_CLOSED_STATUSES),
                    )
                )
                or 0
            )
            if open_cnt > 0:
                order.fulfill_status = "aftersale"
                order.update_time = utcnow()
                order.version = int(order.version or 0) + 1
                await self.s.commit()
            return
        # 清除：检查是否还有其它在途售后
        others = int(
            await self.s.scalar(
                select(func.count())
                .select_from(AftReturnApply.__table__)
                .where(
                    AftReturnApply.order_id == order.id,
                    AftReturnApply.status.notin_(APPLY_CLOSED_STATUSES),
                )
            )
            or 0
        )
        if others == 0:
            order.fulfill_status = "pending"
            order.update_time = utcnow()
            order.version = int(order.version or 0) + 1
            await self.s.commit()

    # ============ 查询 ============

    async def _get(self, apply_id: int) -> AftReturnApply:
        row = await self.s.scalar(
            select(AftReturnApply).where(AftReturnApply.id == apply_id)
        )
        if row is None:
            raise NotFoundError(f"售后申请单不存在: {apply_id}")
        return row

    async def _order_of(self, row: AftReturnApply) -> OrdOrder | None:
        if not row.order_id:
            return None
        return await self.s.scalar(
            select(OrdOrder).where(
                OrdOrder.id == row.order_id, OrdOrder.is_deleted == 0
            )
        )

    async def list_applies(
        self,
        *,
        status: int | None = None,
        aftersale_type: int | None = None,
        order_id: int | None = None,
        shop_id: int | None = None,
        only_open: bool = False,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """售后申请列表（FR-07a 工作台队列用）"""
        q = select(AftReturnApply)
        if status is not None:
            q = q.where(AftReturnApply.status == status)
        if aftersale_type is not None:
            q = q.where(AftReturnApply.aftersale_type == aftersale_type)
        if order_id:
            q = q.where(AftReturnApply.order_id == order_id)
        if shop_id:
            q = q.where(AftReturnApply.shop_id == shop_id)
        if only_open:
            q = q.where(AftReturnApply.status.notin_(APPLY_CLOSED_STATUSES))
        rows = list(await self.s.scalars(q.order_by(AftReturnApply.id.desc()).limit(limit)))
        return [
            {
                "id": r.id,
                "apply_bn": r.apply_bn,
                "source": r.source,
                "platform": r.platform,
                "shop_id": r.shop_id,
                "aftersale_type": r.aftersale_type,
                "aftersale_type_name": AFTERSALE_TYPE_LABEL.get(
                    r.aftersale_type, str(r.aftersale_type)
                ),
                "status": r.status,
                "status_name": APPLY_STATUS_LABEL.get(r.status, str(r.status)),
                "goods_status": r.goods_status,
                "order_id": r.order_id,
                "order_bn": r.order_bn,
                "apply_amount_customer": float(r.apply_amount_customer or 0),
                "apply_amount_platform_bear": float(
                    r.apply_amount_platform_bear or 0
                ),
                "approved_amount_customer": float(
                    r.approved_amount_customer or 0
                ),
                "reason_code": r.reason_code,
                "deadline": r.deadline.strftime("%Y-%m-%d %H:%M:%S")
                if r.deadline
                else None,
                "warn_level": r.warn_level,
                "sync_status": r.sync_status,
                "create_time": r.create_time.strftime("%Y-%m-%d %H:%M:%S")
                if r.create_time
                else None,
            }
            for r in rows
        ]

    async def get_apply(self, apply_id: int) -> dict[str, Any]:
        """售后申请详情（含行与操作日志）"""
        row = await self._get(apply_id)
        items = list(
            await self.s.scalars(
                select(AftReturnApplyItem).where(
                    AftReturnApplyItem.apply_id == apply_id,
                    AftReturnApplyItem.is_deleted == 0,
                )
            )
        )
        logs = list(
            await self.s.scalars(
                select(AftReturnApplyLog)
                .where(AftReturnApplyLog.apply_id == apply_id)
                .order_by(AftReturnApplyLog.seq)
            )
        )
        refunds = list(
            await self.s.scalars(
                select(AftRefund).where(AftRefund.apply_id == apply_id)
            )
        )
        return {
            "id": row.id,
            "apply_bn": row.apply_bn,
            "source": row.source,
            "platform": row.platform,
            "platform_aftersale_bn": row.platform_aftersale_bn,
            "aftersale_type": row.aftersale_type,
            "aftersale_type_name": AFTERSALE_TYPE_LABEL.get(
                row.aftersale_type, str(row.aftersale_type)
            ),
            "status": row.status,
            "status_name": APPLY_STATUS_LABEL.get(row.status, str(row.status)),
            "goods_status": row.goods_status,
            "order_id": row.order_id,
            "order_bn": row.order_bn,
            "apply_amount_customer": float(row.apply_amount_customer or 0),
            "apply_amount_platform_bear": float(
                row.apply_amount_platform_bear or 0
            ),
            "approved_amount_customer": float(
                row.approved_amount_customer or 0
            ),
            "reason_code": row.reason_code,
            "reason_raw": row.reason_raw,
            "buyer_claim": row.buyer_claim,
            "deadline": row.deadline.strftime("%Y-%m-%d %H:%M:%S")
            if row.deadline
            else None,
            "operator": row.operator,
            "auditor": row.auditor,
            "audit_time": row.audit_time.strftime("%Y-%m-%d %H:%M:%S")
            if row.audit_time
            else None,
            "sync_status": row.sync_status,
            "auto_agreed_by_platform": row.auto_agreed_by_platform,
            "create_time": row.create_time.strftime("%Y-%m-%d %H:%M:%S")
            if row.create_time
            else None,
            "items": [
                {
                    "id": i.id,
                    "order_item_id": i.order_item_id,
                    "oid": i.oid,
                    "bm_id": i.bm_id,
                    "sku_name": i.sku_name,
                    "apply_num": i.apply_num,
                    "approved_num": i.approved_num,
                    "apply_amount_customer_line": float(
                        i.apply_amount_customer_line or 0
                    ),
                    "approved_amount_customer_line": float(
                        i.approved_amount_customer_line or 0
                    ),
                    "gift_flag": i.gift_flag,
                }
                for i in items
            ],
            "logs": [
                {
                    "seq": lg.seq,
                    "action": lg.action,
                    "from_status": lg.from_status,
                    "to_status": lg.to_status,
                    "operator": lg.operator,
                    "operator_type": lg.operator_type,
                    "detail": lg.detail_json,
                    "create_time": lg.create_time.strftime("%Y-%m-%d %H:%M:%S")
                    if lg.create_time
                    else None,
                }
                for lg in logs
            ],
            "refunds": [
                {
                    "id": rf.id,
                    "refund_bn": rf.refund_bn,
                    "status": rf.status,
                    "status_name": REFUND_STATUS_LABEL.get(
                        rf.status, str(rf.status)
                    ),
                    "channel": rf.channel,
                    "refund_customer": float(rf.refund_customer or 0),
                    "platform_refund_no": rf.platform_refund_no,
                }
                for rf in refunds
            ],
        }
