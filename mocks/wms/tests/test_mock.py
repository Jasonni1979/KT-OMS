"""WMS 模拟器测试（W7：SRS-D09.02 通道契约保真）

覆盖：
- 签名校验（无 sign / 错 sign 拒绝）
- 出库指令受理 + 单号幂等（重复下发返回首次结果）
- 叫回指令（已开始拣货 → 拒绝）
- 状态回放（接收确认 / 一次性出库 / 部分出库 / 打回 / 叫回成功失败）
- 回传幂等（delivery_bn + batch_no + cb_type）
- 错误注入（RETRYABLE / FATAL 分级）
- 单据反查
"""
from __future__ import annotations

import pytest
from app.main import app
from app.protocol import calc_sign
from fastapi.testclient import TestClient

client = TestClient(app)
SECRET = "mock_wms_secret"


def _signed(body: dict) -> dict:
    b = dict(body)
    b["sign"] = calc_sign(b, SECRET)
    return b


@pytest.fixture(autouse=True)
def _reset():
    client.post("/sim/reset")
    yield
    client.post("/sim/reset")


def _create_cmd(cmd_no: str = "DLV26010100001-R1", lines: int = 2) -> dict:
    """下发一条出库指令，返回受理结果"""
    payload = {
        "cmd_no": cmd_no,
        "warehouse_code": "TTX-HD01",
        "owner_code": "KC",
        "waybill_no": "SF123456789",
        "lines": [
            {"sku_code": f"BM{100 + i}", "num": 2} for i in range(lines)
        ],
    }
    r = client.post("/wms/restful/outbound", json=_signed(payload))
    return r.json()


# ============ 签名 ============


def test_sign_required_rejects_unsigned():
    """无 sign → wms.invalid-signature（FATAL）"""
    r = client.post("/wms/restful/outbound", json={"cmd_no": "X-R1", "lines": [{"num": 1}]})
    body = r.json()
    assert body["code"] == "wms.invalid-signature"
    assert body["err_class"] == "FATAL"


def test_sign_required_rejects_wrong_sign():
    """错 sign → 拒绝"""
    r = client.post(
        "/wms/restful/outbound",
        json={"cmd_no": "X-R1", "lines": [{"num": 1}], "sign": "WRONG"},
    )
    assert r.json()["code"] == "wms.invalid-signature"


# ============ 出库指令 ============


def test_outbound_accept_and_idempotent():
    """指令受理 + 同单号幂等（重复下发不产生第二条指令）"""
    body = _create_cmd()
    assert body["code"] == 0
    assert body["data"]["accepted"] is True
    assert body["data"]["duplicated"] is False
    wms_bill_no = body["data"]["wms_bill_no"]

    body2 = _create_cmd()
    assert body2["code"] == 0
    assert body2["data"]["duplicated"] is True
    assert body2["data"]["wms_bill_no"] == wms_bill_no

    r = client.get("/sim/cmds")
    assert r.json()["data"]["total"] == 1


def test_outbound_requires_lines():
    """缺明细行 → FATAL 报文校验失败"""
    r = client.post(
        "/wms/restful/outbound", json=_signed({"cmd_no": "X-R1", "lines": []})
    )
    assert r.json()["code"] == "wms.invalid-payload"
    assert r.json()["err_class"] == "FATAL"


def test_outbound_requires_cmd_no():
    """缺 cmd_no → FATAL"""
    r = client.post(
        "/wms/restful/outbound", json=_signed({"cmd_no": "", "lines": [{"num": 1}]})
    )
    assert r.json()["code"] == "wms.invalid-payload"


def test_qimen_style_entry():
    """奇门风格入口 deliveryorder.create 与 RESTful 等价"""
    body = _signed(
        {
            "cmd_no": "DLV26010100002-R1",
            "warehouse_code": "TTX-HD01",
            "lines": [{"sku_code": "BM1", "num": 1}],
        }
    )
    r = client.post("/wms/qimen/deliveryorder.create", json=body)
    assert r.json()["code"] == 0
    assert r.json()["data"]["accepted"] is True


def test_qimen_unknown_method_rejected():
    """不支持的方法 → FATAL"""
    r = client.post("/wms/qimen/unknown.method", json=_signed({"cmd_no": "X"}))
    assert r.json()["code"] == "wms.method-not-allowed"


# ============ 叫回 ============


def test_recall_success():
    """叫回指令 → 受理并置已取消"""
    _create_cmd()
    r = client.post(
        "/wms/restful/cancel", json=_signed({"cmd_no": "DLV26010100001-R1"})
    )
    assert r.json()["code"] == 0
    assert r.json()["data"]["cancelled"] is True
    cmds = client.get("/sim/cmds").json()["data"]["items"]
    assert cmds[0]["status"] == "cancelled"


def test_recall_rejected_after_pick():
    """已开始拣货 → 叫回被拒（RETRYABLE）"""
    _create_cmd()
    client.post("/sim/pick", json={"cmd_no": "DLV26010100001-R1"})
    r = client.post(
        "/wms/restful/cancel", json=_signed({"cmd_no": "DLV26010100001-R1"})
    )
    assert r.json()["code"] == "wms.recall-rejected"
    assert r.json()["err_class"] == "RETRYABLE"


def test_recall_unknown_cmd_fatal():
    """指令不存在 → FATAL"""
    r = client.post("/wms/restful/cancel", json=_signed({"cmd_no": "NOT-EXIST-R1"}))
    assert r.json()["code"] == "wms.order-not-exist"
    assert r.json()["err_class"] == "FATAL"


# ============ 状态回放 ============


def test_playback_accepted():
    """接收确认回放 → 指令转作业中"""
    _create_cmd()
    r = client.post(
        "/sim/playback",
        json={"cmd_no": "DLV26010100001-R1", "action": "accepted", "batch_no": "A1"},
    )
    assert r.json()["code"] == 0
    cmds = client.get("/sim/cmds").json()["data"]["items"]
    assert cmds[0]["status"] == "working"
    cbs = client.get("/sim/callbacks").json()["data"]["items"]
    assert cbs[0]["cb_type"] == "accepted"


def test_playback_outbound_full():
    """一次性出库回放 → 产生出库回传（明细/包裹/称重）"""
    _create_cmd(lines=2)
    r = client.post(
        "/sim/playback",
        json={
            "cmd_no": "DLV26010100001-R1",
            "action": "outbound",
            "batch_no": "B1",
            "weight": 3.2,
            "waybill_no": "SF999",
        },
    )
    assert r.json()["code"] == 0
    cbs = client.get("/sim/callbacks").json()["data"]["items"]
    assert cbs[0]["cb_type"] == "outbound"
    assert len(cbs[0]["lines"]) == 2
    assert cbs[0]["weight"] == 3.2
    assert cbs[0]["packages"][0]["package_no"] == "PKGB1"


def test_playback_partial_outbound():
    """部分出库回放 → 只回传第一行（驱动 partial_outbound）"""
    _create_cmd(lines=3)
    client.post(
        "/sim/playback",
        json={"cmd_no": "DLV26010100001-R1", "action": "partial", "batch_no": "B1"},
    )
    cbs = client.get("/sim/callbacks").json()["data"]["items"]
    assert len(cbs[0]["lines"]) == 1
    cmds = client.get("/sim/cmds").json()["data"]["items"]
    assert cmds[0]["status"] == "partial"


def test_playback_actual_num_override_makes_diff():
    """实发数量覆盖 → 制造少发差异"""
    _create_cmd(lines=2)
    client.post(
        "/sim/playback",
        json={
            "cmd_no": "DLV26010100001-R1",
            "action": "outbound",
            "batch_no": "B1",
            "actual_num": {"BM100": 1},  # 指令 2 实发 1 → 少发
        },
    )
    cbs = client.get("/sim/callbacks").json()["data"]["items"]
    lines = {l["sku_code"]: l["num"] for l in cbs[0]["lines"]}
    assert lines["BM100"] == 1


def test_playback_rejected():
    """打回回放 → 结构化原因"""
    _create_cmd()
    client.post(
        "/sim/playback",
        json={
            "cmd_no": "DLV26010100001-R1",
            "action": "rejected",
            "reject_reason": "仓库缺货",
            "reject_reason_code": "LACK_STOCK",
        },
    )
    cbs = client.get("/sim/callbacks").json()["data"]["items"]
    assert cbs[0]["cb_type"] == "rejected"
    assert cbs[0]["reject_reason_code"] == "LACK_STOCK"
    cmds = client.get("/sim/cmds").json()["data"]["items"]
    assert cmds[0]["status"] == "rejected"


def test_playback_recall_result():
    """叫回结果回放（成功/失败两态）"""
    _create_cmd()
    client.post(
        "/sim/playback",
        json={"cmd_no": "DLV26010100001-R1", "action": "recall_success"},
    )
    cbs = client.get("/sim/callbacks").json()["data"]["items"]
    assert cbs[0]["cb_type"] == "cancelled"


# ============ 回传幂等 ============


def test_callback_idempotent_by_batch():
    """回传幂等：同 delivery_bn + batch_no + cb_type 只登记一次"""
    _create_cmd()
    payload = {
        "cb_type": "outbound",
        "cmd_no": "DLV26010100001-R1",
        "batch_no": "B1",
        "lines": [{"sku_code": "BM100", "num": 2}],
    }
    r1 = client.post("/wms/callback", json=payload)
    r2 = client.post("/wms/callback", json=payload)
    assert r1.json()["data"]["duplicated"] is False
    assert r2.json()["data"]["duplicated"] is True
    assert client.get("/sim/callbacks").json()["data"]["total"] == 1


# ============ 错误注入 ============


def test_inject_retryable_error():
    """注入 RETRYABLE 错误（通道层应重试）"""
    r = client.post(
        "/wms/restful/outbound",
        json=_signed(
            {
                "cmd_no": "X-R1",
                "lines": [{"sku_code": "A", "num": 1}],
                "_inject_error": "SYSTEM_BUSY",
            }
        ),
    )
    body = r.json()
    assert body["code"] == "wms.system-busy"
    assert body["err_class"] == "RETRYABLE"


def test_inject_fatal_error():
    """注入 FATAL 错误（不可重试）"""
    r = client.post(
        "/wms/restful/outbound",
        json=_signed(
            {
                "cmd_no": "X-R1",
                "lines": [{"sku_code": "A", "num": 1}],
                "_inject_error": "INVALID_PAYLOAD",
            }
        ),
    )
    body = r.json()
    assert body["code"] == "wms.invalid-payload"
    assert body["err_class"] == "FATAL"


def test_inject_unknown_error_rejected():
    """未支持的注入码 → FATAL"""
    r = client.post(
        "/wms/restful/outbound",
        json=_signed(
            {
                "cmd_no": "X-R1",
                "lines": [{"sku_code": "A", "num": 1}],
                "_inject_error": "NOT_EXIST",
            }
        ),
    )
    assert r.json()["code"] == "wms.unknown-error"


# ============ 单据反查 ============


def test_query_cmd():
    """单据反查（回传超时兜底）"""
    _create_cmd()
    r = client.post(
        "/wms/restful/query", json=_signed({"cmd_no": "DLV26010100001-R1"})
    )
    data = r.json()["data"]
    assert data["found"] is True
    assert data["cmd"]["delivery_bn"] == "DLV26010100001"
    # 不存在
    r2 = client.post("/wms/restful/query", json=_signed({"cmd_no": "NOPE-R1"}))
    assert r2.json()["data"]["found"] is False


def test_healthz():
    """存活探针"""
    r = client.get("/healthz")
    assert r.json()["status"] == "up"


# ============ 错误预置注入（/sim/inject）============


def test_inject_by_cmd_no():
    """按指令单号预置错误 → 下发时返回该错误（次数递减）"""
    _create_cmd()
    r = client.post(
        "/sim/inject",
        json={"cmd_no": "DLV26010100001-R1", "error": "SYSTEM_BUSY", "times": 1},
    )
    assert r.json()["code"] == 0
    assert r.json()["data"]["err_class"] == "RETRYABLE"

    # 第一次下发命中注入
    r2 = client.post(
        "/wms/restful/outbound",
        json=_signed(
            {"cmd_no": "DLV26010100001-R1", "lines": [{"sku_code": "A", "num": 1}]}
        ),
    )
    assert r2.json()["code"] == "wms.system-busy"

    # 次数用尽 → 恢复正常
    r3 = client.post(
        "/wms/restful/outbound",
        json=_signed(
            {"cmd_no": "DLV26010100001-R1", "lines": [{"sku_code": "A", "num": 1}]}
        ),
    )
    assert r3.json()["code"] == 0


def test_inject_unknown_error_rejected():
    """未支持的注入码 → FATAL"""
    r = client.post(
        "/sim/inject", json={"cmd_no": "X-R1", "error": "NOT_EXIST", "times": 1}
    )
    assert r.json()["code"] == "wms.unknown-error"


def test_inject_requires_cmd_no():
    """cmd_no 必填"""
    r = client.post("/sim/inject", json={"cmd_no": "", "error": "TIMEOUT"})
    assert r.json()["code"] == "wms.invalid-payload"
