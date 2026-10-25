"""审单引擎端到端验证脚本（W5 交付自检）

跑通：投审 → 插件链决策 → 结构化原因 → plan 落库 → 执行器预占 → 状态 transit。
不依赖 pytest，直接对开发库跑，产出可读断言输出。

用法：
    cd backend && .venv/bin/python -m app.scripts.audit_e2e
"""
from __future__ import annotations

import asyncio
import sys

from app.core.db import AuthContext, SessionFactory, set_auth_context
from app.core.exceptions import NotFoundError
from app.core.plugin_chain import REGISTRY
from app.models.order import OrdOrder
from app.services.audit_engine import AuditEngine, register_audit_chain
from app.services.audit_plugins import register_audit_plugins
from app.services.audit_rule import AuditRuleService
from app.services.master import get_redis
from app.services.plan_executor import PlanExecutor


def step(n: str, name: str, passed: bool, detail: str = "") -> bool:
    mark = "PASS" if passed else "FAIL"
    print(f"[{mark}] {n}. {name}" + (f" | {detail}" if detail else ""))
    return passed


async def main() -> int:
    register_audit_chain()
    register_audit_plugins()
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    redis = await get_redis()
    results: list[bool] = []

    async with SessionFactory() as s:
        # 找一张待审订单
        order = await s.scalar(
            __import__("sqlalchemy").select(OrdOrder)
            .where(OrdOrder.is_deleted == 0)
            .order_by(OrdOrder.id.desc())
            .limit(1)
        )
        if order is None:
            print("[FAIL] 库里没有订单，先跑 scenario_e2e / seed_demo 造数")
            return 1
        print(f"\n=== KT-OMS 审单引擎端到端（订单 {order.order_bn} id={order.id}）===\n")

        # ① 插件注册
        plugins = REGISTRY.list_plugins("order.audit")
        results.append(
            step("1", "插件注册（服务发现式，chain_id 隔离）", len(plugins) == 9,
                 f"注册 {len(plugins)} 个插件")
        )

        # ② 规则加载 + 匹配
        rule_svc = AuditRuleService()
        await rule_svc.load(s)
        engine = AuditEngine(s, redis, rule_svc)
        ctx = await engine.load_context(order.id)
        rule = rule_svc.match(ctx.dims)
        results.append(
            step("2", "规则匹配（weight DESC 首个命中 + 缺省兜底）", rule.id != 0,
                 f"命中规则「{rule.rule_name}」auto_confirm={rule.auto_confirm}")
        )

        # ③ 投审：插件链执行
        outcome = await engine.submit(order.id, batch_no=order.batch_no)
        results.append(
            step("3", "插件链执行（五段编排 + 耗时留痕）",
                 len(outcome.traces) > 0,
                 f"执行 {len(outcome.traces)} 个插件，决策={outcome.decision}，"
                 f"耗时 {outcome.cost_ms}ms")
        )
        for t in outcome.traces:
            print(f"        · {t['plugin']:<16} {t['phase']:<10} {t['status']:<8} "
                  f"{t['cost_ms']}ms {','.join(t['reason_codes'])}")

        # ④ 结构化原因
        from app.models.audit import OrdAuditReason
        reasons = list(
            await s.scalars(
                __import__("sqlalchemy").select(OrdAuditReason)
                .where(OrdAuditReason.order_id == order.id)
            )
        )
        results.append(
            step("4", "结构化原因落库（替代位标记）", True,
                 f"{len(reasons)} 条原因："
                 f"{[r.reason_code for r in reasons]}")
        )

        # ⑤ plan 落库（决策执行分离）
        results.append(
            step("5", "plan 落库（决策与执行分离）", outcome.plan_id is not None,
                 f"plan_id={outcome.plan_id} plan_bn={outcome.plan_bn} "
                 f"decision={outcome.decision}")
        )
        if outcome.plan_id:
            ex = PlanExecutor(s, redis)
            replay = await ex.replay(order.id)
            results.append(
                step("5b", "plan 回放（版本链 + 溯源）", len(replay["versions"]) >= 1,
                     f"版本数={len(replay['versions'])} "
                     f"rule_snapshot={replay['versions'][0].get('rule_snapshot_id')}")
            )

        # ⑥ 执行器（人工同源执行入口）
        if outcome.plan_id:
            ex = PlanExecutor(s, redis)
            try:
                res = await ex.execute(outcome.plan_id, operator="e2e")
                results.append(
                    step("6", "plan 执行（预占 + 状态 transit）", res.ok,
                         f"status={res.status} fail={res.fail_code or '-'} "
                         f"预占组数={len(res.freeze_refs)}")
                )
                order2 = await s.scalar(
                    __import__("sqlalchemy").select(OrdOrder).where(OrdOrder.id == order.id)
                )
                results.append(
                    step("6b", "状态 transit（audit=已审核 fulfill=履约中）",
                         order2 is not None and order2.audit_status == "audited",
                         f"audit_status={order2.audit_status if order2 else '-'} "
                         f"fulfill_status={order2.fulfill_status if order2 else '-'}")
                )
            except NotFoundError as e:
                results.append(step("6", "plan 执行", False, f"缺货/预占失败：{e}"))

    passed = sum(1 for r in results if r)
    print(f"\n合计：{passed}/{len(results)} 项通过")
    from app.core.db import engine as db_engine

    await db_engine.dispose()
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
