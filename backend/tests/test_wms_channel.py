"""W7 履约通道测试（D09.01 路由 + D09.02 出库指令通道 + D02.04 回传 + D02.05 重试）

覆盖：
- D09.01 FR-04a 路由四元组
- D09.02 FR-01 指令下发（组装 / 幂等 / 报文映射）
- D09.02 §5.4 错误分类（RETRYABLE / FATAL / BIZ_REJECT）
- D09.02 §5.2 幂等键体系
- D09.02 FR-03a 回传标准化（物料编码 → bm_id）
- D02.04 发货回传（组装 / 台账 / 幂等）
- D02.01 FR-06c 统一错误分级五级
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.adapters.wms import (
    ERR_CLASS_MAP,
    QimenAdapter,
    TtxRestAdapter,
    WmsRoute,
    classify,
    get_adapter,
    sign_payload,
)
from app.modules.m7_integration.service.wms_channel import (
    BACKOFF_MINUTES,
    CMD_ACCEPTED,
    CMD_COMPLETED,
    CMD_PARTIAL,
    CMD_SENT,
    ERR_BIZ_REJECT,
    ERR_FATAL,
    ERR_RETRYABLE,
    EVENT_CALLBACK,
    EVENT_PUSHED,
    MAX_RETRY,
    OutboundCommandService,
    _delivery_bn_of,
)
from app.modules.m7_integration.service.writeback import (
    ACTION_DELIVERY_SEND,
    LEVEL_AUTH,
    LEVEL_FATAL,
    LEVEL_MANUAL,
    LEVEL_RATE_LIMITED,
    LEVEL_RETRYABLE,
    WritebackService,
)
from app.scripts.wms_channel_e2e import _make_delivery

# ============ D09.01 路由四元组 ============


def test_route_dataclass_shape():
    """FR-04a 路由四元组结构（wms_id / adapter / 账号 / wms_branch_code）"""
    r = WmsRoute(
        wms_id=1,
        binding_id=2,
        adapter_code="ttx-adapter",
        app_key="k",
        secret="s",
        wms_branch_code="WH-01",
        wms_owner_code="OWNER-1",
        endpoint="http://x",
    )
    d = r.to_dict()
    assert d["wms_id"] == 1
    assert d["adapter_code"] == "ttx-adapter"
    assert d["wms_branch_code"] == "WH-01"
    assert d["wms_owner_code"] == "OWNER-1"
    assert d["degraded"] == ""


# ============ D09.02 指令组装与报文映射 ============


def test_adapter_registry():
    """D09.01 协议适配器注册机制（按 adapter_code 取实例）"""
    assert get_adapter("ttx-adapter") is not None
    assert get_adapter("qimen-adapter") is not None
    assert get_adapter("not-exist") is None


def test_ttx_payload_mapping():
    """通天晓报文映射：仓编码取自路由（非指令）"""
    route = WmsRoute(
        wms_id=1, binding_id=1, adapter_code="ttx-adapter",
        wms_branch_code="TTX-HD01", wms_owner_code="KC",
    )
    dto = {
        "cmd_no": "DLV1-R1",
        "waybill_no": "SF123",
        "lines": [{"sku_code": "BM1", "num": 2}],
        "remark": "测试",
    }
    payload = TtxRestAdapter().build_payload(dto, route)
    assert payload["warehouse_code"] == "TTX-HD01"
    assert payload["owner_code"] == "KC"
    assert payload["cmd_no"] == "DLV1-R1"
    assert payload["lines"][0]["num"] == 2


def test_qimen_payload_mapping():
    """奇门报文映射（与 RESTful 同构，差异在路径）"""
    route = WmsRoute(
        wms_id=1, binding_id=1, adapter_code="qimen-adapter",
        wms_branch_code="QIMEN-01", wms_owner_code="",
    )
    dto = {"cmd_no": "DLV2-R1", "lines": [{"sku_code": "BM2", "num": 1}]}
    payload = QimenAdapter().build_payload(dto, route)
    assert payload["warehouse_code"] == "QIMEN-01"
    assert payload["cmd_no"] == "DLV2-R1"


def test_sign_payload_stable():
    """通道签名稳定（同参数同结果，排序拼接）"""
    a = sign_payload({"b": 2, "a": 1}, "secret")
    b = sign_payload({"a": 1, "b": 2}, "secret")
    assert a == b
    assert a == sign_payload({"a": 1, "b": 2, "sign": "x"}, "secret")


# ============ D09.02 §5.4 错误分类 ============


def test_error_classification():
    """D09.02 §5.4：RETRYABLE / FATAL / BIZ_REJECT 三类"""
    assert classify("wms.timeout") == ERR_RETRYABLE
    assert classify("wms.system-busy") == ERR_RETRYABLE
    assert classify("wms.invalid-payload") == ERR_FATAL
    assert classify("wms.no-permission") == ERR_FATAL
    assert classify("wms.business-reject") == ERR_BIZ_REJECT
    # 未知错误码默认按可重试（保守重试）
    assert classify("wms.unknown-thing") == ERR_RETRYABLE


def test_error_class_map_covers_all():
    """错误码字典覆盖三类"""
    classes = set(ERR_CLASS_MAP.values())
    assert {ERR_RETRYABLE, ERR_FATAL, ERR_BIZ_REJECT} <= classes


# ============ D09.02 §5.2 幂等键体系 ============


def test_delivery_bn_of_cmd_no():
    """下发单号解析（DLV...-R1 → DLV...；叫回 -C1 同理）"""
    assert _delivery_bn_of("DLV26010100001-R1") == "DLV26010100001"
    assert _delivery_bn_of("DLV26010100001-C1") == "DLV26010100001"
    assert _delivery_bn_of("DLV26010100001") == "DLV26010100001"


def test_backoff_sequence_and_max_retry():
    """分级退避序列（D02.05 同款 1/5/15/60min）与重试上限"""
    assert BACKOFF_MINUTES == (1, 5, 15, 60)
    assert MAX_RETRY == 5


# ============ D02.01 错误分级五级 ============


def test_platform_error_levels():
    """D02.01 FR-06c 统一错误分级字典（五级）"""
    cls = WritebackService._classify
    assert cls("isv.trade-service-error") == LEVEL_RETRYABLE
    assert cls("flow-limit") == LEVEL_RATE_LIMITED
    assert cls("isv.session-expired") == LEVEL_AUTH
    assert cls("isv.trade-not-exist") == LEVEL_MANUAL
    assert cls("isv.invalid-signature") == LEVEL_FATAL
    # 未知 → 可重试
    assert cls("whatever") == LEVEL_RETRYABLE


def test_writeback_action_name():
    """平台动作名（统一方法名 → 适配器映射）"""
    assert ACTION_DELIVERY_SEND == "taobao.logistics.online.send"


# ============ D09.02 回传标准化 ============


async def test_standardize_lines_maps_material_code():
    """FR-03a 解析标准化：WMS 物料编码 → OMS bm_id"""
    from app.core.db import SessionFactory
    from app.modules.m7_integration.service.wms_channel import OutboundCommandService

    async with SessionFactory() as s:
        svc = OutboundCommandService(s, None)  # type: ignore[arg-type]
        row = await s.execute(
            text(
                "SELECT material_bn, id FROM oms_stock.inv_material "
                "WHERE is_deleted = 0 ORDER BY id LIMIT 1"
            )
        )
        r = row.mappings().first()
        if not r:
            pytest.skip("无物料数据")
        code = str(r["material_bn"])
        bm_id = int(r["id"])
        out = await svc._standardize_lines(
            [{"sku_code": code, "num": 2}, {"sku_code": "NOPE", "num": 1}]
        )
        assert out[0]["bm_id"] == bm_id
        assert out[0]["sku_code"] == code
        # 映射缺失 → bm_id=0（由编排层登记差异人工处理）
        assert out[1]["bm_id"] == 0


# ============ 事件名常量 ============


def test_event_names():
    """标准化事件名（FR-03e）"""
    assert EVENT_PUSHED == "wms.outbound.pushed"
    assert EVENT_CALLBACK == "wms.outbound.callback"


def test_cmd_status_constants():
    """通道侧状态机投影（§4.2）"""
    assert CMD_ACCEPTED == "accepted"
    assert CMD_SENT == "sent"


# ============ §4.2 通道侧状态投影：回传闭环 vs 部分回传 ============


def test_cmd_status_projection_constants():
    """§4.2 状态枚举：回传闭环 / 部分回传"""
    assert CMD_COMPLETED == "completed"
    assert CMD_PARTIAL == "partial"
    assert CMD_ACCEPTED == "accepted"
    assert CMD_SENT == "sent"


async def test_outbound_cmd_status_closed_when_fulfilled(auth_client):
    """累计回传量 ≥ 指令量 → 回传闭环（completed）

    口径：发货单行 Σnum vs 已登记出库回传 Σ实发量。
    """
    from app.core.db import AuthContext, SessionFactory, set_auth_context

    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    async with SessionFactory() as s:
        # 复用 W7 E2E 自造环境（仓 + 物料 + 库存 + WMS 绑定）
        from app.scripts.wms_channel_e2e import _ensure_wms_env

        branch_id, owner_id, bm_id = await _ensure_wms_env(s)
        did = await _make_delivery(s, branch_id, owner_id, bm_id)
        # 该单 1 行 num=2 → 指令量 2
        instruct = int(
            await s.scalar(
                text(
                    "SELECT COALESCE(SUM(num), 0) FROM oms_order.ord_delivery_item "
                    "WHERE delivery_id = :d"
                ),
                {"d": did},
            )
            or 0
        )
        assert instruct == 2

        svc = OutboundCommandService(s, None)  # type: ignore[arg-type]
        # 未回传 → 部分回传
        st1 = await svc._outbound_cmd_status(0, did)
        assert st1 == CMD_PARTIAL

        # 登记一条实发 2 件的出库回传 → 齐套 → 回传闭环
        await s.execute(
            text(
                "INSERT INTO oms_fulfill.ful_outbound_callback "
                "(tenant_id, delivery_id, callback_type, wms_batch_no, idempotent_key, "
                " lines_json, packages_json, process_status, receive_time, "
                " create_time, update_time, version) "
                "VALUES (1, :d, 'outbound', :b, :k, :lj, '[]', 'registered', NOW(3), "
                " NOW(3), NOW(3), 0)"
            ),
            {
                "d": did,
                "b": f"W7CLOSED{did}",
                "k": f"W7CLOSED{did}:outbound",
                "lj": '[{"bm_id": 0, "num": 2}]',
            },
        )
        await s.commit()
        st2 = await svc._outbound_cmd_status(0, did)
        assert st2 == CMD_COMPLETED

        # 清理
        await s.execute(
            text(
                "DELETE FROM oms_fulfill.ful_outbound_callback "
                "WHERE idempotent_key = :k"
            ),
            {"k": f"W7CLOSED{did}:outbound"},
        )
        await s.execute(
            text("DELETE FROM oms_order.ord_delivery_item WHERE delivery_id = :d"),
            {"d": did},
        )
        await s.execute(
            text("DELETE FROM oms_order.ord_delivery WHERE id = :d"), {"d": did}
        )
        await s.commit()


async def test_delivery_detail_has_channel_trace(auth_client):
    """发货单详情含 WMS 通道轨迹（指令 / 回传 / 通道日志 / 失败台账）"""
    from app.core.db import AuthContext, SessionFactory, set_auth_context

    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    async with SessionFactory() as s:
        from app.scripts.wms_channel_e2e import _ensure_wms_env

        branch_id, owner_id, bm_id = await _ensure_wms_env(s)
        did = await _make_delivery(s, branch_id, owner_id, bm_id)
        await s.execute(
            text(
                "INSERT INTO oms_fulfill.ful_outbound_cmd "
                "(tenant_id, owner_id, branch_id, cmd_bn, delivery_id, delivery_bn, "
                " push_round, wms_id, binding_id, adapter_code, cmd_type, status, "
                " wms_bill_no, source, idempotent_key, "
                " create_time, update_time, version) "
                "VALUES (1, :o, :b, :bn, :d, :dbn, 1, "
                " (SELECT id FROM oms_fulfill.ful_wms WHERE is_deleted = 0 LIMIT 1), "
                " (SELECT id FROM oms_fulfill.ful_wms_binding WHERE is_deleted = 0 LIMIT 1), "
                " 'ttx-adapter', 'push', 'sent', 'WMS-TEST', "
                " 'local', :ik, NOW(3), NOW(3), 0)"
            ),
            {
                "o": owner_id,
                "b": branch_id,
                "bn": f"CMDTRACE{did}-1",
                "d": did,
                "dbn": f"DLVTRACE{did}",
                "ik": f"trace:{did}",
            },
        )
        await s.commit()

    r = await auth_client.get(f"/api/v1/delivery/{did}")
    assert r.status_code == 200
    data = r.json()["data"]
    ch = data["channel"]
    assert ch["available"] is True
    assert len(ch["cmds"]) == 1
    assert ch["cmds"][0]["cmd_bn"] == f"CMDTRACE{did}-1"
    assert ch["cmds"][0]["status"] == "sent"
    # 无回传/无日志/无失败 → 空数组而非报错
    assert ch["callbacks"] == []
    assert ch["logs"] == []
    assert ch["fails"] == []

    async with SessionFactory() as s:
        await s.execute(
            text("DELETE FROM oms_fulfill.ful_outbound_cmd WHERE idempotent_key = :ik"),
            {"ik": f"trace:{did}"},
        )
        await s.execute(
            text("DELETE FROM oms_order.ord_delivery_item WHERE delivery_id = :d"),
            {"d": did},
        )
        await s.execute(
            text("DELETE FROM oms_order.ord_delivery WHERE id = :d"), {"d": did}
        )
        await s.commit()
