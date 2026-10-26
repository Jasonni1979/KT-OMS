"""单号规则契约 —— 各域单号前缀与生成规则

⚠ **幂等键相关**：回传幂等键 = 发货单号 + 批次号 + 类型；
造演示/测试数据时单号**必须唯一**，否则会被幂等挡掉（静默失败，难排查）。
"""
from __future__ import annotations

from typing import Final

#: 订单号前缀（平台单 / 本地单 / 导入单 / 换货单 / 补发单）
ORDER_BN_PREFIX: Final[dict[str, str]] = {
    "platform": "P",
    "local": "L",
    "import": "I",
    "exchange": "C",
    "reship": "B",
}

#: 售后单号前缀
AFTERSALE_BN_PREFIX: Final[dict[str, str]] = {
    "apply": "MA",     # 手工售后申请单
    "return": "RA",    # 退货申请单
    "refund": "RF",    # 退款单
}

#: 单号生成规则（长度 / 字符集）
BN_RULES: Final[dict[str, dict[str, str]]] = {
    "order": {"prefix": "P/L/I/C/B", "seq": "按日期 + 序列", "unique": "全局唯一"},
    "aftersale_apply": {"prefix": "MA", "seq": "按日期 + 序列", "unique": "全局唯一"},
    "delivery": {"prefix": "DL", "seq": "按日期 + 序列", "unique": "全局唯一"},
}
