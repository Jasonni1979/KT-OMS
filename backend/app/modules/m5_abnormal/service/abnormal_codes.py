"""M5 异常原因码族 —— 异常类型字典与状态集合"""

from __future__ import annotations

from app.models.abnormal import (
    ABNORMAL_STATUS_CANCELLED,
    ABNORMAL_STATUS_RESOLVED,
)

EXC_PRODUCT_UNBOUND = "PRODUCT_UNBOUND"    # 商品未绑定

EXC_ADDR_REMOTE = "ADDR_REMOTE"            # 收货地址偏远

EXC_ADDR_INCOMPLETE = "ADDR_INCOMPLETE"    # 地址不全/双地址

EXC_ADDR_POBOX = "ADDR_POBOX"              # PO Box 地址

EXC_ADDR_FAKE = "ADDR_FAKE"                # 虚假/不可达地址

EXC_PURCHASE_LIMIT = "PURCHASE_LIMIT"      # 限购命中

EXC_PRICE_ABNORMAL = "PRICE_ABNORMAL"      # 价格异常

EXC_BLACKLIST = "BLACKLIST"                # 黑名单客户

EXC_RISK_HIT = "RISK_HIT"                  # 风控命中

EXC_STOCK_SHORT = "STOCK_SHORT"            # 缺货

EXC_OVERSOLD = "OVERSOLD"                  # 超卖

EXC_PAY_ABNORMAL = "PAY_ABNORMAL"          # 支付异常

EXC_SPLIT_FAILED = "SPLIT_FAILED"          # 拆合单失败

EXC_WMS_PUSH_FAILED = "WMS_PUSH_FAILED"    # 推仓失败

EXC_SYNC_BACK_FAILED = "SYNC_BACK_FAILED"  # 回传失败

EXC_FULFILL_STAGNANT = "FULFILL_STAGNANT"  # 履约停滞

EXC_OTHER = "OTHER"                    # 其他异常（FR-01c：未映射原因码兜底）

ABNORMAL_SEQ_DOMAIN = "AB"

STOCKOUT_TYPES = (EXC_STOCK_SHORT, EXC_OVERSOLD)

ADDRESS_TYPES = (
    EXC_ADDR_REMOTE,
    EXC_ADDR_INCOMPLETE,
    EXC_ADDR_POBOX,
    EXC_ADDR_FAKE,
)

CLOSED_STATUSES = (ABNORMAL_STATUS_RESOLVED, ABNORMAL_STATUS_CANCELLED)
