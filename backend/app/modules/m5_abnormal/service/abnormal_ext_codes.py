"""M5 扩展域常量 —— 应急批次阶段/SLA/名单维度与作用域"""

from __future__ import annotations

from app.contracts.enums import ORD_OVERSOLD_BATCH_STAGE, ORD_RISK_LIST_LIST_TYPE

STAGE_ALARM = "alarm"

STAGE_ALLOC_CALC = "alloc_calc"

STAGE_NEGOTIATE = "negotiate"

STAGE_REFUND = "refund"

STAGE_COMPENSATE = "compensate"

STAGE_REVIEW = "review"

BATCH_STAGE_LABEL = ORD_OVERSOLD_BATCH_STAGE

BATCH_STAGE_ORDER = (
    STAGE_ALARM,
    STAGE_ALLOC_CALC,
    STAGE_NEGOTIATE,
    STAGE_REFUND,
    STAGE_COMPENSATE,
    STAGE_REVIEW,
)

SLA_HOURS = {
    STAGE_ALARM: 0,
    STAGE_ALLOC_CALC: 4,
    STAGE_NEGOTIATE: 24,
}

PROMO_SLA_HOURS = {
    STAGE_ALARM: 0,
    STAGE_ALLOC_CALC: 2,
    STAGE_NEGOTIATE: 24,
}

LIST_BLACK = "black"

LIST_GRAY = "gray"

LIST_WHITE = "white"

LIST_TYPE_LABEL = ORD_RISK_LIST_LIST_TYPE

DIM_MOBILE = "mobile"

DIM_ADDRESS = "address"

DIM_ACCOUNT = "account"

DIM_NAME = "name"

VALUE_PLAIN = "plain"

VALUE_HASH = "hash"

SCOPE_GLOBAL = "global"

SCOPE_TENANT = "tenant"

SCOPE_OWNER = "owner"
