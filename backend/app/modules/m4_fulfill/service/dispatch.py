"""分派服务（D03.03 FR-02：多维规则分派 + 负载均衡）

**分派流程**（SRS-D03.03 §5.1）：
```
dispatch(order, reasonCodes):
    if order.assign_op and config.keep_on_reentry: return 原审核员   # 连续性优先
    rule = DispatchRuleCache.match(order, reasonCodes)              # weight DESC 首命中
    group = rule?.group ?? ReasonGroupMap(reasonCodes) ?? DEFAULT_GROUP
    candidates = group.members.filter(在班 and 持有量<上限 and 数据权限覆盖)
    if candidates.empty:
        assignToPool(group); alert(组长); return
    op = (轮询) ? rrNext(group, candidates) : minBy(candidates, 持有量)
    assign(order, group, op)
```

**负载策略**（FR-02b）：
- round_robin：Redis 指针原子推进（INCR）
- least_task：持有未处理单数最小者（并列取工号小者，保证稳定）

参考实现溯源：商派 `omeauto_auto_dispatch::getAutoDispatchUser` 静态指组/指人。
本模块升级为「多维规则 + 负载均衡 + 公共池兜底」。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.rule_engine import ConditionGroup, evaluate
from app.models.audit import OrdAuditGroup, OrdAuditTask, OrdDispatchRule
from app.models.order import OrdOrder

logger = get_logger("dispatch")

#: SLA 分级时限（FR-02/§5.2：缺货类 24h / 地址类 4h / 默认 8h，可配）
SLA_HOURS: dict[str, int] = {
    "STOCK_SHORTAGE": 24,
    "STOCK_RACE": 24,
    "ADDRESS_INVALID": 4,
    "ADDRESS_FORBIDDEN": 4,
    "ADDRESS_FAKE": 4,
}
DEFAULT_SLA_HOURS = 8

#: 成员默认任务上限（FR-02b）
DEFAULT_TASK_LIMIT = 50

#: 审核组默认名（无规则命中且原因码无组建议时）
DEFAULT_GROUP_NAME = "默认审核组"


@dataclass
class Member:
    """审核组成员"""

    op_id: int
    name: str = ""
    duty_status: str = "on"          # on=在班 / off=离班 / leave=请假
    task_limit: int = DEFAULT_TASK_LIMIT
    skill_tags: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Member:
        # task_limit 显式给 0 时表示「不接受任何任务」（测试用），不能被默认值覆盖
        raw_limit = d.get("task_limit")
        limit = DEFAULT_TASK_LIMIT if raw_limit is None else int(raw_limit)
        return cls(
            op_id=int(d.get("op_id", 0) or 0),
            name=str(d.get("name", "") or ""),
            duty_status=str(d.get("duty_status", "on") or "on"),
            task_limit=limit,
            skill_tags=list(d.get("skill_tags", []) or []),
        )


@dataclass
class DispatchResult:
    """分派结果"""

    order_id: int
    task_id: int | None = None
    assign_group: int | None = None
    assign_op: int | None = None
    #: 落公共池 / 命中规则 / 无规则
    route: str = ""
    reason: str = ""
    rule_id: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "task_id": self.task_id,
            "assign_group": self.assign_group,
            "assign_op": self.assign_op,
            "route": self.route,
            "reason": self.reason,
            "rule_id": self.rule_id,
        }


class DispatchService:
    """分派服务"""

    def __init__(self, session: AsyncSession, redis: Redis):
        self.s = session
        self.r = redis

    # ---------- 规则匹配 ----------

    async def match_rule(
        self, order: OrdOrder, reason_codes: list[str]
    ) -> tuple[OrdDispatchRule | None, list[dict[str, Any]]]:
        """分派规则匹配（weight DESC 首个全命中；条件维度含原因码）"""
        dims = {
            "shop_id": [order.shop_id],
            "brand_id": [order.brand_id],
            "owner_id": [order.owner_id],
            "platform": [order.createway],
            "order.amount_paid": float(order.paid_amount),
            "order_type": [order.order_type],
            "reason_code": list(reason_codes),
            "order.has_memo": bool(order.buyer_memo),
        }
        rows = list(
            await self.s.scalars(
                select(OrdDispatchRule)
                .where(
                    OrdDispatchRule.is_deleted == 0,
                    OrdDispatchRule.status == "enabled",
                )
                .order_by(OrdDispatchRule.weight.desc(), OrdDispatchRule.id.asc())
            )
        )
        for rule in rows:
            group = ConditionGroup.from_dict(rule.conditions)
            if not group.items:
                continue
            if evaluate(group, dims).hit:
                return rule, []
        return None, []

    # ---------- 审核组与候选 ----------

    async def _group(self, group_id: int) -> OrdAuditGroup | None:
        return await self.s.scalar(
            select(OrdAuditGroup).where(
                OrdAuditGroup.id == group_id, OrdAuditGroup.is_deleted == 0
            )
        )

    async def _default_group(self) -> OrdAuditGroup | None:
        return await self.s.scalar(
            select(OrdAuditGroup)
            .where(OrdAuditGroup.is_deleted == 0, OrdAuditGroup.status == "enabled")
            .order_by(OrdAuditGroup.id)
            .limit(1)
        )

    async def _members(self, group: OrdAuditGroup) -> list[Member]:
        raw = group.members or []
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except (TypeError, ValueError):
                raw = []
        if isinstance(raw, dict):
            raw = [raw]
        return [Member.from_dict(m) for m in raw if isinstance(m, dict)]

    async def _load_counts(self, op_ids: list[int]) -> dict[int, int]:
        """各审核员当前持有未处理单数（负载均衡依据）"""
        if not op_ids:
            return {}
        rows = await self.s.execute(
            select(OrdAuditTask.assign_op, func.count(OrdAuditTask.id))
            .where(
                OrdAuditTask.assign_op.in_(op_ids),
                OrdAuditTask.is_active == 1,
                OrdAuditTask.task_status.notin_(["done", "rejected", "closed"]),
            )
            .group_by(OrdAuditTask.assign_op)
        )
        return {int(op_id): int(cnt) for op_id, cnt in rows.all() if op_id}

    async def _pick_member(
        self, group: OrdAuditGroup, strategy: str, filter_on_duty: bool
    ) -> tuple[Member | None, str]:
        """组内选人（FR-02b：候选过滤 + 负载策略）"""
        members = await self._members(group)
        if not members:
            return None, "组内无成员"
        counts = await self._load_counts([m.op_id for m in members])
        candidates: list[Member] = []
        for m in members:
            if filter_on_duty and m.duty_status != "on":
                continue
            if counts.get(m.op_id, 0) >= m.task_limit:
                continue
            candidates.append(m)
        if not candidates:
            return None, "全员满载或不在班"
        if strategy == "round_robin":
            # Redis 指针原子推进（FR-02b）
            key = f"dispatch:rr:{group.id}"
            ptr = await self.r.incr(key)
            idx = (int(ptr) - 1) % len(candidates)
            return candidates[idx], ""
        # least_task：持有量最小者，并列取工号小者（稳定）
        candidates.sort(key=lambda m: (counts.get(m.op_id, 0), m.op_id))
        return candidates[0], ""

    # ---------- 自动分派 ----------

    async def auto(
        self, order_id: int, reason_codes: list[str]
    ) -> DispatchResult:
        """自动分派（IF-D03.03-01；幂等：已分派跳过）"""
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id, OrdOrder.is_deleted == 0)
        )
        if order is None:
            from app.core.exceptions import NotFoundError

            raise NotFoundError(f"订单不存在: {order_id}")
        # 幂等：已有活跃任务 → 跳过
        existing = await self.s.scalar(
            select(OrdAuditTask)
            .where(OrdAuditTask.order_id == order_id, OrdAuditTask.is_active == 1)
            .limit(1)
        )
        if existing is not None:
            return DispatchResult(
                order_id=order_id,
                task_id=existing.id,
                assign_group=existing.assign_group,
                assign_op=existing.assign_op,
                route="already_assigned",
                reason="已有活跃任务，幂等跳过",
            )

        rule, _ = await self.match_rule(order, reason_codes)
        group: OrdAuditGroup | None = None
        route = ""
        if rule is not None:
            group = await self._group(rule.target_group_id)
            route = "rule"
        if group is None:
            # 原因码 → 审核组建议映射（FR-02f）
            group = await self._group_by_reason(reason_codes)
            route = "reason_group" if group is not None else ""
        if group is None:
            group = await self._default_group()
            route = "default_group" if group is not None else route
        if group is None:
            return DispatchResult(
                order_id=order_id, route="no_group", reason="无可用审核组"
            )

        strategy = rule.strategy if rule is not None else "least_task"
        filter_on_duty = bool(rule.filter_on_duty) if rule is not None else True
        member, why = await self._pick_member(group, strategy, filter_on_duty)

        task = self._new_task(order, group, member, route)
        if member is None:
            # 全员满载 → 落组公共池（FR-02b）+ 告警组长
            task.assign_way = "pool"
            self.s.add(task)
            await self.s.commit()
            logger.warning(
                "dispatch_pool", detail=why, group_id=group.id, order_id=order_id
            )
            return DispatchResult(
                order_id=order_id,
                task_id=task.id,
                assign_group=group.id,
                assign_op=None,
                route="pool",
                reason=why,
                rule_id=rule.id if rule else 0,
            )

        task.assign_op = member.op_id
        task.assign_way = "rule" if route == "rule" else "auto"
        self.s.add(task)
        await self.s.commit()
        return DispatchResult(
            order_id=order_id,
            task_id=task.id,
            assign_group=group.id,
            assign_op=member.op_id,
            route=route,
            rule_id=rule.id if rule else 0,
        )

    async def _group_by_reason(
        self, reason_codes: list[str]
    ) -> OrdAuditGroup | None:
        """原因码 → 审核组建议映射（FR-02f 兜底）"""
        from app.core.dicts import DICTS

        groups = list(
            await self.s.scalars(
                select(OrdAuditGroup).where(
                    OrdAuditGroup.is_deleted == 0, OrdAuditGroup.status == "enabled"
                )
            )
        )
        if not groups:
            return None
        for code in reason_codes:
            item = DICTS.get("audit_reason_code", code)
            if item is None or not item.audit_group:
                continue
            for g in groups:
                if g.group_name == item.audit_group:
                    return g
        return None

    def _new_task(
        self,
        order: OrdOrder,
        group: OrdAuditGroup,
        member: Member | None,
        route: str,
    ) -> OrdAuditTask:
        """建审单任务（SLA 分级时限）"""
        now = datetime.now()
        return OrdAuditTask(
            owner_id=order.owner_id,
            order_id=order.id,
            batch_no=order.batch_no,
            assign_group=group.id,
            assign_op=member.op_id if member else None,
            assign_time=now,
            assign_way="rule" if route == "rule" else "auto",
            task_status="assigned" if member else "wait_assign",
            sla_deadline=now + timedelta(hours=DEFAULT_SLA_HOURS),
            shop_id=order.shop_id,
            is_active=1,
        )

    async def set_sla_by_reasons(self, task: OrdAuditTask, reason_codes: list[str]) -> None:
        """按原因码分级设定 SLA（缺货类 24h / 地址类 4h / 默认 8h）"""
        hours = DEFAULT_SLA_HOURS
        for code in reason_codes:
            if code in SLA_HOURS:
                hours = SLA_HOURS[code]
                break
        task.sla_deadline = datetime.now() + timedelta(hours=hours)

    # ---------- 手动指派/转派/回收（FR-02d） ----------

    async def assign(
        self,
        task_ids: list[int],
        target_op: int | None,
        target_group: int | None,
        operator: int | None,
        *,
        reason: str = "",
    ) -> int:
        """手动指派/转派/回收（全部留痕）"""
        from app.models.audit import OrdAuditWorkLog

        n = 0
        for tid in task_ids:
            task = await self.s.scalar(
                select(OrdAuditTask).where(OrdAuditTask.id == tid, OrdAuditTask.is_active == 1)
            )
            if task is None:
                continue
            from_op = task.assign_op
            task.assign_op = target_op
            if target_group:
                task.assign_group = target_group
            task.assign_way = "manual"
            task.assign_time = datetime.now()
            task.task_status = "assigned" if target_op else "wait_assign"
            self.s.add(
                OrdAuditWorkLog(
                    order_id=task.order_id,
                    task_id=task.id,
                    op_id=operator,
                    action="assign",
                    from_op=from_op,
                    to_op=target_op,
                    memo=reason,
                )
            )
            n += 1
        await self.s.commit()
        return n
