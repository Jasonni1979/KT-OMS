"""KT-OMS FastAPI 应用入口（模块化单体，SRS-00 架构风格）

启动: cd backend && uv run uvicorn app.main:app --reload --port 8000
文档: http://localhost:8000/docs (Swagger) / http://localhost:8000/redoc
"""
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.db import check_driver_compat, engine, install_scope_injection
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.middleware import AuthContextMiddleware, TraceMiddleware
from app.models import registry  # noqa: F401  # 业务域可过滤实体声明注册（导入即生效）

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging("DEBUG" if settings.debug else "INFO")
    # D10.03 FR-04a：行级过滤注入已在模块加载期安装（此处仅确认日志）
    install_scope_injection()
    # 驱动兼容性自检（pymysql 2.x × aiomysql → varbinary 写入炸）
    ok, msg = check_driver_compat()
    if not ok:
        logger.error("driver_incompatible", detail=msg)
    else:
        logger.info("driver_compat", detail=msg)
    logger.info("startup", app=settings.app_name, env=settings.env)
    yield
    await engine.dispose()
    logger.info("shutdown")


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="凯淳自研 OMS —— 11 域 67 模块，文档见 docs/（SRS-00 总纲入口）",
    lifespan=lifespan,
)

# CORS：开发期放开（生产按环境收紧到前端域名）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.env == "dev" else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Trace-Id"],
)

app.add_middleware(AuthContextMiddleware)
app.add_middleware(TraceMiddleware)

register_exception_handlers(app)
app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/")
async def root() -> dict:
    return {"app": settings.app_name, "docs": "/docs", "api": settings.api_prefix}
