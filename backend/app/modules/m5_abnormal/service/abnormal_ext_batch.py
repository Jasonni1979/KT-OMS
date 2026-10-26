"""AbnormalExtBatchMixin —— 由 AbnormalExtService 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.timeutil import utcnow
from app.models.abnormal import OrdAbnormal, OrdStockout
from app.models.abnormal_ext import (
    OrdOversoldBatch,
)
from app.modules.m5_abnormal.service.abnormal_ext_codes import (
    BATCH_STAGE_LABEL,
    BATCH_STAGE_ORDER,
    PROMO_SLA_HOURS,
    SLA_HOURS,
    STAGE_ALARM,
    STAGE_REVIEW,
)


class AbnormalExtBatchMixin:
    """AbnormalExtService 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Any

    async def aggregate_oversold_batch(
        self,
        *,
        shop_id: int,
        bm_id: int,
        owner_id: int,
        abnormal_ids: list[int],
    ) -> OrdOversoldBatch:
        """超卖单聚合为应急批次（FR-05b）

        聚合键 = 店铺 × 基础物料 × 货主。已存在未关闭批次则并入，
        否则新建（`OS+日期+序列`）。
        """
        if not abnormal_ids:
            raise ValidationError("超卖批次至少需要一个超卖单")
        existing = await self.s.scalar(
            select(OrdOversoldBatch).where(
                OrdOversoldBatch.shop_id == shop_id,
                OrdOversoldBatch.bm_id == bm_id,
                OrdOversoldBatch.owner_id == owner_id,
                OrdOversoldBatch.stage != STAGE_REVIEW,
                OrdOversoldBatch.is_deleted == 0,
            )
        )
        if existing is not None:
            existing.total_orders = int(existing.total_orders or 0) + len(abnormal_ids)
            existing.update_time = utcnow()
            existing.version = int(existing.version or 0) + 1
            await self.s.commit()
            await self.s.refresh(existing)
            return existing

        now = utcnow()
        row = OrdOversoldBatch(
            tenant_id=1,
            owner_id=owner_id,
            batch_bn=f"OS{now:%Y%m%d}{uuid.uuid4().hex[:6].upper()}",
            shop_id=shop_id,
            bm_id=bm_id,
            total_orders=len(abnormal_ids),
            resolved_orders=0,
            refund_orders=0,
            stage=STAGE_ALARM,
            stage_timeline={STAGE_ALARM: now.isoformat()},
            promo_mode=0,
            compensation=[],
            version=0,
            is_deleted=0,
        )
        self.s.add(row)
        await self.s.flush()
        # 批次内订单 → **缺货明细**回写批次引用
        # ⚠ 批次引用列在 `ord_stockout.batch_id`（DDL 权威），
        #   异常单表本身没有批次列 → 关联路径 = 异常单 → 缺货明细 → 批次
        from sqlalchemy import update

        await self.s.execute(
            update(OrdStockout)
            .where(OrdStockout.abnormal_id.in_(abnormal_ids))
            .values(batch_id=row.id)
        )
        await self.s.commit()
        await self.s.refresh(row)
        return row

    async def advance_batch(
        self, batch_id: int, to_stage: str, *, operator: str = "system"
    ) -> OrdOversoldBatch:
        """批次阶段推进（FR-05c：分级 SLA）

        合法推进按 `BATCH_STAGE_ORDER` 顺序；跳阶段拒绝。
        """
        row = await self.s.scalar(
            select(OrdOversoldBatch).where(
                OrdOversoldBatch.id == batch_id, OrdOversoldBatch.is_deleted == 0
            )
        )
        if row is None:
            raise NotFoundError(f"应急批次不存在: {batch_id}")
        if to_stage not in BATCH_STAGE_ORDER:
            raise ValidationError(f"非法批次阶段: {to_stage}")
        cur_idx = BATCH_STAGE_ORDER.index(row.stage)
        to_idx = BATCH_STAGE_ORDER.index(to_stage)
        if to_idx <= cur_idx:
            raise ConflictError(
                f"批次阶段不可从 {BATCH_STAGE_LABEL.get(row.stage)} "
                f"回退/重复到 {BATCH_STAGE_LABEL.get(to_stage)}",
                code="BATCH_STAGE_INVALID",
            )
        if to_idx > cur_idx + 1:
            raise ConflictError(
                f"批次阶段不可跳过中间阶段"
                f"（当前 {BATCH_STAGE_LABEL.get(row.stage)} → 目标 "
                f"{BATCH_STAGE_LABEL.get(to_stage)}）",
                code="BATCH_STAGE_SKIPPED",
            )
        now = utcnow()
        timeline = dict(row.stage_timeline or {})
        timeline[to_stage] = now.isoformat()
        row.stage = to_stage
        row.stage_timeline = timeline
        row.update_time = now
        row.version = int(row.version or 0) + 1
        await self.s.commit()
        await self.s.refresh(row)
        return row

    async def batch_sla_status(self, batch_id: int) -> dict[str, Any]:
        """批次 SLA 状态（FR-05c：按阶段到达时间算剩余/超期）

        大促模式（promo_mode=1）用收紧后的 SLA。
        """
        row = await self.s.scalar(
            select(OrdOversoldBatch).where(
                OrdOversoldBatch.id == batch_id, OrdOversoldBatch.is_deleted == 0
            )
        )
        if row is None:
            raise NotFoundError(f"应急批次不存在: {batch_id}")
        sla_map = PROMO_SLA_HOURS if int(row.promo_mode or 0) else SLA_HOURS
        timeline = row.stage_timeline if isinstance(row.stage_timeline, dict) else {}
        now = utcnow()
        stages: list[dict[str, Any]] = []
        overdue_stage = ""
        for st, hours in sla_map.items():
            at = timeline.get(st)
            if not at:
                continue
            from datetime import datetime

            try:
                arrive = datetime.fromisoformat(str(at))
            except ValueError:
                continue
            deadline = arrive + timedelta(hours=hours)
            remain = (deadline - now).total_seconds() / 3600
            over = remain < 0
            if over and not overdue_stage:
                overdue_stage = st
            stages.append(
                {
                    "stage": st,
                    "stage_name": BATCH_STAGE_LABEL.get(st, st),
                    "arrive_at": at,
                    "sla_hours": hours,
                    "deadline": deadline.strftime("%Y-%m-%d %H:%M:%S"),
                    "remain_hours": round(remain, 2),
                    "overdue": over,
                }
            )
        return {
            "batch_id": batch_id,
            "stage": row.stage,
            "stage_name": BATCH_STAGE_LABEL.get(row.stage, row.stage),
            "promo_mode": int(row.promo_mode or 0),
            "total_orders": int(row.total_orders or 0),
            "resolved_orders": int(row.resolved_orders or 0),
            "refund_orders": int(row.refund_orders or 0),
            "stages": stages,
            "overdue_stage": overdue_stage,
            "overdue": bool(overdue_stage),
        }

    async def set_promo_mode(
        self, batch_id: int, *, promo: bool, operator: str = "system"
    ) -> OrdOversoldBatch:
        """大促模式开关（FR-05d：SLA 收紧 + 告警升级）"""
        row = await self.s.scalar(
            select(OrdOversoldBatch).where(
                OrdOversoldBatch.id == batch_id, OrdOversoldBatch.is_deleted == 0
            )
        )
        if row is None:
            raise NotFoundError(f"应急批次不存在: {batch_id}")
        row.promo_mode = 1 if promo else 0
        row.update_time = utcnow()
        row.version = int(row.version or 0) + 1
        await self.s.commit()
        await self.s.refresh(row)
        return row

    async def register_compensation(
        self,
        batch_id: int,
        *,
        order_id: int,
        comp_type: str,
        amount: float,
        liability: str = "",
        oa_approval_id: str = "",
    ) -> OrdOversoldBatch:
        """赔付登记（FR-05e：赔付金额入批次台账）"""
        row = await self.s.scalar(
            select(OrdOversoldBatch).where(
                OrdOversoldBatch.id == batch_id, OrdOversoldBatch.is_deleted == 0
            )
        )
        if row is None:
            raise NotFoundError(f"应急批次不存在: {batch_id}")
        comp = list(row.compensation or [])
        comp.append(
            {
                "order_id": order_id,
                "type": comp_type,
                "amount": amount,
                "liability": liability,
                "oa_approval_id": oa_approval_id,
                "at": utcnow().isoformat(),
            }
        )
        row.compensation = comp
        row.update_time = utcnow()
        row.version = int(row.version or 0) + 1
        await self.s.commit()
        await self.s.refresh(row)
        return row

    async def close_batch_review(self, batch_id: int) -> dict[str, Any]:
        """批次关闭复盘（FR-05e：生成复盘摘要）

        单量 / 解决路径分布 / 平均解决时长 / 赔付金额 / 根因标签。
        """
        row = await self.s.scalar(
            select(OrdOversoldBatch).where(
                OrdOversoldBatch.id == batch_id, OrdOversoldBatch.is_deleted == 0
            )
        )
        if row is None:
            raise NotFoundError(f"应急批次不存在: {batch_id}")
        comp = list(row.compensation or [])
        total_amount = sum(float(c.get("amount") or 0) for c in comp)
        # 解决路径分布：按批次内订单当前状态统计
        # （批次 → 缺货明细.batch_id → 异常单）
        rows = list(
            await self.s.scalars(
                select(OrdAbnormal)
                .join(OrdStockout, OrdStockout.abnormal_id == OrdAbnormal.id)
                .where(
                    OrdStockout.batch_id == batch_id,
                    OrdAbnormal.is_deleted == 0,
                )
                .distinct()
            )
        )
        by_status: dict[str, int] = {}
        durations: list[float] = []
        for a in rows:
            st = str(a.status or "")
            by_status[st] = by_status.get(st, 0) + 1
            if a.create_time and a.update_time:
                durations.append((a.update_time - a.create_time).total_seconds() / 3600)
        avg_hours = round(sum(durations) / len(durations), 2) if durations else 0.0
        summary = {
            "batch_id": batch_id,
            "batch_bn": row.batch_bn,
            "total_orders": int(row.total_orders or 0),
            "resolved_orders": int(row.resolved_orders or 0),
            "refund_orders": int(row.refund_orders or 0),
            "resolution_paths": by_status,
            "avg_resolve_hours": avg_hours,
            "compensation_total": round(total_amount, 2),
            "compensation_count": len(comp),
            "root_cause_tags": ["oversold"],
            "closed_at": utcnow().isoformat(),
        }
        await self.advance_batch(batch_id, STAGE_REVIEW, operator="system")
        return summary
