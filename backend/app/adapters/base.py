"""平台适配器接口层（D02.01 §5.1 五层管线 / D02.02 适配器接口）

五层拆分（每平台声明绑定，多为「默认实现 + 个别覆写」）：

| 层 | 接口 | 默认实现 | 覆写场景 |
|---|---|---|---|
| 配置层 | PlatformConfig | 读 gw_adapter_config / gw_platform_config | 平台特有方法映射 |
| 签名层 | SignStrategy | md5 / hmac-sha256 | 平台特有签名规则 |
| 传输层 | Transport | httpx + 连接池 + 重试 | 需要代理/证书的平台 |
| 报文层 | MessageFormat | JSON | XML 平台 |
| 日志层 | CallLogger | api_log 落库（脱敏+截断） | 额外指标上报 |

统一方法名（FR-06）→ 平台原生方法名映射由适配器声明，
模拟器与真实 TOP 使用同一套统一方法名（切换 driver 即可，业务域零改动）。
"""

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class AdapterResult:
    """统一结果（MessageFormat.decode 的输出）"""

    succ: bool
    data: Any = None
    err_code: str = ""
    err_msg: str = ""
    msg_id: str = ""
    raw: dict = field(default_factory=dict)

    @property
    def trades(self) -> list[dict]:
        """平台单列表（trade.sold.get 的 trades 数组）"""
        return (self.data or {}).get("trades", []) if isinstance(self.data, dict) else []

    @property
    def total_results(self) -> int:
        """总条数（分页依据）"""
        if isinstance(self.data, dict):
            return int(self.data.get("total_results", 0) or 0)
        return 0


@dataclass
class AppCredential:
    """应用/店铺凭证（生产从 gw_shop_auth 取密文解密后使用）"""

    app_key: str = ""
    app_secret: str = ""
    access_token: str = ""
    session_key: str = ""

    @property
    def is_usable(self) -> bool:
        return bool(self.app_key and self.app_secret)


@dataclass
class RateLimitRule:
    """限流规则（D02.01 FR-05）"""

    capacity: int = 100
    rate_per_sec: float = 20.0
    scope: str = "platform"


class PlatformConfig(Protocol):
    """配置层"""

    def gateway_url(self, method: str) -> str: ...

    def credential(self, shop_id: int) -> AppCredential: ...

    def rate_limit_rule(self, method: str, shop_id: int) -> RateLimitRule: ...


class SignStrategy(Protocol):
    """签名层"""

    def sign(self, params: dict, secret: str) -> str: ...

    def verify(self, params: dict, sign: str, secret: str) -> bool: ...


class Transport(Protocol):
    """传输层"""

    async def send(
        self, method: str, url: str, payload: dict, timeout: float
    ) -> tuple[int, dict]: ...


class MessageFormat(Protocol):
    """报文层"""

    def encode(self, params: dict) -> dict: ...

    def decode(self, response: dict) -> AdapterResult: ...


class CallLogger(Protocol):
    """日志层"""

    async def log(
        self,
        *,
        method: str,
        native_method: str,
        platform: str,
        shop_id: int,
        primary_bn: str,
        request_params: dict,
        response_body: dict,
        http_status: int,
        err_code: str,
        err_level: str,
        spend_ms: int,
        source: str,
        msg_id: str = "",
    ) -> None: ...


class AdapterInterface(Protocol):
    """平台适配器（D02.02）

    业务域只依赖本接口，不感知平台差异（FR-04a）。
    """

    platform: str
    adapter_version: str
    mapping_version: str

    async def call(
        self, method: str, params: dict, *, shop_id: int = 0, primary_bn: str = ""
    ) -> AdapterResult: ...

    def walk_list(
        self,
        *,
        shop_id: int,
        start_time: Any,
        end_time: Any,
        page_size: int = 50,
        max_pages: int = 200,
    ) -> AsyncIterator[AdapterResult]: ...

    async def order_detail(
        self, *, shop_id: int, platform_order_bn: str, primary_bn: str = ""
    ) -> AdapterResult: ...

    async def item_get(
        self, *, shop_id: int, platform_item_id: str, primary_bn: str = ""
    ) -> AdapterResult: ...


# ============ 统一方法名常量（FR-06 方法名字典）============

METHOD_TRADE_SOLD_GET = "taobao.trade.sold.get"
METHOD_TRADE_DETAIL_GET = "taobao.trade.detail.get"
METHOD_ITEM_GET = "taobao.item.get"
METHOD_LOGISTICS_SEND = "taobao.logistics.online.send"
METHOD_REFUND_GET = "taobao.refund.get"
METHOD_REFUND_LIST_GET = "taobao.refund.list.get"


class UnifiedMethod:
    """统一方法名 → 平台原生方法名（模拟器与真实 TOP 同名）"""

    NATIVE_MAP = {
        METHOD_TRADE_SOLD_GET: METHOD_TRADE_SOLD_GET,
        METHOD_TRADE_DETAIL_GET: METHOD_TRADE_DETAIL_GET,
        METHOD_ITEM_GET: METHOD_ITEM_GET,
        METHOD_LOGISTICS_SEND: METHOD_LOGISTICS_SEND,
        METHOD_REFUND_GET: METHOD_REFUND_GET,
        METHOD_REFUND_LIST_GET: METHOD_REFUND_LIST_GET,
    }

    @classmethod
    def native(cls, method: str) -> str:
        return cls.NATIVE_MAP.get(method, method)
