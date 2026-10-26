"""认证测试（D10.02 MVP）：账密登录/失败锁定/会话互踢/登出吊销/刷新旋转/401保护"""
import pytest

from app.modules.m1_master.service.master import get_redis

pytestmark = pytest.mark.asyncio

ADMIN = {"login_name": "admin", "password": "Ktoms@2026"}


async def _login(client, **over):
    body = {**ADMIN, **over}
    return await client.post("/api/v1/auth/login", json=body)


async def test_login_success(client):
    r = await _login(client)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["access_token"] and data["refresh_token"]
    assert data["account_name"] == "系统管理员"


async def test_login_wrong_password(client):
    r = await _login(client, password="wrong-pass")
    assert r.status_code == 401
    assert r.json()["code"] == "AUTH_FAILED"


async def test_me_and_protected_route(client):
    """未带token 401；带token /me 返回超管全量权限"""
    r0 = await client.get("/api/v1/auth/me")
    assert r0.status_code == 401
    r0b = await client.get("/api/v1/master/owners")
    assert r0b.status_code == 401  # master 域已挂登录保护
    tok = (await _login(client)).json()["data"]["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    r = await client.get("/api/v1/auth/me", headers=h)
    assert r.status_code == 200
    me = r.json()["data"]
    assert me["is_superuser"] is True
    # 档案域带 token 可访问
    r2 = await client.get("/api/v1/master/owners", headers=h)
    assert r2.status_code == 200


async def test_logout_revokes_session(client):
    """登出后 Redis 会话删除 → access 立即失效（即时吊销双保险）"""
    tok = (await _login(client)).json()["data"]["access_token"]
    h = {"Authorization": f"Bearer {tok}"}
    r = await client.post("/api/v1/auth/logout", headers=h)
    assert r.status_code == 200
    r2 = await client.get("/api/v1/auth/me", headers=h)
    assert r2.status_code == 401
    assert r2.json()["code"] == "SESSION_REVOKED"


async def test_refresh_rotation(client):
    """刷新旋转：旧 refresh 作废，新 token 可用"""
    data = (await _login(client)).json()["data"]
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert r.status_code == 200, r.text
    new = r.json()["data"]
    assert new["refresh_token"] != data["refresh_token"]
    # 旧 refresh 再用 → 401
    r2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": data["refresh_token"]})
    assert r2.status_code == 401
    # 新 access 可用
    h = {"Authorization": f"Bearer {new['access_token']}"}
    r3 = await client.get("/api/v1/auth/me", headers=h)
    assert r3.status_code == 200


async def test_same_device_kick(client):
    """同端互踢：第二次 pc 登录后，第一个会话被踢（Redis session 指向新会话）"""
    d1 = (await _login(client, device_type="pc")).json()["data"]
    d2 = (await _login(client, device_type="pc")).json()["data"]
    assert d1["session_id"] != d2["session_id"]
    redis = await get_redis()
    cur = await redis.get("session:1:pc")
    assert cur == d2["session_id"]


async def test_lock_after_5_failures(client):
    """连败5次锁定（用独立测试账户验证，避免锁死admin影响其他用例）"""
    # 直接构造：临时把 admin fail_count 推高不可行（会锁admin）——
    # 用不存在的账户与 admin 分开验证锁定逻辑单元：此处走服务层单元测试
    from app.core.db import SessionFactory
    from app.core.security import hash_password
    from app.models.account import OrgAccount, OrgAccountCredential
    from app.modules.m1_master.service.auth import AuthService

    redis = await get_redis()
    # 先清理残留（幂等，避免唯一键冲突）
    from sqlalchemy import text as _text

    from app.core.db import engine as _engine
    async with _engine.begin() as conn:
        await conn.execute(_text(
            "DELETE FROM oms_org.org_session WHERE account_id IN "
            "(SELECT id FROM oms_org.org_account WHERE login_name='t_lock_user')"
        ))
        await conn.execute(_text(
            "DELETE FROM oms_org.org_account_credential WHERE account_id IN "
            "(SELECT id FROM oms_org.org_account WHERE login_name='t_lock_user')"
        ))
        await conn.execute(_text("DELETE FROM oms_org.org_account WHERE login_name='t_lock_user'"))

    async with SessionFactory() as s:
        acc = OrgAccount(tenant_id=1, account_type="staff", login_name="t_lock_user",
                         account_name="锁定测试", org_node_id=1, status=2, source="local",
                         mobile_hash="test-lock-user-hash")  # uk_org_account_mobile 唯一键
        s.add(acc)
        await s.flush()
        s.add(OrgAccountCredential(tenant_id=1, account_id=acc.id, credential_type="password",
                                   password_hash=hash_password("Test@12345"), status=1))
        await s.commit()
        acc_id = acc.id

        svc = AuthService(s, redis)
        from app.core.exceptions import PermissionDeniedError
        for _ in range(5):
            with pytest.raises(PermissionDeniedError):
                await svc.login_password("t_lock_user", "bad-pass")
        # 第6次即使密码对也被锁
        with pytest.raises(PermissionDeniedError) as ei:
            await svc.login_password("t_lock_user", "Test@12345")
        assert ei.value.code == "ACCOUNT_LOCKED"

    # 清理测试账户
    from sqlalchemy import text

    from app.core.db import engine
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM oms_org.org_account WHERE login_name='t_lock_user'"))
        await conn.execute(text(f"DELETE FROM oms_org.org_account_credential WHERE account_id={acc_id}"))
        await conn.execute(text(f"DELETE FROM oms_org.org_session WHERE account_id={acc_id}"))
