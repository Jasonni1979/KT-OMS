"""认证依赖（FastAPI Depends 链）：Bearer token → validate_access → AuthContext 注入

- get_current_account：全部需登录接口的统一依赖
- require_perm(code)：权限点校验依赖工厂（action 级）
- AuthContext 注入 contextvars（M1a-3 数据权限中间件消费；MVP 超管=all 维度）
"""
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AuthContext, get_session, set_auth_context
from app.core.exceptions import PermissionDeniedError
from app.services.auth import AuthService
from app.services.master import get_redis

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
    # 注入 AuthContext（MVP：超管=all；普通账户四维过滤在 M1a-3 中间件按角色 data_scope 展开）
    is_super = bool(result.get("su"))
    ctx = AuthContext(
        tenant_id=account.tenant_id,
        account_id=account.id,
        is_superuser=is_super,
        owner_ids=[] if is_super else [],   # M1a-3：非超管按角色授权节点展开
        shop_ids=[],
        branch_ids=[],
    )
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
