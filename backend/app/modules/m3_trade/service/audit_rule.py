"""审单规则服务（D03.02 FR-03：规则三层模型 + 命中逻辑 + 静态缓存）

**规则三层结构**（FR-03a）：
- 条件层：conditions（18 维 DSL JSON，AND 组合；同维度多值 OR）
- 插件层：plugin_config（逐插件 enable/params 覆盖）
- 动作层：auto_confirm / pass_action / fail_route / effective_window / exclude_window

**命中逻辑**（FR-03b）：
- 规则按 weight DESC 排序（同 weight 按 id ASC）
- 订单组匹配**第一个全条件命中**的规则
- 无命中 → 系统内置缺省规则兜底（auto_confirm=0，全转人工）
- 组内订单命中不同规则时按「组内最低 autoConfirm 权限」执行（冲突时拆组独立审）

**时间窗**（FR-03a 动作层 + SC-07）：
- exclude_window 命中 → autoConfirm 被压制（决策照跑，通过动作降级为转人工）
- effective_window 未命中 → 规则不生效

参考实现溯源：商派 `sdb_omeauto_order_type` LEFT JOIN `autoconfirm`（17 维分组条件 +
weight DESC 首命中 + defaulted 缺省兜底 + confirmStartTime/excludeStartTime 时间窗）。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rule_engine import ConditionGroup, DimensionSpec, evaluate, register_dimensions
from app.models.audit import OrdAuditRule

#: 审单规则维度字典（FR-03a 18 维中的核心子集；维度取值由上下文装载注入）
AUDIT_DIM_GROUP = "order.audit"

register_dimensions(
    AUDIT_DIM_GROUP,
    [
        DimensionSpec("shop_id", "set", "店铺", "ref:gw_shop"),
        DimensionSpec("brand_id", "set", "品牌", "ref:inv_brand"),
        DimensionSpec("owner_id", "set", "货主", "ref:org_owner"),
        DimensionSpec("platform", "set", "平台", "enum:platform"),
        DimensionSpec("order.amount_paid", "number", "客户实付金额", "order.paid_amount"),
        DimensionSpec("order.amount_list", "number", "订单原价", "order.list_amount"),
        DimensionSpec("order_type", "set", "订单类型", "enum:order_type"),
        DimensionSpec("order.items.category", "set", "商品类目", "enum:material_category"),
        DimensionSpec("order.items.sku", "set", "SKU", "order_item.platform_sku_code"),
        DimensionSpec("order.items.material_type", "set", "物料类型", "enum:material_type"),
        DimensionSpec("order.items.count", "number", "SKU 种类数", "computed"),
        DimensionSpec("order.items.nums", "number", "明细件数", "computed"),
        DimensionSpec("order.weight", "number", "订单重量", "computed"),
        DimensionSpec("order.is_cod", "bool", "货到付款", "order.is_cod"),
        DimensionSpec("order.receiver_province", "set", "收货省份", "receiver.province"),
        DimensionSpec("order.receiver_city", "set", "收货城市", "receiver.city"),
        DimensionSpec("order.has_memo", "bool", "有无买家留言", "order.buyer_memo"),
        DimensionSpec("order.buyer_tag", "set", "买家标签", "order.platform_extra"),
        DimensionSpec("order.createway", "set", "下单来源", "order.createway"),
        DimensionSpec("order.router_num", "number", "路由次数", "order_extend.router_num"),
    ],
)


@dataclass
class TimeWindow:
    """时间窗（生效/排除时段）

    形如：`{"start": "09:00", "end": "23:00"}` 或 `{"days": [1,2,3], "start": ..., "end": ...}`
    支持跨零点（start > end）。
    """

    start: str = ""
    end: str = ""
    days: list[int] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: Any) -> TimeWindow | None:
        if not d or not isinstance(d, dict):
            return None
        return cls(
            start=str(d.get("start", "") or ""),
            end=str(d.get("end", "") or ""),
            days=[int(x) for x in (d.get("days") or [])],
        )

    def matches(self, now: datetime | None = None) -> bool:
        """当前时刻是否落在窗内"""
        if not self.start or not self.end:
            return False
        now = now or datetime.now()
        if self.days and now.isoweekday() not in self.days:
            return False
        try:
            sh, sm = (int(x) for x in self.start.split(":"))
            eh, em = (int(x) for x in self.end.split(":"))
        except (ValueError, AttributeError):
            return False
        minutes = now.hour * 60 + now.minute
        begin, finish = sh * 60 + sm, eh * 60 + em
        if begin <= finish:
            return begin <= minutes <= finish
        return minutes >= begin or minutes <= finish


@dataclass
class AuditRule:
    """审单规则（内存态）"""

    id: int
    rule_name: str
    conditions: dict[str, Any]
    weight: int = 0
    plugin_config: dict[str, Any] = field(default_factory=dict)
    auto_confirm: bool = False
    pass_action: str = "exec_plan"
    fail_route: dict[str, Any] = field(default_factory=dict)
    effective_window: dict[str, Any] | None = None
    exclude_window: dict[str, Any] | None = None
    default_audit_group: int | None = None
    router_num_limit: int = 5
    status: str = "enabled"
    is_default: bool = False
    owner_id: int | None = None
    version: int = 0

    @classmethod
    def from_row(cls, row: OrdAuditRule) -> AuditRule:
        return cls(
            id=row.id,
            rule_name=row.rule_name,
            conditions=row.conditions or {},
            weight=row.weight,
            plugin_config=row.plugin_config or {},
            auto_confirm=bool(row.auto_confirm),
            pass_action=row.pass_action,
            fail_route=row.fail_route or {},
            effective_window=row.effective_window,
            exclude_window=row.exclude_window,
            default_audit_group=row.default_audit_group,
            router_num_limit=row.router_num_limit,
            status=row.status,
            is_default=bool(row.is_default),
            owner_id=row.owner_id,
            version=row.version,
        )

    # ---------- 命中与时间窗 ----------

    def matches(self, context: dict[str, Any]) -> bool:
        group = ConditionGroup.from_dict(self.conditions)
        if not group.items:
            return False
        return evaluate(group, context).hit

    def explain(self, context: dict[str, Any]) -> dict[str, Any]:
        """dry-run 用：逐项求值明细"""
        group = ConditionGroup.from_dict(self.conditions)
        return evaluate(group, context, explain=True).to_dict()

    def in_effective_window(self, now: datetime | None = None) -> bool:
        """生效时段：未配则恒生效"""
        w = TimeWindow.from_dict(self.effective_window)
        return True if w is None else w.matches(now)

    def in_exclude_window(self, now: datetime | None = None) -> bool:
        """排除时段：未配则恒不排除"""
        w = TimeWindow.from_dict(self.exclude_window)
        return False if w is None else w.matches(now)

    def auto_confirm_effective(self, now: datetime | None = None) -> bool:
        """autoConfirm 是否实际生效（排除时段压制 → 降级转人工，SC-07）"""
        return self.auto_confirm and not self.in_exclude_window(now)

    def degraded(self) -> AuditRule:
        """降级为转人工（时间窗压制时用）"""
        return AuditRule(
            id=self.id,
            rule_name=self.rule_name,
            conditions=self.conditions,
            weight=self.weight,
            plugin_config=self.plugin_config,
            auto_confirm=False,
            pass_action="manual_confirm",
            fail_route=self.fail_route,
            effective_window=self.effective_window,
            exclude_window=self.exclude_window,
            default_audit_group=self.default_audit_group,
            router_num_limit=self.router_num_limit,
            status=self.status,
            is_default=self.is_default,
            owner_id=self.owner_id,
            version=self.version,
        )

    def snapshot(self) -> str:
        """规则快照 ID（FR-05c：决策留痕引用，不受后续变更影响）"""
        payload = json.dumps(
            {
                "id": self.id,
                "name": self.rule_name,
                "conditions": self.conditions,
                "weight": self.weight,
                "plugin_config": self.plugin_config,
                "auto_confirm": self.auto_confirm,
                "pass_action": self.pass_action,
                "fail_route": self.fail_route,
                "effective_window": self.effective_window,
                "exclude_window": self.exclude_window,
                "default_audit_group": self.default_audit_group,
                "router_num_limit": self.router_num_limit,
                "version": self.version,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        import hashlib

        return hashlib.sha256(payload.encode()).hexdigest()[:32]


#: 缺省规则（系统内置，不可删不可停；autoConfirm=关，全转人工）
DEFAULT_RULE = AuditRule(
    id=0,
    rule_name="系统缺省规则（全部转人工）",
    conditions={},
    weight=-9999,
    auto_confirm=False,
    pass_action="manual_confirm",
    is_default=True,
)


class AuditRuleService:
    """审单规则服务（静态缓存 + 变更失效 + 降级查库）

    FR-06b：规则集静态缓存（启动全量加载进程内）；变更事件驱动增量重载；
    缓存加载失败降级实时查库并告警。
    """

    CACHE_TTL = 60.0  # 秒（FR-09b：广播丢失兜底=被动过期核对）

    def __init__(self) -> None:
        self._cache: list[AuditRule] = []
        self._loaded_at: float = 0.0
        self._dirty: bool = True

    async def load(self, session: AsyncSession, *, force: bool = False) -> int:
        """加载规则集到内存缓存"""
        if not force and not self._dirty and (time.monotonic() - self._loaded_at) < self.CACHE_TTL:
            return len(self._cache)
        rows = list(
            await session.scalars(
                select(OrdAuditRule)
                .where(OrdAuditRule.status == "enabled", OrdAuditRule.is_deleted == 0)
                .order_by(OrdAuditRule.weight.desc(), OrdAuditRule.id.asc())
            )
        )
        self._cache = [AuditRule.from_row(r) for r in rows]
        # 缺省规则兜底永远存在且排在最后
        if not any(r.is_default for r in self._cache):
            self._cache.append(DEFAULT_RULE)
        else:
            self._cache = [r for r in self._cache if not r.is_default] + [DEFAULT_RULE]
        self._loaded_at = time.monotonic()
        self._dirty = False
        return len(self._cache)

    def invalidate(self) -> None:
        """变更事件驱动失效（FR-06b/FR-09b）"""
        self._dirty = True

    def rules(self) -> list[AuditRule]:
        return self._cache

    def match(self, context: dict[str, Any], *, now: datetime | None = None) -> AuditRule:
        """规则匹配（FR-03b：weight DESC 首个全命中；无命中走缺省）"""
        for rule in self._cache:
            if rule.is_default:
                continue
            if not rule.in_effective_window(now):
                continue
            if rule.matches(context):
                return rule
        return DEFAULT_RULE

    def match_with_explain(
        self, context: dict[str, Any], *, now: datetime | None = None
    ) -> tuple[AuditRule, list[dict[str, Any]]]:
        """匹配 + 各规则求值明细（dry-run 报告）"""
        traces: list[dict[str, Any]] = []
        for rule in self._cache:
            if rule.is_default:
                continue
            detail = rule.explain(context)
            traces.append(
                {
                    "rule_id": rule.id,
                    "rule_name": rule.rule_name,
                    "hit": detail["hit"],
                    "in_effective_window": rule.in_effective_window(now),
                    "details": detail["details"],
                }
            )
            if detail["hit"] and rule.in_effective_window(now):
                return rule, traces
        return DEFAULT_RULE, traces

    def resolve_group_conflict(self, rules: list[AuditRule]) -> AuditRule:
        """组内规则冲突裁决（FR-03b §5.3：取组内最低 autoConfirm 权限）

        差异仅参数级（同 autoConfirm）→ 用组代表单规则；
        差异在 autoConfirm → 用最低权限（更保守）规则。
        """
        if not rules:
            return DEFAULT_RULE
        if len({r.auto_confirm for r in rules}) == 1:
            return rules[0]
        return min(rules, key=lambda r: (r.auto_confirm, -r.weight))
