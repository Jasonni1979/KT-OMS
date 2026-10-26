"""AuditSubmitMixin —— 由 AuditEngine 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.plugin_chain import (
    LEVEL_BLOCK,
    Reason,
    RuleContext,
    run_chain,
)
from app.models.audit import (
    OrdAuditPluginPerf,
    OrdAuditReason,
    OrdFulfillPlan,
)
from app.modules.m3_trade.service.audit_models import (
    AuditContextData,
    AuditOutcome,
    _num,  # noqa: F401
    _plugin_params,  # noqa: F401
)
from app.modules.m3_trade.service.audit_plugins import CHAIN_ID
from app.modules.m3_trade.service.audit_rule import AuditRule

logger = get_logger("audit")


class AuditSubmitMixin:
    """AuditEngine 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Redis
    rule_service: Any

    # ---------- 主入口 ----------

    async def submit(
        self,
        order_id: int,
        *,
        batch_no: str = "",
        decision_by: str = "auto",
        dry_run: bool = False,
    ) -> AuditOutcome:
        """投审（IF-D03.02-01：MQ 消费入口；幂等 batch_no+order 锁）"""
        t0 = time.perf_counter()
        ctx_data = await self.load_context(order_id)
        # 物流候选需先知道选中的仓 → 延后到链内由 logi_match 插件按仓查
        # 但插件上下文装载在链执行前，这里用候选仓首个做物流候选预载
        candidates = ctx_data.meta.get("branch_candidates") or []
        if candidates:
            ctx_data.meta["logistics_candidates"] = await self._logistics_candidates(
                int(candidates[0].get("branch_id", 0) or 0)
            )

        # 规则匹配（FR-03b）
        await self.rule_service.load(self.s)
        rule = self.rule_service.match(ctx_data.dims)
        if rule.in_exclude_window():
            # SC-07：排除时段内 autoConfirm 被压制，决策照跑
            rule = rule.degraded()

        # 构造插件链上下文
        ctx = RuleContext(
            data={**ctx_data.dims, **{k: v for k, v in ctx_data.order.items() if k != "id"}},
            decision={},
            dry_run=dry_run,
            meta={
                **ctx_data.meta,
                "batch_no": batch_no or ctx_data.order.get("batch_no", ""),
                "order_id": order_id,
                "plugin_params": _plugin_params(rule),
            },
        )
        ctx.data["items"] = ctx_data.items  # type: ignore[assignment]

        # 执行插件链
        chain_result = await run_chain(
            CHAIN_ID, ctx, plugin_config=rule.plugin_config or None
        )

        # 决策（FR-05a）
        decision_ctx = {
            "branch": ctx.decision.get("branch"),
            "split_groups": ctx.decision.get("split_groups", []),
            "logistics": ctx.decision.get("logistics"),
            "stock_snapshot": ctx.decision.get("stock_snapshot", []),
            "branch_candidates": ctx.decision.get("branch_candidates", []),
            "logistics_candidates": ctx.decision.get("logistics_candidates", []),
        }
        outcome = AuditOutcome(
            order_id=order_id,
            order_bn=ctx_data.order["order_bn"],
            batch_no=batch_no or ctx_data.order.get("batch_no", ""),
            decision="manual",
            reasons=chain_result.reasons,
            traces=[t.to_dict() for t in chain_result.traces],
            rule_id=rule.id,
            rule_name=rule.rule_name,
            rule_snapshot_id=rule.snapshot(),
            decision_ctx=decision_ctx,
        )

        # 落结构化原因（FR-04a：先归档旧批次再写新）
        if chain_result.reasons:
            await self.write_reasons(order_id, outcome.batch_no, chain_result.reasons, ctx_data)
            outcome.decision = self._route(chain_result.reasons)

        # 产出 plan（FR-05b：plan 先落库，执行异步）
        if not chain_result.blocked and rule.auto_confirm_effective():
            plan = await self.save_plan(outcome, rule, decision_by=decision_by, draft=False)
            outcome.plan_id = plan.id
            outcome.plan_bn = plan.plan_bn
            outcome.decision = "auto_pass"
        elif not chain_result.blocked:
            # 决策草稿随单（人工确认即执行）
            plan = await self.save_plan(outcome, rule, decision_by=decision_by, draft=True)
            outcome.plan_id = plan.id
            outcome.plan_bn = plan.plan_bn
            outcome.decision = "manual"

        # 插件耗时 + 批次日志（FR-01e / FR-06c）
        await self.write_perf(outcome, chain_result)
        outcome.cost_ms = int((time.perf_counter() - t0) * 1000)
        return outcome

    # ---------- 原因路由（FR-05 §5.4） ----------

    def _route(self, reasons: list[Reason]) -> str:
        """按原因码默认路由（字典缺省路由优先）"""
        from app.core.dicts import DICTS

        for r in reasons:
            if r.level != LEVEL_BLOCK:
                continue
            item = DICTS.get("audit_reason_code", r.code)
            route = r.route_target or (item.default_route if item else "")
            if route in ("shortage", "shortage_hold"):
                return "shortage"
            if route == "retrial":
                return "retrial"
            if route == "pool":
                return "pool"
            if route == "hold":
                return "hold"
        return "manual"

    # ---------- 原因落库 ----------

    async def write_reasons(
        self,
        order_id: int,
        batch_no: str,
        reasons: list[Reason],
        ctx_data: AuditContextData,
    ) -> int:
        """写结构化原因（FR-04c：重审先清旧原因再写新）"""
        # 归档旧批次（历史可查）
        await self.s.execute(
            select(OrdAuditReason).where(OrdAuditReason.order_id == order_id)
        )
        old = list(
            await self.s.scalars(
                select(OrdAuditReason).where(OrdAuditReason.order_id == order_id)
            )
        )
        for o in old:
            await self.s.delete(o)
        for r in reasons:
            self.s.add(
                OrdAuditReason(
                    order_id=order_id,
                    batch_no=batch_no,
                    plugin_name=r.plugin,
                    reason_code=r.code,
                    level=r.level,
                    description=r.description[:1024],
                    detail=r.detail or None,
                    suggest_action=r.suggest_action,
                    route_target=r.route_target,
                    handle_status="open",
                    shop_id=int(ctx_data.order.get("shop_id", 0) or 0),
                    owner_id=int(ctx_data.order.get("owner_id", 0) or 0),
                )
            )
        await self.s.commit()
        # FR-03a：审单不通过 → 按原因码字典落异常单
        #   落单与否由字典决定（exc_type 为空 / need_abnormal_bill=0 → 不落单），
        #   避免异常池泛滥；缺货类同时落缺货明细（FR-04a）。
        await self._raise_abnormals(order_id, reasons)
        return len(reasons)

    async def _raise_abnormals(
        self, order_id: int, reasons: list[Reason]
    ) -> int:
        """按结构化原因落异常单（FR-03a）"""
        from app.modules.m5_abnormal.contract import AbnormalService

        svc = AbnormalService(self.s, self.r)
        raised = 0
        for r in reasons:
            try:
                row, _created = await svc.raise_by_reason(
                    order_id=order_id,
                    reason_code=r.code,
                    source="audit",
                    source_ref=f"{r.plugin}:{r.code}",
                    detail=r.detail or {},
                )
            except Exception as e:  # noqa: BLE001 —— 落单失败不阻断审单主流程
                logger.warning(
                    "abnormal_raise_failed", detail=str(e), order_id=order_id, code=r.code
                )
                continue
            if row is not None:
                raised += 1
        return raised

    # ---------- plan 落库 ----------

    async def save_plan(
        self,
        outcome: AuditOutcome,
        rule: AuditRule,
        *,
        decision_by: str,
        draft: bool,
    ) -> OrdFulfillPlan:
        """落 plan（FR-05a 四要素 + 溯源；FR-05d 版本链）"""
        version = 1
        prev = await self.s.scalar(
            select(OrdFulfillPlan)
            .where(OrdFulfillPlan.order_id == outcome.order_id)
            .order_by(OrdFulfillPlan.plan_version.desc())
            .limit(1)
        )
        if prev is not None:
            version = int(prev.plan_version) + 1
            # 旧 plan 置废弃（FR-05d）
            prev.plan_status = "discarded"
            prev.exec_status = "discarded"
        plan = OrdFulfillPlan(
            owner_id=int(outcome.decision_ctx.get("owner_id", 0) or 0),
            plan_bn=f"PL{datetime.now():%y%m%d}{outcome.order_id:06d}v{version}",
            order_id=outcome.order_id,
            order_ids=[outcome.order_id],
            plan_version=version,
            warehouse_alloc=outcome.decision_ctx.get("branch") or {},
            split_matrix={"groups": outcome.decision_ctx.get("split_groups", [])},
            logistics_alloc=outcome.decision_ctx.get("logistics") or {},
            combine_group=None,
            rule_snapshot_id=outcome.rule_snapshot_id,
            plugin_trace={"traces": outcome.traces, "reasons": [r.to_dict() for r in outcome.reasons]},
            decision_by=decision_by,
            decision_time=datetime.now(),
            plan_status="draft" if draft else "pending",
            exec_status="waiting",
            shop_id=int(outcome.decision_ctx.get("shop_id", 0) or 0),
        )
        # owner/shop 兜底：从上下文补
        if not plan.owner_id:
            plan.owner_id = 0
        self.s.add(plan)
        await self.s.flush()
        await self.s.commit()
        return plan

    # ---------- 插件耗时 + 批次日志 ----------

    async def write_perf(self, outcome: AuditOutcome, chain_result: Any) -> None:
        for t in chain_result.traces:
            self.s.add(
                OrdAuditPluginPerf(
                    batch_no=outcome.batch_no,
                    order_id=outcome.order_id,
                    plugin_name=t.plugin,
                    phase=t.phase,
                    cost_ms=t.cost_ms,
                    result=t.status,
                    reason_codes=",".join(t.reason_codes)[:512] or None,
                )
            )
        await self.s.commit()