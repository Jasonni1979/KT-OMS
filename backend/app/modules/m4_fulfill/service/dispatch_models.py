"""M4 调度数据契约 —— 候选仓/调度结果/策略与失败码"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

MODE_SINGLE = "single"        # 整仓

MODE_MULTI = "multi"          # 多仓（需拆单）

MODE_LACK = "lack"            # 缺货

MODE_APPOINTED = "appointed"  # 平台指定仓

STRATEGY_BINDING_PRIORITY = "binding_priority"

STRATEGY_REGION_ROUTE = "region_route"

STRATEGY_STOCK_DEPTH = "stock_depth"

STRATEGY_OWNER_ASSIGN = "owner_assign"

STRATEGY_ROUND_ROBIN = "round_robin"  # P1 预留

FAIL_NO_CANDIDATE_BRANCH = "NO_CANDIDATE_BRANCH"

FAIL_PARTIAL_LACK = "PARTIAL_LACK"

FAIL_FULL_LACK = "FULL_LACK"

@dataclass
class BranchCandidate:
    """候选仓（D03.06 FR-01a）"""

    branch_id: int
    branch_name: str = ""
    priority: int = 999
    #: 来源：platform/owner/shop/region/fallback
    source: str = "shop"
    #: 行级限定（该仓只服务指定货主）
    owner_ids: list[int] = field(default_factory=list)
    region_code: str = ""
    #: 满足度（FR-03a）
    fulfill_rate: float = 0.0
    available_map: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch_id": self.branch_id,
            "branch_name": self.branch_name,
            "priority": self.priority,
            "source": self.source,
            "owner_ids": list(self.owner_ids),
            "region_code": self.region_code,
            "fulfill_rate": round(self.fulfill_rate, 4),
            "available_map": dict(self.available_map),
        }

@dataclass
class DispatchResult:
    """分仓结果"""

    ok: bool
    mode: str = MODE_SINGLE
    #: 行级分配 {order_item_id: {branch_id: qty}}
    alloc: dict[int, dict[int, int]] = field(default_factory=dict)
    candidates: list[BranchCandidate] = field(default_factory=list)
    fulfill_snapshot: dict[str, Any] = field(default_factory=dict)
    lack_detail: dict[str, Any] = field(default_factory=dict)
    rule_hit: dict[str, Any] = field(default_factory=dict)
    fail_code: str = ""
    fail_message: str = ""
    split_required: bool = False
    lack_route: str = ""
    plan_id: int = 0
    round_no: int = 0
    cost_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "alloc": {str(k): v for k, v in self.alloc.items()},
            "candidates": [c.to_dict() for c in self.candidates],
            "fulfill_snapshot": self.fulfill_snapshot,
            "lack_detail": self.lack_detail,
            "rule_hit": self.rule_hit,
            "fail_code": self.fail_code,
            "fail_message": self.fail_message,
            "split_required": self.split_required,
            "lack_route": self.lack_route,
            "plan_id": self.plan_id,
            "round_no": self.round_no,
            "cost_ms": self.cost_ms,
        }

def period_match(
    effective: Any, exclude: Any, now: datetime
) -> bool:
    """时间窗匹配（生效窗口内且不在排除窗口内）"""
    if exclude and _in_window(exclude, now):
        return False
    if effective and not _in_window(effective, now):
        return False
    return True

def _in_window(spec: Any, now: datetime) -> bool:
    """时间窗判定（支持 {"start":"23:00","end":"02:00"} 跨零点）"""
    if not spec:
        return False
    data: dict[str, Any] = spec if isinstance(spec, dict) else {}
    start = str(data.get("start", "") or "")
    end = str(data.get("end", "") or "")
    if not start or not end:
        return False
    cur = now.strftime("%H:%M")
    if start <= end:
        return start <= cur <= end
    # 跨零点
    return cur >= start or cur <= end
