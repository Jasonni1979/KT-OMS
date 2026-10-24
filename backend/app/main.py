"""KT-OMS FastAPI 应用入口（模块化单体，SRS-00 架构风格）

启动: cd backend && uv run uvicorn app.main:app --reload --port 8000
文档: http://localhost:8000/docs (Swagger) / http://localhost:8000/redoc
"""
from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.db import engine
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.middleware import AuthContextMiddleware, TraceMiddleware

logger = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging("DEBUG" if settings.debug else "INFO")
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
