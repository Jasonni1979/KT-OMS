"""SKU 映射服务（D02.03 FR-05 未知商品自动建档联动 / D03.01 FR-04b/FR-04d）

映射链：
```
platform_sku_id
  → oms_stock.inv_sales_material（shop_id + sales_material_bn）
  → inv_bom_version（生效版）→ inv_bom_item → 基础物料 inv_material
  → {sm_id, bm_id, bm_number, bm_name, owner_id, bom_version, 展开明细}
```

**未知商品自动建档（FR-05）**：
- 未命中销售物料 → 调适配器 `itemGet` 拉平台商品资料 → `SalesMaterialService.auto_create`（幂等）
- 并发防护：同一 `platform_sku_id` 加 Redis 锁去重
- 时效：单商品建档 ≤5s；不阻塞整批（未建档成功的行标 parse_status=pending）
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.material import InvSalesMaterial
from app.modules.m2_stock.service.material import BomExpandItem, SalesMaterialService, bom_expand

#: 自动建档锁 TTL（秒）
AUTOCREATE_LOCK_TTL = 10
#: 自动建档等待上限（秒，FR-05c）
AUTOCREATE_TIMEOUT = 5.0


@dataclass
class LineMapping:
    """单行映射结果"""

    line_no: int
    platform_sku_id: str
    platform_item_id: str = ""
    sm_id: int = 0
    bm_id: int = 0
    bm_number: str = ""
    bm_name: str = ""
    owner_id: int = 0
    bom_version: int = 0
    parse_status: str = "parsed"   # parsed / pending / failed
    expanded: list[BomExpandItem] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)
    auto_created: bool = False
    message: str = ""


class SkuMappingService:
    """SKU 映射 + 未知商品自动建档"""

    def __init__(
        self,
        session: AsyncSession,
        redis: Redis | None = None,
        gateway: Any | None = None,
    ):
        self.s = session
        self.r = redis
        self.gw = gateway

    async def find_sales_material(
        self, shop_id: int, platform_sku_id: str
    ) -> InvSalesMaterial | None:
        """按店铺 + 平台 SKU 编码查销售物料"""
        if not platform_sku_id:
            return None
        return await self.s.scalar(
            select(InvSalesMaterial).where(
                InvSalesMaterial.shop_id == shop_id,
                InvSalesMaterial.sales_material_bn == platform_sku_id,
                InvSalesMaterial.is_deleted == 0,
            )
        )

    async def map_line(
        self,
        *,
        shop_id: int,
        line_no: int,
        platform_sku_id: str,
        platform_item_id: str = "",
        qty: int = 1,
        allow_auto_create: bool = True,
    ) -> LineMapping:
        """单行映射（含自动建档兜底）"""
        mapping = LineMapping(
            line_no=line_no,
            platform_sku_id=platform_sku_id,
            platform_item_id=platform_item_id,
        )
        sm = await self.find_sales_material(shop_id, platform_sku_id)
        if sm is None and allow_auto_create:
            sm = await self._auto_create(shop_id, platform_sku_id, platform_item_id)
            if sm is not None:
                mapping.auto_created = True
        if sm is None:
            mapping.parse_status = "pending"
            mapping.message = "平台SKU未映射到销售物料（自动建档未成功）"
            return mapping

        mapping.sm_id = sm.id
        mapping.owner_id = sm.owner_id
        expanded, bom_version = await bom_expand(self.s, sm.id, qty)
        mapping.bom_version = bom_version
        if not expanded:
            # 销售物料存在但 BOM 未绑定 → 软失败（暂缓投审，不拒单）
            mapping.parse_status = "pending"
            mapping.message = "销售物料未绑定基础物料（BOM 未绑定）"
            return mapping
        mapping.expanded = expanded
        first = expanded[0]
        mapping.bm_id = first.bm_id
        mapping.bm_number = first.bm_number
        mapping.bm_name = first.bm_name
        return mapping

    async def _auto_create(
        self, shop_id: int, platform_sku_id: str, platform_item_id: str
    ) -> InvSalesMaterial | None:
        """未知商品自动建档（FR-05a/05b：锁去重 + 幂等）"""
        lock_key = f"lock:autocreate:{shop_id}:{platform_sku_id}"
        got = False
        if self.r is not None:
            try:
                got = bool(await self.r.set(lock_key, "1", nx=True, ex=AUTOCREATE_LOCK_TTL))
            except Exception:
                got = True  # Redis 异常时不阻断（幂等键兜底）
        if not got:
            # 已有其他协程在建档 → 等待其完成后再查
            for _ in range(int(AUTOCREATE_TIMEOUT * 10)):
                await asyncio.sleep(0.1)
                sm = await self.find_sales_material(shop_id, platform_sku_id)
                if sm is not None:
                    return sm
            return None

        try:
            title = platform_sku_id
            spec = ""
            if self.gw is not None and platform_item_id:
                try:
                    res = await self.gw.adapter.item_get(
                        shop_id=shop_id,
                        platform_item_id=platform_item_id,
                        primary_bn=platform_sku_id,
                    )
                    if res.succ:
                        item = (res.data or {}).get("item") or {}
                        title = str(item.get("title") or platform_sku_id)
                        props = item.get("props") or {}
                        spec = str(props.get("规格") or "")
                except Exception:
                    pass  # 拉取失败不阻断（用占位名建档，后续可补全）
            svc = SalesMaterialService(self.s)
            sm, _created = await svc.auto_create(
                _auto_create_payload(shop_id, platform_sku_id, title, spec)
            )
            return sm
        finally:
            if self.r is not None:
                try:
                    await self.r.delete(lock_key)
                except Exception:
                    pass


def _auto_create_payload(shop_id: int, sku: str, title: str, spec: str):
    """构造自动建档入参（复用 D04.01 FR-01a 的 SalesMaterialAutoCreate 契约）"""
    from app.schemas.material import SalesMaterialAutoCreate

    return SalesMaterialAutoCreate(
        shop_id=shop_id,
        sales_material_bn=sku,
        sales_material_name=title,
        spec_text=spec,
        sales_material_type=1,
    )
