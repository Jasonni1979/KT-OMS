"""DispatchRuleMixin —— 由 DispatchService 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.fulfill import (
    OrdBranchDispatchRule,
)
from app.models.order import OrdOrder, OrdOrderItem, OrdReceiver
from app.models.stock import InvStockLedger
from app.modules.m2_stock.contract import StockLedgerService
from app.modules.m4_fulfill.service.dispatch_models import (
    STRATEGY_BINDING_PRIORITY,
    STRATEGY_OWNER_ASSIGN,
    STRATEGY_REGION_ROUTE,
    STRATEGY_ROUND_ROBIN,
    BranchCandidate,
    _in_window,  # noqa: F401
    period_match,
)

logger = get_logger("dispatch")


class DispatchRuleMixin:
    """DispatchService 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Redis

    async def _match_rule(
        self,
        order: OrdOrder,
        receiver: OrdReceiver | None,
        candidates: list[BranchCandidate],
    ) -> dict[str, Any]:
        """分仓规则命中（FR-02c：weight DESC 首个全条件命中；缺省兜底）"""
        rules = list(
            await self.s.scalars(
                select(OrdBranchDispatchRule)
                .where(
                    OrdBranchDispatchRule.is_deleted == 0,
                    OrdBranchDispatchRule.status == "enabled",
                )
                .order_by(OrdBranchDispatchRule.weight.desc(), OrdBranchDispatchRule.id)
            )
        )
        dims = self._rule_dims(order, receiver)
        for rule in rules:
            if rule.default_flag:
                continue
            if not self._conditions_hit(rule.conditions, dims):
                continue
            # 时间段：生效/排除（FR-02d）
            if not self._period_ok(rule):
                continue
            return {
                "rule_id": rule.id,
                "rule_name": rule.rule_name,
                "strategy": rule.strategy_type,
                "branch_seq": rule.branch_seq,
                "weight": rule.weight,
            }
        # 缺省兜底：按店铺绑定仓优先级（FR-02c）
        return {
            "rule_id": 0,
            "rule_name": "缺省兜底（店铺绑定仓优先级）",
            "strategy": STRATEGY_BINDING_PRIORITY,
            "branch_seq": None,
            "weight": -9999,
        }

    def _rule_dims(self, order: OrdOrder, receiver: OrdReceiver | None) -> dict[str, Any]:
        return {
            "shop_id": int(order.shop_id or 0),
            "platform": str(getattr(order, "platform", "") or ""),
            "order_type": str(order.order_type or ""),
            "owner_id": int(order.owner_id or 0),
            "receiver_province": str(receiver.province or "") if receiver else "",
            "receiver_city": str(receiver.city or "") if receiver else "",
            "receiver_district": str(receiver.district or "") if receiver else "",
        }

    def _conditions_hit(self, conditions: Any, dims: dict[str, Any]) -> bool:
        """规则条件求值（AND 组合，维度缺失视为不命中）"""
        if not conditions:
            return False
        try:
            items = conditions.get("items") or []
        except AttributeError:
            return False
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

    def _period_ok(self, rule: OrdBranchDispatchRule) -> bool:
        """生效/排除时间段（FR-02d）"""
        now = datetime.now()
        return period_match(rule.effective_period, rule.exclude_period, now)

    async def _sort_by_strategy(
        self,
        candidates: list[BranchCandidate],
        rule_hit: dict[str, Any],
        items: list[OrdOrderItem],
    ) -> list[BranchCandidate]:
        """按策略排序候选仓（FR-02b）"""
        strategy = str(rule_hit.get("strategy", STRATEGY_BINDING_PRIORITY))
        seq = rule_hit.get("branch_seq")
        by_id = {c.branch_id: c for c in candidates}

        if strategy == STRATEGY_BINDING_PRIORITY:
            ordered = sorted(candidates, key=lambda c: (c.priority, c.branch_id))
        elif strategy == STRATEGY_REGION_ROUTE:
            ordered = sorted(
                candidates,
                key=lambda c: (
                    0 if (isinstance(seq, list) and c.branch_id in seq) else 1,
                    c.priority,
                    c.branch_id,
                ),
            )
        elif strategy == STRATEGY_OWNER_ASSIGN:
            # 货主指定仓：单一归属仓优先（owner_id>0 的仓）
            ordered = sorted(
                candidates,
                key=lambda c: (0 if len(c.owner_ids) == 1 else 1, c.priority, c.branch_id),
            )
        elif strategy == STRATEGY_ROUND_ROBIN:
            ordered = sorted(candidates, key=lambda c: (c.branch_id % 7, c.branch_id))
        else:
            # stock_depth / store_o2o：满足度需在预取后计算，此处先按优先级
            ordered = sorted(candidates, key=lambda c: (c.priority, c.branch_id))
        del by_id
        return ordered

    async def _prefetch_stock(
        self, candidates: list[BranchCandidate], items: list[OrdOrderItem]
    ) -> dict[tuple[int, int, int], int]:
        """一次批量预取三元可用量（FR-03e：SKU × 候选仓 × 行货主）

        一次 Redis HMGET（热路径）+ 一次 DB IN 查询（miss 降级），
        **不做逐仓逐 SKU 查询**——DB/Redis 交互次数与仓数、SKU 数无关。
        """
        view: dict[tuple[int, int, int], int] = {}
        if not candidates or not items:
            return view
        # 去重三元键
        keys: list[tuple[int, int, int]] = []
        seen: set[tuple[int, int, int]] = set()
        for cand in candidates:
            for it in items:
                if not it.bm_id:
                    continue
                key = (cand.branch_id, int(it.bm_id), int(it.owner_id or 0))
                if key in seen:
                    continue
                seen.add(key)
                keys.append(key)
        if not keys:
            return view

        # ① Redis 批量读（热路径）
        redis_keys = [StockLedgerService.stock_key(*k) for k in keys]
        try:
            pipes = await self.r.mget(redis_keys)
        except Exception:
            pipes = [None] * len(redis_keys)
        misses: list[tuple[int, int, int]] = []
        for key, raw in zip(keys, pipes, strict=True):
            if raw is None:
                misses.append(key)
                continue
            view[key] = self._available_from_hash(raw)

        # ② DB 批量补齐（miss 降级）
        if misses:
            branch_ids = sorted({k[0] for k in misses})
            bm_ids = sorted({k[1] for k in misses})
            owner_ids = sorted({k[2] for k in misses})
            rows = await self.s.execute(
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
                    InvStockLedger.branch_id.in_(branch_ids),
                    InvStockLedger.bm_id.in_(bm_ids),
                    InvStockLedger.owner_id.in_(owner_ids),
                    InvStockLedger.is_deleted == 0,
                )
            )
            db_map = {
                (int(r[0]), int(r[1]), int(r[2])): StockLedgerService.available_of(
                    int(r[3]), int(r[4]), int(r[5]), int(r[6]), int(r[7])
                )
                for r in rows.all()
            }
            for key in misses:
                view[key] = db_map.get(key, 0)
        return view

    @staticmethod
    def _available_from_hash(raw: Any) -> int:
        """从 Redis hash 值算可用量（口径与 DB 一致）"""
        if isinstance(raw, (bytes, bytearray)):
            try:
                raw = raw.decode()
            except UnicodeDecodeError:
                return 0
        if not isinstance(raw, dict):
            return 0

        def _g(field: str) -> int:
            val = raw.get(field, raw.get(field.encode(), 0))
            if val is None:
                return 0
            try:
                return int(val)
            except (TypeError, ValueError):
                return 0

        return StockLedgerService.available_of(
            _g("store"), _g("freeze"), _g("defective"), _g("safe_locked"), 1
        )

    def _fulfill_rate(
        self,
        cand: BranchCandidate,
        items: list[OrdOrderItem],
        stock_view: dict[tuple[int, int, int], int],
    ) -> float:
        """满足率（FR-03a：Σ min(available, need) / Σ need）

        行级货主约束（FR-01c）：仓不服务该行货主 → 该行可用量记 0。
        """
        total = 0
        got = 0
        for it in items:
            need = int(it.nums or 0) - int(getattr(it, "split_num", 0) or 0)
            if need <= 0 or not it.bm_id:
                continue
            total += need
            if not self._can_serve(cand, int(it.owner_id or 0)):
                continue
            avail = stock_view.get((cand.branch_id, int(it.bm_id), int(it.owner_id or 0)), 0)
            got += min(avail, need)
        if total <= 0:
            return 1.0
        return got / total

    @staticmethod
    def _can_serve(cand: BranchCandidate, owner_id: int) -> bool:
        """仓能否服务该货主（FR-01c 行级硬约束：单一归属仓只发自己货主的货）"""
        if not cand.owner_ids:
            return True
        return owner_id in cand.owner_ids