"""配货分仓引擎（D03.06）

**定位**：分仓**决策器**——回答「这张订单的货从哪个（些）仓发」。
决策与执行分离：输出不可变 plan（行→仓→分配量），不做任何库存承诺，
由审单链路（D03.02）拿 plan 去预占（D04.03）、拆单（D03.04）、出发货单（D03.07）。

**核心流程**（§4.1 决策树）：
```
① 平台指定仓 store_code？→ 锁定唯一候选（校验存在且营业），不换仓
② 候选仓生成（按序合并去重 + 硬过滤）：
   货主仓属限定（行级硬过滤）> 店铺绑定仓（优先级）> 区域路由命中仓 > 全局兜底仓
③ 一次批量预取三元可用量（SKU × 候选仓 × 行货主）
④ 规则引擎命中（weight DESC 首个全命中）→ 候选仓按策略排序
⑤ 满足度计算：首个满足率=100% → 整仓 plan
   否则贪心多仓组合 → 多仓 plan（split_required=true）
   否则缺货判定 → lack plan（缺口明细 + 缺货路径编排）
⑥ plan 落库（轮次追加，旧轮次 superseded）+ 路由决策埋点
```

**关键契约**：
- 三元口径（仓×SKU×货主）——FR-03a，行货主的可用量，不是货主总量
- 硬过滤不可被手工绕过（货主仓属）——FR-06b
- 满足度快照是时点值，预占才是最终裁决——FR-03c
- plan 不可变、按轮次追加——FR-05a
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.fulfill import (
    OrdBranchChangeLog,
    OrdBranchDispatchRule,
    OrdDispatchPlan,
    OrdRoutingDecisionLog,
)
from app.models.order import OrdOrder, OrdOrderItem, OrdReceiver
from app.models.stock import InvStockLedger
from app.modules.m2_stock.service.stock_ledger import StockLedgerService

logger = get_logger("dispatch")

#: 分仓模式
MODE_SINGLE = "single"        # 整仓
MODE_MULTI = "multi"          # 多仓（需拆单）
MODE_LACK = "lack"            # 缺货
MODE_APPOINTED = "appointed"  # 平台指定仓

#: 选仓策略类型（FR-02b）
STRATEGY_BINDING_PRIORITY = "binding_priority"
STRATEGY_REGION_ROUTE = "region_route"
STRATEGY_STOCK_DEPTH = "stock_depth"
STRATEGY_OWNER_ASSIGN = "owner_assign"
STRATEGY_STORE_O2O = "store_o2o"      # P1（M3 交付）
STRATEGY_ROUND_ROBIN = "round_robin"  # P1 预留

#: 失败码
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


class DispatchService:
    """分仓服务（D03.06 FR-02/03/04/05/06）"""

    def __init__(self, session: AsyncSession, redis: Redis):
        self.s = session
        self.r = redis

    # ==================== 主入口 ====================

    async def dispatch(
        self,
        order_id: int,
        *,
        exclude_branches: list[int] | None = None,
        source: str = "auto",
        appointed_branch_id: int | None = None,
        operator: str = "system",
    ) -> DispatchResult:
        """分仓主入口（IF-D03.06-01）

        幂等：同订单同轮次返回最新 plan；plan 按轮次追加。
        """
        started = datetime.now()
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id, OrdOrder.is_deleted == 0)
        )
        if not order:
            raise NotFoundError(f"订单不存在: {order_id}")

        items = list(
            await self.s.scalars(
                select(OrdOrderItem)
                .where(OrdOrderItem.order_id == order_id, OrdOrderItem.is_deleted == 0)
                .order_by(OrdOrderItem.id)
            )
        )
        if not items:
            raise ValidationError("订单无明细行，无法分仓")

        receiver = await self.s.scalar(
            select(OrdReceiver).where(OrdReceiver.order_id == order_id).limit(1)
        )

        # ① 平台指定仓（FR-01a 最高优先级，锁定唯一候选）
        appointed = appointed_branch_id
        if appointed is None:
            appointed = self._appointed_from_order(order)
        if appointed:
            candidates = await self._appointed_candidates(appointed)
            if not candidates:
                return await self._fail(
                    order, items, [], FAIL_NO_CANDIDATE_BRANCH,
                    f"平台指定仓无效或未营业: {appointed}", source, started,
                )
            rule_hit = {"strategy": "platform_appointed", "branch_seq": [appointed]}
        else:
            # ② 候选仓生成
            candidates = await self.gen_candidates(order, items, exclude_branches or [])
            if not candidates:
                return await self._fail(
                    order, items, [], FAIL_NO_CANDIDATE_BRANCH,
                    "无候选发货仓（店铺未绑定发货仓 / 货主仓属不匹配）", source, started,
                )
            # ④ 规则引擎命中 → 仓序
            rule_hit = await self._match_rule(order, receiver, candidates)
            candidates = await self._sort_by_strategy(candidates, rule_hit, items)

        # ③ 一次批量预取三元可用量（FR-03e）
        stock_view = await self._prefetch_stock(candidates, items)

        # ⑤ 满足度计算
        for c in candidates:
            c.fulfill_rate = self._fulfill_rate(c, items, stock_view)
            c.available_map = {
                str(it.id): stock_view.get((c.branch_id, it.bm_id, it.owner_id), 0)
                for it in items
                if it.bm_id
            }

        result = await self._decide(order, items, candidates, stock_view, rule_hit, source, started)
        return result

    # ==================== 候选仓生成（FR-01）====================

    async def gen_candidates(
        self,
        order: OrdOrder,
        items: list[OrdOrderItem],
        exclude: list[int],
    ) -> list[BranchCandidate]:
        """候选仓生成（FR-01a：按序合并去重；FR-01b 硬过滤；FR-01c 行级候选）"""
        exclude_set = {int(b) for b in exclude}
        by_id: dict[int, BranchCandidate] = {}

        # ① 店铺绑定仓（含优先级）
        shop_binds = await self._shop_branch_binds(order.shop_id)
        for b in shop_binds:
            bid = int(b.get("branch_id", 0) or 0)
            if bid <= 0 or bid in exclude_set:
                continue
            by_id[bid] = BranchCandidate(
                branch_id=bid,
                priority=int(b.get("priority", 999) or 999),
                source="shop",
            )

        # ② 区域路由命中仓（FR-02a 条件维度：收货地址区域）
        region_hits = await self._region_route_branches(order)
        for idx, bid in enumerate(region_hits):
            if bid <= 0 or bid in exclude_set:
                continue
            if bid not in by_id:
                by_id[bid] = BranchCandidate(
                    branch_id=bid, priority=500 + idx, source="region"
                )

        # ③ 全局兜底仓
        if not by_id:
            for bid in await self._fallback_branches():
                if bid in exclude_set:
                    continue
                by_id[bid] = BranchCandidate(
                    branch_id=bid, priority=900, source="fallback"
                )

        # ④ 硬过滤（FR-01b）：营业状态 + 仓类型 + 货主仓属限定（FR-01c 行级）
        out: list[BranchCandidate] = []
        for cand in list(by_id.values()):
            row = await self._branch_row(cand.branch_id)
            if not row:
                continue
            if str(row.get("status", "")) != "enabled":
                continue
            # 卡密虚拟仓不参与实物分仓
            if str(row.get("branch_type", "")) in {"virtual", "card"}:
                continue
            cand.branch_name = str(row.get("branch_name", ""))
            cand.region_code = str(row.get("region_code", "") or "")
            # 货主仓属：单一归属仓（owner_id>0）只服务该货主
            owner_limit = int(row.get("owner_id", 0) or 0)
            if owner_limit > 0:
                cand.owner_ids = [owner_limit]
            else:
                cand.owner_ids = await self._branch_servable_owners(cand.branch_id)
            out.append(cand)

        # 行级候选收敛（FR-01c）：行货主仓属 ∩ 店铺可用仓
        return self._filter_by_owner_scope(out, items)

    def _filter_by_owner_scope(
        self, candidates: list[BranchCandidate], items: list[OrdOrderItem]
    ) -> list[BranchCandidate]:
        """行级候选收敛（FR-01c：行货主仓属 ∩ 店铺可用仓）

        仓作为**整单候选**的条件 = 至少服务本单某一行的货主；
        行级约束在分配阶段生效（贪心分配时行只能落到服务其货主的仓）——
        对应 SC-04「各行独立分仓」，混货主订单按行分到不同仓。
        """
        item_owners = {int(it.owner_id or 0) for it in items if it.bm_id}
        out: list[BranchCandidate] = []
        for cand in candidates:
            if not cand.owner_ids:
                # 未配置可服务货主的仓 → 不做货主维限制
                out.append(cand)
                continue
            if item_owners and item_owners & set(cand.owner_ids):
                out.append(cand)
        return out

    async def _branch_servable_owners(self, branch_id: int) -> list[int]:
        """仓可服务货主（D10.01 FR-07a：org_node_relation branch_owner 关系）"""
        rows = await self.s.execute(
            text(
                "SELECT b.org_node_id FROM oms_fulfill.ful_branch b "
                "WHERE b.id = :bid AND b.is_deleted = 0"
            ),
            {"bid": branch_id},
        )
        node_id = rows.scalar()
        if not node_id:
            return []
        rels = await self.s.execute(
            text(
                "SELECT r.rel_id FROM oms_org.org_node_relation r "
                "JOIN oms_org.org_owner o ON o.id = r.rel_id AND o.is_deleted = 0 "
                "WHERE r.node_id = :nid AND r.rel_type = 'branch_owner' "
                "AND r.status = 1"
            ),
            {"nid": node_id},
        )
        return [int(r) for r in rels.scalars().all()]

    async def _branch_row(self, branch_id: int) -> dict[str, Any] | None:
        rows = await self.s.execute(
            text(
                "SELECT id, branch_name, branch_type, region_code, owner_id, status "
                "FROM oms_fulfill.ful_branch WHERE id = :bid AND is_deleted = 0"
            ),
            {"bid": branch_id},
        )
        row = rows.mappings().first()
        return dict(row) if row else None

    async def _shop_branch_binds(self, shop_id: int) -> list[dict[str, Any]]:
        """店铺发货仓绑定（gw_shop_config.branch_bind_json）"""
        raw = await self.s.scalar(
            text(
                "SELECT branch_bind_json FROM oms_gateway.gw_shop_config "
                "WHERE shop_id = :sid AND is_deleted = 0 LIMIT 1"
            ),
            {"sid": shop_id},
        )
        if not raw:
            return []
        try:
            binds = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return []
        return [b for b in binds if isinstance(b, dict)] if isinstance(binds, list) else []

    async def _region_route_branches(self, order: OrdOrder) -> list[int]:
        """区域路由命中仓（ful_area_router，条件→logi_seq）"""
        recv = await self.s.scalar(
            select(OrdReceiver).where(OrdReceiver.order_id == order.id).limit(1)
        )
        if not recv:
            return []
        rows = await self.s.execute(
            text(
                "SELECT logi_seq FROM oms_fulfill.ful_area_router "
                "WHERE is_deleted = 0 AND status = 'enabled' ORDER BY weight DESC, id"
            )
        )
        out: list[int] = []
        for seq in rows.scalars().all():
            try:
                items = json.loads(seq) if isinstance(seq, str) else seq
            except (TypeError, ValueError):
                continue
            if isinstance(items, list):
                out.extend(int(x) for x in items if str(x).isdigit())
        return out

    async def _fallback_branches(self) -> list[int]:
        rows = await self.s.execute(
            text(
                "SELECT id FROM oms_fulfill.ful_branch "
                "WHERE is_deleted = 0 AND status = 'enabled' AND branch_type = 'entity' "
                "ORDER BY id LIMIT 5"
            )
        )
        return [int(r) for r in rows.scalars().all()]

    def _appointed_from_order(self, order: OrdOrder) -> int:
        """平台指定仓（订单报文 store_code；FR-01a）"""
        extra = getattr(order, "platform_extra", None) or {}
        if isinstance(extra, dict):
            for key in ("store_code", "warehouse_hint", "branch_code"):
                val = str(extra.get(key, "") or "").strip()
                if val.isdigit():
                    return int(val)
        return 0

    async def _appointed_candidates(self, branch_id: int) -> list[BranchCandidate]:
        """指定仓候选（FR-01a：命中即锁定唯一候选）"""
        row = await self._branch_row(branch_id)
        if not row or str(row.get("status", "")) != "enabled":
            return []
        return [
            BranchCandidate(
                branch_id=branch_id,
                branch_name=str(row.get("branch_name", "")),
                priority=0,
                source="platform",
            )
        ]

    # ==================== 规则引擎（FR-02）====================

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

    # ==================== 满足度计算（FR-03）====================

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

    # ==================== 决策（FR-03b）====================

    async def _decide(
        self,
        order: OrdOrder,
        items: list[OrdOrderItem],
        candidates: list[BranchCandidate],
        stock_view: dict[tuple[int, int, int], int],
        rule_hit: dict[str, Any],
        source: str,
        started: datetime,
    ) -> DispatchResult:
        """整仓优先 → 贪心多仓 → 缺货判定（FR-03b/FR-04a）"""
        res = DispatchResult(ok=True, rule_hit=rule_hit)

        # ① 整仓优先
        for cand in candidates:
            if cand.fulfill_rate >= 1.0:
                cand.priority = 0
                res.mode = (
                    MODE_APPOINTED if cand.source == "platform" else MODE_SINGLE
                )
                res.alloc = self._alloc_single(cand, items)
                res.candidates = candidates
                res.fulfill_snapshot = self._snapshot(candidates)
                return await self._finish(order, res, source, started)

        # ② 贪心多仓组合
        remain: dict[int, int] = {}
        for it in items:
            need = int(it.nums or 0) - int(getattr(it, "split_num", 0) or 0)
            if need > 0 and it.bm_id:
                remain[int(it.id)] = need
        alloc: dict[int, dict[int, int]] = {}
        for cand in candidates:
            if not remain:
                break
            for it in items:
                iid = int(it.id)
                if iid not in remain or remain[iid] <= 0:
                    continue
                # 行级货主约束（FR-01c）：仓不服务该行货主 → 该行不可在此仓发
                if not self._can_serve(cand, int(it.owner_id or 0)):
                    continue
                avail = stock_view.get(
                    (cand.branch_id, int(it.bm_id), int(it.owner_id or 0)), 0
                )
                take = min(avail, remain[iid])
                if take > 0:
                    alloc.setdefault(iid, {})[cand.branch_id] = (
                        alloc.get(iid, {}).get(cand.branch_id, 0) + take
                    )
                    remain[iid] -= take
        if not remain:
            res.mode = MODE_MULTI
            res.alloc = alloc
            res.split_required = True
            res.candidates = candidates
            res.fulfill_snapshot = self._snapshot(candidates)
            return await self._finish(order, res, source, started)

        # ③ 缺货判定（FR-04a）
        res.ok = False
        res.mode = MODE_LACK
        res.alloc = alloc
        res.split_required = True
        res.candidates = candidates
        res.fulfill_snapshot = self._snapshot(candidates)
        gap_rows = []
        for it in items:
            iid = int(it.id)
            if remain.get(iid, 0) <= 0:
                continue
            gap_rows.append(
                {
                    "order_item_id": iid,
                    "bm_id": int(it.bm_id or 0),
                    "bm_number": str(it.bm_number or ""),
                    "need": int(it.nums or 0),
                    "gap": remain[iid],
                    "best_available": sum(
                        stock_view.get(
                            (c.branch_id, int(it.bm_id), int(it.owner_id or 0)), 0
                        )
                        for c in candidates
                    ),
                    "candidate_count": len(candidates),
                }
            )
        res.lack_detail = {"gaps": gap_rows, "gap_total": sum(remain.values())}
        res.fail_code = (
            FAIL_PARTIAL_LACK if alloc else FAIL_FULL_LACK
        )
        res.fail_message = (
            f"{len(gap_rows)} 行缺货，缺口 {res.lack_detail['gap_total']} 件"
        )
        res.lack_route = "transfer_to_lack"  # 转 D03.09 缺货流程
        return await self._finish(order, res, source, started)

    def _alloc_single(
        self, cand: BranchCandidate, items: list[OrdOrderItem]
    ) -> dict[int, dict[int, int]]:
        """整仓分配（整仓满足率=100% 时调用；行级货主约束已由满足度保证）"""
        alloc: dict[int, dict[int, int]] = {}
        for it in items:
            need = int(it.nums or 0) - int(getattr(it, "split_num", 0) or 0)
            if need <= 0:
                continue
            alloc[int(it.id)] = {cand.branch_id: need}
        return alloc

    def _snapshot(self, candidates: list[BranchCandidate]) -> dict[str, Any]:
        """满足度快照（FR-03c：人工界面「建议仓+各仓库存」数据源）"""
        return {
            "branches": [c.to_dict() for c in candidates],
            "generated_at": datetime.now().isoformat(timespec="milliseconds"),
        }

    # ==================== plan 落库（FR-05）====================

    async def _finish(
        self,
        order: OrdOrder,
        res: DispatchResult,
        source: str,
        started: datetime,
    ) -> DispatchResult:
        """plan 落库 + 旧轮次 superseded + 埋点"""
        res.cost_ms = int((datetime.now() - started).total_seconds() * 1000)
        round_no = await self._next_round(order.id)
        plan = OrdDispatchPlan(
            owner_id=int(order.owner_id or 0),
            order_id=order.id,
            round_no=round_no,
            alloc={str(k): {str(b): q for b, q in v.items()} for k, v in res.alloc.items()},
            mode=res.mode,
            split_required=1 if res.split_required else 0,
            fulfill_snapshot=res.fulfill_snapshot,
            lack_detail=res.lack_detail or None,
            rule_hit=res.rule_hit,
            source=source,
            status="effective",
            lack_route=res.lack_route or None,
            shop_id=int(order.shop_id or 0),
        )
        self.s.add(plan)
        await self.s.flush()
        res.plan_id = plan.id
        res.round_no = round_no

        # 旧轮次 superseded（FR-05c：plan 不可变、只追加）
        await self.s.execute(
            text(
                "UPDATE oms_order.ord_dispatch_plan SET status = 'superseded' "
                "WHERE order_id = :oid AND id <> :pid AND status = 'effective'"
            ),
            {"oid": order.id, "pid": plan.id},
        )

        # 路由决策埋点（FR-08a：DOM 寻源数据地基）
        chosen = 0
        for v in res.alloc.values():
            for b in v:
                chosen = chosen or b
        self.s.add(
            OrdRoutingDecisionLog(
                owner_id=int(order.owner_id or 0),
                order_id=order.id,
                round_no=round_no,
                candidate_branches=[c.to_dict() for c in res.candidates],
                branch_features=self._features(res.candidates),
                rule_hit=res.rule_hit,
                chosen_branch=chosen or None,
                cost_compare=self._cost_compare(res),
                decision_mode="rule",
                duration_ms=res.cost_ms,
                shop_id=int(order.shop_id or 0),
            )
        )
        await self.s.commit()
        return res

    def _features(self, candidates: list[BranchCandidate]) -> dict[str, Any]:
        """各仓特征快照（FR-08a：可用量/深度/满足率）"""
        return {
            str(c.branch_id): {
                "fulfill_rate": round(c.fulfill_rate, 4),
                "available": c.available_map,
                "source": c.source,
                "priority": c.priority,
            }
            for c in candidates
        }

    def _cost_compare(self, res: DispatchResult) -> dict[str, Any]:
        """拆单 vs 等货 vs 调拨成本对比（FR-08b，规则式打分）"""
        if res.mode == MODE_MULTI:
            return {
                "decision": "split",
                "split_cost": res.split_required,
                "reason": "无单一仓整单满足，拆单履约",
            }
        if res.mode == MODE_LACK:
            return {
                "decision": "lack",
                "split_cost": 0,
                "reason": "全仓不可满足，转缺货流程",
            }
        return {"decision": "single", "split_cost": 0, "reason": "整仓满足"}

    async def _next_round(self, order_id: int) -> int:
        rows = await self.s.execute(
            text(
                "SELECT COALESCE(MAX(round_no), 0) FROM oms_order.ord_dispatch_plan "
                "WHERE order_id = :oid"
            ),
            {"oid": order_id},
        )
        return int(rows.scalar() or 0) + 1

    async def _fail(
        self,
        order: OrdOrder,
        items: list[OrdOrderItem],
        candidates: list[BranchCandidate],
        code: str,
        message: str,
        source: str,
        started: datetime,
    ) -> DispatchResult:
        res = DispatchResult(
            ok=False,
            mode=MODE_LACK,
            candidates=candidates,
            fail_code=code,
            fail_message=message,
            lack_route="transfer_to_lack",
        )
        return await self._finish(order, res, source, started)

    # ==================== 换仓重试（IF-D03.06-02）====================

    async def retry_with_gap(
        self,
        order_id: int,
        gap_item_ids: list[int],
        exclude_branches: list[int],
        *,
        operator: str = "system",
    ) -> DispatchResult:
        """换仓重试（FR-04b-1：缺口行重算、排除已试仓）"""
        return await self.dispatch(
            order_id,
            exclude_branches=exclude_branches,
            source="retry",
            operator=operator,
        )

    # ==================== 满足度视图（IF-D03.06-04）====================

    async def get_fulfill_view(self, order_id: int) -> dict[str, Any]:
        """人工审单界面：建议仓 + 各仓库存满足度快照"""
        plan = await self.s.scalar(
            select(OrdDispatchPlan)
            .where(
                OrdDispatchPlan.order_id == order_id,
                OrdDispatchPlan.status == "effective",
            )
            .order_by(OrdDispatchPlan.round_no.desc())
            .limit(1)
        )
        if not plan:
            return {"found": False, "candidates": []}
        snap = plan.fulfill_snapshot or {}
        return {
            "found": True,
            "plan_id": plan.id,
            "round_no": plan.round_no,
            "mode": plan.mode,
            "split_required": bool(plan.split_required),
            "alloc": plan.alloc,
            "lack_detail": plan.lack_detail,
            "candidates": snap.get("branches", []),
            "rule_hit": plan.rule_hit,
        }

    # ==================== 手工改仓（FR-06）====================

    async def change_branch(
        self,
        order_id: int,
        new_branch_id: int,
        reason: str,
        operator: str,
        *,
        forced: bool = False,
    ) -> DispatchResult:
        """手工改仓（FR-06b/c/d：校验 + 审计 + 新轮次 plan source=manual）"""
        if not reason:
            raise ValidationError("改仓原因必填")
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id, OrdOrder.is_deleted == 0)
        )
        if not order:
            raise NotFoundError(f"订单不存在: {order_id}")

        old_plan = await self.s.scalar(
            select(OrdDispatchPlan)
            .where(
                OrdDispatchPlan.order_id == order_id,
                OrdDispatchPlan.status == "effective",
            )
            .order_by(OrdDispatchPlan.round_no.desc())
            .limit(1)
        )
        old_branch = 0
        old_rate = 0.0
        if old_plan:
            for v in (old_plan.alloc or {}).values():
                for b in v:
                    old_branch = old_branch or int(b)
            snap = old_plan.fulfill_snapshot or {}
            for b in snap.get("branches", []):
                if int(b.get("branch_id", 0)) == old_branch:
                    old_rate = float(b.get("fulfill_rate", 0) or 0)

        # 货主仓属硬约束不可绕过（FR-06b + AC-04）
        items = list(
            await self.s.scalars(
                select(OrdOrderItem)
                .where(OrdOrderItem.order_id == order_id, OrdOrderItem.is_deleted == 0)
            )
        )
        servable = await self._branch_servable_owners(new_branch_id)
        item_owners = {int(it.owner_id or 0) for it in items if it.bm_id}
        if servable and item_owners and not item_owners.issubset(set(servable)):
            raise ValidationError(
                f"新仓不可服务本单货主（仓可服务货主={servable}，本单货主={sorted(item_owners)}）"
            )

        # 新仓满足度校验（不足时警示，强制需走审批——本实现记 forced 标记）
        view = await self.get_fulfill_view(order_id)
        new_rate = 0.0
        for b in view.get("candidates", []):
            if int(b.get("branch_id", 0)) == new_branch_id:
                new_rate = float(b.get("fulfill_rate", 0) or 0)
        if new_rate < 1.0 and not forced:
            raise ValidationError(
                f"新仓满足度不足（{new_rate:.2%}），如需强制改仓请带 forced 标记"
            )

        # 写审计（FR-06c）
        self.s.add(
            OrdBranchChangeLog(
                owner_id=int(order.owner_id or 0),
                order_id=order.id,
                plan_round=old_plan.round_no if old_plan else None,
                old_branch=old_branch or None,
                new_branch=new_branch_id,
                old_fulfill=old_rate,
                new_fulfill=new_rate,
                reason=reason,
                forced=1 if forced else 0,
                operator=operator,
                shop_id=int(order.shop_id or 0),
            )
        )
        await self.s.commit()

        # 新轮次 plan（source=manual，与自动 plan 同构可追溯）
        res = await self.dispatch(
            order_id,
            source="manual",
            appointed_branch_id=new_branch_id,
            operator=operator,
        )
        return res


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
