"""异常单分派规则引擎（FR-02c）

复用 D03.03 的 `ord_dispatch_rule` 规则表（不另建表），但**维度扩展**到异常单
需要的四个维度（FR-02c 原文：条件维度含异常类型/店铺/货主/品牌）：

| 维度 dim          | 说明                                              |
|-------------------|---------------------------------------------------|
| `exc_type`        | 异常类型（如 STOCK_SHORT / ADDR_INCOMPLETE）       |
| `shop_id`         | 店铺                                               |
| `owner_id`        | 货主                                               |
| `brand_id`        | 品牌                                               |
| `reason_code`     | 审单原因码（存量规则沿用，从 reason_detail 取）     |

匹配语义与 D03.03 `DispatchService._conditions_hit` **完全一致**（AND 组合，
维度缺失视为不命中），避免两套规则引擎语义漂移。

排序：weight DESC，**首命中**（与 D03.03 FR-02a 一致）。
兜底：类型字典的 `default_group_id` → 仍无 → 全局最低权重规则 → 留空（待人工分派）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.abnormal import OrdAbnormal, OrdAbnormalTypeDict
from app.models.audit import OrdDispatchRule

#: 异常单分派支持的维度（FR-02c）
ABNORMAL_DISPATCH_DIMS = ("exc_type", "shop_id", "owner_id", "brand_id", "reason_code")

#: 兜底权重（比存量规则的 -9999 略高，确保能被选中）
FALLBACK_WEIGHT = -10_000


class AbnormalDispatchEngine:
    """异常单自动分派引擎（FR-02c）"""

    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    # ---------- 维度构造 ----------

    async def dims_of(self, row: OrdAbnormal) -> dict[str, Any]:
        """构造异常单的规则匹配维度

        `reason_code` 从 `reason_detail` 里取（审单落单时会写入）；`brand_id`
        从订单快照取（订单有 brand_id 字段）。
        """
        dims: dict[str, Any] = {
            "exc_type": row.exc_type,
            "shop_id": row.shop_id,
            "owner_id": row.owner_id,
        }
        detail = row.reason_detail if isinstance(row.reason_detail, dict) else {}
        if detail.get("reason_code"):
            dims["reason_code"] = str(detail["reason_code"])
        brand_id = detail.get("brand_id")
        if brand_id is None and row.order_id:
            brand_id = await self._order_brand(row.order_id)
        if brand_id:
            dims["brand_id"] = brand_id
        return dims

    async def _order_brand(self, order_id: int) -> int:
        """取订单品牌（品牌维度分派用）"""
        from app.models.order import OrdOrder

        row = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id, OrdOrder.is_deleted == 0)
        )
        return int(getattr(row, "brand_id", 0) or 0) if row else 0

    # ---------- 规则匹配 ----------

    async def match_rule(self, row: OrdAbnormal) -> OrdDispatchRule | None:
        """匹配分派规则（weight DESC 首命中）"""
        dims = await self.dims_of(row)
        rules = list(
            await self.s.scalars(
                select(OrdDispatchRule).where(
                    OrdDispatchRule.is_deleted == 0,
                    OrdDispatchRule.status == "enabled",
                )
            )
        )
        # weight DESC，兜底规则（空 conditions）在最后
        rules.sort(key=lambda r: int(r.weight or 0), reverse=True)
        for r in rules:
            if self._hit(r.conditions, dims):
                return r
        return None

    @staticmethod
    def _hit(conditions: Any, dims: dict[str, Any]) -> bool:
        """条件求值（与 D03.03 `_conditions_hit` 同语义）"""
        if not conditions:
            return False
        items = conditions.get("items") or []
        if not items:
            return False
        for it in items:
            dim = str(it.get("dim", "") or "")
            op = str(it.get("op", "") or "eq")
            expect = it.get("value")
            actual = dims.get(dim)
            if actual in (None, ""):
                return False
            if op == "eq" and str(actual) != str(expect):
                return False
            if op == "neq" and str(actual) == str(expect):
                return False
            if op == "in" and actual not in (expect or []):
                return False
            if op == "not_in" and actual in (expect or []):
                return False
            if op == "contains" and str(expect) not in str(actual):
                return False
            if op == "starts_with" and not str(actual).startswith(str(expect)):
                return False
        return True

    # ---------- 分派决策 ----------

    async def decide(self, row: OrdAbnormal) -> dict[str, Any]:
        """分派决策（只算不执行）

        返回：目标处理组 / 命中规则 / 维度快照 / 兜底来源。
        """
        rule = await self.match_rule(row)
        dims = await self.dims_of(row)
        if rule is not None:
            return {
                "group_id": int(rule.target_group_id or 0),
                "op_id": int(rule.target_op_id or 0),
                "rule_id": rule.id,
                "rule_name": rule.rule_name,
                "strategy": rule.strategy,
                "source": "rule",
                "dims": dims,
            }
        # 兜底①：类型字典默认处理组
        tdict = await self._type_of(row.exc_type)
        gid = int(getattr(tdict, "default_group_id", 0) or 0) if tdict else 0
        if gid:
            return {
                "group_id": gid,
                "op_id": 0,
                "rule_id": None,
                "rule_name": f"类型默认处理组（{row.exc_type}）",
                "strategy": "least_task",
                "source": "type_default",
                "dims": dims,
            }
        # 兜底②：无 → 留待人工分派（不硬塞一个组）
        return {
            "group_id": 0,
            "op_id": 0,
            "rule_id": None,
            "rule_name": "",
            "strategy": "",
            "source": "none",
            "dims": dims,
        }

    async def _type_of(self, type_code: str) -> OrdAbnormalTypeDict | None:
        if not type_code:
            return None
        return await self.s.scalar(
            select(OrdAbnormalTypeDict).where(
                OrdAbnormalTypeDict.type_code == type_code,
                OrdAbnormalTypeDict.is_deleted == 0,
            )
        )
