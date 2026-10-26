"""DispatchCandidateMixin —— 由 DispatchService 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.order import OrdOrder, OrdOrderItem, OrdReceiver
from app.modules.m4_fulfill.service.dispatch_models import (
    FAIL_NO_CANDIDATE_BRANCH,
    BranchCandidate,
    DispatchResult,
    _in_window,  # noqa: F401
    )

logger = get_logger("dispatch")


class DispatchCandidateMixin:
    """DispatchService 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Redis

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
