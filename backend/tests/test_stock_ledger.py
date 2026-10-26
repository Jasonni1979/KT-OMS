"""三元记账 + 五口径测试（M1b-3，SRS-D04.02 FR-01/02/03/04/05/06）

覆盖：自动开行/口径记账与流水/幂等/负库存拦截/负卖开关/可用公式（锁定安全库存开关）/
多口径一次记账/Redis 同步/人工调整/对账差异自动修复/连续差异升级人工/快照/缓存重建/多维查询。
"""
import pytest
from sqlalchemy import text

from app.core.db import engine

pytestmark = pytest.mark.asyncio

CLEANUP_SQL = [
    "DELETE FROM oms_stock.inv_stock_recon_diff WHERE branch_id IN "
    "(SELECT id FROM oms_fulfill.ful_branch WHERE branch_name LIKE '记账%')",
    "DELETE FROM oms_stock.inv_stock_change_log WHERE bm_id IN "
    "(SELECT id FROM oms_stock.inv_material WHERE material_bn LIKE 'LED\\_%')",
    "DELETE FROM oms_stock.inv_stock_snapshot WHERE bm_id IN "
    "(SELECT id FROM oms_stock.inv_material WHERE material_bn LIKE 'LED\\_%')",
    "DELETE FROM oms_stock.inv_stock_ledger WHERE bm_id IN "
    "(SELECT id FROM oms_stock.inv_material WHERE material_bn LIKE 'LED\\_%')",
    "DELETE FROM oms_stock.inv_stock_config WHERE scope_ref LIKE '%记账%' OR scope_ref LIKE '%LED%'",
    "DELETE FROM oms_stock.inv_material WHERE material_bn LIKE 'LED\\_%'",
    "DELETE FROM oms_fulfill.ful_branch WHERE branch_name LIKE '记账%'",
    "DELETE FROM oms_org.org_node WHERE org_code LIKE 'WH\\_%'",
    "DELETE FROM oms_org.org_owner WHERE owner_code LIKE 'LED\\_%'",
]


async def _cleanup() -> None:
    async with engine.begin() as conn:
        for sql in CLEANUP_SQL:
            await conn.execute(text(sql))


@pytest.fixture(autouse=True, scope="module")
async def isolate_ledger_data():
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
        "owner_code": code, "owner_name": f"记账货主{code}", "owner_type": "KC_BUYOUT",
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
        "material_bn": bn, "material_name": f"记账物料{bn}", "owner_id": owner_id,
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _redis_key(branch_id: int, bm_id: int, owner_id: int) -> str:
    return f"inv:{branch_id}:{bm_id}:{owner_id}"


async def _clear_redis(keys: list[str]) -> None:
    from app.modules.m1_master.service.master import get_redis

    r = await get_redis()
    for k in keys:
        await r.delete(k)


# ============ 记账核心（FR-01/FR-02/FR-03）============

async def test_change_auto_opens_ledger_row(auth_client):
    """FR-01a 自动开立记账行 + FR-03a 流水一条"""
    owner = await _make_owner(auth_client, "LED_OWNER_1")
    branch = await _make_branch(auth_client, "记账测试仓1", owner["id"])
    mat = await _make_material(auth_client, "LED_M_1", owner["id"])
    key = await _redis_key(branch["id"], mat["id"], owner["id"])
    await _clear_redis([key])

    r = await auth_client.post("/api/v1/stock/ledger/change", json={
        "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
        "changes": [{"field": "store", "delta": 100}],
        "bill_type": "purchase_in", "bill_bn": "B001", "bill_item_id": 1,
        "action": "inbound", "operator": "tester",
    })
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["idempotent"] is False
    assert d["balances"]["store"] == 100
    assert len(d["change_log_ids"]) == 1

    # 余额可查
    bal = (await auth_client.get(
        f"/api/v1/stock/ledger/{branch['id']}/{mat['id']}/{owner['id']}"
    )).json()["data"]
    assert bal["store"] == 100
    assert bal["available"] == 100

    # 流水落库（before/after 快照）
    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT change_field, change_num, before_balance, after_balance, bill_type, action "
            "FROM oms_stock.inv_stock_change_log WHERE bm_id=:m"),
            {"m": mat["id"]})).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "store"
        assert rows[0][1] == 100
        assert rows[0][2] == 0
        assert rows[0][3] == 100
        assert rows[0][4] == "purchase_in"
        assert rows[0][5] == "inbound"


async def test_change_is_idempotent(auth_client):
    """FR-03d 幂等：同一幂等键不重复记账"""
    owner = await _make_owner(auth_client, "LED_OWNER_2")
    branch = await _make_branch(auth_client, "记账测试仓2", owner["id"])
    mat = await _make_material(auth_client, "LED_M_2", owner["id"])
    await _clear_redis([await _redis_key(branch["id"], mat["id"], owner["id"])])

    payload = {
        "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
        "changes": [{"field": "store", "delta": 50}],
        "bill_type": "purchase_in", "bill_bn": "B002", "bill_item_id": 1,
        "action": "inbound", "operator": "tester",
    }
    r1 = await auth_client.post("/api/v1/stock/ledger/change", json=payload)
    assert r1.status_code == 200
    r2 = await auth_client.post("/api/v1/stock/ledger/change", json=payload)
    assert r2.status_code == 200
    d2 = r2.json()["data"]
    assert d2["idempotent"] is True
    assert d2["balances"]["store"] == 50  # 未重复累加


async def test_change_reject_negative_stock(auth_client):
    """FR-02c 负库存默认禁止"""
    owner = await _make_owner(auth_client, "LED_OWNER_3")
    branch = await _make_branch(auth_client, "记账测试仓3", owner["id"])
    mat = await _make_material(auth_client, "LED_M_3", owner["id"])
    await _clear_redis([await _redis_key(branch["id"], mat["id"], owner["id"])])

    r = await auth_client.post("/api/v1/stock/ledger/change", json={
        "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
        "changes": [{"field": "store", "delta": -10}],
        "bill_type": "sale_out", "bill_bn": "B003", "bill_item_id": 1,
        "action": "outbound",
    })
    assert r.status_code == 422
    assert "余额不足" in r.json()["message"]


async def test_available_formula_with_locked_safe_stock(auth_client):
    """§5.1 可用公式：store − freeze − defective − (is_locked ? safe_store : 0)"""
    owner = await _make_owner(auth_client, "LED_OWNER_4")
    branch = await _make_branch(auth_client, "记账测试仓4", owner["id"])
    mat = await _make_material(auth_client, "LED_M_4", owner["id"])
    await _clear_redis([await _redis_key(branch["id"], mat["id"], owner["id"])])

    # 入库 100
    r = await auth_client.post("/api/v1/stock/ledger/change", json={
        "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
        "changes": [{"field": "store", "delta": 100}],
        "bill_type": "purchase_in", "bill_bn": "B004", "bill_item_id": 1, "action": "inbound",
    })
    assert r.status_code == 200, r.text
    # 锁定 20 + 次品 5
    r2 = await auth_client.post("/api/v1/stock/ledger/change", json={
        "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
        "changes": [{"field": "freeze", "delta": 20}, {"field": "defective", "delta": 5}],
        "bill_type": "reserve", "bill_bn": "B005", "bill_item_id": 1, "action": "reserve",
    })
    assert r2.status_code == 200, r2.text
    d = r2.json()["data"]
    # available = 100 - 20 - 5 - 0 = 75
    assert d["available"] == 75
    assert len(d["change_log_ids"]) == 2  # 多口径 → 多条流水


async def test_redis_synced_after_change(auth_client):
    """Redis 缓存与 DB 同步（记账后立即可读）"""
    owner = await _make_owner(auth_client, "LED_OWNER_5")
    branch = await _make_branch(auth_client, "记账测试仓5", owner["id"])
    mat = await _make_material(auth_client, "LED_M_5", owner["id"])
    key = await _redis_key(branch["id"], mat["id"], owner["id"])
    await _clear_redis([key])

    await auth_client.post("/api/v1/stock/ledger/change", json={
        "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
        "changes": [{"field": "store", "delta": 77}],
        "bill_type": "purchase_in", "bill_bn": "B006", "bill_item_id": 1, "action": "inbound",
    })
    from app.modules.m1_master.service.master import get_redis

    r = await get_redis()
    raw = await r.hgetall(key)
    assert int(raw.get("store") or raw.get(b"store") or 0) == 77


# ============ 人工调整（FR-04）============

async def test_manual_adjust(auth_client):
    """FR-04c 人工调整：生效即记账 + 流水"""
    owner = await _make_owner(auth_client, "LED_OWNER_6")
    branch = await _make_branch(auth_client, "记账测试仓6", owner["id"])
    mat = await _make_material(auth_client, "LED_M_6", owner["id"])
    await _clear_redis([await _redis_key(branch["id"], mat["id"], owner["id"])])

    r = await auth_client.post("/api/v1/stock/ledger/adjust", json={
        "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
        "field": "store", "adjust_num": 15, "adjust_type": "盘盈",
        "reason": "盘点差异", "operator": "tester",
    })
    assert r.status_code == 200, r.text
    assert r.json()["data"]["balances"]["store"] == 15

    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT bill_type, action, source FROM oms_stock.inv_stock_change_log "
            "WHERE bm_id=:m"), {"m": mat["id"]})).fetchall()
        assert rows[0][0] == "adjust"
        assert rows[0][1] == "adjust"
        assert rows[0][2] == "manual"


async def test_manual_adjust_requires_reason(auth_client):
    """FR-04b 原因必填"""
    owner = await _make_owner(auth_client, "LED_OWNER_7")
    branch = await _make_branch(auth_client, "记账测试仓7", owner["id"])
    mat = await _make_material(auth_client, "LED_M_7", owner["id"])
    r = await auth_client.post("/api/v1/stock/ledger/adjust", json={
        "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
        "field": "store", "adjust_num": 5, "adjust_type": "盘盈", "reason": "",
    })
    assert r.status_code == 422


# ============ 对账（FR-05/FR-06）============

async def test_recon_detects_and_fixes_difference(auth_client):
    """FR-05c Redis vs DB 对账：发现差异 → 落差异表 → 自动修复"""
    owner = await _make_owner(auth_client, "LED_OWNER_8")
    branch = await _make_branch(auth_client, "记账测试仓8", owner["id"])
    mat = await _make_material(auth_client, "LED_M_8", owner["id"])
    key = await _redis_key(branch["id"], mat["id"], owner["id"])
    await _clear_redis([key])

    await auth_client.post("/api/v1/stock/ledger/change", json={
        "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
        "changes": [{"field": "store", "delta": 60}],
        "bill_type": "purchase_in", "bill_bn": "B007", "bill_item_id": 1, "action": "inbound",
    })
    # 人为破坏 Redis
    from app.modules.m1_master.service.master import get_redis

    r = await get_redis()
    await r.hset(key, "store", 999)

    run = await auth_client.post("/api/v1/stock/recon/run")
    assert run.status_code == 200, run.text
    report = run.json()["data"]
    assert report["diff_count"] >= 1
    assert report["fixed"] >= 1

    # Redis 已被修复回 DB 值
    raw = await r.hgetall(key)
    assert int(raw.get("store") or raw.get(b"store") or 0) == 60

    # 差异落表
    diffs = (await auth_client.get("/api/v1/stock/recon/diffs")).json()["data"]
    assert any(d["branch_id"] == branch["id"] and d["diff_num"] == 999 - 60 for d in diffs)


async def test_snapshot_generation(auth_client):
    """FR-06a 日终快照"""
    owner = await _make_owner(auth_client, "LED_OWNER_9")
    branch = await _make_branch(auth_client, "记账测试仓9", owner["id"])
    mat = await _make_material(auth_client, "LED_M_9", owner["id"])
    await _clear_redis([await _redis_key(branch["id"], mat["id"], owner["id"])])

    await auth_client.post("/api/v1/stock/ledger/change", json={
        "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
        "changes": [{"field": "store", "delta": 42}],
        "bill_type": "purchase_in", "bill_bn": "B008", "bill_item_id": 1, "action": "inbound",
    })
    r = await auth_client.post("/api/v1/stock/snapshot")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["created"] >= 1

    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT store, available_num FROM oms_stock.inv_stock_snapshot WHERE bm_id=:m"),
            {"m": mat["id"]})).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 42
        assert rows[0][1] == 42


async def test_cache_rebuild(auth_client):
    """FR-05d 缓存重建"""
    owner = await _make_owner(auth_client, "LED_OWNER_10")
    branch = await _make_branch(auth_client, "记账测试仓10", owner["id"])
    mat = await _make_material(auth_client, "LED_M_10", owner["id"])
    key = await _redis_key(branch["id"], mat["id"], owner["id"])
    await _clear_redis([key])

    await auth_client.post("/api/v1/stock/ledger/change", json={
        "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
        "changes": [{"field": "store", "delta": 33}],
        "bill_type": "purchase_in", "bill_bn": "B009", "bill_item_id": 1, "action": "inbound",
    })
    from app.modules.m1_master.service.master import get_redis

    r = await get_redis()
    await r.delete(key)
    rebuild = await auth_client.post("/api/v1/stock/recon/rebuild-cache")
    assert rebuild.status_code == 200, rebuild.text
    assert rebuild.json()["data"]["rebuilt"] >= 1
    raw = await r.hgetall(key)
    assert int(raw.get("store") or raw.get(b"store") or 0) == 33


async def test_ledger_query_multi_dimension(auth_client):
    """FR-01c 多维查询（仓/货主/物料关键字）"""
    owner = await _make_owner(auth_client, "LED_OWNER_11")
    branch = await _make_branch(auth_client, "记账测试仓11", owner["id"])
    mat = await _make_material(auth_client, "LED_M_11", owner["id"])
    await _clear_redis([await _redis_key(branch["id"], mat["id"], owner["id"])])

    await auth_client.post("/api/v1/stock/ledger/change", json={
        "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
        "changes": [{"field": "store", "delta": 8}],
        "bill_type": "purchase_in", "bill_bn": "B010", "bill_item_id": 1, "action": "inbound",
    })
    r = await auth_client.get("/api/v1/stock/ledger", params={
        "branch_id": branch["id"], "owner_id": owner["id"], "keyword": "LED_M_11",
    })
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    assert len(rows) == 1
    assert rows[0]["material_bn"] == "LED_M_11"
    assert rows[0]["available"] == 8


async def test_negative_stock_allowed_when_config_enabled(auth_client):
    """FR-02c 负卖开关：按「仓库×货主」开启后允许负库存"""
    owner = await _make_owner(auth_client, "LED_OWNER_12")
    branch = await _make_branch(auth_client, "记账测试仓12", owner["id"])
    mat = await _make_material(auth_client, "LED_M_12", owner["id"])
    await _clear_redis([await _redis_key(branch["id"], mat["id"], owner["id"])])

    # 未开开关 → 拒绝负库存
    r0 = await auth_client.post("/api/v1/stock/ledger/change", json={
        "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
        "changes": [{"field": "store", "delta": -5}],
        "bill_type": "sale_out", "bill_bn": "B011", "bill_item_id": 1, "action": "outbound",
    })
    assert r0.status_code == 422

    # 开启负卖（仓库×货主维度）
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO oms_stock.inv_stock_config "
            "(tenant_id, config_type, scope_type, scope_ref, config_json, status, create_time, update_time) "
            "VALUES (1, 1, 5, :ref, CAST(:cfg AS JSON), 1, NOW(3), NOW(3))"),
            {"ref": f"branch:{branch['id']}:owner:{owner['id']}",
             "cfg": '{"allow_negative": 1}'},
        )

    r1 = await auth_client.post("/api/v1/stock/ledger/change", json={
        "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
        "changes": [{"field": "store", "delta": -5}],
        "bill_type": "sale_out", "bill_bn": "B012", "bill_item_id": 1, "action": "outbound",
    })
    assert r1.status_code == 200, r1.text
    assert r1.json()["data"]["balances"]["store"] == -5  # 负余额被记录


async def test_locked_safe_stock_reduces_available(auth_client):
    """§5.1 锁定安全库存开关：开启时 safe_store 计入可用扣减"""
    owner = await _make_owner(auth_client, "LED_OWNER_13")
    branch = await _make_branch(auth_client, "记账测试仓13", owner["id"])
    mat = await _make_material(auth_client, "LED_M_13", owner["id"])
    await _clear_redis([await _redis_key(branch["id"], mat["id"], owner["id"])])

    await auth_client.post("/api/v1/stock/ledger/change", json={
        "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
        "changes": [{"field": "store", "delta": 100}],
        "bill_type": "purchase_in", "bill_bn": "B013", "bill_item_id": 1, "action": "inbound",
    })
    # 设置安全库存 20 并开启锁定开关
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE oms_stock.inv_stock_ledger SET safe_store=20, is_locked=1 "
            "WHERE branch_id=:b AND bm_id=:m AND owner_id=:o"),
            {"b": branch["id"], "m": mat["id"], "o": owner["id"]},
        )

    bal = (await auth_client.get(
        f"/api/v1/stock/ledger/{branch['id']}/{mat['id']}/{owner['id']}"
    )).json()["data"]
    assert bal["safe_store"] == 20
    assert bal["is_locked"] == 1
    assert bal["available"] == 80  # 100 - 0 - 0 - 20

    # 关闭锁定开关 → 安全库存不再扣减
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE oms_stock.inv_stock_ledger SET is_locked=0 "
            "WHERE branch_id=:b AND bm_id=:m AND owner_id=:o"),
            {"b": branch["id"], "m": mat["id"], "o": owner["id"]},
        )
    bal2 = (await auth_client.get(
        f"/api/v1/stock/ledger/{branch['id']}/{mat['id']}/{owner['id']}"
    )).json()["data"]
    assert bal2["available"] == 100
