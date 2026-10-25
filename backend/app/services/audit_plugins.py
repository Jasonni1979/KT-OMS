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


class BranchSelectPlugin(BasePlugin):
    """branch_select（WAREHOUSE）：选仓

    优先级：平台指定仓（order.platform_extra.warehouse_hint 或 warehouse_memo）
    > 店铺发货仓绑定（gw_shop_config.branch_bind_json，D03.06 基础版）
    > 唯一发货仓
    """

    PLUGIN_NAME = "branch_select"
    PHASE = "WAREHOUSE"
    ORDER = 10

    async def process(self, ctx: RuleContext) -> PluginResult:
        candidates: list[dict[str, Any]] = ctx.meta.get("branch_candidates", []) or []
        hint = str(ctx.get("warehouse_hint", "") or "").strip()
        if hint:
            for c in candidates:
                if str(c.get("branch_bn", "")) == hint or str(c.get("branch_id")) == hint:
                    return PluginResult.mutate({"branch": c, "branch_candidates": candidates})
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
        # 候选仓按优先级排序（branch_bind_json 里带 priority）
        picked = sorted(candidates, key=lambda c: c.get("priority", 999))[0]
        return PluginResult.mutate({"branch": picked, "branch_candidates": candidates})


class SplitPlugin(BasePlugin):
    """split（WAREHOUSE）：拆单（本期实现仓/货主维度基础版）

    真实实现调 D03.04 策略注册表（W6）；P0 基础版按「仓 × 货主」分组——
    与 SC-D03.02-04 的拆单语义一致（拆单=发货单维度，订单头不产生新订单）。
    """

    PLUGIN_NAME = "split"
    PHASE = "WAREHOUSE"
    ORDER = 20

    async def process(self, ctx: RuleContext) -> PluginResult:
        branch = ctx.decision.get("branch")
        if not branch:
            # 上游 branch_select 已 HOLD → 短路，不会到这里；防御性返回
            return PluginResult.pass_()
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
        from app.services.stock_ledger import StockLedgerService

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
