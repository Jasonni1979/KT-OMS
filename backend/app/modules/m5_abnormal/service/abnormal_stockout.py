"""AbnormalStockoutMixin —— 由 AbnormalService 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.core.timeutil import utcnow
from app.models.abnormal import (
    OrdAbnormal,
    OrdStockout,
)
from app.models.audit import OrdAuditReason
from app.modules.m5_abnormal.service.abnormal_codes import (
    CLOSED_STATUSES,
)

logger = get_logger("abnormal")


class AbnormalStockoutMixin:
    """AbnormalService 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Any

    async def release_order_marks(
        self, row: OrdAbnormal, *, operator: str = "system"
    ) -> bool:
        """解除订单异常标记

        订单存在多个未闭环异常单时，**全部闭环才解除标记**（对齐 D03.02
        「结构化原因清零才可审」）。解除动作 = 把对应审单原因置为 handled。
        """
        others = await self.s.scalars(
            select(OrdAbnormal).where(
                OrdAbnormal.order_id == row.order_id,
                OrdAbnormal.id != row.id,
                OrdAbnormal.status.notin_(CLOSED_STATUSES),
                OrdAbnormal.is_deleted == 0,
            )
        )
        if list(others):
            return False  # 还有未闭环异常单 → 不解除
        # 审单原因置 handled（D03.02 写入口径：open → handled）
        await self.s.execute(
            update(OrdAuditReason)
            .where(
                OrdAuditReason.order_id == row.order_id,
                OrdAuditReason.handle_status == "open",
            )
            .values(handle_status="handled", handle_way=f"abnormal:{operator}"[:64])
        )
        await self.s.commit()
        return True

    async def mark_stockout(
        self,
        row: OrdAbnormal,
        items: list[dict],
        *,
        oversold: bool = False,
    ) -> list[OrdStockout]:
        """缺货标记与明细

        items 每项：{branch_id, bm_id, lack_num, stock_snapshot?}
        **同一订单多次预占失败按明细合并更新缺口**（FR-04a）：
        同 (branch_id, bm_id) 已有明细 → 累加 lack_num 并刷新快照。
        """
        out: list[OrdStockout] = []
        for it in items:
            branch_id = int(it.get("branch_id") or 0)
            bm_id = int(it.get("bm_id") or 0)
            lack = int(it.get("lack_num") or 0)
            exist = await self.s.scalar(
                select(OrdStockout).where(
                    OrdStockout.abnormal_id == row.id,
                    OrdStockout.branch_id == branch_id,
                    OrdStockout.bm_id == bm_id,
                    OrdStockout.is_deleted == 0,
                )
            )
            if exist is not None:
                exist.lack_num = int(exist.lack_num or 0) + lack
                if it.get("stock_snapshot") is not None:
                    exist.stock_snapshot = it["stock_snapshot"]
                exist.oversold_flag = 1 if oversold else exist.oversold_flag
                exist.version += 1
                out.append(exist)
            else:
                detail = OrdStockout(
                    tenant_id=row.tenant_id,
                    owner_id=row.owner_id,
                    abnormal_id=row.id,
                    order_id=row.order_id,
                    branch_id=branch_id,
                    bm_id=bm_id,
                    lack_num=lack,
                    stock_snapshot=it.get("stock_snapshot"),
                    strategy_status="wait_calc",
                    oversold_flag=1 if oversold else 0,
                    version=0,
                    is_deleted=0,
                )
                self.s.add(detail)
                out.append(detail)
        await self.s.commit()
        for d in out:
            await self.s.refresh(d)
        return out

    async def stockouts_of(self, abnormal_id: int) -> list[OrdStockout]:
        rows = await self.s.scalars(
            select(OrdStockout)
            .where(
                OrdStockout.abnormal_id == abnormal_id,
                OrdStockout.is_deleted == 0,
            )
            .order_by(OrdStockout.id)
        )
        return list(rows)

    async def set_strategy_result(
        self,
        detail_id: int,
        *,
        status: str,
        result: dict | None = None,
    ) -> OrdStockout:
        """回写策略链结果（FR-04b）"""
        row = await self.s.scalar(
            select(OrdStockout).where(OrdStockout.id == detail_id)
        )
        if row is None:
            raise NotFoundError(f"缺货明细不存在: {detail_id}")
        row.strategy_status = status
        if result is not None:
            row.strategy_result = result
        row.version += 1
        await self.s.commit()
        await self.s.refresh(row)
        return row

    async def set_strategy_result_of(
        self,
        abnormal_id: int,
        *,
        status: str,
        result: dict | None = None,
    ) -> list[OrdStockout]:
        """按异常单批量回写策略链结果（FR-04b）

        策略链是**异常单级**的动作（换仓重试 / 解除重审），但结果落在**缺货明细**
        上（每条明细的策略状态）→ 统一回写该单的全部明细。
        """
        rows = list(
            await self.s.scalars(
                select(OrdStockout).where(
                    OrdStockout.abnormal_id == abnormal_id,
                    OrdStockout.is_deleted == 0,
                )
            )
        )
        for r in rows:
            r.strategy_status = status
            if result is not None:
                r.strategy_result = result
            r.version += 1
        await self.s.commit()
        return rows

    async def get(self, abnormal_id: int) -> OrdAbnormal:
        row = await self.s.scalar(
            select(OrdAbnormal).where(
                OrdAbnormal.id == abnormal_id, OrdAbnormal.is_deleted == 0
            )
        )
        if row is None:
            raise NotFoundError(f"异常单不存在: {abnormal_id}")
        return row

    async def list_abnormals(
        self,
        *,
        status: str | None = None,
        exc_type: str | None = None,
        exc_category: str | None = None,
        order_id: int | None = None,
        shop_id: int | None = None,
        group_id: int | None = None,
        keyword: str | None = None,
        only_open: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[OrdAbnormal], int]:
        """异常单列表（FR-02f：按类型/状态/店铺/处理组过滤 + 分页）"""
        stmt = select(OrdAbnormal).where(OrdAbnormal.is_deleted == 0)
        if status:
            stmt = stmt.where(OrdAbnormal.status == status)
        if exc_type:
            stmt = stmt.where(OrdAbnormal.exc_type == exc_type)
        if exc_category:
            stmt = stmt.where(OrdAbnormal.exc_category == exc_category)
        if order_id:
            stmt = stmt.where(OrdAbnormal.order_id == order_id)
        if shop_id:
            stmt = stmt.where(OrdAbnormal.shop_id == shop_id)
        if group_id:
            stmt = stmt.where(OrdAbnormal.group_id == group_id)
        if only_open:
            stmt = stmt.where(OrdAbnormal.status.notin_(CLOSED_STATUSES))
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                OrdAbnormal.abnormal_bn.like(like) | OrdAbnormal.order_bn.like(like)
            )
        total = await self.s.scalar(
            select(func.count()).select_from(stmt.subquery())
        )
        rows = await self.s.scalars(
            stmt.order_by(OrdAbnormal.id.desc()).limit(limit).offset(offset)
        )
        return list(rows), int(total or 0)

    async def sla_status(self, row: OrdAbnormal) -> dict:
        """SLA 状态（FR-01a：默认 SLA 小时 → 是否超时 / 剩余小时）"""
        now = utcnow()
        deadline = row.sla_deadline
        if deadline is None:
            return {"deadline": None, "overdue": False, "remain_hours": None}
        remain = (deadline - now).total_seconds() / 3600
        return {
            "deadline": deadline.strftime("%Y-%m-%d %H:%M:%S"),
            "overdue": remain < 0 and row.status not in CLOSED_STATUSES,
            "remain_hours": round(remain, 2),
        }
