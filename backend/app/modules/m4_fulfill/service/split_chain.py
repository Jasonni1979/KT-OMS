"""SplitChainMixin —— 由 SplitService 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.fulfill import OrdSplitRule
from app.models.order import OrdOrderItem
from app.modules.m2_stock.contract import StockLedgerService
from app.modules.m4_fulfill.service.split_models import (
    FAIL_CONFIG_INVALID,
    FAIL_CONSERVATION_VIOLATION,
    FAIL_NO_ITEMS,
    FAIL_STRATEGY_DISABLED,
    SplitGroup,
    SplitInput,
    SplitItem,
    SplitOutcome,
    SplitResult,
)
from app.modules.m4_fulfill.service.split_strategies import (
    SplitStrategyRegistry,
)

logger = get_logger("split")


class SplitChainMixin:
    """SplitService 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Redis
    registry: SplitStrategyRegistry

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