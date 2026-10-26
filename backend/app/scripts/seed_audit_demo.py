"""审单演示数据装配（W5 界面演示用）

造一批**待审订单**：不同原因类型（地址/缺货/大额/留言），走投审 → 落原因 → 分派 → 进队列。
让工作台界面有真实可操作的内容。

用法：
    cd backend && .venv/bin/python -m app.scripts.seed_audit_demo
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select, text

from app.core.db import AuthContext, SessionFactory, engine, set_auth_context
from app.models.order import OrdOrder
from app.modules.m1_master.service.master import get_redis
from app.modules.m3_trade.service.audit_engine import AuditEngine, register_audit_chain
from app.modules.m3_trade.service.audit_plugins import register_audit_plugins
from app.modules.m3_trade.service.audit_rule import AuditRuleService
from app.modules.m4_fulfill.service.dispatch import DispatchService

#: 演示用地址（覆盖正常/异常两类）
ADDR_NORMAL = ("广东省", "深圳市", "南山区", "科技园南路88号A座1203")
ADDR_BAD = ("", "", "", "")
ADDR_SHORT = ("北京市", "北京市", "朝阳区", "")


async def main() -> int:
    register_audit_chain()
    register_audit_plugins()
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    redis = await get_redis()

    async with SessionFactory() as s:
        # 取一批已有订单（不同实付金额与留言状态）
        orders = list(
            await s.scalars(
                select(OrdOrder).where(OrdOrder.is_deleted == 0).order_by(OrdOrder.id).limit(12)
            )
        )
        if not orders:
            print("[FAIL] 库里没有订单，先跑 scenario_e2e 造数")
            return 1
        print(f"取到 {len(orders)} 张订单，开始投审装配…\n")

        engine_svc = AuditEngine(s, redis, AuditRuleService())
        dispatch = DispatchService(s, redis)
        made = 0
        for i, order in enumerate(orders):
            # 造差异化场景：改地址 / 缺货 / 大额 / 留言
            scenario = ["addr_bad", "addr_short", "memo", "amount"][i % 4]
            if scenario == "addr_bad":
                await s.execute(
                    text("UPDATE oms_order.ord_receiver SET province='', city='', district='' "
                         "WHERE order_id=:oid"),
                    {"oid": order.id},
                )
            elif scenario == "addr_short":
                await s.execute(
                    text("UPDATE oms_order.ord_receiver SET province=:p, city=:c, district=:d "
                         "WHERE order_id=:oid"),
                    {"p": "北京市", "c": "北京市", "d": "朝阳区", "oid": order.id},
                )
            elif scenario == "memo":
                order.buyer_memo = "发顺丰到付，谢谢"
            elif scenario == "amount":
                order.paid_amount = 1500.0
            # 重置审单状态（允许重复投审）
            order.audit_status = "pending"
            order.fulfill_status = "pending"
            await s.commit()

            outcome = await engine_svc.submit(order.id, batch_no=order.batch_no)
            # 有 BLOCK 原因 → 分派进队列
            if outcome.blocked:
                res = await dispatch.auto(order.id, outcome.reason_codes)
                made += 1
                print(f"  · {order.order_bn:<20} 决策={outcome.decision:<10} "
                      f"原因={','.join(outcome.reason_codes) or '-':<40} "
                      f"分派={res.route}/op={res.assign_op}")
            else:
                print(f"  · {order.order_bn:<20} 决策={outcome.decision:<10} "
                      f"（自动通过，不进人工队列）")

        print(f"\n共装配 {made} 张待审订单进工作台队列")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
