"""M3 审单插件组 B —— 分仓/拆单/库存/物流"""

from __future__ import annotations

from typing import Any

from app.core.plugin_chain import (
    LEVEL_BLOCK,
    PluginResult,
    Reason,
    RuleContext,
)
from app.core.rule_engine import register_dimensions  # noqa: F401  （维度字典在 audit_rule.py 注册）
from app.modules.m3_trade.service.audit_plugin_base import (
    BasePlugin,
    SplitGroup,
)


class BranchSelectPlugin(BasePlugin):
    """branch_select（WAREHOUSE）：选仓 → 调 D03.06 配货分仓

    W6 起走真实分仓引擎（DispatchService.dispatch）：
    候选仓生成（平台指定仓 > 货主仓属 ∩ 店铺绑定 > 区域路由 > 全局兜底）
    → 规则命中 → 满足度计算 → 整仓优先/贪心多仓/缺货判定 → plan 落库。

    决策区写入：branch（单仓）/ dispatch_plan（多仓或缺货）/ split_required。
    """

    PLUGIN_NAME = "branch_select"
    PHASE = "WAREHOUSE"
    ORDER = 10

    async def process(self, ctx: RuleContext) -> PluginResult:
        from app.modules.m4_fulfill.contract import (
            DispatchService_dispatch_service as DispatchService,
        )

        order_id = int(ctx.get("order_id", 0) or 0)
        session = ctx.meta.get("session")
        redis = ctx.meta.get("redis")
        if not order_id or session is None or redis is None:
            # 上下文不全（单测直接调用插件）→ 退化到候选仓排序
            candidates: list[dict[str, Any]] = ctx.meta.get("branch_candidates", []) or []
            if not candidates:
                return PluginResult.hold([
                    Reason(
                        plugin=self.PLUGIN_NAME,
                        code="NO_BRANCH",
                        level=LEVEL_BLOCK,
                        description="无可用发货仓（店铺未绑定发货仓）",
                        detail={"shop_id": ctx.get("shop_id")},
                        suggest_action="人工指定仓库",
                        route_target="manual",
                    )
                ])
            # 平台指定仓优先（FR-01a）
            hint = str(ctx.get("warehouse_hint", "") or "").strip()
            picked_c = candidates[0]
            if hint:
                for c in candidates:
                    if str(c.get("branch_bn", "")) == hint or str(
                        c.get("branch_id")
                    ) == hint:
                        picked_c = c
                        break
            else:
                picked_c = sorted(
                    candidates, key=lambda c: c.get("priority", 999)
                )[0]
            return PluginResult.mutate(
                {"branch": picked_c, "branch_candidates": candidates}
            )

        svc = DispatchService(session, redis)
        # 平台指定仓（FR-01a 最高优先级）——hint 来自订单报文
        hint = str(ctx.get("warehouse_hint", "") or "").strip()
        appointed = int(hint) if hint.isdigit() else None
        res = await svc.dispatch(order_id, appointed_branch_id=appointed)

        if not res.ok:
            # 缺货/无候选仓 → 结构化不通过原因（FR-04a 分级）
            code = res.fail_code or "NO_BRANCH"
            detail = dict(res.lack_detail or {})
            detail.update({"plan_id": res.plan_id, "mode": res.mode})
            return PluginResult.hold([
                Reason(
                    plugin=self.PLUGIN_NAME,
                    code=code,
                    level=LEVEL_BLOCK,
                    description=res.fail_message or f"分仓失败：{code}",
                    detail=detail,
                    suggest_action="换仓重试或转缺货流程",
                    route_target="shortage" if res.mode == "lack" else "manual",
                )
            ])

        # 整仓 → 单分支；多仓 → 交下游 split 插件按仓拆
        picked: dict[str, Any] = {}
        for cand in res.candidates:
            if cand.fulfill_rate >= 1.0:
                picked = cand.to_dict()
                break
        return PluginResult.mutate(
            {
                "branch": picked,
                "branch_candidates": [c.to_dict() for c in res.candidates],
                "dispatch_plan": {
                    "plan_id": res.plan_id,
                    "round_no": res.round_no,
                    "mode": res.mode,
                    "alloc": {str(k): v for k, v in res.alloc.items()},
                    "split_required": res.split_required,
                },
                "split_required": res.split_required,
            }
        )

class SplitPlugin(BasePlugin):
    """split（WAREHOUSE）：拆单 → 调 D03.04 拆单策略中心

    W6 起走真实拆单引擎（SplitService.split）：
    加载规则 → 校验策略启用 → 预取上下文（库存视图/分仓 plan）→ 策略纯函数计算
    → **守恒校验** → 产出分配方案（组 = 未来发货单）。

    无拆单规则时退化为「仓 × 货主」基础分组（与 D03.04 FR-06e「不拆是特例」口径一致）。
    """

    PLUGIN_NAME = "split"
    PHASE = "WAREHOUSE"
    ORDER = 20

    async def process(self, ctx: RuleContext) -> PluginResult:
        branch = ctx.decision.get("branch")
        if not branch:
            # 上游 branch_select 已 HOLD → 短路，不会到这里；防御性返回
            return PluginResult.pass_()
        order_id = int(ctx.get("order_id", 0) or 0)
        session = ctx.meta.get("session")
        redis = ctx.meta.get("redis")
        plan = ctx.decision.get("dispatch_plan") or {}

        # 有拆单规则 → 走真实引擎
        rule_id = int(ctx.get("split_rule_id", 0) or 0)
        if rule_id and order_id and session is not None and redis is not None:
            from app.modules.m4_fulfill.contract import SplitService

            svc = SplitService(session, redis)
            context: dict[str, Any] = {
                "branch_plan": {"alloc": plan.get("alloc") or {}},
                "branch_seq": [
                    c.get("branch_id")
                    for c in (ctx.decision.get("branch_candidates") or [])
                    if c.get("branch_id")
                ],
            }
            res = await svc.split(order_id, rule_id, context)
            if not res.ok:
                return PluginResult.hold([
                    Reason(
                        plugin=self.PLUGIN_NAME,
                        code=res.fail_code or "SPLIT_FAIL",
                        level=LEVEL_BLOCK,
                        description=f"拆单失败：{res.fail_code}",
                        detail=res.fail_detail,
                        suggest_action="人工拆单或修正规则",
                        route_target="manual",
                    )
                ])
            return PluginResult.mutate(
                {"split_groups": res.groups, "split_trace_id": res.trace_id}
            )

        # 无规则 → 基础分组（仓 × 货主）
        branch_id = int(branch.get("branch_id", 0) or 0)
        items: list[dict[str, Any]] = ctx.meta.get("items", []) or []
        groups: dict[tuple[int, int], SplitGroup] = {}
        for it in items:
            item_id = int(it.get("id", 0) or 0)
            owner_id = int(it.get("owner_id", 0) or 0)
            bm_id = int(it.get("bm_id", 0) or 0)
            nums = int(it.get("nums", 0) or 0)
            if nums <= 0:
                continue
            key = (branch_id, owner_id)
            g = groups.get(key)
            if g is None:
                g = SplitGroup(
                    group_key=f"G{branch_id}_{owner_id}",
                    branch_id=branch_id,
                    owner_id=owner_id,
                    lines=[],
                )
                groups[key] = g
            g.lines.append((item_id, nums, bm_id, str(it.get("bm_number", "") or "")))
        if not groups:
            return PluginResult.hold([
                Reason(
                    plugin=self.PLUGIN_NAME,
                    code="SPLIT_FAIL",
                    level=LEVEL_BLOCK,
                    description="订单无可发货明细行",
                    detail={"items": len(items)},
                    suggest_action="人工审核",
                    route_target="manual",
                )
            ])
        split_groups = [g.to_dict() for g in groups.values()]
        return PluginResult.mutate({"split_groups": split_groups})

class StockCheckPlugin(BasePlugin):
    """stock_check（STOCK）：库存校验（按拆单方案逐组查可用）

    可用量口径**只取** StockLedgerService.available_of（D04.02 全局唯一公式）。
    缺货 → STOCK_SHORTAGE → 路由 D03.09 缺货流程。
    """

    PLUGIN_NAME = "stock_check"
    PHASE = "STOCK"
    ORDER = 10

    async def process(self, ctx: RuleContext) -> PluginResult:
        from app.core.exceptions import NotFoundError
        from app.modules.m2_stock.contract import StockLedgerService

        groups: list[dict[str, Any]] = ctx.decision.get("split_groups", [])
        if not groups:
            return PluginResult.pass_()
        items_by_id: dict[int, dict[str, Any]] = {
            int(i.get("id", 0) or 0): i for i in (ctx.meta.get("items", []) or [])
        }
        ledger = StockLedgerService(ctx.meta["session"], ctx.meta["redis"])
        shortages: list[dict[str, Any]] = []
        snapshots: list[dict[str, Any]] = []
        for g in groups:
            for line in g.get("lines", []):
                item_id = int(line.get("item_id", 0) or 0)
                need = int(line.get("nums", 0) or 0)
                it = items_by_id.get(item_id, {})
                bm_id = int(it.get("bm_id", 0) or 0)
                owner_id = int(g.get("owner_id", 0) or 0)
                branch_id = int(g.get("branch_id", 0) or 0)
                if bm_id <= 0:
                    shortages.append(
                        {"item_id": item_id, "need": need, "available": 0,
                         "reason": "行未解析（无基础物料）"}
                    )
                    continue
                try:
                    bal = await ledger.get_balance(branch_id, bm_id, owner_id)
                    available = int(bal.available)
                except NotFoundError:
                    # 记账行不存在 = 该三元键无库存 → 可用 0
                    available = 0
                snapshots.append(
                    {"branch_id": branch_id, "bm_id": bm_id,
                     "owner_id": owner_id, "need": need, "available": available}
                )
                if available < need:
                    shortages.append(
                        {"item_id": item_id, "material_bn": it.get("bm_number", ""),
                         "need": need, "available": available,
                         "shortage": need - available}
                    )
        if shortages:
            return PluginResult.hold([
                Reason(
                    plugin=self.PLUGIN_NAME,
                    code="STOCK_SHORTAGE",
                    level=LEVEL_BLOCK,
                    description=(
                        f"库存不足：{len(shortages)} 行缺口，"
                        f"共缺 {sum(s.get('shortage', 0) for s in shortages)} 件"
                    ),
                    detail={"shortages": shortages, "candidate_snapshot": snapshots},
                    suggest_action="等补货",
                    route_target="shortage",
                )
            ])
        return PluginResult.mutate({"stock_snapshot": snapshots})

class LogiMatchPlugin(BasePlugin):
    """logi_match（LOGISTICS）：物流匹配

    候选物流来自上下文 meta.logistics_candidates（D09.04 规则，P0 用仓绑定表基础版）。
    """

    PLUGIN_NAME = "logi_match"
    PHASE = "LOGISTICS"
    ORDER = 10

    async def process(self, ctx: RuleContext) -> PluginResult:
        candidates: list[dict[str, Any]] = ctx.meta.get("logistics_candidates", []) or []
        if not candidates:
            return PluginResult.hold([
                Reason(
                    plugin=self.PLUGIN_NAME,
                    code="NO_LOGISTICS",
                    level=LEVEL_BLOCK,
                    description="无可用物流方案（仓未绑定物流）",
                    detail={"branch_id": ctx.decision.get("branch", {}).get("branch_id")},
                    suggest_action="人工指定物流",
                    route_target="manual",
                )
            ])
        weight = float(ctx.get("order_weight", 0) or 0)
        picked = sorted(
            candidates,
            key=lambda c: (c.get("priority", 999), -c.get("max_weight", 0) if weight else 0),
        )[0]
        return PluginResult.mutate({"logistics": picked, "logistics_candidates": candidates})