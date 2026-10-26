"""订单修改与改地址测试（W8-3 · SRS-D03.08 最小子集）

覆盖：
- FR-01a 改单入口 + 并发互斥（同订单已有进行中改单 → 拒绝）
- FR-01c 前置状态校验（已发货/已完成/已取消 → 拒绝，提示走售后）
- FR-02a 快照（订单主档/行/收货人；收货人保持密文，不落明文）
- FR-03b 纯地址改单不动库存（无发货单 → 直接生效）
- FR-05a 字段级差异对比
- FR-06a/06c 叫回（有发货单 → 置 recalling；叫回成功 → 生效；失败 → 挂起 + 落异常单）
"""
from __future__ import annotations

import time

import pytest
from sqlalchemy import select, text

from app.core.db import AuthContext, SessionFactory, engine, set_auth_context
from app.core.exceptions import ConflictError, NotFoundError
from app.models.modify import OrdOrderModify, OrdOrderSnapshot
from app.models.order import OrdReceiver
from app.services.modify import (
    MODIFY_STATUS_CANCELLED,
    MODIFY_STATUS_EFFECTIVE,
    MODIFY_STATUS_RECALLING,
    MODIFY_STATUS_SUSPENDED,
    ModifyService,
)

pytestmark = pytest.mark.asyncio


def _uid() -> str:
    return f"{time.time_ns() % 100000000:08d}"


@pytest.fixture(autouse=True)
async def _ctx():
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    yield


async def _mk_order(
    order_status: str = "processing",
    ship_status: str = "unshipped",
    with_delivery: bool = False,
) -> int:
    """造订单（含可选的发货单，用于触发叫回）"""
    order_bn = f"MOD{_uid()}"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_order "
                "(tenant_id, owner_id, order_bn, platform_order_bn, shop_id, brand_id, "
                " createway, order_type, order_status, audit_status, fulfill_status, "
                " pay_status, ship_status, list_amount, shop_discount, platform_subsidy, "
                " paid_amount, freight, is_cod, order_time, pay_time, create_time, "
                " update_time, version, is_deleted) "
                "VALUES (1, 1, :obn, :pon, 0, 0, 'platform', 'normal', :ost, 'passed', "
                "'pending', 'paid', :sst, 100, 0, 0, 100, 0, 0, NOW(3), NOW(3), "
                "NOW(3), NOW(3), 0, 0)"
            ),
            {
                "obn": order_bn,
                "pon": f"MODSIM_{_uid()}",
                "ost": order_status,
                "sst": ship_status,
            },
        )
        oid = int(
            (
                await conn.execute(
                    text("SELECT id FROM oms_order.ord_order WHERE order_bn = :obn"),
                    {"obn": order_bn},
                )
            ).scalar()
            or 0
        )
        # 收货人（密文字段）
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_receiver "
                "(tenant_id, owner_id, order_id, name_enc, name_hash, mobile_enc, "
                " mobile_hash, mobile_tail4, province, city, district, town, "
                " address_enc, address_hash, is_cipher, create_time, update_time, "
                " version, is_deleted) "
                "VALUES (1, 1, :oid, :ne, 'nh', :me, 'mh', '0000', "
                "'广东省', '深圳市', '南山区', '', :ae, 'ah', 0, NOW(3), NOW(3), 0, 0)"
            ),
            {
                "oid": oid,
                "ne": b"ENC_NAME_BYTES",
                "me": b"ENC_MOBILE_BYTES",
                "ae": b"ENC_ADDR_BYTES",
            },
        )
        if with_delivery:
            await conn.execute(
                text(
                    "INSERT INTO oms_order.ord_delivery "
                    "(tenant_id, owner_id, delivery_bn, order_id, shop_id, "
                    " branch_id, status, sync_status, create_time, update_time, version, "
                    " is_deleted) "
                    "VALUES (1, 1, :dbn, :oid, 0, 0, 'created', 'init', NOW(3), "
                    "NOW(3), 0, 0)"
                ),
                {"dbn": f"MODDLV{_uid()}", "oid": oid},
            )
    return oid


async def _clean(order_ids: list[int]) -> None:
    if not order_ids:
        return
    lst = ",".join(str(i) for i in order_ids)
    async with engine.begin() as conn:
        await conn.execute(
            text(f"DELETE FROM oms_order.ord_abnormal WHERE order_id IN ({lst})")
        )
        await conn.execute(
            text(f"DELETE FROM oms_order.ord_order_modify WHERE order_id IN ({lst})")
        )
        await conn.execute(
            text(f"DELETE FROM oms_order.ord_order_snapshot WHERE order_id IN ({lst})")
        )
        await conn.execute(
            text(f"DELETE FROM oms_order.ord_delivery WHERE order_id IN ({lst})")
        )
        await conn.execute(
            text(f"DELETE FROM oms_order.ord_receiver WHERE order_id IN ({lst})")
        )
        await conn.execute(text(f"DELETE FROM oms_order.ord_order WHERE id IN ({lst})"))


# ============ FR-01a/01c 入口与前置校验 ============


async def test_address_modify_without_delivery_effective_directly():
    """FR-03b：无发货单 → 纯地址改单直接生效（不动库存）"""
    oid = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = ModifyService(s, None)
            res = await svc.create_address_modify(
                oid,
                province="浙江省",
                city="杭州市",
                district="西湖区",
                town="文一西路",
                address_enc=b"NEW_ADDR_ENC",
                operator="tester",
            )
        assert res["ok"] is True
        assert res["need_recall"] is False
        assert res["effective"] is True
        assert res["status"] == MODIFY_STATUS_EFFECTIVE
        async with SessionFactory() as s:
            rcv = await s.scalar(
                select(OrdReceiver).where(OrdReceiver.order_id == oid)
            )
        assert rcv is not None
        assert rcv.province == "浙江省"
        assert rcv.district == "西湖区"
        assert rcv.address_enc == b"NEW_ADDR_ENC"
    finally:
        await _clean([oid])


async def test_address_modify_rejects_shipped_order():
    """FR-01c：已发货订单拒绝改单（提示走售后）"""
    oid = await _mk_order(order_status="shipped", ship_status="shipped")
    try:
        async with SessionFactory() as s:
            svc = ModifyService(s, None)
            with pytest.raises(ConflictError) as e:
                await svc.create_address_modify(oid, province="浙江省", operator="tester")
        assert "售后" in str(e.value)
    finally:
        await _clean([oid])


async def test_address_modify_rejects_cancelled_order():
    """FR-01c：已取消订单拒绝改单"""
    oid = await _mk_order(order_status="cancelled")
    try:
        async with SessionFactory() as s:
            svc = ModifyService(s, None)
            with pytest.raises(ConflictError):
                await svc.create_address_modify(oid, province="浙江省", operator="tester")
    finally:
        await _clean([oid])


async def test_concurrent_modify_blocked():
    """FR-01a：同订单已有进行中改单 → 拒绝第二张（并发互斥）"""
    oid = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = ModifyService(s, None)
            await svc.create_address_modify(
                oid, province="浙江省", operator="tester"
            )
            # 第一张已 effective（状态不在进行中集合）→ 可再发起
            # 手动造一张 recalling 的进行中改单
            mod = await s.scalar(
                select(OrdOrderModify).where(OrdOrderModify.order_id == oid)
            )
            assert mod is not None
            mod.status = MODIFY_STATUS_RECALLING
            await s.commit()
            with pytest.raises(ConflictError) as e:
                await svc.create_address_modify(
                    oid, province="江苏省", operator="tester"
                )
        assert "进行中" in str(e.value)
    finally:
        await _clean([oid])


async def test_modify_order_not_found():
    """边界：订单不存在 → 404"""
    async with SessionFactory() as s:
        svc = ModifyService(s, None)
        with pytest.raises(NotFoundError):
            await svc.create_address_modify(99999999, province="浙江省")


# ============ FR-02a 快照 ============


async def test_snapshot_created_with_receiver_cipher():
    """FR-02a：快照落库；收货人快照保持**密文**（不落明文）"""
    oid = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = ModifyService(s, None)
            res = await svc.create_address_modify(
                oid, province="浙江省", operator="tester"
            )
            snap = await s.scalar(
                select(OrdOrderSnapshot).where(
                    OrdOrderSnapshot.id == int(res["modify_id"]) and False
                )
            ) if False else await s.scalar(
                select(OrdOrderSnapshot).where(OrdOrderSnapshot.order_id == oid)
            )
        assert snap is not None
        assert snap.snap_order is not None
        assert snap.snap_receiver is not None
        # 密文存 hex，不是明文
        assert snap.snap_receiver["name_enc"] == b"ENC_NAME_BYTES".hex()
        assert snap.snap_receiver["address_enc"] == b"ENC_ADDR_BYTES".hex()
        assert "ENC_NAME_BYTES" not in str(snap.snap_receiver)
    finally:
        await _clean([oid])


async def test_snapshot_records_order_and_items():
    """FR-02a：快照含订单主档与行"""
    oid = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = ModifyService(s, None)
            await svc.create_address_modify(oid, province="浙江省", operator="tester")
            snap = await s.scalar(
                select(OrdOrderSnapshot).where(OrdOrderSnapshot.order_id == oid)
            )
        assert snap is not None
        assert snap.snap_order["order_status"] == "processing"
        assert float(snap.snap_order["paid_amount"]) == 100.0
        assert isinstance(snap.snap_items, list)
    finally:
        await _clean([oid])


# ============ FR-05a 差异对比 ============


async def test_diff_summary_lists_changed_fields():
    """FR-05a：字段级差异（旧值/新值/变更字段）"""
    oid = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = ModifyService(s, None)
            res = await svc.create_address_modify(
                oid,
                province="浙江省",
                city="杭州市",
                district="西湖区",
                address_enc=b"NEW_ADDR_ENC",
                operator="tester",
            )
        diff = res["diff"]
        assert diff["has_diff"] is True
        assert "province" in diff["changed_fields"]
        assert "district" in diff["changed_fields"]
        assert "city" in diff["changed_fields"]
        assert diff["old"]["province"] == "广东省"
        assert diff["new"]["province"] == "浙江省"
    finally:
        await _clean([oid])


async def test_diff_no_change_when_same_address():
    """FR-05a：地址无变化 → has_diff=False"""
    oid = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = ModifyService(s, None)
            res = await svc.create_address_modify(
                oid,
                province="广东省",
                city="深圳市",
                district="南山区",
                address_enc=b"ENC_ADDR_BYTES",
                operator="tester",
            )
        assert res["diff"]["has_diff"] is False
        assert res["diff"]["changed_fields"] == []
    finally:
        await _clean([oid])


# ============ FR-06a/06c 叫回 ============


async def test_address_modify_with_delivery_requires_recall():
    """FR-06a：有发货单 → 需叫回（改单置 recalling，不直接生效）"""
    oid = await _mk_order(with_delivery=True)
    try:
        async with SessionFactory() as s:
            svc = ModifyService(s, None)
            res = await svc.create_address_modify(
                oid, province="浙江省", operator="tester"
            )
        assert res["need_recall"] is True
        assert res["effective"] is False
        # 叫回失败（WMS 未绑定）→ 改单挂起
        assert res["status"] in (MODIFY_STATUS_RECALLING, MODIFY_STATUS_SUSPENDED)
        async with SessionFactory() as s:
            rcv = await s.scalar(
                select(OrdReceiver).where(OrdReceiver.order_id == oid)
            )
        # 叫回未成功 → 地址不应被改
        assert rcv is not None
        assert rcv.province == "广东省"
    finally:
        await _clean([oid])


async def test_recall_failure_suspends_and_raises_abnormal():
    """FR-06c：叫回失败 → 改单挂起 + 落异常单（人工跟进）"""
    oid = await _mk_order(with_delivery=True)
    try:
        async with SessionFactory() as s:
            svc = ModifyService(s, None)
            res = await svc.create_address_modify(
                oid, province="浙江省", operator="tester"
            )
        # 无 WMS 绑定 → 叫回必然失败
        assert res["status"] == MODIFY_STATUS_SUSPENDED
        assert res["recall_result"]["all_ok"] is False
        async with SessionFactory() as s:
            cnt = await s.scalar(
                text(
                    "SELECT COUNT(*) FROM oms_order.ord_abnormal "
                    "WHERE order_id = :o AND exc_type = 'RECALL_FAILED'"
                ),
                {"o": oid},
            )
        assert int(cnt or 0) == 1
    finally:
        await _clean([oid])


async def test_cancel_modify_after_recall_failure():
    """FR-06c：叫回失败后的人工决策 —— 撤销改单恢复现场"""
    oid = await _mk_order(with_delivery=True)
    try:
        async with SessionFactory() as s:
            svc = ModifyService(s, None)
            res = await svc.create_address_modify(
                oid, province="浙江省", operator="tester"
            )
            assert res["status"] == MODIFY_STATUS_SUSPENDED
            cancel = await svc.cancel_recall_modify(
                int(res["modify_id"]), operator="tester", reason="放弃改地址"
            )
        assert cancel["status"] == MODIFY_STATUS_CANCELLED
        async with SessionFactory() as s:
            rcv = await s.scalar(
                select(OrdReceiver).where(OrdReceiver.order_id == oid)
            )
        # 撤销 → 地址保持原值（现场恢复）
        assert rcv is not None
        assert rcv.province == "广东省"
    finally:
        await _clean([oid])


async def test_recall_complete_requires_recalling_status():
    """FR-06c：非叫回中状态 → 拒绝触发完成"""
    oid = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = ModifyService(s, None)
            res = await svc.create_address_modify(
                oid, province="浙江省", operator="tester"
            )
            with pytest.raises(ConflictError):
                await svc.complete_recall_and_effective(
                    int(res["modify_id"]), operator="tester"
                )
    finally:
        await _clean([oid])


# ============ 查询 ============


async def test_list_and_detail_modify():
    """改单列表与详情（含快照与 Saga 日志）"""
    oid = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = ModifyService(s, None)
            res = await svc.create_address_modify(
                oid, province="浙江省", operator="tester"
            )
            items = await svc.list_modifies(order_id=oid)
            detail = await svc.get_modify(int(res["modify_id"]))
        assert len(items) == 1
        assert items[0]["modify_type"] == "address"
        # ⚠ 文案以 **DDL 为权威**（oms_order.ord_order_modify.modify_type = '地址'）
        #   原先代码手抄的 "修改地址" 是漂移 —— P0 契约化后统一取 DDL 值
        assert items[0]["modify_type_name"] == "地址"
        assert detail["snapshot"] is not None
        assert detail["snapshot"]["snap_receiver"]["province"] == "广东省"
        assert isinstance(detail["saga_log"], list)
    finally:
        await _clean([oid])


async def test_modify_saga_log_records_effective_stage():
    """Saga 日志记录生效阶段（可追溯）"""
    oid = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = ModifyService(s, None)
            res = await svc.create_address_modify(
                oid, province="浙江省", operator="tester"
            )
            detail = await svc.get_modify(int(res["modify_id"]))
        stages = [x.get("stage") for x in (detail["saga_log"] or [])]
        assert "effective" in stages
    finally:
        await _clean([oid])
