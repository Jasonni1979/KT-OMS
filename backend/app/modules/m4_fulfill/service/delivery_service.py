"""发货单指令状态机（D03.07）

**定位**：发货单（delivery）是**履约执行单元**——订单经审单→拆单后的产物，
推 WMS 的载体，出库回传的锚点，平台发货回传的依据。

**状态机是 SRS-00 §4.4 契约的权威定义源**（§4.1 状态图 + §5.1 流转表）。
本模块把商派订单级 `pause` 布尔升级为**发货单级指令状态机**（四指令）。

**状态枚举**：
```
draft → pushed → processing → outbound → shipped → finished
分支：push_failed（可重推）/ recalling → recalled（可恢复或取消）
      / rejected（WMS 打回）/ cancelled / partial_outbound（部分出库子状态）
```

**四指令**（契约口径）：
| 指令 | 流转 | 说明 |
|---|---|---|
| 推送 push | draft/recalled → pushed | 经 D09.02 下发 WMS |
| 叫回 recall | pushed/processing → recalling → recalled | 暂停/改单/取消前置 |
| 恢复 resume | recalled → pushed | 暂停恢复语义（重推） |
| 确认 confirm | outbound → shipped | 发货确认（自动/人工） |

**关键约束**：
- 状态变更**唯一入口** `transit()`：表驱动流转校验 → 行级锁 → 落库 + delivery_log 同事务
- 非法流转（跳态/重复指令）拒绝 + 告警；重复指令幂等
- 指令与状态分离：recalling 等中间态保证分布式动作期间状态可观测可对账

⚠ 本文件在 P3（上下文体积治理）中拆分为多个文件；
   此处保留 re-export，**原有 import 路径全部保持可用**。
"""

from __future__ import annotations

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.m4_fulfill.service.delivery_callback import DeliveryCallbackMixin
from app.modules.m4_fulfill.service.delivery_create import DeliveryCreateMixin
from app.modules.m4_fulfill.service.delivery_query import DeliveryQueryMixin
from app.modules.m4_fulfill.service.delivery_states import (
    CMD_CANCEL,
    CMD_CB_ACK,
    CMD_CB_OUT,
    CMD_CONFIRM,
    CMD_FINISH,
    CMD_PUSH,
    CMD_PUSH_FAILED,
    CMD_RECALL,
    CMD_RECALL_FAIL,
    CMD_REJECT,
    CMD_RESUME,
    FINAL_STATES,
    ST_CANCELLED,
    ST_DRAFT,
    ST_FINISHED,
    ST_OUTBOUND,
    ST_PARTIAL_OUTBOUND,
    ST_PROCESSING,
    ST_PUSH_FAILED,
    ST_PUSHED,
    ST_RECALLED,
    ST_RECALLING,
    ST_REJECTED,
    ST_SHIPPED,
    SYNC_FAIL,
    SYNC_INIT,
    SYNC_NONE,
    SYNC_RUNNING,
    SYNC_SUCC,
    TRANSITIONS,
    DeliveryOutcome,
    Transition,
    _FallbackCmdResult,  # noqa: F401
    allowed_commands,
    find_transition,
)
from app.modules.m4_fulfill.service.delivery_transit import DeliveryTransitMixin

__all__ = [
    "ST_DRAFT",
    "ST_PUSHED",
    "ST_PUSH_FAILED",
    "ST_PROCESSING",
    "ST_PARTIAL_OUTBOUND",
    "ST_OUTBOUND",
    "ST_SHIPPED",
    "ST_FINISHED",
    "ST_RECALLING",
    "ST_RECALLED",
    "ST_REJECTED",
    "ST_CANCELLED",
    "FINAL_STATES",
    "CMD_PUSH",
    "CMD_RECALL",
    "CMD_RESUME",
    "CMD_CONFIRM",
    "CMD_CANCEL",
    "CMD_REJECT",
    "CMD_CB_ACK",
    "CMD_CB_OUT",
    "CMD_FINISH",
    "SYNC_INIT",
    "SYNC_RUNNING",
    "SYNC_SUCC",
    "SYNC_FAIL",
    "SYNC_NONE",
    "CMD_PUSH_FAILED",
    "CMD_RECALL_FAIL",
    "Transition",
    "TRANSITIONS",
    "find_transition",
    "allowed_commands",
    "DeliveryOutcome",
    "DeliveryService",
]


logger = get_logger("delivery")

class DeliveryService(DeliveryCreateMixin, DeliveryTransitMixin, DeliveryCallbackMixin, DeliveryQueryMixin):
    """发货单服务（D03.07 FR-01/03/05/06/07/08/09）"""

    def __init__(self, session: AsyncSession, redis: Redis):
        self.s = session
        self.r = redis
