"""淘系（TaoBao）平台适配器（D02.02）

**driver 切换**（业务域零改动）：
- `platform.driver=simulator`（默认）→ 对接 mock-platform（`POST {base}/api/taobao/router`），
  走模拟器的 TOP 风格签名与错误码，用于 M1-M3 仿真开发与内测
- `platform.driver=taobao` → 真实淘系开放平台（`https://eco.taobao.com/router/rest`）

两种 driver 使用**同一套统一方法名与同一套 canonical 转换**，切换只改配置。

canonical 转换（FR-04a）：平台报文 → CanonicalOrder。
字段映射见 `docs/canonical订单字段映射.md`。
"""

import hashlib
import time
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx

from app.adapters.base import (
    METHOD_ITEM_GET,
    METHOD_TRADE_DETAIL_GET,
    METHOD_TRADE_SOLD_GET,
    AdapterResult,
    AppCredential,
    RateLimitRule,
    UnifiedMethod,
)
from app.core.config import settings
from app.schemas import canonical as cc

#: 平台状态 → canonical 状态（映射表见 docs/canonical订单字段映射.md §4.1）
STATUS_MAP = {
    "WAIT_BUYER_PAY": "unpaid",
    "WAIT_SELLER_SEND_GOODS": "unshipped",
    "WAIT_BUYER_CONFIRM_GOODS": "shipped",
    "TRADE_CLOSED": "closed",
    "TRADE_CLOSED_BY_TAOBAO": "closed",
    "TRADE_FINISHED": "finished",
}

#: 行级退款状态映射
REFUND_STATUS_MAP = {
    "NO_REFUND": "none",
    "REFUNDING": "refunding",
    "REFUNDED": "refunded",
}

_TS_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f")


def parse_time(value: Any) -> datetime | None:
    """解析平台时间（多种格式兜底）"""
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    s = str(value).strip()
    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


class TaobaoSignStrategy:
    """签名层：md5(secret + 排序拼接 + secret) 大写（TOP 风格）"""

    def sign(self, params: dict, secret: str) -> str:
        payload = "".join(
            f"{k}{params[k]}" for k in sorted(params) if k not in ("sign", "sign_method")
        )
        return hashlib.md5(f"{secret}{payload}{secret}".encode()).hexdigest().upper()

    def verify(self, params: dict, sign: str, secret: str) -> bool:
        expect = self.sign(params, secret)
        return hashlib.md5(expect.encode()).hexdigest() == hashlib.md5(sign.encode()).hexdigest()


class TaobaoConfig:
    """配置层（driver 决定网关地址）"""

    platform = "taobao"
    adapter_version = "taobao-adapter/1.0"
    mapping_version = "canonical-map/1.0"

    def gateway_url(self, method: str) -> str:
        if settings.platform_driver == "taobao":
            return "https://eco.taobao.com/router/rest"
        return f"{settings.platform_gateway_url.rstrip('/')}/api/taobao/router"

    def credential(self, shop_id: int) -> AppCredential:
        return AppCredential(
            app_key=settings.platform_app_key,
            app_secret=settings.platform_app_secret,
        )

    def rate_limit_rule(self, method: str, shop_id: int) -> RateLimitRule:
        # 真实淘系：调用频次按 app 维度（通常 20 次/秒）；模拟器不限流但保留规则位
        return RateLimitRule(capacity=40, rate_per_sec=20.0, scope="platform")


class TaobaoTransport:
    """传输层（httpx + 超时；重试在网关层做）"""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client
        self._owned = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        return self._client

    async def close(self) -> None:
        if self._client and self._owned:
            await self._client.aclose()
            self._client = None

    async def send(
        self, method: str, url: str, payload: dict, timeout: float
    ) -> tuple[int, dict]:
        client = await self._get_client()
        resp = await client.post(url, json=payload, timeout=timeout)
        try:
            body = resp.json()
        except Exception:
            body = {"_raw": resp.text[:2000]}
        return resp.status_code, body


class TaobaoMessageFormat:
    """报文层（JSON；TOP 包裹 error_response / {method}_response）"""

    def encode(self, params: dict) -> dict:
        return params

    def decode(self, response: dict) -> AdapterResult:
        err = response.get("error_response")
        if err:
            code = str(err.get("code", "isv.unknown-error"))
            msg = str(err.get("msg", "")) or str(err.get("sub_msg", ""))
            return AdapterResult(
                succ=False,
                err_code=code,
                err_msg=msg,
                raw=response,
            )
        # 取第一个以 _response 结尾的键
        for key, val in response.items():
            if key.endswith("_response") and isinstance(val, dict):
                return AdapterResult(succ=True, data=val, raw=response)
        return AdapterResult(succ=False, err_code="isv.empty-response", raw=response)


class TaobaoAdapter:
    """淘系适配器（实现 AdapterInterface）"""

    platform = TaobaoConfig.platform
    adapter_version = TaobaoConfig.adapter_version
    mapping_version = TaobaoConfig.mapping_version

    def __init__(
        self,
        transport: TaobaoTransport | None = None,
        signer: TaobaoSignStrategy | None = None,
        cfg: TaobaoConfig | None = None,
    ):
        self.cfg = cfg or TaobaoConfig()
        self.signer = signer or TaobaoSignStrategy()
        self.transport = transport or TaobaoTransport()
        self.fmt = TaobaoMessageFormat()

    # ---------- 底层调用 ----------

    async def call(
        self,
        method: str,
        params: dict,
        *,
        shop_id: int = 0,
        primary_bn: str = "",
        session_key: str = "",
    ) -> AdapterResult:
        cred = self.cfg.credential(shop_id)
        payload: dict[str, Any] = {
            "method": UnifiedMethod.native(method),
            "app_key": cred.app_key,
            "timestamp": str(int(time.time())),
            "v": "2.0",
            "format": "json",
            "sign_method": "md5",
        }
        if session_key:
            payload["session"] = session_key
        payload.update({k: v for k, v in params.items() if v is not None})
        payload["sign"] = self.signer.sign(payload, cred.app_secret)
        url = self.cfg.gateway_url(method)
        status, body = await self.transport.send(method, url, payload, timeout=30.0)
        if status != 200:
            return AdapterResult(
                succ=False,
                err_code=f"http.{status}",
                err_msg=str(body)[:500],
                raw=body,
            )
        return self.fmt.decode(body)

    # ---------- AdapterInterface ----------

    async def walk_list(
        self,
        *,
        shop_id: int,
        start_time: Any,
        end_time: Any,
        page_size: int = 50,
        max_pages: int = 200,
        status: str = "",
    ) -> AsyncIterator[AdapterResult]:
        """增量窗口分页拉取（D02.03 FR-02c）"""
        page_no = 1
        while page_no <= max_pages:
            params: dict[str, Any] = {
                "page_no": page_no,
                "page_size": page_size,
                "start_modified": _fmt_ts(start_time),
                "end_modified": _fmt_ts(end_time),
            }
            if status:
                params["status"] = status
            res = await self.call(METHOD_TRADE_SOLD_GET, params, shop_id=shop_id)
            if not res.succ:
                yield res
                return
            yield res
            if not res.trades or len(res.trades) < page_size:
                return
            page_no += 1

    async def order_detail(
        self, *, shop_id: int, platform_order_bn: str, primary_bn: str = ""
    ) -> AdapterResult:
        """单拉补偿（FR-03a：拉全量详情，不信任消息体）"""
        return await self.call(
            METHOD_TRADE_DETAIL_GET,
            {"tid": platform_order_bn},
            shop_id=shop_id,
            primary_bn=primary_bn,
        )

    async def item_get(
        self, *, shop_id: int, platform_item_id: str, primary_bn: str = ""
    ) -> AdapterResult:
        """商品查询（未知商品自动建档 FR-05a）"""
        return await self.call(
            METHOD_ITEM_GET,
            {"item_id": platform_item_id},
            shop_id=shop_id,
            primary_bn=primary_bn,
        )

    async def close(self) -> None:
        await self.transport.close()


def _fmt_ts(value: Any) -> str:
    """时间 → 平台格式（'%Y-%m-%d %H:%M:%S'）"""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value or "")


def to_canonical(
    trade: dict, *, shop_id: int, platform: str = "taobao"
) -> cc.CanonicalOrder:
    """平台 trade 报文 → canonical 标准订单（D02.03 FR-04a）

    关键策略：
    - 双口径金额：平台承担取 `platform_bear_amount`；商家承担由恒等式反推
      （merchant = total − paid + freight − platform_bear）
    - 行级：平台承担的优惠直接采用平台行级值 `divide_order_fee`（FR-06b 平台值优先），
      商家承担部分留给 OMS 侧比例分摊（§5.2）
    - 未知状态/缺失字段 → 记 convert_warnings，不静默降级
    """
    orders = trade.get("orders") or []
    canonical_status = STATUS_MAP.get(str(trade.get("status", "")), "")
    warnings: list[str] = []
    if not canonical_status:
        canonical_status = "unshipped"
        warnings.append(f"未知平台状态: {trade.get('status')}")

    total_amount = float(trade.get("total_fee") or 0)
    customer_paid = float(trade.get("buyer_pay_amount") or 0)
    freight = float(trade.get("post_fee") or 0)
    platform_bear = float(trade.get("platform_bear_amount") or 0)
    if platform_bear == 0 and (total_amount or customer_paid):
        warnings.append("平台承担金额缺失，按恒等式反推")
    merchant_bear = round(total_amount - customer_paid + freight - platform_bear, 2)
    if merchant_bear < 0:
        # 平台报文金额不自洽（平台承担 > 可优惠额）→ 钳制并告警，不静默产生负数
        warnings.append(f"商家承担金额为负({merchant_bear})，已钳制为 0（平台报文金额不自洽）")
        merchant_bear = 0.0

    items: list[cc.CanonicalOrderItem] = []
    for idx, sub in enumerate(orders, start=1):
        sku_id = str(sub.get("sku_id") or sub.get("outer_id") or "")
        if not sku_id:
            warnings.append(f"第{idx}行缺少平台SKU编码")
        num = int(sub.get("num") or 0)
        price = float(sub.get("price") or 0)
        line_list = float(sub.get("total_fee") or price * num)
        items.append(
            cc.CanonicalOrderItem(
                line_no=idx,
                oid=str(sub.get("oid") or ""),
                platform_sku_id=sku_id,
                platform_item_id=str(sub.get("item_id") or ""),
                goods_name=str(sub.get("item_title") or ""),
                sku_spec=str(sub.get("sku_spec") or ""),
                num=num,
                sale_price=price,
                list_amount=line_list,
                # 平台行级分摊值（平台承担的优惠）
                platform_bear_line=float(sub.get("divide_order_fee") or 0),
                customer_paid_line=round(line_list - float(sub.get("divide_order_fee") or 0), 2),
                merchant_bear_line=0,
                refund_status=REFUND_STATUS_MAP.get(
                    str(sub.get("refund_status") or "NO_REFUND"), "none"
                ),
                gift_flag=1 if sub.get("gift") else 0,
                platform_extra={"raw": sub},
            )
        )

    modified = parse_time(trade.get("modified")) or datetime.now()
    created = parse_time(trade.get("created")) or modified
    pay_time = parse_time(trade.get("pay_time"))

    receiver = cc.CanonicalReceiver(
        name=str(trade.get("receiver_name") or ""),
        mobile=str(trade.get("receiver_mobile") or ""),
        province=str(trade.get("receiver_state") or ""),
        city=str(trade.get("receiver_city") or ""),
        district=str(trade.get("receiver_district") or ""),
        address=str(trade.get("receiver_address") or ""),
        zip=str(trade.get("receiver_zip") or ""),
        buyer_nick=str(trade.get("buyer_nick") or ""),
        encrypted_channel=str(trade.get("receiver_encrypted_channel") or "none"),
        cipher_blob=({"oaid": trade.get("oaid")} if trade.get("oaid") else None),
    )

    order = cc.CanonicalOrder(
        platform=platform,
        shop_id=shop_id,
        platform_order_bn=str(trade.get("tid") or ""),
        order_type="normal",
        platform_status=str(trade.get("status") or ""),
        canonical_status=canonical_status,
        platform_modified=modified,
        platform_create_time=created,
        pay_time=pay_time,
        total_amount=total_amount,
        customer_paid=customer_paid,
        platform_bear_total=platform_bear,
        merchant_bear_total=merchant_bear,
        freight=freight,
        buyer_message=str(trade.get("buyer_message") or ""),
        seller_memo=str(trade.get("seller_memo") or ""),
        receiver=receiver,
        items=items,
        platform_extra={
            "platform": {
                "consign_time": trade.get("consign_time"),
                "logistics_type": trade.get("logistics_type"),
                "shipping_type": trade.get("shipping_type"),
                "warehouse_hint": trade.get("warehouse_hint"),
                "logistics_hint": trade.get("logistics_hint"),
                "raw_status": trade.get("status"),
            }
        },
        convert_warnings=warnings,
    )
    # 旗帜：平台 seller_flag 1-5 → OMS flag_color（FR-04h）
    seller_flag = int(trade.get("seller_flag") or 0)
    if seller_flag:
        order.flag_color = cc.PLATFORM_FLAG_COLOR_MAP.get(seller_flag, 0)
    return order
