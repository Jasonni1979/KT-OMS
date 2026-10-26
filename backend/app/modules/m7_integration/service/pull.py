"""拉单服务（D02.03 FR-02 轮询通道 / FR-03 单拉补偿与幂等落库管线）

**拉单三保险**（D02.03 §5.2）：
1. 轮询增量（主通道）：水位窗口 `[last − overlap, now − safety_delay]`，只进不退
2. 单拉补偿（次通道）：消息触发 / 人工补偿 / 重试反查 / 对账核实
3. 每日全量对账（兜底）：M1 阶段未实现（依赖 D02.05 反查倒灌）

**幂等路由（FR-03c 版本收敛）**：
`本地不存在 → create`；`报文更新 → update`；`报文相等或更旧 → skip`；
`平台状态=已关闭 且 本地未投递 → close`。

**七步落库管线（FR-03d）**：预置日志 → canonical 转换 → 准入校验 →
商品映射与未知商品建档 → 幂等路由 → 缓冲落库 → 投递 D03.01。
"""

from datetime import datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.base import METHOD_TRADE_SOLD_GET
from app.adapters.taobao import _fmt_ts, to_canonical
from app.core.logging import get_logger
from app.core.pipl import blind_index, encrypt
from app.models.gateway import (
    GwOrderBuffer,
    GwOrderBufferItem,
    GwPullWatermark,
)
from app.models.shop import GwShop
from app.modules.m2_stock.service.sku_mapping import LineMapping, SkuMappingService
from app.modules.m7_integration.service.gateway import Gateway
from app.schemas import canonical as cc

logger = get_logger("pull")

#: 单次拉取窗口上限（D02.03 FR-02b：超限分片）
MAX_WINDOW = timedelta(hours=2)
#: 单页条数
DEFAULT_PAGE_SIZE = 50


class PullService:
    """拉单服务"""

    def __init__(self, session: AsyncSession, gateway: Gateway, redis: Redis):
        self.s = session
        self.gw = gateway
        self.r = redis

    # ---------- 水位 ----------

    async def get_watermark(self, shop_id: int, channel: str = "order") -> GwPullWatermark:
        """取水位（不存在则按默认参数创建）"""
        wm = await self.s.scalar(
            select(GwPullWatermark).where(
                GwPullWatermark.shop_id == shop_id,
                GwPullWatermark.channel == channel,
            )
        )
        if wm is None:
            wm = GwPullWatermark(
                shop_id=shop_id,
                channel=channel,
                # DDL NOT NULL → 首次建行给回溯起点（24h），与首轮窗口口径一致
                last_download_time=datetime.now() - timedelta(hours=24),
                overlap_sec=300,
                safety_delay_sec=60,
                poll_interval_sec=60,
                lag_alert_threshold_sec=1800,
            )
            self.s.add(wm)
            await self.s.commit()
            await self.s.refresh(wm)
        return wm

    async def _advance_watermark(
        self, wm: GwPullWatermark, new_time: datetime
    ) -> bool:
        """CAS 推进水位（只进不退，D02.03 FR-02a）"""
        if wm.last_download_time and new_time <= wm.last_download_time:
            return False
        res = await self.s.execute(
            update(GwPullWatermark)
            .where(
                GwPullWatermark.id == wm.id,
                GwPullWatermark.version == wm.version,
            )
            .values(
                last_download_time=new_time,
                version=GwPullWatermark.version + 1,
            )
        )
        await self.s.commit()
        return int(getattr(res, 'rowcount', 0) or 0) > 0

    # ---------- 轮询 ----------

    async def poll_shop(
        self, shop_id: int, *, channel: str = "order"
    ) -> dict[str, Any]:
        """轮询拉单（FR-02）：返回处理统计"""
        shop = await self.s.scalar(
            select(GwShop).where(GwShop.id == shop_id, GwShop.is_deleted == 0)
        )
        if not shop:
            return {"ok": False, "reason": f"店铺不存在: {shop_id}"}

        wm = await self.get_watermark(shop_id, channel)
        now = datetime.now()
        end_time = now - timedelta(seconds=wm.safety_delay_sec)
        # 增量窗口：水位 − overlap（重叠区防漏单，重复由幂等吸收）
        start_time = (
            wm.last_download_time - timedelta(seconds=wm.overlap_sec)
            if wm.last_download_time
            else end_time - timedelta(hours=24)
        )
        if start_time >= end_time:
            return {"ok": True, "created": 0, "updated": 0, "skipped": 0, "reason": "窗口为空"}

        # 窗口超 2h → 分片（FR-02b）
        segments: list[tuple[datetime, datetime]] = []
        cur = start_time
        while cur < end_time:
            nxt = min(cur + MAX_WINDOW, end_time)
            segments.append((cur, nxt))
            cur = nxt

        stat: dict[str, Any] = {
            "ok": True, "created": 0, "updated": 0, "skipped": 0,
            "closed": 0, "errors": 0,
        }
        window_end = start_time
        for seg_start, seg_end in segments:
            ok = await self._pull_window(shop, seg_start, seg_end, stat)
            if not ok:
                # 该窗口失败 → 不推水位（FR-02c：宁可重复不可漏）
                stat["ok"] = False
                break
            window_end = seg_end

        if stat["ok"]:
            await self._advance_watermark(wm, window_end)
        stat["window_start"] = start_time.isoformat()
        stat["window_end"] = window_end.isoformat()
        return stat

    async def _pull_window(
        self,
        shop: GwShop,
        seg_start: datetime,
        seg_end: datetime,
        stat: dict[str, Any],
    ) -> bool:
        """拉一个时间窗（分页迭代 + 逐单处理）"""
        async for res in self.gw.walk_list(
            METHOD_TRADE_SOLD_GET,
            {
                "start_modified": _fmt_ts(seg_start),
                "end_modified": _fmt_ts(seg_end),
            },
            shop_id=shop.id,
            primary_bn=f"pull:{shop.id}",
            page_size=DEFAULT_PAGE_SIZE,
        ):
            if not res.succ:
                stat["errors"] += 1
                return False
            for trade in res.trades:
                try:
                    outcome = await self._ingest_trade(shop, trade)
                except Exception as exc:
                    # 不静默吞异常：记录到日志，便于定位（拉单丢单是隐蔽故障）
                    logger.error(
                        "ingest_trade_failed",
                        tid=str(trade.get("tid") or ""),
                        error=str(exc),
                        exc_info=True,
                    )
                    stat["errors"] += 1
                    continue
                stat[outcome] = stat.get(outcome, 0) + 1
        return True

    # ---------- 单拉补偿（FR-03a）----------

    async def pull_single(
        self, shop_id: int, platform_order_bn: str, reason: str = "manual"
    ) -> dict[str, Any]:
        """单拉补偿：拉全量详情并按幂等路由落库"""
        shop = await self.s.scalar(
            select(GwShop).where(GwShop.id == shop_id, GwShop.is_deleted == 0)
        )
        if not shop:
            return {"ok": False, "reason": f"店铺不存在: {shop_id}"}
        res = await self.gw.adapter.order_detail(
            shop_id=shop_id,
            platform_order_bn=platform_order_bn,
            primary_bn=platform_order_bn,
        )
        if not res.succ:
            return {"ok": False, "err_code": res.err_code, "err_msg": res.err_msg}
        trade = (res.data or {}).get("trade") or {}
        outcome = await self._ingest_trade(shop, trade)
        return {"ok": True, "outcome": outcome, "reason": reason}

    # ---------- 幂等路由 + 缓冲落库（FR-03c/03d）----------

    async def _ingest_trade(self, shop: GwShop, trade: dict) -> str:
        """单笔平台单 → canonical → 物料映射 → 幂等路由 → 缓冲落库 → 投递订单域"""
        order = to_canonical(trade, shop_id=shop.id, platform="taobao")
        if not order.platform_order_bn:
            return "errors"
        if not order.items:
            # 行空 = 硬失败（D03.01 FR-04c）→ 落失败单，不进缓冲池
            await self._record_fail(order, "ITEM_EMPTY", "商品行为空")
            return "errors"

        # ④ 商品映射与未知商品自动建档（D02.03 FR-05，落库管线第④步）
        mapper = SkuMappingService(self.s, self.r, self.gw)
        mapping: list[LineMapping] = []
        for item in order.items:
            mapping.append(
                await mapper.map_line(
                    shop_id=order.shop_id,
                    line_no=item.line_no,
                    platform_sku_id=item.platform_sku_id,
                    platform_item_id=item.platform_item_id,
                    qty=item.num,
                )
            )

        existing = await self.s.scalar(
            select(GwOrderBuffer).where(
                GwOrderBuffer.platform == order.platform,
                GwOrderBuffer.shop_id == order.shop_id,
                GwOrderBuffer.platform_order_bn == order.platform_order_bn,
                GwOrderBuffer.is_deleted == 0,
            )
        )
        if existing is None:
            await self._save_buffer(shop, order, mapping, create=True)
            return await self._deliver(order, mapping)
        # 版本收敛：报文不新于本地 → skip
        if existing.platform_modified and order.platform_modified <= existing.platform_modified:
            if (
                order.canonical_status == "closed"
                and existing.deliver_status in ("pending", "waiting")
            ):
                existing.deliver_status = "closed"
                existing.canonical_status = "closed"
                await self.s.commit()
                return "closed"
            return "skipped"
        await self._save_buffer(shop, order, mapping, create=False, buffer_id=existing.id)
        return await self._deliver(order, mapping)

    async def _deliver(self, order: cc.CanonicalOrder, mapping: list[LineMapping]) -> str:
        """⑦ 投递 D03.01（订单域建单）

        M1c 阶段同步投递（无 MQ 时序表）；投递结果回写缓冲状态：
        - 成功 → deliver_status=accepted
        - 幂等重复 → deliver_status=accepted（订单已存在）
        - 硬失败 → deliver_status=fail（保留缓冲等待人工/重投）
        """
        from app.modules.m3_trade.service.order_create import OrderCreateService

        oc = OrderCreateService(self.s, self.r, self.gw)
        res = await oc.create(order, source="platform", mapping=mapping)
        buffer = await self.s.scalar(
            select(GwOrderBuffer).where(
                GwOrderBuffer.platform == order.platform,
                GwOrderBuffer.shop_id == order.shop_id,
                GwOrderBuffer.platform_order_bn == order.platform_order_bn,
                GwOrderBuffer.is_deleted == 0,
            )
        )
        if buffer is not None:
            if res.hard_failure:
                buffer.deliver_status = "fail"
                buffer.deliver_times += 1
                buffer.last_deliver_time = datetime.now()
            else:
                buffer.deliver_status = "accepted"
                buffer.deliver_times += 1
                buffer.last_deliver_time = datetime.now()
            await self.s.commit()
        if res.hard_failure:
            return "errors"
        return "skipped" if res.duplicated else "created"

    async def _save_buffer(
        self,
        shop: GwShop,
        order: cc.CanonicalOrder,
        mapping: list[LineMapping],
        *,
        create: bool,
        buffer_id: int | None = None,
    ) -> None:
        """canonical → 缓冲池落库（收货人 PIPL 加密）"""
        data = {
            "owner_id": shop.owner_id,
            # 缓冲单号（DDL 唯一键 uk_gw_order_buffer_bn，NOT NULL）
            "buffer_bn": await self._next_buffer_bn(),
            "platform": order.platform,
            "shop_id": order.shop_id,
            "platform_order_bn": order.platform_order_bn,
            "order_type": order.order_type,
            "platform_status": order.platform_status,
            "canonical_status": order.canonical_status,
            "platform_modified": order.platform_modified,
            "pay_time": order.pay_time,
            "platform_create_time": order.platform_create_time,
            "total_amount": order.total_amount,
            "customer_paid": order.customer_paid,
            "platform_bear_total": order.platform_bear_total,
            "freight": order.freight,
            "buyer_message": order.buyer_message,
            "seller_memo": order.seller_memo,
            # PIPL 加密（D02.03 FR-04b）
            "receiver_name_enc": encrypt(order.receiver.name),
            "receiver_mobile_enc": encrypt(order.receiver.mobile),
            "receiver_mobile_hash": blind_index(order.receiver.mobile),
            "receiver_province": order.receiver.province,
            "receiver_city": order.receiver.city,
            "receiver_district": order.receiver.district,
            "receiver_address_enc": encrypt(order.receiver.address),
            "receiver_zip": order.receiver.zip,
            "oaid_json": order.receiver.cipher_blob,
            "receiver_encrypted_channel": order.receiver.encrypted_channel,
            "warehouse_hint": order.warehouse_hint,
            "logistics_hint": order.logistics_hint,
            "platform_extra": order.platform_extra,
            "convert_warnings": order.convert_warnings,
            "adapter_version": self.gw.adapter.adapter_version,
            "mapping_version": self.gw.adapter.mapping_version,
            "deliver_status": "pending",
            "source": "api",
        }
        buffer: GwOrderBuffer
        if create:
            buffer = GwOrderBuffer(**data)
            self.s.add(buffer)
            await self.s.flush()
        else:
            existing = await self.s.scalar(
                select(GwOrderBuffer).where(GwOrderBuffer.id == buffer_id)
            )
            if existing is None:
                buffer = GwOrderBuffer(**data)
                self.s.add(buffer)
                await self.s.flush()
            else:
                for k, v in data.items():
                    setattr(existing, k, v)
                existing.version += 1
                buffer = existing
        await self.s.flush()

        # 明细行（重建式覆盖，避免重复累加）
        await self.s.execute(
            delete(GwOrderBufferItem).where(GwOrderBufferItem.buffer_id == buffer.id)
        )
        sm_by_line = {m.line_no: m.sm_id for m in mapping if m.sm_id}
        for item in order.items:
            self.s.add(
                GwOrderBufferItem(
                    buffer_id=buffer.id,
                    line_no=item.line_no,
                    local_sku_id=sm_by_line.get(item.line_no),
                    oid=item.oid,
                    platform_sku_id=item.platform_sku_id,
                    platform_item_id=item.platform_item_id,
                    goods_name=item.goods_name,
                    sku_spec=item.sku_spec,
                    num=item.num,
                    sale_price=item.sale_price,
                    customer_paid_line=item.customer_paid_line,
                    platform_bear_line=item.platform_bear_line,
                    merchant_bear_line=item.merchant_bear_line,
                    refund_status=item.refund_status,
                    gift_flag=item.gift_flag,
                    platform_extra=item.platform_extra,
                )
            )
        await self.s.commit()

    async def _record_fail(
        self, order: cc.CanonicalOrder, fail_code: str, reason: str
    ) -> None:
        """接入失败单（D03.01 FR-04c 硬失败：独立列表人工处理）"""
        from app.models.order import OrdOrderFail

        self.s.add(
            OrdOrderFail(
                owner_id=0,
                fail_bn=f"FAIL{datetime.now():%Y%m%d}{await self._next_seq('fail')}",
                shop_id=order.shop_id,
                platform_order_bn=order.platform_order_bn,
                createway="platform",
                fail_code=fail_code,
                fail_reason=reason,
                raw_payload=order.model_dump(mode="json"),
                handle_status="pending",
            )
        )
        await self.s.commit()

    async def _next_buffer_bn(self) -> str:
        """缓冲单号发号（Redis INCR，DDL 唯一键 uk_gw_order_buffer_bn）"""
        seq = await self._next_seq("buffer_bn")
        return f"BUF{datetime.now():%Y%m%d}{seq:06d}"

    async def _next_seq(self, kind: str) -> int:
        """Redis 发号（失败单号等）"""
        try:
            return int(await self.r.incr(f"seq:{kind}:{datetime.now():%Y%m%d}"))
        except Exception:
            return int(datetime.now().timestamp() % 100000)
