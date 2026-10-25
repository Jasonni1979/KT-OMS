"""WMS 协议适配器接口层（D09.01 §1.2 协议适配器抽象 + D09.02 通道执行方）

**协议差异不出适配器层**（D09.01 核心约束）：业务编排（发货单、状态机）
不进通道层，协议转换（奇门 XML 风格 vs 通天晓 JSON RESTful）不进业务域。

首批实现：
- `QimenAdapter`（奇门风格）：`POST {endpoint}?method=deliveryorder.create`
- `TtxRestAdapter`（通天晓 RESTful）：`POST {endpoint}/wms/restful/outbound`

统一方法名（内部用）→ WMS 原生路径映射由适配器声明。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


@dataclass
class WmsRoute:
    """路由四元组（D09.01 FR-04a）+ binding_id"""

    wms_id: int
    binding_id: int
    adapter_code: str
    #: 账号配置（app_key / secret）
    app_key: str = ""
    secret: str = ""
    #: WMS 侧仓编码
    wms_branch_code: str = ""
    #: WMS 侧货主编码（一仓多货主按绑定账号区分，D09.01 SC-03）
    wms_owner_code: str = ""
    #: 协议
    protocol: str = "qimen"
    #: 端点
    endpoint: str = ""
    timeout_ms: int = 10000
    #: 能力矩阵
    capability: dict[str, Any] = field(default_factory=dict)
    #: 降级标记（熔断时 route 返回 degraded=buffer）
    degraded: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "wms_id": self.wms_id,
            "binding_id": self.binding_id,
            "adapter_code": self.adapter_code,
            "wms_branch_code": self.wms_branch_code,
            "wms_owner_code": self.wms_owner_code,
            "protocol": self.protocol,
            "endpoint": self.endpoint,
            "timeout_ms": self.timeout_ms,
            "capability": dict(self.capability),
            "degraded": self.degraded,
        }


@dataclass
class WmsCallResult:
    """通道调用结果"""

    succ: bool
    #: WMS 侧单号（受理应答回填）
    wms_bill_no: str = ""
    #: 错误码（原始）
    err_code: str = ""
    #: 错误分类（RETRYABLE / FATAL / BIZ_REJECT）—— D09.02 §5.4
    err_class: str = ""
    err_msg: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    spend_ms: int = 0
    #: 是否已受理（幂等重复下发时为 True）
    duplicated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "succ": self.succ,
            "wms_bill_no": self.wms_bill_no,
            "err_code": self.err_code,
            "err_class": self.err_class,
            "err_msg": self.err_msg,
            "spend_ms": self.spend_ms,
            "duplicated": self.duplicated,
        }


class WmsAdapter(Protocol):
    """WMS 适配器接口（D09.01 协议适配器抽象）"""

    adapter_code: str
    protocol: str

    async def outbound_push(
        self, route: WmsRoute, payload: dict[str, Any]
    ) -> WmsCallResult: ...

    async def outbound_cancel(
        self, route: WmsRoute, payload: dict[str, Any]
    ) -> WmsCallResult: ...

    async def query_order(
        self, route: WmsRoute, cmd_no: str
    ) -> WmsCallResult: ...

    def build_payload(
        self, dto: dict[str, Any], route: WmsRoute
    ) -> dict[str, Any]:
        """标准指令 DTO → WMS 原生报文"""
        ...


#: 错误码 → 分类映射（D09.02 §5.4）
ERR_CLASS_MAP: dict[str, str] = {
    # 可重试：网络/超时/系统忙/限流
    "wms.timeout": "RETRYABLE",
    "wms.system-busy": "RETRYABLE",
    "wms.lock-conflict": "RETRYABLE",
    "wms.network-error": "RETRYABLE",
    "wms.service-unavailable": "RETRYABLE",
    "wms.recall-rejected": "RETRYABLE",
    # 终态失败：报文/配置/权限
    "wms.invalid-payload": "FATAL",
    "wms.invalid-signature": "FATAL",
    "wms.no-permission": "FATAL",
    "wms.service-closed": "FATAL",
    "wms.method-not-allowed": "FATAL",
    "wms.order-not-exist": "FATAL",
    "wms.unknown-error": "FATAL",
    # 业务拒绝
    "wms.business-reject": "BIZ_REJECT",
}


def classify(err_code: str) -> str:
    """错误分类（D09.02 §5.4）"""
    return ERR_CLASS_MAP.get(err_code, "RETRYABLE")


def sign_payload(payload: dict[str, Any], secret: str) -> str:
    """通道签名：md5(app_key + 排序拼接 + secret) 大写"""
    import hashlib
    import hmac

    body = {k: v for k, v in payload.items() if k != "sign"}
    raw = "".join(f"{k}{body[k]}" for k in sorted(body))
    return hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest().upper()


class _BaseHttpAdapter:
    """HTTP 传输基类（连接池 + 超时 + 错误翻译）"""

    adapter_code = "base"
    protocol = "restful"

    async def _post(
        self,
        route: WmsRoute,
        url: str,
        payload: dict[str, Any],
        *,
        sign_field: str = "sign",
    ) -> WmsCallResult:
        import time

        body = dict(payload)
        body[sign_field] = sign_payload(body, route.secret)
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=route.timeout_ms / 1000) as client:
                resp = await client.post(url, json=body)
            spend = int((time.monotonic() - started) * 1000)
            try:
                data = resp.json()
            except Exception:
                return WmsCallResult(
                    succ=False,
                    err_code="wms.invalid-payload",
                    err_class="FATAL",
                    err_msg=f"响应非 JSON: {resp.text[:200]}",
                    raw={"status": resp.status_code},
                    spend_ms=spend,
                )
            return self._parse(data, spend)
        except httpx.TimeoutException as e:
            return WmsCallResult(
                succ=False,
                err_code="wms.timeout",
                err_class="RETRYABLE",
                err_msg=f"请求超时: {e}",
                spend_ms=int((time.monotonic() - started) * 1000),
            )
        except Exception as e:
            return WmsCallResult(
                succ=False,
                err_code="wms.network-error",
                err_class="RETRYABLE",
                err_msg=str(e)[:200],
                spend_ms=int((time.monotonic() - started) * 1000),
            )

    def _parse(self, data: dict[str, Any], spend: int) -> WmsCallResult:
        """统一响应解析：{code:0 成功, code!=0 错误}

        注意：WMS 侧错误码是**字符串**（如 wms.timeout），成功码是数字 0。
        """
        raw_code = data.get("code", -1)
        is_ok = raw_code == 0 or raw_code == "0"
        if is_ok:
            payload = data.get("data") or {}
            return WmsCallResult(
                succ=True,
                wms_bill_no=str(payload.get("wms_bill_no", "") or ""),
                duplicated=bool(payload.get("duplicated", False)),
                raw=data,
                spend_ms=spend,
            )
        err_code = str(raw_code if raw_code not in (None, -1) else "")
        # 模拟器用字符串码（如 wms.timeout），此处兼容
        err_class = str(data.get("err_class", "") or "") or classify(err_code)
        return WmsCallResult(
            succ=False,
            err_code=err_code,
            err_class=err_class,
            err_msg=str(data.get("msg", "") or "")[:200],
            raw=data,
            spend_ms=spend,
        )


class TtxRestAdapter(_BaseHttpAdapter):
    """通天晓 RESTful 适配器"""

    adapter_code = "ttx-adapter"
    protocol = "ttx_rest"

    def build_payload(self, dto: dict[str, Any], route: WmsRoute) -> dict[str, Any]:
        """标准 DTO → 通天晓 JSON 报文"""
        return {
            "cmd_no": dto.get("cmd_no", ""),
            "warehouse_code": route.wms_branch_code,
            "owner_code": route.wms_owner_code or dto.get("owner_code", ""),
            "waybill_no": dto.get("waybill_no", ""),
            "print_ref": dto.get("print_ref", ""),
            "lines": dto.get("lines", []),
            "remark": dto.get("remark", ""),
        }

    async def outbound_push(
        self, route: WmsRoute, payload: dict[str, Any]
    ) -> WmsCallResult:
        base = (route.endpoint or "").rstrip("/")
        return await self._post(route, f"{base}/wms/restful/outbound", payload)

    async def outbound_cancel(
        self, route: WmsRoute, payload: dict[str, Any]
    ) -> WmsCallResult:
        base = (route.endpoint or "").rstrip("/")
        return await self._post(route, f"{base}/wms/restful/cancel", payload)

    async def query_order(
        self, route: WmsRoute, cmd_no: str
    ) -> WmsCallResult:
        base = (route.endpoint or "").rstrip("/")
        return await self._post(route, f"{base}/wms/restful/query", {"cmd_no": cmd_no})


class QimenAdapter(_BaseHttpAdapter):
    """奇门风格适配器（method 参数路由）"""

    adapter_code = "qimen-adapter"
    protocol = "qimen"

    def build_payload(self, dto: dict[str, Any], route: WmsRoute) -> dict[str, Any]:
        """标准 DTO → 奇门风格报文"""
        return {
            "cmd_no": dto.get("cmd_no", ""),
            "warehouse_code": route.wms_branch_code,
            "owner_code": route.wms_owner_code or dto.get("owner_code", ""),
            "waybill_no": dto.get("waybill_no", ""),
            "print_ref": dto.get("print_ref", ""),
            "lines": dto.get("lines", []),
            "remark": dto.get("remark", ""),
        }

    async def outbound_push(
        self, route: WmsRoute, payload: dict[str, Any]
    ) -> WmsCallResult:
        base = (route.endpoint or "").rstrip("/")
        return await self._post(
            route, f"{base}/wms/qimen/deliveryorder.create", payload
        )

    async def outbound_cancel(
        self, route: WmsRoute, payload: dict[str, Any]
    ) -> WmsCallResult:
        base = (route.endpoint or "").rstrip("/")
        return await self._post(
            route, f"{base}/wms/qimen/deliveryorder.cancel", payload
        )

    async def query_order(
        self, route: WmsRoute, cmd_no: str
    ) -> WmsCallResult:
        base = (route.endpoint or "").rstrip("/")
        return await self._post(
            route, f"{base}/wms/qimen/deliveryorder.get", {"cmd_no": cmd_no}
        )


class FluxRestAdapter(TtxRestAdapter):
    """flux（其他 RESTful WMS）——与通天晓同协议族"""

    adapter_code = "flux-adapter"
    protocol = "restful"


#: 适配器注册表（D09.01 协议适配器注册机制）
ADAPTERS: dict[str, WmsAdapter] = {
    "ttx-adapter": TtxRestAdapter(),
    "qimen-adapter": QimenAdapter(),
    "flux-adapter": FluxRestAdapter(),
}


def get_adapter(adapter_code: str) -> WmsAdapter | None:
    """取适配器实例（D09.01 适配器注册表）"""
    return ADAPTERS.get(adapter_code)
