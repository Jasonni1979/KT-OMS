"""M3 审单上下文与结果模型（审单引擎的数据契约）"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.plugin_chain import (
    LEVEL_BLOCK,
    Reason,
)
from app.modules.m3_trade.service.audit_rule import AuditRule


@dataclass
class AuditOutcome:
    """审单结果"""

    order_id: int
    order_bn: str
    batch_no: str
    #: 决策结果：auto_pass / manual / shortage / retrial / pool
    decision: str
    #: 是否产出 plan
    plan_id: int | None = None
    plan_bn: str = ""
    #: 结构化原因
    reasons: list[Reason] = field(default_factory=list)
    #: 插件 trace
    traces: list[dict[str, Any]] = field(default_factory=list)
    #: 命中的规则
    rule_id: int = 0
    rule_name: str = ""
    rule_snapshot_id: str = ""
    #: 决策上下文（plan 四要素）
    decision_ctx: dict[str, Any] = field(default_factory=dict)
    cost_ms: int = 0

    @property
    def blocked(self) -> bool:
        return any(r.level == LEVEL_BLOCK for r in self.reasons)

    @property
    def reason_codes(self) -> list[str]:
        return [r.code for r in self.reasons]

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "order_bn": self.order_bn,
            "batch_no": self.batch_no,
            "decision": self.decision,
            "plan_id": self.plan_id,
            "plan_bn": self.plan_bn,
            "reasons": [r.to_dict() for r in self.reasons],
            "traces": self.traces,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "rule_snapshot_id": self.rule_snapshot_id,
            "decision_ctx": self.decision_ctx,
            "cost_ms": self.cost_ms,
        }

@dataclass
class AuditContextData:
    """审单上下文装载结果（只读数据袋 + 元信息）"""

    order: dict[str, Any]
    items: list[dict[str, Any]]
    receiver: dict[str, Any]
    #: 规则匹配用维度上下文
    dims: dict[str, Any]
    #: 插件用元信息（候选仓/物流/黑名单等）
    meta: dict[str, Any]

def _num(v: Any) -> float:
    """数值兜底（可空列 → 0.0）

    ⚠ `weight` / `tax_amount` 在 DDL 里是**可空列**（is_nullable=YES），
    直接 `float(it.weight)` 遇 NULL 会抛 TypeError → 整个审单链路 500。
    """
    if v is None:
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0

def _plugin_params(rule: AuditRule) -> dict[str, Any]:
    """从规则 plugin_config 提取插件参数（FR-01d）"""
    out: dict[str, Any] = {}
    for name, cfg in (rule.plugin_config or {}).items():
        if isinstance(cfg, dict) and cfg.get("params"):
            out[name] = {"params": cfg["params"]}
    return out
