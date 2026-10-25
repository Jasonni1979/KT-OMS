"""销售物料与 BOM 绑定测试（M1b-1b，SRS-D04.01 FR-01/FR-03）

覆盖：手工建档/店铺内编码唯一/自动建档幂等/绑定成功与货主回填/跨货主拒绝/
占比合计校验/纯固定价模式/版本化留痕/解绑/组合装嵌套约束/组合装类型改写/
待绑定清单/自动绑定建议。
"""
import pytest
from sqlalchemy import text

from app.core.db import engine

pytestmark = pytest.mark.asyncio

CLEANUP_SQL = [
    "DELETE FROM oms_stock.inv_bom_item WHERE sm_id IN "
    "(SELECT id FROM oms_stock.inv_sales_material WHERE sales_material_bn LIKE 'SM\\_%')",
    "DELETE FROM oms_stock.inv_bom_version WHERE sm_id IN "
    "(SELECT id FROM oms_stock.inv_sales_material WHERE sales_material_bn LIKE 'SM\\_%')",
    "DELETE FROM oms_stock.inv_sales_material WHERE sales_material_bn LIKE 'SM\\_%'",
    "DELETE FROM oms_stock.inv_material WHERE material_bn LIKE 'BM\\_%'",
    "DELETE FROM oms_stock.inv_material_cat WHERE cat_name LIKE '测试BOM%'",
    "DELETE FROM oms_gateway.gw_shop WHERE shop_name LIKE '测试BOM%'",
    "DELETE FROM oms_org.org_node WHERE org_code LIKE 'SHOP\\_BOM\\_%'",
    "DELETE FROM oms_org.org_owner WHERE owner_code LIKE 'T\\_BOM\\_%'",
]


async def _cleanup() -> None:
    async with engine.begin() as conn:
        for sql in CLEANUP_SQL:
            await conn.execute(text(sql))


@pytest.fixture(autouse=True, scope="module")
async def isolate_bom_data():
    await _cleanup()
    yield
    await _cleanup()


async def _owner_co_node_id() -> int:
    async with engine.begin() as conn:
        r = await conn.execute(
            text("SELECT id FROM oms_org.org_node "
                 "WHERE node_type='owner_co' AND is_deleted=0 LIMIT 1")
        )
        return int(r.scalar())


async def _make_owner(auth_client, code: str, name: str) -> dict:
    r = await auth_client.post("/api/v1/master/owners", json={
        "owner_code": code, "owner_name": name, "owner_type": "KC_BUYOUT",
        "org_node_id": await _owner_co_node_id(),
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _make_shop(auth_client, name: str, owner_id: int) -> dict:
    # platform_shop_id 参与唯一键 (platform, platform_shop_id) → 每个店给唯一平台码
    r = await auth_client.post(
        f"/api/v1/master/shops?parent_node_id={await _owner_co_node_id()}",
        json={"shop_name": name, "owner_id": owner_id, "platform": "taobao",
              "platform_shop_id": f"tb_{name}",
              "shop_type": "flagship", "business_type": "direct_sale"},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _make_material(
    auth_client, bn: str, name: str, owner_id: int, mtype: int = 3
) -> dict:
    r = await auth_client.post("/api/v1/material/materials", json={
        "material_bn": bn, "material_name": name, "owner_id": owner_id, "type": mtype,
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _make_sm(auth_client, bn: str, name: str, shop_id: int) -> dict:
    r = await auth_client.post("/api/v1/material/sales-materials", json={
        "shop_id": shop_id, "sales_material_bn": bn, "sales_material_name": name,
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


# ============ 销售物料（FR-01）============

async def test_sales_material_create_and_dup(auth_client):
    """手工建档 + 店铺内平台编码唯一"""
    owner = await _make_owner(auth_client, "T_BOM_O1", "BOM测试货主1")
    shop = await _make_shop(auth_client, "测试BOM店铺1", owner["id"])

    sm = await _make_sm(auth_client, "SM_001", "测试销售物料1", shop["id"])
    assert sm["bind_status"] == 0
    assert sm["owner_id"] == 0  # 未绑定时无归属货主

    r = await auth_client.post("/api/v1/material/sales-materials", json={
        "shop_id": shop["id"], "sales_material_bn": "SM_001", "sales_material_name": "重复",
    })
    assert r.status_code == 409


async def test_auto_create_is_idempotent(auth_client):
    """FR-01a 自动建档幂等：同店铺同编码只建一次"""
    owner = await _make_owner(auth_client, "T_BOM_O2", "BOM测试货主2")
    shop = await _make_shop(auth_client, "测试BOM店铺2", owner["id"])
    payload = {
        "shop_id": shop["id"], "sales_material_bn": "SM_AUTO",
        "sales_material_name": "自动建档物料", "spec_text": "红色 M码",
    }
    r1 = await auth_client.post("/api/v1/material/sales-materials/auto", json=payload)
    assert r1.status_code == 200, r1.text
    d1 = r1.json()["data"]
    assert d1["created"] is True
    assert d1["material"]["source"] == "api"

    r2 = await auth_client.post("/api/v1/material/sales-materials/auto", json=payload)
    assert r2.status_code == 200
    d2 = r2.json()["data"]
    assert d2["created"] is False
    assert d2["material"]["id"] == d1["material"]["id"]


async def test_unbound_list(auth_client):
    """FR-01c 待绑定清单"""
    owner = await _make_owner(auth_client, "T_BOM_O3", "BOM测试货主3")
    shop = await _make_shop(auth_client, "测试BOM店铺3", owner["id"])
    await _make_sm(auth_client, "SM_UNB", "待绑定物料", shop["id"])

    r = await auth_client.get("/api/v1/material/sales-materials/unbound")
    assert r.status_code == 200, r.text
    assert any(s["sales_material_bn"] == "SM_UNB" for s in r.json()["data"])


# ============ BOM 绑定（FR-03）============

async def test_bom_bind_success_and_owner_backfill(auth_client):
    """绑定成功 → bind_status=1 + owner_id 回填"""
    owner = await _make_owner(auth_client, "T_BOM_O4", "BOM测试货主4")
    shop = await _make_shop(auth_client, "测试BOM店铺4", owner["id"])
    bm = await _make_material(auth_client, "BM_001", "基础物料甲", owner["id"])
    sm = await _make_sm(auth_client, "SM_B1", "普通单商品", shop["id"])

    r = await auth_client.post(f"/api/v1/material/sales-materials/{sm['id']}/bom", json={
        "items": [{"bm_id": bm["id"], "bind_num": 1, "rate": 100}],
        "operator": "tester",
    })
    assert r.status_code == 200, r.text
    bom = r.json()["data"]
    assert bom["version_no"] == 1
    assert bom["status"] == 2  # 生效
    assert len(bom["items"]) == 1
    assert bom["items"][0]["material_bn"] == "BM_001"

    # 销售物料回填
    sm2 = (await auth_client.get("/api/v1/material/sales-materials", params={
        "keyword": "SM_B1"})).json()["data"][0]
    assert sm2["bind_status"] == 1
    assert sm2["owner_id"] == owner["id"]


async def test_bom_reject_cross_owner(auth_client):
    """§6.1 同货主校验：跨货主组合拒绝"""
    o1 = await _make_owner(auth_client, "T_BOM_O5", "BOM测试货主5")
    o2 = await _make_owner(auth_client, "T_BOM_O6", "BOM测试货主6")
    shop = await _make_shop(auth_client, "测试BOM店铺5", o1["id"])
    bm1 = await _make_material(auth_client, "BM_X1", "跨货主物料甲", o1["id"])
    bm2 = await _make_material(auth_client, "BM_X2", "跨货主物料乙", o2["id"])
    sm = await _make_sm(auth_client, "SM_X", "跨货主组合", shop["id"])

    r = await auth_client.post(f"/api/v1/material/sales-materials/{sm['id']}/bom", json={
        "items": [
            {"bm_id": bm1["id"], "bind_num": 1, "rate": 50},
            {"bm_id": bm2["id"], "bind_num": 1, "rate": 50},
        ],
    })
    assert r.status_code == 422
    assert "同货主" in r.json()["message"]


async def test_bom_rate_sum_must_be_100(auth_client):
    """§6.3 占比合计必须 100%"""
    owner = await _make_owner(auth_client, "T_BOM_O7", "BOM测试货主7")
    shop = await _make_shop(auth_client, "测试BOM店铺6", owner["id"])
    bm1 = await _make_material(auth_client, "BM_R1", "占比物料甲", owner["id"])
    bm2 = await _make_material(auth_client, "BM_R2", "占比物料乙", owner["id"])
    sm = await _make_sm(auth_client, "SM_R", "占比校验单", shop["id"])

    r = await auth_client.post(f"/api/v1/material/sales-materials/{sm['id']}/bom", json={
        "items": [
            {"bm_id": bm1["id"], "bind_num": 1, "rate": 60},
            {"bm_id": bm2["id"], "bind_num": 1, "rate": 30},
        ],
    })
    assert r.status_code == 422
    assert "100%" in r.json()["message"]


async def test_bom_pure_fixed_price_allowed(auth_client):
    """纯固定价模式（rate 全 0）不校验占比合计"""
    owner = await _make_owner(auth_client, "T_BOM_O8", "BOM测试货主8")
    shop = await _make_shop(auth_client, "测试BOM店铺7", owner["id"])
    bm1 = await _make_material(auth_client, "BM_F1", "固定价物料甲", owner["id"])
    bm2 = await _make_material(auth_client, "BM_F2", "固定价物料乙", owner["id"])
    sm = await _make_sm(auth_client, "SM_F", "固定价组合", shop["id"])

    r = await auth_client.post(f"/api/v1/material/sales-materials/{sm['id']}/bom", json={
        "items": [
            {"bm_id": bm1["id"], "bind_num": 1, "fixed_price": 39.9},
            {"bm_id": bm2["id"], "bind_num": 1, "fixed_price": 19.9},
        ],
    })
    assert r.status_code == 200, r.text
    items = r.json()["data"]["items"]
    assert all(i["rate"] == 0 for i in items)
    assert {i["fixed_price"] for i in items} == {39.9, 19.9}


async def test_bom_versioning_keeps_history(auth_client):
    """FR-03b 变更留痕：新版本 +1，旧版转历史"""
    owner = await _make_owner(auth_client, "T_BOM_O9", "BOM测试货主9")
    shop = await _make_shop(auth_client, "测试BOM店铺8", owner["id"])
    bm1 = await _make_material(auth_client, "BM_V1", "版本物料甲", owner["id"])
    bm2 = await _make_material(auth_client, "BM_V2", "版本物料乙", owner["id"])
    sm = await _make_sm(auth_client, "SM_V", "版本变更单", shop["id"])

    r1 = await auth_client.post(f"/api/v1/material/sales-materials/{sm['id']}/bom", json={
        "items": [{"bm_id": bm1["id"], "bind_num": 1, "rate": 100}],
    })
    assert r1.status_code == 200, r1.text
    assert r1.json()["data"]["version_no"] == 1

    r2 = await auth_client.post(f"/api/v1/material/sales-materials/{sm['id']}/bom", json={
        "items": [{"bm_id": bm2["id"], "bind_num": 1, "rate": 100}],
    })
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["version_no"] == 2
    assert r2.json()["data"]["status"] == 2

    # 当前生效版本只有一个
    cur = (await auth_client.get(f"/api/v1/material/sales-materials/{sm['id']}/bom")).json()["data"]
    assert cur["version_no"] == 2

    # 历史可查（2 个版本，旧版 status=3）
    hist = (await auth_client.get(
        f"/api/v1/material/sales-materials/{sm['id']}/bom/history")).json()["data"]
    assert len(hist) == 2
    statuses = {h["version_no"]: h["status"] for h in hist}
    assert statuses[1] == 3
    assert statuses[2] == 2


async def test_bom_unbind(auth_client):
    """解绑 → bind_status=0 + owner_id 清零"""
    owner = await _make_owner(auth_client, "T_BOM_O10", "BOM测试货主10")
    shop = await _make_shop(auth_client, "测试BOM店铺9", owner["id"])
    bm = await _make_material(auth_client, "BM_U1", "解绑物料", owner["id"])
    sm = await _make_sm(auth_client, "SM_U", "待解绑单", shop["id"])

    await auth_client.post(f"/api/v1/material/sales-materials/{sm['id']}/bom", json={
        "items": [{"bm_id": bm["id"], "bind_num": 1, "rate": 100}],
    })
    d = await auth_client.delete(f"/api/v1/material/sales-materials/{sm['id']}/bom")
    assert d.status_code == 200, d.text

    sm2 = (await auth_client.get("/api/v1/material/sales-materials", params={
        "keyword": "SM_U"})).json()["data"][0]
    assert sm2["bind_status"] == 0
    assert sm2["owner_id"] == 0


async def test_bom_reject_nested_combo(auth_client):
    """§5.2 嵌套约束：组合装成员不得再作为另一组合装成员"""
    owner = await _make_owner(auth_client, "T_BOM_O11", "BOM测试货主11")
    shop = await _make_shop(auth_client, "测试BOM店铺10", owner["id"])
    bm_a = await _make_material(auth_client, "BM_N1", "组合成员甲", owner["id"])
    bm_b = await _make_material(auth_client, "BM_N2", "组合成员乙", owner["id"])
    bm_c = await _make_material(auth_client, "BM_N3", "组合成员丙", owner["id"])

    # 第一个组合装：甲×2 + 乙×1 → 组合装
    sm1 = await _make_sm(auth_client, "SM_N1", "组合装一", shop["id"])
    r1 = await auth_client.post(f"/api/v1/material/sales-materials/{sm1['id']}/bom", json={
        "items": [
            {"bm_id": bm_a["id"], "bind_num": 2, "rate": 50},
            {"bm_id": bm_b["id"], "bind_num": 1, "rate": 50},
        ],
    })
    assert r1.status_code == 200, r1.text

    # 第二个组合装试图复用甲 → 拒绝
    sm2 = await _make_sm(auth_client, "SM_N2", "组合装二", shop["id"])
    r2 = await auth_client.post(f"/api/v1/material/sales-materials/{sm2['id']}/bom", json={
        "items": [
            {"bm_id": bm_a["id"], "bind_num": 1, "rate": 50},
            {"bm_id": bm_c["id"], "bind_num": 1, "rate": 50},
        ],
    })
    assert r2.status_code == 422
    assert "嵌套约束" in r2.json()["message"]


async def test_bom_combo_type_autoupdate(auth_client):
    """组合装判定后销售物料类型自动改写为「组合」"""
    owner = await _make_owner(auth_client, "T_BOM_O12", "BOM测试货主12")
    shop = await _make_shop(auth_client, "测试BOM店铺11", owner["id"])
    bm = await _make_material(auth_client, "BM_C1", "礼盒物料", owner["id"], mtype=4)
    sm = await _make_sm(auth_client, "SM_C", "礼盒组合单", shop["id"])

    r = await auth_client.post(f"/api/v1/material/sales-materials/{sm['id']}/bom", json={
        "items": [{"bm_id": bm["id"], "bind_num": 1, "rate": 100}],
    })
    assert r.status_code == 200, r.text
    sm2 = (await auth_client.get("/api/v1/material/sales-materials", params={
        "keyword": "SM_C"})).json()["data"][0]
    assert sm2["sales_material_type"] == 2  # 组合


async def test_bom_candidates_suggestion(auth_client):
    """FR-03d 自动绑定建议"""
    owner = await _make_owner(auth_client, "T_BOM_O13", "BOM测试货主13")
    shop = await _make_shop(auth_client, "测试BOM店铺12", owner["id"])
    await _make_material(auth_client, "BM_S1", "保温杯", owner["id"])
    sm = await _make_sm(auth_client, "SM_S", "保温杯 红色 M", shop["id"])
    # 补规格文本
    await auth_client.put(f"/api/v1/material/sales-materials/{sm['id']}", json={
        "spec_text": "红色 M", "version": sm["version"],
    })

    r = await auth_client.get(f"/api/v1/material/sales-materials/{sm['id']}/bom/candidates")
    assert r.status_code == 200, r.text
    cands = r.json()["data"]
    assert any(c["material_bn"] == "BM_S1" for c in cands)
    assert cands[0]["score"] > 0
