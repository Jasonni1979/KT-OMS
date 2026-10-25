"""模拟器测试（V1.1 §2.1/§2.2）：签名/错误码/增量分页/造单场景/回传接收

不依赖外部服务：直接用 FastAPI TestClient 跑 mock-platform 应用。
"""
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.protocol import calc_sign
from app.store import SCENARIOS

client = TestClient(app)
SECRET = "mock_app_secret"


def _signed(method: str, **params) -> dict:
    p = {"method": method, "timestamp": str(int(time.time())), "app_key": "mock_app_key", **params}
    p["sign"] = calc_sign(p, SECRET)
    return p


@pytest.fixture(autouse=True)
def _reset():
    client.post("/sim/reset")
    yield
    client.post("/sim/reset")


def test_sign_verify_rejects_unsigned():
    """签名校验：无 sign → isv.invalid-signature"""
    r = client.post("/api/taobao/router", json={"method": "taobao.trade.sold.get"})
    assert r.json()["error_response"]["code"] == "isv.invalid-signature"


def test_sign_verify_rejects_wrong_sign():
    """签名校验：错 sign → isv.invalid-signature"""
    r = client.post("/api/taobao/router", json={
        "method": "taobao.trade.sold.get", "sign": "WRONG",
    })
    assert r.json()["error_response"]["code"] == "isv.invalid-signature"


def test_session_invalid():
    """Session 校验：无效 session → isv.invalid-session-key"""
    r = client.post("/api/taobao/router", json=_signed(
        "taobao.trade.sold.get", session="bad_session"))
    assert r.json()["error_response"]["code"] == "isv.invalid-session-key"


def test_error_injection():
    """错误注入：_inject_error → 返回指定错误码（供适配器重试逻辑锻炼）"""
    r = client.post("/api/taobao/router", json=_signed(
        "taobao.trade.sold.get", _inject_error="isv.trade-service-error"))
    err = r.json()["error_response"]
    assert err["code"] == "isv.trade-service-error"
    assert err["sub_code"] == "isv.trade-service-error"


def test_method_not_allowed():
    r = client.post("/api/taobao/router", json=_signed("taobao.unknown.method"))
    assert r.json()["error_response"]["code"] == "isv.method-not-allowed"


def test_generate_and_pull_orders():
    """造单 → 拉单：total_results 与返回单数一致"""
    gen = client.post("/sim/orders", json={"scenario": "normal", "count": 3}).json()
    assert gen["data"]["count"] == 3
    r = client.post("/api/taobao/router", json=_signed(
        "taobao.trade.sold.get", page_no=1, page_size=10)).json()
    resp = r["trade_sold_get_response"]
    assert resp["total_results"] == 3
    assert len(resp["trades"]) == 3
    t = resp["trades"][0]
    # 报文形状对齐 canonical 映射所需字段
    for f in ("tid", "status", "created", "modified", "pay_time", "buyer_nick",
              "receiver_name", "receiver_mobile", "receiver_state", "receiver_city",
              "receiver_district", "receiver_address", "total_fee", "post_fee",
              "buyer_pay_amount", "platform_bear_amount", "orders"):
        assert f in t, f"缺少字段 {f}"
    sub = t["orders"][0]
    for f in ("oid", "item_id", "sku_id", "item_title", "num", "price", "total_fee"):
        assert f in sub


def test_pagination():
    """分页：page_no/page_size 淘系语义"""
    client.post("/sim/orders", json={"scenario": "normal", "count": 5})
    p1 = client.post("/api/taobao/router", json=_signed(
        "taobao.trade.sold.get", page_no=1, page_size=2)).json()["trade_sold_get_response"]
    p2 = client.post("/api/taobao/router", json=_signed(
        "taobao.trade.sold.get", page_no=2, page_size=2)).json()["trade_sold_get_response"]
    p3 = client.post("/api/taobao/router", json=_signed(
        "taobao.trade.sold.get", page_no=3, page_size=2)).json()["trade_sold_get_response"]
    assert p1["total_results"] == 5
    assert len(p1["trades"]) == 2 and len(p2["trades"]) == 2 and len(p3["trades"]) == 1
    ids = {t["tid"] for t in p1["trades"]} | {t["tid"] for t in p2["trades"]}
    assert len(ids) == 4  # 无重复


def test_incremental_window():
    """增量语义：start_modified/end_modified 时间窗过滤"""
    client.post("/sim/orders", json={"scenario": "normal", "count": 2})
    r = client.post("/api/taobao/router", json=_signed(
        "taobao.trade.sold.get", start_modified="2000-01-01 00:00:00",
        end_modified="2000-01-02 00:00:00")).json()["trade_sold_get_response"]
    assert r["total_results"] == 0
    r2 = client.post("/api/taobao/router", json=_signed(
        "taobao.trade.sold.get", start_modified="2000-01-01 00:00:00")).json()
    assert r2["trade_sold_get_response"]["total_results"] == 2


def test_trade_detail_and_not_exist():
    """详情：存在则返回；不存在 → isv.trade-not-exist"""
    tid = client.post("/sim/orders", json={"scenario": "normal", "count": 1}).json()["data"]["tids"][0]
    r = client.post("/api/taobao/router", json=_signed("taobao.trade.detail.get", tid=tid)).json()
    assert r["trade_detail_get_response"]["trade"]["tid"] == tid
    r2 = client.post("/api/taobao/router", json=_signed(
        "taobao.trade.detail.get", tid="NOT_EXIST")).json()
    assert r2["error_response"]["code"] == "isv.trade-not-exist"


def test_item_get():
    """商品查询：存在返回 sku；不存在 → isv.item-not-exist"""
    r = client.post("/api/taobao/router", json=_signed(
        "taobao.item.get", item_id="ITEM_TSHIRT_001")).json()
    assert "item_get_response" in r
    r2 = client.post("/api/taobao/router", json=_signed(
        "taobao.item.get", item_id="NOPE")).json()
    assert r2["error_response"]["code"] == "isv.item-not-exist"


def test_logistics_writeback_received():
    """发货回传：模拟器接收并留档（供链路断言）"""
    tid = client.post("/sim/orders", json={"scenario": "normal", "count": 1}).json()["data"]["tids"][0]
    r = client.post("/api/taobao/router", json=_signed(
        "taobao.logistics.online.send", tid=tid,
        logistics_company="SF", logistics_no="SF123456")).json()
    assert "logistics_online_send_response" in r
    wb = client.get("/sim/writebacks").json()["data"]
    assert wb["total"] == 1
    assert wb["items"][0]["tid"] == tid
    # 订单状态推进为待收货
    detail = client.post("/api/taobao/router", json=_signed(
        "taobao.trade.detail.get", tid=tid)).json()["trade_detail_get_response"]["trade"]
    assert detail["status"] == "WAIT_BUYER_CONFIRM_GOODS"


def test_scenarios_all_work():
    """造单场景库：全部场景可生成且结构完整"""
    for scn in SCENARIOS:
        gen = client.post("/sim/orders", json={"scenario": scn, "count": 1}).json()
        assert gen["code"] == 0, scn
        tid = gen["data"]["tids"][0]
        detail = client.post("/api/taobao/router", json=_signed(
            "taobao.trade.detail.get", tid=tid)).json()["trade_detail_get_response"]["trade"]
        assert detail["orders"], f"{scn} 场景缺行"


def test_multi_item_and_out_of_stock_shapes():
    """场景特征：多商品单多行；缺货单数量异常放大"""
    tid = client.post("/sim/orders", json={"scenario": "multi_item", "count": 1}).json()["data"]["tids"][0]
    d = client.post("/api/taobao/router", json=_signed(
        "taobao.trade.detail.get", tid=tid)).json()["trade_detail_get_response"]["trade"]
    assert len(d["orders"]) >= 2
    tid2 = client.post("/sim/orders", json={"scenario": "out_of_stock", "count": 1}).json()["data"]["tids"][0]
    d2 = client.post("/api/taobao/router", json=_signed(
        "taobao.trade.detail.get", tid=tid2)).json()["trade_detail_get_response"]["trade"]
    assert d2["orders"][0]["num"] > 100


def test_refund_generation_and_query():
    """售后：造单带 with_refund → refund.get 可查"""
    gen = client.post("/sim/orders", json={
        "scenario": "return_refund", "count": 1, "with_refund": True}).json()
    tid = gen["data"]["tids"][0]
    r = client.post("/api/taobao/router", json=_signed("taobao.refund.get", tid=tid)).json()
    refunds = r["refund_get_response"]["refunds"]
    assert len(refunds) == 1
    assert refunds[0]["refund_type"] == "RETURN_GOODS"
    assert refunds[0]["tid"] == tid


def test_unknown_scenario_rejected():
    r = client.post("/sim/orders", json={"scenario": "not_exist", "count": 1}).json()
    assert r["code"] == 400
