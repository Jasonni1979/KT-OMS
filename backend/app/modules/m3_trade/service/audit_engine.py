"""审单引擎主服务（D03.02 FR-01 插件链架构 + FR-04 结构化原因 + FR-05 plan）

**主循环**（SRS-D03.02 §5.1）：
```
submit(group_msg):
    ctx = AuditContext.load(group.orders)      # 只读装载
    rule = RuleCache.match(ctx)                # 18维条件·weight DESC·首个命中·缺省兜底
    if rule.timeWindow.excluded(now):          # 排除时段
        rule = rule.degradeToManual()           # autoConfirm压制, 决策照跑
    plugins = PluginRegistry.chain(rule)       # 5段编排, 段内order, 开关过滤
    for p in plugins:                          # 逐插件执行
        r = p.process(ctx)
        if r in (HOLD, SHORT_CIRCUIT):
            ctx.reasons += r.reasons
            if p.phase != CHECK: break          # CHECK段不短路(FR-01c)
    if ctx.hasBlockReason():
        AuditReasonRepo.write(ctx.reasons)      # 结构化原因(先归档旧批次)
        route(ctx.reasons)                     # 按原因码字典默认路由
    elif rule.autoConfirm and ctx.decisionComplete():
        plan = Plan.build(ctx, rule)            # 四要素+溯源快照
        PlanRepo.save(plan)                     # 决策落库(与执行解耦)
        StatusService.transit(audit=已审核)
    else:
        PlanRepo.saveDraft(plan)                # 决策草稿随单, 人工确认即执行
        dispatchToManual(ctx)
```

**关键设计**：
- 短路规则：ADMIT/WAREHOUSE/STOCK/LOGISTICS 段 HOLD 即短路；**CHECK 段不短路**（全收集原因）
- 决策执行分离：plan 先落库（状态=待执行）→ 执行器异步消费（FR-05b）
- 人工同源执行：executeManualPlan 与自动链路走同一执行器（FR-05f）

⚠ 本文件在 P3（上下文体积治理）中拆分为多个文件；
   此处保留 re-export，**原有 import 路径全部保持可用**。
"""

from __future__ import annotations

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.plugin_chain import (
    ChainSpec,
    PhaseSpec,
)
from app.modules.m3_trade.service.audit_context import AuditContextMixin
from app.modules.m3_trade.service.audit_models import (
    AuditContextData,
    AuditOutcome,
    _num,  # noqa: F401
    _plugin_params,  # noqa: F401
)
from app.modules.m3_trade.service.audit_plugins import CHAIN_ID, PHASES
from app.modules.m3_trade.service.audit_rule import AuditRuleService
from app.modules.m3_trade.service.audit_submit import AuditSubmitMixin

__all__ = [
    "AuditOutcome",
    "AuditContextData",
    "AuditEngine",
    "register_audit_chain",
]


logger = get_logger("audit")

class AuditEngine(AuditContextMixin, AuditSubmitMixin):
    """审单引擎"""

    def __init__(
        self,
        session: AsyncSession,
        redis: Redis,
        rule_service: AuditRuleService | None = None,
    ):
        self.s = session
        self.r = redis
        self.rule_service = rule_service or AuditRuleService()


#: 链声明注册（模块导入时注册一次；插件注册在 audit_plugins 注册入口）
def register_audit_chain() -> None:
    """注册审单链（段序 + 短路策略 + 异常策略）"""
    from app.core.plugin_chain import REGISTRY

    spec = ChainSpec(
        chain_id=CHAIN_ID,
        phases=[PhaseSpec(name=n, short_circuit=sc, exception_policy="strict")
                for n, sc in PHASES],
        plugin_timeout=0.5,
        exception_policy="dual",
    )
    REGISTRY.register_chain(spec)

# ============ 导入即注册（W8-2b 修的真实缺陷）============
# ⚠ **此前只有 seed_audit_demo / audit_e2e 两个脚本手动调用注册**，
#   API 服务与其它脚本都没注册 → 审单一跑就抛 `KeyError: 链未注册: order.audit`，
#   即**审单链路在生产上完全不可用**（E2E 用例恰好自己注册了，把问题盖住了）。
#   注册是幂等的（同名插件覆盖 / 同 chain_id 覆盖），放模块导入期最安全。
def _ensure_audit_chain_registered() -> None:
    """确保审单链与插件已注册（幂等，可重复调用）"""
    from app.core.plugin_chain import REGISTRY

    if REGISTRY.chain_spec(CHAIN_ID) is not None:
        return
    register_audit_chain()
    from app.modules.m3_trade.service.audit_plugins import register_audit_plugins

    register_audit_plugins()

_ensure_audit_chain_registered()
