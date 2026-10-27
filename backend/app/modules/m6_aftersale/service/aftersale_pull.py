"""平台售后报文自动同步（D05.01 FR-01a · G1 缺口补齐）

**缺口**：平台侧买家发起的「仅退款 / 退货退款」此前**不会自动进 OMS** ——
售后申请单只能靠人工在 M6 侧建单（`AftersaleService.create_apply`），
平台售后与 OMS 订单脱节 → 审核 / 退款链路无法自动流转。

**本服务**把平台售后报文按增量窗口拉回来并落成售后申请单：

```
① 增量拉取   taobao.refund.list.get（modified 时间窗 → 走 M7 网关，限流 + api_log 留痕）
② 报文映射   refund_type → 售后类型；refund_amount → 双口径金额；num → 申请数量
③ 原单关联   按 platform_order_bn 找 OMS 订单 + 订单行（FR-01e）
④ 幂等落库   (platform, shop_id, platform_aftersale_bn) 三键（FR-01b）+ 版本收敛（FR-01c）
⑤ 错误统计   created / idempotent / updated / skipped / errors / pending_link
```

⚠ **模块归属**：本服务属 **M6（售后域）** —— 售后申请单是 M6 的表；
   平台 IO 走 **M7 的 Gateway**（跨模块只走 `contract.py`，门禁 R2）。
   反过来放 M7 会违反 M7 契约「不得 import M6」。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.aftersale import AftReturnApply
from app.models.order import OrdOrder, OrdOrderItem
from app.modules.m6_aftersale.service.aftersale import AftersaleService
from app.modules.m6_aftersale.service.aftersale_codes import (
    GOODS_RECEIVED,
    GOODS_SHIPPED,
    GOODS_UNSHIPPED,
    ST_PENDING_LINK,
    TYPE_EXCHANGE,
    TYPE_REFUND_ONLY,
    TYPE_RESHIPMENT,
    TYPE_RETURN_REFUND,
)
from app.modules.m7_integration.contract import Gateway

logger = get_logger("aftersale_pull")

#: 平台售后类型 → OMS 售后类型（D05.01 FR-01d）
REFUND_TYPE_MAP: dict[str, int] = {
    "ONLY_REFUND": TYPE_REFUND_ONLY,
    "RETURN_GOODS": TYPE_RETURN_REFUND,
    "EXCHANGE": TYPE_EXCHANGE,
    "RESHIPMENT": TYPE_RESHIPMENT,
}

#: OMS 订单发货状态 → 货物状态（D05.01 goods_status：0=未发货 1=已发货未收 2=已收货）
SHIP_STATUS_MAP: dict[str, int] = {
    "unshipped": GOODS_UNSHIPPED,
    "partial": GOODS_SHIPPED,
    "shipped": GOODS_SHIPPED,
    "partial_return": GOODS_RECEIVED,
    "returned": GOODS_RECEIVED,
}

#: 平台原因文案关键词 → OMS 标准原因码（D05.01 §5.5，字典 `aft_reason_dict` 同码）
REASON_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("七天无理由", "SEVEN_NO_REASON"),
    ("无理由", "SEVEN_NO_REASON"),
    ("不想要", "WRONG_PURCHASE"),
    ("拍错", "WRONG_PURCHASE"),
    ("多拍", "WRONG_PURCHASE"),
    ("质量", "QUALITY_ISSUE"),
    ("破损", "DAMAGED"),
    ("少件", "MISSING_ITEM"),
    ("漏发", "MISSING_ITEM"),
    ("物流", "LOGISTICS_ISSUE"),
    ("未收到", "BUYER_NO_RECEIVE"),
)

#: 原因未命中时的兜底码（D05.01 §5.5：其他-待归类）
REASON_FALLBACK = "OTHER_UNCLASSIFIED"

#: 单页条数
DEFAULT_PAGE_SIZE = 50
#: 单次拉取最大页数（防御平台异常分页）
MAX_PAGES = 50


def _goods_status(aftersale_type: int, ship_status: str) -> int:
    """货物状态推导（D05.01 goods_status）

    - 退货退款 / 换货：货已在买家手上 → 已收货
    - 仅退款 / 补发：按 OMS 订单发货状态推导
    """
    if aftersale_type in (TYPE_RETURN_REFUND, TYPE_EXCHANGE):
        return GOODS_RECEIVED
    return SHIP_STATUS_MAP.get(str(ship_status or ""), GOODS_UNSHIPPED)


def _reason_code(msg: dict) -> str:
    """平台售后原因 → OMS 标准原因码（D05.01 §5.5）

    优先级：① 平台质检不良标记 → ② 平台原因文案关键词 → ③ 兜底「其他-待归类」。
    """
    if str(msg.get("goods_condition") or "") == "QUALITY_DEFECTIVE":
        return "QUALITY_ISSUE"
    text = str(msg.get("reason") or "")
    for keyword, code in REASON_KEYWORDS:
        if keyword in text:
            return code
    return REASON_FALLBACK


class AftersalePullService:
    """平台售后报文自动同步（D05.01 FR-01a）"""

    def __init__(self, session: AsyncSession, gateway: Gateway, redis: Any = None) -> None:
        self.s = session
        self.gw = gateway
        self.r = redis

    # ---------- 主流程 ----------

    async def pull_refunds(
        self,
        shop_id: int,
        *,
        start_modified: Any,
        end_modified: Any,
        platform: str = "taobao",
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = MAX_PAGES,
    ) -> dict[str, Any]:
        """拉取平台售后报文并落成售后申请单（FR-01a）

        返回统计：
        - `total` 平台返回的报文条数
        - `created` 新建申请单数
        - `idempotent` 命中幂等（复用已有单）的报文数
        - `updated` 幂等命中且平台报文更新（版本收敛 → 刷新平台元信息）
        - `skipped` 报文不完整 / 无法定位订单行（可重放）
        - `errors` 平台调用失败或落库异常
        - `pending_link` 落「待关联」异常态（订单未进 OMS）
        """
        stat: dict[str, Any] = {
            "ok": True,
            "platform": platform,
            "shop_id": shop_id,
            "total": 0,
            "created": 0,
            "idempotent": 0,
            "updated": 0,
            "skipped": 0,
            "errors": 0,
            "pending_link": 0,
        }
        messages, err = await self._fetch(
            shop_id, start_modified, end_modified, page_size, max_pages
        )
        if err is not None:
            stat["ok"] = False
            stat["err_code"] = err[0]
            stat["err_msg"] = err[1]
            return stat

        stat["total"] = len(messages)
        aft = AftersaleService(self.s, self.r)
        for msg in messages:
            try:
                await self._ingest(aft, shop_id, platform, msg, stat)
            except Exception as exc:
                # 不静默吞异常：写日志（售后丢单是隐蔽故障）
                logger.error(
                    "aftersale_ingest_failed",
                    refund_id=str(msg.get("refund_id") or ""),
                    error=str(exc),
                    exc_info=True,
                )
                stat["errors"] += 1
        return stat

    # ---------- 平台拉取 ----------

    async def _fetch(
        self,
        shop_id: int,
        start_modified: Any,
        end_modified: Any,
        page_size: int,
        max_pages: int,
    ) -> tuple[list[dict], tuple[str, str] | None]:
        """分页拉取平台售后报文（走 M7 网关 → 限流 + api_log 留痕）

        ⚠ 模拟器的 `taobao.refund.list.get` **忽略分页参数**（一次返回窗口内全部），
          真实淘系按 page_no/page_size 分页 → 用 `total_results` 收敛，
          两种语义都能正确终止。
        """
        out: list[dict] = []
        page_no = 1
        while page_no <= max_pages:
            res = await self.gw.refund_list_get(
                shop_id=shop_id,
                start_modified=start_modified,
                end_modified=end_modified,
                page_no=page_no,
                page_size=page_size,
                primary_bn=f"aftersale_pull:{shop_id}",
            )
            if not res.succ:
                return out, (res.err_code or "isv.unknown-error", res.err_msg or "")
            page = res.refunds
            out.extend(page)
            total = res.total_results
            if not page or len(out) >= (total or len(out)):
                break
            if len(page) < page_size:
                break
            page_no += 1
        return out, None

    # ---------- 单条报文落库 ----------

    async def _ingest(
        self,
        aft: AftersaleService,
        shop_id: int,
        platform: str,
        msg: dict,
        stat: dict[str, Any],
    ) -> None:
        """单条平台售后报文 → 售后申请单"""
        refund_id = str(msg.get("refund_id") or "").strip()
        platform_order_bn = str(msg.get("tid") or "").strip()
        raw_type = str(msg.get("refund_type") or "")
        aftersale_type = REFUND_TYPE_MAP.get(raw_type.upper())
        if not refund_id or aftersale_type is None:
            stat["skipped"] += 1
            logger.warning(
                "aftersale_msg_incomplete",
                refund_id=refund_id,
                refund_type=raw_type,
                reason="缺平台售后单号或售后类型不可识别",
            )
            return
        amount = round(float(msg.get("refund_amount") or 0), 2)
        if amount < 0:
            stat["skipped"] += 1
            logger.warning(
                "aftersale_amount_invalid",
                refund_id=refund_id,
                refund_amount=msg.get("refund_amount"),
                reason="平台退款金额为负",
            )
            return

        # 幂等（FR-01b）：三键命中 → 复用已有单；报文更新则刷新平台元信息（FR-01c）
        existing = await self.s.scalar(
            select(AftReturnApply).where(
                AftReturnApply.platform == platform,
                AftReturnApply.shop_id == shop_id,
                AftReturnApply.platform_aftersale_bn == refund_id,
            )
        )
        if existing is not None:
            stat["idempotent"] += 1
            if await self._refresh_platform_meta(existing, msg, raw_type):
                stat["updated"] += 1
            return

        order = await self._find_order(shop_id, platform_order_bn)
        goods_status = GOODS_UNSHIPPED
        items: list[dict[str, Any]] = []
        if order is not None:
            goods_status = _goods_status(aftersale_type, order.ship_status)
            lines, why = await self._locate_lines(order, msg)
            if not lines:
                stat["skipped"] += 1
                logger.warning(
                    "aftersale_line_unmatched",
                    refund_id=refund_id,
                    order_id=int(order.id),
                    reason=why,
                )
                return
            apply_num = int(msg.get("num") or 0) or 1
            for line in lines:
                if apply_num > int(line.nums or 0):
                    # 平台报数 > OMS 行购买数（数据不自洽）→ 不硬失败，留待人工
                    stat["skipped"] += 1
                    logger.warning(
                        "aftersale_num_exceeds_line",
                        refund_id=refund_id,
                        order_item_id=int(line.id),
                        apply_num=apply_num,
                        line_nums=int(line.nums or 0),
                        reason="平台申请数量超过订单行购买数量",
                    )
                    return
                items.append(
                    {
                        "order_item_id": int(line.id),
                        "oid": str(line.platform_oid or ""),
                        "bm_id": int(line.bm_id or 0),
                        "sku_name": str(line.bm_name or ""),
                        "apply_num": apply_num,
                        "apply_amount_customer_line": amount,
                        "apply_amount_platform_bear_line": 0,
                        "gift_flag": int(line.is_gift or 0),
                    }
                )

        row, _created = await aft.create_apply(
            aftersale_type=aftersale_type,
            platform=platform,
            shop_id=shop_id,
            platform_aftersale_bn=refund_id,
            platform_order_bn=platform_order_bn,
            order_id=int(order.id) if order is not None else 0,
            items=items,
            reason_code=_reason_code(msg),
            reason_raw=str(msg.get("reason") or ""),
            buyer_claim=str(msg.get("buyer_claim") or msg.get("desc") or ""),
            apply_amount_customer=amount,
            apply_amount_platform_bear=round(
                float(msg.get("platform_bear_amount") or 0), 2
            ),
            source="platform",
            goods_status=goods_status,
        )
        stat["created"] += 1
        if int(row.status) == ST_PENDING_LINK:
            stat["pending_link"] += 1
        await self._write_platform_meta(row, msg, raw_type)

    # ---------- 订单 / 订单行定位 ----------

    async def _find_order(
        self, shop_id: int, platform_order_bn: str
    ) -> OrdOrder | None:
        """按平台单号找 OMS 订单（FR-01e 原单关联）"""
        if not platform_order_bn:
            return None
        stmt = select(OrdOrder).where(
            OrdOrder.platform_order_bn == platform_order_bn,
            OrdOrder.is_deleted == 0,
        )
        if shop_id:
            stmt = stmt.where(OrdOrder.shop_id == shop_id)
        return await self.s.scalar(stmt)

    async def _locate_lines(
        self, order: OrdOrder, msg: dict
    ) -> tuple[list[OrdOrderItem], str]:
        """按平台报文定位 OMS 订单行（FR-01e / FR-02f）

        匹配优先级：① 平台子单号 oid → ② 平台 SKU → ③ 单行订单直接归位
        （平台报文可能只带商品池 SKU，与真实下单行不一致）。
        """
        lines = list(
            await self.s.scalars(
                select(OrdOrderItem)
                .where(
                    OrdOrderItem.order_id == order.id,
                    OrdOrderItem.is_deleted == 0,
                )
                .order_by(OrdOrderItem.id)
            )
        )
        if not lines:
            return [], "订单无有效行"
        oid = str(msg.get("oid") or "")
        if oid:
            hit = [ln for ln in lines if str(ln.platform_oid or "") == oid]
            if hit:
                return hit[:1], ""
        sku = str(msg.get("sku_id") or "")
        if sku:
            hit = [ln for ln in lines if str(ln.platform_sku_code or "") == sku]
            if hit:
                return hit[:1], ""
        if len(lines) == 1:
            return lines, ""
        return [], f"订单 {len(lines)} 行，平台报文 sku={sku or '-'} 无法定位"

    # ---------- 平台原始信息回填（FR-04b/FR-04c）----------

    async def _write_platform_meta(
        self, row: AftReturnApply, msg: dict, raw_type: str
    ) -> None:
        """回填平台原始信息（生成列 `platform_refund_id` / `platform_aftersale_type_raw` 依赖它）"""
        row.platform_extra = {
            "refund_id": str(msg.get("refund_id") or ""),
            "aftersale_type_raw": raw_type,
            "goods_condition": str(msg.get("goods_condition") or ""),
            "platform_order_bn": str(msg.get("tid") or ""),
            "raw": msg,
        }
        row.platform_status_raw = str(msg.get("status") or "")
        row.platform_modified_version = str(msg.get("modified") or "")
        await self.s.commit()

    async def _refresh_platform_meta(
        self, row: AftReturnApply, msg: dict, raw_type: str
    ) -> bool:
        """版本收敛（FR-01c）：平台报文更新 → 刷新平台元信息；报文更旧 → 保留本地"""
        new_version = str(msg.get("modified") or "")
        old_version = str(row.platform_modified_version or "")
        if not new_version or (old_version and new_version <= old_version):
            return False
        await self._write_platform_meta(row, msg, raw_type)
        return True
