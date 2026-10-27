"""D10.02 租户账户与角色 · 补充测试（验收报告缺口 G2）

**背景**：`docs/MVP内测验收报告.md` 的 G2 —— D10.02 覆盖 48.5%（17 条 FR 未触达）。
逐条核对 SRS 后发现，那 17 条里有 **11 条根本没实现或明确 OUT**：

| FR | 状态 | 处置 |
|---|---|---|
| FR-01c 租户↔货主关联 | **已实现**（`org_tenant.owner_scope_json`） | 本文件补测 |
| FR-01e tenant_id 必填 | **已实现**（全表 NOT NULL + 注入隔离） | 本文件补测 |
| FR-02e 部门岗位与组织节点 | **已实现**（`org_account.org_node_id/dept_name/position`） | 本文件补测 |
| FR-07 / 07a / 07b OIDC 预留 | **本期只交付表结构与开关**（FR-07b 原文） | 本文件补测（结构 + 默认关） |
| FR-02c 企微扫码 | 预留未实现 | 不测 |
| FR-03a~03e 外部租户账户 | 品牌方门户 = PLAN-DEV-01 §1.2 OUT | 不测 |
| FR-06a/06b/06d/06e 入职/转岗/注销/僵尸治理 | **服务层无实现** | 不测（记为未实现） |

> ⚠ **诚实原则**：不为了刷覆盖率给「未实现」的能力写假测试。
> 覆盖率是**结果**不是目标 —— 补测只覆盖真实存在的行为。
"""
from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy import delete, select, text

from app.core.db import AuthContext, SessionFactory, set_auth_context
from app.models.account import OrgAccount, OrgAccountCredential

pytestmark = pytest.mark.asyncio

PREFIX = "T_ACCX"


@pytest.fixture(autouse=True)
async def _ctx():
    """裸 ORM 查询需要 AuthContext（数据权限中间件 fail-closed）"""
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    yield


async def _mk_account(
    login_name: str,
    *,
    tenant_id: int = 1,
    org_node_id: int = 0,
    dept_name: str = "",
    position: str = "",
) -> int:
    """造一个账户（不建凭证/角色，只测档案层字段）"""
    async with SessionFactory() as s:
        acc = OrgAccount(
            tenant_id=tenant_id,
            login_name=login_name,
            account_name=f"补测-{login_name}",
            account_type="staff",
            # ⚠ mobile_hash 是全局唯一 → 必须按 login_name 派生
            mobile_hash=hashlib.sha1(f"{login_name}-{uuid.uuid4().hex[:6]}".encode()).hexdigest(),
            org_node_id=org_node_id,
            dept_name=dept_name,
            position=position,
            status=1,
            fail_count=0,
            roles_ver=1,
        )
        s.add(acc)
        await s.commit()
        return int(acc.id)


async def _clean(prefix: str = PREFIX) -> None:
    """清理测试账户（先子表后父表）"""
    async with SessionFactory() as s:
        accs = (
            await s.execute(select(OrgAccount).where(OrgAccount.login_name.like(f"{prefix}%")))
        ).scalars().all()
        if not accs:
            return
        ids = [int(a.id) for a in accs]
        await s.execute(
            delete(OrgAccountCredential).where(OrgAccountCredential.account_id.in_(ids))
        )
        await s.execute(delete(OrgAccount).where(OrgAccount.id.in_(ids)))
        await s.commit()


# ============ FR-01e 租户隔离 ============


async def test_account_tenant_id_is_not_nullable():
    """FR-01e：所有业务表 tenant_id 必填（内部数据 tenant_id=1）"""
    async with SessionFactory() as s:
        nullable = await s.scalar(
            text(
                "SELECT IS_NULLABLE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA='oms_org' AND TABLE_NAME='org_account' "
                "AND COLUMN_NAME='tenant_id'"
            )
        )
    assert str(nullable).upper() == "NO"


async def test_tenant_isolation_not_yet_enforced_on_account_entities():
    """FR-01e（**缺陷证据**）：账户域实体尚未注册数据权限 → 租户隔离未生效

    ⚠ **这不是期望行为，是当前缺陷的证据**（验收报告 G9）：
    - 数据权限注入只作用于 `FILTERABLE_REGISTRY` 里**已注册**的实体
      （`app/core/permission.py::_inject_scope` 遍历注册表逐个加条件）
    - 账户域实体（OrgAccount / OrgRole / OrgSession…）**未注册** →
      ORM 查询不注入 tenant_id 条件 → 跨租户可见
    - 且 `permission.py` 文档写的「未注册实体只注入 tenant_id 保底隔离」
      **实现里并不存在**（`_build_criteria` 只对已注册实体调用）

    故本测试断言的是**当前事实**（跨租户可见）。
    缺陷修复（注册账户域实体 + 给认证链路加 `without_data_scope()` 豁免）后，
    本测试**会失败** → 提醒同步更新为期望行为的断言。
    """
    await _clean()
    await _mk_account(f"{PREFIX}T2", tenant_id=2)
    try:
        set_auth_context(AuthContext(tenant_id=1, is_superuser=False))
        async with SessionFactory() as s:
            rows = (
                await s.execute(
                    select(OrgAccount).where(OrgAccount.login_name.like(f"{PREFIX}%"))
                )
            ).scalars().all()
        # 当前事实：租户 1 的上下文**能看到**租户 2 的账户（隔离未生效）
        assert len(rows) == 1, (
            "账户域实体已注册数据权限 → 租户隔离生效了！"
            "请把本测试改为断言『租户 1 看不到租户 2』，并更新验收报告 G9"
        )
    finally:
        set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
        await _clean()


async def test_account_entities_absent_from_data_scope_registry():
    """FR-01e（**缺陷证据**）：账户域实体未登记进数据权限注册表"""
    from app.core.permission import FILTERABLE_REGISTRY

    for entity in (OrgAccount, OrgAccountCredential):
        assert entity not in FILTERABLE_REGISTRY, (
            f"{entity.__name__} 已注册数据权限 → 请更新本测试与验收报告 G9"
        )


# ============ FR-02e 部门岗位与组织节点 ============


async def test_account_binds_org_node_dept_and_position():
    """FR-02e：账户挂组织节点 + 部门 + 岗位（D10.03 授权的挂载点）"""
    await _clean()
    await _mk_account(
        f"{PREFIX}ORG",
        org_node_id=42,
        dept_name="供应链部",
        position="库存专员",
    )
    try:
        async with SessionFactory() as s:
            acc = await s.scalar(
                select(OrgAccount).where(
                    OrgAccount.login_name == f"{PREFIX}ORG"
                )
            )
        assert acc is not None
        assert int(acc.org_node_id) == 42
        assert acc.dept_name == "供应链部"
        assert acc.position == "库存专员"
    finally:
        await _clean()


async def test_account_org_node_defaults_to_zero():
    """FR-02e：未指定组织节点时默认 0（不挂靠任何节点）"""
    await _clean()
    await _mk_account(f"{PREFIX}NOORG")
    try:
        async with SessionFactory() as s:
            acc = await s.scalar(
                select(OrgAccount).where(OrgAccount.login_name == f"{PREFIX}NOORG")
            )
        assert acc is not None
        assert int(acc.org_node_id) == 0
    finally:
        await _clean()


# ============ FR-01c 租户与货主关联 ============


async def test_tenant_owner_scope_json_is_readable():
    """FR-01c：租户关联货主集（owner_scope_json）是外部租户隔离的**唯一数据来源**

    ⚠ DDL 有这列但 ORM 曾**漏映射** → 门户登录会话的 owner 范围读不到 → 本测试锁住该能力。
    """
    from app.models.hello import OrgTenant

    async with SessionFactory() as s:
        tenant = await s.scalar(
            select(OrgTenant).where(OrgTenant.tenant_code == f"{PREFIX}_TENANT")
        )
        if tenant is None:
            tenant = OrgTenant(
                tenant_code=f"{PREFIX}_TENANT",
                tenant_name="补测外部租户",
                tenant_type="external",
                owner_scope_json={"owner_ids": [11, 12]},
                contact_name="张三",
                contact_phone_hash=hashlib.sha1(f"{PREFIX}-phone".encode()).hexdigest(),
                source="local",
                status=1,
                version=0,
                is_deleted=0,
            )
            s.add(tenant)
            await s.commit()
            tid = int(tenant.id)
        else:
            tid = int(tenant.id)
        scope = tenant.owner_scope_json
    try:
        assert scope is not None, "租户未落 owner_scope_json"
        assert "owner_ids" in scope
    finally:
        async with SessionFactory() as s:
            await s.execute(text("DELETE FROM oms_org.org_tenant WHERE id = :i"), {"i": tid})
            await s.commit()


async def test_owner_table_carries_tenant_binding():
    """FR-01c：货主表带 tenant_id（租户↔货主关联的另一端）"""
    async with SessionFactory() as s:
        n = await s.scalar(
            text(
                "SELECT COUNT(*) FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA='oms_org' AND TABLE_NAME='org_owner' "
                "AND COLUMN_NAME='tenant_id' AND IS_NULLABLE='NO'"
            )
        )
    assert int(n or 0) == 1


# ============ FR-07 / 07a / 07b OIDC 预留结构 ============


async def test_idp_config_table_has_reserved_columns():
    """FR-07a：IdP 配置表预留结构（issuer/client_id/密钥引用/JWKS/映射策略/开关）"""
    async with SessionFactory() as s:
        cols = (
            await s.execute(
                text(
                    "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA='oms_org' AND TABLE_NAME='org_idp_config'"
                )
            )
        ).scalars().all()
    have = {str(c) for c in cols}
    for need in ("issuer", "client_id", "client_secret_ref", "jwks_uri", "mapping_policy", "enabled"):
        assert need in have, f"IdP 预留结构缺列：{need}"


async def test_idp_config_disabled_by_default():
    """FR-07b：本期只交付表结构与开关，**开关默认关闭**"""
    async with SessionFactory() as s:
        n = await s.scalar(
            text(
                "SELECT COUNT(*) FROM oms_org.org_idp_config "
                "WHERE enabled = 1 AND is_deleted = 0"
            )
        )
    assert int(n or 0) == 0, "存在已启用的 IdP 配置（本期不应启用）"


async def test_credential_has_sso_subject_mapping():
    """FR-07a：账户预留 sso_subject 映射字段（OIDC 账户绑定位）"""
    fields = set(OrgAccountCredential.__table__.columns.keys())
    assert "sso_subject" in fields
    assert "sso_idp_id" in fields
