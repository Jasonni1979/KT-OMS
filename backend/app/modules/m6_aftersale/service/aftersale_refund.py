"""AftersaleRefundMixin —— 由 AftersaleService 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.timeutil import utcnow
from app.models.aftersale import (
    AftRefund,
    AftReturnApply,
    AftReturnApplyItem,
)
from app.models.order import OrdOrder
from app.modules.m6_aftersale.service.aftersale_codes import (
    APPLY_CLOSED_STATUSES,
    APPLY_STATUS_LABEL,
    AUDIT_MANUAL,
    CHANNEL_PLATFORM,
    REFUND_CANCELLED,
    REFUND_FAILED,
    REFUND_STATUS_LABEL,
    REFUND_WAIT,
    REFUNDED,
    REFUNDED_OFFLINE,
    REFUNDING,
    ST_EXCHANGING,
    ST_REFUNDING,
    ST_REJECTED,
    ST_WAIT_AUDIT,
    ST_WAIT_RETURN,
    SYNC_NONE,
    TYPE_REFUND_ONLY,
    TYPE_RETURN_REFUND,
)


class AftersaleRefundMixin:
    """AftersaleService 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Any

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
