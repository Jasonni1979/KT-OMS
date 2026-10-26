"""异常单分派规则引擎 + 动作执行器测试（W8-2b · SRS-D03.09 FR-02c/FR-02d）

覆盖：
- FR-02c  分派规则引擎（异常类型/店铺/货主/品牌维度；weight DESC 首命中；
            未命中 → 类型默认处理组 → 都没有则留待人工分派）
- FR-02d  动作白名单（按类型 action_set 校验，越权动作拒绝）
            + 5 个可执行动作（reaudit/to_retrial/suspend/cancel/force_pass）
            + 2 个扩展位动作（to_aftersale/refund → 明确「本期未实现」，不伪造数据）
"""
from __future__ import annotations

import time

import pytest
from sqlalchemy import select, text

from app.core.db import AuthContext, SessionFactory, engine, set_auth_context
from app.core.exceptions import ValidationError
from app.models.abnormal import (
    ABNORMAL_STATUS_ASSIGNED,
    ABNORMAL_STATUS_SUSPENDED,
    ABNORMAL_STATUS_WAIT_DISPATCH,
    OrdAbnormal,
    OrdAbnormalTypeDict,
)
from app.models.order import OrdOrder
from app.services.abnormal import AbnormalService
from app.services.abnormal_action import (
    ACT_CANCEL,
    ACT_FORCE_PASS,
    ACT_REAUDIT,
    ACT_REFUND,
    ACT_SUSPEND,
    ACT_TO_AFTERSALE,
    ACT_TO_RETRIAL,
    AbnormalActionService,
)
from app.services.abnormal_dispatch import AbnormalDispatchEngine

pytestmark = pytest.mark.asyncio


def _uid() -> str:
    return f"{time.time_ns() % 100000000:08d}"


@pytest.fixture(autouse=True)
async def _ctx():
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    yield


async def _mk_order(owner_id: int = 1, shop_id: int = 0, brand_id: int = 0) -> int:
    order_bn = f"ABND{_uid()}"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_order "
                "(tenant_id, owner_id, order_bn, platform_order_bn, shop_id, brand_id, "
                " createway, order_type, order_status, audit_status, fulfill_status, "
                " pay_status, ship_status, list_amount, shop_discount, platform_subsidy, "
                " paid_amount, freight, is_cod, order_time, pay_time, create_time, "
                " update_time, version, is_deleted) "
                "VALUES (1, :oid_owner, :obn, :pon, :sid, :bid, 'platform', 'normal', "
                "'processing', 'pending', 'pending', 'paid', 'unshipped', "
                "100, 0, 0, 100, 0, 0, NOW(3), NOW(3), NOW(3), NOW(3), 0, 0)"
            ),
            {
                "obn": order_bn,
                "sid": shop_id,
                "bid": brand_id,
                "pon": f"SIM_ABND_{_uid()}",
                "oid_owner": owner_id,
            },
        )
        r = await conn.execute(
            text("SELECT id FROM oms_order.ord_order WHERE order_bn = :obn"),
            {"obn": order_bn},
        )
        return int(r.scalar())


async def _mk_abnormal(
    order_id: int,
    exc_type: str = "PRODUCT_UNBOUND",
    shop_id: int = 0,
    owner_id: int = 1,
    status: str = "assigned",
) -> int:
    """造一张异常单（直写 DB，绕过自动分派以便单独测引擎）"""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_abnormal "
                "(tenant_id, owner_id, abnormal_bn, order_id, order_bn, shop_id, "
                " exc_type, exc_category, source, source_ref, reason_detail, status, "
                " sla_deadline, timeline, create_time, update_time, version, is_deleted) "
                "VALUES (1, :own, :abn, :oid, (SELECT order_bn FROM oms_order.ord_order "
                " WHERE id = :oid), :sid, :etype, 'data', 'manual', 'test', "
                "JSON_OBJECT('reason_code','GOODS_UNBOUND'), :st, "
                "DATE_ADD(NOW(3), INTERVAL 24 HOUR), JSON_ARRAY(), NOW(3), NOW(3), 0, 0)"
            ),
            {
                "abn": f"ABN{_uid()}",
                "oid": order_id,
                "sid": shop_id,
                "etype": exc_type,
                "own": owner_id,
                "st": status,
            },
        )
        r = await conn.execute(
            text(
                "SELECT id FROM oms_order.ord_abnormal WHERE order_id = :oid "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"oid": order_id},
        )
        return int(r.scalar())


async def _mk_rule(
    rule_name: str,
    conditions: dict,
    weight: int,
    target_group_id: int,
) -> int:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_dispatch_rule "
                "(tenant_id, rule_name, conditions, weight, target_group_id, strategy, "
                " status, create_time, update_time, version, is_deleted) "
                "VALUES (1, :rn, CAST(:cond AS JSON), :w, :gid, 'least_task', "
                "'enabled', NOW(3), NOW(3), 0, 0)"
            ),
            {
                "rn": rule_name,
                "cond": str(conditions).replace("'", '"'),
                "w": weight,
                "gid": target_group_id,
            },
        )
        r = await conn.execute(
            text(
                "SELECT id FROM oms_order.ord_dispatch_rule WHERE rule_name = :rn "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"rn": rule_name},
        )
        return int(r.scalar())


async def _clean(order_ids: list[int], rule_names: list[str]) -> None:
    if not order_ids and not rule_names:
        return
    async with engine.begin() as conn:
        if order_ids:
            lst = ",".join(str(i) for i in order_ids)
            # ⚠ 清理顺序：**先子表后父表**（缺货明细 → 异常单）
            #   否则异常单被删后缺货明细变孤儿（第三轮数据体检实测 17 条孤儿）
            await conn.execute(
                text(
                    "DELETE FROM oms_order.ord_stockout WHERE abnormal_id IN "
                    f"(SELECT id FROM oms_order.ord_abnormal WHERE order_id IN ({lst}))"
                )
            )
            await conn.execute(
                text(f"DELETE FROM oms_order.ord_abnormal WHERE order_id IN ({lst})")
            )
            await conn.execute(
                text(f"DELETE FROM oms_order.ord_retrial WHERE order_id IN ({lst})")
            )
            await conn.execute(
                text(f"DELETE FROM oms_order.ord_order WHERE id IN ({lst})")
            )
        if rule_names:
            lst = ",".join(f"'{n}'" for n in rule_names)
            await conn.execute(
                text(f"DELETE FROM oms_order.ord_dispatch_rule WHERE rule_name IN ({lst})")
            )
        # 售后域（W9-1 转售后/退款动作会落单）→ 必须连带清理，否则污染开发库
        if order_ids:
            lst = ",".join(str(i) for i in order_ids)
            await conn.execute(
                text(
                    "DELETE FROM oms_aftersale.aft_return_apply_log WHERE apply_id IN "
                    "(SELECT id FROM oms_aftersale.aft_return_apply "
                    f"WHERE order_id IN ({lst}))"
                )
            )
            await conn.execute(
                text(
                    "DELETE FROM oms_aftersale.aft_return_apply_item WHERE apply_id IN "
                    "(SELECT id FROM oms_aftersale.aft_return_apply "
                    f"WHERE order_id IN ({lst}))"
                )
            )
            await conn.execute(
                text(f"DELETE FROM oms_aftersale.aft_refund WHERE order_id IN ({lst})")
            )
            await conn.execute(
                text(
                    f"DELETE FROM oms_aftersale.aft_return_apply WHERE order_id IN ({lst})"
                )
            )


# ============ FR-02c 分派规则引擎 ============


async def test_dispatch_engine_matches_by_exc_type():
    """FR-02c：按异常类型维度匹配规则 → 目标处理组"""
    order_id = await _mk_order()
    abn_id = await _mk_abnormal(order_id, "STOCK_SHORT", status="wait_dispatch")
    rule_name = f"T_ABN_RULE_{_uid()}"
    rule_id = await _mk_rule(
        rule_name,
        {"items": [{"op": "in", "dim": "exc_type", "value": ["STOCK_SHORT"]}]},
        500,
        3,
    )
    try:
        async with SessionFactory() as s:
            engine_ = AbnormalDispatchEngine(s)
            abn = await s.scalar(
                select(OrdAbnormal).where(OrdAbnormal.id == abn_id)
            )
            decision = await engine_.decide(abn)
        assert decision["source"] == "rule"
        assert decision["group_id"] == 3
        assert decision["rule_id"] == rule_id
    finally:
        await _clean([order_id], [rule_name])


async def test_dispatch_engine_matches_by_shop_id():
    """FR-02c：按店铺维度匹配"""
    order_id = await _mk_order(shop_id=777)
    abn_id = await _mk_abnormal(order_id, "ADDR_INCOMPLETE", shop_id=777)
    rule_name = f"T_ABN_RULE_{_uid()}"
    await _mk_rule(
        rule_name,
        {"items": [{"op": "eq", "dim": "shop_id", "value": "777"}]},
        600,
        2,
    )
    try:
        async with SessionFactory() as s:
            engine_ = AbnormalDispatchEngine(s)
            abn = await s.scalar(select(OrdAbnormal).where(OrdAbnormal.id == abn_id))
            decision = await engine_.decide(abn)
        assert decision["group_id"] == 2
        assert decision["source"] == "rule"
    finally:
        await _clean([order_id], [rule_name])


async def test_dispatch_engine_weight_desc_first_hit():
    """FR-02c：weight DESC 首命中（高权重规则优先）"""
    order_id = await _mk_order()
    abn_id = await _mk_abnormal(order_id, "STOCK_SHORT", status="wait_dispatch")
    n1 = f"T_ABN_HI_{_uid()}"
    n2 = f"T_ABN_LO_{_uid()}"
    await _mk_rule(
        n1,
        {"items": [{"op": "in", "dim": "exc_type", "value": ["STOCK_SHORT"]}]},
        900,
        3,
    )
    await _mk_rule(
        n2,
        {"items": [{"op": "in", "dim": "exc_type", "value": ["STOCK_SHORT"]}]},
        100,
        5,
    )
    try:
        async with SessionFactory() as s:
            engine_ = AbnormalDispatchEngine(s)
            abn = await s.scalar(select(OrdAbnormal).where(OrdAbnormal.id == abn_id))
            decision = await engine_.decide(abn)
        assert decision["group_id"] == 3  # 高权重那条
    finally:
        await _clean([order_id], [n1, n2])


async def test_dispatch_engine_dimension_miss_not_hit():
    """FR-02c：维度缺失视为不命中（避免误分派）"""
    order_id = await _mk_order(shop_id=0)
    abn_id = await _mk_abnormal(order_id, "STOCK_SHORT", shop_id=0)
    rule_name = f"T_ABN_RULE_{_uid()}"
    await _mk_rule(
        rule_name,
        {"items": [{"op": "eq", "dim": "shop_id", "value": "99999"}]},
        800,
        3,
    )
    try:
        async with SessionFactory() as s:
            engine_ = AbnormalDispatchEngine(s)
            abn = await s.scalar(select(OrdAbnormal).where(OrdAbnormal.id == abn_id))
            decision = await engine_.decide(abn)
        # 该规则不命中 → 落到别的规则或 type_default / none
        assert decision["group_id"] != 3
    finally:
        await _clean([order_id], [rule_name])


async def test_auto_dispatch_transitions_status():
    """FR-02c：自动分派后状态由「待分派」变为「已分派」"""
    order_id = await _mk_order()
    abn_id = await _mk_abnormal(order_id, "STOCK_SHORT", status="wait_dispatch")
    rule_name = f"T_ABN_RULE_{_uid()}"
    await _mk_rule(
        rule_name,
        {"items": [{"op": "in", "dim": "exc_type", "value": ["STOCK_SHORT"]}]},
        700,
        3,
    )
    try:
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            row, decision = await svc.auto_dispatch(abn_id, operator="test")
        assert row is not None
        assert row.status == ABNORMAL_STATUS_ASSIGNED
        assert int(row.group_id or 0) == 3
        assert decision["ok"] is True
    finally:
        await _clean([order_id], [rule_name])


async def test_auto_dispatch_without_match_stays_wait_dispatch():
    """FR-02c：无匹配规则且类型无默认组 → 留「待分派」等人工分派"""
    order_id = await _mk_order()
    abn_id = await _mk_abnormal(order_id, "OTHER", status="wait_dispatch")
    try:
        async with SessionFactory() as s:
            svc = AbnormalService(s, None)
            row, decision = await svc.auto_dispatch(abn_id, operator="test")
        assert row is None
        assert decision["ok"] is False
        async with SessionFactory() as s:
            abn = await s.scalar(select(OrdAbnormal).where(OrdAbnormal.id == abn_id))
        assert abn.status == ABNORMAL_STATUS_WAIT_DISPATCH
    finally:
        await _clean([order_id], [])


# ============ FR-02d 动作白名单 ============


async def test_allowed_actions_follow_type_action_set():
    """FR-02d：可用动作集来自类型字典的 action_set"""
    order_id = await _mk_order()
    abn_id = await _mk_abnormal(order_id, "PRODUCT_UNBOUND")
    try:
        async with SessionFactory() as s:
            svc = AbnormalActionService(s, None)
            allowed = await svc.allowed_actions(abn_id)
        # DDL 预置：PRODUCT_UNBOUND → ["reaudit"]
        assert allowed == ["reaudit"]
    finally:
        await _clean([order_id], [])


async def test_action_not_in_whitelist_rejected():
    """FR-02d：越权动作被拒（不在该类型 action_set 内）"""
    order_id = await _mk_order()
    abn_id = await _mk_abnormal(order_id, "PRODUCT_UNBOUND")
    try:
        async with SessionFactory() as s:
            svc = AbnormalActionService(s, None)
            with pytest.raises(ValidationError) as e:
                await svc.execute(abn_id, ACT_CANCEL, operator="test")
        assert "允许动作集" in str(e.value) or "ACTION_NOT_ALLOWED" in str(e.value)
    finally:
        await _clean([order_id], [])


async def test_illegal_action_name_rejected():
    """FR-02d：非法动作名直接拒绝"""
    order_id = await _mk_order()
    abn_id = await _mk_abnormal(order_id, "OTHER", status="wait_dispatch")
    try:
        async with SessionFactory() as s:
            svc = AbnormalActionService(s, None)
            with pytest.raises(ValidationError):
                await svc.execute(abn_id, "drop_table", operator="test")
    finally:
        await _clean([order_id], [])


# ============ FR-02d 动作执行 ============


async def test_suspend_action_requires_hours():
    """FR-02d：挂起须填预计恢复时间"""
    order_id = await _mk_order()
    abn_id = await _mk_abnormal(order_id, "STOCK_SHORT")
    try:
        async with SessionFactory() as s:
            svc = AbnormalActionService(s, None)
            with pytest.raises(ValidationError):
                await svc.execute(abn_id, ACT_SUSPEND, operator="test", extra={})
    finally:
        await _clean([order_id], [])


async def test_suspend_action_sets_suspended_status():
    """FR-02d：挂起动作 → 状态变为已挂起"""
    order_id = await _mk_order()
    abn_id = await _mk_abnormal(order_id, "STOCK_SHORT")
    try:
        async with SessionFactory() as s:
            svc = AbnormalActionService(s, None)
            res = await svc.execute(
                abn_id, ACT_SUSPEND, operator="test", extra={"suspend_hours": 4}
            )
        assert res["ok"] is True
        async with SessionFactory() as s:
            abn = await s.scalar(select(OrdAbnormal).where(OrdAbnormal.id == abn_id))
        assert abn.status == ABNORMAL_STATUS_SUSPENDED
        assert abn.suspend_until is not None
    finally:
        await _clean([order_id], [])


async def test_to_retrial_creates_retrial_order():
    """FR-02d：转复审动作落 ord_retrial 复审单并回写关联

    用 PRICE_ABNORMAL（DDL 预置 action_set 含 to_retrial）。
    """
    order_id = await _mk_order()
    abn_id = await _mk_abnormal(order_id, "PRICE_ABNORMAL")
    try:
        async with SessionFactory() as s:
            svc = AbnormalActionService(s, None)
            res = await svc.execute(abn_id, ACT_TO_RETRIAL, operator="test", note="改地址")
        assert res["ok"] is True
        assert res["retrial_id"] > 0
        async with SessionFactory() as s:
            abn = await s.scalar(select(OrdAbnormal).where(OrdAbnormal.id == abn_id))
        assert int(abn.rel_retrial_id or 0) == res["retrial_id"]
    finally:
        await _clean([order_id], [])


async def test_cancel_action_cancels_order_and_releases():
    """FR-02d：取消订单动作 → 订单置已取消 + 记 resolve_action"""
    order_id = await _mk_order()
    abn_id = await _mk_abnormal(order_id, "RISK_HIT")
    try:
        async with SessionFactory() as s:
            svc = AbnormalActionService(s, None)
            res = await svc.execute(abn_id, ACT_CANCEL, operator="test")
        assert res["ok"] is True
        async with SessionFactory() as s:
            abn = await s.scalar(select(OrdAbnormal).where(OrdAbnormal.id == abn_id))
            order = await s.scalar(select(OrdOrder).where(OrdOrder.id == order_id))
        assert abn.resolve_action == ACT_CANCEL
        assert order.order_status == "cancelled"
    finally:
        await _clean([order_id], [])


async def test_force_pass_clears_open_audit_reasons():
    """FR-02d：强制放行 → 解除未处理审单原因标记 + 留审计痕迹"""
    order_id = await _mk_order()
    abn_id = await _mk_abnormal(order_id, "RISK_HIT")
    # 造一条 open 审单原因
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_audit_reason "
                "(tenant_id, owner_id, order_id, batch_no, plugin_name, reason_code, "
                " level, description, detail, suggest_action, route_target, handle_status, "
                " shop_id, create_time) "
                "VALUES (1, 1, :oid, 'B1', 'risk', 'RISK_HIT', 'BLOCK', '风控', "
                "NULL, 'review', 'manual', 'open', 0, NOW(3))"
            ),
            {"oid": order_id},
        )
    try:
        async with SessionFactory() as s:
            svc = AbnormalActionService(s, None)
            res = await svc.execute(abn_id, ACT_FORCE_PASS, operator="test", note="已核实")
        assert res["ok"] is True
        async with SessionFactory() as s:
            abn = await s.scalar(select(OrdAbnormal).where(OrdAbnormal.id == abn_id))
            open_cnt = await s.scalar(
                text(
                    "SELECT COUNT(*) FROM oms_order.ord_audit_reason "
                    "WHERE order_id = :o AND handle_status='open'"
                ),
                {"o": order_id},
            )
        assert int(open_cnt or 0) == 0
        assert abn.resolve_action == ACT_FORCE_PASS
        detail = abn.reason_detail if isinstance(abn.reason_detail, dict) else {}
        assert "force_pass" in detail
        assert detail["force_pass"]["operator"] == "test"
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM oms_order.ord_audit_reason WHERE order_id = :o"
                ),
                {"o": order_id},
            )
        await _clean([order_id], [])


async def test_reaudit_action_reruns_audit():
    """FR-02d：修复后重新审单 → 重新投审（决策由审单引擎给出）"""
    order_id = await _mk_order()
    abn_id = await _mk_abnormal(order_id, "STOCK_SHORT")
    try:
        async with SessionFactory() as s:
            svc = AbnormalActionService(s, None)
            res = await svc.execute(abn_id, ACT_REAUDIT, operator="test")
        assert res["ok"] is True
        assert res["stage"] == "reaudit"
        # 决策字段存在（auto_pass / manual / shortage / retrial / pool）
        assert res["audit_decision"] in (
            "auto_pass",
            "manual",
            "shortage",
            "retrial",
            "pool",
        )
    finally:
        await _clean([order_id], [])


# ============ 扩展位动作（不伪造数据）============


async def test_to_aftersale_creates_aftersale_apply():
    """FR-02d（W9-1 已落地）：转售后 → 生成售后申请单"""
    order_id = await _mk_order()
    abn_id = await _mk_abnormal(order_id, "ADDR_INCOMPLETE")
    try:
        async with SessionFactory() as s:
            svc = AbnormalActionService(s, None)
            res = await svc.execute(abn_id, ACT_TO_AFTERSALE, operator="test")
        assert res["ok"] is True
        assert res["stage"] == "to_aftersale"
        assert int(res["apply_id"] or 0) > 0
        assert str(res["apply_bn"] or "").startswith("MA")
        async with SessionFactory() as s:
            cnt = await s.scalar(
                text(
                    "SELECT COUNT(*) FROM oms_aftersale.aft_return_apply WHERE id = :i"
                ),
                {"i": res["apply_id"]},
            )
        assert int(cnt or 0) == 1
    finally:
        await _clean([order_id], [])


async def test_refund_creates_refund_order():
    """FR-02d（W9-1 已落地）：退款 → 生成退款单（待退款态，不伪造已退款）"""
    order_id = await _mk_order()
    abn_id = await _mk_abnormal(order_id, "STOCK_SHORT")
    try:
        async with SessionFactory() as s:
            svc = AbnormalActionService(s, None)
            res = await svc.execute(abn_id, ACT_REFUND, operator="test")
        assert res["ok"] is True
        assert res["stage"] == "refund"
        assert int(res["refund_id"] or 0) > 0
        # 状态=待退款（1），**不是**已退款 → 不伪造平台打款成功
        assert int(res["refund_status"]) == 1
        assert "pending" in str(res["platform_execution"])
        async with SessionFactory() as s:
            cnt = await s.scalar(
                text("SELECT COUNT(*) FROM oms_aftersale.aft_refund WHERE id = :i"),
                {"i": res["refund_id"]},
            )
        assert int(cnt or 0) == 1
    finally:
        await _clean([order_id], [])


async def test_action_set_whitelist_not_polluted():
    """回归：类型字典的 action_set 未被测试改动"""
    async with SessionFactory() as s:
        t = await s.scalar(
            select(OrdAbnormalTypeDict).where(
                OrdAbnormalTypeDict.type_code == "PRODUCT_UNBOUND"
            )
        )
        assert t is not None
        assert t.action_set == ["reaudit"]


async def test_action_rejected_when_not_dispatched():
    """FR-02d：待分派的异常单不可直接执行动作（不能绕过状态机改订单）"""
    order_id = await _mk_order()
    abn_id = await _mk_abnormal(order_id, "PRODUCT_UNBOUND", status="wait_dispatch")
    try:
        async with SessionFactory() as s:
            svc = AbnormalActionService(s, None)
            with pytest.raises(ValidationError) as e:
                await svc.execute(abn_id, ACT_REAUDIT, operator="test")
        assert "先分派" in str(e.value)
    finally:
        await _clean([order_id], [])


# ============ goods_match 插件（W8-2b 补齐的产出路径）============


async def test_goods_match_plugin_produces_unbound_reason():
    """FR-03a：未绑定商品的订单行 → goods_match 插件产出 GOODS_UNBOUND

    补这个插件的原因：D03.09 的 PRODUCT_UNBOUND 类型与 GOODS_UNBOUND 原因码
    在字典里都已配置，但插件链里**没有插件产出该原因码** → 未绑定商品永远
    不会落异常单。
    """
    from app.core.plugin_chain import RuleContext
    from app.services.audit_plugins import GoodsMatchPlugin

    ctx = RuleContext()
    ctx.meta["items"] = [
        {"id": 1, "bm_id": 0, "platform_sku_code": "SKU_X", "nums": 2,
         "parse_status": "pending", "is_gift": 0, "is_virtual": 0},
        {"id": 2, "bm_id": 99, "platform_sku_code": "SKU_Y", "nums": 1,
         "parse_status": "parsed", "is_gift": 0, "is_virtual": 0},
    ]
    res = await GoodsMatchPlugin().process(ctx)
    assert res.status == "HOLD"
    assert len(res.reasons) == 1
    assert res.reasons[0].code == "GOODS_UNBOUND"
    assert len(res.reasons[0].detail["unbound"]) == 1
    assert res.reasons[0].detail["unbound"][0]["platform_sku_code"] == "SKU_X"


async def test_goods_match_plugin_passes_when_all_bound():
    """FR-03a：全部已绑定 → 放行"""
    from app.core.plugin_chain import RuleContext
    from app.services.audit_plugins import GoodsMatchPlugin

    ctx = RuleContext()
    ctx.meta["items"] = [
        {"id": 1, "bm_id": 99, "platform_sku_code": "SKU_Y", "nums": 1,
         "parse_status": "parsed", "is_gift": 0, "is_virtual": 0},
    ]
    res = await GoodsMatchPlugin().process(ctx)
    assert res.status == "PASS"


async def test_goods_match_plugin_skips_gift_and_virtual():
    """FR-03a：赠品/虚拟品不参与未绑定判定"""
    from app.core.plugin_chain import RuleContext
    from app.services.audit_plugins import GoodsMatchPlugin

    ctx = RuleContext()
    ctx.meta["items"] = [
        {"id": 1, "bm_id": 0, "nums": 1, "is_gift": 1, "is_virtual": 0},
        {"id": 2, "bm_id": 0, "nums": 1, "is_gift": 0, "is_virtual": 1},
    ]
    res = await GoodsMatchPlugin().process(ctx)
    assert res.status == "PASS"


async def test_goods_match_plugin_registered_in_chain():
    """回归：goods_match 已注册进审单插件链（否则不会执行）"""
    from app.services.audit_plugins import build_plugins

    names = [p.name() for p in build_plugins()]
    assert "goods_match" in names

