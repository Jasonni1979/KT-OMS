"""档案域测试（D10.01）：层级矩阵/单根/编码唯一/联动建档/乐观锁/货主校验

测试数据隔离：模块级 autouse fixture 前后清理 T_% / SHOP_% / WH_% 与测试店铺/仓库/货主，
保证可重复执行（CI 与本地一致）。
"""
import pytest
from sqlalchemy import text

from app.core.db import engine

pytestmark = pytest.mark.asyncio

CLEANUP_SQL = [
    "DELETE FROM oms_org.org_node "
    "WHERE org_code LIKE 'T\\_%' OR org_code LIKE 'SHOP\\_%' OR org_code LIKE 'WH\\_%'",
    "DELETE FROM oms_org.org_owner WHERE owner_code LIKE 'T\\_%'",
    "DELETE FROM oms_gateway.gw_shop WHERE shop_name LIKE '测试%'",
    "DELETE FROM oms_fulfill.ful_branch WHERE branch_name LIKE '测试%' OR branch_name LIKE '多货主%'",
]


async def _cleanup() -> None:
    async with engine.begin() as conn:
        for sql in CLEANUP_SQL:
            await conn.execute(text(sql))


@pytest.fixture(autouse=True, scope="module")
async def isolate_master_data():
    await _cleanup()
    yield
    await _cleanup()


async def test_org_seed_ready(auth_client):
    """FR-08a：seed 后根节点与默认货主存在"""
    r = await auth_client.get("/api/v1/master/org-nodes", params={"parent_id": 0})
    assert r.status_code == 200
    nodes = r.json()["data"]
    assert any(n["org_code"] == "KC_ROOT" and n["node_type"] == "group" for n in nodes)
    r2 = await auth_client.get("/api/v1/master/owners")
    assert any(o["owner_code"] == "owner_KC" for o in r2.json()["data"])


async def test_hierarchy_matrix_violation(auth_client):
    """§5.1：group 下不允许直接挂 shop"""
    root = (await auth_client.get("/api/v1/master/org-nodes", params={"parent_id": 0})).json()["data"][0]
    r = await auth_client.post("/api/v1/master/org-nodes", json={
        "org_code": "T_BAD_SHOP", "org_name": "违例店铺", "node_type": "shop",
        "parent_id": root["id"], "ref_id": 999,
    })
    assert r.status_code == 422
    assert "层级约束违例" in r.json()["message"]


async def test_group_single_root(auth_client):
    """FR-01e：group 唯一根"""
    r = await auth_client.post("/api/v1/master/org-nodes", json={
        "org_code": "T_SECOND_ROOT", "org_name": "第二集团", "node_type": "group", "parent_id": 0,
    })
    assert r.status_code == 409


async def test_node_crud_and_dup_code(auth_client):
    """FR-02：建 brand 节点→重名/重码拦截→停用→软删"""
    root = (await auth_client.get("/api/v1/master/org-nodes", params={"parent_id": 0})).json()["data"][0]
    r = await auth_client.post("/api/v1/master/org-nodes", json={
        "org_code": "T_BRAND_01", "org_name": "测试品牌01", "node_type": "brand", "parent_id": root["id"],
    })
    assert r.status_code == 200, r.text
    node = r.json()["data"]
    assert node["cat_path"] == f",{root['id']},{node['id']},"  # §5.2 路径补全
    # 重码
    r2 = await auth_client.post("/api/v1/master/org-nodes", json={
        "org_code": "T_BRAND_01", "org_name": "另一名字", "node_type": "brand", "parent_id": root["id"],
    })
    assert r2.status_code == 409
    # 启用中不可删
    r3 = await auth_client.delete(f"/api/v1/master/org-nodes/{node['id']}")
    assert r3.status_code == 422
    # 停用 → 删除
    r4 = await auth_client.put(
        f"/api/v1/master/org-nodes/{node['id']}", json={"status": 2, "version": node["version"]}
    )
    assert r4.status_code == 200
    r5 = await auth_client.delete(f"/api/v1/master/org-nodes/{node['id']}")
    assert r5.status_code == 200


async def test_optimistic_lock(auth_client):
    """乐观锁：过期 version 提交冲突"""
    root = (await auth_client.get("/api/v1/master/org-nodes", params={"parent_id": 0})).json()["data"][0]
    r = await auth_client.post("/api/v1/master/org-nodes", json={
        "org_code": "T_LOCK_01", "org_name": "锁测试", "node_type": "dept", "parent_id": root["id"],
    })
    node = r.json()["data"]
    r1 = await auth_client.put(f"/api/v1/master/org-nodes/{node['id']}", json={"remark": "改1", "version": 0})
    assert r1.status_code == 200
    r2 = await auth_client.put(f"/api/v1/master/org-nodes/{node['id']}", json={"remark": "改2", "version": 0})
    assert r2.status_code == 409 and r2.json()["code"] == "OPTIMISTIC_LOCK"
    await auth_client.put(f"/api/v1/master/org-nodes/{node['id']}", json={"status": 2, "version": 1})
    await auth_client.delete(f"/api/v1/master/org-nodes/{node['id']}")


async def test_owner_requires_owner_co_node(auth_client):
    """FR-03b：货主必须挂 owner_co 节点"""
    root = (await auth_client.get("/api/v1/master/org-nodes", params={"parent_id": 0})).json()["data"][0]
    r = await auth_client.post("/api/v1/master/owners", json={
        "owner_code": "T_OWNER_BAD", "owner_name": "挂错节点", "owner_type": "KC_BUYOUT",
        "org_node_id": root["id"],  # group 节点，非法
    })
    assert r.status_code == 422


async def test_owner_create_and_taxno(auth_client):
    """FR-03：合法建货主 + 税号格式校验"""
    resp = await auth_client.get("/api/v1/master/org-nodes/search", params={"keyword": "KC_TRADE_CO"})
    nodes = resp.json()["data"]
    co = nodes[0]
    r = await auth_client.post("/api/v1/master/owners", json={
        "owner_code": "T_OWNER_01", "owner_name": "测试货主01", "owner_type": "BRAND_CONSIGN",
        "org_node_id": co["id"], "tax_no": "123",
    })
    assert r.status_code == 422  # 税号格式错误
    r2 = await auth_client.post("/api/v1/master/owners", json={
        "owner_code": "T_OWNER_01", "owner_name": "测试货主01", "owner_type": "BRAND_CONSIGN",
        "org_node_id": co["id"], "tax_no": "91330100MA27XW2H1K",
    })
    assert r2.status_code == 200, r2.text


async def test_shop_creates_org_node(auth_client):
    """FR-02a：店铺建档联动组织树 shop 节点 + ref_id 双向引用"""
    resp = await auth_client.get("/api/v1/master/org-nodes/search", params={"keyword": "KC_TRADE_CO"})
    co = resp.json()["data"][0]
    owners = (await auth_client.get("/api/v1/master/owners")).json()["data"]
    owner = next(o for o in owners if o["owner_code"] == "owner_KC")
    r = await auth_client.post("/api/v1/master/shops", params={"parent_node_id": co["id"]}, json={
        "shop_name": "测试天猫旗舰店", "owner_id": owner["id"], "platform": "taobao",
        "platform_shop_id": "sim_seller_001",
    })
    assert r.status_code == 200, r.text
    shop = r.json()["data"]
    assert shop["shop_bn"].startswith("S")
    assert shop["org_node_id"] > 0
    resp = await auth_client.get("/api/v1/master/org-nodes/search", params={"keyword": "测试天猫旗舰店"})
    nodes = resp.json()["data"]
    assert any(n["node_type"] == "shop" and n["ref_id"] == shop["id"] for n in nodes)


async def test_branch_creates_warehouse_node(auth_client):
    """仓库建档联动 warehouse 节点直属根；多货主仓必须管控"""
    r_bad = await auth_client.post("/api/v1/master/branches", json={
        "branch_name": "多货主仓不控", "owner_id": None, "is_ctrl": 0,
    })
    assert r_bad.status_code == 422
    r = await auth_client.post("/api/v1/master/branches", json={
        "branch_name": "测试华东仓", "owner_id": None, "branch_type": "entity",
        "region_code": "EAST", "province": "上海", "city": "上海", "cutoff_time": "16:30",
    })
    assert r.status_code == 200, r.text
    b = r.json()["data"]
    assert b["branch_bn"].startswith("B") and b["org_node_id"] > 0
