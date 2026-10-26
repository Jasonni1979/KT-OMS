"""异常单域测试（W8 · SRS-D03.09 异常单与缺货处理）

覆盖：
- FR-01a/01b   内置异常类型字典（DDL 预置 16 种）+ 默认处理组 + SLA
- FR-01c       原因码 → 异常类型映射（权威源 ord_reason_code_dict.exc_type）+ 兜底
- FR-02a       创建（幂等：同订单同类型未闭环 → 复用）
- FR-02b       状态机（合法流转 / 非法流转拒绝 / 时间线留痕）
- FR-02c       分派（待分派 → 已分派；非待分派拒绝）
- FR-02d       处理动作（开始处理 / 挂起必须填预计恢复时间 / 解决 / 取消）
- FR-02e       闭环联动（解除订单审单原因标记；多异常单全部闭环才解除）
- FR-04a       缺货标记（三元键明细；多次预占失败按明细合并累加）
- FR-05a       超卖标记
- SLA 计时（UTC 基准，与 DB 的 DATETIME 同基准）
"""
from __future__ import annotations

import time

import pytest
from sqlalchemy import select, text

from app.core.db import AuthContext, SessionFactory, engine, set_auth_context
from app.core.exceptions import ConflictError, ValidationError
from app.models.abnormal import (
    ABNORMAL_STATUS_ASSIGNED,
    ABNORMAL_STATUS_CANCELLED,
    ABNORMAL_STATUS_PROCESSING,
    ABNORMAL_STATUS_RESOLVED,
    ABNORMAL_STATUS_SUSPENDED,
    ABNORMAL_STATUS_WAIT_DISPATCH,
    OrdAbnormalTypeDict,
    OrdReasonCodeDict,
    OrdStockout,
)
from app.models.order import OrdOrder
from app.modules.m5_abnormal.service.abnormal import (
    EXC_ADDR_INCOMPLETE,
    EXC_OTHER,
    EXC_OVERSOLD,
    EXC_PRODUCT_UNBOUND,
    EXC_STOCK_SHORT,
    AbnormalService,
)

pytestmark = pytest.mark.asyncio


def _uid() -> str:
    return f"{time.time_ns() % 100000000:08d}"


@pytest.fixture(autouse=True)
async def _ctx():
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    yield


async def _mk_order(owner_id: int = 1, shop_id: int = 0) -> int:
    """造一张订单（裸连接绕开 fail-closed，测试造数豁免通道）"""
    order_bn = f"ABN{_uid()}"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_order "
                "(tenant_id, owner_id, order_bn, platform_order_bn, shop_id, brand_id, "
                " createway, order_type, order_status, audit_status, fulfill_status, "
                " pay_status, ship_status, list_amount, shop_discount, platform_subsidy, "
                " paid_amount, freight, is_cod, order_time, pay_time, create_time, "
                " update_time, version, is_deleted) "
                "VALUES (1, :oid_owner, :obn, :pon, :sid, 0, 'platform', 'normal', "
                "'processing', 'pending', 'pending', 'paid', 'unshipped', "
                "100, 0, 0, 100, 0, 0, NOW(3), NOW(3), NOW(3), NOW(3), 0, 0)"
            ),
            {"obn": order_bn, "sid": shop_id, "pon": f"SIM_ABN_{_uid()}", "oid_owner": owner_id},
        )
        r = await conn.execute(
            text("SELECT id FROM oms_order.ord_order WHERE order_bn = :obn"),
            {"obn": order_bn},
        )
        return int(r.scalar())


async def _mk_reason(order_id: int, reason_code: str = "GOODS_UNBOUND") -> int:
    """造一条审单原因（handle_status=open，用于验证闭环联动）"""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_audit_reason "
                "(tenant_id, owner_id, order_id, batch_no, plugin_name, reason_code, "
                " level, description, detail, suggest_action, route_target, handle_status, "
                " shop_id, create_time) "
                "VALUES (1, 1, :oid, 'B1', 'goods_match', :rc, 'BLOCK', '测试原因', "
                "NULL, 'bind', 'manual', 'open', 0, NOW(3))"
            ),
            {"oid": order_id, "rc": reason_code},
        )
        r = await conn.execute(
            text(
                "SELECT id FROM oms_order.ord_audit_reason "
                "WHERE order_id = :oid AND handle_status='open' ORDER BY id DESC LIMIT 1"
            ),
            {"oid": order_id},
        )
        return int(r.scalar())


async def _get_order(order_id: int) -> OrdOrder:
    async with SessionFactory() as s:
        return await s.scalar(select(OrdOrder).where(OrdOrder.id == order_id))


async def _open_reasons(order_id: int) -> int:
    async with SessionFactory() as s:
        return int(
            await s.scalar(
                text(
                    "SELECT COUNT(*) FROM oms_order.ord_audit_reason "
                    "WHERE order_id = :o AND handle_status='open'"
                ),
                {"o": order_id},
            )
            or 0
        )


async def _clean(order_ids: list[int]) -> None:
    """清理测试数据（按 FK 顺序：先子表后父表）"""
    if not order_ids:
        return
    async with engine.begin() as conn:
        for sql in (
            "DELETE FROM oms_order.ord_stockout WHERE order_id IN :ids",
            "DELETE FROM oms_order.ord_abnormal WHERE order_id IN :ids",
            "DELETE FROM oms_order.ord_audit_reason WHERE order_id IN :ids",
            "DELETE FROM oms_order.ord_order WHERE id IN :ids",
        ):
            await conn.execute(text(sql), {"ids": order_ids})


# ============ FR-01 类型字典与映射 ============


async def test_builtin_types_present():
    """FR-01a/01b：DDL 预置的内置类型齐全（16 种 + OTHER 兜底）"""
    async with SessionFactory() as s:
        rows = await s.scalars(
            select(OrdAbnormalTypeDict).where(OrdAbnormalTypeDict.disabled == 0)
        )
        codes = {r.type_code for r in rows}
    for expect in (
        EXC_PRODUCT_UNBOUND,
        EXC_ADDR_INCOMPLETE,
        EXC_STOCK_SHORT,
        EXC_OVERSOLD,
        EXC_OTHER,
    ):
        assert expect in codes, f"缺内置类型 {expect}"
    assert len(codes) >= 16


async def test_reason_code_maps_to_exception_type():
    """FR-01c：原因码 → 异常类型（权威源 ord_reason_code_dict.exc_type）"""
    async with SessionFactory() as s:
        svc = AbnormalService(s, None)
        t = await svc.type_by_reason_code("GOODS_UNBOUND")
        assert t is not None
        assert t.type_code == EXC_PRODUCT_UNBOUND
        t2 = await svc.type_by_reason_code("STOCK_SHORTAGE")
        assert t2 is not None and t2.type_code == EXC_STOCK_SHORT


async def test_unmapped_reason_falls_back_to_other():
    """FR-01c：未映射原因码 → 兜底「其他异常」"""
    async with SessionFactory() as s:
        svc = AbnormalService(s, None)
        t = await svc.type_by_reason_code("REASON_NOT_EXIST_XYZ")
        assert t is not None
        assert t.type_code == EXC_OTHER


async def test_reason_dict_exposes_exc_type():
    """FR-01c：原因码字典条目带 exc_type 映射"""
    async with SessionFactory() as s:
        rd = await s.scalar(
            select(OrdReasonCodeDict).where(
                OrdReasonCodeDict.reason_code == "GOODS_UNBOUND"
            )
        )
    assert rd is not None
    assert rd.exc_type == EXC_PRODUCT_UNBOUND
    assert rd.default_route


# ============ FR-02a 创建与幂等 ============


async def test_create_abnormal_and_idempotent():
    """FR-02a：同订单同类型未闭环 → 幂等复用，不重复建单"""
    order_id = await _mk_order()
    try:
        order = await _get_order(order_id)
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            a1, created1 = await svc.create(
                order=order,
                exc_type=EXC_PRODUCT_UNBOUND,
                source="audit",
                source_ref="GOODS_UNBOUND",
            )
            a2, created2 = await svc.create(
                order=order,
                exc_type=EXC_PRODUCT_UNBOUND,
                source="audit",
                source_ref="GOODS_UNBOUND",
            )
        assert created1 is True
        assert created2 is False
        assert a1.id == a2.id
        assert a1.status == ABNORMAL_STATUS_WAIT_DISPATCH
        assert a1.abnormal_bn.startswith("ABN")
    finally:
        await _clean([order_id])


async def test_create_sets_sla_deadline_from_dict():
    """FR-01a：SLA 截止 = 创建时间 + 默认 SLA 小时数"""
    order_id = await _mk_order()
    try:
        order = await _get_order(order_id)
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            t = await svc.type_of(EXC_OVERSOLD)
            a, _ = await svc.create(
                order=order, exc_type=EXC_OVERSOLD, source="manual"
            )
            sla = await svc.sla_status(a)
        assert t is not None
        assert a.sla_deadline is not None
        assert sla["overdue"] is False
        # 超卖 SLA 更短（4h）→ 剩余小时 < 5
        assert sla["remain_hours"] is not None and sla["remain_hours"] <= 4
    finally:
        await _clean([order_id])


# ============ FR-02b 状态机 ============


async def test_state_machine_legal_transitions():
    """FR-02b：待分派 → 已分派 → 处理中 → 已解决"""
    order_id = await _mk_order()
    try:
        order = await _get_order(order_id)
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            a, _ = await svc.create(
                order=order, exc_type=EXC_PRODUCT_UNBOUND, source="manual"
            )
            await svc.dispatch(a.id, group_id=1, op_id=7, operator="tester")
            assert (await svc.get(a.id)).status == ABNORMAL_STATUS_ASSIGNED
            await svc.start_processing(a.id, operator="tester")
            assert (await svc.get(a.id)).status == ABNORMAL_STATUS_PROCESSING
            await svc.resolve(a.id, action="reaudit", operator="tester")
            assert (await svc.get(a.id)).status == ABNORMAL_STATUS_RESOLVED
    finally:
        await _clean([order_id])


async def test_state_machine_rejects_illegal_transition():
    """FR-02b：非法流转被拒（待分派 → 已解决）"""
    order_id = await _mk_order()
    try:
        order = await _get_order(order_id)
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            a, _ = await svc.create(
                order=order, exc_type=EXC_PRODUCT_UNBOUND, source="manual"
            )
            with pytest.raises(ConflictError):
                await svc.transit(a.id, ABNORMAL_STATUS_RESOLVED, operator="tester")
    finally:
        await _clean([order_id])


async def test_timeline_recorded():
    """FR-02b：状态变迁写时间线（操作人/动作/前后状态）"""
    order_id = await _mk_order()
    try:
        order = await _get_order(order_id)
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            a, _ = await svc.create(
                order=order, exc_type=EXC_PRODUCT_UNBOUND, source="manual"
            )
            await svc.dispatch(a.id, group_id=2, op_id=3, operator="tester")
            row = await svc.get(a.id)
        tl = list(row.timeline or [])
        assert len(tl) >= 2
        assert tl[0]["action"] == "create"
        assert tl[0]["to"] == ABNORMAL_STATUS_WAIT_DISPATCH
        assert tl[-1]["action"] == "dispatch"
        assert tl[-1]["from"] == ABNORMAL_STATUS_WAIT_DISPATCH
        assert tl[-1]["to"] == ABNORMAL_STATUS_ASSIGNED
        assert tl[-1]["operator"] == "tester"
    finally:
        await _clean([order_id])


# ============ FR-02c 分派 ============


async def test_dispatch_requires_wait_dispatch_status():
    """FR-02c：非「待分派」不可分派"""
    order_id = await _mk_order()
    try:
        order = await _get_order(order_id)
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            a, _ = await svc.create(
                order=order, exc_type=EXC_PRODUCT_UNBOUND, source="manual"
            )
            await svc.dispatch(a.id, group_id=1, operator="t")
            with pytest.raises(ConflictError):
                await svc.dispatch(a.id, group_id=2, operator="t")
    finally:
        await _clean([order_id])


# ============ FR-02d 处理动作 ============


async def test_suspend_requires_expected_recover_time():
    """FR-02d：挂起必须填预计恢复时间"""
    order_id = await _mk_order()
    try:
        order = await _get_order(order_id)
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            a, _ = await svc.create(
                order=order, exc_type=EXC_PRODUCT_UNBOUND, source="manual"
            )
            await svc.dispatch(a.id, group_id=1, operator="t")
            with pytest.raises(ValidationError):
                await svc.suspend(a.id, until_hours=0, operator="t")
            row = await svc.suspend(a.id, until_hours=24, operator="t")
        assert row.status == ABNORMAL_STATUS_SUSPENDED
        assert row.suspend_until is not None
    finally:
        await _clean([order_id])


async def test_cancel_closes_abnormal():
    """FR-02d/02b：取消 → 已取消（终态）"""
    order_id = await _mk_order()
    try:
        order = await _get_order(order_id)
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            a, _ = await svc.create(
                order=order, exc_type=EXC_PRODUCT_UNBOUND, source="manual"
            )
            await svc.dispatch(a.id, group_id=1, operator="t")
            row = await svc.cancel(a.id, operator="t", note="订单取消收口")
        assert row.status == ABNORMAL_STATUS_CANCELLED
    finally:
        await _clean([order_id])


# ============ FR-02e 闭环联动 ============


async def test_resolve_releases_audit_reason_mark():
    """FR-02e：异常单解决 → 订单审单原因标记解除（open → handled）"""
    order_id = await _mk_order()
    try:
        await _mk_reason(order_id)
        assert await _open_reasons(order_id) == 1
        order = await _get_order(order_id)
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            a, _ = await svc.create(
                order=order, exc_type=EXC_PRODUCT_UNBOUND, source="audit"
            )
            await svc.dispatch(a.id, group_id=1, operator="t")
            await svc.resolve(a.id, action="reaudit", operator="t")
        assert await _open_reasons(order_id) == 0
    finally:
        await _clean([order_id])


async def test_marks_kept_until_all_abnormals_closed():
    """FR-02e：同订单有多个未闭环异常单时，**全部闭环才解除标记**"""
    order_id = await _mk_order()
    try:
        await _mk_reason(order_id)
        order = await _get_order(order_id)
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            a1, _ = await svc.create(
                order=order, exc_type=EXC_PRODUCT_UNBOUND, source="audit"
            )
            a2, _ = await svc.create(
                order=order, exc_type=EXC_ADDR_INCOMPLETE, source="audit"
            )
            # 解决第一个 → 还有未闭环的 a2 → 标记不解除
            await svc.dispatch(a1.id, group_id=1, operator="t")
            await svc.resolve(a1.id, action="reaudit", operator="t")
            assert await _open_reasons(order_id) == 1
            # 解决第二个 → 全部闭环 → 标记解除
            await svc.dispatch(a2.id, group_id=1, operator="t")
            await svc.resolve(a2.id, action="reaudit", operator="t")
        assert await _open_reasons(order_id) == 0
    finally:
        await _clean([order_id])


# ============ FR-04a 缺货标记 ============


async def test_stockout_detail_merges_same_triple_key():
    """FR-04a：同 (仓×物料×货主) 多次预占失败 → 缺口量累加合并"""
    order_id = await _mk_order()
    try:
        order = await _get_order(order_id)
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            a, _ = await svc.create(
                order=order, exc_type=EXC_STOCK_SHORT, source="freeze"
            )
            d1 = await svc.mark_stockout(
                a,
                [{"branch_id": 10, "bm_id": 20, "lack_num": 3}],
            )
            d2 = await svc.mark_stockout(
                a,
                [{"branch_id": 10, "bm_id": 20, "lack_num": 2}],
            )
            d3 = await svc.mark_stockout(
                a,
                [{"branch_id": 11, "bm_id": 20, "lack_num": 5}],
            )
            details = await svc.stockouts_of(a.id)
        assert len(d1) == 1 and len(d2) == 1 and len(d3) == 1
        assert d1[0].id == d2[0].id  # 同三元键 → 同一条明细
        assert d3[0].id != d1[0].id  # 不同仓 → 新明细
        assert len(details) == 2
        # 缺口量累加：3 + 2 = 5（同一 ORM 对象被就地更新，故查库确认）
        async with SessionFactory() as s2:
            merged = await s2.scalar(
                select(OrdStockout).where(OrdStockout.id == d1[0].id)
            )
        assert merged is not None
        assert merged.lack_num == 5
    finally:
        await _clean([order_id])


async def test_stockout_oversold_flag():
    """FR-05a：超卖标记（平台已成交但 OMS 无货）"""
    order_id = await _mk_order()
    try:
        order = await _get_order(order_id)
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            a, _ = await svc.create(
                order=order, exc_type=EXC_OVERSOLD, source="freeze"
            )
            d = await svc.mark_stockout(
                a, [{"branch_id": 10, "bm_id": 20, "lack_num": 1}], oversold=True
            )
        assert d[0].oversold_flag == 1
    finally:
        await _clean([order_id])


async def test_strategy_result_persisted():
    """FR-04b：策略链结果回写（换仓候选等）"""
    order_id = await _mk_order()
    try:
        order = await _get_order(order_id)
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            a, _ = await svc.create(
                order=order, exc_type=EXC_STOCK_SHORT, source="freeze"
            )
            d = await svc.mark_stockout(
                a, [{"branch_id": 10, "bm_id": 20, "lack_num": 4}]
            )
            row = await svc.set_strategy_result(
                d[0].id,
                status="done",
                result={"switch_branch": [{"branch_id": 11, "available": 9}]},
            )
        assert row.strategy_status == "done"
        assert row.strategy_result["switch_branch"][0]["branch_id"] == 11
    finally:
        await _clean([order_id])


# ============ FR-02f 查询 ============


async def test_list_abnormals_filter_by_status():
    """FR-02f：按状态过滤 + 只看未闭环"""
    order_id = await _mk_order()
    try:
        order = await _get_order(order_id)
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            a, _ = await svc.create(
                order=order, exc_type=EXC_PRODUCT_UNBOUND, source="manual"
            )
            rows, total = await svc.list_abnormals(status=ABNORMAL_STATUS_WAIT_DISPATCH)
            ids = [r.id for r in rows]
            assert a.id in ids
            open_rows, _ = await svc.list_abnormals(only_open=True)
            assert a.id in [r.id for r in open_rows]
            await svc.dispatch(a.id, group_id=1, operator="t")
            closed, _ = await svc.list_abnormals(status=ABNORMAL_STATUS_WAIT_DISPATCH)
            assert a.id not in [r.id for r in closed]
    finally:
        await _clean([order_id])


async def test_list_abnormals_filter_by_type_and_category():
    """FR-02f：按异常类型 / 分类过滤"""
    order_id = await _mk_order()
    try:
        order = await _get_order(order_id)
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            a, _ = await svc.create(
                order=order, exc_type=EXC_STOCK_SHORT, source="freeze"
            )
            rows, _ = await svc.list_abnormals(exc_type=EXC_STOCK_SHORT)
            assert a.id in [r.id for r in rows]
            rows2, _ = await svc.list_abnormals(exc_category="stock")
            assert a.id in [r.id for r in rows2]
    finally:
        await _clean([order_id])


# ============ FR-03a/03b 统一落单入口 ============


async def test_raise_by_reason_creates_abnormal_for_mapped_code():
    """FR-03a：映射了异常类型的原因码 → 落异常单"""
    order_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            row, created = await svc.raise_by_reason(
                order_id=order_id,
                reason_code="GOODS_UNBOUND",
                source="audit",
                source_ref="goods_match:GOODS_UNBOUND",
            )
        assert row is not None
        assert created is True
        assert row.exc_type == EXC_PRODUCT_UNBOUND
        assert row.source == "audit"
        assert row.status == ABNORMAL_STATUS_WAIT_DISPATCH
        assert row.order_id == order_id
    finally:
        await _clean([order_id])


async def test_raise_by_reason_skips_unmapped_code():
    """FR-03a：未映射异常类型的原因码 → **不落单**（避免异常池泛滥）"""
    order_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            row, created = await svc.raise_by_reason(
                order_id=order_id,
                reason_code="MEMO_HOLD",  # DDL 里 exc_type=NULL
                source="audit",
            )
        assert row is None
        assert created is False
        async with SessionFactory() as s:
            cnt = await s.scalar(
                text(
                    "SELECT COUNT(*) FROM oms_order.ord_abnormal WHERE order_id = :o"
                ),
                {"o": order_id},
            )
        assert int(cnt or 0) == 0
    finally:
        await _clean([order_id])


async def test_raise_by_reason_follows_need_abnormal_bill_flag():
    """FR-03a：是否落单由类型字典的 need_abnormal_bill 决定

    DDL 预置的 16 种类型当前全为 1（= 1）→ 映射了 exc_type 的原因码都落单；
    「不落单」实际由 **exc_type 是否为空** 决定（见上一个用例）。
    本用例锁住「need_abnormal_bill=0 时不落单」这条规则（可配置项，值可被运营改）。
    """
    order_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            t = await svc.type_of("PRICE_ABNORMAL")
            assert t is not None
            # 临时把 need_abnormal_bill 置 0 → 应不落单
            t.need_abnormal_bill = 0
            await s.commit()
            row, _ = await svc.raise_by_reason(
                order_id=order_id, reason_code="PRICE_ABNORMAL", source="audit"
            )
        assert row is None
    finally:
        # 还原字典（避免污染其他用例）
        async with SessionFactory() as s:
            t = await s.scalar(
                select(OrdAbnormalTypeDict).where(
                    OrdAbnormalTypeDict.type_code == "PRICE_ABNORMAL"
                )
            )
            if t is not None:
                t.need_abnormal_bill = 1
                await s.commit()
        await _clean([order_id])


async def test_raise_by_reason_creates_stockout_details():
    """FR-04a：缺货原因码 → 同时落缺货明细（三元键 + 缺口量）"""
    order_id = await _mk_order()
    try:
        detail = {
            "shortages": [
                {
                    "branch_id": 11,
                    "bm_id": 22,
                    "owner_id": 1,
                    "need": 5,
                    "available": 2,
                    "shortage": 3,
                }
            ]
        }
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            row, _ = await svc.raise_by_reason(
                order_id=order_id,
                reason_code="STOCK_SHORTAGE",
                source="audit",
                detail=detail,
            )
            assert row is not None
            assert row.exc_type == EXC_STOCK_SHORT
            details = await svc.stockouts_of(row.id)
        assert len(details) == 1
        assert details[0].branch_id == 11
        assert details[0].bm_id == 22
        assert details[0].lack_num == 3
        assert details[0].stock_snapshot["need"] == 5
    finally:
        await _clean([order_id])


async def test_raise_by_reason_is_idempotent():
    """FR-02a：同一原因码重复触发 → 复用同一异常单"""
    order_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            r1, c1 = await svc.raise_by_reason(
                order_id=order_id, reason_code="GOODS_UNBOUND", source="audit"
            )
            r2, c2 = await svc.raise_by_reason(
                order_id=order_id, reason_code="GOODS_UNBOUND", source="audit"
            )
        assert c1 is True and c2 is False
        assert r1 is not None and r2 is not None
        assert r1.id == r2.id
    finally:
        await _clean([order_id])

