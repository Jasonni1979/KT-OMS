"""M3 订单与审单 —— **契约公开面（唯一对外接口）**

⚠ **跨模块 import 只能从本文件导入**（门禁 R2 强制）。
   `service/` 下的实现是内部细节，不对外承诺稳定性 ——
   需要跨模块用的能力，在此显式导出。

本文件由 `tools/gen_module_public_api.py` 生成，请勿手工编辑。
"""
from __future__ import annotations

from app.modules.m3_trade.service.allocation import (
    _TOLERANCE_CENTS,
    TOLERANCE,
    LineAmount,
    allocate,
    check_amount_consistency,
)
from app.modules.m3_trade.service.audit_engine import (
    AuditEngine,
    register_audit_chain,
)
from app.modules.m3_trade.service.audit_models import (
    AuditContextData,
    AuditOutcome,
)
from app.modules.m3_trade.service.audit_plugin_base import (
    CHAIN_ID,
    PHASES,
    BasePlugin,
    SplitGroup,
)
from app.modules.m3_trade.service.audit_plugins import (
    W5_PLUGINS,
    build_plugins,
    register_audit_plugins,
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
from app.modules.m3_trade.service.audit_rule import (
    AUDIT_DIM_GROUP,
    DEFAULT_RULE,
    AuditRule,
    AuditRuleService,
    TimeWindow,
)
from app.modules.m3_trade.service.order_bn import (
    PREFIX_B2B,
    PREFIX_EXCHANGE,
    PREFIX_IMPORT,
    PREFIX_LOCAL,
    PREFIX_PLATFORM,
    PREFIX_RESHIP,
    SEQ_DOMAIN,
    SEQ_SPACE,
    STEP,
    OrderBnGenerator,
    shop_code_of,
)
from app.modules.m3_trade.service.order_create import (
    FAIL_AMOUNT_MISMATCH,
    FAIL_AUTH_EXPIRED,
    FAIL_ITEM_EMPTY,
    FAIL_REQUIRED_MISSING,
    FAIL_SHOP_INVALID,
    SOURCE_PREFIX,
    OrderCreateResult,
    OrderCreateService,
)

__all__ = [
    "LineAmount",
    "TOLERANCE",
    "_TOLERANCE_CENTS",
    "allocate",
    "check_amount_consistency",
    "AuditEngine",
    "register_audit_chain",
    "AuditContextData",
    "AuditOutcome",
    "BasePlugin",
    "CHAIN_ID",
    "PHASES",
    "SplitGroup",
    "W5_PLUGINS",
    "build_plugins",
    "register_audit_plugins",
    "AddressCheckPlugin",
    "AdmitStatusPlugin",
    "AutoPassPlugin",
    "BlacklistPlugin",
    "GoodsMatchPlugin",
    "PriceCheckPlugin",
    "BranchSelectPlugin",
    "LogiMatchPlugin",
    "SplitPlugin",
    "StockCheckPlugin",
    "AUDIT_DIM_GROUP",
    "AuditRule",
    "AuditRuleService",
    "DEFAULT_RULE",
    "TimeWindow",
    "OrderBnGenerator",
    "PREFIX_B2B",
    "PREFIX_EXCHANGE",
    "PREFIX_IMPORT",
    "PREFIX_LOCAL",
    "PREFIX_PLATFORM",
    "PREFIX_RESHIP",
    "SEQ_DOMAIN",
    "SEQ_SPACE",
    "STEP",
    "shop_code_of",
    "FAIL_AMOUNT_MISMATCH",
    "FAIL_AUTH_EXPIRED",
    "FAIL_ITEM_EMPTY",
    "FAIL_REQUIRED_MISSING",
    "FAIL_SHOP_INVALID",
    "OrderCreateResult",
    "OrderCreateService",
    "SOURCE_PREFIX",
]
