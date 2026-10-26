"""数据权限生产化测试（D10.03 FR-04 行级过滤 + §5.1 四步模型 + §5.2 注入形态）

对照 M0.4 spike 的四个验证点做生产化回归，并新增：
- 真实实体（OrgOwner/GwShop/FulBranch）行级过滤生效
- 业务查询代码零感知（查询语句不含任何权限条件）
- §5.2 注入形态：声明维度空集 → deny_all（返回空集而非报错，不暴露存在性）
- §5.1 四步模型：节点授权→子树展开→维度联动推导→并集合并
- 豁免通道显式放行
"""
import pytest
from sqlalchemy import select, text

from app.core.db import AuthContext, set_auth_context, without_data_scope
from app.models.branch import FulBranch
from app.models.org import OrgOwner
from app.models.shop import GwShop

pytestmark = pytest.mark.asyncio

CLEANUP = [
    "DELETE FROM oms_org.org_node WHERE org_code LIKE 'PERM\\_%'",
    "DELETE FROM oms_org.org_owner WHERE owner_code LIKE 'PERM\\_%'",
    "DELETE FROM oms_gateway.gw_shop WHERE shop_name LIKE 'PERM%'",
    "DELETE FROM oms_fulfill.ful_branch WHERE branch_name LIKE 'PERM%'",
    "DELETE FROM oms_org.org_data_permission WHERE reason LIKE 'PERM%'",
]


async def _cleanup():
    from app.core.db import engine
    async with engine.begin() as conn:
        for sql in CLEANUP:
            await conn.execute(text(sql))


@pytest.fixture(autouse=True, scope="module")
async def isolate_perm_data():
    await _cleanup()
    yield
    await _cleanup()


async def _seed_two_tenants() -> dict[str, int]:
    """造两个租户的数据：tenant1 货主A/B + 店铺 + 仓；tenant2 货主C（幂等：先清后插）"""
    from app.core.db import engine
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM oms_org.org_owner WHERE owner_code LIKE 'PERM\\_%'"))
        await conn.execute(text("DELETE FROM oms_gateway.gw_shop WHERE shop_name LIKE 'PERM%'"))
        await conn.execute(text("DELETE FROM oms_fulfill.ful_branch WHERE branch_name LIKE 'PERM%'"))
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO oms_org.org_owner "
            "(owner_code, owner_name, owner_type, org_node_id, tenant_id, status, create_time, update_time) "
            "VALUES ('PERM_T1_A','PERM租户1货主A','KC_BUYOUT',1,1,1,NOW(3),NOW(3)),"
            "       ('PERM_T1_B','PERM租户1货主B','BRAND_CONSIGN',1,1,1,NOW(3),NOW(3)),"
            "       ('PERM_T2_C','PERM租户2货主C','KC_BUYOUT',1,2,1,NOW(3),NOW(3))"
        ))
        await conn.execute(text(
            "INSERT INTO oms_gateway.gw_shop "
            "(owner_id, shop_bn, shop_name, platform, platform_shop_id, app_id, org_node_id, "
            " shop_type, business_type, auth_status, status, source, tenant_id, create_time, update_time) "
            "SELECT id, 'P000001', 'PERM店铺T1', 'taobao', 'p1', 0, 0, 'flagship', 'direct_sale', "
            "'pending', 'enabled', 'local', 1, NOW(3), NOW(3) "
            "FROM oms_org.org_owner WHERE owner_code='PERM_T1_A'"
        ))
        await conn.execute(text(
            "INSERT INTO oms_fulfill.ful_branch "
            "(owner_id, branch_bn, branch_name, branch_type, is_ctrl, countable_flag, "
            " is_declare, org_node_id, status, source, tenant_id, create_time, update_time) "
            "VALUES (NULL,'P000009','PERM仓','entity',1,1,0,0,'enabled','local',1,NOW(3),NOW(3))"
        ))
    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT owner_code, id FROM oms_org.org_owner WHERE owner_code LIKE 'PERM_%'"
        ))).all()
        shop = (await conn.execute(text(
            "SELECT id FROM oms_gateway.gw_shop WHERE shop_name='PERM店铺T1'"
        ))).scalar_one()
        branch = (await conn.execute(text(
            "SELECT id FROM oms_fulfill.ful_branch WHERE branch_name='PERM仓'"
        ))).scalar_one()
    ids = {r[0]: r[1] for r in rows}
    ids["shop"] = shop
    ids["branch"] = branch
    return ids


async def _query_owners() -> list[str]:
    """业务视角查询——不含任何权限条件（验证无感知注入）"""
    from app.core.db import SessionFactory
    async with SessionFactory() as s:
        rows = (await s.execute(
            select(OrgOwner).where(OrgOwner.owner_code.like("PERM_%"))
        )).scalars().all()
        return sorted(r.owner_code for r in rows)


async def test_row_level_filter_tenant_isolation():
    """核心：业务查询零感知，租户隔离自动生效（tenant_id 维度）"""
    ids = await _seed_two_tenants()
    set_auth_context(AuthContext(tenant_id=1, owner_ids=[ids["PERM_T1_A"], ids["PERM_T1_B"]]))
    t1 = await _query_owners()
    set_auth_context(AuthContext(tenant_id=2, owner_ids=[ids["PERM_T2_C"]]))
    t2 = await _query_owners()
    assert t1 == ["PERM_T1_A", "PERM_T1_B"]
    assert t2 == ["PERM_T2_C"]
    set_auth_context(None)


async def test_cross_tenant_owner_blocked():
    """跨租户：tenant1 上下文即便拿到 tenant2 的 owner_id 也查不到（租户维度恒过滤）"""
    ids = await _seed_two_tenants()
    set_auth_context(AuthContext(tenant_id=1, owner_ids=[ids["PERM_T2_C"]]))
    codes = await _query_owners()
    assert codes == []
    set_auth_context(None)


async def test_empty_scope_deny_all():
    """§5.2 注入形态：声明维度 scope 为空集 → 返回空结果（不暴露存在性，不报错）"""
    await _seed_two_tenants()
    set_auth_context(AuthContext(tenant_id=1, owner_ids=[]))
    codes = await _query_owners()
    assert codes == []
    set_auth_context(None)


async def test_fail_closed_without_context():
    """无 AuthContext → 拒绝查询（M0.4 用例3 生产化回归）"""
    from app.core.db import SessionFactory
    set_auth_context(None)
    async with SessionFactory() as s:
        with pytest.raises(PermissionError):
            await s.execute(select(OrgOwner))
    set_auth_context(None)


async def test_exemption_channel():
    """豁免通道：显式 without_data_scope() 放行全量"""
    from app.core.db import SessionFactory
    await _seed_two_tenants()
    set_auth_context(AuthContext(tenant_id=1, owner_ids=[]))
    async with SessionFactory() as s:
        with without_data_scope():
            rows = (await s.execute(
                select(OrgOwner).where(OrgOwner.owner_code.like("PERM_%"))
            )).scalars().all()
        assert len(rows) == 3  # 豁免后不受租户/维度限制
    set_auth_context(None)


async def test_shop_filtered_by_scope():
    """店铺过滤：scope 含该店 owner 维 + shop 维时可见（§5.2 各声明维度 AND 注入）"""
    from app.core.db import SessionFactory
    ids = await _seed_two_tenants()
    set_auth_context(AuthContext(
        tenant_id=1, owner_ids=[ids["PERM_T1_A"]], shop_ids=[ids["shop"]],
    ))
    async with SessionFactory() as s:
        rows = (await s.execute(select(GwShop))).scalars().all()
        assert len(rows) == 1 and rows[0].shop_name == "PERM店铺T1"
    set_auth_context(None)


async def test_shop_scope_missing_shop_dim_denied():
    """店铺声明 shop 维：scope 缺该维 → deny_all（§5.2 空集恒假）"""
    from app.core.db import SessionFactory
    ids = await _seed_two_tenants()
    set_auth_context(AuthContext(tenant_id=1, owner_ids=[ids["PERM_T1_A"]], shop_ids=[]))
    async with SessionFactory() as s:
        rows = (await s.execute(select(GwShop))).scalars().all()
        assert rows == []
    set_auth_context(None)


async def test_branch_filtered_by_branch_scope():
    """仓库过滤：branch 维 scope 放行指定仓"""
    from app.core.db import SessionFactory
    ids = await _seed_two_tenants()
    set_auth_context(AuthContext(tenant_id=1, branch_ids=[ids["branch"]]))
    async with SessionFactory() as s:
        rows = (await s.execute(select(FulBranch))).scalars().all()
        assert len(rows) == 1 and rows[0].branch_name == "PERM仓"
    set_auth_context(None)


async def test_four_step_model_scope_expansion():
    """§5.1 四步模型：节点授权 → 子树展开 → 维度联动推导 → 并集合并"""
    from app.core.db import SessionFactory, engine
    from app.modules.m1_master.service.master import get_redis
    from app.modules.m1_master.service.permission import PermissionService

    ids = await _seed_two_tenants()
    # 组织树：品牌节点 PERM_BRAND → 子节点：店铺节点(ref=shop) + 货主公司节点(ref=owner)
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO oms_org.org_node "
            "(tenant_id, org_code, org_name, node_type, parent_id, cat_path, node_level, "
            " ref_id, sort_no, status, remark, source, create_time, update_time) "
            "VALUES (1,'PERM_BRAND','PERM品牌','brand',1,'',2,0,0,1,'','local',NOW(3),NOW(3))"
        ))
        brand_id = (await conn.execute(text(
            "SELECT id FROM oms_org.org_node WHERE org_code='PERM_BRAND'"
        ))).scalar_one()
        await conn.execute(text(
            "INSERT INTO oms_org.org_node "
            "(tenant_id, org_code, org_name, node_type, parent_id, cat_path, node_level, "
            " ref_id, sort_no, status, remark, source, create_time, update_time) "
            f"VALUES (1,'PERM_SHOP_NODE','PERM店铺节点','shop',{brand_id},',{brand_id},',3,"
            f"{ids['shop']},0,1,'','local',NOW(3),NOW(3))"
        ))
        await conn.execute(text(
            "INSERT INTO oms_org.org_node "
            "(tenant_id, org_code, org_name, node_type, parent_id, cat_path, node_level, "
            " ref_id, sort_no, status, remark, source, create_time, update_time) "
            f"VALUES (1,'PERM_OWNER_NODE','PERM货主公司节点','owner_co',{brand_id},',{brand_id},',3,"
            f"{ids['PERM_T1_A']},0,1,'','local',NOW(3),NOW(3))"
        ))
        # 账户 999 授权品牌节点（dim_type=org_node, grant_scope=inherit）
        await conn.execute(text(
            "INSERT INTO oms_org.org_data_permission "
            "(tenant_id, account_id, dim_type, dim_id, grant_scope, grant_source, reason, "
            " grant_op, status, create_time, update_time) "
            f"VALUES (1,999,'org_node',{brand_id},'inherit','direct','PERM授权','seed',1,NOW(3),NOW(3))"
        ))

    redis = await get_redis()
    await redis.delete("perm:scope:999")
    async with SessionFactory() as s:
        scope = await PermissionService(s, redis).get_scope(999, 1)
    # ② 展开：shop 节点 → shop_ids；owner_co 节点 → owner_ids
    assert ids["shop"] in scope.shop_ids
    assert ids["PERM_T1_A"] in scope.owner_ids
    assert scope.source in ("inherit", "direct", "role_custom")
    await redis.delete("perm:scope:999")


async def test_scope_cache_hit():
    """§5.2/FR-08a：scope 缓存命中（第二次解析走 Redis，不查库）"""
    from app.core.db import SessionFactory
    from app.modules.m1_master.service.master import get_redis
    from app.modules.m1_master.service.permission import PermissionService

    redis = await get_redis()
    await redis.set("perm:scope:998", '{"tenant_id":1,"all":false,"owner_ids":[42],'
                                     '"shop_ids":[],"branch_ids":[],"brand_ids":[],"source":"cache"}')
    async with SessionFactory() as s:
        scope = await PermissionService(s, redis).get_scope(998, 1)
    assert scope.owner_ids == [42] and scope.source == "cache"
    await redis.delete("perm:scope:998")


async def test_api_401_without_token():
    """接口层：无 token → 401（中间件不注入默认超管上下文，fail-closed 生效）"""
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/api/v1/master/owners")
        assert r.status_code == 401
