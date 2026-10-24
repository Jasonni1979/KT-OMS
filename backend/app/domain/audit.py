"""审单插件链最小实现（M0.6 spike / SRS-D03.02 五段插件链 + D01.03 规则引擎承载）

设计要点（对齐 SRS-D03.02）：
- 插件注册表：@register_plugin 装饰器登记，order() 决定执行序（对应商派 omeauto 插件位）
- 五段编排：风控段(CHECK短路) → 拦截段 → 校验段(CHECK不短路,收集全部原因) → 决策段 → 裁决段
- 决策与执行分离：插件链产出 FulfillPlan（履约方案），不落库不生成发货单（执行器另做）
- 结构化审核原因：AuditReason 替代商派位标记
- 短路规则：风控/拦截段任一 HOLD 即短路；校验段跑完收集全部原因（一次带全问题清单）
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Protocol


class Stage(enum.Enum):
    """五段（SRS-D03.02 FR-01b）"""
    RISK = "risk"          # 风控段：短路
    INTERCEPT = "intercept"  # 拦截段：短路
    CHECK = "check"        # 校验段：不短路，收集全部 HOLD
    DECISION = "decision"  # 决策段：选仓/拆单/物流/合单
    VERDICT = "verdict"    # 裁决段：auto_pass 终判


class Result(enum.Enum):
    PASS = "pass"
    HOLD = "hold"          # 挂起转人工
    SHORT_CIRCUIT = "short_circuit"


@dataclass
class AuditReason:
    """结构化审核原因（替代商派位标记，SRS-D03.02 契约）"""
    plugin: str
    code: str
    level: str = "BLOCK"   # BLOCK / WARN
    message: str = ""


@dataclass
class OrderContext:
    """审单上下文（canonical 订单 + 决策产物）"""
    order_id: str
    shop_id: int
    owner_id: int
    amount: float
    receiver_mobile: str = ""
    receiver_address: str = ""
    items: list[dict] = field(default_factory=list)
    # 决策段产物（FulfillPlan 雏形）
    selected_branch: int | None = None
    split_plan: list[dict] = field(default_factory=list)
    logistics: str | None = None
    auto_passed: bool = False
    reasons: list[AuditReason] = field(default_factory=list)


class AuditPlugin(Protocol):
    """插件接口（对应商派 lib/auto/plugin 的插件位）"""
    name: str
    stage: Stage
    order: int

    def process(self, ctx: OrderContext) -> Result: ...


# ---------- 插件注册表（D01.03 注册表机制；对应商派 whitelist 声明式） ----------
_REGISTRY: list[AuditPlugin] = []


def register_plugin(cls: type) -> type:
    """装饰器注册：新增插件=实现接口+加装饰器，不改链代码（SRS-D03.02 可插拔）"""
    inst = cls()
    _REGISTRY.append(inst)
    _REGISTRY.sort(key=lambda p: (list(Stage).index(p.stage), p.order))
    return cls


# ---------- 8 个核心插件（M0 最小集；M2 补全 D03.02 全部插件位） ----------
@register_plugin
class BlacklistCheck:
    name, stage, order = "blacklist_check", Stage.RISK, 10

    def process(self, ctx: OrderContext) -> Result:
        if ctx.receiver_mobile in BLACKLIST_MOCK:
            ctx.reasons.append(AuditReason(self.name, "BLACKLIST", message="命中黑名单"))
            return Result.SHORT_CIRCUIT
        return Result.PASS


@register_plugin
class PurchaseLimitCheck:
    name, stage, order = "purchase_limit", Stage.RISK, 20

    def process(self, ctx: OrderContext) -> Result:
        # M0 桩：限购规则（D03.02 V1.2 插件），此处仅占位
        return Result.PASS


@register_plugin
class DuplicateCheck:
    name, stage, order = "duplicate_check", Stage.INTERCEPT, 10

    def process(self, ctx: OrderContext) -> Result:
        return Result.PASS


@register_plugin
class AddressCheck:
    name, stage, order = "address_check", Stage.CHECK, 10

    def process(self, ctx: OrderContext) -> Result:
        if len(ctx.receiver_address) < 6:
            ctx.reasons.append(AuditReason(self.name, "ADDRESS_INVALID", message="地址过短/不全"))
            return Result.HOLD
        return Result.PASS


@register_plugin
class PriceCheck:
    name, stage, order = "price_check", Stage.CHECK, 20

    def process(self, ctx: OrderContext) -> Result:
        if ctx.amount <= 0:
            ctx.reasons.append(AuditReason(self.name, "PRICE_ABNORMAL", message="成交价异常"))
            return Result.HOLD
        return Result.PASS


@register_plugin
class StockCheck:
    name, stage, order = "stock_check", Stage.CHECK, 30

    def process(self, ctx: OrderContext) -> Result:
        # M0 桩：缺货校验（真实走 D04.03 reserve；此处模拟有货）
        return Result.PASS


@register_plugin
class WarehouseDecision:
    name, stage, order = "warehouse_select", Stage.DECISION, 10

    def process(self, ctx: OrderContext) -> Result:
        ctx.selected_branch = 1  # M0 桩：单仓；M2 走 D03.06 分仓规则
        return Result.PASS


@register_plugin
class LogisticsDecision:
    name, stage, order = "logistics_match", Stage.DECISION, 20

    def process(self, ctx: OrderContext) -> Result:
        ctx.logistics = "SF"  # M0 桩：默认顺丰；M2 走 D09.04 区域路由
        return Result.PASS


@register_plugin
class AutoPassVerdict:
    name, stage, order = "auto_pass", Stage.VERDICT, 99

    def process(self, ctx: OrderContext) -> Result:
        # 裁决段：无 BLOCK 级原因 → 自动通过，产出 plan
        if not any(r.level == "BLOCK" for r in ctx.reasons):
            ctx.auto_passed = True
        return Result.PASS


BLACKLIST_MOCK: set[str] = set()


class AuditEngine:
    """审单引擎：执行插件链（决策与执行分离——只产出 plan，不落库）"""

    def __init__(self, plugins: list[AuditPlugin] | None = None):
        self.plugins = plugins if plugins is not None else list(_REGISTRY)

    def audit(self, ctx: OrderContext) -> OrderContext:
        for plugin in self.plugins:
            result = plugin.process(ctx)
            # 风控/拦截段短路：立即停止
            if result == Result.SHORT_CIRCUIT:
                ctx.auto_passed = False
                break
            # 校验段 HOLD 不短路（继续跑完收集全部原因），但标记不可自动通过
            if result == Result.HOLD:
                ctx.auto_passed = False
        return ctx


def registered_plugins() -> list[tuple[str, str, int]]:
    return [(p.name, p.stage.value, p.order) for p in _REGISTRY]
