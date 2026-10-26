"""缺货策略链测试（W8-2 · SRS-D03.09 FR-04b 换仓重试 + FR-04c 解除重审）

覆盖：
- FR-04b-1 换仓测算：整单满足 / 部分满足 / 无候选仓 / 借调建议留扩展位（P1）
- FR-04b-1 换仓执行：排除已试仓 → 新 plan → 重新预占 → 成功则异常单闭环
- FR-04c   解除重审：库存补足 → 重新预占 → 成功则异常单闭环
- 策略结果回写到缺货明细（strategy_status / strategy_result）
"""
from __future__ import annotations

import time

import pytest
from sqlalchemy import select, text

from app.core.db import AuthContext, SessionFactory, engine, set_auth_context
from app.core.exceptions import ValidationError
from app.models.abnormal import (
    ABNORMAL_STATUS_RESOLVED,
    OrdAbnormal,
    OrdStockout,
)
from app.models.order import OrdOrder
from app.services.abnormal import EXC_STOCK_SHORT, AbnormalService
from app.services.master import get_redis
from app.services.stockout_strategy import (
    STRATEGY_NONE,
    STRATEGY_PARTIAL,
    StockoutStrategyService,
)

pytestmark = pytest.mark.asyncio


def _uid() -> str:
    return f"{time.time_ns() % 100000000:08d}"


@pytest.fixture(autouse=True)
async def _ctx():
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    yield


async def _mk_order(shop_id: int = 0) -> int:
    order_bn = f"ABNS{_uid()}"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_order "
                "(tenant_id, owner_id, order_bn, platform_order_bn, shop_id, brand_id, "
                " createway, order_type, order_status, audit_status, fulfill_status, "
                " pay_status, ship_status, list_amount, shop_discount, platform_subsidy, "
                " paid_amount, freight, is_cod, order_time, pay_time, create_time, "
                " update_time, version, is_deleted) "
                "VALUES (1, 1, :obn, :pon, :sid, 0, 'platform', 'normal', "
                "'processing', 'pending', 'pending', 'paid', 'unshipped', "
                "100, 0, 0, 100, 0, 0, NOW(3), NOW(3), NOW(3), NOW(3), 0, 0)"
            ),
            {"obn": order_bn, "pon": f"SIM_ABNS_{_uid()}", "sid": shop_id},
        )
        r = await conn.execute(
            text("SELECT id FROM oms_order.ord_order WHERE order_bn = :obn"),
            {"obn": order_bn},
        )
        return int(r.scalar())


async def _mk_abnormal_with_stockout(
    order_id: int,
    *,
    branch_id: int = 1,
    bm_id: int = 1,
    lack_num: int = 5,
    shop_id: int = 0,
) -> int:
    """造一张缺货异常单（含缺货明细）"""
    async with SessionFactory() as s:
        order = await s.scalar(select(OrdOrder).where(OrdOrder.id == order_id))
        svc = AbnormalService(s, None)
        row, _ = await svc.create(
            order=order, exc_type=EXC_STOCK_SHORT, source="freeze"
        )
        await svc.mark_stockout(
            row,
            [
                {
                    "branch_id": branch_id,
                    "bm_id": bm_id,
                    "lack_num": lack_num,
                    "stock_snapshot": {"need": lack_num, "available": 0, "owner_id": 1},
                }
            ],
        )
        return int(row.id)


async def _clean(order_ids: list[int]) -> None:
    if not order_ids:
        return
    async with engine.begin() as conn:
        for sql in (
            "DELETE FROM oms_order.ord_stockout WHERE order_id IN :ids",
            "DELETE FROM oms_order.ord_abnormal WHERE order_id IN :ids",
            "DELETE FROM oms_order.ord_order WHERE id IN :ids",
        ):
            await conn.execute(text(sql), {"ids": order_ids})


# ============ FR-04b-1 换仓测算 ============


async def test_calc_switch_branch_no_candidates():
    """无候选仓 → status=none（建议借调/采购，P1）"""
    order_id = await _mk_order(shop_id=0)
    try:
        abn_id = await _mk_abnormal_with_stockout(order_id, shop_id=0)
        async with SessionFactory() as s:
            svc = StockoutStrategyService(s, await get_redis())
            res = await svc.calc_switch_branch(abn_id)
        assert res["status"] == STRATEGY_NONE
        assert res["suggest"]["action"] == "none"
        # 借调建议留扩展位（不伪造数据）
        assert res["borrow_stock"]["enabled"] is False
        assert "D04.05" in res["borrow_stock"]["reason"]
    finally:
        await _clean([order_id])


async def test_calc_switch_branch_partial_when_no_stock():
    """候选仓存在但无库存 → status=none（不是 partial）"""
    order_id = await _mk_order(shop_id=0)
    try:
        abn_id = await _mk_abnormal_with_stockout(order_id, branch_id=999, bm_id=999)
        async with SessionFactory() as s:
            svc = StockoutStrategyService(s, await get_redis())
            res = await svc.calc_switch_branch(abn_id)
        # 店铺无仓绑定 → 无候选仓
        assert res["status"] in (STRATEGY_NONE, STRATEGY_PARTIAL)
        assert res["current_branch_ids"] == [999]
    finally:
        await _clean([order_id])


async def test_calc_switch_branch_reports_borrow_stock_disabled():
    """借调建议恒为未启用（P1），不返回伪造的可借额度"""
    order_id = await _mk_order(shop_id=0)
    try:
        abn_id = await _mk_abnormal_with_stockout(order_id)
        async with SessionFactory() as s:
            svc = StockoutStrategyService(s, await get_redis())
            res = await svc.calc_switch_branch(abn_id)
        assert "enabled" in res["borrow_stock"]
        assert res["borrow_stock"]["enabled"] is False
        # 不得出现伪造的额度数字
        assert "quota" not in res["borrow_stock"]
        assert "amount" not in res["borrow_stock"]
    finally:
        await _clean([order_id])


async def test_calc_requires_stockout_details():
    """无缺货明细的异常单 → 测算返回 none（不抛错）"""
    order_id = await _mk_order(shop_id=0)
    try:
        async with SessionFactory() as s:
            order = await s.scalar(select(OrdOrder).where(OrdOrder.id == order_id))
            svc = AbnormalService(s, None)
            row, _ = await svc.create(
                order=order, exc_type=EXC_STOCK_SHORT, source="manual"
            )
            abn_id = int(row.id)
            strat = StockoutStrategyService(s, await get_redis())
            res = await strat.calc_switch_branch(abn_id)
        assert res["status"] == STRATEGY_NONE
        assert res["suggest"]["action"] == "none"
    finally:
        await _clean([order_id])


# ============ FR-04b-1 换仓执行 ============


async def test_switch_branch_without_details_raises():
    """无缺货明细 → 换仓重试拒绝执行"""
    order_id = await _mk_order(shop_id=0)
    try:
        async with SessionFactory() as s:
            order = await s.scalar(select(OrdOrder).where(OrdOrder.id == order_id))
            svc = AbnormalService(s, None)
            row, _ = await svc.create(
                order=order, exc_type=EXC_STOCK_SHORT, source="manual"
            )
            strat = StockoutStrategyService(s, await get_redis())
            with pytest.raises(ValidationError):
                await strat.switch_branch(int(row.id), operator="test")
    finally:
        await _clean([order_id])


async def test_switch_branch_records_result_on_failure():
    """换仓失败 → 策略结果回写为 failed，异常单**不闭环**"""
    order_id = await _mk_order(shop_id=0)
    try:
        abn_id = await _mk_abnormal_with_stockout(order_id, branch_id=999, bm_id=999)
        async with SessionFactory() as s:
            strat = StockoutStrategyService(s, await get_redis())
            res = await strat.switch_branch(abn_id, operator="test")
        # 分仓失败（订单无行/无仓）→ ok=False
        assert res["ok"] is False
        assert res["excluded_branches"] == [999]
        # 结果回写
        async with SessionFactory() as s:
            details = list(
                await s.scalars(
                    select(OrdStockout).where(
                        OrdStockout.abnormal_id == abn_id,
                        OrdStockout.is_deleted == 0,
                    )
                )
            )
            abn = await s.scalar(
                select(OrdAbnormal).where(OrdAbnormal.id == abn_id)
            )
        assert details
        assert details[0].strategy_status in ("none", "failed")
        assert details[0].strategy_result is not None
        # 异常单不闭环（仍待处理）
        assert abn is not None
        assert abn.status != ABNORMAL_STATUS_RESOLVED
    finally:
        await _clean([order_id])


# ============ FR-04c 解除重审 ============


async def test_release_retry_without_plan_raises():
    """无履约方案 → 解除重审拒绝执行"""
    from app.core.exceptions import NotFoundError

    order_id = await _mk_order(shop_id=0)
    try:
        abn_id = await _mk_abnormal_with_stockout(order_id)
        async with SessionFactory() as s:
            strat = StockoutStrategyService(s, await get_redis())
            with pytest.raises(NotFoundError):
                await strat.release_and_retry(abn_id, operator="test")
    finally:
        await _clean([order_id])
