"""M7 通道协议常量 —— 指令状态/错误分级/回调类型/事件名与出入参模型"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

CMD_ACCEPTED = "accepted"      # 已受理

CMD_SENT = "sent"              # 已下发

CMD_WORKING = "working"        # WMS 作业中

CMD_PARTIAL = "partial"        # 部分回传

CMD_COMPLETED = "completed"    # 回传闭环

CMD_CANCELLED = "cancelled"    # 已取消

CMD_REJECTED = "rejected"      # 已打回

CMD_FAILED = "failed"          # 下发失败

CMD_BUFFERED = "buffered"      # 缓冲中（熔断降级）

ERR_RETRYABLE = "RETRYABLE"

ERR_FATAL = "FATAL"

ERR_BIZ_REJECT = "BIZ_REJECT"

BACKOFF_MINUTES = (1, 5, 15, 60)

MAX_RETRY = 5

CB_ACCEPTED = "accepted"

CB_OUTBOUND = "outbound"

CB_REJECTED = "rejected"

CB_CANCELLED = "cancelled"

CB_RECALL_FAILED = "recall_failed"

EVENT_PUSHED = "wms.outbound.pushed"

EVENT_PUSH_FAILED = "wms.outbound.push.failed"

EVENT_CALLBACK = "wms.outbound.callback"

EVENT_ACCEPTED = "wms.outbound.accepted"

EVENT_REJECTED = "wms.outbound.rejected"

EVENT_RECALL_SUCC = "wms.outbound.recall.succ"

EVENT_RECALL_FAILED = "wms.outbound.recall.failed"

@dataclass
class CmdOutcome:
    """指令执行结果"""

    ok: bool
    cmd_id: int = 0
    cmd_bn: str = ""
    cmd_no: str = ""
    wms_bill_no: str = ""
    status: str = ""
    err_code: str = ""
    err_class: str = ""
    err_msg: str = ""
    #: 是否受理（异步下发口径：受理即返回）
    accepted: bool = False
    #: 下一重试时间
    next_retry_time: datetime | None = None
    retry_times: int = 0
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "cmd_id": self.cmd_id,
            "cmd_bn": self.cmd_bn,
            "cmd_no": self.cmd_no,
            "wms_bill_no": self.wms_bill_no,
            "status": self.status,
            "err_code": self.err_code,
            "err_class": self.err_class,
            "err_msg": self.err_msg,
            "accepted": self.accepted,
            "next_retry_time": (
                self.next_retry_time.isoformat() if self.next_retry_time else None
            ),
            "retry_times": self.retry_times,
            "detail": self.detail,
        }

@dataclass
class CallbackOutcome:
    """回传接收结果"""

    ok: bool
    duplicated: bool = False
    delivery_id: int = 0
    batch_no: str = ""
    cb_type: str = ""
    #: 发布的事件名
    event: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "duplicated": self.duplicated,
            "delivery_id": self.delivery_id,
            "batch_no": self.batch_no,
            "cb_type": self.cb_type,
            "event": self.event,
            "detail": self.detail,
        }

def _delivery_bn_of(cmd_no: str) -> str:
    """从下发单号解析发货单号（DLV...-R1 → DLV...）"""
    if "-R" in cmd_no:
        return cmd_no.rsplit("-R", 1)[0]
    if "-C" in cmd_no:
        return cmd_no.rsplit("-C", 1)[0]
    return cmd_no
