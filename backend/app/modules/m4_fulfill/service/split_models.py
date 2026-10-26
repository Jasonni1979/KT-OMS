"""M4 拆单数据契约 —— 输入/分组/结果/失败码族"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

FAIL_NO_STOCK = "NO_STOCK"

FAIL_CONFIG_INVALID = "CONFIG_INVALID"

FAIL_PRECONDITION_UNMET = "PRECONDITION_UNMET"

FAIL_CONSERVATION_VIOLATION = "CONSERVATION_VIOLATION"

FAIL_STRATEGY_DISABLED = "STRATEGY_DISABLED"

FAIL_NO_ITEMS = "NO_ITEMS"

@dataclass
class SplitItem:
    """只读明细快照（§5.1 SplitInput.items）"""

    item_id: int
    bm_id: int = 0
    bm_number: str = ""
    bm_name: str = ""
    #: 未拆余量（= nums - split_num）
    nums: int = 0
    owner_id: int = 0
    #: 物料属性
    material_type: int = 0
    cat_id: int = 0
    weight: float = 0.0
    volume: float = 0.0
    is_virtual: int = 0
    is_gift: int = 0
    #: 平台子单号（order_host 策略）
    oid: str = ""
    #: 履约渠道
    channel: str = ""
    #: 借调标记：按记账货主分组（FR-05d）
    lend_flag: int = 0
    price: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "bm_id": self.bm_id,
            "bm_number": self.bm_number,
            "nums": self.nums,
            "owner_id": self.owner_id,
            "material_type": self.material_type,
            "cat_id": self.cat_id,
            "weight": self.weight,
            "volume": self.volume,
            "is_virtual": self.is_virtual,
            "is_gift": self.is_gift,
            "oid": self.oid,
            "channel": self.channel,
            "lend_flag": self.lend_flag,
        }

@dataclass
class SplitGroup:
    """分组（组 = 未来发货单）"""

    group_key: str
    #: [(订单行 ID, 分配数量)]
    lines: list[tuple[int, int]] = field(default_factory=list)
    #: 组属性 → 发货单字段（FR-03b）
    attrs: dict[str, Any] = field(default_factory=dict)

    def add(self, item_id: int, nums: int) -> None:
        self.lines.append((item_id, nums))

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_key": self.group_key,
            "items": [{"item_id": i, "nums": n} for i, n in self.lines],
            "attrs": dict(self.attrs),
        }

@dataclass
class SplitInput:
    """策略输入（§5.1）"""

    items: list[SplitItem] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.context.get(key, default)

@dataclass
class SplitResult:
    """策略输出（§5.1）"""

    groups: list[SplitGroup] = field(default_factory=list)
    fail_code: str = ""
    fail_detail: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.fail_code

    def to_dict(self) -> dict[str, Any]:
        return {
            "groups": [g.to_dict() for g in self.groups],
            "fail_code": self.fail_code,
            "fail_detail": self.fail_detail,
        }

@dataclass
class SplitOutcome:
    """拆单结果"""

    ok: bool
    groups: list[dict[str, Any]] = field(default_factory=list)
    fail_code: str = ""
    fail_detail: dict[str, Any] = field(default_factory=dict)
    trace_id: int = 0
    round_no: int = 0
    cost_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "groups": self.groups,
            "fail_code": self.fail_code,
            "fail_detail": self.fail_detail,
            "trace_id": self.trace_id,
            "round_no": self.round_no,
            "cost_ms": self.cost_ms,
        }

def dump_json(obj: Any) -> str:
    """调试用 JSON 序列化"""
    return json.dumps(obj, ensure_ascii=False, default=str)
