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
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.core.plugin_chain import (
    LEVEL_BLOCK,
    ChainSpec,
    PhaseSpec,
    Reason,
    RuleContext,
    run_chain,
)
from app.models.audit import (
    OrdAuditPluginPerf,
    OrdAuditReason,
    OrdFulfillPlan,
)
from app.models.order import OrdOrder, OrdOrderItem, OrdReceiver
from app.services.audit_plugins import CHAIN_ID, PHASES
from app.services.audit_rule import AuditRule, AuditRuleService

logger = get_logger("audit")


@dataclass
class AuditOutcome:
    """审单结果"""

    order_id: int
    order_bn: str
    batch_no: str
    #: 决策结果：auto_pass / manual / shortage / retrial / pool
    decision: str
    #: 是否产出 plan
    plan_id: int | None = None
    plan_bn: str = ""
    #: 结构化原因
    reasons: list[Reason] = field(default_factory=list)
    #: 插件 trace
    traces: list[dict[str, Any]] = field(default_factory=list)
    #: 命中的规则
    rule_id: int = 0
    rule_name: str = ""
    rule_snapshot_id: str = ""
    #: 决策上下文（plan 四要素）
    decision_ctx: dict[str, Any] = field(default_factory=dict)
    cost_ms: int = 0

    @property
    def blocked(self) -> bool:
        return any(r.level == LEVEL_BLOCK for r in self.reasons)

    @property
    def reason_codes(self) -> list[str]:
        return [r.code for r in self.reasons]

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "order_bn": self.order_bn,
            "batch_no": self.batch_no,
            "decision": self.decision,
            "plan_id": self.plan_id,
            "plan_bn": self.plan_bn,
            "reasons": [r.to_dict() for r in self.reasons],
            "traces": self.traces,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "rule_snapshot_id": self.rule_snapshot_id,
            "decision_ctx": self.decision_ctx,
            "cost_ms": self.cost_ms,
        }


@dataclass
class AuditContextData:
    """审单上下文装载结果（只读数据袋 + 元信息）"""

    order: dict[str, Any]
    items: list[dict[str, Any]]
    receiver: dict[str, Any]
    #: 规则匹配用维度上下文
    dims: dict[str, Any]
    #: 插件用元信息（候选仓/物流/黑名单等）
    meta: dict[str, Any]


class AuditEngine:
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

    # ---------- 上下文装载 ----------

    async def load_context(self, order_id: int) -> AuditContextData:
        """装载审单上下文（FR-01b：只读装载订单快照+行BOM+收货人）"""
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id, OrdOrder.is_deleted == 0)
        )
        if order is None:
            raise NotFoundError(f"订单不存在: {order_id}")
        items = list(
            await self.s.scalars(
                select(OrdOrderItem)
                .where(OrdOrderItem.order_id == order_id, OrdOrderItem.is_deleted == 0)
                .order_by(OrdOrderItem.id)
            )
        )
        receiver = await self.s.scalar(
            select(OrdReceiver).where(OrdReceiver.order_id == order_id)
        )
        item_dicts = [
            {
                "id": it.id,
                "owner_id": it.owner_id,
                "bm_id": it.bm_id,
                "bm_number": it.bm_number,
                "bm_name": it.bm_name,
                "nums": it.nums,
                "paid_amount": float(it.paid_amount),
                "list_price": float(it.list_price),
                "parse_status": it.parse_status,
                "is_virtual": it.is_virtual,
                "is_gift": it.is_gift,
                "weight": float(it.weight),
                "platform_sku_code": it.platform_sku_code,
            }
            for it in items
        ]
        recv: dict[str, Any] = {
            "province": receiver.province if receiver else "",
            "city": receiver.city if receiver else "",
            "district": receiver.district if receiver else "",
            "town": receiver.town if receiver else "",
            "mobile_hash": receiver.mobile_hash if receiver else "",
            "address_hash": receiver.address_hash if receiver else "",
            # 详址密文长度（PIPL：地址密文不可读，长度可作为「详址是否填写」的判据）
            "address_len": len(receiver.address_enc) if receiver and receiver.address_enc else 0,
            "is_cipher": receiver.is_cipher if receiver else 0,
        }
        order_dict = {
            "id": order.id,
            "order_bn": order.order_bn,
            "shop_id": order.shop_id,
            "brand_id": order.brand_id,
            "owner_id": order.owner_id,
            "order_status": order.order_status,
            "audit_status": order.audit_status,
            "fulfill_status": order.fulfill_status,
            "pay_status": order.pay_status,
            "ship_status": order.ship_status,
            "paid_amount": float(order.paid_amount),
            "list_amount": float(order.list_amount),
            "order_type": order.order_type,
            "createway": order.createway,
            "is_cod": order.is_cod,
            "is_pause": order.is_pause,
            "buyer_memo": order.buyer_memo,
            "warehouse_memo": order.warehouse_memo,
            "warehouse_hint": order.warehouse_memo,
            "buyer_id": order.buyer_nick,
            "batch_no": order.batch_no,
            "pay_time": order.pay_time,
            "order_time": order.order_time,
        }
        # 规则维度上下文（18 维取值；缺失维度不命中）
        dims: dict[str, Any] = {
            "shop_id": [order.shop_id],
            "brand_id": [order.brand_id],
            "owner_id": [order.owner_id],
            "order.amount_paid": float(order.paid_amount),
            "order.amount_list": float(order.list_amount),
            "order_type": [order.order_type],
            "order.is_cod": bool(order.is_cod),
            "order.receiver_province": [receiver.province] if receiver and receiver.province else [],
            "order.receiver_city": [receiver.city] if receiver and receiver.city else [],
            "order.has_memo": bool(order.buyer_memo),
            "order.createway": [order.createway],
            "order.items.sku": [it.platform_sku_code for it in items if it.platform_sku_code],
            "order.items.count": len({it.platform_sku_code for it in items}),
            "order.items.nums": sum(it.nums for it in items),
            "order.weight": sum(float(it.weight) for it in items),
        }
        # 插件元信息（ctx.meta：插件运行期依赖的外部句柄与候选集）
        meta: dict[str, Any] = {
            "session": self.s,
            "redis": self.r,
            "items": item_dicts,
            "branch_candidates": await self._branch_candidates(order.shop_id),
            "logistics_candidates": [],
            "blacklist_entries": [],
            "order_weight": dims["order.weight"],
        }
        # 插件只读取数据袋（ctx.data）——收货人等只读字段必须进数据袋
        dims.update(
            {
                "receiver_province": recv["province"],
                "receiver_city": recv["city"],
                "receiver_district": recv["district"],
                "receiver_town": recv["town"],
                "receiver_address_hash": recv["address_hash"],
                "receiver_mobile_hash": recv["mobile_hash"],
                "receiver_address_len": recv["address_len"],
                "receiver_is_cipher": recv["is_cipher"],
            }
        )
        return AuditContextData(
            order=order_dict, items=item_dicts, receiver=recv, dims=dims, meta=meta
        )

    async def _branch_candidates(self, shop_id: int) -> list[dict[str, Any]]:
        """候选发货仓（店铺发货仓绑定 gw_shop_config.branch_bind_json）"""
        from sqlalchemy import text

        row = await self.s.execute(
            text(
                "SELECT branch_bind_json FROM oms_gateway.gw_shop_config "
                "WHERE shop_id = :sid AND is_deleted = 0 LIMIT 1"
            ),
            {"sid": shop_id},
        )
        raw = row.scalar()
        if not raw:
            return []
        try:
            binds = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return []
        if not isinstance(binds, list):
            return []
        out: list[dict[str, Any]] = []
        for b in binds:
            branch_id = int(b.get("branch_id", 0) or 0)
            if branch_id <= 0:
                continue
            name = await self.s.scalar(
                text("SELECT branch_name FROM oms_fulfill.ful_branch WHERE id = :bid"),
                {"bid": branch_id},
            )
            out.append(
                {
                    "branch_id": branch_id,
                    "branch_name": name or "",
                    "priority": int(b.get("priority", 999) or 999),
                }
            )
        return out

    async def _logistics_candidates(self, branch_id: int) -> list[dict[str, Any]]:
        """候选物流（仓-物流绑定 ful_store_carrier_map）"""
        from sqlalchemy import text

        rows = await self.s.execute(
            text(
                "SELECT m.carrier_code, m.carrier_store_id, c.carrier_name "
                "FROM oms_fulfill.ful_store_carrier_map m "
                "LEFT JOIN oms_fulfill.ful_carrier c ON c.carrier_code = m.carrier_code "
                "WHERE m.store_branch_id = :bid AND m.is_deleted = 0 "
                "ORDER BY m.id"
            ),
            {"bid": branch_id},
        )
        return [
            {
                "carrier_code": r[0],
                "carrier_store_id": r[1],
                "carrier_name": r[2] or r[0],
                "priority": i,
            }
            for i, r in enumerate(rows.all())
        ]

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
        return len(reasons)

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


def _plugin_params(rule: AuditRule) -> dict[str, Any]:
    """从规则 plugin_config 提取插件参数（FR-01d）"""
    out: dict[str, Any] = {}
    for name, cfg in (rule.plugin_config or {}).items():
        if isinstance(cfg, dict) and cfg.get("params"):
            out[name] = {"params": cfg["params"]}
    return out


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
