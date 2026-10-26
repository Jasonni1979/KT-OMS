"""AftersaleQueryMixin —— 由 AftersaleService 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.aftersale import (
    AftRefund,
    AftReturnApply,
    AftReturnApplyItem,
    AftReturnApplyLog,
)
from app.models.order import OrdOrder
from app.modules.m6_aftersale.service.aftersale_codes import (
    AFTERSALE_TYPE_LABEL,
    APPLY_CLOSED_STATUSES,
    APPLY_STATUS_LABEL,
    REFUND_STATUS_LABEL,
)


class AftersaleQueryMixin:
    """AftersaleService 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Any

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
