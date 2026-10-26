"""M3 审单插件组 A —— 准入/黑白名单/商品/地址/价格"""

from __future__ import annotations

from typing import Any

from app.core.plugin_chain import (
    LEVEL_BLOCK,
    LEVEL_WARN,
    PluginResult,
    Reason,
    RuleContext,
)
from app.core.rule_engine import register_dimensions  # noqa: F401  （维度字典在 audit_rule.py 注册）
from app.modules.m3_trade.service.audit_plugin_base import (
    BasePlugin,
)


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