"""出库指令通道（D09.02）

**定位**：OMS 与 WMS 之间的**指令执行方**——消费 D03.07 的四指令中「经通道的部分」，
把发货单业务数据组装为标准出库指令 DTO，经 D09.01 路由与协议适配器下发目标 WMS；
接收 WMS 出库回传（验签/解析/标准化/幂等登记/回执应答），发布标准化事件驱动
D03.07 业务编排。

**职责边界（关键）**：
- 通道层：指令组装/下发/回执/回传登记/重试/熔断缓冲/通道日志
- 编排层（D03.07）：行匹配 → settle → 差异处理 → 包裹落库 → 状态流转 → 确认 → 事件
  —— 通道层**只供数与联动**，不替业务编排做决策

**幂等键体系（§5.2）**：
| 动作 | 幂等键 |
|---|---|
| 指令下发 | delivery_id + 推送轮次（单号含轮次 → 重推新轮次新单号） |
| 回传接收 | OMS 单据号 + WMS 回传批次号 |
| 叫回 | delivery_id + 叫回轮次 |

**错误分类（§5.4）**：RETRYABLE（退避重试 1/5/15/60min）/ FATAL（终态失败告警）/
BIZ_REJECT（业务拒绝，走打回流程）。

⚠ 本文件在 P3（上下文体积治理）中拆分为多个文件；
   此处保留 re-export，**原有 import 路径全部保持可用**。
"""

from __future__ import annotations

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.m7_integration.service.wms_callback import WmsCallbackMixin
from app.modules.m7_integration.service.wms_cmd_store import WmsCmdStoreMixin
from app.modules.m7_integration.service.wms_codes import (
    BACKOFF_MINUTES,
    CB_ACCEPTED,
    CB_CANCELLED,
    CB_OUTBOUND,
    CB_RECALL_FAILED,
    CB_REJECTED,
    CMD_ACCEPTED,
    CMD_BUFFERED,
    CMD_CANCELLED,
    CMD_COMPLETED,
    CMD_FAILED,
    CMD_PARTIAL,
    CMD_REJECTED,
    CMD_SENT,
    CMD_WORKING,
    ERR_BIZ_REJECT,
    ERR_FATAL,
    ERR_RETRYABLE,
    EVENT_ACCEPTED,
    EVENT_CALLBACK,
    EVENT_PUSH_FAILED,
    EVENT_PUSHED,
    EVENT_RECALL_FAILED,
    EVENT_RECALL_SUCC,
    EVENT_REJECTED,
    MAX_RETRY,
    CallbackOutcome,
    CmdOutcome,
    _delivery_bn_of,  # noqa: F401
)
from app.modules.m7_integration.service.wms_push import WmsPushMixin
from app.modules.m7_integration.service.wms_route import (
    WmsRouteService,
)

__all__ = [
    "CMD_ACCEPTED",
    "CMD_SENT",
    "CMD_WORKING",
    "CMD_PARTIAL",
    "CMD_COMPLETED",
    "CMD_CANCELLED",
    "CMD_REJECTED",
    "CMD_FAILED",
    "CMD_BUFFERED",
    "ERR_RETRYABLE",
    "ERR_FATAL",
    "ERR_BIZ_REJECT",
    "BACKOFF_MINUTES",
    "MAX_RETRY",
    "CB_ACCEPTED",
    "CB_OUTBOUND",
    "CB_REJECTED",
    "CB_CANCELLED",
    "CB_RECALL_FAILED",
    "EVENT_PUSHED",
    "EVENT_PUSH_FAILED",
    "EVENT_CALLBACK",
    "EVENT_ACCEPTED",
    "EVENT_REJECTED",
    "EVENT_RECALL_SUCC",
    "EVENT_RECALL_FAILED",
    "CmdOutcome",
    "CallbackOutcome",
    "WmsRouteService",
    "OutboundCommandService",
]


logger = get_logger("wms_channel")

class OutboundCommandService(WmsPushMixin, WmsCmdStoreMixin, WmsCallbackMixin):
    """出库指令通道服务（D09.02 FR-01/02/03/04）"""

    def __init__(self, session: AsyncSession, redis: Redis):
        self.s = session
        self.r = redis
        self.router = WmsRouteService(session)
