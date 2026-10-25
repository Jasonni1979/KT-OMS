"""淘系平台模拟器（mock-platform）—— 保真要点（V1.1 计划 §2.1）

- TOP 风格统一入口：`POST /api/taobao/router`，method 参数路由
- TOP 风格签名校验：md5(secret + 排序拼接 + secret) 大写，支持 hmac-sha256
- 统一响应包裹：`error_response` / `{method}_response` + total_results
- 典型错误码：isv.invalid-signature / isv.session-expired / isv.trade-service-error / flow-limit
- 增量语义：按 modified 时间窗过滤 + page_no/page_size 分页
- 错误注入：`_inject_error` 参数（让适配器重试/降级逻辑在仿真期被真实锻炼）
"""
from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

# ---------------- 签名（TOP 风格） ----------------

def calc_sign(params: dict[str, Any], secret: str, sign_method: str = "md5") -> str:
    """TOP 签名：md5(secret + k1v1k2v2... + secret) 大写；hmac-sha256 为简化实现"""
    payload = "".join(
        f"{k}{params[k]}" for k in sorted(params) if k not in ("sign", "sign_method")
    )
    if sign_method == "hmac-sha256":
        return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest().upper()
    return hashlib.md5(f"{secret}{payload}{secret}".encode()).hexdigest().upper()


def verify_sign(params: dict[str, Any], secret: str) -> bool:
    sign = params.get("sign")
    if not sign:
        return False
    method = params.get("sign_method", "md5")
    return hmac.compare_digest(str(sign), calc_sign(params, secret, method))


# ---------------- 错误码 ----------------

class TopError(Exception):
    """平台错误（TOP error_response 形态）"""

    def __init__(self, code: str, message: str, sub_code: str = "", sub_msg: str = ""):
        self.code = code
        self.message = message
        self.sub_code = sub_code
        self.sub_msg = sub_msg
        super().__init__(f"{code}: {message}")


# 注入的错误码白名单（测试适配器重试/降级）
INJECTABLE_ERRORS = {
    "isv.trade-service-error": "系统异常，请稍后再试",
    "flow-limit": "流量限制，请稍后再试",
    "isv.invalid-session-key": "Session失效",
    "isv.item-not-exist": "商品不存在",
    "isv.buyer-not-exist": "买家不存在",
    "isv.trade-not-exist": "交易不存在",
    "isv.refund-not-exist": "退款单不存在",
    "isv.permission-api-call-limit": "API调用权限受限",
}


def make_error_response(code: str, message: str, sub_code: str = "", sub_msg: str = "") -> dict:
    err = {"code": code, "msg": message, "sub_code": sub_code, "sub_msg": sub_msg,
           "request_id": f"sim-{int(time.time() * 1000)}"}
    return {"error_response": err}
