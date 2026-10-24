"""全局中间件：trace_id 注入 + 请求日志 + AuthContext 骨架

AuthContext 的完整四维解析（账号→角色→数据权限展开）在 M1 D10 实现；
M0 骨架先放默认上下文，保证 contextvars 链路贯通（M0.4 数据权限 spike 的基础）。
"""
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.db import AuthContext, set_auth_context


class TraceMiddleware(BaseHTTPMiddleware):
    """trace_id 贯穿（对齐 D01.01 消息信封 trace_id / D11.03 全链路追踪）"""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        trace_id = request.headers.get("X-Trace-Id") or uuid.uuid4().hex[:16]
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(trace_id=trace_id)

        start = time.perf_counter()
        response = await call_next(request)
        cost_ms = round((time.perf_counter() - start) * 1000, 2)

        response.headers["X-Trace-Id"] = trace_id
        structlog.get_logger("access").info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            cost_ms=cost_ms,
        )
        return response


class AuthContextMiddleware(BaseHTTPMiddleware):
    """M0 骨架：注入默认 AuthContext（tenant_id=1 开发租户）。

    M1 替换为真实实现：解析 JWT → 账号 → 角色 → D10.03 数据权限展开（缓存）→ AuthContext。
    外部租户（品牌方门户）强制单货主硬隔离在 D10.03 实现。
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
        return await call_next(request)
