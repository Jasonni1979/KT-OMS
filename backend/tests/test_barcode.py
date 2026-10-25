"""条码测试（M1b-1c，SRS-D04.01 FR-04：条码全局唯一 + 一品多码 + 反查服务）"""
import pytest
from sqlalchemy import text

from app.core.db import engine

pytestmark = pytest.mark.asyncio

CLEANUP_SQL = [
    "DELETE FROM oms_stock.inv_barcode WHERE barcode LIKE 'BC\\_%'",
    "DELETE FROM oms_stock.inv_material WHERE material_bn LIKE 'BC\\_M\\_%'",
    "DELETE FROM oms_org.org_owner WHERE owner_code LIKE 'T\\_BC\\_%'",
]


async def _cleanup() -> None:
    async with engine.begin() as conn:
        for sql in CLEANUP_SQL:
            await conn.execute(text(sql))


@pytest.fixture(autouse=True, scope="module")
async def isolate_barcode_data():
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


async def _make_owner(auth_client, code: str) -> dict:
    r = await auth_client.post("/api/v1/master/owners", json={
        "owner_code": code, "owner_name": f"条码货主{code}", "owner_type": "KC_BUYOUT",
        "org_node_id": await _owner_co_node_id(),
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _make_material(auth_client, bn: str, name: str, owner_id: int) -> dict:
    r = await auth_client.post("/api/v1/material/materials", json={
        "material_bn": bn, "material_name": name, "owner_id": owner_id,
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def test_barcode_create_and_global_unique(auth_client):
    """FR-04a 条码全局唯一；冲突时提示归属物料"""
    owner = await _make_owner(auth_client, "T_BC_1")
    bm = await _make_material(auth_client, "BC_M_1", "条码物料甲", owner["id"])

    r = await auth_client.post("/api/v1/material/barcodes", json={
        "barcode": "BC_6901234567890", "bm_id": bm["id"], "barcode_type": 1,
    })
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["barcode"] == "BC_6901234567890"
    assert data["material_bn"] == "BC_M_1"
    assert data["owner_id"] == owner["id"]

    # 同一条码再登记 → 409 且提示归属物料
    bm2 = await _make_material(auth_client, "BC_M_2", "条码物料乙", owner["id"])
    r2 = await auth_client.post("/api/v1/material/barcodes", json={
        "barcode": "BC_6901234567890", "bm_id": bm2["id"], "barcode_type": 1,
    })
    assert r2.status_code == 409
    body = r2.json()
    assert "归属物料" in body["message"]
    assert body["data"]["material_bn"] == "BC_M_1"


async def test_one_material_multi_barcodes(auth_client):
    """一品多码：同一基础物料可登记多个条码"""
    owner = await _make_owner(auth_client, "T_BC_2")
    bm = await _make_material(auth_client, "BC_M_3", "多码物料", owner["id"])
    for code in ("BC_111", "BC_222", "BC_333"):
        r = await auth_client.post("/api/v1/material/barcodes", json={
            "barcode": code, "bm_id": bm["id"], "barcode_type": 1,
        })
        assert r.status_code == 200, r.text

    lst = (await auth_client.get("/api/v1/material/barcodes", params={
        "bm_id": bm["id"]})).json()["data"]
    assert len(lst) == 3
    assert {x["barcode"] for x in lst} == {"BC_111", "BC_222", "BC_333"}


async def test_shop_barcode_requires_shop(auth_client):
    """店铺码必须关联店铺"""
    owner = await _make_owner(auth_client, "T_BC_3")
    bm = await _make_material(auth_client, "BC_M_4", "店铺码物料", owner["id"])
    r = await auth_client.post("/api/v1/material/barcodes", json={
        "barcode": "BC_SHOP_1", "bm_id": bm["id"], "barcode_type": 2,
    })
    assert r.status_code == 422
    assert "店铺" in r.json()["message"]


async def test_barcode_lookup(auth_client):
    """FR-04b 条码反查（WMS 回传/门店扫码/售后核销）"""
    owner = await _make_owner(auth_client, "T_BC_4")
    bm = await _make_material(auth_client, "BC_M_5", "反查物料", owner["id"])
    await auth_client.post("/api/v1/material/barcodes", json={
        "barcode": "BC_LOOKUP", "bm_id": bm["id"], "barcode_type": 3,
    })

    r = await auth_client.get("/api/v1/material/barcodes/lookup", params={"barcode": "BC_LOOKUP"})
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["bm_id"] == bm["id"]
    assert d["material_bn"] == "BC_M_5"
    assert d["owner_id"] == owner["id"]

    # 未登记条码 → 404
    r2 = await auth_client.get("/api/v1/material/barcodes/lookup", params={"barcode": "BC_NONE"})
    assert r2.status_code == 404


async def test_barcode_disable_and_optimistic_lock(auth_client):
    """停用条码 + 乐观锁冲突"""
    owner = await _make_owner(auth_client, "T_BC_5")
    bm = await _make_material(auth_client, "BC_M_6", "停用条码物料", owner["id"])
    bc = (await auth_client.post("/api/v1/material/barcodes", json={
        "barcode": "BC_STOP", "bm_id": bm["id"], "barcode_type": 1,
    })).json()["data"]

    # 旧版本 → 409
    bad = await auth_client.put(f"/api/v1/material/barcodes/{bc['id']}", json={
        "status": 2, "version": bc["version"] - 1,
    })
    assert bad.status_code == 409

    # 正确版本 → 停用成功
    good = await auth_client.put(f"/api/v1/material/barcodes/{bc['id']}", json={
        "status": 2, "version": bc["version"],
    })
    assert good.status_code == 200, good.text
    assert good.json()["data"]["status"] == 2


async def test_barcode_material_must_exist(auth_client):
    """基础物料不存在 → 拒绝"""
    await _make_owner(auth_client, "T_BC_6")
    r = await auth_client.post("/api/v1/material/barcodes", json={
        "barcode": "BC_NOMAT", "bm_id": 99999999, "barcode_type": 1,
    })
    assert r.status_code == 422
