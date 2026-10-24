"""统一异常体系 + 全局异常处理器（对齐 D01 底座：错误码分级、结构化响应）"""
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger

logger = get_logger("exception")


class BizError(Exception):
    """业务异常基类：携带业务错误码（对齐 D02.05 错误码分级思想）"""

    code: str = "BIZ_ERROR"
    http_status: int = status.HTTP_400_BAD_REQUEST
    message: str = "业务处理失败"

    def __init__(self, message: str | None = None, *, code: str | None = None,
                 http_status: int | None = None, data: Any = None):
        self.message = message or self.message
        if code:
            self.code = code
        if http_status:
            self.http_status = http_status
        self.data = data
        super().__init__(self.message)


class NotFoundError(BizError):
    code = "NOT_FOUND"
    http_status = status.HTTP_404_NOT_FOUND
    message = "资源不存在"


class PermissionDeniedError(BizError):
    code = "PERMISSION_DENIED"
    http_status = status.HTTP_403_FORBIDDEN
    message = "无权访问"


class ValidationError(BizError):
    code = "VALIDATION_ERROR"
    http_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    message = "数据校验失败"


class ConflictError(BizError):
    code = "CONFLICT"
    http_status = status.HTTP_409_CONFLICT
    message = "资源状态冲突"


def _envelope(code: str, message: str, data: Any = None, *, http_status: int = 400) -> JSONResponse:
    return JSONResponse(status_code=http_status, content={"code": code, "message": message, "data": data})


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BizError)
    async def _biz_handler(_: Request, exc: BizError) -> JSONResponse:
        logger.warning("biz_error", code=exc.code, message=exc.message, data=exc.data)
        return _envelope(exc.code, exc.message, exc.data, http_status=exc.http_status)

    @app.exception_handler(StarletteHTTPException)
    async def _http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _envelope(f"HTTP_{exc.status_code}", str(exc.detail), http_status=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _envelope("VALIDATION_ERROR", "请求参数校验失败", exc.errors(), http_status=422)

    @app.exception_handler(Exception)
    async def _unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("unhandled_error", path=request.url.path, error=str(exc), exc_info=exc)
        return _envelope("INTERNAL_ERROR", "服务器内部错误", http_status=500)
