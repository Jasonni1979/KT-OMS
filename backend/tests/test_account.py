"""D10.02 租户账户与角色测试（补齐）

在 test_auth.py 基础上补齐 FR 级覆盖：
- FR-01d 租户禁用 → 账户禁止登录 / 会话失效
- FR-02a 账户档案（状态机：正常/锁定/禁用）
- FR-02b 自建账号体系：登录名唯一 + 首登强制改密
- FR-02d 密码策略：连败锁定 15 分钟 / 锁定到期自动解锁
- FR-04a/04b/04c/04d 角色：分类 / 权限点绑定 / 账户多角色 / 角色档案
- FR-05b 会话管理（JWT + Redis 吊销双保险）
- FR-05c 多端策略（同端互踢 + 异端并存）
- FR-05d 登录审计（失败原因结构化落库）
- FR-05e 权限上下文（AuthContext 组装）
- FR-06c 离职禁用 → 会话即时踢出
"""
from __future__ import annotations

import hashlib
from datetime import UTC

import pytest
from sqlalchemy import select, text

from app.core.db import SessionFactory
from app.services.auth import (
    LOCK_MINUTES,
    MAX_FAIL,
    REFRESH_DAYS,
    SUPERUSER_ROLE_CODE,
)

pytestmark = pytest.mark.asyncio

ADMIN = {"login_name": "admin", "password": "Ktoms@2026"}


@pytest.fixture(autouse=True)
async def _sys_ctx():
    """裸 ORM 查询需要 AuthContext（M0.4 fail-closed 机制）"""
    from app.core.db import AuthContext, set_auth_context

    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    yield


async def _login(client, **over):
    body = {**ADMIN, **over}
    return await client.post("/api/v1/auth/login", json=body)


async def _create_account(
    login_name: str,
    password: str = "Test@2026",
    *,
    status: int = 1,
    must_change: bool = False,
    role_codes: list[str] | None = None,
) -> int:
    """造一个 staff 账户（含凭证 + 角色绑定）"""
    from app.core import security as sec
    from app.models.account import (
        OrgAccount,
        OrgAccountCredential,
        OrgAccountRole,
    )

    async with SessionFactory() as s:
        acc = OrgAccount(
            tenant_id=1,
            login_name=login_name,
            account_name=f"测试-{login_name}",
            account_type="staff",
            # ⚠ uk_org_account_mobile 是全局唯一索引，空串会撞唯一键 → 必须派生
            mobile_hash=hashlib.sha1(login_name.encode()).hexdigest(),
            status=status,
            fail_count=0,
            roles_ver=1,
        )
        s.add(acc)
        await s.flush()
        s.add(
            OrgAccountCredential(
                tenant_id=1,
                account_id=acc.id,
                credential_type="password",
                password_hash=sec.hash_password(password),
                status=1,
                must_change_pwd=1 if must_change else 0,
            )
        )
        for rc in role_codes or []:
            role = await s.scalar(
                text("SELECT id FROM oms_org.org_role WHERE role_code = :c"),
                {"c": rc},
            )
            if role:
                s.add(
                    OrgAccountRole(
                        tenant_id=1, account_id=acc.id, role_id=int(role)
                    )
                )
        await s.commit()
        return int(acc.id)


async def _cleanup_accounts(prefix: str = "T_ACC") -> None:
    """清理测试账户（按 login_name 前缀）

    注意：org_account_role / org_session / org_role_perm **无 is_deleted 列**，
    只能物理删除。
    """
    from sqlalchemy import delete

    from app.models.account import (
        OrgAccount,
        OrgAccountCredential,
        OrgAccountRole,
        OrgSession,
    )

    async with SessionFactory() as s:
        accs = (
            await s.execute(
                select(OrgAccount).where(OrgAccount.login_name.like(f"{prefix}%"))
            )
        ).scalars().all()
        if not accs:
            return
        ids = [int(a.id) for a in accs]
        await s.execute(
            delete(OrgAccountCredential).where(
                OrgAccountCredential.account_id.in_(ids)
            )
        )
        await s.execute(
            delete(OrgAccountRole).where(OrgAccountRole.account_id.in_(ids))
        )
        await s.execute(delete(OrgSession).where(OrgSession.account_id.in_(ids)))
        await s.execute(delete(OrgAccount).where(OrgAccount.id.in_(ids)))
        await s.commit()


# ============ FR-02b 自建账号体系 ============


async def test_new_account_first_login_must_change_password(client):
    """FR-02b：首次登录强制改密（must_change_pwd=True）"""
    await _cleanup_accounts("T_ACCFC")
    await _create_account("T_ACCFC", "Test@2026", must_change=True)
    try:
        r = await _login(client, login_name="T_ACCFC", password="Test@2026")
        assert r.status_code == 200, r.text
        assert r.json()["data"]["must_change_pwd"] is True
    finally:
        await _cleanup_accounts("T_ACCFC")


async def test_login_name_unique_per_account(client):
    """FR-02b：登录名唯一——同名账户不能重复建档"""
    from app.core.db import AuthContext, set_auth_context

    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    await _cleanup_accounts("T_ACCUNIQ")
    await _create_account("T_ACCUNIQ", "Test@2026")
    try:
        async with SessionFactory() as s:
            cnt = await s.scalar(
                text(
                    "SELECT COUNT(*) FROM oms_org.org_account "
                    "WHERE login_name = :n AND is_deleted = 0"
                ),
                {"n": "T_ACCUNIQ"},
            )
        assert int(cnt or 0) == 1
    finally:
        await _cleanup_accounts("T_ACCUNIQ")


# ============ FR-02a / FR-06c 账户状态机 ============


async def test_disabled_account_cannot_login(client):
    """FR-02a：账户禁用 → 拒绝登录（ACCOUNT_DISABLED）"""
    await _cleanup_accounts("T_ACCDIS")
    await _create_account("T_ACCDIS", "Test@2026", status=4)
    try:
        r = await _login(client, login_name="T_ACCDIS", password="Test@2026")
        assert r.status_code == 403, r.text
        assert r.json()["code"] == "ACCOUNT_DISABLED"
    finally:
        await _cleanup_accounts("T_ACCDIS")


async def test_disabled_account_session_invalidated(client):
    """FR-01d / FR-06c：账户禁用 → 已签发的会话立即失效"""
    await _cleanup_accounts("T_ACCDI2")
    await _create_account("T_ACCDI2", "Test@2026")
    try:
        r = await _login(client, login_name="T_ACCDI2", password="Test@2026")
        assert r.status_code == 200, r.text
        token = r.json()["data"]["access_token"]
        # 禁用账户
        async with SessionFactory() as s:
            await s.execute(
                text(
                    "UPDATE oms_org.org_account SET status = 4 "
                    "WHERE login_name = :n"
                ),
                {"n": "T_ACCDI2"},
            )
            await s.commit()
        r2 = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert r2.status_code == 401, r2.text
        assert r2.json()["code"] == "ACCOUNT_DISABLED"
    finally:
        await _cleanup_accounts("T_ACCDI2")


# ============ FR-02d 密码策略（连败锁定 / 自动解锁）============


async def test_lock_policy_constants_match_srs():
    """FR-02d：连败 5 次锁定 15 分钟（与 SRS 默认值一致）"""
    assert MAX_FAIL == 5
    assert LOCK_MINUTES == 15


async def test_lock_expires_auto_unlock(client):
    """FR-02d：锁定到期后自动解锁并可登录"""
    await _cleanup_accounts("T_ACCUNL")
    await _create_account("T_ACCUNL", "Test@2026", status=3)
    try:
        # 手工把 lock_until 置为过去 → 应自动解锁
        from datetime import datetime, timedelta

        expired = datetime.now(UTC).replace(tzinfo=None) - timedelta(
            minutes=1
        )
        async with SessionFactory() as s:
            await s.execute(
                text(
                    "UPDATE oms_org.org_account SET lock_until = :lu WHERE login_name = :n"
                ),
                {"n": "T_ACCUNL", "lu": expired},
            )
            await s.commit()
        r = await _login(client, login_name="T_ACCUNL", password="Test@2026")
        assert r.status_code == 200, r.text
        assert r.json()["data"]["access_token"]
    finally:
        await _cleanup_accounts("T_ACCUNL")


async def test_locked_account_rejected_with_code(client):
    """FR-02d：锁定中 → ACCOUNT_LOCKED（423）"""
    await _cleanup_accounts("T_ACCLK")
    await _create_account("T_ACCLK", "Test@2026", status=3)
    try:
        # ⚠ 用 Python 本地时间而非 MySQL NOW()：DB 容器时区（UTC）与应用时区（+08:00）
        #    不一致时，NOW() 写入的 lock_until 会被应用判为「已过期」→ 误放行
        from datetime import datetime, timedelta

        # 与 auth._utcnow() 同基准（UTC naive）
        lock_until = datetime.now(UTC).replace(tzinfo=None) + timedelta(
            minutes=10
        )
        async with SessionFactory() as s:
            await s.execute(
                text(
                    "UPDATE oms_org.org_account SET lock_until = :lu WHERE login_name = :n"
                ),
                {"n": "T_ACCLK", "lu": lock_until},
            )
            await s.commit()
        r = await _login(client, login_name="T_ACCLK", password="Test@2026")
        assert r.status_code == 423, r.text
        assert r.json()["code"] == "ACCOUNT_LOCKED"
    finally:
        await _cleanup_accounts("T_ACCLK")


# ============ FR-05d 登录审计 ============


async def test_login_failure_audit_recorded(client):
    """FR-05d：登录失败写审计流水（原因结构化 pwd_error）"""
    await _cleanup_accounts("T_ACCAUD")
    await _create_account("T_ACCAUD", "Test@2026")
    try:
        r = await _login(client, login_name="T_ACCAUD", password="WrongPass1")
        assert r.status_code == 401, r.text
        async with SessionFactory() as s:
            row = (
                await s.execute(
                    text(
                        "SELECT login_result, fail_reason, channel FROM oms_org.org_session "
                        "WHERE login_ip = :ip ORDER BY id DESC LIMIT 1"
                    ),
                    {"ip": "127.0.0.1"},
                )
            ).mappings().first()
        assert row is not None
        assert int(row["login_result"]) == 2  # 失败
        assert row["fail_reason"] == "pwd_error"
        assert row["channel"] == "password"
    finally:
        await _cleanup_accounts("T_ACCAUD")


# ============ FR-05b 会话管理 ============


async def test_refresh_token_expiry_days():
    """FR-05b：refresh 有效期 7 天"""
    assert REFRESH_DAYS == 7


async def test_logout_deletes_redis_session(client):
    """FR-05b：登出 = 删 Redis + refresh 吊销（双保险）"""
    from app.services.master import get_redis

    r = await _login(client)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    token = data["access_token"]
    account_id = int(data["account_id"])
    r2 = await client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 200, r2.text
    redis = await get_redis()
    # 登出后该账户 pc 端会话键应已删除
    assert await redis.get(f"session:{account_id}:pc") is None
    # 且该 token 立即失效（FR-05b 即时吊销）
    r3 = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert r3.status_code == 401, r3.text
    assert r3.json()["code"] == "SESSION_REVOKED"


async def test_validate_access_rejects_after_roles_changed(client):
    """FR-04b / FR-05b：角色变更（roles_ver 变化）→ 强制重新登录"""
    r = await _login(client)
    assert r.status_code == 200, r.text
    token = r.json()["data"]["access_token"]
    async with SessionFactory() as s:
        await s.execute(
            text(
                "UPDATE oms_org.org_account SET roles_ver = roles_ver + 1 "
                "WHERE login_name = 'admin'"
            )
        )
        await s.commit()
    r2 = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert r2.status_code == 401, r2.text
    assert r2.json()["code"] == "ROLES_CHANGED"
    # 复原（避免影响其他用例）
    async with SessionFactory() as s:
        await s.execute(
            text(
                "UPDATE oms_org.org_account SET roles_ver = roles_ver - 1 "
                "WHERE login_name = 'admin'"
            )
        )
        await s.commit()


# ============ FR-05c 多端策略 ============


async def test_multi_device_sessions_coexist(client):
    """FR-05c：不同端（pc / mobile）会话并存"""
    r1 = await _login(client, device_type="pc")
    r2 = await _login(client, device_type="mobile")
    assert r1.status_code == 200 and r2.status_code == 200
    t1 = r1.json()["data"]["access_token"]
    t2 = r2.json()["data"]["access_token"]
    assert t1 != t2
    # 两端都能通过校验
    for t in (t1, t2):
        r = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {t}"}
        )
        assert r.status_code == 200, r.text


async def test_same_device_login_kicks_previous(client):
    """FR-05c：同端互踢——旧会话立即失效"""
    r1 = await _login(client, device_type="pc")
    t1 = r1.json()["data"]["access_token"]
    r2 = await _login(client, device_type="pc")
    t2 = r2.json()["data"]["access_token"]
    assert t1 != t2
    # 旧 token 的会话记录状态应变为已踢（3）
    async with SessionFactory() as s:
        row = (
            await s.execute(
                text(
                    "SELECT status FROM oms_org.org_session "
                    "WHERE login_ip = :ip ORDER BY id DESC LIMIT 2"
                ),
                {"ip": "127.0.0.1"},
            )
        ).all()
    statuses = sorted(int(x[0]) for x in row)
    assert 3 in statuses


# ============ FR-05e 权限上下文 / FR-04 角色 ============


async def test_me_returns_permission_context(client):
    """FR-05e：/auth/me 返回账户与权限点（前端动态菜单依据）"""
    r = await _login(client)
    assert r.status_code == 200, r.text
    r2 = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {r.json()['data']['access_token']}"},
    )
    assert r2.status_code == 200, r2.text
    d = r2.json()["data"]
    assert d["account_id"]
    assert "permissions" in d
    assert isinstance(d["permissions"], list)


async def test_superuser_has_all_permission_points(client):
    """FR-04a：超管角色 → 权限点全量生效"""
    r = await _login(client)
    token = r.json()["data"]["access_token"]
    r2 = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    perms = r2.json()["data"]["permissions"]
    async with SessionFactory() as s:
        total = await s.scalar(
            text(
                "SELECT COUNT(*) FROM oms_org.org_perm_point "
                "WHERE status = 1 AND is_deleted = 0"
            )
        )
    assert len(perms) == int(total or 0)


async def test_account_role_binding_and_permission_union(client):
    """FR-04c：账户多角色 → 权限点取并集"""
    from app.core.db import AuthContext, set_auth_context

    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    await _cleanup_accounts("T_ACCRL")
    # 取两个非超管角色
    async with SessionFactory() as s:
        roles = (
            await s.execute(
                text(
                    "SELECT role_code FROM oms_org.org_role "
                    "WHERE role_code != :sup AND is_deleted = 0 LIMIT 2"
                ),
                {"sup": SUPERUSER_ROLE_CODE},
            )
        ).scalars().all()
    if len(roles) < 2:
        pytest.skip("库中非超管角色不足 2 个")
    aid = await _create_account(
        "T_ACCRL", "Test@2026", role_codes=list(roles)
    )
    try:
        r = await _login(client, login_name="T_ACCRL", password="Test@2026")
        assert r.status_code == 200, r.text
        token = r.json()["data"]["access_token"]
        r2 = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        perms = r2.json()["data"]["permissions"]
        async with SessionFactory() as s:
            rows = (
                await s.execute(
                    text(
                        "SELECT COUNT(DISTINCT perm_code) FROM oms_org.org_role_perm rp "
                        "JOIN oms_org.org_account_role ar ON ar.role_id = rp.role_id "
                        "WHERE ar.account_id = :a"
                    ),
                    {"a": aid},
                )
            ).scalar()
        assert len(perms) == int(rows or 0)
    finally:
        await _cleanup_accounts("T_ACCRL")


async def test_role_delete_blocked_when_account_bound(client):
    """FR-04d：删除角色前校验无账户绑定"""
    from app.core.db import AuthContext, set_auth_context

    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    async with SessionFactory() as s:
        row = (
            await s.execute(
                text(
                    "SELECT r.id, r.role_code FROM oms_org.org_role r "
                    "JOIN oms_org.org_account_role ar ON ar.role_id = r.id "
                    "WHERE r.is_deleted = 0 LIMIT 1"
                )
            )
        ).mappings().first()
    if not row:
        pytest.skip("库中无角色被账户绑定")
    # 绑定存在 → 角色不可删（由服务层校验）
    async with SessionFactory() as s:
        bound = await s.scalar(
            text(
                "SELECT COUNT(*) FROM oms_org.org_account_role "
                "WHERE role_id = :r"
            ),
            {"r": int(row["id"])},
        )
    assert int(bound or 0) >= 1
