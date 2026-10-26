"""订单接入与拉单测试（M1c-3a/3b，SRS-D02.03 + D03.01）

覆盖：canonical 转换/字段映射/优惠分摊算法/订单号规则/建单落库与四套状态/
幂等防重/硬失败分级/软失败标记/BOM 展开快照/未知商品自动建档/水位推进/
拉单幂等路由/端到端（模拟器造单 → 拉单 → 建单）。
"""
import os
import socket
import subprocess
import time
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.db import SessionFactory, engine

pytestmark = pytest.mark.asyncio

REPO_ROOT = Path(__file__).resolve().parents[2]
MOCK_DIR = REPO_ROOT / "mocks" / "platform"

CLEANUP_SQL = [
    "DELETE FROM oms_order.ord_order_item WHERE order_id IN "
    "(SELECT id FROM oms_order.ord_order WHERE platform_order_bn LIKE 'SIM%')",
    "DELETE FROM oms_order.ord_order_pmt WHERE order_id IN "
    "(SELECT id FROM oms_order.ord_order WHERE platform_order_bn LIKE 'SIM%')",
    "DELETE FROM oms_order.ord_receiver WHERE order_id IN "
    "(SELECT id FROM oms_order.ord_order WHERE platform_order_bn LIKE 'SIM%')",
    "DELETE FROM oms_order.ord_status_log WHERE order_id IN "
    "(SELECT id FROM oms_order.ord_order WHERE platform_order_bn LIKE 'SIM%')",
    "DELETE FROM oms_order.ord_order WHERE platform_order_bn LIKE 'SIM%'",
    "DELETE FROM oms_order.ord_order_fail WHERE platform_order_bn LIKE 'SIM%'",
    "DELETE FROM oms_gateway.gw_order_buffer_item WHERE buffer_id IN "
    "(SELECT id FROM oms_gateway.gw_order_buffer WHERE platform_order_bn LIKE 'SIM%')",
    "DELETE FROM oms_gateway.gw_order_buffer WHERE platform_order_bn LIKE 'SIM%'",
    "DELETE FROM oms_gateway.gw_pull_watermark WHERE shop_id IN "
    "(SELECT id FROM oms_gateway.gw_shop WHERE shop_name LIKE '测试拉单%')",
    "DELETE FROM oms_gateway.gw_api_log WHERE primary_bn LIKE 'SIM%'",
    "DELETE FROM oms_stock.inv_bom_item WHERE sm_id IN "
    "(SELECT id FROM oms_stock.inv_sales_material WHERE sales_material_bn LIKE 'SM\\_OI\\_%')",
    "DELETE FROM oms_stock.inv_bom_version WHERE sm_id IN "
    "(SELECT id FROM oms_stock.inv_sales_material WHERE sales_material_bn LIKE 'SM\\_OI\\_%')",
    "DELETE FROM oms_stock.inv_sales_material WHERE sales_material_bn LIKE 'SM\\_OI\\_%'",
    "DELETE FROM oms_stock.inv_material WHERE material_bn LIKE 'BM\\_OI\\_%'",
    "DELETE FROM oms_gateway.gw_shop WHERE shop_name LIKE '测试拉单%'",
    "DELETE FROM oms_org.org_node WHERE org_code LIKE 'SHOP\\_OI\\_%'",
    "DELETE FROM oms_org.org_owner WHERE owner_code LIKE 'T\\_OI\\_%'",
]


async def _cleanup() -> None:
    async with engine.begin() as conn:
        for sql in CLEANUP_SQL:
            await conn.execute(text(sql))


@pytest.fixture(autouse=True, scope="module")
async def isolate_order_data():
    """数据隔离 + 注入超管上下文

    服务层直连 DB 时不带请求上下文 → fail-closed 会拒绝查询（这是 D10.03 的设计）。
    测试通过显式注入超管上下文来模拟「API 请求内调用服务层」的等价环境。
    """
    from app.core.db import AuthContext, set_auth_context

    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    await _cleanup()
    yield
    await _cleanup()
    set_auth_context(None)


# ============ 基础数据 ============


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
    r = await auth_client.post(
        f"/api/v1/master/shops?parent_node_id={await _owner_co_node_id()}",
        json={"shop_name": name, "owner_id": owner_id, "platform": "taobao",
              "platform_shop_id": f"tb_{name}",
              "shop_type": "flagship", "business_type": "direct_sale"},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _make_material(auth_client, bn: str, name: str, owner_id: int) -> dict:
    r = await auth_client.post("/api/v1/material/materials", json={
        "material_bn": bn, "material_name": name, "owner_id": owner_id, "type": 3,
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _make_sales_material(
    auth_client, shop_id: int, bn: str, name: str
) -> dict:
    r = await auth_client.post("/api/v1/material/sales-materials", json={
        "shop_id": shop_id, "sales_material_bn": bn, "sales_material_name": name,
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _bind_bom(auth_client, sm_id: int, bm_id: int) -> dict:
    r = await auth_client.post(f"/api/v1/material/sales-materials/{sm_id}/bom", json={
        "items": [{"bm_id": bm_id, "bind_num": 1, "rate": 100, "fixed_price": 0}],
    })
    assert r.status_code == 200, r.text
    return r.json()["data"]


def _trade(
    tid: str = "SIM900001",
    sku: str = "SM_OI_001",
    *,
    total_fee: float = 100.0,
    paid: float = 90.0,
    platform_bear: float = 10.0,
    freight: float = 0.0,
    num: int = 2,
    price: float = 50.0,
    status: str = "WAIT_SELLER_SEND_GOODS",
    modified: str = "2026-10-25 10:00:00",
) -> dict:
    """构造一条淘系 trade 报文（形状对齐 mock-platform）"""
    return {
        "tid": tid,
        "status": status,
        "created": "2026-10-25 09:00:00",
        "modified": modified,
        "pay_time": "2026-10-25 09:05:00",
        "buyer_nick": "测试买家",
        "receiver_name": "张三",
        "receiver_mobile": "13800000000",
        "receiver_state": "浙江省",
        "receiver_city": "杭州市",
        "receiver_district": "西湖区",
        "receiver_address": "文三路100号",
        "receiver_zip": "310000",
        "buyer_message": "麻烦发顺丰",
        "seller_memo": "",
        "total_fee": total_fee,
        "post_fee": freight,
        "buyer_pay_amount": paid,
        "platform_bear_amount": platform_bear,
        "consign_time": "",
        "logistics_type": "快递",
        "shipping_type": "快递",
        "warehouse_hint": "",
        "logistics_hint": "",
        "receiver_encrypted_channel": "none",
        "oaid": "",
        "orders": [{
            "oid": f"{tid}-1",
            "item_id": "50001",
            "sku_id": sku,
            "item_title": "测试保温杯",
            "sku_spec": "红色 500ml",
            "num": num,
            "price": price,
            "total_fee": price * num,
            "divide_order_fee": platform_bear,
            "refund_status": "NO_REFUND",
            "gift": False,
        }],
    }


# ============ ① canonical 转换（D02.03 FR-04a）============


def test_canonical_conversion_taobao():
    """淘系报文 → canonical：字段映射 + 双口径反推 + 行级映射"""
    from app.adapters.taobao import to_canonical

    trade = _trade()
    c = to_canonical(trade, shop_id=7)
    assert c.platform == "taobao"
    assert c.shop_id == 7
    assert c.platform_order_bn == "SIM900001"
    assert c.canonical_status == "unshipped"
    assert c.platform_status == "WAIT_SELLER_SEND_GOODS"
    assert c.total_amount == 100.0
    assert c.customer_paid == 90.0
    assert c.platform_bear_total == 10.0
    # 商家承担 = total − paid + freight − platform_bear
    assert c.merchant_bear_total == 0.0
    assert c.freight == 0.0
    assert c.receiver.name == "张三"
    assert c.receiver.mobile == "13800000000"
    assert c.receiver.district == "西湖区"
    assert c.buyer_message == "麻烦发顺丰"
    assert len(c.items) == 1
    it = c.items[0]
    assert it.platform_sku_id == "SM_OI_001"
    assert it.num == 2
    assert it.list_amount == 100.0
    assert it.platform_bear_line == 10.0
    assert it.customer_paid_line == 90.0
    assert c.idem_key == "taobao:7:SIM900001"


def test_canonical_unknown_status_adds_warning():
    """未知平台状态 → 归 unshipped + 转换告警（不静默降级）"""
    from app.adapters.taobao import to_canonical

    c = to_canonical(_trade(status="WEIRD_STATUS"), shop_id=7)
    assert c.canonical_status == "unshipped"
    assert any("未知平台状态" in w for w in c.convert_warnings)


def test_canonical_status_mapping_table():
    """平台状态 → canonical 状态映射表完整"""
    from app.adapters.taobao import STATUS_MAP

    assert STATUS_MAP["WAIT_BUYER_PAY"] == "unpaid"
    assert STATUS_MAP["WAIT_SELLER_SEND_GOODS"] == "unshipped"
    assert STATUS_MAP["WAIT_BUYER_CONFIRM_GOODS"] == "shipped"
    assert STATUS_MAP["TRADE_CLOSED"] == "closed"
    assert STATUS_MAP["TRADE_FINISHED"] == "finished"


# ============ ② 优惠分摊（D03.01 §5.2）============


def test_allocation_proportional_with_tail():
    """比例分摊：尾差归最大金额行；Σ行实付 = 订单实付（不含运费）"""
    from app.modules.m3_trade.service.allocation import allocate, check_amount_consistency

    lines = [(1, 33.33), (2, 33.33), (3, 33.34)]
    allocs, _ = allocate(lines, shop_discount=10.0, platform_subsidy=0.0)
    assert round(sum(a.shop_discount for a in allocs), 2) == 10.0
    # 尾差归最大金额行（第3行 33.34）
    assert allocs[2].shop_discount > allocs[0].shop_discount
    ok, msg = check_amount_consistency(allocs, 90.0, 0.0)
    assert ok, msg


def test_allocation_dual_split():
    """双口径二次拆分：商家 6 + 平台 4 = 10，分摊到行"""
    from app.modules.m3_trade.service.allocation import allocate

    lines = [(1, 50.0), (2, 50.0)]
    allocs, _ = allocate(lines, shop_discount=6.0, platform_subsidy=4.0)
    assert round(sum(a.shop_discount for a in allocs), 2) == 6.0
    assert round(sum(a.platform_subsidy for a in allocs), 2) == 4.0
    assert round(sum(a.paid_amount for a in allocs), 2) == 90.0


def test_allocation_gift_line_zero():
    """0 元行（赠品）不参与分摊，实付为 0"""
    from app.modules.m3_trade.service.allocation import allocate

    lines = [(1, 100.0), (2, 0.0)]
    allocs, _ = allocate(lines, shop_discount=10.0, platform_subsidy=0.0)
    assert allocs[1].shop_discount == 0.0
    assert allocs[1].paid_amount == 0.0


def test_allocation_consistency_detects_mismatch():
    """金额勾稽超差 → 检出（FR-04b 硬失败前置）"""
    from app.modules.m3_trade.service.allocation import LineAmount, check_amount_consistency

    lines = [LineAmount(1, 100.0, 0.0, 0.0, 100.0)]
    ok, msg = check_amount_consistency(lines, 50.0, 0.0)
    assert not ok
    assert "金额勾稽超差" in msg


# ============ ③ 订单号（D03.01 FR-03）============


async def test_order_bn_format_and_uniqueness(auth_client):
    """订单号 17 位规则：前缀+yyMMdd+店铺码3位+混淆序列7位，且不重复"""
    from app.modules.m3_trade.service.order_bn import OrderBnGenerator, shop_code_of

    assert shop_code_of("S20261025000123") == "123"
    assert shop_code_of("S20261025999999") == "999"
    assert len(shop_code_of("S1")) == 3

    from app.modules.m1_master.service.master import get_redis

    redis = await get_redis()
    async with SessionFactory() as s:
        gen = OrderBnGenerator(s, redis)
        bns = [await gen.next("P", "S202610250001") for _ in range(5)]
    assert len(set(bns)) == 5
    for bn in bns:
        assert len(bn) == 17, bn
        assert bn[0] == "P"
        assert bn[1:7].isdigit()
        assert bn[7:10].isdigit()
        assert bn[10:].isdigit()


# ============ ④ 建单落库（D03.01 FR-04/05）============


async def _canonical_of(trade: dict, shop_id: int):
    from app.adapters.taobao import to_canonical

    return to_canonical(trade, shop_id=shop_id)


async def test_create_order_persists_aggregate(auth_client):
    """建单落库：订单头+行+收货人(加密)+优惠分摊+状态日志，四套状态初始化"""
    from app.modules.m1_master.service.master import get_redis
    from app.modules.m3_trade.service.order_create import OrderCreateService

    owner = await _make_owner(auth_client, "T_OI_01", "接入测试货主")
    shop = await _make_shop(auth_client, "测试拉单店01", owner["id"])
    mat = await _make_material(auth_client, "BM_OI_01", "基础物料01", owner["id"])
    sm = await _make_sales_material(auth_client, shop["id"], "SM_OI_001", "销售物料01")
    await _bind_bom(auth_client, sm["id"], mat["id"])

    redis = await get_redis()
    c = await _canonical_of(_trade(sku="SM_OI_001"), shop["id"])
    async with SessionFactory() as s:
        res = await OrderCreateService(s, redis).create(c, source="platform")
    assert res.ok, res.hard_message
    assert res.order_id > 0
    assert len(res.order_bn) == 17

    # 订单头
    r = await auth_client.get(f"/api/v1/orders/{res.order_id}")
    order = r.json()["data"]
    assert order["platform_order_bn"] == "SIM900001"
    assert order["audit_status"] == "pending"
    assert order["fulfill_status"] == "pending"
    assert order["ship_status"] == "unshipped"
    assert order["order_status"] == "processing"
    assert order["pay_status"] == "paid"
    assert order["list_amount"] == 100.0
    assert order["platform_subsidy"] == 10.0
    assert order["paid_amount"] == 90.0
    # 行 + BOM 展开快照
    assert len(order["items"]) == 1
    item = order["items"][0]
    assert item["bm_number"] == "BM_OI_01"
    assert item["bom_version"] >= 1
    assert item["parse_status"] == "parsed"
    assert item["nums"] == 2
    # 收货人脱敏
    rcv = (await auth_client.get(
        f"/api/v1/orders/{res.order_id}/receiver")).json()["data"]
    assert rcv["name_masked"] == "张*"
    assert rcv["mobile_masked"] == "138****0000"
    assert rcv["mobile_tail4"] == "0000"
    # 优惠分摊（单级）
    pmts = (await auth_client.get(
        f"/api/v1/orders/{res.order_id}/pmt")).json()["data"]
    assert any(p["bearer"] == "platform" and p["amount"] == 10.0 for p in pmts)


async def test_create_order_is_idempotent(auth_client):
    """幂等防重（FR-02a）：同 (shop, 平台单号) 重复创建返回已存在 order_id，不重复落库"""
    from app.modules.m1_master.service.master import get_redis
    from app.modules.m3_trade.service.order_create import OrderCreateService

    owner = await _make_owner(auth_client, "T_OI_02", "幂等测试货主")
    shop = await _make_shop(auth_client, "测试拉单店02", owner["id"])
    redis = await get_redis()
    c = await _canonical_of(_trade(tid="SIM900002"), shop["id"])
    async with SessionFactory() as s:
        svc = OrderCreateService(s, redis)
        r1 = await svc.create(c, source="platform")
        r2 = await svc.create(c, source="platform")
    assert r1.ok and r2.ok
    assert r2.duplicated
    assert r2.order_id == r1.order_id
    lst = (await auth_client.get(
        "/api/v1/orders", params={"platform_order_bn": "SIM900002"})).json()["data"]
    assert len(lst) == 1


async def test_hard_fail_amount_mismatch(auth_client):
    """硬失败：金额勾稽超差 → 落失败单，不建订单（FR-04c）"""
    from app.modules.m1_master.service.master import get_redis
    from app.modules.m3_trade.service.order_create import OrderCreateService

    owner = await _make_owner(auth_client, "T_OI_03", "勾稽测试货主")
    shop = await _make_shop(auth_client, "测试拉单店03", owner["id"])
    redis = await get_redis()
    # 平台报文不自洽：订单头原价 100，但行原价合计仅 80 → 行实付合计 ≠ 订单实付
    trade = _trade(tid="SIM900003", total_fee=100.0, paid=90.0, platform_bear=0.0)
    trade["orders"][0]["price"] = 40.0
    trade["orders"][0]["total_fee"] = 80.0
    trade["orders"][0]["divide_order_fee"] = 0.0
    c = await _canonical_of(trade, shop["id"])
    async with SessionFactory() as s:
        res = await OrderCreateService(s, redis).create(c, source="platform")
    assert not res.ok
    assert res.hard_failure == "AMOUNT_MISMATCH"
    lst = (await auth_client.get(
        "/api/v1/orders", params={"platform_order_bn": "SIM900003"})).json()["data"]
    assert not lst
    fails = (await auth_client.get(
        "/api/v1/orders/fail/list")).json()["data"]
    hit = [f for f in fails if f["platform_order_bn"] == "SIM900003"]
    assert hit and hit[0]["fail_code"] == "AMOUNT_MISMATCH"
    assert hit[0]["handle_status"] == "pending"


async def test_hard_fail_empty_items(auth_client):
    """硬失败：商品行为空 → 落失败单"""
    from app.modules.m1_master.service.master import get_redis
    from app.modules.m3_trade.service.order_create import OrderCreateService

    owner = await _make_owner(auth_client, "T_OI_04", "空行测试货主")
    shop = await _make_shop(auth_client, "测试拉单店04", owner["id"])
    redis = await get_redis()
    trade = _trade(tid="SIM900004")
    trade["orders"] = []
    c = await _canonical_of(trade, shop["id"])
    async with SessionFactory() as s:
        res = await OrderCreateService(s, redis).create(c, source="platform")
    assert not res.ok
    assert res.hard_failure == "ITEM_EMPTY"


async def test_hard_fail_invalid_shop(auth_client):
    """硬失败：店铺无效 → 落失败单"""
    from app.modules.m1_master.service.master import get_redis
    from app.modules.m3_trade.service.order_create import OrderCreateService

    redis = await get_redis()
    c = await _canonical_of(_trade(tid="SIM900005"), 999999)
    async with SessionFactory() as s:
        res = await OrderCreateService(s, redis).create(c, source="platform")
    assert not res.ok
    assert res.hard_failure == "SHOP_INVALID"


async def test_soft_fail_unbound_sku(auth_client):
    """软失败：商品未绑定 → 正常落库 + parse_status=pending + 软失败标记"""
    from app.modules.m1_master.service.master import get_redis
    from app.modules.m3_trade.service.order_create import OrderCreateService

    owner = await _make_owner(auth_client, "T_OI_05", "未绑定测试货主")
    shop = await _make_shop(auth_client, "测试拉单店05", owner["id"])
    redis = await get_redis()
    c = await _canonical_of(_trade(tid="SIM900006", sku="SM_OI_NOBIND"), shop["id"])
    async with SessionFactory() as s:
        res = await OrderCreateService(s, redis).create(c, source="platform")
    assert res.ok, res.hard_message
    assert res.soft_failures
    order = (await auth_client.get(
        f"/api/v1/orders/{res.order_id}")).json()["data"]
    assert order["items"][0]["parse_status"] == "pending"


# ============ ⑤ 未知商品自动建档（D02.03 FR-05）============


async def test_unknown_sku_auto_create(auth_client):
    """未知商品自动建档：生成销售物料档案（幂等，FR-05a）"""
    from app.modules.m1_master.service.master import get_redis
    from app.modules.m2_stock.service.sku_mapping import SkuMappingService

    owner = await _make_owner(auth_client, "T_OI_06", "自动建档货主")
    shop = await _make_shop(auth_client, "测试拉单店06", owner["id"])
    redis = await get_redis()
    async with SessionFactory() as s:
        svc = SkuMappingService(s, redis, None)
        m = await svc.map_line(
            shop_id=shop["id"], line_no=1,
            platform_sku_id="SM_OI_AUTO", platform_item_id="50099", qty=1,
        )
        assert m.auto_created
        assert m.sm_id > 0
        # 幂等：再建一次不再新建
        m2 = await svc.map_line(
            shop_id=shop["id"], line_no=1,
            platform_sku_id="SM_OI_AUTO", platform_item_id="50099", qty=1,
        )
    assert m2.sm_id == m.sm_id
    assert not m2.auto_created


# ============ ⑥ 水位（D02.03 FR-02a）============


async def test_watermark_advances_and_never_regresses(auth_client):
    """水位：CAS 推进且只进不退"""
    from datetime import datetime, timedelta

    from app.modules.m1_master.service.master import get_redis
    from app.modules.m7_integration.service.gateway import get_gateway
    from app.modules.m7_integration.service.pull import PullService

    owner = await _make_owner(auth_client, "T_OI_07", "水位测试货主")
    shop = await _make_shop(auth_client, "测试拉单店07", owner["id"])
    redis = await get_redis()
    async with SessionFactory() as s:
        svc = PullService(s, get_gateway(redis), redis)
        wm = await svc.get_watermark(shop["id"])
        # DDL NOT NULL → 首次建行即给 24h 回溯起点
        assert wm.last_download_time is not None
        t1 = datetime.now() - timedelta(minutes=5)
        ok1 = await svc._advance_watermark(wm, t1)
        assert ok1
        await svc.s.refresh(wm)
        assert wm.last_download_time is not None
        # 回退时间 → 不推进
        ok2 = await svc._advance_watermark(wm, t1 - timedelta(minutes=1))
        assert not ok2


# ============ ⑦ 端到端（模拟器 → 拉单 → 建单）============


def _free_port() -> int:
    """探测空闲端口（避免固定端口被占用导致用例失败）"""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def mock_platform():
    """启动 mock-platform（独立进程，动态端口）"""
    port = _free_port()
    py = str(REPO_ROOT / "backend" / ".venv" / "bin" / "python")
    env = {**os.environ, "PYTHONPATH": str(MOCK_DIR)}
    proc = subprocess.Popen(
        [py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(MOCK_DIR), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                break
        except OSError:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.skip("mock-platform 启动失败（跳过端到端用例）")
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


async def test_end_to_end_pull_to_order(mock_platform, auth_client, monkeypatch):
    """端到端：模拟器造单 → 拉单 → canonical 缓冲 → 订单落库 → 幂等重拉不重复建单"""
    import httpx

    from app.core.config import settings
    from app.modules.m1_master.service.master import get_redis
    from app.modules.m7_integration.service.gateway import get_gateway
    from app.modules.m7_integration.service.pull import PullService

    # 网关指向模拟器
    monkeypatch.setattr(settings, "platform_gateway_url", mock_platform)
    get_gateway(redis=None)

    # ① 模拟器造单
    async with httpx.AsyncClient() as hc:
        r = await hc.post(f"{mock_platform}/sim/orders",
                          json={"scenario": "normal", "count": 3})
        assert r.status_code == 200, r.text
        made = r.json()["data"]
        assert made["count"] == 3

    # ② 准备本地店铺与物料（模拟器 SKU 需与本地销售物料一致才能映射）
    owner = await _make_owner(auth_client, "T_OI_E2E", "端到端货主")
    shop = await _make_shop(auth_client, "测试拉单店E2E", owner["id"])
    mat = await _make_material(auth_client, "BM_OI_E2E", "端到端基础物料", owner["id"])
    sm = await _make_sales_material(auth_client, shop["id"], "SIMSKU001", "端到端销售物料")
    await _bind_bom(auth_client, sm["id"], mat["id"])

    # ③ 拉单（模拟器造的单用的是自己的 SKU → 未映射 → 软失败 pending，仍应建单）
    #    说明：默认 safety_delay_sec=60（平台数据延迟保护）会把"刚刚造的单"挡在窗口外，
    #    真实拉单本就有 1 分钟延迟；测试用店铺级覆写把延迟设为 0 以便即时验证。
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO oms_gateway.gw_pull_watermark "
            "(tenant_id, shop_id, channel, last_download_time, overlap_sec, "
            " safety_delay_sec, poll_interval_sec, lag_alert_threshold_sec, "
            " create_time, update_time, version) "
            "VALUES (1, :sid, 'order', NOW(3), 300, 0, 60, 1800, NOW(3), NOW(3), 0) "
            "ON DUPLICATE KEY UPDATE safety_delay_sec = 0"
        ), {"sid": shop["id"]})
    redis = await get_redis()
    async with SessionFactory() as s:
        svc = PullService(s, get_gateway(redis), redis)
        stat = await svc.poll_shop(shop["id"])
    assert stat["ok"], stat
    assert stat["created"] >= 1

    # ④ 订单落库
    orders = (await auth_client.get(
        "/api/v1/orders", params={"shop_id": shop["id"]})).json()["data"]
    assert orders, "拉单后应有订单落库"
    o = orders[0]
    assert len(o["order_bn"]) == 17
    assert o["platform_order_bn"].startswith("SIM")
    assert o["audit_status"] == "pending"
    assert o["pay_status"] == "paid"

    # ⑤ 缓冲池已投递
    buffers = (await auth_client.get(
        "/api/v1/pull/buffer", params={"shop_id": shop["id"]})).json()["data"]
    assert buffers
    assert buffers[0]["deliver_status"] == "accepted"

    # ⑥ 水位已推进
    wm = (await auth_client.get(
        f"/api/v1/pull/watermark/{shop['id']}")).json()["data"]
    assert wm["last_download_time"] is not None

    # ⑦ 幂等：再拉一次不重复建单
    before = len(orders)
    async with SessionFactory() as s:
        stat2 = await PullService(s, get_gateway(redis), redis).poll_shop(shop["id"])
    assert stat2["ok"]
    orders2 = (await auth_client.get(
        "/api/v1/orders", params={"shop_id": shop["id"]})).json()["data"]
    assert len(orders2) == before

    # ⑧ api_log 有留痕
    logs = (await auth_client.get("/api/v1/gateway/logs")).json()["data"]
    assert any(row["method"] == "taobao.trade.sold.get" for row in logs)
