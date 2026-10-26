"""认证 API（/api/v1/auth）：登录/刷新/登出/当前用户信息"""
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.deps import get_current_account
from app.core.response import ok
from app.modules.m1_master.contract import AuthService, fingerprint, get_redis

router = APIRouter(tags=["auth-认证"])


class LoginReq(BaseModel):
    login_name: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)
    device_type: str = Field(default="pc", pattern="^(pc|mobile)$")


class RefreshReq(BaseModel):
    refresh_token: str
    device_type: str = Field(default="pc", pattern="^(pc|mobile)$")


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return (fwd.split(",")[0].strip() if fwd else request.client.host if request.client else "")


@router.post("/login", summary="账密登录（staff 通道）")
async def login(
    body: LoginReq,
    request: Request,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    ip = _client_ip(request)
    fp = fingerprint(ip, request.headers.get("user-agent", ""))
    result = await AuthService(session, redis).login_password(
        body.login_name, body.password, body.device_type, ip, fp
    )
    return ok(result)


@router.post("/refresh", summary="刷新令牌（旋转作废旧token）")
async def refresh(
    body: RefreshReq,
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    tokens = await AuthService(session, redis).refresh(body.refresh_token, body.device_type)
    return ok(tokens)


@router.post("/logout", summary="登出（删Redis+吊销refresh）")
async def logout(
    request: Request,
    current: dict = Depends(get_current_account),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    await AuthService(session, redis).logout(int(current["sub"]))
    return ok(None)


@router.get("/me", summary="当前用户信息+权限点（前端动态菜单/按钮控制）")
async def me(
    current: dict = Depends(get_current_account),
    session: AsyncSession = Depends(get_session),
    redis: Redis = Depends(get_redis),
):
    account = current["account"]
    perms = await AuthService(session, redis).permissions_of(account.id)
    return ok({
        "account_id": account.id,
        "account_name": account.account_name,
        "login_name": account.login_name,
        "is_superuser": bool(current.get("su")),
        "roles_ver": account.roles_ver,
        "permissions": perms,
    })
