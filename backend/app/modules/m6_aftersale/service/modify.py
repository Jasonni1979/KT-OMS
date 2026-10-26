"""订单修改与改地址服务（SRS-D03.08 最小子集 · W8-3）

D03.08 完整形态包含快照/冻结/差异对比/叫回/复审/审批（FR-01~FR-07），
W8 只做**评审可用的最小闭环**：

| 能力 | 状态 | 说明 |
|---|---|---|
| 未推仓直改地址 | ✅ 真跑 | 无发货单 → 直接改收货信息 + 落改单/快照 + 审计 |
| 已推仓改地址 | ✅ 真跑 | 有发货单 → 先叫回（W7 链路）→ 叫回成功后改地址 |
| 叫回失败 | ✅ 真跑 | 改单置挂起 + 落异常单（人工跟进），不静默 |
| 快照 | ✅ 真跑 | 改前落 `ord_order_snapshot`（订单主档/行/收货人，密文原样存） |
| 差异对比 | ✅ 真跑 | `diff_summary`（字段级旧值/新值） |
| 改单冻结（FR-03a） | ⚠️ 扩展位 | 纯地址改单**本就不动库存**（FR-03b）→ 本期不需冻结 |
| 审批 / 复审联动 | ⚠️ 扩展位 | 属后续批次，改单单据已留 `approval_id` 扩展位 |
| 并发互斥（FR-01a） | ✅ 真跑 | 同订单同一时刻只允许一张进行中的改单（Redis 锁 + DB 状态校验） |

⚠ **地址是 PIPL 敏感字段**：快照与 diff 里的地址保持**密文**（`address_enc`），
前端只展示脱敏值，不做明文落库。

⚠ 本文件在 P3（上下文体积治理）中拆分为多个文件；
   此处保留 re-export，**原有 import 路径全部保持可用**。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.m6_aftersale.service.modify_apply import ModifyApplyMixin
from app.modules.m6_aftersale.service.modify_codes import (
    MODIFY_ADDRESS,
    MODIFY_OPEN_STATUSES,
    MODIFY_STATUS_CANCELLED,
    MODIFY_STATUS_EDITING,
    MODIFY_STATUS_EFFECTIVE,
    MODIFY_STATUS_RECALLING,
    MODIFY_STATUS_SUSPENDED,
    MODIFY_TYPE_LABEL,
    _hex,  # noqa: F401
    _unhex,  # noqa: F401
    s_rows,
)
from app.modules.m6_aftersale.service.modify_request import ModifyRequestMixin

__all__ = [
    "MODIFY_ADDRESS",
    "MODIFY_STATUS_EDITING",
    "MODIFY_STATUS_RECALLING",
    "MODIFY_STATUS_EFFECTIVE",
    "MODIFY_STATUS_SUSPENDED",
    "MODIFY_STATUS_CANCELLED",
    "MODIFY_OPEN_STATUSES",
    "MODIFY_TYPE_LABEL",
    "ModifyService",
    "s_rows",
]


class ModifyService(ModifyRequestMixin, ModifyApplyMixin):
    """订单修改服务（D03.08 最小子集）"""

    def __init__(self, session: AsyncSession, redis: Any = None) -> None:
        self.s = session
        self.r = redis
