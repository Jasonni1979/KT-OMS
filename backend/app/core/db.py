"""SQLAlchemy 2.0 async 会话管理 + 请求上下文（contextvars）

请求上下文承载 D10.03 四维数据权限的 AuthContext（tenant_id/owner_ids/shop_ids/branch_ids），
M0.4 spike 将基于此实现 with_loader_criteria 全局行级过滤。
"""
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings


@dataclass
class AuthContext:
    """当前请求的权限上下文（D10.03 契约：四维行级过滤 + 租户隔离）"""

    tenant_id: int = 1
    owner_ids: list[int] = field(default_factory=list)    # 空=全部（超管）；外部租户=单货主硬隔离
    shop_ids: list[int] = field(default_factory=list)
    branch_ids: list[int] = field(default_factory=list)
    account_id: int = 0
    is_superuser: bool = False


# 每请求一个上下文（contextvars 天然协程隔离，asyncio.gather 并发安全）
_auth_ctx: ContextVar[AuthContext | None] = ContextVar("auth_ctx", default=None)


def set_auth_context(ctx: AuthContext) -> None:
    _auth_ctx.set(ctx)


def get_auth_context() -> AuthContext | None:
    return _auth_ctx.get()


def require_auth_context() -> AuthContext:
    ctx = _auth_ctx.get()
    if ctx is None:
        raise RuntimeError("AuthContext 未初始化（应经权限中间件设置）")
    return ctx


engine = create_async_engine(
    settings.sqlalchemy_uri,
    echo=settings.mysql_echo,
    pool_size=settings.mysql_pool_size,
    max_overflow=settings.mysql_max_overflow,
    pool_pre_ping=True,
    pool_recycle=3600,
)

SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends 注入点"""
    async with SessionFactory() as session:
        yield session


@asynccontextmanager
async def session_scope() -> AsyncGenerator[AsyncSession, None]:
    """服务层/worker 用事务作用域（对齐 SRS：业务事务+outbox 同库提交）"""
    async with SessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
