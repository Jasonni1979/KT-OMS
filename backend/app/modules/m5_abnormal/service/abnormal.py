"""异常单服务（SRS-D03.09 异常单与缺货处理 · W8）

覆盖：
- FR-01a/01b/01c  异常类型字典 + 原因码→类型映射（未映射兜底「其他异常」并告警）
- FR-02a          创建来源（系统自动 / 事件订阅 / 人工标记 / 联动生成）+ 幂等
- FR-02b          状态机（待分派→已分派→处理中→已解决/已取消/已挂起）+ 时间线
- FR-02c          分派（按类型默认处理组 / 手动改派转派撤销）
- FR-02d          处理动作（重新审单 / 取消订单 / 挂起 / 强制放行）
- FR-02e          闭环（异常单解决后解除订单异常标记；多异常单全部闭环才解除）
- FR-04a          缺货标记（订单级标记 + 三元键明细，多次预占失败按明细合并）
- FR-05a          超卖识别（平台已成交但 OMS 无货 → 超卖标记，SLA 更短）

**时间基准**：全链路用 `app.core.timeutil.utcnow()`（UTC naive）——
SLA 计时 / 账龄统计跨域比较，与 DB 的 DATETIME 同基准，与 DB 服务器时区无关。

⚠ 本文件在 P3（上下文体积治理）中拆分为多个文件；
   此处保留 re-export，**原有 import 路径全部保持可用**。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.m5_abnormal.service.abnormal_codes import (
    ABNORMAL_SEQ_DOMAIN,
    ADDRESS_TYPES,
    CLOSED_STATUSES,
    EXC_ADDR_FAKE,
    EXC_ADDR_INCOMPLETE,
    EXC_ADDR_POBOX,
    EXC_ADDR_REMOTE,
    EXC_BLACKLIST,
    EXC_FULFILL_STAGNANT,
    EXC_OTHER,
    EXC_OVERSOLD,
    EXC_PAY_ABNORMAL,
    EXC_PRICE_ABNORMAL,
    EXC_PRODUCT_UNBOUND,
    EXC_PURCHASE_LIMIT,
    EXC_RISK_HIT,
    EXC_SPLIT_FAILED,
    EXC_STOCK_SHORT,
    EXC_SYNC_BACK_FAILED,
    EXC_WMS_PUSH_FAILED,
    STOCKOUT_TYPES,
)
from app.modules.m5_abnormal.service.abnormal_create import AbnormalCreateMixin
from app.modules.m5_abnormal.service.abnormal_process import AbnormalProcessMixin
from app.modules.m5_abnormal.service.abnormal_stockout import AbnormalStockoutMixin

__all__ = [
    "EXC_PRODUCT_UNBOUND",
    "EXC_ADDR_REMOTE",
    "EXC_ADDR_INCOMPLETE",
    "EXC_ADDR_POBOX",
    "EXC_ADDR_FAKE",
    "EXC_PURCHASE_LIMIT",
    "EXC_PRICE_ABNORMAL",
    "EXC_BLACKLIST",
    "EXC_RISK_HIT",
    "EXC_STOCK_SHORT",
    "EXC_OVERSOLD",
    "EXC_PAY_ABNORMAL",
    "EXC_SPLIT_FAILED",
    "EXC_WMS_PUSH_FAILED",
    "EXC_SYNC_BACK_FAILED",
    "EXC_FULFILL_STAGNANT",
    "EXC_OTHER",
    "ABNORMAL_SEQ_DOMAIN",
    "STOCKOUT_TYPES",
    "ADDRESS_TYPES",
    "CLOSED_STATUSES",
    "AbnormalService",
]


logger = get_logger("abnormal")

class AbnormalService(AbnormalCreateMixin, AbnormalProcessMixin, AbnormalStockoutMixin):
    """异常单服务"""

    def __init__(self, session: AsyncSession, redis: Any = None):
        self.s = session
        self.r = redis
