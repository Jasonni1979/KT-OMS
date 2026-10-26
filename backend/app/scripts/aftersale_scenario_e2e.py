"""售后场景端到端（W10 · M3 内测验收）

**为什么补这个**：mock-platform 的造单场景库有 3 个售后场景
（`refund_only` 仅退款 / `return_refund` 退货退款 / `defective_return` 质检不良），
但此前端到端只覆盖了 1 条链路（`cross_domain_e2e.py` 的「异常单 → 转售后 → 审核 →
退款 → 订单联动」），**仅退款与退货退款两类单的直接建单闭环没有端到端验证**。

本脚本覆盖（每类都走完「建单 → 审核 → 退款单 → 退款完成 → 订单 pay_status 联动」）：

| 场景 | 售后类型 | 货品状态 | 断言要点 |
|---|---|---|---|
| 仅退款（未发货） | 1 | 未发货 | 建单落「待审核」→ 审核同意生成退款单 → 退款完成 → 订单 pay_status=refunded |
| 退货退款（已发货） | 2 | 已发货 | 同上 + 状态机允许「待退货 → 待收货」推进 |
| 幂等 | 1 | — | 同 `(platform, shop_id, platform_aftersale_bn)` 重复建单 → 返回同一单（FR-01b） |
| 审核拒绝 | 1 | — | 审核拒绝 → 不生成退款单，状态推进到「已拒绝」 |

⚠ **平台售后报文自动同步（D05.01 FR-01a）未实现** —— 本脚本走**手工建单侧**
（`AftersaleService.create_apply`）验证售后域自身的能力。
平台报文自动进单是独立缺口（见《MVP内测验收报告》G1）。

用法：
    cd backend && .venv/bin/python -m app.scripts.aftersale_scenario_e2e
"""
from __future__ import annotations

import asyncio
import sys
import uuid
from typing import Any

from sqlalchemy import select, text

from app.core.db import AuthContext, SessionFactory, engine, set_auth_context
from app.models.aftersale import AftRefund, AftReturnApply
from app.models.order import OrdOrder
from app.modules.m6_aftersale.service.aftersale import AftersaleService
from app.modules.m6_aftersale.service.aftersale_codes import (
    GOODS_SHIPPED,
    GOODS_UNSHIPPED,
    REFUNDED,
    REFUNDING,
    ST_REFUNDING,
    ST_REJECTED,
    ST_WAIT_AUDIT,
    ST_WAIT_RECEIVE,
    ST_WAIT_REFUND,
    ST_WAIT_RETURN,
    TYPE_REFUND_ONLY,
    TYPE_RETURN_REFUND,
)
from app.scripts._checker import Checker

#: 自造数据前缀（**独立前缀**，不与演示数据/其它 E2E 冲突）
PREFIX = "DLVAFT"

PASS = 0


def _uid() -> str:
    return uuid.uuid4().hex[:10].upper()


async def _mk_order(
    shop_id: int = 0, paid: float = 100.0, shipped: bool = False
) -> tuple[int, int]:
    """造订单 + 1 行（订单/行都用独立前缀，便于精确清理）

    返回 (订单 id, 订单行 id) —— 售后申请行必须引用**真实订单行 id**
    （FR-02f 校验行归属与数量上限）。
    """
    order_bn = f"{PREFIX}O{_uid()}"
    ship_status = "shipped" if shipped else "unshipped"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_order "
                "(tenant_id, owner_id, order_bn, platform_order_bn, shop_id, brand_id, "
                " createway, order_type, order_status, audit_status, fulfill_status, "
                " pay_status, ship_status, list_amount, shop_discount, platform_subsidy, "
                " paid_amount, freight, is_cod, order_time, pay_time, create_time, "
                " update_time, version, is_deleted) "
                "VALUES (1, 1, :obn, :pon, :sid, 0, 'platform', 'normal', 'processing', "
                "'passed', 'pending', 'paid', :ship, :paid, 0, 0, :paid, 0, 0, "
                "NOW(3), NOW(3), NOW(3), NOW(3), 0, 0)"
            ),
            {
                "obn": order_bn,
                "pon": f"{PREFIX}SIM_{_uid()}",
                "sid": shop_id,
                "paid": paid,
                "ship": ship_status,
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
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_order_item "
                "(tenant_id, owner_id, order_id, platform_sku_code, bm_id, bm_number, "
                " bm_name, nums, list_price, list_amount, paid_amount, parse_status, "
                " create_time, update_time, version, is_deleted) "
                "VALUES (1, 1, :oid, :sku, 0, :bmn, '售后场景物料', 2, :price, "
                ":amount, :amount, 'parsed', NOW(3), NOW(3), 0, 0)"
            ),
            {
                "oid": oid,
                "sku": f"{PREFIX}SKU_{_uid()}",
                "bmn": f"{PREFIX}BM_{_uid()}",
                "price": paid / 2,
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
    """清理（**先子表后父表** —— 顺序反了整段 rollback 且静默不删）"""
    if not order_ids:
        return
    lst = ",".join(str(i) for i in order_ids)
    async with engine.begin() as conn:
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
            text(f"DELETE FROM oms_aftersale.aft_return_apply WHERE order_id IN ({lst})")
        )
        await conn.execute(
            text(f"DELETE FROM oms_order.ord_order_item WHERE order_id IN ({lst})")
        )
        await conn.execute(text(f"DELETE FROM oms_order.ord_order WHERE id IN ({lst})"))


def _items(item_id: int, paid: float, apply_num: int = 2) -> list[dict[str, Any]]:
    """售后申请行

    ⚠ 字段名必须是 `apply_num`（不是 nums）且 `order_item_id` 必须是**真实订单行 id**
    —— FR-02f 会校验行归属与「本单+历史 ≤ 购买数量」。
    """
    return [
        {
            "order_item_id": item_id,
            "apply_num": apply_num,
            "apply_amount": paid,
            "sku_name": "售后场景物料",
            "bm_id": 0,
        }
    ]


async def _scenario_refund_only(ck: Checker) -> None:
    """场景 1：仅退款（未发货）全闭环"""
    ck.section("场景 1：仅退款（未发货）建单 → 审核 → 退款 → 订单联动")
    oid, item_id = await _mk_order(paid=100.0)
    try:
        async with SessionFactory() as s:
            aft = AftersaleService(s, None)
            apply, created = await aft.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                platform="taobao",
                shop_id=0,
                platform_aftersale_bn=f"{PREFIX}RF{_uid()}",
                platform_order_bn=f"{PREFIX}SIM_{_uid()}",
                order_id=oid,
                items=_items(item_id, 100.0),
                reason_code="REFUND_ONLY",
                apply_amount_customer=100.0,
                source="platform",
                goods_status=GOODS_UNSHIPPED,
            )
            apply_id = int(apply.id)
            detail = await aft.get_apply(apply_id)
        ck.check(
            "仅退款：建单成功且状态为待审核",
            created and detail["status"] == ST_WAIT_AUDIT,
            f"apply_id={apply_id} 状态={detail.get('status')}",
        )

        # 审核同意 → 生成退款单
        async with SessionFactory() as s:
            aft = AftersaleService(s, None)
            audit = await aft.audit(
                apply_id, agree=True, operator="xde", approved_amount_customer=100
            )
            detail = await aft.get_apply(apply_id)
        refund_id = int(audit.get("refund_id") or 0)
        ck.check(
            "仅退款：审核同意生成退款单且状态推进到退款中",
            refund_id > 0 and detail["status"] == ST_REFUNDING,
            f"refund_id={refund_id} 状态={detail.get('status')}",
        )

        # 退款完成 → 订单 pay_status 联动
        async with SessionFactory() as s:
            aft = AftersaleService(s, None)
            await aft.refund_transit(refund_id, REFUNDING, operator="xde")
            await aft.refund_transit(refund_id, REFUNDED, operator="xde")
            order = await s.scalar(select(OrdOrder).where(OrdOrder.id == oid))
            rf = await s.scalar(select(AftRefund).where(AftRefund.id == refund_id))
        ck.check(
            "仅退款：退款单状态为已退款",
            rf is not None and int(rf.status) == REFUNDED,
            f"refund_status={getattr(rf, 'status', None)}",
        )
        ck.check(
            "仅退款：订单 pay_status 联动为已退款",
            order is not None and order.pay_status == "refunded",
            f"pay_status={getattr(order, 'pay_status', None)}",
        )
    finally:
        await _clean([oid])


async def _scenario_return_refund(ck: Checker) -> None:
    """场景 2：退货退款（已发货）全闭环"""
    ck.section("场景 2：退货退款（已发货）建单 → 审核 → 退款 → 订单联动")
    oid, item_id = await _mk_order(paid=200.0, shipped=True)
    try:
        async with SessionFactory() as s:
            aft = AftersaleService(s, None)
            apply, created = await aft.create_apply(
                aftersale_type=TYPE_RETURN_REFUND,
                platform="taobao",
                shop_id=0,
                platform_aftersale_bn=f"{PREFIX}RR{_uid()}",
                order_id=oid,
                items=_items(item_id, 200.0),
                reason_code="RETURN_REFUND",
                apply_amount_customer=200.0,
                source="platform",
                goods_status=GOODS_SHIPPED,
            )
            apply_id = int(apply.id)
            detail = await aft.get_apply(apply_id)
        ck.check(
            "退货退款：建单成功且状态为待审核",
            created and detail["status"] == ST_WAIT_AUDIT,
            f"apply_id={apply_id} 状态={detail.get('status')}",
        )

        async with SessionFactory() as s:
            aft = AftersaleService(s, None)
            audit = await aft.audit(
                apply_id, agree=True, operator="xde", approved_amount_customer=200
            )
            refund_id = int(audit.get("refund_id") or 0)
            detail = await aft.get_apply(apply_id)
        # ⚠ 退货退款审核同意后进「待退货」（不是「退款中」——那是没有退货动作的类型）
        ck.check(
            "退货退款：审核同意生成退款单且状态进待退货",
            refund_id > 0 and detail["status"] == ST_WAIT_RETURN,
            f"refund_id={refund_id} 状态={detail.get('status')}",
        )

        # 退货链路推进：待退货 → 待收货 → 待退款
        async with SessionFactory() as s:
            aft = AftersaleService(s, None)
            await aft.transit(apply_id, ST_WAIT_RECEIVE, operator="xde")
            d2 = await aft.get_apply(apply_id)
        ck.check(
            "退货退款：待退货 → 待收货 流转成功",
            d2["status"] == ST_WAIT_RECEIVE,
            f"状态={d2.get('status')}",
        )
        async with SessionFactory() as s:
            aft = AftersaleService(s, None)
            await aft.transit(apply_id, ST_WAIT_REFUND, operator="xde")
            d3 = await aft.get_apply(apply_id)
        ck.check(
            "退货退款：待收货 → 待退款 流转成功",
            d3["status"] == ST_WAIT_REFUND,
            f"状态={d3.get('status')}",
        )

        async with SessionFactory() as s:
            aft = AftersaleService(s, None)
            await aft.refund_transit(refund_id, REFUNDING, operator="xde")
            await aft.refund_transit(refund_id, REFUNDED, operator="xde")
            order = await s.scalar(select(OrdOrder).where(OrdOrder.id == oid))
        ck.check(
            "退货退款：订单 pay_status 联动为已退款",
            order is not None and order.pay_status == "refunded",
            f"pay_status={getattr(order, 'pay_status', None)}",
        )
    finally:
        await _clean([oid])


async def _scenario_idempotent(ck: Checker) -> None:
    """场景 3：平台售后单幂等（FR-01b）"""
    ck.section("场景 3：平台售后单按三键幂等")
    oid, item_id = await _mk_order(paid=50.0)
    try:
        asn = f"{PREFIX}IDEM{_uid()}"
        async with SessionFactory() as s:
            aft = AftersaleService(s, None)
            a1, c1 = await aft.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                platform="taobao",
                shop_id=0,
                platform_aftersale_bn=asn,
                order_id=oid,
                items=_items(item_id, 50.0),
                apply_amount_customer=50.0,
                source="platform",
                goods_status=GOODS_UNSHIPPED,
            )
        async with SessionFactory() as s:
            aft = AftersaleService(s, None)
            a2, c2 = await aft.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                platform="taobao",
                shop_id=0,
                platform_aftersale_bn=asn,
                order_id=oid,
                items=_items(item_id, 50.0),
                apply_amount_customer=50.0,
                source="platform",
                goods_status=GOODS_UNSHIPPED,
            )
        ck.check(
            "幂等：首次建单为新建",
            c1 is True and int(a1.id) > 0,
            f"apply_id={a1.id}",
        )
        ck.check(
            "幂等：重复建单复用同一单（未新建）",
            c2 is False and int(a2.id) == int(a1.id),
            f"首次={a1.id} 二次={a2.id} created={c2}",
        )
    finally:
        await _clean([oid])


async def _scenario_audit_reject(ck: Checker) -> None:
    """场景 4：审核拒绝（不生成退款单）"""
    ck.section("场景 4：售后审核拒绝")
    oid, item_id = await _mk_order(paid=80.0)
    try:
        async with SessionFactory() as s:
            aft = AftersaleService(s, None)
            apply, _ = await aft.create_apply(
                aftersale_type=TYPE_REFUND_ONLY,
                platform="taobao",
                shop_id=0,
                platform_aftersale_bn=f"{PREFIX}RJ{_uid()}",
                order_id=oid,
                items=_items(item_id, 80.0),
                apply_amount_customer=80.0,
                source="platform",
                goods_status=GOODS_UNSHIPPED,
            )
            apply_id = int(apply.id)
            audit = await aft.audit(
                apply_id, agree=False, operator="xde", reject_reason_code="EVIDENCE_INSUFFICIENT"
            )
            detail = await aft.get_apply(apply_id)
        ck.check(
            "审核拒绝：不生成退款单",
            int(audit.get("refund_id") or 0) == 0,
            f"refund_id={audit.get('refund_id')}",
        )
        ck.check(
            "审核拒绝：申请单状态推进到已拒绝",
            detail["status"] == ST_REJECTED,
            f"状态={detail.get('status')}",
        )
        async with SessionFactory() as s:
            n = len(
                (
                    await s.scalars(
                        select(AftReturnApply).where(AftReturnApply.order_id == oid)
                    )
                ).all()
            )
        ck.check("审核拒绝：仅生成 1 张申请单（无重复）", n == 1, f"申请单数={n}")
    finally:
        await _clean([oid])


async def main() -> int:
    # ⚠ 数据权限中间件 fail-closed：无 AuthContext 的 ORM 查询会被拒绝
    #   （PermissionError: AuthContext 缺失）→ E2E 需显式声明超管上下文
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    ck = Checker("售后场景端到端（W10 内测）")
    await _scenario_refund_only(ck)
    await _scenario_return_refund(ck)
    await _scenario_idempotent(ck)
    await _scenario_audit_reject(ck)
    print(ck.render())
    print(f"\n断言合计：{ck.total}（通过 {ck.passed} / 失败 {ck.failed}）")
    if ck.failed:
        print("❌ 售后场景端到端存在失败断言")
        return 1
    print("✅ 售后场景端到端全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
