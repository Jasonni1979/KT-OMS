"""预占/释放/转扣减测试（M1b-4，SRS-D04.03）

覆盖：预占成功与台账/口径同步、预占幂等、可用不足拦截、Saga 补偿回滚、
释放与幂等释放、转扣减与部分核销、释放/核销互斥、过期回收、台账多维查询、账龄分析。
"""
import pytest
from sqlalchemy import text

from app.core.db import engine

pytestmark = pytest.mark.asyncio

CLEANUP_SQL = [
    "DELETE FROM oms_stock.inv_freeze_log WHERE obj_bn LIKE 'FRZ\\_%'",
    "DELETE FROM oms_stock.inv_stock_change_log WHERE bm_id IN "
    "(SELECT id FROM oms_stock.inv_material WHERE material_bn LIKE 'FRZ\\_M\\_%')",
    "DELETE FROM oms_stock.inv_stock_ledger WHERE bm_id IN "
    "(SELECT id FROM oms_stock.inv_material WHERE material_bn LIKE 'FRZ\\_M\\_%')",
    "DELETE FROM oms_stock.inv_material WHERE material_bn LIKE 'FRZ\\_M\\_%'",
    "DELETE FROM oms_fulfill.ful_branch WHERE branch_name LIKE '预占%'",
    "DELETE FROM oms_org.org_node WHERE org_code LIKE 'WH\\_%'",
    "DELETE FROM oms_org.org_owner WHERE owner_code LIKE 'FRZ\\_O\\_%'",
]


async def _cleanup_redis() -> None:
    """清理测试涉及的 Redis 键：预占标记 inv:freeze:* 与三元键 inv:{b}:{bm}:{o}

    必须同时清理：DB 台账被清但 Redis 标记残留时，下一轮预占会命中
    FREEZE_MARKER_CONFLICT（标记在、台账无）——测试隔离的必修项。
    """
    from app.services.master import get_redis

    r = await get_redis()
    keys: list = []
    async for k in r.scan_iter(match="inv:freeze:*"):
        keys.append(k)
    async for k in r.scan_iter(match="inv:*"):
        parts = k.decode() if isinstance(k, bytes) else k
        if parts.count(":") == 3:  # 三元键 inv:{branch}:{bm}:{owner}
            keys.append(k)
    if keys:
        await r.delete(*keys)


async def _cleanup() -> None:
    async with engine.begin() as conn:
        for sql in CLEANUP_SQL:
            await conn.execute(text(sql))
    await _cleanup_redis()


@pytest.fixture(autouse=True, scope="module")
async def isolate_freeze_data():
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
        "owner_code": code, "owner_name": f"预占货主{code}", "owner_type": "KC_BUYOUT",
        "org_node_id": await _owner_co_node_id(),
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _make_branch(auth_client, name: str, owner_id: int) -> dict:
    r = await auth_client.post("/api/v1/master/branches", json={
        "branch_name": name, "owner_id": None, "is_ctrl": 1, "countable_flag": 1,
    })
    assert r.status_code == 200, r.text
    branch = r.json()["data"]
    await auth_client.post(f"/api/v1/master/branches/{branch['id']}/owners", json={
        "owner_ids": [owner_id],
    })
    return branch


async def _make_material(auth_client, bn: str, owner_id: int) -> dict:
    r = await auth_client.post("/api/v1/material/materials", json={
        "material_bn": bn, "material_name": f"预占物料{bn}", "owner_id": owner_id,
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _stock_in(auth_client, branch_id: int, bm_id: int, owner_id: int, num: int) -> None:
    """先入库（走 M1b-3 记账）"""
    r = await auth_client.post("/api/v1/stock/ledger/change", json={
        "branch_id": branch_id, "bm_id": bm_id, "owner_id": owner_id,
        "changes": [{"field": "store", "delta": num}],
        "bill_type": "purchase_in", "bill_bn": f"FRZIN{branch_id}", "bill_item_id": 1,
        "action": "inbound",
    })
    assert r.status_code == 200, r.text


async def _clear_redis(branch_id: int, bm_id: int, owner_id: int, obj_bns: list[str]) -> None:
    from app.services.master import get_redis

    r = await get_redis()
    keys = [f"inv:{branch_id}:{bm_id}:{owner_id}"]
    for bn in obj_bns:
        keys.append(f"inv:freeze:1:{bn}:1")
    await r.delete(*keys)


async def _setup(auth_client, suffix: str, stock: int = 100):
    owner = await _make_owner(auth_client, f"FRZ_O_{suffix}")
    branch = await _make_branch(auth_client, f"预占测试仓{suffix}", owner["id"])
    mat = await _make_material(auth_client, f"FRZ_M_{suffix}", owner["id"])
    await _clear_redis(branch["id"], mat["id"], owner["id"], [])
    if stock:
        await _stock_in(auth_client, branch["id"], mat["id"], owner["id"], stock)
    return owner, branch, mat


# ============ 预占（FR-01）============

async def test_reserve_success(auth_client):
    """预占成功：台账 + freeze 口径 + 可用减少"""
    owner, branch, mat = await _setup(auth_client, "1", stock=100)
    bn = "FRZ_ORD_1"
    await _clear_redis(branch["id"], mat["id"], owner["id"], [bn])

    r = await auth_client.post("/api/v1/stock/freeze/reserve", json={
        "obj_type": 1, "obj_bn": bn,
        "items": [{
            "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
            "num": 30, "shop_id": 0, "obj_item_id": 1,
        }],
    })
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["reserved_num"] == 30
    assert d["available_after"] == 70
    assert len(d["logs"]) == 1
    assert d["logs"][0]["status"] == 1

    # 记账行 freeze=30
    bal = (await auth_client.get(
        f"/api/v1/stock/ledger/{branch['id']}/{mat['id']}/{owner['id']}"
    )).json()["data"]
    assert bal["store"] == 100
    assert bal["freeze"] == 30
    assert bal["available"] == 70


async def test_reserve_idempotent(auth_client):
    """幂等：同一 (对象,行,动作) 二次预占不重复占用"""
    owner, branch, mat = await _setup(auth_client, "2", stock=100)
    bn = "FRZ_ORD_2"
    await _clear_redis(branch["id"], mat["id"], owner["id"], [bn])
    payload = {
        "obj_type": 1, "obj_bn": bn,
        "items": [{
            "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
            "num": 20, "obj_item_id": 1,
        }],
    }
    r1 = await auth_client.post("/api/v1/stock/freeze/reserve", json=payload)
    assert r1.status_code == 200, r1.text
    r2 = await auth_client.post("/api/v1/stock/freeze/reserve", json=payload)
    assert r2.status_code == 200, r2.text

    bal = (await auth_client.get(
        f"/api/v1/stock/ledger/{branch['id']}/{mat['id']}/{owner['id']}"
    )).json()["data"]
    assert bal["freeze"] == 20  # 未重复占用


async def test_reserve_reject_insufficient(auth_client):
    """可用不足 → 409 INSUFFICIENT_STOCK"""
    owner, branch, mat = await _setup(auth_client, "3", stock=10)
    bn = "FRZ_ORD_3"
    await _clear_redis(branch["id"], mat["id"], owner["id"], [bn])

    r = await auth_client.post("/api/v1/stock/freeze/reserve", json={
        "obj_type": 1, "obj_bn": bn,
        "items": [{
            "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
            "num": 50, "obj_item_id": 1,
        }],
    })
    assert r.status_code == 409
    assert r.json()["code"] == "INSUFFICIENT_STOCK"


async def test_reserve_saga_compensation(auth_client):
    """FR-01b Saga 补偿：第二行失败 → 第一行反向释放并留痕"""
    owner, branch, mat = await _setup(auth_client, "4", stock=100)
    mat2 = await _make_material(auth_client, "FRZ_M_4B", owner["id"])
    bn = "FRZ_ORD_4"
    await _clear_redis(branch["id"], mat["id"], owner["id"], [bn])
    await _clear_redis(branch["id"], mat2["id"], owner["id"], [bn])

    r = await auth_client.post("/api/v1/stock/freeze/reserve", json={
        "obj_type": 1, "obj_bn": bn,
        "items": [
            {"branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
             "num": 10, "obj_item_id": 1},
            {"branch_id": branch["id"], "bm_id": mat2["id"], "owner_id": owner["id"],
             "num": 999, "obj_item_id": 2},
        ],
    })
    assert r.status_code == 409

    # 第一行已被反向释放（freeze 归零）
    bal = (await auth_client.get(
        f"/api/v1/stock/ledger/{branch['id']}/{mat['id']}/{owner['id']}"
    )).json()["data"]
    assert bal["freeze"] == 0
    assert bal["available"] == 100

    # 台账标记 is_compensated=1（补偿留痕）
    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT is_compensated, status FROM oms_stock.inv_freeze_log WHERE obj_bn=:bn"),
            {"bn": bn})).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 1


# ============ 释放（FR-02）============

async def test_release_restores_freeze(auth_client):
    """释放：freeze 恢复 + 台账状态=已释放"""
    owner, branch, mat = await _setup(auth_client, "5", stock=100)
    bn = "FRZ_ORD_5"
    await _clear_redis(branch["id"], mat["id"], owner["id"], [bn])

    await auth_client.post("/api/v1/stock/freeze/reserve", json={
        "obj_type": 1, "obj_bn": bn,
        "items": [{"branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
                   "num": 40, "obj_item_id": 1}],
    })
    r = await auth_client.post("/api/v1/stock/freeze/release", json={
        "obj_type": 1, "obj_bn": bn, "operator": "tester",
    })
    assert r.status_code == 200, r.text
    assert r.json()["data"]["reserved_num"] == 40

    bal = (await auth_client.get(
        f"/api/v1/stock/ledger/{branch['id']}/{mat['id']}/{owner['id']}"
    )).json()["data"]
    assert bal["freeze"] == 0
    assert bal["available"] == 100

    logs = (await auth_client.get("/api/v1/stock/freeze/logs", params={"obj_bn": bn})).json()["data"]
    assert logs[0]["status"] == 4  # 已释放


async def test_release_is_idempotent(auth_client):
    """FR-02c 重复释放幂等"""
    owner, branch, mat = await _setup(auth_client, "6", stock=100)
    bn = "FRZ_ORD_6"
    await _clear_redis(branch["id"], mat["id"], owner["id"], [bn])

    await auth_client.post("/api/v1/stock/freeze/reserve", json={
        "obj_type": 1, "obj_bn": bn,
        "items": [{"branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
                   "num": 15, "obj_item_id": 1}],
    })
    payload = {"obj_type": 1, "obj_bn": bn, "operator": "tester"}
    r1 = await auth_client.post("/api/v1/stock/freeze/release", json=payload)
    assert r1.status_code == 200
    r2 = await auth_client.post("/api/v1/stock/freeze/release", json=payload)
    assert r2.status_code == 200, r2.text

    bal = (await auth_client.get(
        f"/api/v1/stock/ledger/{branch['id']}/{mat['id']}/{owner['id']}"
    )).json()["data"]
    assert bal["freeze"] == 0  # 未重复扣减


# ============ 转扣减（FR-03）============

async def test_settle_deducts_store_and_freeze(auth_client):
    """FR-03a 转扣减：freeze-N & store-N 原子"""
    owner, branch, mat = await _setup(auth_client, "7", stock=100)
    bn = "FRZ_ORD_7"
    await _clear_redis(branch["id"], mat["id"], owner["id"], [bn])

    await auth_client.post("/api/v1/stock/freeze/reserve", json={
        "obj_type": 1, "obj_bn": bn,
        "items": [{"branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
                   "num": 25, "obj_item_id": 1}],
    })
    r = await auth_client.post("/api/v1/stock/freeze/settle", json={
        "obj_type": 1, "obj_bn": bn, "obj_item_id": 1, "num": 25,
        "bill_type": "sale_out", "bill_bn": "SH001", "bill_item_id": 1,
    })
    assert r.status_code == 200, r.text

    bal = (await auth_client.get(
        f"/api/v1/stock/ledger/{branch['id']}/{mat['id']}/{owner['id']}"
    )).json()["data"]
    assert bal["store"] == 75
    assert bal["freeze"] == 0
    assert bal["available"] == 75

    logs = (await auth_client.get("/api/v1/stock/freeze/logs", params={"obj_bn": bn})).json()["data"]
    assert logs[0]["status"] == 3  # 已核销
    assert logs[0]["settled_num"] == 25


async def test_settle_partial(auth_client):
    """FR-03b 部分核销（多包裹）"""
    owner, branch, mat = await _setup(auth_client, "8", stock=100)
    bn = "FRZ_ORD_8"
    await _clear_redis(branch["id"], mat["id"], owner["id"], [bn])

    await auth_client.post("/api/v1/stock/freeze/reserve", json={
        "obj_type": 1, "obj_bn": bn,
        "items": [{"branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
                   "num": 50, "obj_item_id": 1}],
    })
    await auth_client.post("/api/v1/stock/freeze/settle", json={
        "obj_type": 1, "obj_bn": bn, "obj_item_id": 1, "num": 20,
        "bill_type": "sale_out", "bill_bn": "SH002a", "bill_item_id": 1,
    })
    logs = (await auth_client.get("/api/v1/stock/freeze/logs", params={"obj_bn": bn})).json()["data"]
    assert logs[0]["status"] == 2  # 部分核销
    assert logs[0]["settled_num"] == 20

    bal = (await auth_client.get(
        f"/api/v1/stock/ledger/{branch['id']}/{mat['id']}/{owner['id']}"
    )).json()["data"]
    assert bal["store"] == 80
    assert bal["freeze"] == 30


async def test_release_and_settle_are_exclusive(auth_client):
    """§5.2 释放/核销互斥：已释放不可再核销"""
    owner, branch, mat = await _setup(auth_client, "9", stock=100)
    bn = "FRZ_ORD_9"
    await _clear_redis(branch["id"], mat["id"], owner["id"], [bn])

    await auth_client.post("/api/v1/stock/freeze/reserve", json={
        "obj_type": 1, "obj_bn": bn,
        "items": [{"branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
                   "num": 10, "obj_item_id": 1}],
    })
    await auth_client.post("/api/v1/stock/freeze/release", json={
        "obj_type": 1, "obj_bn": bn, "operator": "tester",
    })
    r = await auth_client.post("/api/v1/stock/freeze/settle", json={
        "obj_type": 1, "obj_bn": bn, "obj_item_id": 1, "num": 10,
    })
    assert r.status_code in (404, 409)


# ============ 过期回收（FR-02b）与台账查询（FR-04）============

async def test_expire_reclaim(auth_client):
    """FR-02b 过期回收：超期未核销预占自动释放"""
    owner, branch, mat = await _setup(auth_client, "10", stock=100)
    bn = "FRZ_ORD_10"
    await _clear_redis(branch["id"], mat["id"], owner["id"], [bn])

    await auth_client.post("/api/v1/stock/freeze/reserve", json={
        "obj_type": 1, "obj_bn": bn,
        "items": [{"branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
                   "num": 5, "obj_item_id": 1}],
        "ttl_hours": 1,
    })
    # 人为把过期时间改到过去
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE oms_stock.inv_freeze_log SET expire_time = DATE_SUB(NOW(3), INTERVAL 1 HOUR) "
            "WHERE obj_bn=:bn"), {"bn": bn})

    r = await auth_client.post("/api/v1/stock/freeze/expire-reclaim")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["reclaimed"] >= 1

    bal = (await auth_client.get(
        f"/api/v1/stock/ledger/{branch['id']}/{mat['id']}/{owner['id']}"
    )).json()["data"]
    assert bal["freeze"] == 0


async def test_freeze_logs_query_and_age(auth_client):
    """FR-04a 台账多维查询 + 账龄分析"""
    owner, branch, mat = await _setup(auth_client, "11", stock=100)
    bn = "FRZ_ORD_11"
    await _clear_redis(branch["id"], mat["id"], owner["id"], [bn])

    await auth_client.post("/api/v1/stock/freeze/reserve", json={
        "obj_type": 1, "obj_bn": bn,
        "items": [{"branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
                   "num": 7, "obj_item_id": 1}],
    })
    logs = (await auth_client.get("/api/v1/stock/freeze/logs", params={
        "obj_bn": bn, "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
        "status": 1,
    })).json()["data"]
    assert len(logs) == 1
    assert logs[0]["num"] == 7

    age = (await auth_client.get("/api/v1/stock/freeze/age")).json()["data"]
    assert age["total"] >= 1
