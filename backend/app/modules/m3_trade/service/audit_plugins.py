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

⚠ 本文件在 P3（上下文体积治理）中拆分为多个文件；
   此处保留 re-export，**原有 import 路径全部保持可用**。
"""

from __future__ import annotations

from typing import Any

from app.core.rule_engine import register_dimensions  # noqa: F401  （维度字典在 audit_rule.py 注册）
from app.modules.m3_trade.service.audit_plugin_base import (
    CHAIN_ID,
    PHASES,
    BasePlugin,
    SplitGroup,
)
from app.modules.m3_trade.service.audit_plugins_admit import (
    AddressCheckPlugin,
    AdmitStatusPlugin,
    AutoPassPlugin,
    BlacklistPlugin,
    GoodsMatchPlugin,
    PriceCheckPlugin,
)
from app.modules.m3_trade.service.audit_plugins_fulfill import (
    BranchSelectPlugin,
    LogiMatchPlugin,
    SplitPlugin,
    StockCheckPlugin,
)

__all__ = [
    "CHAIN_ID",
    "PHASES",
    "SplitGroup",
    "BasePlugin",
    "AdmitStatusPlugin",
    "BlacklistPlugin",
    "GoodsMatchPlugin",
    "BranchSelectPlugin",
    "SplitPlugin",
    "StockCheckPlugin",
    "LogiMatchPlugin",
    "AddressCheckPlugin",
    "PriceCheckPlugin",
    "AutoPassPlugin",
    "W5_PLUGINS",
    "build_plugins",
    "register_audit_plugins",
]


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
