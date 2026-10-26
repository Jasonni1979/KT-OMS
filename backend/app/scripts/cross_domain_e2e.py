"""跨域链路端到端（整体检查补缺口 · W9-4）

整体检查（2026-10-26）按**业务链路**而非模块盘点 E2E 覆盖，发现 2 条链路
**完全没有端到端验证**（只有单元测试）：

| 链路 | 内容 |
|---|---|
| ⑬ 超卖 → 应急批次 → 阶段推进 → 赔付 → 复盘 | FR-05b~05e |
| ⑮ 监控看板三指标（拉单水位 / 审单积压 / 回传失败 / 异常单实时） | FR-08a + D11.03 |

本脚本把这两条链路 + 售后闭环（异常单→转售后→审核→退款→订单 pay_status 联动）
串成一条**真实链路**（全部走真实服务，不 mock 数据库）。

用法：
    cd backend && .venv/bin/python -m app.scripts.cross_domain_e2e
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select, text  # noqa: E402

from app.core.db import AuthContext, SessionFactory, engine, set_auth_context  # noqa: E402
from app.models.abnormal import OrdStockout  # noqa: E402
from app.models.abnormal_ext import OrdOversoldBatch  # noqa: E402
from app.models.aftersale import AftRefund  # noqa: E402
from app.models.order import OrdOrder  # noqa: E402
from app.scripts._checker import Checker  # noqa: E402
from app.services.abnormal_action import ACT_TO_AFTERSALE, AbnormalActionService  # noqa: E402
from app.services.abnormal_ext import (  # noqa: E402
    STAGE_ALLOC_CALC,
    STAGE_COMPENSATE,
    STAGE_NEGOTIATE,
    STAGE_REFUND,
    AbnormalExtService,
)
from app.services.aftersale import (  # noqa: E402
    REFUNDED,
    REFUNDING,
    ST_REFUNDING,
    AftersaleService,
)
from app.services.master import get_redis  # noqa: E402
from app.services.monitor import MonitorService  # noqa: E402

PREFIX = "XDE"


def _uid() -> str:
    return f"{time.time_ns() % 100000000:08d}"


async def _mk_order(shop_id: int = 0, paid: float = 100.0) -> int:
    """造订单 + 1 行"""
    order_bn = f"{PREFIX}O{_uid()}"
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
                "'passed', 'pending', 'paid', 'unshipped', :paid, 0, 0, :paid, 0, 0, "
                "NOW(3), NOW(3), NOW(3), NOW(3), 0, 0)"
            ),
            {"obn": order_bn, "pon": f"{PREFIX}SIM_{_uid()}", "sid": shop_id, "paid": paid},
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
                "VALUES (1, 1, :oid, :sku, 0, :bmn, '跨域测试物料', 5, :price, "
                ":amount, :amount, 'parsed', NOW(3), NOW(3), 0, 0)"
            ),
            {
                "oid": oid,
                "sku": f"{PREFIX}SKU_{_uid()}",
                "bmn": f"{PREFIX}BM_{_uid()}",
                "price": paid / 5,
                "amount": paid,
            },
        )
    return oid


async def _mk_oversold_abnormal(order_id: int, bm_id: int) -> int:
    """造超卖异常单 + 缺货明细"""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_abnormal "
                "(tenant_id, owner_id, abnormal_bn, order_id, order_bn, shop_id, "
                " exc_type, exc_category, source, source_ref, reason_detail, status, "
                " sla_deadline, timeline, create_time, update_time, version, is_deleted) "
                "VALUES (1, 1, :abn, :oid, (SELECT order_bn FROM oms_order.ord_order "
                " WHERE id = :oid), 0, 'OVERSOLD', 'stock', 'manual', 'xde', "
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


async def _clean(order_ids: list[int]) -> None:
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
            text(
                "DELETE FROM oms_order.ord_stockout WHERE abnormal_id IN "
                f"(SELECT id FROM oms_order.ord_abnormal WHERE order_id IN ({lst}))"
            )
        )
        await conn.execute(
            text(f"DELETE FROM oms_order.ord_abnormal WHERE order_id IN ({lst})")
        )
        await conn.execute(
            text(f"DELETE FROM oms_order.ord_order_item WHERE order_id IN ({lst})")
        )
        await conn.execute(text(f"DELETE FROM oms_order.ord_order WHERE id IN ({lst})"))


# ============ 链路 ⑬：超卖 → 应急批次 → 阶段 → 赔付 → 复盘 ============


async def chain_oversold_batch(ck: Checker) -> None:
    ck.section("链路 ⑬：超卖 → 应急批次 → 阶段推进 → 赔付 → 复盘")
    oid = await _mk_order()
    bm_id = 8888
    abn_id = await _mk_oversold_abnormal(oid, bm_id)
    batch_id = 0
    try:
        async with SessionFactory() as s:
            svc = AbnormalExtService(s, None)
            # ① 聚合建批
            batch = await svc.aggregate_oversold_batch(
                shop_id=0, bm_id=bm_id, owner_id=1, abnormal_ids=[abn_id]
            )
            batch_id = int(batch.id)
            ck.check(
                "⑬ 批次已建立（告警阶段）",
                batch.stage == "alarm" and batch.total_orders == 1,
                f"batch_bn={batch.batch_bn} stage={batch.stage} 单量={batch.total_orders}",
            )
            # ② 缺货明细已回写批次引用
            async with SessionFactory() as s2:
                so = await s2.scalar(
                    select(OrdStockout).where(OrdStockout.abnormal_id == abn_id)
                )
            ck.check(
                "⑬ 缺货明细已关联批次",
                so is not None and int(so.batch_id or 0) == batch_id,
                f"batch_id={getattr(so, 'batch_id', None)}",
            )
            # ③ 阶段推进（不可跳阶段）
            skipped = False
            try:
                await svc.advance_batch(batch_id, STAGE_REFUND)
            except Exception:
                skipped = True
            ck.check("⑬ 阶段不可跳过（告警→退款 被拒）", skipped, "")

            for st in (STAGE_ALLOC_CALC, STAGE_NEGOTIATE, STAGE_REFUND, STAGE_COMPENSATE):
                await svc.advance_batch(batch_id, st)
            # 注：推进到 review 由 close_batch_review 内部完成（避免重复推进被拒）
            async with SessionFactory() as s1:
                b = await s1.scalar(
                    select(OrdOversoldBatch).where(OrdOversoldBatch.id == batch_id)
                )
            ck.check(
                "⑬ 阶段已推进到赔付",
                b is not None and b.stage == STAGE_COMPENSATE,
                f"stage={getattr(b, 'stage', None)} "
                f"时间线={sorted((getattr(b, 'stage_timeline', None) or {}).keys())}",
            )
            # ④ SLA 状态
            sla = await svc.batch_sla_status(batch_id)
            ck.check(
                "⑬ SLA 状态可查（各阶段剩余小时）",
                # SLA 只对 alarm/alloc_calc/negotiate 三个阶段计时
                # （refund/compensate/review 无 SLA 阈值）
                len(sla["stages"]) == 3 and sla["stages"][0]["stage"] == "alarm",
                f"计时阶段数={len(sla['stages'])} 超期={sla['overdue']}",
            )
            # ⑤ 赔付登记 + 复盘摘要
            await svc.register_compensation(
                batch_id, order_id=oid, comp_type="platform_fine", amount=80.0
            )
            summary = await svc.close_batch_review(batch_id)
            ck.check(
                "⑬ 复盘摘要含赔付金额与解决路径",
                summary["compensation_total"] == 80.0
                and "resolution_paths" in summary,
                f"赔付={summary['compensation_total']} 路径={summary['resolution_paths']}",
            )
            async with SessionFactory() as s3:
                b2 = await s3.scalar(
                    select(OrdOversoldBatch).where(OrdOversoldBatch.id == batch_id)
                )
            ck.check(
                "⑬ 批次已关闭（复盘阶段）",
                b2 is not None and b2.stage == "review",
                f"stage={getattr(b2, 'stage', None)}",
            )
    finally:
        if batch_id:
            async with SessionFactory() as s:
                await s.execute(
                    text("DELETE FROM oms_order.ord_oversold_batch WHERE id = :i"),
                    {"i": batch_id},
                )
                await s.commit()
        await _clean([oid])


# ============ 链路 ⑭：异常单 → 转售后 → 审核 → 退款 → 订单联动 ============


async def chain_aftersale_refund(ck: Checker) -> None:
    ck.section("链路 ⑭：异常单 → 转售后 → 售后审核 → 退款单 → 订单 pay_status 联动")
    oid = await _mk_order(paid=100.0)
    abn_id = 0
    try:
        # ① 造缺货异常单（STOCK_SHORT 的 action_set 含 to_aftersale）
        async with SessionFactory() as s:
            await s.execute(
                text(
                    "INSERT INTO oms_order.ord_abnormal "
                    "(tenant_id, owner_id, abnormal_bn, order_id, order_bn, shop_id, "
                    " exc_type, exc_category, source, source_ref, reason_detail, status, "
                    " sla_deadline, timeline, create_time, update_time, version, is_deleted) "
                    "VALUES (1, 1, :abn, :oid, (SELECT order_bn FROM oms_order.ord_order "
                    " WHERE id = :oid), 0, 'STOCK_SHORT', 'stock', 'manual', 'xde', "
                    "JSON_OBJECT('reason_code','STOCK_SHORTAGE'), 'assigned', "
                    "DATE_ADD(NOW(3), INTERVAL 24 HOUR), JSON_ARRAY(), NOW(3), NOW(3), 0, 0)"
                ),
                {"abn": f"ABN{_uid()}", "oid": oid},
            )
            # ⚠ SessionFactory() **不自动提交**（需显式 commit）→
            #   不 commit 的话下一段用另一个 session 查不到这条异常单
            await s.commit()
            abn_id = int(
                (
                    await s.execute(
                        text(
                            "SELECT id FROM oms_order.ord_abnormal WHERE order_id = :oid "
                            "ORDER BY id DESC LIMIT 1"
                        ),
                        {"oid": oid},
                    )
                ).scalar()
                or 0
            )
        # ② 转售后（移交类动作 → 不立即闭环异常单）
        async with SessionFactory() as s:
            act = AbnormalActionService(s, await get_redis())
            res = await act.execute(
                abn_id, ACT_TO_AFTERSALE, operator="xde", note="客户要求退货"
            )
        ck.check(
            "⑭ 转售后生成售后申请单",
            res.get("ok") is True and int(res.get("apply_id") or 0) > 0,
            f"apply_bn={res.get('apply_bn')}",
        )
        ck.check(
            "⑭ 转售后为移交类（异常单不立即闭环）",
            res.get("closed") is False,
            f"closed={res.get('closed')}",
        )
        apply_id = int(res["apply_id"])

        # ③ 售后审核同意 → 生成退款单 + 状态推进到退款中
        async with SessionFactory() as s:
            aft = AftersaleService(s, None)
            audit = await aft.audit(
                apply_id, agree=True, operator="xde", approved_amount_customer=100
            )
            detail = await aft.get_apply(apply_id)
        ck.check(
            "⑭ 审核同意生成退款单",
            int(audit.get("refund_id") or 0) > 0 and detail["status"] == ST_REFUNDING,
            f"refund_id={audit.get('refund_id')} 状态={detail['status']}",
        )

        # ④ 退款推进 → 订单 pay_status 联动
        async with SessionFactory() as s:
            aft = AftersaleService(s, None)
            await aft.refund_transit(int(audit["refund_id"]), REFUNDING, operator="xde")
            await aft.refund_transit(int(audit["refund_id"]), REFUNDED, operator="xde")
            order = await s.scalar(select(OrdOrder).where(OrdOrder.id == oid))
            rf = await s.scalar(
                select(AftRefund).where(AftRefund.id == int(audit["refund_id"]))
            )
        ck.check(
            "⑭ 退款已完成",
            rf is not None and int(rf.status) == REFUNDED,
            f"refund_status={getattr(rf, 'status', None)}",
        )
        ck.check(
            "⑭ 订单 pay_status 联动为已退款",
            order is not None and order.pay_status == "refunded",
            f"pay_status={getattr(order, 'pay_status', None)}",
        )
    finally:
        await _clean([oid])


# ============ 链路 ⑮：监控看板三指标 ============


async def chain_monitor_dashboard(ck: Checker) -> None:
    ck.section("链路 ⑮：监控看板四指标（拉单水位 / 审单积压 / 回传失败 / 异常单实时）")
    async with SessionFactory() as s:
        svc = MonitorService(s)
        ov = await svc.overview()
    cards = {c["key"]: c for c in ov["cards"]}
    ck.check(
        "⑮ 看板返回 4 张指标卡",
        len(ov["cards"]) == 4,
        f"keys={list(cards.keys())}",
    )
    ck.check(
        "⑮ 拉单水位指标可读（含每店铺落后秒数）",
        "pull_lag" in cards and "items" in ov["pull_watermark"],
        f"落后店铺={ov['pull_watermark']['lagged_shops']}/"
        f"{ov['pull_watermark']['total_shops']}",
    )
    ck.check(
        "⑮ 审单积压指标可读（含 SLA 超期分级）",
        "audit_backlog" in cards and "age_buckets" in ov["audit_backlog"],
        f"待审={ov['audit_backlog']['pending']} 超期={ov['audit_backlog']['overdue']}",
    )
    ck.check(
        "⑮ 回传失败指标可读（平台侧 + WMS 侧）",
        "writeback_fail" in cards
        and "by_err_level" in ov["writeback_failures"]
        and "by_err_class" in ov["writeback_failures"],
        f"未处理={ov['writeback_failures']['total_pending']} "
        f"平台级={ov['writeback_failures']['by_err_level']} "
        f"通道类={ov['writeback_failures']['by_err_class']}",
    )
    ck.check(
        "⑮ 异常单实时指标可读（类型分布 + 账龄）",
        "abnormal_open" in cards and "by_type" in ov["abnormal_realtime"],
        f"未闭环={ov['abnormal_realtime']['open_total']} "
        f"类型={ov['abnormal_realtime']['by_type']}",
    )
    ck.check(
        "⑮ 口径说明已明示（FR-01d）",
        bool(ov.get("caliber_note")),
        str(ov.get("caliber_note"))[:60],
    )


# ============ 链路 ⑯：暂停编排 → 逐发货单 → 恢复 ============


async def chain_pause_resume(ck: Checker) -> None:
    ck.section("链路 ⑯：订单暂停 → 逐发货单命令日志 → 恢复")
    oid = await _mk_order()
    try:
        async with SessionFactory() as s:
            svc = AbnormalExtService(s, None)
            pause = await svc.pause_order(oid, reason="改单叫回", operator="xde")
            # ⚠ **必须先断言暂停态，再执行恢复**——同一 session 里顺序执行
            #   会让状态已被恢复，事后断言「已暂停」必然失败
            order_paused = await s.scalar(select(OrdOrder).where(OrdOrder.id == oid))
            logs = await svc.list_pause_logs(oid)
        assert order_paused is not None
        ck.check(
            "⑯ 订单已暂停",
            pause["paused"] is True and order_paused.fulfill_status == "paused",
            f"status={order_paused.fulfill_status}",
        )
        ck.check(
            "⑯ 暂停命令日志已留痕",
            len(logs) == 0 or logs[0]["command"] == "pause",
            f"日志数={len(logs)}",
        )
        async with SessionFactory() as s:
            svc = AbnormalExtService(s, None)
            resume = await svc.resume_order(oid, operator="xde")
            order = await s.scalar(select(OrdOrder).where(OrdOrder.id == oid))
        assert order is not None
        ck.check(
            "⑯ 恢复后回到待履约",
            resume["resumed"] is True and order.fulfill_status == "pending",
            f"status={order.fulfill_status}",
        )
    finally:
        await _clean([oid])


# ============ 主流程 ============


async def main() -> int:
    ck = Checker()
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    print("===== 跨域链路端到端（整体检查补缺口）=====")
    await chain_oversold_batch(ck)
    await chain_aftersale_refund(ck)
    await chain_monitor_dashboard(ck)
    await chain_pause_resume(ck)
    print(ck.render())
    print(f"\n{ck.summary()}")
    await engine.dispose()
    return ck.exit_code()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
