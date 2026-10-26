"""售后服务域测试（W9-1 · SRS-D05.01 售后申请 + D05.03 仅退款与退款单）

覆盖：
- D05.01 FR-01b 落库幂等（平台单三键唯一）
- D05.01 FR-01d 类型判定（仅退款/退货退款/换货/补发）
- D05.01 FR-01e 原单关联（订单缺失 → 待关联异常态）
- D05.01 FR-02a 申请单头（RA/MA 单号 + 双口径金额 + 时限）
- D05.01 FR-02b/02c 状态机（合法迁移 / 非法拒绝 / 类型裁剪 / 日志完整）
- D05.01 FR-02e 审核（同意→退款单生成 / 拒绝→拒绝原因码）
- D05.01 FR-02f 部分售后（行级数量上限校验）
- D05.01 FR-03a 手工建单（operator 必填）
- D05.01 FR-05a 售后中订单标记（落单打标 / 闭环清标）
- D05.01 FR-05b pay_status 联动（部分/全额退款）
- D05.03 FR-01 退款单生成
- D05.03 FR-02 退款状态推进（退款中/已退款/失败重试）
"""
from __future__ import annotations

import time

import pytest
from sqlalchemy import select, text

from app.core.db import AuthContext, SessionFactory, engine, set_auth_context
from app.core.exceptions import ConflictError, ValidationError
from app.models.aftersale import AftRefund
from app.models.order import OrdOrder
from app.services.aftersale import (
    APPLY_STATUS_LABEL,
    REFUND_FAILED,
    REFUND_WAIT,
    REFUNDED,
    REFUNDING,
    ST_DONE,
    ST_EXCHANGING,
    ST_PENDING_LINK,
    ST_REFUNDING,
    ST_REJECTED,
    ST_WAIT_AUDIT,
    ST_WAIT_RECEIVE,
    ST_WAIT_REFUND,
    ST_WAIT_RETURN,
    TYPE_EXCHANGE,
    TYPE_REFUND_ONLY,
    TYPE_RETURN_REFUND,
    AftersaleService,
)

pytestmark = pytest.mark.asyncio


def _uid() -> str:
    return f"{time.time_ns() % 100000000:08d}"


@pytest.fixture(autouse=True)
async def _ctx():
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    yield


async def _mk_order(nums: int = 5, paid: float = 100.0) -> tuple[int, int]:
    """造订单 + 1 行（返回 order_id, order_item_id）"""
    order_bn = f"AFT{_uid()}"
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
                "'passed', 'pending', 'paid', 'unshipped', :paid, 0, 0, :paid, 0, 0, "
                "NOW(3), NOW(3), NOW(3), NOW(3), 0, 0)"
            ),
            {"obn": order_bn, "pon": f"AFTSIM_{_uid()}", "paid": paid},
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
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_order_item "
                "(tenant_id, owner_id, order_id, platform_sku_code, bm_id, bm_number, "
                " bm_name, nums, list_price, list_amount, paid_amount, parse_status, "
                " create_time, update_time, version, is_deleted) "
                "VALUES (1, 1, :oid, :sku, 0, :bmn, '售后测试物料', :nums, "
                ":price, :amount, :amount, 'parsed', NOW(3), NOW(3), 0, 0)"
            ),
            {
                "oid": oid,
                "sku": f"AFTSKU_{_uid()}",
                "bmn": f"AFTBM_{_uid()}",
                "nums": nums,
                "price": paid / max(1, nums),
                "amount": paid,
            },
        )
        item_id = int(
            (
                await conn.execute(
                    text(
                        "SELECT id FROM oms_order.ord_order_item WHERE order_id = :oid "
                        "ORDER BY id DESC LIMIT 1"
                    ),
                    {"oid": oid},
                )
            ).scalar()
            or 0
        )
    return oid, item_id


async def _clean(order_ids: list[int]) -> None:
    if not order_ids:
        return
    lst = ",".join(str(i) for i in order_ids)
    async with engine.begin() as conn:
        await conn.execute(
            text(f"DELETE FROM oms_aftersale.aft_return_apply_log WHERE apply_id IN "
                 f"(SELECT id FROM oms_aftersale.aft_return_apply WHERE order_id IN ({lst}))")
        )
        await conn.execute(
            text(f"DELETE FROM oms_aftersale.aft_return_apply_item WHERE apply_id IN "
                 f"(SELECT id FROM oms_aftersale.aft_return_apply WHERE order_id IN ({lst}))")
        )
        await conn.execute(
            text(f"DELETE FROM oms_aftersale.aft_refund WHERE order_id IN ({lst})")
        )
        await conn.execute(
            text(f"DELETE FROM oms_aftersale.aft_return_apply WHERE order_id IN ({lst})")
        )
        await conn.execute(
            text(f"DELETE FROM oms_order.ord_order_item WHERE order_id IN ({lst})")
        )
        await conn.execute(text(f"DELETE FROM oms_order.ord_order WHERE id IN ({lst})"))


# ============ FR-01b/01d/01e/02a 落单 ============


async def test_create_apply_only_refund():
    """FR-02a：仅退款申请落单（状态=待审核，RA 单号，时限已算）"""
    oid, item_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            row, created = await svc.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                platform="taobao",
                shop_id=0,
                platform_aftersale_bn=f"AS{_uid()}",
                platform_order_bn="",
                order_id=oid,
                items=[
                    {
                        "order_item_id": item_id,
                        "apply_num": 1,
                        "apply_amount_customer_line": 50,
                    }
                ],
                reason_code="SEVEN_NO_REASON",
                apply_amount_customer=50,
            )
        assert created is True
        assert row.apply_bn.startswith("RA")
        assert row.status == ST_WAIT_AUDIT
        assert row.deadline is not None
        assert float(row.apply_amount_customer) == 50
    finally:
        await _clean([oid])


async def test_create_apply_is_idempotent_by_platform_key():
    """FR-01b：同一平台单号重复落单 → 复用不新建"""
    oid, item_id = await _mk_order()
    as_bn = f"AS{_uid()}"
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            r1, c1 = await svc.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                platform="taobao",
                platform_aftersale_bn=as_bn,
                order_id=oid,
                items=[{"order_item_id": item_id, "apply_num": 1}],
            )
            r2, c2 = await svc.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                platform="taobao",
                platform_aftersale_bn=as_bn,
                order_id=oid,
                items=[{"order_item_id": item_id, "apply_num": 1}],
            )
        assert c1 is True and c2 is False
        assert r1.id == r2.id
    finally:
        await _clean([oid])


async def test_apply_without_order_is_pending_link():
    """FR-01e：订单缺失 → 落「待关联」异常态"""
    async with SessionFactory() as s:
        svc = AftersaleService(s, None)
        row, created = await svc.create_apply(
            aftersale_type=TYPE_REFUND_ONLY,
            platform="taobao",
            platform_aftersale_bn=f"AS{_uid()}",
            platform_order_bn="NOT_EXIST_ORDER_BN",
            items=[],
        )
        assert created is True
        assert row.status == ST_PENDING_LINK
        await s.execute(text("DELETE FROM oms_aftersale.aft_return_apply WHERE id = :i"), {"i": row.id})
        await s.commit()


async def test_manual_apply_requires_operator():
    """FR-03a：手工建单须填操作人"""
    oid, item_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            with pytest.raises(ValidationError):
                await svc.create_apply(
                    aftersale_type=TYPE_REFUND_ONLY,
                    order_id=oid,
                    items=[{"order_item_id": item_id, "apply_num": 1}],
                    source="manual",
                    operator="",
                )
    finally:
        await _clean([oid])


async def test_manual_apply_bn_prefix_is_ma():
    """FR-03a：手工单用 MA 前缀"""
    oid, item_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            row, _ = await svc.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                order_id=oid,
                items=[{"order_item_id": item_id, "apply_num": 1}],
                source="manual",
                operator="tester",
            )
        assert row.apply_bn.startswith("MA")
    finally:
        await _clean([oid])


async def test_invalid_aftersale_type_rejected():
    """FR-01d：非法售后类型拒绝"""
    oid, item_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            with pytest.raises(ValidationError):
                await svc.create_apply(
                    aftersale_type=99,
                    order_id=oid,
                    items=[{"order_item_id": item_id, "apply_num": 1}],
                )
    finally:
        await _clean([oid])


# ============ FR-02f 部分售后数量校验 ============


async def test_apply_num_exceeds_purchase_qty_rejected():
    """FR-02f：申请数量超过行购买数量 → 拒绝"""
    oid, item_id = await _mk_order(nums=2)
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            with pytest.raises(ValidationError) as e:
                await svc.create_apply(
                    aftersale_type=TYPE_REFUND_ONLY,
                    order_id=oid,
                    items=[{"order_item_id": item_id, "apply_num": 3}],
                )
        assert "超限" in str(e.value)
    finally:
        await _clean([oid])


async def test_historical_apply_counts_toward_limit():
    """FR-02f：历史已申请数量计入上限（本单 + 历史 ≤ 购买数量）"""
    oid, item_id = await _mk_order(nums=3)
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            await svc.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                platform="taobao",
                platform_aftersale_bn=f"AS{_uid()}",
                order_id=oid,
                items=[{"order_item_id": item_id, "apply_num": 2}],
            )
            # 再申请 2 → 累计 4 > 3 → 拒绝
            with pytest.raises(ValidationError):
                await svc.create_apply(
                    aftersale_type=TYPE_REFUND_ONLY,
                    platform="taobao",
                    platform_aftersale_bn=f"AS{_uid()}",
                    order_id=oid,
                    items=[{"order_item_id": item_id, "apply_num": 2}],
                )
            # 再申请 1 → 累计 3 ≤ 3 → 通过
            row, created = await svc.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                platform="taobao",
                platform_aftersale_bn=f"AS{_uid()}",
                order_id=oid,
                items=[{"order_item_id": item_id, "apply_num": 1}],
            )
        assert created is True
    finally:
        await _clean([oid])


# ============ FR-02b/02c 状态机 ============


async def test_illegal_transition_rejected():
    """FR-02c：非法流转（如 待审核 → 完成）被拒绝"""
    oid, item_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            row, _ = await svc.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                order_id=oid,
                items=[{"order_item_id": item_id, "apply_num": 1}],
            )
            with pytest.raises(ConflictError) as e:
                await svc.transit(row.id, ST_DONE, operator="tester")
        assert "不可从" in str(e.value)
    finally:
        await _clean([oid])


async def test_refund_only_cannot_transit_to_wait_return():
    """FR-02b 类型裁剪：仅退款不允许流转到待退货"""
    oid, item_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            row, _ = await svc.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                order_id=oid,
                items=[{"order_item_id": item_id, "apply_num": 1}],
            )
            with pytest.raises(ConflictError) as e:
                await svc.transit(row.id, ST_WAIT_RETURN, operator="tester")
        assert "不允许流转" in str(e.value)
    finally:
        await _clean([oid])


async def test_exchange_cannot_transit_to_refunding():
    """FR-02b 类型裁剪：换货不允许流转到退款中"""
    oid, item_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            row, _ = await svc.create_apply(
                aftersale_type=TYPE_EXCHANGE,
                order_id=oid,
                items=[{"order_item_id": item_id, "apply_num": 1}],
            )
            with pytest.raises(ConflictError):
                await svc.transit(row.id, ST_REFUNDING, operator="tester")
    finally:
        await _clean([oid])


async def test_return_refund_full_flow_transitions():
    """FR-02b：退货退款完整链路 待审核→待退货→待收货→待退款→完成"""
    oid, item_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            row, _ = await svc.create_apply(
                aftersale_type=TYPE_RETURN_REFUND,
                order_id=oid,
                items=[{"order_item_id": item_id, "apply_num": 1}],
            )
            await svc.transit(row.id, ST_WAIT_RETURN, operator="t")
            await svc.transit(row.id, ST_WAIT_RECEIVE, operator="t")
            await svc.transit(row.id, ST_WAIT_REFUND, operator="t")
            await svc.transit(row.id, ST_DONE, operator="t")
            detail = await svc.get_apply(row.id)
        assert detail["status"] == ST_DONE
        # 每次变迁都写日志（FR-02c）
        actions = [lg["action"] for lg in detail["logs"]]
        assert "create" in actions
        assert len(detail["logs"]) >= 5
        # 日志序号递增
        seqs = [lg["seq"] for lg in detail["logs"]]
        assert seqs == sorted(seqs)
    finally:
        await _clean([oid])


async def test_rejected_can_reopen_to_wait_audit():
    """FR-02b：拒绝 → 可 reopen 回待审核"""
    oid, item_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            row, _ = await svc.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                order_id=oid,
                items=[{"order_item_id": item_id, "apply_num": 1}],
            )
            await svc.transit(row.id, ST_REJECTED, operator="t")
            await svc.transit(row.id, ST_WAIT_AUDIT, operator="t")
            detail = await svc.get_apply(row.id)
        assert detail["status"] == ST_WAIT_AUDIT
    finally:
        await _clean([oid])


# ============ FR-02e 审核 ============


async def test_audit_agree_generates_refund_and_advances():
    """FR-02e：审核同意（仅退款）→ 生成退款单 + 状态推进到退款中"""
    oid, item_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            row, _ = await svc.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                order_id=oid,
                items=[{"order_item_id": item_id, "apply_num": 1}],
                apply_amount_customer=50,
            )
            res = await svc.audit(row.id, agree=True, operator="tester")
            detail = await svc.get_apply(row.id)
        assert res["decision"] == "agree"
        assert res["refund_id"] > 0
        assert detail["status"] == ST_REFUNDING
        assert len(detail["refunds"]) == 1
        assert detail["refunds"][0]["status"] == REFUND_WAIT
        assert float(detail["refunds"][0]["refund_customer"]) == 50
        # 平台回传未实现 → 明确 pending，不伪造成功
        assert res["sync_pending"] is True
    finally:
        await _clean([oid])


async def test_audit_reject_records_reason():
    """FR-02e：审核拒绝 → 状态到拒绝 + 记录拒绝原因码"""
    oid, item_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            row, _ = await svc.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                order_id=oid,
                items=[{"order_item_id": item_id, "apply_num": 1}],
            )
            res = await svc.audit(
                row.id,
                agree=False,
                operator="tester",
                reject_reason_code="REJECT_BY_POLICY",
            )
            detail = await svc.get_apply(row.id)
        assert res["decision"] == "reject"
        assert detail["status"] == ST_REJECTED
        assert res["reject_reason_code"] == "REJECT_BY_POLICY"
        # 拒绝不生成退款单
        assert len(detail["refunds"]) == 0
    finally:
        await _clean([oid])


async def test_audit_only_when_wait_audit():
    """FR-02e：非待审核状态不可重复审核"""
    oid, item_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            row, _ = await svc.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                order_id=oid,
                items=[{"order_item_id": item_id, "apply_num": 1}],
            )
            await svc.audit(row.id, agree=True, operator="tester")
            with pytest.raises(ConflictError):
                await svc.audit(row.id, agree=True, operator="tester2")
    finally:
        await _clean([oid])


async def test_audit_return_refund_goes_to_wait_return():
    """FR-02e：审核同意（退货退款）→ 状态到待退货"""
    oid, item_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            row, _ = await svc.create_apply(
                aftersale_type=TYPE_RETURN_REFUND,
                order_id=oid,
                items=[{"order_item_id": item_id, "apply_num": 1}],
                apply_amount_customer=50,
            )
            await svc.audit(row.id, agree=True, operator="tester")
            detail = await svc.get_apply(row.id)
        assert detail["status"] == ST_WAIT_RETURN
        assert len(detail["refunds"]) == 1
    finally:
        await _clean([oid])


async def test_audit_exchange_goes_to_exchanging_without_refund():
    """FR-02e：审核同意（换货）→ 状态到换货执行中，不生成退款单"""
    oid, item_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            row, _ = await svc.create_apply(
                aftersale_type=TYPE_EXCHANGE,
                order_id=oid,
                items=[{"order_item_id": item_id, "apply_num": 1}],
            )
            await svc.audit(row.id, agree=True, operator="tester")
            detail = await svc.get_apply(row.id)
        assert detail["status"] == ST_EXCHANGING
        assert len(detail["refunds"]) == 0
    finally:
        await _clean([oid])


# ============ D05.03 FR-02 退款状态推进 ============


async def test_refund_transit_to_refunded_links_order_pay_status():
    """D05.03 FR-02 + D05.01 FR-05b：退款成功 → 订单 pay_status=refunded（全额）"""
    oid, item_id = await _mk_order(paid=100.0)
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            row, _ = await svc.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                order_id=oid,
                items=[{"order_item_id": item_id, "apply_num": 1}],
                apply_amount_customer=100,
            )
            res = await svc.audit(row.id, agree=True, operator="tester")
            await svc.refund_transit(res["refund_id"], REFUNDING, operator="tester")
            await svc.refund_transit(res["refund_id"], REFUNDED, operator="tester")
            order = await s.scalar(select(OrdOrder).where(OrdOrder.id == oid))
        assert order is not None
        assert order.pay_status == "refunded"
    finally:
        await _clean([oid])


async def test_partial_refund_links_order_pay_status():
    """D05.01 FR-05b：部分退款 → 订单 pay_status=part_refunded"""
    oid, item_id = await _mk_order(paid=100.0)
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            row, _ = await svc.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                order_id=oid,
                items=[{"order_item_id": item_id, "apply_num": 1}],
                apply_amount_customer=30,
            )
            res = await svc.audit(row.id, agree=True, operator="tester")
            await svc.refund_transit(res["refund_id"], REFUNDING, operator="tester")
            await svc.refund_transit(res["refund_id"], REFUNDED, operator="tester")
            order = await s.scalar(select(OrdOrder).where(OrdOrder.id == oid))
        assert order is not None
        assert order.pay_status == "part_refunded"
    finally:
        await _clean([oid])


async def test_refund_failed_can_retry():
    """D05.03 FR-02：退款失败 → 可重试回退款中"""
    oid, item_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            row, _ = await svc.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                order_id=oid,
                items=[{"order_item_id": item_id, "apply_num": 1}],
                apply_amount_customer=50,
            )
            res = await svc.audit(row.id, agree=True, operator="tester")
            await svc.refund_transit(res["refund_id"], REFUNDING, operator="t")
            await svc.refund_transit(
                res["refund_id"], REFUND_FAILED, operator="t", fail_reason_code="E_TIMEOUT"
            )
            await svc.refund_transit(res["refund_id"], REFUNDING, operator="t")
            async with SessionFactory() as s2:
                rf = await s2.scalar(
                    select(AftRefund).where(AftRefund.id == res["refund_id"])
                )
        assert rf is not None
        assert rf.status == REFUNDING
        assert rf.fail_reason_code == "E_TIMEOUT"
    finally:
        await _clean([oid])


async def test_refund_illegal_transition_rejected():
    """D05.03 FR-02：已退款不可再流转（吸收态不回退）"""
    oid, item_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            row, _ = await svc.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                order_id=oid,
                items=[{"order_item_id": item_id, "apply_num": 1}],
                apply_amount_customer=50,
            )
            res = await svc.audit(row.id, agree=True, operator="tester")
            await svc.refund_transit(res["refund_id"], REFUNDING, operator="t")
            await svc.refund_transit(res["refund_id"], REFUNDED, operator="t")
            with pytest.raises(ConflictError):
                await svc.refund_transit(res["refund_id"], REFUNDING, operator="t")
    finally:
        await _clean([oid])


# ============ FR-05a 订单售后中标记 ============


async def test_order_marked_in_aftersale_then_cleared():
    """FR-05a：落单打「售后中」标记；闭环后清除"""
    oid, item_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            row, _ = await svc.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                order_id=oid,
                items=[{"order_item_id": item_id, "apply_num": 1}],
            )
            order = await s.scalar(select(OrdOrder).where(OrdOrder.id == oid))
            assert order is not None
            assert order.fulfill_status == "aftersale"
            # 审核同意 → 退款中（仍是在途）→ 标记保持
            res = await svc.audit(row.id, agree=True, operator="tester")
            await svc.refund_transit(res["refund_id"], REFUNDING, operator="t")
            await svc.refund_transit(res["refund_id"], REFUNDED, operator="t")
            await svc.transit(row.id, ST_DONE, operator="t")
            order2 = await s.scalar(select(OrdOrder).where(OrdOrder.id == oid))
        assert order2 is not None
        assert order2.fulfill_status == "pending"
    finally:
        await _clean([oid])


# ============ 查询 ============


async def test_list_applies_filters():
    """售后申请列表（按状态/类型/订单筛选）"""
    oid, item_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            await svc.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                order_id=oid,
                items=[{"order_item_id": item_id, "apply_num": 1}],
            )
            items = await svc.list_applies(order_id=oid)
            only_open = await svc.list_applies(order_id=oid, only_open=True)
            by_type = await svc.list_applies(aftersale_type=TYPE_EXCHANGE)
        assert len(items) == 1
        assert len(only_open) == 1
        assert len(by_type) == 0
        assert items[0]["status_name"] == APPLY_STATUS_LABEL[ST_WAIT_AUDIT]
    finally:
        await _clean([oid])


async def test_get_apply_includes_items_logs_refunds():
    """售后申请详情含行/日志/退款单"""
    oid, item_id = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AftersaleService(s, None)
            row, _ = await svc.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                order_id=oid,
                items=[
                    {
                        "order_item_id": item_id,
                        "apply_num": 2,
                        "apply_amount_customer_line": 40,
                    }
                ],
                apply_amount_customer=40,
            )
            await svc.audit(row.id, agree=True, operator="tester")
            detail = await svc.get_apply(row.id)
        assert len(detail["items"]) == 1
        assert detail["items"][0]["apply_num"] == 2
        assert detail["items"][0]["approved_num"] == 0
        assert len(detail["logs"]) >= 2
        assert len(detail["refunds"]) == 1
    finally:
        await _clean([oid])


async def test_apply_not_found():
    """边界：售后单不存在 → 404"""
    from app.core.exceptions import NotFoundError

    async with SessionFactory() as s:
        svc = AftersaleService(s, None)
        with pytest.raises(NotFoundError):
            await svc.get_apply(99999999)
