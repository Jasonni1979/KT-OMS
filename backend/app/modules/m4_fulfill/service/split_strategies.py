"""M4 拆单策略 —— 货主/分仓/库存深度三种策略与注册表"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from app.modules.m4_fulfill.service.split_models import (
    FAIL_NO_ITEMS,
    FAIL_NO_STOCK,
    FAIL_PRECONDITION_UNMET,
    SplitGroup,
    SplitInput,
    SplitResult,
)


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

REGISTRY = SplitStrategyRegistry()

def build_registry() -> SplitStrategyRegistry:
    """构建注册表（W6 三个策略）"""
    reg = SplitStrategyRegistry()
    reg.register(OwnerSplitStrategy())
    reg.register(BranchSplitStrategy())
    reg.register(StockDepthSplitStrategy())
    return reg