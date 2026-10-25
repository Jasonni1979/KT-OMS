"""SQLAlchemy 2.0 async 会话管理 + 请求上下文（contextvars）

请求上下文承载 D10.03 四维数据权限的 AuthContext（tenant_id/owner_ids/shop_ids/branch_ids），
M0.4 spike 将基于此实现 with_loader_criteria 全局行级过滤。
"""
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
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
    brand_ids: list[int] = field(default_factory=list)
    account_id: int = 0
    is_superuser: bool = False
    all_data: bool = False          # 内部 all 模式角色（D10.03 FR-02c）：租户内全部可见
    scope_source: str = ""           # scope 来源标记（诊断/审计用）


# 每请求一个上下文（contextvars 天然协程隔离，asyncio.gather 并发安全）
_auth_ctx: ContextVar[AuthContext | None] = ContextVar("auth_ctx", default=None)

# 豁免通道（FR-04d）：系统级任务（worker/调度/跨货主聚合）显式声明使用，
# 需登记调用点清单；CI 可静态检查滥用
_scope_exempt: ContextVar[bool] = ContextVar("scope_exempt", default=False)


def set_auth_context(ctx: AuthContext) -> None:
    _auth_ctx.set(ctx)


def clear_auth_context() -> None:
    """清空当前上下文（请求进入时防跨请求串扰）"""
    _auth_ctx.set(None)


def get_auth_context() -> AuthContext | None:
    return _auth_ctx.get()


def require_auth_context() -> AuthContext:
    ctx = _auth_ctx.get()
    if ctx is None:
        raise RuntimeError("AuthContext 未初始化（应经权限中间件设置）")
    return ctx


def is_scope_exempt() -> bool:
    return _scope_exempt.get()


def system_scope(func):
    """装饰器：被装饰的异步函数整体走豁免通道（FR-04d 系统级任务专用）

    用于认证链路与 scope 解析——它们发生在 AuthContext 注入之前，属系统级操作。
    豁免调用点须登记清单（docs/权限豁免调用点清单.md），CI 静态检查滥用。
    """
    import functools

    @functools.wraps(func)
    async def _wrapper(*args, **kwargs):
        with without_data_scope():
            return await func(*args, **kwargs)

    return _wrapper


@contextmanager
def without_data_scope() -> Generator[None, None, None]:
    """豁免通道：块内查询不做行级过滤（仅系统级任务使用，FR-04d）

    用法：
        with without_data_scope():
            await do_something_system_level()
    """
    token = _scope_exempt.set(True)
    try:
        yield
    finally:
        _scope_exempt.reset(token)


engine = create_async_engine(
    settings.sqlalchemy_uri,
    echo=settings.mysql_echo,
    pool_size=settings.mysql_pool_size,
    max_overflow=settings.mysql_max_overflow,
    pool_pre_ping=True,
    pool_recycle=3600,
)

SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def install_scope_injection() -> None:
    """安装行级过滤注入（D10.03 FR-04a）

    在模块加载期安装（而非 lifespan），确保测试（ASGITransport 不触发 lifespan）
    与独立脚本同样受保护。
    """
    from app.core.permission import install_scope_injection as _install
    _install(SessionFactory)


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
