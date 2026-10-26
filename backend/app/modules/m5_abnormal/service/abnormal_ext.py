"""异常单扩展域服务（W9-2 · SRS-D03.09 FR-05b/FR-05c/FR-06/FR-07）

三块能力：

| 能力 | 条款 | 说明 |
|---|---|---|
| **超卖应急批次** | FR-05b~05e | 同店铺同 SKU 自动聚合；批次级统一决策；分级 SLA；复盘 |
| **订单暂停编排** | FR-06a~06e | 暂停/恢复逐发货单分布式动作；任一失败按整体失败；不半恢复；暂停期间约束 |
| **名单服务** | FR-07a~07d | 黑/灰/白名单；两层库（全局 + 租户/货主私有）；命中私有优先；增删改走审批留痕 |

⚠ **告警推送（D01.07 企微）为扩展位**：本期落「告警待发」记录 + 明确 `pending`，
不假装已推送（企微通道未实现）。

⚠ 本文件在 P3（上下文体积治理）中拆分为多个文件；
   此处保留 re-export，**原有 import 路径全部保持可用**。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.m5_abnormal.service.abnormal_ext_batch import AbnormalExtBatchMixin
from app.modules.m5_abnormal.service.abnormal_ext_codes import (
    BATCH_STAGE_LABEL,
    BATCH_STAGE_ORDER,
    DIM_ACCOUNT,
    DIM_ADDRESS,
    DIM_MOBILE,
    DIM_NAME,
    LIST_BLACK,
    LIST_GRAY,
    LIST_TYPE_LABEL,
    LIST_WHITE,
    PROMO_SLA_HOURS,
    SCOPE_GLOBAL,
    SCOPE_OWNER,
    SCOPE_TENANT,
    SLA_HOURS,
    STAGE_ALARM,
    STAGE_ALLOC_CALC,
    STAGE_COMPENSATE,
    STAGE_NEGOTIATE,
    STAGE_REFUND,
    STAGE_REVIEW,
    VALUE_HASH,
    VALUE_PLAIN,
)
from app.modules.m5_abnormal.service.abnormal_ext_list import AbnormalExtListMixin

__all__ = [
    "STAGE_ALARM",
    "STAGE_ALLOC_CALC",
    "STAGE_NEGOTIATE",
    "STAGE_REFUND",
    "STAGE_COMPENSATE",
    "STAGE_REVIEW",
    "BATCH_STAGE_LABEL",
    "BATCH_STAGE_ORDER",
    "SLA_HOURS",
    "PROMO_SLA_HOURS",
    "LIST_BLACK",
    "LIST_GRAY",
    "LIST_WHITE",
    "LIST_TYPE_LABEL",
    "DIM_MOBILE",
    "DIM_ADDRESS",
    "DIM_ACCOUNT",
    "DIM_NAME",
    "VALUE_PLAIN",
    "VALUE_HASH",
    "SCOPE_GLOBAL",
    "SCOPE_TENANT",
    "SCOPE_OWNER",
    "AbnormalExtService",
]


class AbnormalExtService(AbnormalExtBatchMixin, AbnormalExtListMixin):
    """异常单扩展域服务（W9-2）"""

    def __init__(self, session: AsyncSession, redis: Any = None) -> None:
        self.s = session
        self.r = redis
