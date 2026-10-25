"""出入库单据中心测试（M1b-5，SRS-D04.04 FR-01/02/03/04/05/06）

覆盖：类型目录与口径模板、创建草稿、确认即记账（入库类多口径）、仓执行类全流程
（草稿→下发→部分回传→全部回传→确认）、回传超量拒绝、§5.5 不可动用已预占量、
红冲反向记账、已结算禁止红冲、结算状态回写、追溯链。
"""
import pytest
from sqlalchemy import text

from app.core.db import engine

pytestmark = pytest.mark.asyncio

CLEANUP_SQL = [
    "DELETE FROM oms_stock.inv_io_bill_item WHERE bill_bn LIKE '%BILL%' OR bill_bn LIKE 'purchase_in%' "
    "OR bill_bn LIKE 'stocktake_%' OR bill_bn LIKE 'sale_out%'",
    "DELETE FROM oms_stock.inv_io_bill WHERE bill_bn LIKE '%BILL%' OR bill_bn LIKE 'purchase_in%' "
    "OR bill_bn LIKE 'stocktake_%' OR bill_bn LIKE 'sale_out%'",
    "DELETE FROM oms_stock.inv_freeze_log WHERE obj_bn LIKE 'BILL_%'",
    "DELETE FROM oms_stock.inv_stock_change_log WHERE bm_id IN "
    "(SELECT id FROM oms_stock.inv_material WHERE material_bn LIKE 'BL\\_M\\_%')",
    "DELETE FROM oms_stock.inv_stock_ledger WHERE bm_id IN "
    "(SELECT id FROM oms_stock.inv_material WHERE material_bn LIKE 'BL\\_M\\_%')",
    "DELETE FROM oms_stock.inv_material WHERE material_bn LIKE 'BL\\_M\\_%'",
    "DELETE FROM oms_fulfill.ful_branch WHERE branch_name LIKE '单据%'",
    "DELETE FROM oms_org.org_node WHERE org_code LIKE 'WH\\_%'",
    "DELETE FROM oms_org.org_owner WHERE owner_code LIKE 'BL\\_O\\_%'",
]


async def _cleanup_redis() -> None:
    from app.services.master import get_redis

    r = await get_redis()
    keys: list = []
    async for k in r.scan_iter(match="inv:freeze:*"):
        keys.append(k)
    async for k in r.scan_iter(match="inv:*"):
        parts = k.decode() if isinstance(k, bytes) else k
        if parts.count(":") == 3:
            keys.append(k)
    if keys:
        await r.delete(*keys)


async def _cleanup() -> None:
    async with engine.begin() as conn:
        for sql in CLEANUP_SQL:
            await conn.execute(text(sql))
    await _cleanup_redis()


@pytest.fixture(autouse=True, scope="module")
async def isolate_bill_data():
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
        "owner_code": code, "owner_name": f"单据货主{code}", "owner_type": "KC_BUYOUT",
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
        "material_bn": bn, "material_name": f"单据物料{bn}", "owner_id": owner_id,
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _setup(auth_client, suffix: str):
    owner = await _make_owner(auth_client, f"BL_O_{suffix}")
    branch = await _make_branch(auth_client, f"单据测试仓{suffix}", owner["id"])
    mat = await _make_material(auth_client, f"BL_M_{suffix}", owner["id"])
    return owner, branch, mat


# ============ 类型与创建（FR-01/FR-03）============

async def test_bill_types_with_effect_template(auth_client):
    """FR-01 类型目录带口径影响模板"""
    r = await auth_client.get("/api/v1/stock/bill/types")
    assert r.status_code == 200, r.text
    types = {t["type_code"]: t for t in r.json()["data"]}
    assert "stocktake_in" in types
    assert types["stocktake_in"]["effect_template"] == [{"sign": 1, "field": "store"}]
    assert types["sale_out"]["effect_template"] == [{"action": "settle"}]


async def test_create_bill_draft(auth_client):
    """FR-03 创建草稿：单号规则 {类型码}{YYYYMMDD}{6位序列}"""
    owner, branch, mat = await _setup(auth_client, "1")
    r = await auth_client.post("/api/v1/stock/bills", json={
        "bill_type": "stocktake_in", "branch_id": branch["id"], "owner_id": owner["id"],
        "source_bill_type": "stocktake", "source_bill_bn": "PD0001",
        "items": [{"bm_id": mat["id"], "issued_num": 10, "confirmed_num": 10, "unit_cost": 5.5}],
        "operator": "tester", "memo": "盘盈",
    })
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["status"] == 1  # 草稿
    assert d["bill_type"] == "stocktake_in"
    assert d["direction"] == 1
    assert d["bill_bn"].startswith("stocktake_in")
    assert len(d["items"]) == 1
    assert d["items"][0]["amount"] == 55.0


# ============ 确认即记账（FR-02b）============

async def test_confirm_local_bill_posts_ledger(auth_client):
    """本地记账类确认 → store +N + 流水"""
    owner, branch, mat = await _setup(auth_client, "2")
    bill = (await auth_client.post("/api/v1/stock/bills", json={
        "bill_type": "stocktake_in", "branch_id": branch["id"], "owner_id": owner["id"],
        "items": [{"bm_id": mat["id"], "issued_num": 12, "confirmed_num": 12}],
    })).json()["data"]

    r = await auth_client.post(f"/api/v1/stock/bills/{bill['id']}/confirm")
    assert r.status_code == 200, r.text
    assert r.json()["data"]["status"] == 5  # 已确认

    bal = (await auth_client.get(
        f"/api/v1/stock/ledger/{branch['id']}/{mat['id']}/{owner['id']}"
    )).json()["data"]
    assert bal["store"] == 12

    async with engine.begin() as conn:
        rows = (await conn.execute(text(
            "SELECT change_field, change_num, bill_bn, bill_item_id, action "
            "FROM oms_stock.inv_stock_change_log WHERE bill_bn=:bn"), {"bn": bill["bill_bn"]}
        )).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "store"
        assert rows[0][1] == 12
        assert rows[0][4] == "inbound"


async def test_confirm_purchase_in_affects_two_fields(auth_client):
    """采购入库模板：store+ 与 arrive- 两个口径同时生效"""
    owner, branch, mat = await _setup(auth_client, "3")
    # 先有在途 20
    await auth_client.post("/api/v1/stock/ledger/change", json={
        "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
        "changes": [{"field": "arrive_store", "delta": 20}],
        "bill_type": "purchase_order", "bill_bn": "PO1", "bill_item_id": 1, "action": "purchase",
    })
    bill = (await auth_client.post("/api/v1/stock/bills", json={
        "bill_type": "purchase_in", "branch_id": branch["id"], "owner_id": owner["id"],
        "source_bill_type": "purchase_order", "source_bill_bn": "PO1",
        "items": [{"bm_id": mat["id"], "issued_num": 20, "confirmed_num": 20}],
    })).json()["data"]

    r = await auth_client.post(f"/api/v1/stock/bills/{bill['id']}/confirm")
    assert r.status_code == 200, r.text

    bal = (await auth_client.get(
        f"/api/v1/stock/ledger/{branch['id']}/{mat['id']}/{owner['id']}"
    )).json()["data"]
    assert bal["store"] == 20
    assert bal["arrive_store"] == 0


# ============ 仓执行类流程（FR-02a/FR-02c）============

async def test_wms_flow_draft_push_callback_confirm(auth_client):
    """草稿→下发→部分回传→全部回传→确认"""
    owner, branch, mat = await _setup(auth_client, "4")
    # 采购审核产生在途（采购入库确认时模板含「在途−」）
    await auth_client.post("/api/v1/stock/ledger/change", json={
        "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
        "changes": [{"field": "arrive_store", "delta": 50}],
        "bill_type": "purchase_order", "bill_bn": "PO4", "bill_item_id": 1, "action": "purchase",
    })
    bill = (await auth_client.post("/api/v1/stock/bills", json={
        "bill_type": "purchase_in", "branch_id": branch["id"], "owner_id": owner["id"],
        "items": [{"bm_id": mat["id"], "issued_num": 50}],
    })).json()["data"]

    r1 = await auth_client.post(f"/api/v1/stock/bills/{bill['id']}/push-wms")
    assert r1.status_code == 200, r1.text
    assert r1.json()["data"]["status"] == 2  # 已下发

    r2 = await auth_client.post(f"/api/v1/stock/bills/{bill['id']}/callback", json={
        "items": [{"bm_id": mat["id"], "confirmed_num": 20}],
    })
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["status"] == 3  # 部分回传

    r3 = await auth_client.post(f"/api/v1/stock/bills/{bill['id']}/callback", json={
        "items": [{"bm_id": mat["id"], "confirmed_num": 30}],
    })
    assert r3.json()["data"]["status"] == 4  # 全部回传

    r4 = await auth_client.post(f"/api/v1/stock/bills/{bill['id']}/confirm")
    assert r4.status_code == 200, r4.text
    assert r4.json()["data"]["status"] == 5  # 已确认

    bal = (await auth_client.get(
        f"/api/v1/stock/ledger/{branch['id']}/{mat['id']}/{owner['id']}"
    )).json()["data"]
    assert bal["store"] == 50


async def test_callback_reject_over_qty(auth_client):
    """FR-02c 回传累计超过下发数量 → 拒绝"""
    owner, branch, mat = await _setup(auth_client, "5")
    bill = (await auth_client.post("/api/v1/stock/bills", json={
        "bill_type": "purchase_in", "branch_id": branch["id"], "owner_id": owner["id"],
        "items": [{"bm_id": mat["id"], "issued_num": 10}],
    })).json()["data"]
    await auth_client.post(f"/api/v1/stock/bills/{bill['id']}/push-wms")
    r = await auth_client.post(f"/api/v1/stock/bills/{bill['id']}/callback", json={
        "items": [{"bm_id": mat["id"], "confirmed_num": 15}],
    })
    assert r.status_code == 422
    assert "超过下发" in r.json()["message"]


# ============ §5.5 约束 ============

async def test_outbound_cannot_use_frozen_stock(auth_client):
    """§5.5：出库扣减量不得超过（实际 − 锁定），不可动用已预占量"""
    owner, branch, mat = await _setup(auth_client, "6")
    # 入库 10 + 预占 8
    await auth_client.post("/api/v1/stock/ledger/change", json={
        "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
        "changes": [{"field": "store", "delta": 10}],
        "bill_type": "purchase_in", "bill_bn": "PO2", "bill_item_id": 1, "action": "inbound",
    })
    await auth_client.post("/api/v1/stock/freeze/reserve", json={
        "obj_type": 1, "obj_bn": "BILL_ORD_6",
        "items": [{"branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
                   "num": 8, "obj_item_id": 1}],
    })
    # 盘亏出库 5 → 超出可用(10−8=2)
    bill = (await auth_client.post("/api/v1/stock/bills", json={
        "bill_type": "stocktake_out", "branch_id": branch["id"], "owner_id": owner["id"],
        "items": [{"bm_id": mat["id"], "issued_num": 5, "confirmed_num": 5}],
    })).json()["data"]
    r = await auth_client.post(f"/api/v1/stock/bills/{bill['id']}/confirm")
    assert r.status_code == 422
    assert "不可动用已预占库存" in r.json()["message"]


# ============ 红冲（FR-04）============

async def test_red_flush_reverses_ledger(auth_client):
    """FR-04a/FR-04b 红冲：生成 R 单 + 反向记账 + 原单置已红冲"""
    owner, branch, mat = await _setup(auth_client, "7")
    bill = (await auth_client.post("/api/v1/stock/bills", json={
        "bill_type": "stocktake_in", "branch_id": branch["id"], "owner_id": owner["id"],
        "items": [{"bm_id": mat["id"], "issued_num": 20, "confirmed_num": 20}],
    })).json()["data"]
    await auth_client.post(f"/api/v1/stock/bills/{bill['id']}/confirm")

    bal_before = (await auth_client.get(
        f"/api/v1/stock/ledger/{branch['id']}/{mat['id']}/{owner['id']}"
    )).json()["data"]
    assert bal_before["store"] == 20

    r = await auth_client.post(f"/api/v1/stock/bills/{bill['id']}/red-flush", json={
        "reason": "录入错误", "operator": "tester",
    })
    assert r.status_code == 200, r.text
    red = r.json()["data"]
    assert red["bill_bn"] == f"{bill['bill_bn']}R"
    assert red["red_flush_of"] == bill["bill_bn"]
    assert red["status"] == 5

    bal_after = (await auth_client.get(
        f"/api/v1/stock/ledger/{branch['id']}/{mat['id']}/{owner['id']}"
    )).json()["data"]
    assert bal_after["store"] == 0  # 反向记账

    # 原单标记为已红冲
    orig = (await auth_client.get(f"/api/v1/stock/bills/{bill['id']}")).json()["data"]
    assert orig["status"] == 6


async def test_red_flush_reject_settled_bill(auth_client):
    """FR-05b：已结算单据禁止红冲"""
    owner, branch, mat = await _setup(auth_client, "8")
    await auth_client.post("/api/v1/stock/ledger/change", json={
        "branch_id": branch["id"], "bm_id": mat["id"], "owner_id": owner["id"],
        "changes": [{"field": "arrive_store", "delta": 5}],
        "bill_type": "purchase_order", "bill_bn": "PO8", "bill_item_id": 1, "action": "purchase",
    })
    bill = (await auth_client.post("/api/v1/stock/bills", json={
        "bill_type": "purchase_in", "branch_id": branch["id"], "owner_id": owner["id"],
        "items": [{"bm_id": mat["id"], "issued_num": 5, "confirmed_num": 5}],
    })).json()["data"]
    await auth_client.post(f"/api/v1/stock/bills/{bill['id']}/confirm")
    await auth_client.put(f"/api/v1/stock/bills/{bill['id']}/settle", json={
        "settle_status": 3, "settle_bn": "ST001", "settle_num": 5, "settle_money": 25,
    })
    r = await auth_client.post(f"/api/v1/stock/bills/{bill['id']}/red-flush", json={
        "reason": "尝试红冲", "operator": "tester",
    })
    assert r.status_code == 409
    assert "结算" in r.json()["message"]


# ============ 结算与追溯（FR-05/FR-06）============

async def test_settle_status_update(auth_client):
    """FR-05a 结算状态回写"""
    owner, branch, mat = await _setup(auth_client, "9")
    bill = (await auth_client.post("/api/v1/stock/bills", json={
        "bill_type": "purchase_in", "branch_id": branch["id"], "owner_id": owner["id"],
        "items": [{"bm_id": mat["id"], "issued_num": 8, "confirmed_num": 8, "unit_cost": 3}],
    })).json()["data"]
    await auth_client.post(f"/api/v1/stock/bills/{bill['id']}/confirm")
    r = await auth_client.put(f"/api/v1/stock/bills/{bill['id']}/settle", json={
        "settle_status": 2, "settle_bn": "ST002", "settle_num": 8, "settle_money": 24,
    })
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["settle_status"] == 2
    assert d["settle_bn"] == "ST002"
    assert d["settle_money"] == 24


async def test_bill_trace_chain(auth_client):
    """FR-06a 追溯链：单据 → 流水 → 记账行余额"""
    owner, branch, mat = await _setup(auth_client, "10")
    bill = (await auth_client.post("/api/v1/stock/bills", json={
        "bill_type": "stocktake_in", "branch_id": branch["id"], "owner_id": owner["id"],
        "items": [{"bm_id": mat["id"], "issued_num": 6, "confirmed_num": 6}],
    })).json()["data"]
    await auth_client.post(f"/api/v1/stock/bills/{bill['id']}/confirm")

    r = await auth_client.get(f"/api/v1/stock/bills/{bill['id']}/trace")
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["bill"]["bill_bn"] == bill["bill_bn"]
    assert len(d["change_logs"]) == 1
    assert d["change_logs"][0]["change_num"] == 6
    assert d["ledger"][f"bm_{mat['id']}_store"] == 6
