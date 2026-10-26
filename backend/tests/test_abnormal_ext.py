"""异常单扩展域测试（W9-2 · SRS-D03.09 FR-05b/05c/05d/05e + FR-06 + FR-07 + FR-08c）

覆盖：
- FR-05b 超卖应急批次（同店铺同 SKU 聚合；批次级统一决策；订单继承决策）
- FR-05c 分级 SLA（阶段到达时间计时；大促模式收紧 T+4h→T+2h）
- FR-05d 大促模式开关
- FR-05e 复盘摘要（单量/解决路径/平均时长/赔付金额）
- FR-06a/06b 暂停编排（逐发货单；命令日志留痕）
- FR-06c 恢复编排（不半恢复）
- FR-07a/07b 名单维护（黑/灰/白；加/移黑名单须 OA 审批单号）
- FR-07c/07d 命中判定（动作映射；私有优先）
- FR-08c 告警扫描（SLA 超期 + 数量突增 → pending 推送）
"""
from __future__ import annotations

import time
from datetime import UTC

import pytest
from sqlalchemy import select, text

from app.core.db import AuthContext, SessionFactory, engine, set_auth_context
from app.core.exceptions import ConflictError, ValidationError
from app.models.abnormal import OrdStockout
from app.models.order import OrdOrder
from app.services.abnormal_ext import (
    LIST_BLACK,
    LIST_GRAY,
    LIST_WHITE,
    SCOPE_OWNER,
    SCOPE_TENANT,
    STAGE_ALARM,
    STAGE_ALLOC_CALC,
    STAGE_COMPENSATE,
    STAGE_NEGOTIATE,
    STAGE_REFUND,
    AbnormalExtService,
)

pytestmark = pytest.mark.asyncio


def _uid() -> str:
    return f"{time.time_ns() % 100000000:08d}"


@pytest.fixture(autouse=True)
async def _ctx():
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    yield


async def _mk_order() -> int:
    order_bn = f"ABX{_uid()}"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_order "
                "(tenant_id, owner_id, order_bn, platform_order_bn, shop_id, brand_id, "
                " createway, order_type, order_status, audit_status, fulfill_status, "
                " pay_status, ship_status, list_amount, shop_discount, platform_subsidy, "
                " paid_amount, freight, is_cod, order_time, pay_time, create_time, "
                " update_time, version, is_deleted) "
                "VALUES (1, 1, :obn, :pon, 0, 0, 'platform', 'normal', 'processing', "
                "'passed', 'pending', 'paid', 'unshipped', 100, 0, 0, 100, 0, 0, "
                "NOW(3), NOW(3), NOW(3), NOW(3), 0, 0)"
            ),
            {"obn": order_bn, "pon": f"ABXSIM_{_uid()}"},
        )
        return int(
            (
                await conn.execute(
                    text("SELECT id FROM oms_order.ord_order WHERE order_bn = :obn"),
                    {"obn": order_bn},
                )
            ).scalar()
            or 0
        )


async def _mk_oversold_abnormal(order_id: int, bm_id: int = 77) -> int:
    """造一张超卖异常单（OVERSOLD）+ 缺货明细"""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_abnormal "
                "(tenant_id, owner_id, abnormal_bn, order_id, order_bn, shop_id, "
                " exc_type, exc_category, source, source_ref, reason_detail, status, "
                " sla_deadline, timeline, create_time, update_time, version, is_deleted) "
                "VALUES (1, 1, :abn, :oid, (SELECT order_bn FROM oms_order.ord_order "
                " WHERE id = :oid), 0, 'OVERSOLD', 'stock', 'manual', 'test', "
                "JSON_OBJECT('reason_code','OVERSOLD'), 'assigned', "
                "DATE_ADD(NOW(3), INTERVAL 4 HOUR), JSON_ARRAY(), NOW(3), NOW(3), 0, 0)"
            ),
            {"abn": f"ABN{_uid()}", "oid": order_id},
        )
        abn_id = int(
            (
                await conn.execute(
                    text(
                        "SELECT id FROM oms_order.ord_abnormal WHERE order_id = :oid "
                        "ORDER BY id DESC LIMIT 1"
                    ),
                    {"oid": order_id},
                )
            ).scalar()
            or 0
        )
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_stockout "
                "(tenant_id, owner_id, abnormal_id, order_id, branch_id, bm_id, "
                " lack_num, oversold_flag, create_time, update_time, version, is_deleted) "
                "VALUES (1, 1, :aid, :oid, 1, :bm, 3, 1, NOW(3), NOW(3), 0, 0)"
            ),
            {"aid": abn_id, "oid": order_id, "bm": bm_id},
        )
    return abn_id


async def _clean(order_ids: list[int], list_ids: list[int] | None = None) -> None:
    if order_ids:
        lst = ",".join(str(i) for i in order_ids)
        async with engine.begin() as conn:
            await conn.execute(
                text(f"DELETE FROM oms_order.ord_stockout WHERE abnormal_id IN "
                     f"(SELECT id FROM oms_order.ord_abnormal WHERE order_id IN ({lst}))")
            )
            await conn.execute(
                text(f"DELETE FROM oms_order.ord_abnormal WHERE order_id IN ({lst})")
            )
            await conn.execute(
                text("DELETE FROM oms_order.ord_oversold_batch WHERE is_deleted = 0 "
                     "AND batch_bn LIKE 'OS%' AND total_orders = 0")
            )
            await conn.execute(
                text(f"DELETE FROM oms_order.ord_pause_command_log WHERE order_id IN ({lst})")
            )
            await conn.execute(
                text(f"DELETE FROM oms_order.ord_order WHERE id IN ({lst})")
            )
    if list_ids:
        async with engine.begin() as conn:
            # 按 id 删 + 按测试专用前缀清（历次失败重跑会留下旧记录）
            lst = ",".join(str(i) for i in list_ids)
            await conn.execute(
                text(f"DELETE FROM oms_order.ord_risk_list WHERE id IN ({lst})")
            )
            await conn.execute(
                text(
                    "DELETE FROM oms_order.ord_risk_list WHERE match_value LIKE 'HASH%'"
                )
            )


# ============ FR-05b 应急批次聚合 ============


async def test_aggregate_creates_batch_and_links_stockout():
    """FR-05b：超卖单聚合为批次；缺货明细回写批次引用"""
    oid = await _mk_order()
    abn_id = await _mk_oversold_abnormal(oid, bm_id=77)
    try:
        async with SessionFactory() as s:
            svc = AbnormalExtService(s, None)
            batch = await svc.aggregate_oversold_batch(
                shop_id=0, bm_id=77, owner_id=1, abnormal_ids=[abn_id]
            )
            assert batch.total_orders == 1
            assert batch.stage == STAGE_ALARM
            assert batch.batch_bn.startswith("OS")
            # 缺货明细已回写 batch_id
            async with SessionFactory() as s2:
                so = await s2.scalar(
                    select(OrdStockout).where(OrdStockout.abnormal_id == abn_id)
                )
            assert so is not None
            assert int(so.batch_id or 0) == batch.id
        async with SessionFactory() as s:
            await s.execute(
                text("DELETE FROM oms_order.ord_oversold_batch WHERE id = :i"),
                {"i": batch.id},
            )
            await s.commit()
    finally:
        await _clean([oid])


async def test_aggregate_merges_into_existing_batch():
    """FR-05b：同聚合键再次落单 → 并入已有批次（不新建）"""
    oid1 = await _mk_order()
    oid2 = await _mk_order()
    a1 = await _mk_oversold_abnormal(oid1, bm_id=88)
    a2 = await _mk_oversold_abnormal(oid2, bm_id=88)
    batch_id = 0
    try:
        async with SessionFactory() as s:
            svc = AbnormalExtService(s, None)
            b1 = await svc.aggregate_oversold_batch(
                shop_id=0, bm_id=88, owner_id=1, abnormal_ids=[a1]
            )
            batch_id = b1.id
            b2 = await svc.aggregate_oversold_batch(
                shop_id=0, bm_id=88, owner_id=1, abnormal_ids=[a2]
            )
        assert b2.id == b1.id
        assert b2.total_orders == 2
    finally:
        if batch_id:
            async with SessionFactory() as s:
                await s.execute(
                    text("DELETE FROM oms_order.ord_oversold_batch WHERE id = :i"),
                    {"i": batch_id},
                )
                await s.commit()
        await _clean([oid1, oid2])


async def test_aggregate_requires_abnormal_ids():
    """FR-05b：空单号列表 → 拒绝"""
    async with SessionFactory() as s:
        svc = AbnormalExtService(s, None)
        with pytest.raises(ValidationError):
            await svc.aggregate_oversold_batch(
                shop_id=0, bm_id=1, owner_id=1, abnormal_ids=[]
            )


# ============ FR-05c 分级 SLA ============


async def test_advance_batch_stage_order():
    """FR-05c：批次阶段按顺序推进"""
    oid = await _mk_order()
    abn_id = await _mk_oversold_abnormal(oid, bm_id=99)
    batch_id = 0
    try:
        async with SessionFactory() as s:
            svc = AbnormalExtService(s, None)
            b = await svc.aggregate_oversold_batch(
                shop_id=0, bm_id=99, owner_id=1, abnormal_ids=[abn_id]
            )
            batch_id = b.id
            await svc.advance_batch(b.id, STAGE_ALLOC_CALC)
            b2 = await svc.advance_batch(b.id, STAGE_NEGOTIATE)
        assert b2.stage == STAGE_NEGOTIATE
        timeline = b2.stage_timeline or {}
        assert STAGE_ALLOC_CALC in timeline
        assert STAGE_NEGOTIATE in timeline
    finally:
        if batch_id:
            async with SessionFactory() as s:
                await s.execute(
                    text("DELETE FROM oms_order.ord_oversold_batch WHERE id = :i"),
                    {"i": batch_id},
                )
                await s.commit()
        await _clean([oid])


async def test_advance_batch_cannot_skip_stage():
    """FR-05c：不可跳过中间阶段"""
    oid = await _mk_order()
    abn_id = await _mk_oversold_abnormal(oid, bm_id=100)
    batch_id = 0
    try:
        async with SessionFactory() as s:
            svc = AbnormalExtService(s, None)
            b = await svc.aggregate_oversold_batch(
                shop_id=0, bm_id=100, owner_id=1, abnormal_ids=[abn_id]
            )
            batch_id = b.id
            with pytest.raises(ConflictError) as e:
                await svc.advance_batch(b.id, STAGE_REFUND)
        assert "跳过" in str(e.value)
    finally:
        if batch_id:
            async with SessionFactory() as s:
                await s.execute(
                    text("DELETE FROM oms_order.ord_oversold_batch WHERE id = :i"),
                    {"i": batch_id},
                )
                await s.commit()
        await _clean([oid])


async def test_advance_batch_cannot_go_backward():
    """FR-05c：阶段不可回退"""
    oid = await _mk_order()
    abn_id = await _mk_oversold_abnormal(oid, bm_id=101)
    batch_id = 0
    try:
        async with SessionFactory() as s:
            svc = AbnormalExtService(s, None)
            b = await svc.aggregate_oversold_batch(
                shop_id=0, bm_id=101, owner_id=1, abnormal_ids=[abn_id]
            )
            batch_id = b.id
            await svc.advance_batch(b.id, STAGE_ALLOC_CALC)
            with pytest.raises(ConflictError):
                await svc.advance_batch(b.id, STAGE_ALARM)
    finally:
        if batch_id:
            async with SessionFactory() as s:
                await s.execute(
                    text("DELETE FROM oms_order.ord_oversold_batch WHERE id = :i"),
                    {"i": batch_id},
                )
                await s.commit()
        await _clean([oid])


async def test_batch_sla_status_reports_stages():
    """FR-05c：SLA 状态含各阶段到达时间与剩余小时"""
    oid = await _mk_order()
    abn_id = await _mk_oversold_abnormal(oid, bm_id=102)
    batch_id = 0
    try:
        async with SessionFactory() as s:
            svc = AbnormalExtService(s, None)
            b = await svc.aggregate_oversold_batch(
                shop_id=0, bm_id=102, owner_id=1, abnormal_ids=[abn_id]
            )
            batch_id = b.id
            await svc.advance_batch(b.id, STAGE_ALLOC_CALC)
            status = await svc.batch_sla_status(b.id)
        assert status["stage"] == STAGE_ALLOC_CALC
        assert len(status["stages"]) >= 2
        # 调拨测算 SLA 4h，刚到达 → 未超期
        alloc = next(x for x in status["stages"] if x["stage"] == STAGE_ALLOC_CALC)
        assert alloc["sla_hours"] == 4
        assert alloc["overdue"] is False
    finally:
        if batch_id:
            async with SessionFactory() as s:
                await s.execute(
                    text("DELETE FROM oms_order.ord_oversold_batch WHERE id = :i"),
                    {"i": batch_id},
                )
                await s.commit()
        await _clean([oid])


async def test_promo_mode_tightens_sla():
    """FR-05d：大促模式 → SLA 收紧（调拨测算 4h → 2h）"""
    oid = await _mk_order()
    abn_id = await _mk_oversold_abnormal(oid, bm_id=103)
    batch_id = 0
    try:
        async with SessionFactory() as s:
            svc = AbnormalExtService(s, None)
            b = await svc.aggregate_oversold_batch(
                shop_id=0, bm_id=103, owner_id=1, abnormal_ids=[abn_id]
            )
            batch_id = b.id
            await svc.advance_batch(b.id, STAGE_ALLOC_CALC)
            normal = await svc.batch_sla_status(b.id)
            await svc.set_promo_mode(b.id, promo=True)
            promo = await svc.batch_sla_status(b.id)
        alloc_n = next(x for x in normal["stages"] if x["stage"] == STAGE_ALLOC_CALC)
        alloc_p = next(x for x in promo["stages"] if x["stage"] == STAGE_ALLOC_CALC)
        assert alloc_n["sla_hours"] == 4
        assert alloc_p["sla_hours"] == 2
        assert promo["promo_mode"] == 1
    finally:
        if batch_id:
            async with SessionFactory() as s:
                await s.execute(
                    text("DELETE FROM oms_order.ord_oversold_batch WHERE id = :i"),
                    {"i": batch_id},
                )
                await s.commit()
        await _clean([oid])


# ============ FR-05e 复盘 ============


async def test_close_batch_review_generates_summary():
    """FR-05e：批次关闭生成复盘摘要（单量/解决路径/赔付金额）"""
    oid = await _mk_order()
    abn_id = await _mk_oversold_abnormal(oid, bm_id=104)
    batch_id = 0
    try:
        async with SessionFactory() as s:
            svc = AbnormalExtService(s, None)
            b = await svc.aggregate_oversold_batch(
                shop_id=0, bm_id=104, owner_id=1, abnormal_ids=[abn_id]
            )
            batch_id = b.id
            for st in (STAGE_ALLOC_CALC, STAGE_NEGOTIATE, STAGE_REFUND, STAGE_COMPENSATE):
                await svc.advance_batch(b.id, st)
            await svc.register_compensation(
                b.id, order_id=oid, comp_type="platform_fine", amount=50.0
            )
            summary = await svc.close_batch_review(b.id)
        assert summary["total_orders"] == 1
        assert summary["compensation_total"] == 50.0
        assert summary["compensation_count"] == 1
        assert "resolution_paths" in summary
    finally:
        if batch_id:
            async with SessionFactory() as s:
                await s.execute(
                    text("DELETE FROM oms_order.ord_oversold_batch WHERE id = :i"),
                    {"i": batch_id},
                )
                await s.commit()
        await _clean([oid])


# ============ FR-06 暂停编排 ============


async def test_pause_order_sets_paused_and_logs():
    """FR-06a/06b：订单暂停 + 逐发货单命令日志"""
    oid = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AbnormalExtService(s, None)
            res = await svc.pause_order(oid, reason="改单叫回", operator="tester")
            order = await s.scalar(select(OrdOrder).where(OrdOrder.id == oid))
            logs = await svc.list_pause_logs(oid)
        assert res["paused"] is True
        assert order is not None
        assert order.fulfill_status == "paused"
        assert len(logs) == 0  # 无发货单 → 无命令日志
    finally:
        await _clean([oid])


async def test_resume_order_restores_status():
    """FR-06c：恢复 → 订单回到 pending"""
    oid = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AbnormalExtService(s, None)
            await svc.pause_order(oid, reason="暂停")
            res = await svc.resume_order(oid, operator="tester")
            order = await s.scalar(select(OrdOrder).where(OrdOrder.id == oid))
        assert res["resumed"] is True
        assert order is not None
        assert order.fulfill_status == "pending"
    finally:
        await _clean([oid])


async def test_pause_conflicts_with_aftersale():
    """FR-06d：售后中的订单暂停语义冲突 → 拒绝"""
    oid = await _mk_order()
    try:
        async with SessionFactory() as s:
            await s.execute(
                text(
                    "UPDATE oms_order.ord_order SET fulfill_status = 'aftersale' "
                    "WHERE id = :i"
                ),
                {"i": oid},
            )
            await s.commit()
            svc = AbnormalExtService(s, None)
            with pytest.raises(ConflictError):
                await svc.pause_order(oid, reason="暂停")
    finally:
        await _clean([oid])


# ============ FR-07 名单服务 ============


async def test_add_black_list_requires_oa_approval():
    """FR-07b：加入黑名单必须带 OA 审批单号"""
    async with SessionFactory() as s:
        svc = AbnormalExtService(s, None)
        with pytest.raises(ValidationError) as e:
            await svc.add_to_list(
                list_type=LIST_BLACK, dimension="mobile", match_value="HASH_X"
            )
        assert "OA" in str(e.value)


async def test_add_and_remove_black_list_with_oa():
    """FR-07b：带 OA 审批单号可加入/移出黑名单"""
    async with SessionFactory() as s:
        svc = AbnormalExtService(s, None)
        row = await svc.add_to_list(
            list_type=LIST_BLACK,
            dimension="mobile",
            match_value="HASH_BLACK_1",
            scope=SCOPE_TENANT,
            value_type="hash",
            reason="风控命中",
            oa_approval_id="OA-001",
        )
        list_id = int(row.id)
    try:
        async with SessionFactory() as s:
            svc = AbnormalExtService(s, None)
            hit = await svc.match_list(dimension="mobile", match_value="HASH_BLACK_1")
            assert hit["hit"] is True
            assert hit["list_type"] == LIST_BLACK
            assert hit["action"] == "abnormal_and_retrial"
            # 移出黑名单也须 OA
            with pytest.raises(ValidationError):
                await svc.remove_from_list(list_id)
            await svc.remove_from_list(list_id, oa_approval_id="OA-002")
            hit2 = await svc.match_list(dimension="mobile", match_value="HASH_BLACK_1")
            assert hit2["hit"] is False
    finally:
        await _clean([], [list_id])


async def test_gray_list_action_is_audit_hold():
    """FR-07c：灰名单 → 审单 HOLD 转人工（不生成异常单）"""
    async with SessionFactory() as s:
        svc = AbnormalExtService(s, None)
        row = await svc.add_to_list(
            list_type=LIST_GRAY,
            dimension="address",
            match_value="HASH_ADDR_1",
            scope=SCOPE_TENANT,
        )
        list_id = int(row.id)
    try:
        async with SessionFactory() as s:
            svc = AbnormalExtService(s, None)
            hit = await svc.match_list(dimension="address", match_value="HASH_ADDR_1")
        assert hit["hit"] is True
        assert hit["action"] == "audit_hold"
    finally:
        await _clean([], [list_id])


async def test_white_list_action_is_skip_check():
    """FR-07c：白名单 → 跳过对应校验"""
    async with SessionFactory() as s:
        svc = AbnormalExtService(s, None)
        row = await svc.add_to_list(
            list_type=LIST_WHITE,
            dimension="account",
            match_value="ACC_001",
            scope=SCOPE_TENANT,
        )
        list_id = int(row.id)
    try:
        async with SessionFactory() as s:
            svc = AbnormalExtService(s, None)
            hit = await svc.match_list(
                dimension="account", match_value="ACC_001", owner_id=1
            )
        assert hit["hit"] is True
        assert hit["action"] == "skip_check"
    finally:
        await _clean([], [list_id])


async def test_owner_private_list_has_priority_over_tenant():
    """FR-07d：命中判定私有优先（货主私有 > 租户）"""
    async with SessionFactory() as s:
        svc = AbnormalExtService(s, None)
        tenant_row = await svc.add_to_list(
            list_type=LIST_GRAY,
            dimension="mobile",
            match_value="HASH_PRI",
            scope=SCOPE_TENANT,
        )
        owner_row = await svc.add_to_list(
            list_type=LIST_BLACK,
            dimension="mobile",
            match_value="HASH_PRI",
            scope=SCOPE_OWNER,
            owner_id=1,
            oa_approval_id="OA-003",
        )
        ids = [int(tenant_row.id), int(owner_row.id)]
    try:
        async with SessionFactory() as s:
            svc = AbnormalExtService(s, None)
            hit_owner = await svc.match_list(
                dimension="mobile", match_value="HASH_PRI", owner_id=1
            )
            hit_other = await svc.match_list(
                dimension="mobile", match_value="HASH_PRI", owner_id=999
            )
        # 货主私有命中 → 黑名单
        assert hit_owner["list_type"] == LIST_BLACK
        assert hit_owner["scope"] == SCOPE_OWNER
        # 其他货主 → 落到租户库 → 灰名单
        assert hit_other["list_type"] == LIST_GRAY
        assert hit_other["scope"] == SCOPE_TENANT
    finally:
        await _clean([], ids)


async def test_match_list_respects_effective_period():
    """FR-07a：生效期间外的名单不命中"""
    async with SessionFactory() as s:
        svc = AbnormalExtService(s, None)
        row = await svc.add_to_list(
            list_type=LIST_GRAY,
            dimension="mobile",
            match_value="HASH_EXPIRED",
            scope=SCOPE_TENANT,
            effective_hours=1,
        )
        list_id = int(row.id)
        # 把生效结束时间改到过去
        # ⚠ 必须用**应用同基准（UTC）**：DB 的 NOW() 是本地时区（+08:00），
        #   而应用比较用的是 utcnow() → 用 NOW() 改会得到「未来」的时间，
        #   记录看起来没过期（这正是复盘记录的「DATETIME 无时区」坑）
        from datetime import datetime, timedelta

        past = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=1)
        await s.execute(
            text(
                "UPDATE oms_order.ord_risk_list SET effective_end = :past WHERE id = :i"
            ),
            {"i": list_id, "past": past},
        )
        await s.commit()
        hit = await svc.match_list(dimension="mobile", match_value="HASH_EXPIRED")
    assert hit["hit"] is False
    await _clean([], [list_id])


async def test_add_list_validates_arguments():
    """名单参数校验（非法类型/维度/作用域）"""
    async with SessionFactory() as s:
        svc = AbnormalExtService(s, None)
        with pytest.raises(ValidationError):
            await svc.add_to_list(
                list_type="purple", dimension="mobile", match_value="X"
            )
        with pytest.raises(ValidationError):
            await svc.add_to_list(
                list_type=LIST_GRAY, dimension="wechat", match_value="X"
            )
        with pytest.raises(ValidationError):
            await svc.add_to_list(
                list_type=LIST_GRAY, dimension="mobile", match_value="X", scope="planet"
            )
        with pytest.raises(ValidationError):
            await svc.add_to_list(
                list_type=LIST_GRAY,
                dimension="mobile",
                match_value="X",
                scope=SCOPE_OWNER,
            )


# ============ FR-08c 告警扫描 ============


async def test_scan_alerts_reports_overdue():
    """FR-08c：SLA 超期异常单 → 告警待发清单"""
    oid = await _mk_order()
    abn_id = await _mk_oversold_abnormal(oid, bm_id=110)
    try:
        # 把 SLA 截止改到过去
        async with SessionFactory() as s:
            # ⚠ 用应用同基准（UTC）——DB NOW() 是本地时区（+08:00）
            from datetime import datetime, timedelta

            past = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=3)
            await s.execute(
                text(
                    "UPDATE oms_order.ord_abnormal SET sla_deadline = :past WHERE id = :i"
                ),
                {"i": abn_id, "past": past},
            )
            await s.commit()
            svc = AbnormalExtService(s, None)
            res = await svc.scan_alerts()
        assert res["total"] >= 1
        assert any(a["alert_type"] == "sla_overdue" for a in res["overdue"])
        # 企微推送未实现 → 明确 pending
        assert all(a["push_status"] == "pending" for a in res["overdue"])
    finally:
        await _clean([oid])
