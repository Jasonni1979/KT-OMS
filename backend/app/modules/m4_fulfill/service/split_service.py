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
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.fulfill import OrdSplitRule, OrdSplitTrace
from app.models.order import OrdOrder, OrdOrderItem
from app.modules.m2_stock.contract import StockLedgerService

logger = get_logger("split")

# ==================== 失败码族（FR-03e / §5.6）====================

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


class SplitStrategy(ABC):
    """策略接口规范（FR-01a 纯函数契约 + FR-02a 四接口）"""

    #: 类型码（注册表唯一键）
    split_type: str = ""
    #: 展示名
    name: str = ""
    #: 说明
    description: str = ""
    #: 配置 schema（保存期校验用）
    config_schema: dict[str, Any] = {}
    #: 可作级联下层的策略类型清单（FR-04c 兼容性）
    special: list[str] = []

    @abstractmethod
    def allocate(self, inp: SplitInput) -> SplitResult:
        """分配主逻辑（纯函数：无落库/不改单/不查库/无随机）"""

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        """规则保存期校验（FR-01c：配置错误暴露在保存期而非运行期）"""
        errs: list[str] = []
        for key, spec in (self.config_schema or {}).items():
            if spec.get("required") and key not in (config or {}):
                errs.append(f"缺少必填配置项: {key}")
                continue
            if key not in (config or {}):
                continue
            val = config[key]
            vtype = spec.get("type")
            if vtype == "int":
                if not isinstance(val, int) or isinstance(val, bool):
                    errs.append(f"{key} 必须为整数")
                elif spec.get("min") is not None and val < spec["min"]:
                    errs.append(f"{key} 不得小于 {spec['min']}")
            elif vtype == "number":
                if not isinstance(val, (int, float)) or isinstance(val, bool):
                    errs.append(f"{key} 必须为数值")
            elif vtype == "str":
                if not isinstance(val, str):
                    errs.append(f"{key} 必须为字符串")
            elif vtype == "list":
                if not isinstance(val, list):
                    errs.append(f"{key} 必须为数组")
            elif vtype == "bool":
                if not isinstance(val, bool):
                    errs.append(f"{key} 必须为布尔值")
        return errs

    def get_special(self) -> list[str]:
        """可作级联下层的策略类型清单"""
        return list(self.special)

    def describe(self) -> dict[str, Any]:
        """元信息（名称/说明/config schema）"""
        return {
            "split_type": self.split_type,
            "name": self.name,
            "description": self.description,
            "config_schema": self.config_schema,
            "special": self.get_special(),
        }


# ==================== 三个核心策略 ====================


class OwnerSplitStrategy(SplitStrategy):
    """owner：按货主拆（FR-05，凯淳货权分离核心）

    分组依据 = 明细行物料的 owner_id（三元记账键之一）。
    借调场景按**记账货主**分组（借出方），不按业务归属（FR-05d）。
    跨货主订单若无 owner 策略 → 引擎层拦截（FR-05e，CONFIG_INVALID）。
    """

    split_type = "owner"
    name = "按货主拆"
    description = "按明细行货主分组，产出各自携带 owner_id 的发货单（D08 分账依据）"
    config_schema: dict[str, Any] = {}
    special = ["branch", "weight", "volume", "goods_type"]

    def allocate(self, inp: SplitInput) -> SplitResult:
        buckets: dict[int, SplitGroup] = {}
        for it in inp.items:
            if it.nums <= 0:
                continue
            # 借调按记账货主（FR-05d）
            owner = it.owner_id
            g = buckets.get(owner)
            if g is None:
                g = SplitGroup(
                    group_key=f"OWNER_{owner}",
                    attrs={"owner_id": owner},
                )
                buckets[owner] = g
            g.add(it.item_id, it.nums)
        if not buckets:
            return SplitResult(fail_code=FAIL_NO_ITEMS, fail_detail={"reason": "无可拆分明细"})
        # 单货主也产出方案（组数=1，FR-06e 口径统一）
        return SplitResult(groups=list(buckets.values()))


class BranchSplitStrategy(SplitStrategy):
    """branch：按仓库拆（SC-02）

    消费 D03.06 分仓 plan（行→仓）；分仓未出结果 → PRECONDITION_UNMET。
    """

    split_type = "branch"
    name = "按仓库拆"
    description = "按分仓结果（行→仓）分组，每组产出推对应仓的发货单"
    config_schema: dict[str, Any] = {
        "branch_seq": {"type": "list", "required": False},
    }
    special = ["owner", "weight", "volume"]

    def allocate(self, inp: SplitInput) -> SplitResult:
        plan = inp.get("branch_plan") or {}
        alloc = plan.get("alloc") if isinstance(plan, dict) else None
        if not alloc:
            return SplitResult(
                fail_code=FAIL_PRECONDITION_UNMET,
                fail_detail={"reason": "分仓结果缺失（branch 策略前置依赖未满足）"},
            )
        groups: dict[int, SplitGroup] = {}
        for it in inp.items:
            if it.nums <= 0:
                continue
            # alloc: {order_item_id: {branch_id: qty}}
            item_alloc = alloc.get(str(it.item_id)) or alloc.get(it.item_id) or {}
            if not item_alloc:
                return SplitResult(
                    fail_code=FAIL_PRECONDITION_UNMET,
                    fail_detail={
                        "reason": "分仓结果缺该行",
                        "item_id": it.item_id,
                    },
                )
            for branch_id, qty in item_alloc.items():
                bid = int(branch_id)
                take = min(int(qty), it.nums)
                if take <= 0:
                    continue
                g = groups.get(bid)
                if g is None:
                    g = SplitGroup(
                        group_key=f"BRANCH_{bid}",
                        attrs={"branch_id": bid},
                    )
                    groups[bid] = g
                g.add(it.item_id, take)
        if not groups:
            return SplitResult(
                fail_code=FAIL_PRECONDITION_UNMET,
                fail_detail={"reason": "分仓结果为空"},
            )
        return SplitResult(groups=list(groups.values()))


class StockDepthSplitStrategy(SplitStrategy):
    """stock_depth：按库存深度拆（SC-08 部分拆分与续拆 / SC-09 失败兜底）

    对每行按候选仓优先级查询三元可用量，贪心分配：
    整行满足 → 归该仓组；部分满足 → 行内按量拆；全仓不满足 → NO_STOCK。
    库存视图由引擎统一预取注入（策略内零查库，FR-02c）。
    """

    split_type = "stock_depth"
    name = "按库存深度拆"
    description = "按各仓可用量贪心分配，能发多少发多少；全仓不满足返回 NO_STOCK"
    config_schema: dict[str, Any] = {
        "allow_partial": {"type": "bool", "required": False},
        "lack_route": {"type": "str", "required": False},
    }
    special = ["branch", "owner"]

    def allocate(self, inp: SplitInput) -> SplitResult:
        allow_partial = bool(inp.get("allow_partial", True))
        view = inp.get("stock_view") or {}
        branch_seq = inp.get("branch_seq") or []
        groups: dict[int, SplitGroup] = {}
        gaps: list[dict[str, Any]] = []

        for it in inp.items:
            if it.nums <= 0:
                continue
            remain = it.nums
            for bid in branch_seq:
                avail = int(view.get((int(bid), it.bm_id, it.owner_id), 0))
                if avail <= 0:
                    continue
                take = min(avail, remain)
                g = groups.get(int(bid))
                if g is None:
                    g = SplitGroup(
                        group_key=f"BRANCH_{int(bid)}",
                        attrs={"branch_id": int(bid)},
                    )
                    groups[int(bid)] = g
                g.add(it.item_id, take)
                remain -= take
                if remain <= 0:
                    break
            if remain > 0:
                gaps.append(
                    {
                        "item_id": it.item_id,
                        "bm_id": it.bm_id,
                        "bm_number": it.bm_number,
                        "need": it.nums,
                        "gap": remain,
                    }
                )

        if gaps and not allow_partial:
            return SplitResult(
                fail_code=FAIL_NO_STOCK,
                fail_detail={"gaps": gaps},
            )
        if gaps and not groups:
            # 全仓不满足 → NO_STOCK（§5.6）
            return SplitResult(
                fail_code=FAIL_NO_STOCK,
                fail_detail={"gaps": gaps},
            )
        if not groups:
            return SplitResult(
                fail_code=FAIL_NO_STOCK,
                fail_detail={"reason": "无可用库存", "gaps": gaps},
            )
        res = SplitResult(groups=list(groups.values()))
        if gaps:
            res.fail_detail = {"gaps": gaps}
        return res


# ==================== 策略注册表（FR-01b）====================


class SplitStrategyRegistry:
    """策略注册表（FR-01b：按 split_type 唯一注册）

    新增策略 = 实现接口 + 注册，**不改引擎代码**（AC-14 插件化验证）。
    """

    def __init__(self) -> None:
        self._strategies: dict[str, SplitStrategy] = {}

    def register(self, strategy: SplitStrategy) -> None:
        if not strategy.split_type:
            raise ValueError("策略缺少 split_type")
        self._strategies[strategy.split_type] = strategy

    def get(self, split_type: str) -> SplitStrategy | None:
        return self._strategies.get(split_type)

    def list_all(self) -> list[SplitStrategy]:
        return list(self._strategies.values())

    def describe_all(self) -> list[dict[str, Any]]:
        return [s.describe() for s in self._strategies.values()]

    def is_enabled(self, split_type: str) -> bool:
        """策略启停（FR-01e：停用后执行时拒绝并给出 STRATEGY_DISABLED）"""
        return split_type in self._strategies


#: 全局注册表
REGISTRY = SplitStrategyRegistry()


def build_registry() -> SplitStrategyRegistry:
    """构建注册表（W6 三个策略）"""
    reg = SplitStrategyRegistry()
    reg.register(OwnerSplitStrategy())
    reg.register(BranchSplitStrategy())
    reg.register(StockDepthSplitStrategy())
    return reg


# ==================== 拆单服务（IF-D03.04-01/02/06）====================


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


class SplitService:
    """拆单服务（D03.04 FR-03 引擎 + FR-04 级联 + FR-06 进度）"""

    def __init__(self, session: AsyncSession, redis: Redis):
        self.s = session
        self.r = redis
        self.registry = build_registry()

    # ==================== 主入口 ====================

    async def split(
        self,
        order_id: int,
        split_rule_id: int,
        context: dict[str, Any] | None = None,
        *,
        source: str = "auto",
        operator: str = "system",
    ) -> SplitOutcome:
        """拆单统一入口（IF-D03.04-01）

        流程（FR-03b）：加载规则 → 校验策略启用 → 预取上下文 → 执行策略（或级联）
        → **守恒校验** → 产出 SplitPlan（交给 D03.07 落库发货单）→ 写 split_trace。
        """
        started = datetime.now()
        rule = await self.s.scalar(
            select(OrdSplitRule).where(
                OrdSplitRule.id == split_rule_id,
                OrdSplitRule.is_deleted == 0,
            )
        )
        if not rule:
            raise NotFoundError(f"拆单规则不存在: {split_rule_id}")
        if rule.status != "enabled":
            return await self._trace_fail(
                order_id, rule, [], context or {}, source, operator, started,
                FAIL_STRATEGY_DISABLED, {"rule_status": rule.status},
            )

        items = await self._load_items(order_id)
        if not items:
            return await self._trace_fail(
                order_id, rule, [], context or {}, source, operator, started,
                FAIL_NO_ITEMS, {"reason": "订单无明细行"},
            )

        ctx = dict(context or {})
        # 预取上下文（FR-02c：库存视图引擎统一预取，策略内零查库）
        ctx.setdefault("stock_view", await self._prefetch_stock(items, ctx))
        ctx.setdefault("branch_seq", ctx.get("branch_seq") or [])

        # 跨货主校验（FR-05e：规则链无 owner 策略 → 拒绝执行，防混货主发货单）
        owners = {it.owner_id for it in items if it.bm_id}
        chain_types = [rule.split_type, rule.split_type_2, rule.split_type_3]
        if len(owners) > 1 and "owner" not in [t for t in chain_types if t]:
            return await self._trace_fail(
                order_id, rule, items, ctx, source, operator, started,
                FAIL_CONFIG_INVALID,
                {
                    "reason": "订单跨货主但规则链未含 owner 策略（防混货主发货单）",
                    "owners": sorted(owners),
                    "chain": chain_types,
                },
            )

        # 级联编排（FR-04b/c）
        result = await self._run_chain(rule, items, ctx)
        if not result.ok:
            return await self._trace_fail(
                order_id, rule, items, ctx, source, operator, started,
                result.fail_code, result.fail_detail,
            )

        # 守恒校验（FR-03b / §5.4）
        conserve_err = self.conserve_check(result.groups, items)
        if conserve_err:
            return await self._trace_fail(
                order_id, rule, items, ctx, source, operator, started,
                FAIL_CONSERVATION_VIOLATION, conserve_err,
            )

        # 写 trace（FR-08a）
        return await self._trace_success(
            order_id, rule, items, ctx, result, source, operator, started
        )

    # ==================== 级联编排（FR-04）====================

    async def _run_chain(
        self, rule: OrdSplitRule, items: list[SplitItem], ctx: dict[str, Any]
    ) -> SplitResult:
        """级联执行（FR-04b/c/d）

        第一层对全单明细分组；第二层对**每个上层分组内部**再分组（不跨上层组）。
        产物组 = 各层分组键的笛卡尔交集。
        """
        levels: list[tuple[str, dict[str, Any]]] = [
            (rule.split_type, rule.split_config or {}),
        ]
        if rule.split_type_2:
            levels.append((rule.split_type_2, rule.split_config_2 or {}))
        if rule.split_type_3:
            levels.append((rule.split_type_3, rule.split_config_3 or {}))

        # 级联类型互不相同（FR-04a 保存期校验，这里兜底）
        types = [t for t, _ in levels]
        if len(set(types)) != len(types):
            return SplitResult(
                fail_code=FAIL_CONFIG_INVALID,
                fail_detail={"reason": "级联策略类型重复（防死循环）", "chain": types},
            )

        current: list[SplitGroup] = []
        for idx, (split_type, config) in enumerate(levels):
            strategy = self.registry.get(split_type)
            if strategy is None:
                return SplitResult(
                    fail_code=FAIL_STRATEGY_DISABLED,
                    fail_detail={"reason": f"策略未注册或已停用: {split_type}"},
                )
            # 级联兼容清单校验（FR-04c）
            if idx > 0:
                prev = self.registry.get(types[idx - 1])
                if prev is not None and strategy.split_type not in prev.get_special():
                    return SplitResult(
                        fail_code=FAIL_CONFIG_INVALID,
                        fail_detail={
                            "reason": f"级联组合不兼容：{types[idx - 1]} 不支持下一级 {split_type}",
                            "allowed": prev.get_special(),
                        },
                    )
            # 配置校验（FR-01c）
            errs = strategy.validate_config(config)
            if errs:
                return SplitResult(
                    fail_code=FAIL_CONFIG_INVALID,
                    fail_detail={"reason": f"策略 {split_type} 配置非法", "errors": errs},
                )

            if idx == 0:
                sub_ctx = {**ctx, **{k: v for k, v in config.items() if k not in ctx}}
                sub_ctx.update({k: v for k, v in ctx.items() if k not in sub_ctx})
                res = strategy.allocate(SplitInput(items=items, context=sub_ctx))
                if not res.ok:
                    return res
                current = res.groups
                continue

            # 下层：对每个上层组内部再分组
            next_groups: list[SplitGroup] = []
            for parent in current:
                sub_items = [it for it in items if it.item_id in {i for i, _ in parent.lines}]
                sub_ctx = {**ctx, **{k: v for k, v in config.items() if k not in ctx}}
                sub_ctx.update({k: v for k, v in ctx.items() if k not in sub_ctx})
                res = strategy.allocate(SplitInput(items=sub_items, context=sub_ctx))
                if not res.ok:
                    return res
                for sub in res.groups:
                    # 合并上层属性（笛卡尔交集）
                    attrs = {**parent.attrs, **sub.attrs}
                    merged = SplitGroup(
                        group_key=f"{parent.group_key}_{sub.group_key}",
                        lines=list(sub.lines),
                        attrs=attrs,
                    )
                    next_groups.append(merged)
            current = next_groups
        return SplitResult(groups=current)

    # ==================== 守恒校验（§5.4）====================

    def conserve_check(
        self, groups: list[SplitGroup], items: list[SplitItem]
    ) -> dict[str, Any]:
        """守恒校验（防丢行/防多拆）

        对每行：Σ(组内分配量) 必须 == 未拆余量；且每条分配量 > 0。
        允许例外：赠品「不发」组（skip_delivery）按「分配+跳过=余量」口径。
        """
        by_item: dict[int, int] = {}
        for g in groups:
            for item_id, nums in g.lines:
                if nums <= 0:
                    return {
                        "reason": "组内分配量非正",
                        "item_id": item_id,
                        "nums": nums,
                    }
                by_item[item_id] = by_item.get(item_id, 0) + nums
        for it in items:
            if it.nums <= 0:
                continue
            got = by_item.get(it.item_id, 0)
            if got != it.nums:
                return {
                    "reason": "守恒校验失败：组内分配量之和 ≠ 未拆余量",
                    "item_id": it.item_id,
                    "bm_number": it.bm_number,
                    "expected": it.nums,
                    "actual": got,
                }
        return {}

    # ==================== 上下文装载 ====================

    async def _load_items(self, order_id: int) -> list[SplitItem]:
        """装载只读明细快照（未拆余量 = nums - split_num）"""
        rows = await self.s.execute(
            select(OrdOrderItem).where(
                OrdOrderItem.order_id == order_id,
                OrdOrderItem.is_deleted == 0,
            ).order_by(OrdOrderItem.id)
        )
        out: list[SplitItem] = []
        for r in rows.scalars().all():
            remain = int(r.nums or 0) - int(r.split_num or 0)
            if remain <= 0:
                continue
            out.append(
                SplitItem(
                    item_id=int(r.id),
                    bm_id=int(r.bm_id or 0),
                    bm_number=str(r.bm_number or ""),
                    bm_name=str(r.bm_name or ""),
                    nums=remain,
                    owner_id=int(r.owner_id or 0),
                    material_type=0,
                    is_virtual=int(getattr(r, "is_virtual", 0) or 0),
                    is_gift=int(getattr(r, "is_gift", 0) or 0),
                    price=float(r.paid_amount or 0),
                )
            )
        return out

    async def _prefetch_stock(
        self, items: list[SplitItem], ctx: dict[str, Any]
    ) -> dict[tuple[int, int, int], int]:
        """引擎统一预取三元可用量（FR-02c / §5.3：一次批量，策略内零查库）"""
        branch_seq = ctx.get("branch_seq") or []
        if not branch_seq or not items:
            return {}
        bm_ids = sorted({it.bm_id for it in items if it.bm_id})
        owner_ids = sorted({it.owner_id for it in items})
        from app.models.stock import InvStockLedger

        db_rows = await self.s.execute(
            select(
                InvStockLedger.branch_id,
                InvStockLedger.bm_id,
                InvStockLedger.owner_id,
                InvStockLedger.store,
                InvStockLedger.freeze,
                InvStockLedger.defective,
                InvStockLedger.safe_store,
                InvStockLedger.is_locked,
            ).where(
                InvStockLedger.branch_id.in_([int(b) for b in branch_seq]),
                InvStockLedger.bm_id.in_(bm_ids),
                InvStockLedger.owner_id.in_(owner_ids),
                InvStockLedger.is_deleted == 0,
            )
        )
        return {
            (int(r[0]), int(r[1]), int(r[2])): StockLedgerService.available_of(
                int(r[3]), int(r[4]), int(r[5]), int(r[6]), int(r[7])
            )
            for r in db_rows.all()
        }

    # ==================== trace 落库（FR-08a）====================

    async def _trace_success(
        self,
        order_id: int,
        rule: OrdSplitRule,
        items: list[SplitItem],
        ctx: dict[str, Any],
        result: SplitResult,
        source: str,
        operator: str,
        started: datetime,
    ) -> SplitOutcome:
        cost = int((datetime.now() - started).total_seconds() * 1000)
        round_no = await self._next_round(order_id)
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id).limit(1)
        )
        trace = OrdSplitTrace(
            owner_id=int(order.owner_id or 0) if order else 0,
            order_id=order_id,
            round_no=round_no,
            split_rule_id=rule.id,
            rule_snapshot={
                "rule_name": rule.rule_name,
                "split_type": rule.split_type,
                "split_config": rule.split_config,
                "split_type_2": rule.split_type_2,
                "split_config_2": rule.split_config_2,
                "split_type_3": rule.split_type_3,
                "split_config_3": rule.split_config_3,
            },
            input_snapshot={"items": [i.to_dict() for i in items]},
            group_result={"groups": [g.to_dict() for g in result.groups]},
            source=source,
            result_status="success",
            cost_ms=cost,
            operator=operator,
            shop_id=int(order.shop_id or 0) if order else 0,
        )
        self.s.add(trace)
        await self.s.commit()
        await self.s.refresh(trace)
        return SplitOutcome(
            ok=True,
            groups=[g.to_dict() for g in result.groups],
            trace_id=trace.id,
            round_no=round_no,
            cost_ms=cost,
        )

    async def _trace_fail(
        self,
        order_id: int,
        rule: OrdSplitRule,
        items: list[SplitItem],
        ctx: dict[str, Any],
        source: str,
        operator: str,
        started: datetime,
        code: str,
        detail: dict[str, Any],
    ) -> SplitOutcome:
        cost = int((datetime.now() - started).total_seconds() * 1000)
        round_no = await self._next_round(order_id)
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id).limit(1)
        )
        trace = OrdSplitTrace(
            owner_id=int(order.owner_id or 0) if order else 0,
            order_id=order_id,
            round_no=round_no,
            split_rule_id=rule.id,
            rule_snapshot={"split_type": rule.split_type},
            input_snapshot={"items": [i.to_dict() for i in items]},
            group_result={"groups": []},
            source=source,
            result_status="failed",
            err_code=code,
            err_detail=detail,
            cost_ms=cost,
            operator=operator,
            shop_id=int(order.shop_id or 0) if order else 0,
        )
        self.s.add(trace)
        await self.s.commit()
        await self.s.refresh(trace)
        return SplitOutcome(
            ok=False,
            fail_code=code,
            fail_detail=detail,
            trace_id=trace.id,
            round_no=round_no,
            cost_ms=cost,
        )

    async def _next_round(self, order_id: int) -> int:
        rows = await self.s.execute(
            text(
                "SELECT COALESCE(MAX(round_no), 0) FROM oms_order.ord_split_trace "
                "WHERE order_id = :oid"
            ),
            {"oid": order_id},
        )
        return int(rows.scalar() or 0) + 1

    # ==================== 手工拆单（IF-D03.04-02，FR-07）====================

    async def manual_split(
        self,
        order_id: int,
        groups: list[dict[str, Any]],
        operator: str,
    ) -> SplitOutcome:
        """手工拆单（FR-07：人工审单工作台入口）

        校验（FR-07c）：各组数量之和 ≤ 行未拆余量；组内货主唯一；
        走同一引擎落库通道（source=manual，操作人=真实账号）。
        """
        started = datetime.now()
        items = await self._load_items(order_id)
        if not items:
            return SplitOutcome(ok=False, fail_code=FAIL_NO_ITEMS)
        by_id = {it.item_id: it for it in items}

        # 各组数量之和 ≤ 未拆余量
        per_item: dict[int, int] = {}
        parsed: list[SplitGroup] = []
        for g in groups:
            lines = g.get("items") or g.get("lines") or []
            attrs = dict(g.get("attrs") or {})
            sg = SplitGroup(
                group_key=str(g.get("group_key") or f"MANUAL_{len(parsed) + 1}"),
                attrs=attrs,
            )
            owners: set[int] = set()
            for ln in lines:
                item_id = int(ln.get("item_id", 0) or 0)
                nums = int(ln.get("nums", 0) or 0)
                if item_id not in by_id:
                    return SplitOutcome(
                        ok=False,
                        fail_code=FAIL_CONFIG_INVALID,
                        fail_detail={"reason": f"明细行不存在: {item_id}"},
                    )
                if nums <= 0:
                    return SplitOutcome(
                        ok=False,
                        fail_code=FAIL_CONFIG_INVALID,
                        fail_detail={"reason": "分配数量必须为正"},
                    )
                owners.add(by_id[item_id].owner_id)
                per_item[item_id] = per_item.get(item_id, 0) + nums
                sg.add(item_id, nums)
            if len(owners) > 1:
                return SplitOutcome(
                    ok=False,
                    fail_code=FAIL_CONFIG_INVALID,
                    fail_detail={
                        "reason": "组内货主不唯一（手工拆单不豁免）",
                        "group_key": sg.group_key,
                        "owners": sorted(owners),
                    },
                )
            parsed.append(sg)

        for it in items:
            got = per_item.get(it.item_id, 0)
            if got > it.nums:
                return SplitOutcome(
                    ok=False,
                    fail_code=FAIL_CONFIG_INVALID,
                    fail_detail={
                        "reason": "各组数量之和超过行未拆余量",
                        "item_id": it.item_id,
                        "remain": it.nums,
                        "submitted": got,
                    },
                )
        # 部分拆分允许（未分配余量留给续拆）→ 守恒校验用「≤」口径
        result = SplitResult(groups=parsed)
        # 写 trace（source=manual）
        rule = await self.s.scalar(
            select(OrdSplitRule).where(OrdSplitRule.is_deleted == 0).limit(1)
        )
        if rule is None:
            # 无规则时用占位规则记录手工拆单轨迹
            cost = int((datetime.now() - started).total_seconds() * 1000)
            order = await self.s.scalar(
                select(OrdOrder).where(OrdOrder.id == order_id).limit(1)
            )
            round_no = await self._next_round(order_id)
            trace = OrdSplitTrace(
                owner_id=int(order.owner_id or 0) if order else 0,
                order_id=order_id,
                round_no=round_no,
                split_rule_id=0,
                rule_snapshot={"source": "manual"},
                input_snapshot={"items": [i.to_dict() for i in items]},
                group_result={"groups": [g.to_dict() for g in parsed]},
                source="manual",
                result_status="success",
                cost_ms=cost,
                operator=operator,
                shop_id=int(order.shop_id or 0) if order else 0,
            )
            self.s.add(trace)
            await self.s.commit()
            await self.s.refresh(trace)
            return SplitOutcome(
                ok=True,
                groups=[g.to_dict() for g in parsed],
                trace_id=trace.id,
                round_no=round_no,
                cost_ms=cost,
            )
        return await self._trace_success(
            order_id, rule, items, {}, result, "manual", operator, started
        )

    # ==================== 拆单进度回写（FR-06 / IF-D03.04-07）====================

    async def write_progress(
        self, order_id: int, groups: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """回写拆单进度（FR-06a/b：split_num 累加 + splited_num +1）"""
        rows = await self.s.execute(
            select(OrdOrderItem).where(
                OrdOrderItem.order_id == order_id,
                OrdOrderItem.is_deleted == 0,
            )
        )
        items = {int(r.id): r for r in rows.scalars().all()}
        for g in groups:
            for ln in g.get("items", []):
                item_id = int(ln.get("item_id", 0) or 0)
                nums = int(ln.get("nums", 0) or 0)
                it = items.get(item_id)
                if not it:
                    continue
                new_split = int(it.split_num or 0) + nums
                if new_split > int(it.nums or 0):
                    raise ValidationError(
                        f"split_num 超过行数量（行{item_id}: {new_split} > {it.nums}）"
                    )
                it.split_num = new_split
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id).limit(1)
        )
        if order:
            order.splited_num = int(order.splited_num or 0) + 1
        await self.s.commit()
        return {
            "splited_num": int(order.splited_num or 0) if order else 0,
            "split_num_map": {
                str(i.id): int(i.split_num or 0) for i in items.values()
            },
        }

    async def rollback_progress(
        self, order_id: int, delivery_id: int
    ) -> dict[str, Any]:
        """拆单进度回退（FR-06d：发货单取消/打回 → split_num 扣减）

        splited_num **不回退**（轮次历史保留）。
        """
        from app.models.fulfill import OrdDeliveryItem, OrdDeliveryItemDetail

        details = list(
            await self.s.scalars(
                select(OrdDeliveryItemDetail).where(
                    OrdDeliveryItemDetail.delivery_id == delivery_id
                )
            )
        )
        rows = await self.s.execute(
            select(OrdOrderItem).where(
                OrdOrderItem.order_id == order_id,
                OrdOrderItem.is_deleted == 0,
            )
        )
        items = {int(r.id): r for r in rows.scalars().all()}
        del OrdDeliveryItem
        for d in details:
            it = items.get(int(d.order_item_id))
            if not it:
                continue
            it.split_num = max(0, int(it.split_num or 0) - int(d.split_qty or 0))
        await self.s.commit()
        return {
            "rolled_back": len(details),
            "split_num_map": {str(i): int(v.split_num or 0) for i, v in items.items()},
        }

    # ==================== 追溯查询（IF-D03.04-06）====================

    async def query_trace(self, order_id: int) -> list[dict[str, Any]]:
        """拆单历史时间线（FR-08b）"""
        rows = list(
            await self.s.scalars(
                select(OrdSplitTrace)
                .where(OrdSplitTrace.order_id == order_id)
                .order_by(OrdSplitTrace.round_no)
            )
        )
        return [
            {
                "id": r.id,
                "round_no": r.round_no,
                "split_rule_id": r.split_rule_id,
                "rule_snapshot": r.rule_snapshot,
                "group_result": r.group_result,
                "source": r.source,
                "result_status": r.result_status,
                "err_code": r.err_code,
                "err_detail": r.err_detail,
                "delivery_ids": r.delivery_ids,
                "cost_ms": r.cost_ms,
                "operator": r.operator,
                "create_time": (
                    r.create_time.isoformat() if r.create_time else ""
                ),
            }
            for r in rows
        ]


# ==================== 规则服务（IF-D03.04-03）====================


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


def dump_json(obj: Any) -> str:
    """调试用 JSON 序列化"""
    return json.dumps(obj, ensure_ascii=False, default=str)
