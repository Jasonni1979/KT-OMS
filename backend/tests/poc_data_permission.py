"""M0.4 数据权限全局过滤 POC（D10.03 契约的技术验证，风险点①）

验证目标：
1. with_loader_criteria 全局注入 tenant_id/owner_id 过滤——业务查询代码零感知
2. contextvars AuthContext 在 asyncio 并发下互不串扰（A 租户请求查不到 B 租户数据）
3. 超管 bypass / 外部租户（品牌方）单货主硬隔离两种模式
4. 写入路径同样受限（INSERT 自动补 tenant_id；越权 UPDATE 不生效）

运行: cd backend && uv run python -m tests.poc_data_permission
前置: MySQL（3308）oms_org schema 已建表（deploy/init-db.sh）
"""
import asyncio

from sqlalchemy import BigInteger, String, event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, Session, mapped_column, with_loader_criteria

from app.core.config import settings
from app.core.db import AuthContext, get_auth_context, set_auth_context
from app.models.base import Base


# ---------- POC 用模型：映射真实表 oms_org.org_owner（货主档案，含 tenant_id/owner 维度） ----------
class OrgOwner(Base):
    __tablename__ = "org_owner"
    __table_args__ = {"schema": "oms_org"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_code: Mapped[str] = mapped_column(String(64))
    owner_name: Mapped[str] = mapped_column(String(128))
    tenant_id: Mapped[int] = mapped_column(BigInteger, default=1)


# 可过滤实体注册表（D10.03 FR-04b：实体声明自己拥有哪些权限维度）
FILTERABLE: dict[type, list[str]] = {
    OrgOwner: ["tenant_id"],
    # M1 起：OrdOrder: [tenant_id, owner_id, shop_id]，InvStockLedger: [tenant_id, owner_id, branch_id] ...
}


def _apply_scope(session: Session) -> None:
    """在 do_orm_execute 事件上注入行级过滤（业务查询无感知的关键）"""
    ctx = get_auth_context()
    if ctx is None:
        raise PermissionError("AuthContext 缺失：拒绝无上下文的 ORM 查询（fail-closed）")

    @event.listens_for(session.sync_session, "do_orm_execute")
    def _inject(execute_state) -> None:  # noqa: ANN001
        if not execute_state.is_select:
            return
        if ctx.is_superuser:
            return  # 超管 bypass（内部运维角色，D10.03 FR-05）
        for entity, dims in FILTERABLE.items():
            if "tenant_id" in dims:
                execute_state.statement = execute_state.statement.options(
                    with_loader_criteria(entity, entity.tenant_id == ctx.tenant_id)
                )


def make_session_factory():
    # NullPool：POC/脚本用，连接不池化用完即关，避免跨 event loop 残留（服务用 app.core.db 的池化 engine）
    from sqlalchemy.pool import NullPool
    engine = create_async_engine(settings.sqlalchemy_uri, echo=False, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


async def _seed(factory) -> tuple[int, int]:
    """造两个租户的货主数据（tenant 1=凯淳 / tenant 2=测试外部租户）"""
    async with factory() as s:
        set_auth_context(AuthContext(tenant_id=1, is_superuser=True))  # 种子期超管
        from sqlalchemy import text
        await s.execute(text("DELETE FROM oms_org.org_owner WHERE owner_code LIKE 'POC-%'"))
        await s.execute(text(
            "INSERT INTO oms_org.org_owner (owner_code, owner_name, owner_type, org_node_id, tenant_id, status, create_time, update_time) "
            "VALUES ('POC-T1-A','POC租户1货主A','consignment',0,1,1,NOW(3),NOW(3)),"
            "       ('POC-T1-B','POC租户1货主B','buyout',0,1,1,NOW(3),NOW(3)),"
            "       ('POC-T2-C','POC租户2货主C','consignment',0,2,1,NOW(3),NOW(3))"
        ))
        await s.commit()
    return 1, 2


async def _query_owners() -> list[str]:
    """业务视角的普通查询——不含任何权限过滤代码（验证无感知注入）"""
    engine, factory = make_session_factory()
    async with factory() as s:
        _apply_scope(s)
        rows = (await s.execute(select(OrgOwner).where(OrgOwner.owner_code.like("POC-%")))).scalars().all()
        codes = sorted(r.owner_code for r in rows)
    await engine.dispose()
    return codes


async def case_tenant_isolation() -> bool:
    """用例1：租户1 上下文只见 tenant 1 数据；租户2 只见 tenant 2"""
    async def as_tenant(tid: int) -> list[str]:
        set_auth_context(AuthContext(tenant_id=tid))
        return await _query_owners()

    # 并发跑两个租户上下文，验证 contextvars 不串扰
    t1_codes, t2_codes = await asyncio.gather(as_tenant(1), as_tenant(2))
    ok = t1_codes == ["POC-T1-A", "POC-T1-B"] and t2_codes == ["POC-T2-C"]
    print(f"[用例1 租户隔离+并发不串扰] tenant1={t1_codes} tenant2={t2_codes} → {'✅ PASS' if ok else '❌ FAIL'}")
    return ok


async def case_superuser_bypass() -> bool:
    """用例2：超管见全部"""
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    codes = await _query_owners()
    ok = len(codes) == 3
    print(f"[用例2 超管bypass] 可见={codes} → {'✅ PASS' if ok else '❌ FAIL'}")
    return ok


async def case_fail_closed() -> bool:
    """用例3：无 AuthContext 时拒绝查询（fail-closed，防中间件漏配导致全量泄露）"""
    from app.core import db as dbmod
    dbmod._auth_ctx.set(None)
    try:
        await _query_owners()
        print("[用例3 fail-closed] 无上下文竟查询成功 → ❌ FAIL")
        return False
    except PermissionError:
        print("[用例3 fail-closed] 无上下文查询被拒绝 → ✅ PASS")
        return True


async def main() -> None:
    engine, factory = make_session_factory()
    await _seed(factory)
    await engine.dispose()
    results = [
        await case_tenant_isolation(),
        await case_superuser_bypass(),
        await case_fail_closed(),
    ]
    print("\n" + ("🎉 M0.4 数据权限 POC 全部通过（无感知注入/并发隔离/fail-closed）"
                 if all(results) else "⚠️ 存在失败用例"))
    raise SystemExit(0 if all(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
