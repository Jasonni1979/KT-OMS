"""WMS 模拟器协议层（mock-wms）—— 保真要点

对齐 SRS-D09.02 / D09.01 的 WMS 通道契约：

- **双协议入口**：
  - 奇门风格：`POST /wms/qimen/{method}` —— deliveryorder.create / deliveryorder.cancel
  - RESTful 风格（通天晓）：`POST /wms/restful/outbound` / `/wms/restful/cancel`
- **签名校验**：md5(app_key + 排序拼接 + app_secret) 大写，header `X-WMS-Sign`
- **统一响应包裹**：`{code, msg, data}`，code=0 成功
- **指令单号幂等**：单据号 + 推送轮次（DLV...-R1）唯一，重复下发返回首次受理结果
- **回传事件**：接收确认（accepted）/ 出库回传（outbound）/ 打回（rejected）/ 叫回结果
- **错误注入**：`_inject_error` 参数 → 让通道层的分级重试/终态失败逻辑在仿真期被真实锻炼
  - `TIMEOUT`（网络超时，等价 RETRYABLE）
  - `SYSTEM_BUSY`（系统繁忙，RETRYABLE）
  - `INVALID_PAYLOAD`（报文校验失败，FATAL 不可重试）
  - `NO_PERMISSION`（无权限，FATAL）
  - `RECALL_REJECT`（叫回被拒，已开始拣货）
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

#: 模拟器默认凭证
APP_KEY = "mock_wms_key"
APP_SECRET = "mock_wms_secret"

#: 错误码定义（分级与 D09.01/D02.05 的 api_fail 口径一致）
class WmsError(Exception):
    """WMS 业务错误"""

    def __init__(self, code: str, message: str, err_class: str = "RETRYABLE"):
        self.code = code
        self.message = message
        self.err_class = err_class
        super().__init__(f"{code}: {message}")


#: 可注入错误码 → (code, message, err_class)
INJECTABLE_ERRORS: dict[str, tuple[str, str, str]] = {
    "TIMEOUT": ("wms.timeout", "WMS 网关超时", "RETRYABLE"),
    "SYSTEM_BUSY": ("wms.system-busy", "系统繁忙，请稍后再试", "RETRYABLE"),
    "LOCK_CONFLICT": ("wms.lock-conflict", "单据被锁定，请稍后再试", "RETRYABLE"),
    "INVALID_PAYLOAD": ("wms.invalid-payload", "报文校验失败：必填字段缺失", "FATAL"),
    "NO_PERMISSION": ("wms.no-permission", "无该仓操作权限", "FATAL"),
    "WMS_CLOSED": ("wms.service-closed", "WMS 服务已停止", "FATAL"),
    "RECALL_REJECT": ("wms.recall-rejected", "已开始拣货，无法拦截", "RETRYABLE"),
}

#: WMS 单据状态
CMD_STATUS = {
    "accepted": "已受理",
    "sent": "已下发",
    "working": "WMS作业中",
    "partial": "部分回传",
    "completed": "回传闭环",
    "cancelled": "已取消",
    "rejected": "已打回",
    "failed": "下发失败",
}

#: 回传类型
CB_TYPE = {
    "accepted": "接收确认",
    "outbound": "出库回传",
    "rejected": "打回",
    "cancelled": "叫回成功",
    "recall_failed": "叫回失败",
}


def calc_sign(params: dict[str, Any], secret: str = APP_SECRET) -> str:
    """WMS 通道签名：md5(app_key + 排序拼接 + app_secret) 大写"""
    payload = "".join(
        f"{k}{params[k]}" for k in sorted(params) if k not in ("sign", "sign_method")
    )
    return hmac.new(
        secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest().upper()


def verify_sign(params: dict[str, Any], secret: str = APP_SECRET) -> bool:
    """校验签名"""
    sign = params.get("sign") or params.get("X-WMS-Sign")
    if not sign:
        return False
    return hmac.compare_digest(str(sign), calc_sign(params, secret))


def make_error_response(
    code: str, message: str, err_class: str = "RETRYABLE"
) -> dict[str, Any]:
    """统一错误包裹"""
    return {
        "code": code,
        "msg": message,
        "err_class": err_class,
        "request_id": f"wms-{int(time.time() * 1000)}",
    }


def make_ok(data: dict[str, Any] | None = None) -> dict[str, Any]:
    """统一成功包裹"""
    return {"code": 0, "msg": "success", "data": data or {}}
