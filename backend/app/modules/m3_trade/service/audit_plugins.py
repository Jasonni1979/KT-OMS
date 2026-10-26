"""审单插件实现集（D03.02 FR-02：核心插件位）

W5 范围：核心 8 插件 + auto_pass（计划 §M2 W5 明确列出）。
其余插件位（admit_special/admit_pay/goods_match/gift_check/invoice_check/
amount_check/routernum/label_mark/purchase_limit/combine_check）在 W6+ 按需补齐，
插件位注册表保证新增不改引擎代码（D01.03 FR-03b / D03.02 AC-13）。

插件清单（W5 已实现）：
| 插件 | 段 | 职责 |
|---|---|---|
| admit_status   | ADMIT | 订单硬状态校验（暂停/异常/取消） |
| blacklist     | ADMIT | 黑名单/风控名单匹配（收货手机/地址/买家账号） |
| branch_select | WAREHOUSE | 选仓：平台指定仓 > 分仓规则 > 唯一发货仓 |
| split         | WAREHOUSE | 拆单：调 D03.04 策略（本期实现仓/货主维度基础版） |
| stock_check   | STOCK | 库存校验：按拆单方案逐组查可用（D04.02） |
| logi_match    | LOGISTICS | 物流匹配：仓-物流绑定 + 区域可达 + 重量段 |
| address_check | CHECK | 地址质量：区划可解析/详址长度/敏感词 |
| price_check   | CHECK | 价格校验：行实付 vs 底价红线（缺失降级成本倍数粗校验） |
| auto_pass     | CHECK | 自动审核通过判定（末位） |
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.plugin_chain import (
    LEVEL_BLOCK,
    LEVEL_WARN,
    PluginResult,
    Reason,
    RuleContext,
)
from app.core.rule_engine import register_dimensions  # noqa: F401  （维度字典在 audit_rule.py 注册）

#: 插件链 ID
CHAIN_ID = "order.audit"

#: 段序（FR-01b：段间顺序不可调，依赖关系固定）
PHASES = [
    ("ADMIT", True),        # 准入：任一 HOLD 短路
    ("WAREHOUSE", True),    # 仓：选仓/拆单
    ("STOCK", True),        # 库存校验
    ("LOGISTICS", True),    # 物流匹配
    ("CHECK", False),       # 校验类：不短路（跑完收集全部原因）
]


@dataclass
class SplitGroup:
    """拆单组（发货单维度）"""

    group_key: str
    branch_id: int
    owner_id: int
    #: [(行 ID, 数量, 基础物料 ID, 货号)]
    lines: list[tuple[int, int, int, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_key": self.group_key,
            "branch_id": self.branch_id,
            "owner_id": self.owner_id,
            "lines": [
                {"item_id": i, "nums": n, "bm_id": bm, "material_bn": bn}
                for i, n, bm, bn in self.lines
            ],
        }


class BasePlugin:
    """插件基类（统一 name/phase/order 接口）"""

    PLUGIN_NAME = ""
    PHASE = ""
    ORDER = 100

    def name(self) -> str:
        return self.PLUGIN_NAME

    def phase(self) -> str:
        return self.PHASE

    def order(self) -> int:
        return self.ORDER

    def params(self, ctx: RuleContext) -> dict[str, Any]:
        """插件参数（FR-01d：规则 plugin_config 覆盖 + 全局默认）"""
        cfg = ctx.meta.get("plugin_params", {}).get(self.PLUGIN_NAME, {})
        return {**self.default_params(), **(cfg.get("params") or {})}

    def default_params(self) -> dict[str, Any]:
        return {}


class AdmitStatusPlugin(BasePlugin):
    """admit_status（ADMIT）：订单硬状态校验"""

    PLUGIN_NAME = "admit_status"
    PHASE = "ADMIT"
    ORDER = 10

    def default_params(self) -> dict[str, Any]:
        return {"blocked_status": ["cancelled", "abnormal", "paused"]}

    async def process(self, ctx: RuleContext) -> PluginResult:
        status = str(ctx.get("order_status", "") or "")
        audit_status = str(ctx.get("audit_status", "") or "")
        blocked = set(self.params(ctx)["blocked_status"])
        if status in blocked:
            return PluginResult.hold([
                Reason(
                    plugin=self.PLUGIN_NAME,
                    code="ABNORMAL_ORDER_STATUS",
                    level=LEVEL_BLOCK,
                    description=f"订单状态异常（{status}），不可审单",
                    detail={"order_status": status, "audit_status": audit_status},
                    suggest_action="人工审核",
                    route_target="manual",
                )
            ])
        if ctx.get("is_pause"):
            return PluginResult.hold([
                Reason(
                    plugin=self.PLUGIN_NAME,
                    code="ORDER_PAUSED",
                    level=LEVEL_BLOCK,
                    description="订单已暂停，不可审单",
                    detail={"is_pause": 1},
                    suggest_action="人工审核",
                    route_target="manual",
                )
            ])
        return PluginResult.pass_()


class BlacklistPlugin(BasePlugin):
    """blacklist（ADMIT）：黑名单/风控名单匹配

    名单来源：bas_rule_dict 中 dict_type='audit_blacklist' 的 ext_json（手机/地址/买家账号）。
    P0 用规则字典承载（MVP 期黑名单量小；后续可接 D03.09 风控服务）。
    """

    PLUGIN_NAME = "blacklist"
    PHASE = "ADMIT"
    ORDER = 20

    async def process(self, ctx: RuleContext) -> PluginResult:
        entries: list[dict[str, Any]] = ctx.meta.get("blacklist_entries", []) or []
        if not entries:
            return PluginResult.pass_()
        mobile = str(ctx.get("receiver_mobile_hash", "") or "")
        address = str(ctx.get("receiver_address_hash", "") or "")
        buyer = str(ctx.get("buyer_id", "") or "")
        for e in entries:
            hit_dim = e.get("dim")
            hit_val = str(e.get("value", "") or "")
            actual = {"mobile": mobile, "address": address, "buyer": buyer}.get(str(hit_dim), "")
            if actual and hit_val and actual == hit_val:
                return PluginResult.hold([
                    Reason(
                        plugin=self.PLUGIN_NAME,
                        code="BLACKLIST_HIT",
                        level=LEVEL_BLOCK,
                        description=f"命中黑名单（{e.get('label', hit_dim)}）",
                        detail={"dim": hit_dim, "entry": e},
                        suggest_action="复审",
                        route_target="retrial",
                    )
                ])
        return PluginResult.pass_()



class GoodsMatchPlugin(BasePlugin):
    """goods_match（CHECK）：商品绑定校验（W8-2b 补齐）

    **为什么补**：D03.09 的 `PRODUCT_UNBOUND`（商品未绑定）异常类型在字典与
    原因码表里都已配置（`ord_reason_code_dict.GOODS_UNBOUND → PRODUCT_UNBOUND`），
    但审单插件链里**没有任何插件产出该原因码** → 未绑定商品永远不会落异常单，
    FR-03a 的映射形同虚设。本插件补上这条产出路径。

    判定口径：**订单行未绑定基础物料**（`bm_id = 0`）→ 商品未绑定。
    虚拟/赠品行不参与判定（无实物库存需求）。

    路由：BLOCK → 转人工（挂起等人工建档），建议动作 = 绑定商品。
    """

    PLUGIN_NAME = "goods_match"
    # ⚠ 链段只有 ADMIT/WAREHOUSE/STOCK/LOGISTICS/CHECK —— 没有 DATA 段
    #   （DATA 是 branch_select 插件自声明的段名，实际不在 PHASES 里）
    #   故归入 CHECK 段：不短路、可与其他校验原因一并收集。
    PHASE = "CHECK"
    ORDER = 5

    def default_params(self) -> dict[str, Any]:
        return {
            # 是否把赠品/虚拟品也判为未绑定（默认否）
            "check_gift": False,
            "check_virtual": False,
        }

    async def process(self, ctx: RuleContext) -> PluginResult:
        items: list[dict[str, Any]] = ctx.meta.get("items", []) or []
        if not items:
            return PluginResult.pass_()
        params = self.params(ctx)
        check_gift = bool(params.get("check_gift"))
        check_virtual = bool(params.get("check_virtual"))

        unbound: list[dict[str, Any]] = []
        for it in items:
            if not check_gift and int(it.get("is_gift", 0) or 0):
                continue
            if not check_virtual and int(it.get("is_virtual", 0) or 0):
                continue
            if int(it.get("bm_id", 0) or 0) > 0:
                continue
            unbound.append(
                {
                    "item_id": int(it.get("id", 0) or 0),
                    "platform_sku_code": str(it.get("platform_sku_code", "") or ""),
                    "bm_number": str(it.get("bm_number", "") or ""),
                    "bm_name": str(it.get("bm_name", "") or ""),
                    "nums": int(it.get("nums", 0) or 0),
                    "parse_status": str(it.get("parse_status", "") or ""),
                }
            )
        if not unbound:
            return PluginResult.pass_()
        return PluginResult.hold(
            [
                Reason(
                    plugin=self.PLUGIN_NAME,
                    code="GOODS_UNBOUND",
                    level=LEVEL_BLOCK,
                    description=(
                        f"商品未绑定基础物料：{len(unbound)} 行未绑定"
                    ),
                    detail={"unbound": unbound},
                    suggest_action="绑定商品",
                    route_target="manual",
                )
            ]
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
        from app.modules.m4_fulfill.contract import DispatchService_dispatch_service as DispatchService

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


class AddressCheckPlugin(BasePlugin):
    """address_check（CHECK）：地址质量（不短路段——跑完收集全部原因）

    校验项：区划可解析 / 详址长度 / 敏感词 / 禁运区。
    V1.2 的地图 API 智能校验（P0 不接外部 API，降级为规则校验）。
    """

    PLUGIN_NAME = "address_check"
    PHASE = "CHECK"
    ORDER = 10

    def default_params(self) -> dict[str, Any]:
        return {"min_address_len": 5, "sensitive_words": ["代收", "测试", "空号"], "forbidden": []}

    async def process(self, ctx: RuleContext) -> PluginResult:
        p = self.params(ctx)
        province = str(ctx.get("receiver_province", "") or "")
        city = str(ctx.get("receiver_city", "") or "")
        district = str(ctx.get("receiver_district", "") or "")
        # PIPL：收货详址是密文，插件不可读明文 → 用「是否填写」判据
        # （address_hash 非空 或 密文长度 > 0 → 已填写）
        address_filled = bool(
            str(ctx.get("receiver_address_hash", "") or "")
            or int(ctx.get("receiver_address_len", 0) or 0) > 0
        )
        reasons: list[Reason] = []
        if not province or not city:
            reasons.append(
                Reason(
                    plugin=self.PLUGIN_NAME,
                    code="ADDRESS_INVALID",
                    level=LEVEL_BLOCK,
                    description=f"收货地址区划不可解析（省={province or '空'} 市={city or '空'}）",
                    detail={"province": province, "city": city, "district": district},
                    suggest_action="改地址",
                    route_target="manual",
                )
            )
        if not address_filled:
            reasons.append(
                Reason(
                    plugin=self.PLUGIN_NAME,
                    code="ADDRESS_INVALID",
                    level=LEVEL_BLOCK,
                    description="收货详址缺失（平台密文位为空）",
                    detail={"address_filled": False},
                    suggest_action="改地址",
                    route_target="manual",
                )
            )
        # 敏感词检查（仅区划明文可比对；详址密文不可检 → 由 D03.08 改单页做全文校验）
        for w in p["sensitive_words"]:
            if w and (w in province or w in city or w in district):
                reasons.append(
                    Reason(
                        plugin=self.PLUGIN_NAME,
                        code="ADDRESS_SENSITIVE",
                        level=LEVEL_WARN,
                        description=f"收货区划含敏感词「{w}」",
                        detail={"word": w},
                        suggest_action="人工确认",
                        route_target="manual",
                    )
                )
                break
        for w in p["forbidden"]:
            if w and (w in province or w in city):
                reasons.append(
                    Reason(
                        plugin=self.PLUGIN_NAME,
                        code="ADDRESS_FORBIDDEN",
                        level=LEVEL_BLOCK,
                        description=f"收货地区属禁运区「{w}」",
                        detail={"province": province, "city": city},
                        suggest_action="人工审核",
                        route_target="manual",
                    )
                )
                break
        if reasons:
            return PluginResult.hold(reasons)
        return PluginResult.pass_()


class PriceCheckPlugin(BasePlugin):
    """price_check（CHECK）：价格校验

    V1.5 基准：行实付 vs 下单时点生效底价红线 floor_price（D04.11）；
    **价格档案缺失时降级为成本倍数粗校验（P0 兼容）**。
    """

    PLUGIN_NAME = "price_check"
    PHASE = "CHECK"
    ORDER = 20

    def default_params(self) -> dict[str, Any]:
        return {"max_cost_ratio": 3.0}

    async def process(self, ctx: RuleContext) -> PluginResult:
        p = self.params(ctx)
        max_ratio = float(p["max_cost_ratio"])
        items: list[dict[str, Any]] = ctx.meta.get("items", []) or []
        reasons: list[Reason] = []
        for it in items:
            paid = float(it.get("paid_amount", 0) or 0)
            floor_price = float(it.get("floor_price", 0) or 0)
            cost = float(it.get("unit_cost", 0) or 0)
            nums = int(it.get("nums", 0) or 0)
            line_paid = paid if paid else 0
            if floor_price > 0:
                if nums > 0 and line_paid / nums < floor_price:
                    reasons.append(
                        Reason(
                            plugin=self.PLUGIN_NAME,
                            code="PRICE_ABNORMAL",
                            level=LEVEL_BLOCK,
                            description=(
                                f"行实付低于底价红线（{it.get('bm_number', '')}："
                                f"{line_paid / nums:.2f} < {floor_price:.2f}）"
                            ),
                            detail={"item_id": it.get("id"), "paid": line_paid,
                                    "floor_price": floor_price},
                            suggest_action="复审",
                            route_target="retrial",
                        )
                    )
            elif cost > 0:
                if nums > 0 and (line_paid / nums) / cost > max_ratio:
                    reasons.append(
                        Reason(
                            plugin=self.PLUGIN_NAME,
                            code="PRICE_ABNORMAL",
                            level=LEVEL_BLOCK,
                            description=(
                                f"行实付超成本倍数上限（{it.get('bm_number', '')}："
                                f"倍数 {(line_paid / nums) / cost:.2f} > {max_ratio}）"
                            ),
                            detail={"item_id": it.get("id"), "paid": line_paid, "cost": cost},
                            suggest_action="复审",
                            route_target="retrial",
                        )
                    )
        if reasons:
            return PluginResult.hold(reasons)
        return PluginResult.pass_()


class AutoPassPlugin(BasePlugin):
    """auto_pass（CHECK 末位）：自动审核通过判定

    全部插件无 BLOCK 原因 + 规则 autoConfirm=开 + 时间窗允许 → 产出 plan。
    判定逻辑在引擎侧（决策上下文齐备性检查），插件只做兜底校验。
    """

    PLUGIN_NAME = "auto_pass"
    PHASE = "CHECK"
    ORDER = 999

    async def process(self, ctx: RuleContext) -> PluginResult:
        # 决策完整性：仓库 + 拆单 + 物流 + 库存 四要素齐备
        missing: list[str] = []
        if not ctx.decision.get("branch"):
            missing.append("branch")
        if not ctx.decision.get("split_groups"):
            missing.append("split")
        if not ctx.decision.get("logistics"):
            missing.append("logistics")
        if not ctx.decision.get("stock_snapshot"):
            missing.append("stock")
        if missing:
            return PluginResult.hold([
                Reason(
                    plugin=self.PLUGIN_NAME,
                    code="DECISION_INCOMPLETE",
                    level=LEVEL_BLOCK,
                    description=f"决策要素缺失：{','.join(missing)}",
                    detail={"missing": missing},
                    suggest_action="人工审核",
                    route_target="manual",
                )
            ])
        return PluginResult.pass_()


#: W5 插件清单（注册顺序不影响执行顺序——执行顺序由 phase + order 决定）
W5_PLUGINS: list[type[BasePlugin]] = [
    AdmitStatusPlugin,
    BlacklistPlugin,
    GoodsMatchPlugin,
    BranchSelectPlugin,
    SplitPlugin,
    StockCheckPlugin,
    LogiMatchPlugin,
    AddressCheckPlugin,
    PriceCheckPlugin,
    AutoPassPlugin,
]


def build_plugins() -> list[Any]:
    """实例化 W5 插件"""
    return [cls() for cls in W5_PLUGINS]


def register_audit_plugins() -> None:
    """把 W5 插件注册进插件注册表（D01.03 FR-03b：服务发现式注册）

    新增插件 = 加一个 BasePlugin 子类 + 在此登记一行，**不改引擎代码**（AC-13）。
    """
    from app.core.plugin_chain import register_plugin

    for p in build_plugins():
        register_plugin(CHAIN_ID, p)
