"""异常单扩展域服务（W9-2 · SRS-D03.09 FR-05b/FR-05c/FR-06/FR-07）

三块能力：

| 能力 | 条款 | 说明 |
|---|---|---|
| **超卖应急批次** | FR-05b~05e | 同店铺同 SKU 自动聚合；批次级统一决策；分级 SLA；复盘 |
| **订单暂停编排** | FR-06a~06e | 暂停/恢复逐发货单分布式动作；任一失败按整体失败；不半恢复；暂停期间约束 |
| **名单服务** | FR-07a~07d | 黑/灰/白名单；两层库（全局 + 租户/货主私有）；命中私有优先；增删改走审批留痕 |

⚠ **告警推送（D01.07 企微）为扩展位**：本期落「告警待发」记录 + 明确 `pending`，
不假装已推送（企微通道未实现）。
"""
from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.enums import ORD_OVERSOLD_BATCH_STAGE, ORD_RISK_LIST_LIST_TYPE
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.timeutil import utcnow
from app.models.abnormal import OrdAbnormal, OrdStockout
from app.models.abnormal_ext import (
    OrdOversoldBatch,
    OrdPauseCommandLog,
    OrdRiskList,
)
from app.models.order import OrdOrder

# ============ 应急批次枚举（DDL COMMENT 权威）============

STAGE_ALARM = "alarm"
STAGE_ALLOC_CALC = "alloc_calc"
STAGE_NEGOTIATE = "negotiate"
STAGE_REFUND = "refund"
STAGE_COMPENSATE = "compensate"
STAGE_REVIEW = "review"

BATCH_STAGE_LABEL = ORD_OVERSOLD_BATCH_STAGE

#: 阶段推进顺序（FR-05c 分级 SLA）
BATCH_STAGE_ORDER = (
    STAGE_ALARM,
    STAGE_ALLOC_CALC,
    STAGE_NEGOTIATE,
    STAGE_REFUND,
    STAGE_COMPENSATE,
    STAGE_REVIEW,
)

#: 分级 SLA（小时）—— 大促模式收紧（FR-05d：T+4h → T+2h）
SLA_HOURS = {
    STAGE_ALARM: 0,
    STAGE_ALLOC_CALC: 4,
    STAGE_NEGOTIATE: 24,
}
PROMO_SLA_HOURS = {
    STAGE_ALARM: 0,
    STAGE_ALLOC_CALC: 2,
    STAGE_NEGOTIATE: 24,
}

# ============ 名单枚举 ============

LIST_BLACK = "black"
LIST_GRAY = "gray"
LIST_WHITE = "white"

LIST_TYPE_LABEL = ORD_RISK_LIST_LIST_TYPE

DIM_MOBILE = "mobile"
DIM_ADDRESS = "address"
DIM_ACCOUNT = "account"
DIM_NAME = "name"

VALUE_PLAIN = "plain"
VALUE_HASH = "hash"

SCOPE_GLOBAL = "global"
SCOPE_TENANT = "tenant"
SCOPE_OWNER = "owner"


class AbnormalExtService:
    """异常单扩展域服务（W9-2）"""

    def __init__(self, session: AsyncSession, redis: Any = None) -> None:
        self.s = session
        self.r = redis

    # ============ FR-05b 超卖应急批次 ============

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

    # ============ FR-06 订单暂停编排 ============

    async def pause_order(
        self,
        order_id: int,
        *,
        reason: str,
        abnormal_id: int | None = None,
        operator: str = "system",
    ) -> dict[str, Any]:
        """订单暂停编排（FR-06a/06b：逐发货单处理）

        FR-06b 是**分布式动作**：逐发货单处理，任一失败按整体失败处理。
        本期按「订单置暂停 + 逐发货单记命令日志」实现（WMS 侧暂停报文
        属 D03.07/D09.02 范围，标记 pending 不伪造成功）。
        """
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id, OrdOrder.is_deleted == 0)
        )
        if order is None:
            raise NotFoundError(f"订单不存在: {order_id}")
        if order.fulfill_status == "aftersale":
            raise ConflictError(
                "订单处于售后中，暂停语义重叠，请先处理售后",
                code="ORDER_PAUSE_CONFLICT",
            )
        from app.models.fulfill import OrdDelivery

        deliveries = list(
            await self.s.scalars(
                select(OrdDelivery).where(
                    OrdDelivery.order_id == order_id, OrdDelivery.is_deleted == 0
                )
            )
        )
        # 订单置暂停
        order.fulfill_status = "paused"
        order.update_time = utcnow()
        order.version = int(order.version or 0) + 1
        results: list[dict[str, Any]] = []
        for d in deliveries:
            log = OrdPauseCommandLog(
                tenant_id=order.tenant_id,
                owner_id=order.owner_id,
                order_id=order_id,
                delivery_id=d.id,
                command="pause",
                # WMS 侧暂停报文未实现 → 记 pending（不算成功也不算失败）
                result="pending",
                abnormal_id=abnormal_id,
                operator=operator,
            )
            self.s.add(log)
            results.append(
                {"delivery_id": d.id, "result": "pending", "reason": "WMS 暂停报文待实现"}
            )
        await self.s.commit()
        return {
            "ok": True,
            "order_id": order_id,
            "paused": True,
            "deliveries": results,
            "all_done": all(r["result"] == "ok" for r in results) if results else True,
            "wms_pending": True,
            "note": reason,
        }

    async def resume_order(
        self, order_id: int, *, operator: str = "system"
    ) -> dict[str, Any]:
        """订单恢复编排（FR-06c：逐发货单重推指令）

        ⚠ **不半恢复**：任一发货单恢复失败 → 订单保持暂停（FR-06c）。
        """
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id, OrdOrder.is_deleted == 0)
        )
        if order is None:
            raise NotFoundError(f"订单不存在: {order_id}")
        from app.models.fulfill import OrdDelivery

        deliveries = list(
            await self.s.scalars(
                select(OrdDelivery).where(
                    OrdDelivery.order_id == order_id, OrdDelivery.is_deleted == 0
                )
            )
        )
        results: list[dict[str, Any]] = []
        for d in deliveries:
            log = OrdPauseCommandLog(
                tenant_id=order.tenant_id,
                owner_id=order.owner_id,
                order_id=order_id,
                delivery_id=d.id,
                command="resume",
                result="pending",
                operator=operator,
            )
            self.s.add(log)
            results.append({"delivery_id": d.id, "result": "pending"})
        failed = [r for r in results if r["result"] == "fail"]
        if failed:
            # 不半恢复：保持暂停
            await self.s.commit()
            return {
                "ok": False,
                "order_id": order_id,
                "resumed": False,
                "deliveries": results,
                "reason": "任一发货单恢复失败 → 订单保持暂停（不半恢复）",
            }
        order.fulfill_status = "pending"
        order.update_time = utcnow()
        order.version = int(order.version or 0) + 1
        await self.s.commit()
        return {
            "ok": True,
            "order_id": order_id,
            "resumed": True,
            "deliveries": results,
        }

    async def list_pause_logs(self, order_id: int) -> list[dict[str, Any]]:
        """暂停命令日志（FR-06b 留痕）"""
        rows = list(
            await self.s.scalars(
                select(OrdPauseCommandLog)
                .where(OrdPauseCommandLog.order_id == order_id)
                .order_by(OrdPauseCommandLog.id)
            )
        )
        return [
            {
                "id": r.id,
                "order_id": r.order_id,
                "delivery_id": r.delivery_id,
                "command": r.command,
                "result": r.result,
                "fail_code": r.fail_code,
                "fail_reason": r.fail_reason,
                "abnormal_id": r.abnormal_id,
                "operator": r.operator,
                "create_time": r.create_time.strftime("%Y-%m-%d %H:%M:%S")
                if r.create_time
                else None,
            }
            for r in rows
        ]

    # ============ FR-07 名单服务 ============

    async def add_to_list(
        self,
        *,
        list_type: str,
        dimension: str,
        match_value: str,
        scope: str = SCOPE_TENANT,
        owner_id: int | None = None,
        value_type: str = VALUE_PLAIN,
        reason: str = "",
        source: str = "manual",
        oa_approval_id: str = "",
        effective_hours: int = 0,
    ) -> OrdRiskList:
        """加入名单（FR-07b：增删改走审批）

        ⚠ 加入**黑名单**必须带 OA 审批单号（FR-07b：加入黑名单推 OA）→
        缺失时拒绝。
        """
        if list_type not in LIST_TYPE_LABEL:
            raise ValidationError(f"非法名单类型: {list_type}")
        if dimension not in (DIM_MOBILE, DIM_ADDRESS, DIM_ACCOUNT, DIM_NAME):
            raise ValidationError(f"非法名单维度: {dimension}")
        if scope not in (SCOPE_GLOBAL, SCOPE_TENANT, SCOPE_OWNER):
            raise ValidationError(f"非法作用域: {scope}")
        if scope == SCOPE_OWNER and not owner_id:
            raise ValidationError("货主私有名单须填 owner_id")
        if list_type == LIST_BLACK and not oa_approval_id:
            raise ValidationError(
                "加入黑名单必须带 OA 审批单号（FR-07b）", code="RISK_LIST_OA_REQUIRED"
            )
        now = utcnow()
        row = OrdRiskList(
            tenant_id=1,
            owner_id=owner_id,
            list_type=list_type,
            dimension=dimension,
            match_value=match_value,
            value_type=value_type,
            scope=scope,
            effective_start=now,
            effective_end=(now + timedelta(hours=effective_hours))
            if effective_hours > 0
            else None,
            reason=reason,
            source=source,
            oa_approval_id=oa_approval_id,
            disabled=0,
            is_deleted=0,
        )
        self.s.add(row)
        await self.s.commit()
        await self.s.refresh(row)
        return row

    async def remove_from_list(
        self,
        list_id: int,
        *,
        oa_approval_id: str = "",
        operator: str = "system",
    ) -> bool:
        """移出名单（FR-07b：移出黑名单同样推 OA）"""
        row = await self.s.scalar(
            select(OrdRiskList).where(
                OrdRiskList.id == list_id, OrdRiskList.is_deleted == 0
            )
        )
        if row is None:
            raise NotFoundError(f"名单记录不存在: {list_id}")
        if row.list_type == LIST_BLACK and not oa_approval_id:
            raise ValidationError(
                "移出黑名单必须带 OA 审批单号（FR-07b）",
                code="RISK_LIST_OA_REQUIRED",
            )
        row.disabled = 1
        row.update_time = utcnow()
        await self.s.commit()
        return True

    async def match_list(
        self,
        *,
        dimension: str,
        match_value: str,
        owner_id: int | None = None,
        list_type: str | None = None,
    ) -> dict[str, Any]:
        """名单命中判定（FR-07c/07d：私有优先）

        优先级：货主私有 > 租户私有 > 全局基础库。
        命中动作：黑名单 → 异常单+复审单 / 灰名单 → 审单 HOLD 转人工（不生成异常单）/
        白名单 → 跳过对应校验。
        """
        now = utcnow()
        q = select(OrdRiskList).where(
            OrdRiskList.dimension == dimension,
            OrdRiskList.match_value == match_value,
            OrdRiskList.disabled == 0,
            OrdRiskList.is_deleted == 0,
            # 生效期间过滤**下推到 SQL**：
            # ⚠ 不能在 Python 里对 ORM 对象判断——对象可能是过期快照
            #   （同事务内 UPDATE 过但未 refresh）→ 读到旧的有效期 → 误命中
            or_(OrdRiskList.effective_start.is_(None), OrdRiskList.effective_start <= now),
            or_(OrdRiskList.effective_end.is_(None), OrdRiskList.effective_end >= now),
        )
        if list_type:
            q = q.where(OrdRiskList.list_type == list_type)
        rows = list(await self.s.scalars(q))
        valid = rows
        if not valid:
            return {"hit": False, "list_type": "", "action": "", "scope": ""}
        # 私有优先：owner > tenant > global
        priority = {SCOPE_OWNER: 0, SCOPE_TENANT: 1, SCOPE_GLOBAL: 2}
        if owner_id:
            valid = [
                r for r in valid if r.scope == SCOPE_OWNER and r.owner_id == owner_id
            ] or [r for r in valid if r.scope != SCOPE_OWNER]
        valid.sort(key=lambda r: priority.get(r.scope, 9))
        hit = valid[0]
        action = {
            LIST_BLACK: "abnormal_and_retrial",  # 异常单 + 复审单
            LIST_GRAY: "audit_hold",  # 审单 HOLD 转人工（不生成异常单）
            LIST_WHITE: "skip_check",  # 跳过对应校验
        }.get(hit.list_type, "")
        return {
            "hit": True,
            "list_type": hit.list_type,
            "list_type_name": LIST_TYPE_LABEL.get(hit.list_type, hit.list_type),
            "scope": hit.scope,
            "list_id": hit.id,
            "action": action,
            "reason": hit.reason,
        }

    async def list_entries(
        self,
        *,
        list_type: str | None = None,
        dimension: str | None = None,
        scope: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """名单列表（维护视图）"""
        q = select(OrdRiskList).where(OrdRiskList.is_deleted == 0)
        if list_type:
            q = q.where(OrdRiskList.list_type == list_type)
        if dimension:
            q = q.where(OrdRiskList.dimension == dimension)
        if scope:
            q = q.where(OrdRiskList.scope == scope)
        rows = list(await self.s.scalars(q.order_by(OrdRiskList.id.desc()).limit(limit)))
        return [
            {
                "id": r.id,
                "list_type": r.list_type,
                "list_type_name": LIST_TYPE_LABEL.get(r.list_type, r.list_type),
                "dimension": r.dimension,
                "match_value": r.match_value,
                "value_type": r.value_type,
                "scope": r.scope,
                "owner_id": r.owner_id,
                "reason": r.reason,
                "source": r.source,
                "oa_approval_id": r.oa_approval_id,
                "disabled": r.disabled,
                "effective_start": r.effective_start.strftime("%Y-%m-%d %H:%M:%S")
                if r.effective_start
                else None,
                "effective_end": r.effective_end.strftime("%Y-%m-%d %H:%M:%S")
                if r.effective_end
                else None,
            }
            for r in rows
        ]

    # ============ FR-08c 告警规则 ============

    async def scan_alerts(self) -> dict[str, Any]:
        """异常单告警扫描（FR-08c：类型级超期 + 数量突增）

        产出「告警待发」清单（企微推送 D01.07 未实现 → 明确 pending）。
        """
        rows = list(
            await self.s.scalars(
                select(OrdAbnormal).where(
                    OrdAbnormal.is_deleted == 0,
                    OrdAbnormal.status.notin_(
                        ("resolved", "cancelled")
                    ),
                )
            )
        )
        now = utcnow()
        overdue: list[dict[str, Any]] = []
        by_type_1h: dict[str, int] = {}
        for r in rows:
            if r.sla_deadline and r.sla_deadline < now:
                overdue.append(
                    {
                        "abnormal_id": r.id,
                        "abnormal_bn": r.abnormal_bn,
                        "exc_type": r.exc_type,
                        "order_bn": r.order_bn,
                        "sla_deadline": r.sla_deadline.strftime("%Y-%m-%d %H:%M:%S"),
                        "overdue_hours": round(
                            (now - r.sla_deadline).total_seconds() / 3600, 2
                        ),
                        "alert_type": "sla_overdue",
                        "push_status": "pending",
                    }
                )
            # 数量突增：1 小时内新增
            if r.create_time and (now - r.create_time).total_seconds() <= 3600:
                by_type_1h[r.exc_type] = by_type_1h.get(r.exc_type, 0) + 1
        surge = [
            {
                "exc_type": t,
                "count": c,
                "alert_type": "count_surge",
                "push_status": "pending",
            }
            for t, c in by_type_1h.items()
            if c >= 20
        ]
        return {"overdue": overdue, "surge": surge, "total": len(overdue) + len(surge)}
