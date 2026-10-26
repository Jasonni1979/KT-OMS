"""M4 发货单状态机 —— 状态、命令与转移表（单一事实源）"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models.fulfill import (
    OrdDelivery,
)

ST_DRAFT = "draft"

ST_PUSHED = "pushed"

ST_PUSH_FAILED = "push_failed"

ST_PROCESSING = "processing"

ST_PARTIAL_OUTBOUND = "partial_outbound"

ST_OUTBOUND = "outbound"

ST_SHIPPED = "shipped"

ST_FINISHED = "finished"

ST_RECALLING = "recalling"

ST_RECALLED = "recalled"

ST_REJECTED = "rejected"

ST_CANCELLED = "cancelled"

FINAL_STATES = {ST_FINISHED, ST_CANCELLED, ST_REJECTED}

CMD_PUSH = "push"

CMD_RECALL = "recall"

CMD_RESUME = "resume"

CMD_CONFIRM = "confirm"

CMD_CANCEL = "cancel"

CMD_REJECT = "reject"

CMD_CB_ACK = "callback_ack"       # WMS 接收确认

CMD_CB_OUT = "callback_outbound"  # 出库回传

CMD_FINISH = "finish"             # 收货确认/超时

SYNC_INIT = "init"

SYNC_RUNNING = "running"

SYNC_SUCC = "succ"

SYNC_FAIL = "fail"

SYNC_NONE = "none"  # 无需推仓（虚拟发货单）

CMD_PUSH_FAILED = "push_failed"

CMD_RECALL_FAIL = "recall_failed"

@dataclass(frozen=True)
class Transition:
    """一条合法流转（§5.1 流转表）"""

    command: str
    from_status: str
    to_status: str
    #: 前置校验说明（文档用）
    precondition: str = ""
    #: 失败补偿说明
    compensation: str = ""

TRANSITIONS: tuple[Transition, ...] = (
    Transition(CMD_PUSH, ST_DRAFT, ST_PUSHED, "仓 WMS 绑定有效；非 hold", "push_failed→退避重推"),
    Transition(CMD_PUSH, ST_RECALLED, ST_PUSHED, "恢复指令（预占有效）", "push_failed→退避重推"),
    Transition(CMD_PUSH, ST_PUSH_FAILED, ST_PUSHED, "错误已修复", "超限告警人工"),
    Transition(CMD_PUSH_FAILED, ST_DRAFT, ST_PUSH_FAILED, "推送失败", "自动退避重推"),
    Transition(CMD_CB_ACK, ST_PUSHED, ST_PROCESSING, "回执 delivery_id 匹配", "回执超时→反查对账"),
    Transition(CMD_CB_OUT, ST_PUSHED, ST_OUTBOUND, "批次幂等；行匹配成功", "乱序回传→异常缓冲"),
    Transition(CMD_CB_OUT, ST_PROCESSING, ST_OUTBOUND, "批次幂等；行匹配成功", "乱序回传→异常缓冲"),
    Transition(CMD_CB_OUT, ST_PROCESSING, ST_PARTIAL_OUTBOUND, "首批出库回传", "尾批→outbound"),
    Transition(CMD_CB_OUT, ST_PARTIAL_OUTBOUND, ST_OUTBOUND, "尾批回传·全部行核销", "—"),
    Transition(CMD_CONFIRM, ST_OUTBOUND, ST_SHIPPED, "全部行 settle 完成", "settle 失败→补偿队列"),
    Transition(CMD_RECALL, ST_PUSHED, ST_RECALLING, "未出库", "WMS 拒绝→回原态"),
    Transition(CMD_RECALL, ST_PROCESSING, ST_RECALLING, "未出库", "WMS 拒绝→回原态"),
    Transition(CMD_RECALL, ST_RECALLING, ST_RECALLED, "WMS 拦截成功", "预占保持"),
    Transition(CMD_RECALL_FAIL, ST_RECALLING, ST_PROCESSING, "叫回失败", "回原态+recall_failed"),
    Transition(CMD_RESUME, ST_RECALLED, ST_PUSHED, "订单未取消/预占有效/仓可用", "复核不过→转人工"),
    Transition(CMD_CANCEL, ST_DRAFT, ST_CANCELLED, "取消决策明确", "release+split_num回退"),
    Transition(CMD_CANCEL, ST_RECALLED, ST_CANCELLED, "取消决策明确", "release+split_num回退"),
    Transition(CMD_REJECT, ST_PUSHED, ST_REJECTED, "打回原因结构化", "split_num回退+回审单池"),
    Transition(CMD_REJECT, ST_PROCESSING, ST_REJECTED, "打回原因结构化", "split_num回退+回审单池"),
    Transition(CMD_FINISH, ST_SHIPPED, ST_FINISHED, "订单完成联动", "平台消息丢失→定时对账"),
)

def find_transition(command: str, from_status: str) -> Transition | None:
    """查合法流转（表驱动）"""
    for t in TRANSITIONS:
        if t.command == command and t.from_status == from_status:
            return t
    return None

def allowed_commands(from_status: str) -> list[str]:
    """某状态下允许的指令（供前端渲染）"""
    return sorted({t.command for t in TRANSITIONS if t.from_status == from_status})

@dataclass
class DeliveryOutcome:
    """指令执行结果"""

    ok: bool
    delivery_id: int = 0
    delivery_bn: str = ""
    from_status: str = ""
    to_status: str = ""
    command: str = ""
    fail_code: str = ""
    fail_message: str = ""
    detail: dict[str, Any] = None  # type: ignore[assignment]

    def __init__(self) -> None:
        self.detail = {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "delivery_id": self.delivery_id,
            "delivery_bn": self.delivery_bn,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "command": self.command,
            "fail_code": self.fail_code,
            "fail_message": self.fail_message,
            "detail": self.detail,
        }

class _FallbackCmdResult:
    """通道不可用时的降级结果（本地占位，不阻断推仓状态流转）"""

    def __init__(self, delivery: OrdDelivery):
        self.ok = True
        self.wms_bill_no = f"WMS_{delivery.delivery_bn}"
        self.err_code = ""
        self.err_class = ""
        self.err_msg = ""
        self.status = "sent"
        self.detail = {"degraded": True, "reason": "通道不可用，本地占位"}

    def to_dict(self) -> dict[str, Any]:
        return dict(self.detail)
