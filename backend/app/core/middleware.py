"""全局中间件：trace_id 注入 + 请求日志 + AuthContext 生命周期（D10.03 FR-04a）"""
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.db import clear_auth_context


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
    """请求级权限上下文生命周期管理（D10.03 FR-04a）

    - 请求进入时清空上一请求残留的 AuthContext（contextvars 复用导致串扰的防线）
    - 真实 scope 解析在 get_current_account 依赖中完成（JWT→账号→角色→四维展开→注入）
    - 无登录态的公开接口（healthz 等）不注入上下文：ORM 查询因 fail-closed 被拒，
      公共接口需用 text() 原生 SQL 或显式 without_data_scope() 豁免
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        clear_auth_context()  # 清空残留（防跨请求串扰）
        return await call_next(request)
