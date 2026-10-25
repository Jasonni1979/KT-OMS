"""可售计算服务（D04.08 FR-02 可售数量计算策略链）

计算链（SRS §5.1）：
```
基础可用(D04.02 available，多仓聚合)
  → 减活动锁定池占用（非本渠道活动锁定量，FR-01e 正交叠加）
  → 组合装BOM展开（可售=min(各成员可售/需求量)，向下取整，FR-02b）
  → 策略换算（独立配额 / 共享比例 / 安全库存，FR-01a）
  → 取整与上下限修正（clamp(min, max)）
  → 最终可售
```

**可用库存只取 `StockLedgerService.available_of`（D04.02 全局唯一公式）**，
本模块不另算口径。
"""

import math
from dataclasses import dataclass, field
from datetime import datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.material import InvSalesMaterial
from app.models.stock import InvActivityLockPool, InvStockLedger, InvSyncStrategy
from app.services.material import bom_expand
from app.services.stock_ledger import StockLedgerService

#: 可售缓存 TTL（秒，FR-02d）
CACHE_TTL = 60


@dataclass
class SellableResult:
    """可售计算结果"""

    shop_id: int
    sm_id: int
    platform_sku: str = ""
    base_available: int = 0
    sellable: int = 0
    strategy_type: str = "shared_safe"
    is_combo: bool = False
    member_details: list[dict] = field(default_factory=list)
    branch_ids: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "shop_id": self.shop_id,
            "sm_id": self.sm_id,
            "platform_sku": self.platform_sku,
            "base_available": self.base_available,
            "sellable": self.sellable,
            "strategy_type": self.strategy_type,
            "is_combo": self.is_combo,
            "member_details": self.member_details,
            "branch_ids": self.branch_ids,
            "warnings": self.warnings,
        }


class SellableService:
    """可售计算"""

    def __init__(self, session: AsyncSession, redis: Redis | None = None):
        self.s = session
        self.r = redis

    # ---------- 店铺-发货仓 ----------

    async def shop_branches(self, shop_id: int) -> list[int]:
        """店铺关联发货仓（gw_shop_config.branch_bind_json，按 priority 排序）"""
        from sqlalchemy import text

        row = await self.s.scalar(
            text(
                "SELECT branch_bind_json FROM oms_gateway.gw_shop_config "
                "WHERE shop_id = :sid AND is_deleted = 0 LIMIT 1"
            ),
            {"sid": shop_id},
        )
        if not row:
            return []
        import json

        try:
            binds = json.loads(row) if isinstance(row, str) else (row or [])
        except (TypeError, ValueError):
            return []
        out = [int(b.get("branch_id") or 0) for b in binds if b.get("branch_id")]
        return [b for b in out if b > 0]

    # ---------- 策略 ----------

    async def get_strategy(self, shop_id: int, sm: InvSalesMaterial | None = None) -> InvSyncStrategy | None:
        """取策略（FR-01b：店铺级默认，可下探分类/品牌/物料；数字大者优先）"""
        rows = list(
            await self.s.scalars(
                select(InvSyncStrategy).where(
                    InvSyncStrategy.shop_id == shop_id,
                    InvSyncStrategy.status == 1,
                    InvSyncStrategy.is_deleted == 0,
                )
            )
        )
        if not rows:
            return None
        if sm is not None:
            # 物料级(4) > 分类级(2) > 全店(1)
            # 注：inv_sales_material 无 brand_id 列 → 品牌级(3)下探暂不支持（P1 补品牌关联后启用）
            for scope_type, ref in ((4, sm.id), (2, sm.class_id)):
                if not ref:
                    continue
                for row in rows:
                    if row.scope_type != scope_type:
                        continue
                    refs = row.scope_ref or []
                    if not refs or int(ref) in [int(x) for x in refs]:
                        return row
        for row in rows:
            if row.scope_type == 1:
                return row
        return rows[0]

    # ---------- 单物料可售 ----------

    async def calc_single(
        self, shop_id: int, bm_id: int, owner_id: int, branch_ids: list[int]
    ) -> tuple[int, list[dict]]:
        """单基础物料可售（多仓聚合，FR-02c）+ 活动锁定扣减（FR-01e）"""
        total = 0
        details: list[dict] = []
        for branch_id in branch_ids:
            row = await self.s.scalar(
                select(InvStockLedger).where(
                    InvStockLedger.branch_id == branch_id,
                    InvStockLedger.bm_id == bm_id,
                    InvStockLedger.owner_id == owner_id,
                )
            )
            if row is None:
                available = 0
            else:
                available = StockLedgerService.available_of(
                    row.store,
                    row.freeze,
                    row.defective,
                    row.safe_store,
                    row.is_locked,
                )
            # 活动锁定：非本渠道活动池占用从常规可售中扣减；本渠道池量加回（专属可售）
            locked_other, locked_own = await self._activity_lock(shop_id, branch_id, bm_id, owner_id)
            final = available - locked_other + locked_own
            total += max(final, 0)
            details.append(
                {
                    "branch_id": branch_id,
                    "bm_id": bm_id,
                    "available": available,
                    "activity_locked_other": locked_other,
                    "activity_locked_own": locked_own,
                    "sellable": max(final, 0),
                }
            )
        return total, details

    async def _activity_lock(
        self, shop_id: int, branch_id: int, bm_id: int, owner_id: int
    ) -> tuple[int, int]:
        """活动锁定池占用（本渠道 / 非本渠道）"""
        now = datetime.now()
        rows = list(
            await self.s.scalars(
                select(InvActivityLockPool).where(
                    InvActivityLockPool.branch_id == branch_id,
                    InvActivityLockPool.bm_id == bm_id,
                    InvActivityLockPool.owner_id == owner_id,
                    InvActivityLockPool.is_deleted == 0,
                )
            )
        )
        other = own = 0
        for row in rows:
            if row.status not in ("active", "warmup"):
                continue
            if row.start_time and row.start_time > now:
                continue
            if row.end_time and row.end_time < now:
                continue
            remain = max(row.lock_num - row.sold_num, 0)
            if remain <= 0:
                continue
            scope = row.channel_scope or []
            is_own = any(
                int(x.get("shop_id") or 0) == shop_id
                for x in scope
                if isinstance(x, dict)
            )
            if is_own:
                own += remain
            else:
                other += remain
        return other, own

    # ---------- 主入口 ----------

    async def calc(self, shop_id: int, sm_id: int, *, use_cache: bool = True) -> SellableResult:
        """可售计算（IF-D04.08-01）"""
        cache_key = f"sellable:{shop_id}:{sm_id}"
        if use_cache and self.r is not None:
            try:
                cached = await self.r.get(cache_key)
                if cached:
                    import json

                    data = json.loads(cached)
                    return SellableResult(**data)
            except Exception:
                pass

        sm = await self.s.scalar(
            select(InvSalesMaterial).where(
                InvSalesMaterial.id == sm_id, InvSalesMaterial.is_deleted == 0
            )
        )
        if sm is None:
            raise ValueError(f"销售物料不存在: {sm_id}")
        result = await self._calc_uncached(shop_id, sm)

        if use_cache and self.r is not None:
            try:
                import json

                await self.r.set(cache_key, json.dumps(result.as_dict(), default=str), ex=CACHE_TTL)
            except Exception:
                pass
        return result

    async def _calc_uncached(self, shop_id: int, sm: InvSalesMaterial) -> SellableResult:
        branches = await self.shop_branches(shop_id)
        warnings: list[str] = []
        if not branches:
            warnings.append("店铺未配置关联发货仓（gw_shop_config.branch_bind_json），可售按 0 计")

        # ① BOM 展开（组合装 → 取最小套数，FR-02b）
        expanded, _bom_version = await bom_expand(self.s, sm.id, 1)
        is_combo = len(expanded) > 1
        base_available = 0
        member_details: list[dict] = []

        if not expanded:
            warnings.append("销售物料未绑定基础物料（BOM 未绑定），可售按 0 计")
            expanded = []
        elif is_combo:
            # 组合装：min(成员可售 / 需求量)，向下取整
            min_sets = None
            for member in expanded:
                member_avail, member_detail = await self.calc_single(
                    shop_id, member.bm_id, member.owner_id, branches
                )
                sets = member_avail // member.qty if member.qty > 0 else 0
                member_details.append(
                    {
                        "bm_id": member.bm_id,
                        "bm_number": member.bm_number,
                        "require_num": member.qty,
                        "available": member_avail,
                        "sellable_sets": sets,
                        "branches": member_detail,
                    }
                )
                min_sets = sets if min_sets is None else min(min_sets, sets)
            base_available = min_sets or 0
        else:
            member = expanded[0]
            base_available, member_detail = await self.calc_single(
                shop_id, member.bm_id, member.owner_id, branches
            )
            member_details.append(
                {
                    "bm_id": member.bm_id,
                    "bm_number": member.bm_number,
                    "require_num": member.qty,
                    "available": base_available,
                    "sellable_sets": base_available,
                    "branches": member_detail,
                }
            )

        # ② 策略换算（FR-01a）
        strategy = await self.get_strategy(shop_id, sm)
        strategy_type = strategy.strategy_type if strategy else "shared_safe"
        safe = 0
        if strategy is not None:
            safe = int(strategy.safe_num or 0)
            if not safe and strategy.safe_ratio:
                safe = int(base_available * float(strategy.safe_ratio) / 100)

        if strategy_type == "independent":
            # 独立配额：不共享池（FR-01a），配额明细在独立配额表（P1 未实现 → 用 quota_num）
            sellable = int(strategy.quota_num or 0) if strategy is not None else 0
        elif strategy_type == "shared_ratio":
            pool = max(base_available - safe, 0)
            ratio = float(strategy.alloc_ratio or 0) if strategy is not None else 0
            sellable = int(math.floor(pool * ratio / 100))
        else:  # shared_safe / activity_lock 基座
            sellable = max(base_available - safe, 0)

        # ③ 上下限修正
        if strategy is not None:
            min_s = int(strategy.min_sellable or 0)
            max_s = int(strategy.max_sellable or 0)
            sellable = max(sellable, min_s)
            if max_s > 0:
                sellable = min(sellable, max_s)

        return SellableResult(
            shop_id=shop_id,
            sm_id=sm.id,
            platform_sku=sm.sales_material_bn,
            base_available=base_available,
            sellable=max(sellable, 0),
            strategy_type=strategy_type,
            is_combo=is_combo,
            member_details=member_details,
            branch_ids=branches,
            warnings=warnings,
        )

    # ---------- 缓存失效（FR-02d）----------

    async def invalidate(self, shop_id: int, sm_id: int) -> None:
        """清除可售缓存（stock.changed / material.updated 事件驱动）"""
        if self.r is None:
            return
        try:
            await self.r.delete(f"sellable:{shop_id}:{sm_id}")
        except Exception:
            pass

    async def invalidate_all(self, shop_id: int) -> None:
        """清除店铺全部可售缓存"""
        if self.r is None:
            return
        try:
            async for key in self.r.scan_iter(match=f"sellable:{shop_id}:*"):
                await self.r.delete(key)
        except Exception:
            pass
