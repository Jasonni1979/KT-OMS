"""可售同步服务（D04.08 FR-03 平台库存回写 / FR-04 超卖防护 / FR-05 同步对账）

**回写通道**：经 D02 适配器调用平台库存更新接口（模拟器 = `taobao.item.update`），
失败进 D02.05 重试（本模块落 `inv_sync_log` 并标记失败，不吞异常）。

**节流与防抖**（§5.3）：
- 变化阈值：`|新可售 − 上次回写| ≥ max(1, 上次回写 × threshold_rate)` 才回写
- 售罄/恢复（跨越 0 线）**强制立即回写**，不受阈值限制

**售罄熔断**（FR-04b）：`available ≤ 0` → 立即回写 0 并暂停该 SKU 回写（防抖），
补货后（可售 > 0）自动恢复。

**对账**（FR-05a）：拉平台库存 vs OMS 可售，差异超阈值 → 强制回写 + 落差异清单。
"""

from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import METHOD_ITEM_GET, METHOD_ITEM_UPDATE
from app.models.material import InvSalesMaterial
from app.models.stock import InvSyncLog
from app.services.gateway import Gateway
from app.services.sellable import SellableService

#: 回写触发类型（inv_sync_log.trigger_type）
TRIGGER_EVENT = 1
TRIGGER_WATER = 2
TRIGGER_SCHEDULE = 3
TRIGGER_MANUAL = 4
TRIGGER_RECON = 5

#: 节流窗口（秒，§5.3：同 SKU 窗口内合并）
THROTTLE_WINDOW = 5


@dataclass
class WritebackResult:
    """回写结果"""

    shop_id: int
    sm_id: int
    platform_sku: str
    calc_sellable: int
    written: bool
    reason: str = ""
    error_code: str = ""
    log_id: int = 0

    def as_dict(self) -> dict:
        return {
            "shop_id": self.shop_id,
            "sm_id": self.sm_id,
            "platform_sku": self.platform_sku,
            "calc_sellable": self.calc_sellable,
            "written": self.written,
            "reason": self.reason,
            "error_code": self.error_code,
        }


class StockSyncService:
    """可售同步（计算 + 回写）"""

    def __init__(self, session: AsyncSession, redis: Redis | None, gateway: Gateway):
        self.s = session
        self.r = redis
        self.gw = gateway
        self.sellable = SellableService(session, redis)

    # ---------- 回写状态（Redis）----------

    def _wb_key(self, shop_id: int, sku: str) -> str:
        return f"sellable:wb:{shop_id}:{sku}"

    def _fuse_key(self, shop_id: int, sku: str) -> str:
        return f"sellable:fuse:{shop_id}:{sku}"

    async def _last_written(self, shop_id: int, sku: str) -> int | None:
        """上次回写值（Redis）"""
        if self.r is None:
            return None
        try:
            raw = await self.r.get(self._wb_key(shop_id, sku))
            if raw is None:
                return None
            return int(raw.decode() if isinstance(raw, bytes) else raw)
        except Exception:
            return None

    async def _set_last_written(self, shop_id: int, sku: str, value: int) -> None:
        if self.r is None:
            return
        try:
            await self.r.set(self._wb_key(shop_id, sku), str(value), ex=3600)
        except Exception:
            pass

    async def _fused(self, shop_id: int, sku: str) -> bool:
        """是否处于售罄熔断（暂停回写）"""
        if self.r is None:
            return False
        try:
            return bool(await self.r.exists(self._fuse_key(shop_id, sku)))
        except Exception:
            return False

    async def _set_fused(self, shop_id: int, sku: str, on: bool) -> None:
        if self.r is None:
            return
        try:
            if on:
                await self.r.set(self._fuse_key(shop_id, sku), "1", ex=3600)
            else:
                await self.r.delete(self._fuse_key(shop_id, sku))
        except Exception:
            pass

    # ---------- 回写 ----------

    async def writeback(
        self,
        shop_id: int,
        sm_id: int,
        *,
        trigger: int = TRIGGER_EVENT,
        force: bool = False,
        threshold_rate: float = 0.0,
    ) -> WritebackResult:
        """回写单个 SKU 的可售数量（FR-03a~d）"""
        sm = await self.s.scalar(
            select(InvSalesMaterial).where(
                InvSalesMaterial.id == sm_id, InvSalesMaterial.is_deleted == 0
            )
        )
        if sm is None:
            return WritebackResult(shop_id, sm_id, "", 0, False, "销售物料不存在")
        sku = sm.sales_material_bn

        # 回写必须用**实时计算值**：缓存是给读接口（D11/门户）用的，
        # 用缓存会回写陈旧可售 → 平台库存不准（FR-02d 的缓存失效依赖事件，M1c 阶段无事件总线）
        result = await self.sellable.calc(shop_id, sm_id, use_cache=False)
        calc_num = result.sellable

        # 售罄熔断（FR-04b）：可售 ≤ 0 → 立即回写 0 并暂停该 SKU
        if calc_num <= 0:
            if await self._fused(shop_id, sku):
                # 已熔断且仍为 0 → 不重复回写（防抖）
                return WritebackResult(
                    shop_id, sm_id, sku, 0, False, "售罄熔断中，已暂停回写"
                )
            written = await self._do_writeback(shop_id, sm, 0, trigger)
            await self._set_fused(shop_id, sku, True)
            return written

        # 补货恢复：解除熔断
        if await self._fused(shop_id, sku):
            await self._set_fused(shop_id, sku, False)

        # 节流防抖（§5.3）：变化阈值 / 跨 0 线强制
        last = await self._last_written(shop_id, sku)
        if not force and last is not None:
            threshold = max(1, int(abs(last) * threshold_rate))
            crossed_zero = (last <= 0 < calc_num) or (last > 0 >= calc_num)
            if not crossed_zero and abs(calc_num - last) < threshold:
                return WritebackResult(
                    shop_id, sm_id, sku, calc_num, False,
                    f"变化未超阈值(差{abs(calc_num - last)}<{threshold})，本轮不回写",
                )

        written = await self._do_writeback(shop_id, sm, calc_num, trigger)
        if written.written:
            await self._set_last_written(shop_id, sku, calc_num)
        return written

    async def _do_writeback(
        self, shop_id: int, sm: InvSalesMaterial, num: int, trigger: int
    ) -> WritebackResult:
        """调用平台库存更新接口 + 落回写日志（FR-03c/03d）"""
        res = await self.gw.call(
            METHOD_ITEM_UPDATE,
            {"item_id": sm.id, "sku_id": sm.sales_material_bn, "num": num},
            shop_id=shop_id,
            primary_bn=sm.sales_material_bn,
            source="writeback",
        )
        payload = (res.raw or {}) if isinstance(res.raw, dict) else {}
        import json

        resp_text = json.dumps(payload, ensure_ascii=False, default=str)[:1000]
        log = InvSyncLog(
            owner_id=sm.owner_id,
            shop_id=shop_id,
            sm_id=sm.id,
            platform_sku=sm.sales_material_bn,
            calc_sellable=num,
            writeback_num=num if res.succ else 0,
            trigger_type=trigger,
            sync_status=1 if res.succ else 2,
            platform_response=resp_text,
            error_code="" if res.succ else res.err_code,
        )
        self.s.add(log)
        await self.s.commit()
        await self.s.refresh(log)
        return WritebackResult(
            shop_id=shop_id,
            sm_id=sm.id,
            platform_sku=sm.sales_material_bn,
            calc_sellable=num,
            written=res.succ,
            reason="" if res.succ else res.err_msg,
            error_code=res.err_code,
            log_id=log.id,
        )

    # ---------- 批量 / 全量 ----------

    async def writeback_shop(
        self, shop_id: int, *, trigger: int = TRIGGER_SCHEDULE, force: bool = False
    ) -> list[WritebackResult]:
        """店铺全量回写（定时兜底 / 策略变更触发，FR-01d/FR-03a③）"""
        rows = list(
            await self.s.scalars(
                select(InvSalesMaterial).where(
                    InvSalesMaterial.shop_id == shop_id, InvSalesMaterial.is_deleted == 0
                )
            )
        )
        out: list[WritebackResult] = []
        for sm in rows:
            strategy = await self.sellable.get_strategy(shop_id, sm)
            rate = float(strategy.threshold_rate or 0) if strategy else 0.0
            out.append(
                await self.writeback(
                    shop_id, sm.id, trigger=trigger, force=force, threshold_rate=rate
                )
            )
        return out

    # ---------- 对账（FR-05a）----------

    async def recon_shop(self, shop_id: int) -> dict:
        """同步对账：拉平台库存 vs OMS 可售，差异强制回写"""
        rows = list(
            await self.s.scalars(
                select(InvSalesMaterial).where(
                    InvSalesMaterial.shop_id == shop_id, InvSalesMaterial.is_deleted == 0
                )
            )
        )
        diffs: list[dict] = []
        for sm in rows:
            # 传平台 SKU 编码（OMS 侧只知 SKU 编码；真实平台需 item_id，
            # 由商品档案维护 platform_item_id 映射——P1 补，当前模拟器支持按 SKU 查询）
            res = await self.gw.call(
                METHOD_ITEM_GET,
                {"item_id": sm.sales_material_bn},
                shop_id=shop_id,
                primary_bn=sm.sales_material_bn,
                source="reconcile",
            )
            if not res.succ:
                diffs.append(
                    {
                        "platform_sku": sm.sales_material_bn,
                        "platform_num": None,
                        "oms_num": None,
                        "action": "查询失败",
                        "error_code": res.err_code,
                    }
                )
                continue
            item = (res.data or {}).get("item") or {}
            skus = item.get("skus") or {}
            sku_list = skus.get("sku") if isinstance(skus, dict) else (skus or [])
            platform_num = 0
            for row in sku_list or []:
                if str(row.get("sku_id")) == sm.sales_material_bn or str(
                    row.get("outer_id")
                ) == sm.sales_material_bn:
                    platform_num = int(row.get("quantity") or 0)
                    break
            calc = await self.sellable.calc(shop_id, sm.id, use_cache=False)
            if platform_num != calc.sellable:
                diffs.append(
                    {
                        "platform_sku": sm.sales_material_bn,
                        "platform_num": platform_num,
                        "oms_num": calc.sellable,
                        "diff": platform_num - calc.sellable,
                        "action": "强制回写",
                    }
                )
                await self.writeback(
                    shop_id, sm.id, trigger=TRIGGER_RECON, force=True
                )
        return {"shop_id": shop_id, "checked": len(rows), "diff_count": len(diffs), "diffs": diffs}

    # ---------- 同步状态（IF-D04.08-04）----------

    async def sync_status(self, shop_id: int, skus: list[str] | None = None) -> list[dict]:
        """同步状态查询（供 D11.03 监控）"""
        q = select(InvSyncLog).where(InvSyncLog.shop_id == shop_id)
        if skus:
            q = q.where(InvSyncLog.platform_sku.in_(skus))
        rows = list(await self.s.scalars(q.order_by(InvSyncLog.id.desc()).limit(200)))
        out: list[dict] = []
        seen: set[str] = set()
        for row in rows:
            if row.platform_sku in seen:
                continue
            seen.add(row.platform_sku)
            out.append(
                {
                    "platform_sku": row.platform_sku,
                    "calc_sellable": row.calc_sellable,
                    "writeback_num": row.writeback_num,
                    "sync_status": row.sync_status,
                    "trigger_type": row.trigger_type,
                    "create_time": row.create_time.isoformat(),
                }
            )
        return out
