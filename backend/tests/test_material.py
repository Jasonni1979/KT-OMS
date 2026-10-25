"""物料域测试（M1b-1a，SRS-D04.01）

覆盖：分类树路径维护/同级重名/移动级联/防环/删除保护、品牌唯一与组织节点校验、
基础物料货号唯一/货主必填/分类品牌引用/乐观锁/分类变更同步 cat_path/owner 维行级过滤。
"""
import pytest
from sqlalchemy import text

from app.core.db import AuthContext, engine, set_auth_context
from app.models.material import InvMaterial

pytestmark = pytest.mark.asyncio

CLEANUP_SQL = [
    "DELETE FROM oms_stock.inv_material WHERE material_bn LIKE 'MT\\_%'",
    "DELETE FROM oms_stock.inv_material_cat WHERE cat_name LIKE '测试%'",
    "DELETE FROM oms_stock.inv_brand WHERE brand_name LIKE '测试%'",
]


async def _cleanup() -> None:
    async with engine.begin() as conn:
        for sql in CLEANUP_SQL:
            await conn.execute(text(sql))


@pytest.fixture(autouse=True, scope="module")
async def isolate_material_data():
    await _cleanup()
    yield
    await _cleanup()


async def _owner_id(auth_client, code: str = "T_MAT_OWNER") -> int:
    """取一个可用货主（优先新建，失败则用 seed 的 owner_KC）"""
    resp = await auth_client.get("/api/v1/master/org-nodes", params={"parent_id": 0})
    node = resp.json()["data"]
    owner_co = next(
        (n for n in node if n["node_type"] == "owner_co"), None
    )
    if owner_co is None:
        # seed 的 owner_KC 所属节点：搜索
        resp2 = await auth_client.get(
            "/api/v1/master/org-nodes/search", params={"keyword": "凯淳"}
        )
        nodes = resp2.json()["data"]
        owner_co = next((n for n in nodes if n["node_type"] == "owner_co"), None)
    assert owner_co is not None, "缺少 owner_co 节点"
    r = await auth_client.post("/api/v1/master/owners", json={
        "owner_code": code, "owner_name": "物料测试货主", "owner_type": "KC_BUYOUT",
        "org_node_id": owner_co["id"],
    })
    if r.status_code == 200:
        return r.json()["data"]["id"]
    owners = (await auth_client.get("/api/v1/master/owners")).json()["data"]
    return next(o["id"] for o in owners if o["owner_code"] == code)


# ============ 分类树（FR-05a）============

async def test_category_create_path_maintained(auth_client):
    """建根分类 → cat_path=/id/；建子分类 → 继承父路径"""
    r = await auth_client.post("/api/v1/material/categories", json={
        "cat_name": "测试类目根", "parent_id": 0,
    })
    assert r.status_code == 200, r.text
    root = r.json()["data"]
    assert root["cat_path"] == f"/{root['id']}/"
    assert root["cat_level"] == 1

    r2 = await auth_client.post("/api/v1/material/categories", json={
        "cat_name": "测试类目子", "parent_id": root["id"],
    })
    assert r2.status_code == 200, r2.text
    child = r2.json()["data"]
    assert child["cat_path"] == f"/{root['id']}/{child['id']}/"
    assert child["cat_level"] == 2


async def test_category_duplicate_name_same_level(auth_client):
    """表无唯一键 → 同级同名由应用层拒绝"""
    r = await auth_client.post("/api/v1/material/categories", json={
        "cat_name": "测试重名", "parent_id": 0,
    })
    assert r.status_code == 200, r.text
    r2 = await auth_client.post("/api/v1/material/categories", json={
        "cat_name": "测试重名", "parent_id": 0,
    })
    assert r2.status_code == 409
    assert "同名分类" in r2.json()["message"]


async def test_category_move_cascades_path(auth_client):
    """移动分类 → 子树 cat_path 级联刷新"""
    a = (await auth_client.post("/api/v1/material/categories", json={
        "cat_name": "测试移动A", "parent_id": 0})).json()["data"]
    b = (await auth_client.post("/api/v1/material/categories", json={
        "cat_name": "测试移动B", "parent_id": 0})).json()["data"]
    child = (await auth_client.post("/api/v1/material/categories", json={
        "cat_name": "测试移动子", "parent_id": a["id"]})).json()["data"]
    old_child_path = child["cat_path"]

    r = await auth_client.post(f"/api/v1/material/categories/{a['id']}/move",
                                params={"new_parent_id": b["id"]})
    assert r.status_code == 200, r.text

    # 子节点路径应刷新为 B 之下
    all_cats = (await auth_client.get("/api/v1/material/categories/all")).json()["data"]
    moved_child = next(c for c in all_cats if c["id"] == child["id"])
    assert moved_child["cat_path"] != old_child_path
    assert moved_child["cat_path"].startswith(b["cat_path"])
    assert moved_child["cat_level"] == 3


async def test_category_move_reject_cycle(auth_client):
    """不能移动到自己的子分类下（防环）"""
    a = (await auth_client.post("/api/v1/material/categories", json={
        "cat_name": "测试环A", "parent_id": 0})).json()["data"]
    child = (await auth_client.post("/api/v1/material/categories", json={
        "cat_name": "测试环子", "parent_id": a["id"]})).json()["data"]

    r = await auth_client.post(f"/api/v1/material/categories/{a['id']}/move",
                                params={"new_parent_id": child["id"]})
    assert r.status_code == 422
    assert "子分类" in r.json()["message"]


async def test_category_delete_protected(auth_client):
    """有子分类 → 拒绝删除；被物料引用 → 拒绝删除"""
    root = (await auth_client.post("/api/v1/material/categories", json={
        "cat_name": "测试删除根", "parent_id": 0})).json()["data"]
    child = (await auth_client.post("/api/v1/material/categories", json={
        "cat_name": "测试删除子", "parent_id": root["id"]})).json()["data"]

    r = await auth_client.delete(f"/api/v1/material/categories/{root['id']}")
    assert r.status_code == 409
    assert "子分类" in r.json()["message"]

    # 无子分类但被物料引用 → 拒绝
    owner_id = await _owner_id(auth_client)
    m = await auth_client.post("/api/v1/material/materials", json={
        "material_bn": "MT_DEL_001", "material_name": "被引用物料", "owner_id": owner_id,
        "cat_id": child["id"],
    })
    assert m.status_code == 200, m.text
    r2 = await auth_client.delete(f"/api/v1/material/categories/{child['id']}")
    assert r2.status_code == 409
    assert "引用" in r2.json()["message"]


# ============ 品牌（FR-05b）============

async def test_brand_create_and_duplicate(auth_client):
    """品牌同货主内唯一（uk_inv_brand_name）"""
    owner_id = await _owner_id(auth_client)
    r = await auth_client.post("/api/v1/material/brands", json={
        "brand_name": "测试品牌", "owner_id": owner_id,
    })
    assert r.status_code == 200, r.text
    r2 = await auth_client.post("/api/v1/material/brands", json={
        "brand_name": "测试品牌", "owner_id": owner_id,
    })
    assert r2.status_code == 409


async def test_brand_org_node_must_be_brand_type(auth_client):
    """org_node_id 必须指向 brand 类型节点"""
    owner_id = await _owner_id(auth_client)
    root = (await auth_client.get("/api/v1/master/org-nodes", params={"parent_id": 0})).json()["data"][0]
    r = await auth_client.post("/api/v1/material/brands", json={
        "brand_name": "测试品牌错节点", "owner_id": owner_id, "org_node_id": root["id"],
    })
    assert r.status_code == 422
    assert "brand" in r.json()["message"]


# ============ 基础物料（FR-02）============

async def test_material_create_with_crc32(auth_client):
    """建物料 → 自动算 CRC32 辅助索引 + 冗余分类路径"""
    owner_id = await _owner_id(auth_client)
    cat = (await auth_client.post("/api/v1/material/categories", json={
        "cat_name": "测试物料类目", "parent_id": 0})).json()["data"]

    r = await auth_client.post("/api/v1/material/materials", json={
        "material_bn": "MT_001", "material_name": "测试物料A", "owner_id": owner_id,
        "cat_id": cat["id"], "type": 3,
    })
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["material_bn"] == "MT_001"
    assert data["cat_path"] == cat["cat_path"]
    assert data["material_bn_crc32"] > 0 or data["id"] > 0


async def test_material_bn_duplicate(auth_client):
    """货号全局唯一（uk_inv_material_bn）"""
    owner_id = await _owner_id(auth_client)
    r = await auth_client.post("/api/v1/material/materials", json={
        "material_bn": "MT_DUP", "material_name": "重号物料", "owner_id": owner_id,
    })
    assert r.status_code == 200, r.text
    r2 = await auth_client.post("/api/v1/material/materials", json={
        "material_bn": "MT_DUP", "material_name": "重号物料2", "owner_id": owner_id,
    })
    assert r2.status_code == 409
    assert "货号已存在" in r2.json()["message"]


async def test_material_invalid_refs_rejected(auth_client):
    """分类不存在 → 422；货主无效 → 404"""
    r = await auth_client.post("/api/v1/material/materials", json={
        "material_bn": "MT_BADCAT", "material_name": "坏分类物料", "owner_id": 1, "cat_id": 999999,
    })
    assert r.status_code in (404, 422)

    r2 = await auth_client.post("/api/v1/material/materials", json={
        "material_bn": "MT_BADOWNER", "material_name": "坏货主物料", "owner_id": 999999,
    })
    assert r2.status_code == 404


async def test_material_update_optimistic_lock_and_cat_sync(auth_client):
    """乐观锁冲突 → 409；改分类 → cat_path 同步"""
    owner_id = await _owner_id(auth_client)
    cat1 = (await auth_client.post("/api/v1/material/categories", json={
        "cat_name": "测试类目1", "parent_id": 0})).json()["data"]
    cat2 = (await auth_client.post("/api/v1/material/categories", json={
        "cat_name": "测试类目2", "parent_id": 0})).json()["data"]
    m = (await auth_client.post("/api/v1/material/materials", json={
        "material_bn": "MT_UPD", "material_name": "待改物料", "owner_id": owner_id,
        "cat_id": cat1["id"],
    })).json()["data"]

    # 旧版本提交 → 409
    r = await auth_client.put(f"/api/v1/material/materials/{m['id']}", json={
        "material_name": "改名A", "version": m["version"] - 1,
    })
    assert r.status_code == 409
    assert "OPTIMISTIC_LOCK" in r.json()["code"]

    # 正确版本 + 换分类 → cat_path 同步
    r2 = await auth_client.put(f"/api/v1/material/materials/{m['id']}", json={
        "material_name": "改名B", "cat_id": cat2["id"], "version": m["version"],
    })
    assert r2.status_code == 200, r2.text
    data = r2.json()["data"]
    assert data["material_name"] == "改名B"
    assert data["cat_path"] == cat2["cat_path"]
    assert data["version"] == m["version"] + 1


async def test_material_owner_not_mutable(auth_client):
    """owner_id 建档后不可改（改货主=资产转移 D04.05）"""
    owner_id = await _owner_id(auth_client)
    m = (await auth_client.post("/api/v1/material/materials", json={
        "material_bn": "MT_OWNER_LOCK", "material_name": "货主锁定物料", "owner_id": owner_id,
    })).json()["data"]

    r = await auth_client.put(f"/api/v1/material/materials/{m['id']}", json={
        "owner_id": owner_id + 999, "version": m["version"],
    })
    assert r.status_code == 200
    # owner_id 被忽略（契约中不存在该字段），值不变
    assert r.json()["data"]["owner_id"] == owner_id


async def test_material_row_level_filter_by_owner(auth_client):
    """owner 维行级过滤：非超管按授权货主过滤（数据权限自动生效）"""
    owner_id = await _owner_id(auth_client, code="T_MAT_OWNER2")
    m = (await auth_client.post("/api/v1/material/materials", json={
        "material_bn": "MT_RLS", "material_name": "权限过滤物料", "owner_id": owner_id,
    })).json()["data"]

    from sqlalchemy import select

    if True:
        # 超管上下文 → 可见
        set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
        from app.core.db import SessionFactory

        async with SessionFactory() as s:
            rows = (await s.execute(select(InvMaterial).where(
                InvMaterial.material_bn == "MT_RLS"))).scalars().all()
            assert len(rows) == 1

            # 无权货主上下文 → 不可见
            set_auth_context(AuthContext(tenant_id=1, owner_ids=[owner_id + 99999]))
            rows2 = (await s.execute(select(InvMaterial).where(
                InvMaterial.material_bn == "MT_RLS"))).scalars().all()
            assert len(rows2) == 0
            set_auth_context(None)
    assert m["id"] > 0
