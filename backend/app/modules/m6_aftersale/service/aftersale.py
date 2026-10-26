"""售后服务服务（D05.01 售后申请 + D05.03 仅退款与退款单 · W9-1）

本期做**最小闭环**：申请落库 → 审核 → 状态推进 → 退款单生成/受理 → 订单联动。

| SRS 条款 | 实现 |
|---|---|
| D05.01 FR-01b 落库幂等 | 唯一键 `(platform, shop_id, platform_aftersale_bn)`；重复事件复用 |
| D05.01 FR-01d 类型判定 | 1=仅退款 / 2=退货退款 / 3=换货 / 4=补发 |
| D05.01 FR-01e 原单关联 | 按 platform_order_bn 关联；订单缺失 → 落「待关联」异常态 |
| D05.01 FR-02a 申请单头 | RA/MA 单号 + 双口径金额 + 原因 + 时限 |
| D05.01 FR-02b/02c 状态机 | 11 条合法迁移，**唯一入口 transit**，非法流转拒绝 + 写日志 |
| D05.01 FR-02e 审核 | 同意/拒绝 + 拒绝原因码；审核动作原子编排 = 状态推进 + 退款单生成 |
| D05.01 FR-02f 部分售后 | 行级申请数量 + 双口径金额；数量上限校验（Σ ≤ 行购买数量） |
| D05.01 FR-03a 手工建单 | source=manual，operator 必填 |
| D05.01 FR-05a 售后中标记 | 申请单落库 → 订单打售后中标记；全部闭环 → 清除 |
| D05.01 FR-05b pay_status 联动 | 退款单受理 → 退款中；退款成功 → 部分/全额退款 |
| D05.01 FR-06a 时效 | 落单即算 deadline |
| D05.03 FR-01 退款单 | 审核同意涉钱 → 生成退款单（待退款） |
| D05.03 FR-02 退款执行 | 平台受理 → 退款中 → 已退款；失败可重试 |

⚠ **平台回传（FR-02d）本期为扩展位**：`sync_status` 记录状态但不真正下发平台指令
（D02.04 `SyncService::submitAftersaleAction` 未实现）→ 明确返回 `pending`。

⚠ 本文件在 P3（上下文体积治理）中拆分为多个文件；
   此处保留 re-export，**原有 import 路径全部保持可用**。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.m6_aftersale.service.aftersale_apply import AftersaleApplyMixin
from app.modules.m6_aftersale.service.aftersale_codes import (
    AFTERSALE_TYPE_LABEL,
    ALLOWED_TRANSITIONS,
    APPLY_CLOSED_STATUSES,
    APPLY_STATUS_LABEL,
    AUDIT_AUTO,
    AUDIT_MANUAL,
    AUDIT_OA,
    CHANNEL_OFFLINE,
    CHANNEL_PLATFORM,
    DEFAULT_DEADLINE_HOURS,
    GOODS_RECEIVED,
    GOODS_SHIPPED,
    GOODS_UNSHIPPED,
    OP_MANUAL,
    OP_PLATFORM,
    OP_SYSTEM,
    REFUND_CANCELLED,
    REFUND_FAILED,
    REFUND_STATUS_LABEL,
    REFUND_WAIT,
    REFUNDED,
    REFUNDED_OFFLINE,
    REFUNDING,
    ST_CLOSED,
    ST_DONE,
    ST_EXCHANGING,
    ST_PENDING_LINK,
    ST_REFUNDING,
    ST_REJECTED,
    ST_WAIT_AUDIT,
    ST_WAIT_RECEIVE,
    ST_WAIT_REFUND,
    ST_WAIT_RETURN,
    SYNC_DOING,
    SYNC_MANUAL,
    SYNC_NONE,
    SYNC_RETRY,
    SYNC_SUCCESS,
    TYPE_EXCHANGE,
    TYPE_REFUND_ONLY,
    TYPE_RESHIPMENT,
    TYPE_RETURN_REFUND,
)
from app.modules.m6_aftersale.service.aftersale_query import AftersaleQueryMixin
from app.modules.m6_aftersale.service.aftersale_refund import AftersaleRefundMixin

__all__ = [
    "TYPE_REFUND_ONLY",
    "TYPE_RETURN_REFUND",
    "TYPE_EXCHANGE",
    "TYPE_RESHIPMENT",
    "AFTERSALE_TYPE_LABEL",
    "ST_PENDING_LINK",
    "ST_WAIT_AUDIT",
    "ST_WAIT_RETURN",
    "ST_WAIT_RECEIVE",
    "ST_WAIT_REFUND",
    "ST_REFUNDING",
    "ST_EXCHANGING",
    "ST_DONE",
    "ST_REJECTED",
    "ST_CLOSED",
    "APPLY_STATUS_LABEL",
    "APPLY_CLOSED_STATUSES",
    "GOODS_UNSHIPPED",
    "GOODS_SHIPPED",
    "GOODS_RECEIVED",
    "REFUND_WAIT",
    "REFUNDING",
    "REFUNDED",
    "REFUND_FAILED",
    "REFUNDED_OFFLINE",
    "REFUND_CANCELLED",
    "REFUND_STATUS_LABEL",
    "CHANNEL_PLATFORM",
    "CHANNEL_OFFLINE",
    "SYNC_NONE",
    "SYNC_DOING",
    "SYNC_SUCCESS",
    "SYNC_RETRY",
    "SYNC_MANUAL",
    "AUDIT_MANUAL",
    "AUDIT_AUTO",
    "AUDIT_OA",
    "OP_MANUAL",
    "OP_SYSTEM",
    "OP_PLATFORM",
    "ALLOWED_TRANSITIONS",
    "DEFAULT_DEADLINE_HOURS",
    "AftersaleService",
]


class AftersaleService(AftersaleApplyMixin, AftersaleRefundMixin, AftersaleQueryMixin):
    """售后服务服务（D05）"""

    def __init__(self, session: AsyncSession, redis: Any = None) -> None:
        self.s = session
        self.r = redis
