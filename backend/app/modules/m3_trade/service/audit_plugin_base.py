"""M3 审单插件基类与链定义"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.plugin_chain import (
    RuleContext,
)
from app.core.rule_engine import register_dimensions  # noqa: F401  （维度字典在 audit_rule.py 注册）

#: 插件链 ID
CHAIN_ID = "order.audit"

#: 段序（FR-01b：段间顺序不可调，依赖关系固定）
PHASES = [
    ("ADMIT", True),        # 准入：任一 HOLD 短路
    ("WAREHOUSE", True),    # 仓：选仓/拆单
    ("STOCK", True),        # 库存校验
    ("LOGISTICS", True),    # 物流匹配
    ("CHECK", False),       # 校验类：不短路（跑完收集全部原因）
]

@dataclass
class SplitGroup:
    """拆单组（发货单维度）"""

    group_key: str
    branch_id: int
    owner_id: int
    #: [(行 ID, 数量, 基础物料 ID, 货号)]
    lines: list[tuple[int, int, int, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_key": self.group_key,
            "branch_id": self.branch_id,
            "owner_id": self.owner_id,
            "lines": [
                {"item_id": i, "nums": n, "bm_id": bm, "material_bn": bn}
                for i, n, bm, bn in self.lines
            ],
        }

class BasePlugin:
    """插件基类（统一 name/phase/order 接口）"""

    PLUGIN_NAME = ""
    PHASE = ""
    ORDER = 100

    def name(self) -> str:
        return self.PLUGIN_NAME

    def phase(self) -> str:
        return self.PHASE

    def order(self) -> int:
        return self.ORDER

    def params(self, ctx: RuleContext) -> dict[str, Any]:
        """插件参数（FR-01d：规则 plugin_config 覆盖 + 全局默认）"""
        cfg = ctx.meta.get("plugin_params", {}).get(self.PLUGIN_NAME, {})
        return {**self.default_params(), **(cfg.get("params") or {})}

    def default_params(self) -> dict[str, Any]:
        return {}
