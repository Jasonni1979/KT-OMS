"""拆单策略中心（D03.04）

**定位**：履约路由的「分配决策器」——一张订单的明细按何种规则分成几组，
每组产出一张发货单（delivery）。

**核心契约（SRS-00 §4.4）**：
- 拆单**不产生新订单**：订单主档恒为一张，产物是多张发货单；
- 拆单进度用 `orders.splited_num`（轮次）+ `order_item.split_num`（行已拆数量）表达；
- 拆单是审单插件链的一环，被审单引擎**同步调用**，返回分配方案。

**关键设计（对商派 lib/split 的实质改造）**：
- 策略是**纯函数**（allocate(input) → SplitResult，无落库/不改单/不查库/无随机），
  引擎统一落库（FR-03c）——商派 splitOrder 就地修改内存订单组，失败现场脏；
- **守恒校验显式化**（FR-03a/§5.4）：Σ组内数量 == Σ未拆余量，防丢行/多拆；
- 位图旗标「拆」→ **结构化错误码族**（NO_STOCK/CONFIG_INVALID/…）；
- 失败不抛裸异常，返回错误码 + 明细（FR-03e）。

**W6 实现的 3 个策略**（计划「拆单 3 策略」）：
| split_type | 名称 | 依据 |
|---|---|---|
| `owner` | 按货主拆 | FR-05 凯淳货权分离核心（SC-01）；D08 分账依据 |
| `branch` | 按仓库拆 | SC-02；消费 D03.06 分仓 plan |
| `stock_depth` | 按库存深度拆 | SC-08 部分拆分与续拆 / SC-09 失败兜底 |

注册表架构支持后续零引擎改动新增策略（FR-01b/AC-14）。

⚠ 本文件在 P3（上下文体积治理）中拆分为多个文件；
   此处保留 re-export，**原有 import 路径全部保持可用**。
"""

from __future__ import annotations

from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.fulfill import OrdSplitRule
from app.modules.m4_fulfill.service.split_chain import SplitChainMixin
from app.modules.m4_fulfill.service.split_manual import SplitManualMixin
from app.modules.m4_fulfill.service.split_models import (
    FAIL_CONFIG_INVALID,
    FAIL_CONSERVATION_VIOLATION,
    FAIL_NO_ITEMS,
    FAIL_NO_STOCK,
    FAIL_PRECONDITION_UNMET,
    FAIL_STRATEGY_DISABLED,
    SplitGroup,
    SplitInput,
    SplitItem,
    SplitOutcome,
    SplitResult,
    dump_json,
)
from app.modules.m4_fulfill.service.split_strategies import (
    REGISTRY,
    BranchSplitStrategy,
    OwnerSplitStrategy,
    SplitStrategy,
    SplitStrategyRegistry,
    StockDepthSplitStrategy,
    build_registry,
)

__all__ = [
    "FAIL_NO_STOCK",
    "FAIL_CONFIG_INVALID",
    "FAIL_PRECONDITION_UNMET",
    "FAIL_CONSERVATION_VIOLATION",
    "FAIL_STRATEGY_DISABLED",
    "FAIL_NO_ITEMS",
    "SplitItem",
    "SplitGroup",
    "SplitInput",
    "SplitResult",
    "SplitStrategy",
    "OwnerSplitStrategy",
    "BranchSplitStrategy",
    "StockDepthSplitStrategy",
    "SplitStrategyRegistry",
    "REGISTRY",
    "build_registry",
    "SplitOutcome",
    "SplitService",
    "SplitRuleService",
    "dump_json",
]


logger = get_logger("split")

class SplitService(SplitChainMixin, SplitManualMixin):
    """拆单服务（D03.04 FR-03 引擎 + FR-04 级联 + FR-06 进度）"""

    def __init__(self, session: AsyncSession, redis: Redis):
        self.s = session
        self.r = redis
        self.registry = build_registry()


class SplitRuleService:
    """拆单规则 CRUD + 策略 schema 校验 + 级联兼容校验"""

    def __init__(self, session: AsyncSession):
        self.s = session
        self.registry = build_registry()

    async def save(self, data: dict[str, Any]) -> dict[str, Any]:
        """保存规则（保存期校验：策略启用 + 配置 schema + 级联类型不重复 + 兼容清单）"""
        split_type = str(data.get("split_type", "") or "")
        strategy = self.registry.get(split_type)
        if strategy is None:
            raise ValidationError(f"策略不存在或已停用: {split_type}")
        errs = strategy.validate_config(data.get("split_config") or {})
        if errs:
            raise ValidationError(f"策略配置非法：{errs}")

        chain = [
            (split_type, data.get("split_config") or {}),
            (data.get("split_type_2"), data.get("split_config_2") or {}),
            (data.get("split_type_3"), data.get("split_config_3") or {}),
        ]
        active = [(t, c) for t, c in chain if t]
        types = [t for t, _ in active]
        if len(set(types)) != len(types):
            raise ValidationError(f"级联策略类型不得重复：{types}")
        for idx in range(1, len(active)):
            prev = self.registry.get(active[idx - 1][0])
            cur = active[idx][0]
            if prev is not None and cur not in prev.get_special():
                raise ValidationError(
                    f"级联组合不兼容：{active[idx - 1][0]} 不支持下一级 {cur}"
                    f"（允许：{prev.get_special()}）"
                )
            cur_strategy = self.registry.get(cur)
            if cur_strategy is not None:
                cur_errs = cur_strategy.validate_config(active[idx][1])
                if cur_errs:
                    raise ValidationError(f"级联策略 {cur} 配置非法：{cur_errs}")

        rule_id = int(data.get("id", 0) or 0)
        if rule_id:
            rule = await self.s.scalar(
                select(OrdSplitRule).where(
                    OrdSplitRule.id == rule_id, OrdSplitRule.is_deleted == 0
                )
            )
            if rule is None:
                raise NotFoundError(f"拆单规则不存在: {rule_id}")
            for k, v in data.items():
                if hasattr(rule, k) and k != "id":
                    setattr(rule, k, v)
        else:
            rule = OrdSplitRule(**{k: v for k, v in data.items() if hasattr(OrdSplitRule, k)})
            self.s.add(rule)
        await self.s.commit()
        await self.s.refresh(rule)
        return self.to_dict(rule)

    async def disable(self, rule_id: int) -> None:
        """停用规则"""
        rule = await self.s.scalar(
            select(OrdSplitRule).where(
                OrdSplitRule.id == rule_id, OrdSplitRule.is_deleted == 0
            )
        )
        if not rule:
            raise NotFoundError(f"拆单规则不存在: {rule_id}")
        rule.status = "disabled"
        await self.s.commit()

    async def list_rules(self) -> list[dict[str, Any]]:
        rows = list(
            await self.s.scalars(
                select(OrdSplitRule)
                .where(OrdSplitRule.is_deleted == 0)
                .order_by(OrdSplitRule.id)
            )
        )
        return [self.to_dict(r) for r in rows]

    @staticmethod
    def to_dict(rule: OrdSplitRule) -> dict[str, Any]:
        return {
            "id": rule.id,
            "owner_id": rule.owner_id,
            "rule_name": rule.rule_name,
            "split_type": rule.split_type,
            "split_config": rule.split_config,
            "split_type_2": rule.split_type_2,
            "split_config_2": rule.split_config_2,
            "split_type_3": rule.split_type_3,
            "split_config_3": rule.split_config_3,
            "scope_type": rule.scope_type,
            "scope_ref": rule.scope_ref,
            "confirm_source": rule.confirm_source,
            "status": rule.status,
        }
