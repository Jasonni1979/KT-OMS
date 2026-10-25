"""WMS 模拟器数据仓库（内存）

模拟 WMS 侧的三类状态：
1. **指令单**（OMS 下发的出库/叫回报文）—— 单号唯一，重复下发幂等
2. **WMS 作业单**（指令在 WMS 侧的履约状态）—— 拣货 → 打包 → 出库
3. **回传事件**（WMS 主动回传给 OMS 的）—— 接收确认 / 出库回传 / 打回 / 叫回结果

关键保真点：
- **单号规则**：OMS 侧下发单号 = `delivery_bn + "-R" + 轮次`（SRS-D09.02 §5.1），
  模拟器按此解析出原始发货单号与轮次；
- **批次幂等**：出库回传按 `wms_batch_no` 独立幂等，重复投递不重复登记；
- **实发 ≠ 指令**：模拟器可注入少发/多发（`_actual_num` 覆盖），驱动 D03.07 差异登记路径；
- **分批出库**：一次指令可分多批回传（`batch_no` 区分），驱动 partial_outbound 路径。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

#: OMS 下发单号格式：DLV26010100001-R1
CMD_NO_RE = re.compile(r"^(?P<delivery_bn>[A-Za-z0-9]+)-R(?P<round>\d+)$")


@dataclass
class WmsCmd:
    """WMS 侧指令单"""

    cmd_no: str
    delivery_bn: str
    push_round: int
    cmd_type: str = "push"          # push / recall
    status: str = "accepted"        # CMD_STATUS 键
    wms_bill_no: str = ""
    warehouse_code: str = ""
    owner_code: str = ""
    lines: list[dict[str, Any]] = field(default_factory=list)
    waybill_no: str = ""
    print_ref: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    received_at: str = ""
    #: 已回传批次（避免重复）
    callbacks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cmd_no": self.cmd_no,
            "delivery_bn": self.delivery_bn,
            "push_round": self.push_round,
            "cmd_type": self.cmd_type,
            "status": self.status,
            "status_label": CMD_STATUS_LABEL.get(self.status, self.status),
            "wms_bill_no": self.wms_bill_no,
            "warehouse_code": self.warehouse_code,
            "owner_code": self.owner_code,
            "lines": self.lines,
            "waybill_no": self.waybill_no,
            "print_ref": self.print_ref,
            "received_at": self.received_at,
        }


CMD_STATUS_LABEL = {
    "accepted": "已受理",
    "sent": "已下发",
    "working": "WMS作业中",
    "partial": "部分回传",
    "completed": "回传闭环",
    "cancelled": "已取消",
    "rejected": "已打回",
    "failed": "下发失败",
}


@dataclass
class Callback:
    """回传事件（WMS → OMS）"""

    cb_type: str                     # accepted / outbound / rejected / cancelled / recall_failed
    delivery_bn: str
    batch_no: str = ""
    wms_bill_no: str = ""
    lines: list[dict[str, Any]] = field(default_factory=list)
    packages: list[dict[str, Any]] = field(default_factory=list)
    weight: float = 0.0
    volume: float = 0.0
    waybill_no: str = ""
    reject_reason: str = ""
    reject_reason_code: str = ""
    received_at: str = ""
    acked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "cb_type": self.cb_type,
            "delivery_bn": self.delivery_bn,
            "batch_no": self.batch_no,
            "wms_bill_no": self.wms_bill_no,
            "lines": self.lines,
            "packages": self.packages,
            "weight": self.weight,
            "volume": self.volume,
            "waybill_no": self.waybill_no,
            "reject_reason": self.reject_reason,
            "reject_reason_code": self.reject_reason_code,
            "received_at": self.received_at,
            "acked": self.acked,
        }


class WmsStore:
    """WMS 侧内存仓库"""

    def __init__(self) -> None:
        self.cmds: dict[str, WmsCmd] = {}
        self.callbacks: list[Callback] = []
        self._seq = 0
        #: 叫回被拒的指令（模拟已开始拣货）
        self.recall_reject: set[str] = set()
        #: 拣货完成的指令（叫回会被拒）
        self.picked: set[str] = set()
        #: 按指令单号预置的错误注入 {cmd_no: (err_code, msg, err_class, 剩余次数)}
        #: remaining <= 0 表示永久生效
        self.injected: dict[str, tuple[str, str, str, int]] = {}

    # ---------- 错误注入 ----------

    def inject(
        self, cmd_no: str, err_code: str, msg: str, err_class: str, times: int = 1
    ) -> None:
        """预置错误：命中该指令单号的下发请求时返回指定错误"""
        self.injected[cmd_no] = (err_code, msg, err_class, times)

    def take_inject(self, cmd_no: str) -> tuple[str, str, str] | None:
        """取出预置错误（次数递减；<=0 表示永久）"""
        item = self.injected.get(cmd_no)
        if item is None:
            return None
        code, msg, cls, times = item
        if times > 0:
            times -= 1
            if times <= 0:
                self.injected.pop(cmd_no, None)
            else:
                self.injected[cmd_no] = (code, msg, cls, times)
        return code, msg, cls

    # ---------- 指令 ----------

    def next_bill_no(self) -> str:
        self._seq += 1
        return f"WMS{self._seq:08d}"

    @staticmethod
    def parse_cmd_no(cmd_no: str) -> tuple[str, int]:
        """解析 OMS 下发单号 → (发货单号, 推送轮次)"""
        m = CMD_NO_RE.match(cmd_no)
        if m:
            return m.group("delivery_bn"), int(m.group("round"))
        return cmd_no, 1

    def get_cmd(self, cmd_no: str) -> WmsCmd | None:
        return self.cmds.get(cmd_no)

    def find_by_delivery(self, delivery_bn: str) -> list[WmsCmd]:
        return [c for c in self.cmds.values() if c.delivery_bn == delivery_bn]

    def add_cmd(self, cmd: WmsCmd) -> WmsCmd:
        """登记指令（同单号幂等：重复下发返回首次受理结果）"""
        exist = self.cmds.get(cmd.cmd_no)
        if exist is not None:
            return exist
        self.cmds[cmd.cmd_no] = cmd
        return cmd

    def all_cmds(self) -> list[WmsCmd]:
        return sorted(self.cmds.values(), key=lambda c: c.received_at)

    # ---------- 回传 ----------

    def add_callback(self, cb: Callback) -> Callback:
        """登记回传（幂等键 = delivery_bn + batch_no + cb_type）"""
        for exist in self.callbacks:
            if (
                exist.delivery_bn == cb.delivery_bn
                and exist.batch_no == cb.batch_no
                and exist.cb_type == cb.cb_type
            ):
                return exist
        self.callbacks.append(cb)
        return cb

    def callbacks_of(self, delivery_bn: str) -> list[Callback]:
        return [c for c in self.callbacks if c.delivery_bn == delivery_bn]

    def all_callbacks(self) -> list[Callback]:
        return list(self.callbacks)

    def clear(self) -> int:
        n = len(self.cmds) + len(self.callbacks)
        self.cmds.clear()
        self.callbacks.clear()
        self.recall_reject.clear()
        self.picked.clear()
        self._seq = 0
        return n


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
