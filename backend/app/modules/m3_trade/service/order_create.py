"""订单接入与创建服务（D03.01 FR-01~FR-07）

**统一入口**（FR-01a）：五类来源（platform/local/import/exchange/b2b）
全部收敛为 canonical 标准模型后调用 `OrderCreateService.create()`，走同一套校验与落库。

**校验失败分级**（FR-04c）：
- 硬失败（店铺无效/授权过期/金额勾稽超差/行空）→ 拒单，落 `ord_order_fail`
  （独立列表人工处理，不进缓冲池）
- 软失败（地址待清洗/商品未绑定）→ 正常落库 + 结构化异常标记，暂缓投审

**落库范围**（FR-04a）：订单头 + 订单行（含 BOM 展开快照）+ 收货人（加密）+
优惠分摊（单级+行级）+ 状态日志，一个本地事务。

**四套状态初始化**（FR-05a）：audit=pending / fulfill=pending / ship=unshipped /
order=processing / pay 按报文（平台单=paid，0元单=paid，COD=unpaid）。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pipl import blind_index, encrypt, hash_fingerprint, tail4
from app.models.order import (
    OrdOrder,
    OrdOrderFail,
    OrdOrderItem,
    OrdOrderPmt,
    OrdReceiver,
    OrdStatusLog,
)
from app.models.shop import GwShop
from app.modules.m2_stock.service.sku_mapping import LineMapping, SkuMappingService
from app.modules.m3_trade.service.allocation import allocate, check_amount_consistency
from app.modules.m3_trade.service.order_bn import (
    PREFIX_EXCHANGE,
    PREFIX_IMPORT,
    PREFIX_LOCAL,
    PREFIX_PLATFORM,
    OrderBnGenerator,
)
from app.schemas import canonical as cc

#: 硬失败码（D03.01 FR-04c / ord_order_fail.fail_code 字典）
FAIL_SHOP_INVALID = "SHOP_INVALID"
FAIL_AUTH_EXPIRED = "AUTH_EXPIRED"
FAIL_AMOUNT_MISMATCH = "AMOUNT_MISMATCH"
FAIL_ITEM_EMPTY = "ITEM_EMPTY"
FAIL_REQUIRED_MISSING = "REQUIRED_MISSING"

#: 来源 → 订单前缀（FR-03a）
SOURCE_PREFIX = {
    "platform": PREFIX_PLATFORM,
    "local": PREFIX_LOCAL,
    "import": PREFIX_IMPORT,
    "exchange": PREFIX_EXCHANGE,
}


@dataclass
class OrderCreateResult:
    """建单结果"""

    order_id: int = 0
    order_bn: str = ""
    duplicated: bool = False
    hard_failure: str = ""
    hard_message: str = ""
    soft_failures: list[str] = field(default_factory=list)
    item_count: int = 0
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.hard_failure


class OrderCreateService:
    """订单接入与创建"""

    def __init__(
        self,
        session: AsyncSession,
        redis: Redis | None = None,
        gateway: Any | None = None,
    ):
        self.s = session
        self.r = redis
        self.gw = gateway

    # ---------- 主入口 ----------

    async def create(
        self,
        canonical: cc.CanonicalOrder,
        *,
        source: str = "platform",
        mapping: list[LineMapping] | None = None,
        shop: GwShop | None = None,
    ) -> OrderCreateResult:
        """统一建单入口（FR-01a）"""
        result = OrderCreateResult()

        # ① 幂等（FR-02a：平台单幂等键 = shop_id + platform_order_bn）
        existed = await self.s.scalar(
            select(OrdOrder).where(
                OrdOrder.shop_id == canonical.shop_id,
                OrdOrder.platform_order_bn == canonical.platform_order_bn,
                OrdOrder.is_deleted == 0,
            )
        )
        if existed is not None:
            result.order_id = existed.id
            result.order_bn = existed.order_bn
            result.duplicated = True
            return result

        # ② 店铺校验（硬失败）
        if shop is None:
            shop = await self.s.scalar(
                select(GwShop).where(
                    GwShop.id == canonical.shop_id, GwShop.is_deleted == 0
                )
            )
        if shop is None or shop.status != "enabled":
            return await self._hard_fail(
                canonical,
                source,
                FAIL_SHOP_INVALID,
                f"店铺无效或已停用: shop_id={canonical.shop_id}",
            )
        if shop.auth_status in ("expired", "disabled"):
            return await self._hard_fail(
                canonical,
                source,
                FAIL_AUTH_EXPIRED,
                f"店铺授权{shop.auth_status}：{shop.shop_name}",
            )

        # ③ 商品行校验（硬失败：行空 / 数量≤0）
        if not canonical.items:
            return await self._hard_fail(
                canonical, source, FAIL_ITEM_EMPTY, "商品行为空"
            )
        bad = [it.line_no for it in canonical.items if it.num <= 0]
        if bad:
            return await self._hard_fail(
                canonical,
                source,
                FAIL_ITEM_EMPTY,
                f"商品行数量必须 >0（行 {bad}）",
            )

        # ④ 物料映射与 BOM 展开快照（FR-04b/FR-04d；未命中 → 软失败）
        mapping_service = SkuMappingService(self.s, self.r, self.gw)
        line_maps: list[LineMapping] = []
        for item in canonical.items:
            if mapping:
                hit = next((m for m in mapping if m.line_no == item.line_no), None)
            else:
                hit = None
            if hit is None:
                hit = await mapping_service.map_line(
                    shop_id=canonical.shop_id,
                    line_no=item.line_no,
                    platform_sku_id=item.platform_sku_id,
                    platform_item_id=item.platform_item_id,
                    qty=item.num,
                )
            line_maps.append(hit)
            if hit.parse_status != "parsed":
                result.soft_failures.append(f"行{item.line_no}: {hit.message}")

        # ⑤ 优惠分摊（§5.2）+ 金额勾稽（FR-04b）
        line_pairs = [(it.line_no, round(it.list_amount, 2)) for it in canonical.items]
        platform_line = {
            it.line_no: round(it.platform_bear_line, 2)
            for it in canonical.items
            if it.platform_bear_line
        }
        allocs, alloc_warnings = allocate(
            line_pairs,
            shop_discount=canonical.merchant_bear_total,
            platform_subsidy=canonical.platform_bear_total,
            platform_line=platform_line or None,
        )
        result.warnings.extend(alloc_warnings)
        alloc_map = {a.line_no: a for a in allocs}
        ok, msg = check_amount_consistency(
            allocs, canonical.customer_paid, canonical.freight
        )
        if not ok:
            return await self._hard_fail(
                canonical, source, FAIL_AMOUNT_MISMATCH, msg
            )

        # ⑥ 订单号生成（FR-03）
        prefix = SOURCE_PREFIX.get(source, PREFIX_PLATFORM)
        gen = OrderBnGenerator(self.s, self.r)
        order_bn = await gen.next(prefix, shop.shop_bn)

        # ⑦ 合单指纹（FR-07a：只用盲索引成分）
        combine_hash = hash_fingerprint(
            [
                blind_index(canonical.receiver.name),
                blind_index(canonical.receiver.mobile),
                canonical.receiver.district,
                blind_index(canonical.receiver.address),
                "1" if canonical.is_cod else "0",
                str(canonical.shop_id),
            ]
        )

        # ⑧ 四套状态初始化（FR-05a）
        pay_status = "paid"
        if canonical.is_cod:
            pay_status = "unpaid"
        if canonical.customer_paid == 0 and not canonical.is_cod:
            pay_status = "paid"  # 0 元单免支付校验

        order = OrdOrder(
            owner_id=shop.owner_id,
            order_bn=order_bn,
            platform_order_bn=canonical.platform_order_bn,
            shop_id=canonical.shop_id,
            createway=source,
            order_type=canonical.order_type,
            order_status="processing",
            audit_status="pending",
            fulfill_status="pending",
            pay_status=pay_status,
            ship_status="unshipped",
            list_amount=canonical.total_amount,
            shop_discount=canonical.merchant_bear_total,
            platform_subsidy=canonical.platform_bear_total,
            paid_amount=canonical.customer_paid,
            freight=canonical.freight,
            is_cod=1 if canonical.is_cod else 0,
            promotion_source=canonical.promotion_source,
            promotion_pid=canonical.promotion_pid,
            promotion_id=canonical.promotion_id,
            buyer_id_enc=encrypt(canonical.receiver.buyer_id),
            buyer_nick=canonical.receiver.buyer_nick,
            order_time=canonical.platform_create_time,
            pay_time=canonical.pay_time,
            combine_hash=combine_hash,
            flag_color=canonical.flag_color,
            urge_flag=canonical.urge_flag,
            urge_cnt=canonical.urge_cnt,
            warehouse_memo=canonical.seller_memo,
            buyer_memo=canonical.buyer_message,
            platform_extra={
                "platform": canonical.platform_extra.get("platform", {}),
                "canonical_status": canonical.canonical_status,
                "platform_status": canonical.platform_status,
                "platform_modified": canonical.platform_modified.isoformat(),
                "convert_warnings": canonical.convert_warnings,
                "soft_failures": result.soft_failures,
                "receiver_encrypted_channel": canonical.receiver.encrypted_channel,
            },
            source="api",
        )
        self.s.add(order)
        await self.s.flush()

        # ⑨ 订单行（FR-04d：BOM 展开快照固化）
        item_count = 0
        for item in canonical.items:
            hit = next((m for m in line_maps if m.line_no == item.line_no), None)
            alloc = alloc_map.get(item.line_no)
            owner_id = hit.owner_id if hit else shop.owner_id
            bm_id = hit.bm_id if hit else 0
            bm_number = hit.bm_number if hit else ""
            bm_name = hit.bm_name if hit else ""
            parse_status = hit.parse_status if hit else "pending"
            self.s.add(
                OrdOrderItem(
                    owner_id=owner_id,
                    order_id=order.id,
                    sm_id=hit.sm_id if hit else 0,
                    platform_sku_code=item.platform_sku_id,
                    platform_oid=item.oid,
                    bm_id=bm_id,
                    bm_number=bm_number,
                    bm_name=bm_name,
                    nums=item.num,
                    list_price=item.sale_price,
                    list_amount=item.list_amount,
                    shop_discount=alloc.shop_discount if alloc else 0,
                    platform_subsidy=alloc.platform_subsidy if alloc else 0,
                    paid_amount=alloc.paid_amount if alloc else item.list_amount,
                    bom_version=hit.bom_version if hit else 0,
                    is_gift=item.gift_flag,
                    parse_status=parse_status,
                    platform_extra={
                        "goods_name": item.goods_name,
                        "sku_spec": item.sku_spec,
                        "platform_item_id": item.platform_item_id,
                        "expanded": [e.as_dict() for e in hit.expanded] if hit else [],
                        "auto_created": hit.auto_created if hit else False,
                    },
                )
            )
            item_count += 1
            # 组合装子行（FR-04d：展开为多行基础物料明细，金额按 rate 分摊继承）
            if hit and len(hit.expanded) > 1:
                for sub in hit.expanded[1:]:
                    self.s.add(
                        OrdOrderItem(
                            owner_id=sub.owner_id,
                            order_id=order.id,
                            sm_id=hit.sm_id,
                            platform_sku_code=item.platform_sku_id,
                            platform_oid=item.oid,
                            bm_id=sub.bm_id,
                            bm_number=sub.bm_number,
                            bm_name=sub.bm_name,
                            nums=sub.qty,
                            list_price=item.sale_price,
                            list_amount=round(item.list_amount * sub.rate / 100, 2),
                            shop_discount=0,
                            platform_subsidy=0,
                            paid_amount=round(item.list_amount * sub.rate / 100, 2),
                            bom_version=hit.bom_version,
                            is_virtual=1 if sub.is_virtual else 0,
                            is_gift=item.gift_flag,
                            parse_status="parsed",
                            platform_extra={"parent_line_no": item.line_no, "rate": sub.rate},
                        )
                    )
                    item_count += 1

        # ⑩ 收货人（PIPL 加密 + 盲索引，FR-04f）
        self.s.add(
            OrdReceiver(
                owner_id=shop.owner_id,
                order_id=order.id,
                name_enc=encrypt(canonical.receiver.name),
                name_hash=blind_index(canonical.receiver.name),
                mobile_enc=encrypt(canonical.receiver.mobile),
                mobile_hash=blind_index(canonical.receiver.mobile),
                mobile_tail4=tail4(canonical.receiver.mobile),
                province=canonical.receiver.province,
                city=canonical.receiver.city,
                district=canonical.receiver.district,
                address_enc=encrypt(canonical.receiver.address),
                address_hash=blind_index(canonical.receiver.address),
                zip=canonical.receiver.zip,
                is_cipher=1 if canonical.receiver.encrypted_channel != "none" else 0,
                cipher_blob=canonical.receiver.cipher_blob,
                key_version="v1",
            )
        )

        # ⑪ 优惠分摊落 ord_order_pmt（单级 + 行级，FR-06c）
        for pmt in canonical.promotions:
            self.s.add(
                OrdOrderPmt(
                    owner_id=shop.owner_id,
                    order_id=order.id,
                    item_id=None,
                    pmt_type=pmt.pmt_type,
                    bearer="shop" if pmt.bear_by == "shop" else "platform",
                    amount=pmt.amount,
                    platform_pmt_id=pmt.promotion_id,
                )
            )
        if canonical.merchant_bear_total:
            self.s.add(
                OrdOrderPmt(
                    owner_id=shop.owner_id,
                    order_id=order.id,
                    item_id=None,
                    pmt_type="shop_discount",
                    bearer="shop",
                    amount=canonical.merchant_bear_total,
                )
            )
        if canonical.platform_bear_total:
            self.s.add(
                OrdOrderPmt(
                    owner_id=shop.owner_id,
                    order_id=order.id,
                    item_id=None,
                    pmt_type="platform_coupon",
                    bearer="platform",
                    amount=canonical.platform_bear_total,
                )
            )
        for alloc in allocs:
            if alloc.shop_discount or alloc.platform_subsidy:
                self.s.add(
                    OrdOrderPmt(
                        owner_id=shop.owner_id,
                        order_id=order.id,
                        item_id=None,
                        pmt_type="line_discount",
                        bearer="shop" if alloc.shop_discount else "platform",
                        amount=round(alloc.shop_discount + alloc.platform_subsidy, 2),
                    )
                )

        # ⑫ 状态初始化日志（FR-05b：变迁留痕）
        for domain, value in (
            ("audit", "pending"),
            ("fulfill", "pending"),
            ("pay", pay_status),
            ("ship", "unshipped"),
            ("order", "processing"),
        ):
            self.s.add(
                OrdStatusLog(
                    owner_id=shop.owner_id,
                    order_id=order.id,
                    order_bn=order_bn,
                    status_domain=domain,
                    from_value="",
                    to_value=value,
                    trigger_source="D03.01",
                    operator="system",
                    memo="订单接入初始化",
                )
            )

        await self.s.commit()
        await self.s.refresh(order)
        result.order_id = order.id
        result.order_bn = order_bn
        result.item_count = item_count
        return result

    # ---------- 硬失败 ----------

    async def _hard_fail(
        self,
        canonical: cc.CanonicalOrder,
        source: str,
        fail_code: str,
        reason: str,
    ) -> OrderCreateResult:
        """硬失败：落接入失败单（FR-04c），不进缓冲池"""
        # 失败单号：Redis 发号（同一秒内可能多张失败单 → 秒级时间戳会撞唯一键）
        fail_seq = 0
        if self.r is not None:
            try:
                fail_seq = int(await self.r.incr(f"seq:order_fail:{datetime.now():%Y%m%d}"))
            except Exception:
                fail_seq = 0
        fail_bn = f"FAIL{datetime.now():%Y%m%d}{fail_seq:06d}"
        self.s.add(
            OrdOrderFail(
                owner_id=0,
                fail_bn=fail_bn,
                shop_id=canonical.shop_id,
                platform_order_bn=canonical.platform_order_bn,
                createway=source,
                fail_code=fail_code,
                fail_reason=reason,
                raw_payload=canonical.model_dump(mode="json"),
                handle_status="pending",
            )
        )
        await self.s.commit()
        return OrderCreateResult(
            hard_failure=fail_code, hard_message=reason
        )
