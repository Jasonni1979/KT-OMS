"""超管账户初始化（幂等）：R_SUPER 角色 + admin 账户 + 初始密码

FR-08a 超管账户引导；初始密码 Ktoms@2026（首登应改密，must_change_pwd=1）。
用法：.venv/bin/python -m app.scripts.seed_auth
"""
import asyncio

from sqlalchemy import select

from app.core.db import SessionFactory, engine
from app.core.security import hash_password
from app.models.account import OrgAccount, OrgAccountCredential, OrgAccountRole, OrgRole

INIT_PASSWORD = "Ktoms@2026"


async def seed() -> None:
    async with SessionFactory() as s:
        # 1) 超管角色（system 预置，data_scope_mode=all）
        role = await s.scalar(select(OrgRole).where(OrgRole.role_code == "R_SUPER"))
        if not role:
            role = OrgRole(
                tenant_id=1, role_code="R_SUPER", role_name="超级管理员",
                role_type="system", data_scope_mode="all", remark="FR-08a 预置",
            )
            s.add(role)
            await s.flush()
            print(f"[seed] R_SUPER 角色创建: id={role.id}")
        else:
            print("[seed] R_SUPER 已存在（幂等跳过）")

        # 2) admin 账户
        account = await s.scalar(select(OrgAccount).where(OrgAccount.login_name == "admin"))
        if not account:
            account = OrgAccount(
                tenant_id=1, account_type="staff", login_name="admin",
                account_name="系统管理员", org_node_id=1, status=2, source="local",
                create_op="seed",
            )
            s.add(account)
            await s.flush()
            # 3) 密码凭证
            s.add(OrgAccountCredential(
                tenant_id=1, account_id=account.id, credential_type="password",
                password_hash=hash_password(INIT_PASSWORD), must_change_pwd=1,
            ))
            # 4) 绑定超管角色
            s.add(OrgAccountRole(
                tenant_id=1, account_id=account.id, role_id=role.id, grant_op="seed",
            ))
            print(f"[seed] admin 账户创建: id={account.id}（初始密码 {INIT_PASSWORD}，首登强制改密）")
        else:
            print("[seed] admin 已存在（幂等跳过）")

        await s.commit()
        print("[seed] 完成")


if __name__ == "__main__":
    async def _main():
        await seed()
        await engine.dispose()

    asyncio.run(_main())
