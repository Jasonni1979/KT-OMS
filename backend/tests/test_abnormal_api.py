"""异常单 API 测试（W8 · SRS-D03.09 FR-02c/02d/02f/03d）

覆盖端点：
- GET  /abnormal/types         类型字典
- GET  /abnormal/reason-codes   原因码字典（含 exc_type 映射）
- GET  /abnormal/list           列表（多维过滤 + 分页）
- GET  /abnormal/{id}           详情（缺货明细 + 时间线 + SLA）
- GET  /abnormal/stockouts      缺货明细列表
- POST /abnormal                人工标记（FR-03d）
- POST /abnormal/{id}/dispatch  分派
- POST /abnormal/{id}/process   开始处理
- POST /abnormal/{id}/suspend   挂起（须填预计恢复时间）
- POST /abnormal/{id}/resolve   解决
- POST /abnormal/{id}/cancel    取消
"""
from __future__ import annotations

import time

import pytest

from app.core.db import AuthContext, SessionFactory, engine, set_auth_context
from app.models.abnormal import (
    ABNORMAL_STATUS_ASSIGNED,
    ABNORMAL_STATUS_CANCELLED,
    ABNORMAL_STATUS_RESOLVED,
    ABNORMAL_STATUS_WAIT_DISPATCH,
)
from app.models.order import OrdOrder
from app.modules.m5_abnormal.service.abnormal import EXC_PRODUCT_UNBOUND, EXC_STOCK_SHORT, AbnormalService

pytestmark = pytest.mark.asyncio


def _uid() -> str:
    return f"{time.time_ns() % 100000000:08d}"


@pytest.fixture(autouse=True)
async def _ctx():
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    yield


async def _mk_order() -> int:
    order_bn = f"ABNA{_uid()}"
    async with engine.begin() as conn:
        await conn.execute(
            __import__("sqlalchemy").text(
                "INSERT INTO oms_order.ord_order "
                "(tenant_id, owner_id, order_bn, platform_order_bn, shop_id, brand_id, "
                " createway, order_type, order_status, audit_status, fulfill_status, "
                " pay_status, ship_status, list_amount, shop_discount, platform_subsidy, "
                " paid_amount, freight, is_cod, order_time, pay_time, create_time, "
                " update_time, version, is_deleted) "
                "VALUES (1, 1, :obn, :pon, 0, 0, 'platform', 'normal', "
                "'processing', 'pending', 'pending', 'paid', 'unshipped', "
                "100, 0, 0, 100, 0, 0, NOW(3), NOW(3), NOW(3), NOW(3), 0, 0)"
            ),
            {"obn": order_bn, "pon": f"SIM_ABNA_{_uid()}"},
        )
        r = await conn.execute(
            __import__("sqlalchemy").text(
                "SELECT id FROM oms_order.ord_order WHERE order_bn = :obn"
            ),
            {"obn": order_bn},
        )
        return int(r.scalar())


async def _clean(order_ids: list[int]) -> None:
    if not order_ids:
        return
    async with engine.begin() as conn:
        from sqlalchemy import text

        for sql in (
            "DELETE FROM oms_order.ord_stockout WHERE order_id IN :ids",
            "DELETE FROM oms_order.ord_abnormal WHERE order_id IN :ids",
            "DELETE FROM oms_order.ord_order WHERE id IN :ids",
        ):
            await conn.execute(text(sql), {"ids": order_ids})


async def _mk_abnormal(order_id: int, exc_type: str = EXC_PRODUCT_UNBOUND) -> int:
    async with SessionFactory() as s:
        order = await s.scalar(
            __import__("sqlalchemy").select(OrdOrder).where(OrdOrder.id == order_id)
        )
        svc = AbnormalService(s, None)
        row, _ = await svc.create(order=order, exc_type=exc_type, source="manual")
        return int(row.id)


# ============ 字典 ============


async def test_types_endpoint(auth_client):
    """类型字典端点：返回内置类型（含 SLA / 动作集 / 是否落单）"""
    r = await auth_client.get("/api/v1/abnormal/types")
    assert r.status_code == 200, r.text
    items = r.json()["data"]["items"]
    assert len(items) >= 16
    codes = {i["type_code"] for i in items}
    assert EXC_PRODUCT_UNBOUND in codes
    assert EXC_STOCK_SHORT in codes
    one = next(i for i in items if i["type_code"] == EXC_PRODUCT_UNBOUND)
    assert one["default_sla_hours"] > 0
    assert isinstance(one["action_set"], list)


async def test_reason_codes_endpoint(auth_client):
    """原因码字典端点：带 exc_type 映射"""
    r = await auth_client.get("/api/v1/abnormal/reason-codes")
    assert r.status_code == 200, r.text
    items = r.json()["data"]["items"]
    assert len(items) >= 20
    hit = next(i for i in items if i["reason_code"] == "GOODS_UNBOUND")
    assert hit["exc_type"] == EXC_PRODUCT_UNBOUND
    assert hit["default_route"]


# ============ 列表 / 详情 ============


async def test_list_and_detail(auth_client):
    """FR-02f：列表 + 详情（含时间线与 SLA）"""
    order_id = await _mk_order()
    try:
        abn_id = await _mk_abnormal(order_id)
        r = await auth_client.get("/api/v1/abnormal/list")
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["total"] >= 1
        row = next(i for i in data["items"] if i["id"] == abn_id)
        assert row["status"] == ABNORMAL_STATUS_WAIT_DISPATCH
        assert "sla" in row and "remain_hours" in row["sla"]

        d = await auth_client.get(f"/api/v1/abnormal/{abn_id}")
        assert d.status_code == 200, d.text
        det = d.json()["data"]
        assert det["id"] == abn_id
        assert det["order_id"] == order_id
        assert isinstance(det["timeline"], list) and det["timeline"]
        assert isinstance(det["stockouts"], list)
    finally:
        await _clean([order_id])


async def test_list_filter_by_type(auth_client):
    """FR-02f：按异常类型过滤"""
    order_id = await _mk_order()
    try:
        abn_id = await _mk_abnormal(order_id, EXC_STOCK_SHORT)
        r = await auth_client.get(
            "/api/v1/abnormal/list", params={"exc_type": EXC_STOCK_SHORT}
        )
        assert r.status_code == 200, r.text
        ids = [i["id"] for i in r.json()["data"]["items"]]
        assert abn_id in ids
    finally:
        await _clean([order_id])


async def test_stockouts_endpoint(auth_client):
    """缺货明细列表端点"""
    order_id = await _mk_order()
    try:
        abn_id = await _mk_abnormal(order_id, EXC_STOCK_SHORT)
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            await svc.mark_stockout(
                await svc.get(abn_id),
                [{"branch_id": 3, "bm_id": 4, "lack_num": 2}],
            )
        r = await auth_client.get(
            "/api/v1/abnormal/stockouts", params={"abnormal_id": abn_id}
        )
        assert r.status_code == 200, r.text
        items = r.json()["data"]["items"]
        assert len(items) == 1
        assert items[0]["lack_num"] == 2
    finally:
        await _clean([order_id])


# ============ 人工标记（FR-03d）============


async def test_manual_create_requires_note(auth_client):
    """FR-03d：人工标记的备注必填"""
    order_id = await _mk_order()
    try:
        r = await auth_client.post(
            "/api/v1/abnormal",
            json={"order_id": order_id, "exc_type": EXC_PRODUCT_UNBOUND, "note": ""},
        )
        assert r.status_code == 422, r.text
    finally:
        await _clean([order_id])


async def test_manual_create_and_workflow(auth_client):
    """FR-03d 人工标记 → 分派 → 处理 → 解决 全链路"""
    order_id = await _mk_order()
    try:
        r = await auth_client.post(
            "/api/v1/abnormal",
            json={
                "order_id": order_id,
                "exc_type": EXC_PRODUCT_UNBOUND,
                "note": "人工标记：商品映射待确认",
            },
        )
        assert r.status_code == 200, r.text
        abn_id = int(r.json()["data"]["id"])

        r2 = await auth_client.post(
            f"/api/v1/abnormal/{abn_id}/dispatch",
            json={"group_id": 2, "op_id": 5, "note": "派给商品组"},
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["data"]["status"] == ABNORMAL_STATUS_ASSIGNED

        r3 = await auth_client.post(f"/api/v1/abnormal/{abn_id}/process")
        assert r3.status_code == 200, r3.text

        r4 = await auth_client.post(
            f"/api/v1/abnormal/{abn_id}/resolve",
            json={"action": "reaudit", "note": "已绑定商品，重新审单"},
        )
        assert r4.status_code == 200, r4.text
        assert r4.json()["data"]["status"] == ABNORMAL_STATUS_RESOLVED
    finally:
        await _clean([order_id])


async def test_suspend_requires_recover_time(auth_client):
    """FR-02d：挂起必须填预计恢复时间（>0）"""
    order_id = await _mk_order()
    try:
        abn_id = await _mk_abnormal(order_id)
        r = await auth_client.post(
            f"/api/v1/abnormal/{abn_id}/suspend", json={"until_hours": 0}
        )
        assert r.status_code == 422, r.text
    finally:
        await _clean([order_id])


async def test_cancel_endpoint(auth_client):
    """取消异常单 → 已取消"""
    order_id = await _mk_order()
    try:
        abn_id = await _mk_abnormal(order_id)
        r = await auth_client.post(
            f"/api/v1/abnormal/{abn_id}/cancel", json={"note": "订单取消收口"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["data"]["status"] == ABNORMAL_STATUS_CANCELLED
    finally:
        await _clean([order_id])
