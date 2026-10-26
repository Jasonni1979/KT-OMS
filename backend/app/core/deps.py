"""认证依赖（FastAPI Depends 链）：Bearer token → validate_access → AuthContext 注入

- get_current_account：全部需登录接口的统一依赖
- require_perm(code)：权限点校验依赖工厂（action 级）
- AuthContext 注入 contextvars（M1a-3 数据权限中间件消费；MVP 超管=all 维度）
"""
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session, set_auth_context
from app.core.exceptions import PermissionDeniedError
from app.modules.m1_master.service.auth import AuthService
from app.modules.m1_master.service.master import get_redis
from app.modules.m1_master.service.permission import build_auth_context

_bearer = HTTPBearer(auto_error=False)


async def get_current_account(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
) -> dict:
    if creds is None or not creds.credentials:
        raise PermissionDeniedError("未提供身份凭证", code="UNAUTHORIZED", http_status=401)
    auth = AuthService(session, redis)
    result = await auth.validate_access(creds.credentials)
    account = result["account"]
    is_super = bool(result.get("su"))
    # 解析四维 scope（缓存优先，miss 实时展开）并注入 AuthContext（D10.03 FR-04a）
    ctx = await build_auth_context(account.id, account.tenant_id, session, redis, is_super)
    set_auth_context(ctx)
    request.state.account_id = account.id
    return result


def require_perm(perm_code: str):
    """权限点校验依赖工厂：@router.post(..., dependencies=[Depends(require_perm("d10.owner.create"))])"""

    async def _checker(
        current: dict = Depends(get_current_account),
        session: AsyncSession = Depends(get_session),
        redis: Redis = Depends(get_redis),
    ) -> None:
        if current.get("su"):
            return
        perms = await AuthService(session, redis).permissions_of(int(current["sub"]))
        if perm_code not in perms:
            raise PermissionDeniedError(f"缺少权限: {perm_code}", code="PERM_DENIED", http_status=403)

    return _checker
