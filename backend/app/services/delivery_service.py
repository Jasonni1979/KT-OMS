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
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.fulfill import (
    OrdDelivery,
    OrdDeliveryDiff,
    OrdDeliveryItem,
    OrdDeliveryItemDetail,
    OrdDeliveryLog,
    OrdDeliveryPackage,
)
from app.models.order import OrdOrder, OrdOrderItem

logger = get_logger("delivery")

# ==================== 状态枚举 ====================

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

#: 终态（不可再流转）
FINAL_STATES = {ST_FINISHED, ST_CANCELLED, ST_REJECTED}

#: 指令
CMD_PUSH = "push"
CMD_RECALL = "recall"
CMD_RESUME = "resume"
CMD_CONFIRM = "confirm"
CMD_CANCEL = "cancel"
CMD_REJECT = "reject"
CMD_CB_ACK = "callback_ack"       # WMS 接收确认
CMD_CB_OUT = "callback_outbound"  # 出库回传
CMD_FINISH = "finish"             # 收货确认/超时

#: 推仓同步状态
SYNC_INIT = "init"
SYNC_RUNNING = "running"
SYNC_SUCC = "succ"
SYNC_FAIL = "fail"
SYNC_NONE = "none"  # 无需推仓（虚拟发货单）

#: 兼容别名（先定义，供流转表引用）
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


#: 状态机流转表（§5.1 权威表）
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


class DeliveryService:
    """发货单服务（D03.07 FR-01/03/05/06/07/08/09）"""

    def __init__(self, session: AsyncSession, redis: Redis):
        self.s = session
        self.r = redis

    # ==================== 生成（FR-03：plan 执行器）====================

    async def create_from_plan(
        self,
        order_id: int,
        groups: list[dict[str, Any]],
        *,
        source: str = "auto",
        plan_id: int = 0,
        split_trace_id: int = 0,
        operator: str = "system",
        logi_id: int = 0,
    ) -> list[int]:
        """发货单生成（IF-D03.07-01，单事务 FR-03a）

        发货单头/行/明细溯源落库 + 订单进度回写 + 操作日志。
        任一步失败整体回滚（订单回拆单前状态）。
        """
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id, OrdOrder.is_deleted == 0)
        )
        if not order:
            raise NotFoundError(f"订单不存在: {order_id}")
        item_rows = list(
            await self.s.scalars(
                select(OrdOrderItem)
                .where(OrdOrderItem.order_id == order_id, OrdOrderItem.is_deleted == 0)
                .order_by(OrdOrderItem.id)
            )
        )
        by_id = {int(r.id): r for r in item_rows}

        delivery_ids: list[int] = []
        # 分仓 plan（行→仓）—— 组 attrs 无 branch_id 时按行兜底取仓（FR-03b 组属性映射）
        plan_alloc = await self._dispatch_alloc(order_id)
        for idx, g in enumerate(groups):
            attrs = dict(g.get("attrs") or {})
            branch_id = int(attrs.get("branch_id", 0) or 0)
            owner_id = int(attrs.get("owner_id", order.owner_id or 0))
            is_virtual = 1 if attrs.get("virtual") or attrs.get("virtual_delivery") else 0
            hold_flag = 1 if attrs.get("hold") else 0

            bn = await self._next_delivery_bn()
            delivery = OrdDelivery(
                owner_id=owner_id,
                delivery_bn=bn,
                order_id=order_id,
                order_ids=[order_id],
                status=ST_DRAFT,
                sync_status=SYNC_NONE if is_virtual else SYNC_INIT,
                branch_id=branch_id,
                logi_id=logi_id or None,
                is_virtual=is_virtual,
                hold_flag=hold_flag,
                plan_id=plan_id or None,
                split_trace_id=split_trace_id or None,
                source=source,
                shop_id=int(order.shop_id or 0),
                brand_id=int(order.brand_id or 0),
                memo=str(attrs.get("memo", "") or "") or None,
            )
            self.s.add(delivery)
            await self.s.flush()

            # 发货单行（行内货主唯一 FR-01b：同组内混货主 → 拒绝）
            line_owners: set[int] = set()
            line_map: dict[tuple[int, int], OrdDeliveryItem] = {}
            for ln in g.get("items", []):
                item_id = int(ln.get("item_id", 0) or 0)
                nums = int(ln.get("nums", 0) or 0)
                src = by_id.get(item_id)
                if not src or nums <= 0:
                    continue
                row_owner = int(src.owner_id or 0)
                line_owners.add(row_owner)
                key = (int(src.bm_id or 0), row_owner)
                di = line_map.get(key)
                if di is None:
                    di = OrdDeliveryItem(
                        tenant_id=1,
                        delivery_id=delivery.id,
                        bm_id=int(src.bm_id or 0),
                        bm_number=str(src.bm_number or ""),
                        sm_id=int(src.sm_id or 0) or None,
                        num=0,
                        settled_num=0,
                        owner_id=row_owner,
                        lend_flag=int(getattr(src, "lend_flag", 0) or 0),
                        price=float(src.paid_amount or 0),
                    )
                    self.s.add(di)
                    await self.s.flush()
                    line_map[key] = di
                di.num = int(di.num or 0) + nums

            if len(line_owners) > 1:
                raise ConflictError(
                    f"发货单行内货主不唯一（owner={sorted(line_owners)}）——禁止混货主发货单"
                )

            # 明细溯源（Σsplit_qty = item.num 守恒）
            for di in line_map.values():
                for ln in g.get("items", []):
                    item_id = int(ln.get("item_id", 0) or 0)
                    nums = int(ln.get("nums", 0) or 0)
                    src = by_id.get(item_id)
                    if not src or nums <= 0:
                        continue
                    if int(src.bm_id or 0) != int(di.bm_id) or int(src.owner_id or 0) != int(di.owner_id):
                        continue
                    self.s.add(
                        OrdDeliveryItemDetail(
                            tenant_id=1,
                            delivery_id=delivery.id,
                            delivery_item_id=di.id,
                            order_id=order_id,
                            order_item_id=item_id,
                            split_qty=nums,
                        )
                    )

            # 组无 branch_id → 按组内行从分仓 plan 取仓（单仓组）
            if not branch_id:
                for ln in g.get("items", []):
                    item_id = int(ln.get("item_id", 0) or 0)
                    item_alloc = plan_alloc.get(item_id) or {}
                    if item_alloc:
                        branch_id = int(next(iter(item_alloc)))
                        break
                if branch_id:
                    delivery.branch_id = branch_id

            # 日志留痕（FR-02d）
            self.s.add(
                OrdDeliveryLog(
                    tenant_id=1,
                    delivery_id=delivery.id,
                    command="create",
                    from_status="",
                    to_status=ST_DRAFT,
                    operator=operator,
                    reason=f"按拆单方案生成（第{idx + 1}组）",
                )
            )
            delivery_ids.append(int(delivery.id))

        # 订单进度回写（split_num / splited_num）
        await self._write_progress(order, groups)

        await self.s.commit()
        return delivery_ids

    async def _write_progress(self, order: OrdOrder, groups: list[dict[str, Any]]) -> None:
        """回写拆单进度（FR-06a/b）"""
        item_ids = [int(ln.get("item_id", 0) or 0) for g in groups for ln in g.get("items", [])]
        if not item_ids:
            return
        rows = list(
            await self.s.scalars(
                select(OrdOrderItem).where(OrdOrderItem.id.in_(item_ids))
            )
        )
        per_item: dict[int, int] = {}
        for g in groups:
            for ln in g.get("items", []):
                iid = int(ln.get("item_id", 0) or 0)
                per_item[iid] = per_item.get(iid, 0) + int(ln.get("nums", 0) or 0)
        for r in rows:
            add = per_item.get(int(r.id), 0)
            if add <= 0:
                continue
            new_split = int(r.split_num or 0) + add
            if new_split > int(r.nums or 0):
                raise ValidationError(
                    f"split_num 超限（行{r.id}: {new_split} > {r.nums}）"
                )
            r.split_num = new_split
        order.splited_num = int(order.splited_num or 0) + 1

    async def _dispatch_alloc(self, order_id: int) -> dict[int, dict[int, int]]:
        """取最新生效的分仓 plan（行→仓→量）

        拆单组 attrs 可能不带 branch_id（如 owner 单策略），
        此时发货单的仓从分仓 plan 按行兜底（FR-03b 组属性映射）。
        """
        from app.models.fulfill import OrdDispatchPlan

        plan = await self.s.scalar(
            select(OrdDispatchPlan)
            .where(
                OrdDispatchPlan.order_id == order_id,
                OrdDispatchPlan.status == "effective",
            )
            .order_by(OrdDispatchPlan.round_no.desc())
            .limit(1)
        )
        if not plan or not plan.alloc:
            return {}
        out: dict[int, dict[int, int]] = {}
        for item_id, branch_map in (plan.alloc or {}).items():
            try:
                out[int(item_id)] = {
                    int(b): int(q) for b, q in (branch_map or {}).items()
                }
            except (TypeError, ValueError):
                continue
        return out

    async def _next_delivery_bn(self) -> str:
        """发货单号（FR-01c：DLV+日期+序列，唯一索引）

        与订单号规则不同——发货单号不含店铺码（订单号规则见 D03.01 FR-03c）。
        Redis 优先，失败降级 DB 号段。
        """
        now = datetime.now()
        yymmdd = now.strftime("%y%m%d")
        seq = 0
        if self.r is not None:
            try:
                seq = int(await self.r.incr(f"delivery:seq:{yymmdd}"))
            except Exception:
                seq = 0
        if seq <= 0:
            seq = await self._next_delivery_seq_db(yymmdd)
        return f"DLV{yymmdd}{seq:06d}"

    async def _next_delivery_seq_db(self, yymmdd: str) -> int:
        """DB 号段降级（CAS 发号）"""
        from datetime import date as _date

        from app.models.base import BaseSeq

        parsed = datetime.strptime(yymmdd, "%y%m%d")
        seq_date = _date(parsed.year + 2000, parsed.month, parsed.day)
        row = await self.s.scalar(
            select(BaseSeq).where(
                BaseSeq.seq_domain == "DLV", BaseSeq.seq_date == seq_date
            )
        )
        if row is None:
            row = BaseSeq(
                seq_domain="DLV",
                seq_date=seq_date,
                current_value=0,
                step_size=1000,
                max_value=999999,
                remark="发货单号序列（Redis 故障降级号段）",
            )
            self.s.add(row)
            await self.s.commit()
            await self.s.refresh(row)
        row.current_value = int(row.current_value or 0) + 1
        await self.s.commit()
        return int(row.current_value)

    # ==================== 状态机（FR-02）====================

    async def transit(
        self,
        delivery_id: int,
        command: str,
        *,
        reason: str = "",
        operator: str = "system",
        ref_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> DeliveryOutcome:
        """状态变更唯一入口（§5.2）

        当前态+指令合法性校验（表驱动）→ 行级锁 → 状态落库 + delivery_log 同事务。
        非法流转拒绝并告警；重复指令幂等（同指令同轮次返回首次结果）。
        """
        out = DeliveryOutcome()
        out.command = command

        delivery = await self.s.scalar(
            select(OrdDelivery)
            .where(OrdDelivery.id == delivery_id, OrdDelivery.is_deleted == 0)
            .with_for_update()
        )
        if not delivery:
            raise NotFoundError(f"发货单不存在: {delivery_id}")
        out.delivery_id = delivery.id
        out.delivery_bn = delivery.delivery_bn
        out.from_status = delivery.status

        # 终态保护
        if delivery.status in FINAL_STATES:
            out.ok = False
            out.fail_code = "INVALID_TRANSITION"
            out.fail_message = f"发货单已处于终态 {delivery.status}，不可再流转"
            return out

        tr = find_transition(command, delivery.status)
        if tr is None:
            out.ok = False
            out.fail_code = "INVALID_TRANSITION"
            out.fail_message = (
                f"非法流转：{delivery.status} --{command}--> ? "
                f"（该状态允许指令：{allowed_commands(delivery.status)}）"
            )
            logger.warning(
                "发货单非法流转拦截: delivery=%s status=%s command=%s",
                delivery.delivery_bn, delivery.status, command,
            )
            return out

        delivery.status = tr.to_status
        out.to_status = tr.to_status

        # 推仓同步状态联动
        if command == CMD_PUSH:
            delivery.sync_status = SYNC_SUCC
            delivery.sync_msg = None
        elif command == CMD_PUSH_FAILED:
            delivery.sync_status = SYNC_FAIL
            delivery.sync_msg = reason or "推送失败"
        elif command in (CMD_CANCEL, CMD_REJECT):
            delivery.sync_status = SYNC_FAIL if reason else delivery.sync_status
            delivery.sync_msg = reason or delivery.sync_msg

        if command == CMD_CONFIRM:
            delivery.delivery_time = datetime.now()
        if command == CMD_FINISH:
            delivery.finish_time = datetime.now()

        # 留痕（FR-02d）
        self.s.add(
            OrdDeliveryLog(
                tenant_id=1,
                delivery_id=delivery.id,
                command=command,
                from_status=tr.from_status,
                to_status=tr.to_status,
                operator=operator,
                reason=reason or None,
                ref_id=ref_id or None,
            )
        )
        await self.s.commit()
        out.ok = True
        out.detail = payload or {}
        return out

    # ==================== 四指令（IF-D03.07-02）====================

    async def push(
        self,
        delivery_id: int,
        operator: str = "system",
        reason: str = "",
        push_round: int = 1,
    ) -> DeliveryOutcome:
        """推送指令（draft/recalled → pushed）

        W7 起：实际下发委派 **D09.02 出库指令通道**（`OutboundCommandService.push`）——
        本模块负责状态流转与进度口径，通道负责报文组装/路由/下发/重试。
        通道返回受理即视为推送成功（受理即返回，FR-01a）；下发失败 → 本单置 push_failed。
        """
        # ① 先走通道（受理即返回）——失败不进 pushed
        cmd_res = await self._dispatch_push(delivery_id, push_round, operator, reason)
        if not cmd_res.ok:
            out = DeliveryOutcome()
            out.ok = False
            out.delivery_id = delivery_id
            out.command = CMD_PUSH
            out.fail_code = cmd_res.err_code or "PUSH_FAILED"
            out.fail_message = cmd_res.err_msg or "推仓下发失败"
            out.detail = cmd_res.to_dict()
            # 置 push_failed（表驱动流转：draft → push_failed）
            failed = await self.transit(
                delivery_id, CMD_PUSH_FAILED, operator=operator,
                reason=out.fail_message,
            )
            out.to_status = failed.to_status
            return out

        # ② 状态流转 draft → pushed
        res = await self.transit(
            delivery_id, CMD_PUSH, operator=operator, reason=reason
        )
        if res.ok:
            delivery = await self._get(delivery_id)
            if delivery and cmd_res.wms_bill_no:
                delivery.wms_bill_no = cmd_res.wms_bill_no
                await self.s.commit()
        res.detail = cmd_res.to_dict()
        return res

    async def _dispatch_push(
        self,
        delivery_id: int,
        push_round: int,
        operator: str,
        reason: str,
    ):
        """委派 D09.02 通道下发

        通道**业务级失败**（无绑定/适配器缺失/下发失败）→ 原样上抛，由调用方置 push_failed；
        通道**基础设施不可用**（连接异常等）→ 降级为本地占位，不阻断推仓状态流转。
        """
        from app.core.exceptions import NotFoundError as _NotFound
        from app.services.wms_channel import OutboundCommandService

        try:
            svc = OutboundCommandService(self.s, self.r)
            res = await svc.push([delivery_id], push_round=push_round)
            return res[0] if res else None
        except _NotFound:
            raise
        except Exception as e:
            logger.warning("推仓通道调用失败（降级为本地占位）: %s", e)
            delivery = await self._get(delivery_id)
            if delivery is None:
                raise
            return _FallbackCmdResult(delivery)

    async def recall(
        self,
        delivery_ids: list[int],
        operator: str = "system",
        reason: str = "",
        ref_id: str = "",
    ) -> list[DeliveryOutcome]:
        """叫回指令（IF-D03.07-02 / FR-08b）

        合单组级联叫回：任一失败按整体失败。
        """
        out: list[DeliveryOutcome] = []
        for did in delivery_ids:
            out.append(
                await self.transit(
                    did, CMD_RECALL, operator=operator, reason=reason, ref_id=ref_id
                )
            )
        return out

    async def recall_result(
        self,
        delivery_id: int,
        success: bool,
        operator: str = "system",
        reason: str = "",
    ) -> DeliveryOutcome:
        """叫回结果回传（成功 → recalled；失败 → 回原态）"""
        if success:
            return await self.transit(
                delivery_id, CMD_RECALL, operator=operator, reason=reason
            )
        # 失败：从 recalling 回 processing（表内定义）
        delivery = await self._get(delivery_id)
        if delivery and delivery.status == ST_RECALLING:
            return await self.transit(
                delivery_id, CMD_RECALL_FAIL, operator=operator, reason=reason
            )
        out = DeliveryOutcome()
        out.ok = False
        out.fail_code = "INVALID_TRANSITION"
        out.fail_message = f"当前状态 {delivery.status if delivery else '?'} 不可回叫回失败"
        return out

    async def resume(
        self, delivery_id: int, operator: str = "system", reason: str = ""
    ) -> DeliveryOutcome:
        """恢复指令（recalled → pushed，FR-08c：恢复前复核）"""
        delivery = await self._get(delivery_id)
        if not delivery:
            raise NotFoundError(f"发货单不存在: {delivery_id}")
        # 复核：hold 的预售单不可恢复推仓
        if delivery.hold_flag == 1:
            out = DeliveryOutcome()
            out.ok = False
            out.fail_code = "HOLD_NOT_RELEASED"
            out.fail_message = "预售 hold 单未放行，不可恢复"
            out.delivery_id = delivery.id
            out.from_status = delivery.status
            return out
        return await self.transit(
            delivery_id, CMD_RESUME, operator=operator, reason=reason
        )

    async def confirm(
        self, delivery_id: int, operator: str = "system", reason: str = ""
    ) -> DeliveryOutcome:
        """确认指令（outbound → shipped，FR-05d）

        确认成功后发布 **`order.delivery.shipped`** 事件（DB-00 附录 A 关键事件）——
        D02.04 平台回传 / D08.01 应收 / D08.04 运费对账 / D09.04 轨迹 共同消费。
        """
        res = await self.transit(
            delivery_id, CMD_CONFIRM, operator=operator, reason=reason
        )
        if res.ok:
            await self._link_order_ship_status(delivery_id, operator)
            await self._publish_shipped_event(delivery_id)
        return res

    async def _publish_shipped_event(self, delivery_id: int) -> None:
        """发布 `order.delivery.shipped` 事件（FR-06c）"""
        delivery = await self._get(delivery_id)
        if not delivery:
            return
        payload = {
            "delivery_id": delivery.id,
            "delivery_bn": delivery.delivery_bn,
            "order_id": delivery.order_id,
            "branch_id": delivery.branch_id,
            "owner_id": delivery.owner_id,
            "shop_id": delivery.shop_id,
            "logi_id": delivery.logi_id,
            "logi_no": delivery.logi_no,
            "packages": [],
        }
        try:
            await self.s.execute(
                text(
                    "INSERT INTO oms_base.bas_event_outbox "
                    "(tenant_id, event_id, event_name, reliability, idempotent_key, "
                    " aggregate_type, aggregate_id, owner_id, trace_id, partition_key, "
                    " payload, schema_version, delay_seconds, status, retry_count, "
                    " next_retry_time, publish_time, create_time, update_time, version) "
                    "VALUES (1, :eid, 'order.delivery.shipped', 'reliable', :idem, "
                    " 'order', :aid, :owner, '', :pkey, :payload, 'v1', 0, 0, 0, "
                    " NULL, NULL, NOW(3), NOW(3), 0)"
                ),
                {
                    "eid": uuid4().hex[:26],
                    "idem": f"order.delivery.shipped:{delivery_id}",
                    "aid": str(delivery.order_id),
                    "owner": int(delivery.owner_id or 0),
                    "pkey": str(delivery.order_id),
                    "payload": json.dumps(payload, ensure_ascii=False, default=str),
                },
            )
            await self.s.commit()
        except Exception as e:
            logger.warning("发货事件入 outbox 失败: %s", e)
            await self.s.rollback()

    async def finish(
        self, delivery_id: int, operator: str = "system", reason: str = ""
    ) -> DeliveryOutcome:
        """收货确认/超时（shipped → finished，FR-06d）"""
        return await self.transit(
            delivery_id, CMD_FINISH, operator=operator, reason=reason
        )

    # ==================== 取消与打回（FR-08）====================

    async def cancel(
        self, delivery_id: int, reason: str, operator: str = "system"
    ) -> DeliveryOutcome:
        """发货单取消（FR-08a：原子编排）

        draft 直接取消；pushed/processing 先叫回成功再取消；
        outbound 及之后不可取消（转售后拦截）。
        """
        delivery = await self._get(delivery_id)
        if not delivery:
            raise NotFoundError(f"发货单不存在: {delivery_id}")
        if delivery.status in (ST_OUTBOUND, ST_PARTIAL_OUTBOUND, ST_SHIPPED, ST_FINISHED):
            out = DeliveryOutcome()
            out.ok = False
            out.fail_code = "CANNOT_CANCEL"
            out.fail_message = "已出库及之后不可取消（转售后拦截）"
            out.delivery_id = delivery.id
            out.from_status = delivery.status
            return out
        if delivery.status in (ST_PUSHED, ST_PROCESSING):
            out = DeliveryOutcome()
            out.ok = False
            out.fail_code = "NEED_RECALL_FIRST"
            out.fail_message = "已推仓发货单须先叫回成功再取消"
            out.delivery_id = delivery.id
            out.from_status = delivery.status
            return out
        res = await self.transit(
            delivery_id, CMD_CANCEL, operator=operator, reason=reason
        )
        if res.ok:
            await self._rollback_progress(delivery_id)
        return res

    async def reject(
        self, delivery_id: int, reason: str, operator: str = "system"
    ) -> DeliveryOutcome:
        """WMS 打回（FR-08d / SC-09）

        rejected 状态 + 结构化原因 → 订单行 split_num 回退 + 订单回审单池。
        """
        res = await self.transit(
            delivery_id, CMD_REJECT, operator=operator, reason=reason
        )
        if res.ok:
            await self._rollback_progress(delivery_id)
        return res

    async def _rollback_progress(self, delivery_id: int) -> None:
        """拆单进度回退（FR-06d：split_num 扣减；splited_num 不回退）"""
        delivery = await self._get(delivery_id)
        if not delivery:
            return
        details = list(
            await self.s.scalars(
                select(OrdDeliveryItemDetail).where(
                    OrdDeliveryItemDetail.delivery_id == delivery_id
                )
            )
        )
        if not details:
            return
        item_ids = [int(d.order_item_id) for d in details]
        rows = list(
            await self.s.scalars(select(OrdOrderItem).where(OrdOrderItem.id.in_(item_ids)))
        )
        by_id = {int(r.id): r for r in rows}
        for d in details:
            it = by_id.get(int(d.order_item_id))
            if it:
                it.split_num = max(0, int(it.split_num or 0) - int(d.split_qty or 0))
        await self.s.commit()

    # ==================== 出库回传处理（FR-05b/c）====================

    async def handle_callback(
        self,
        delivery_id: int,
        batch: dict[str, Any],
        *,
        operator: str = "wms",
    ) -> DeliveryOutcome:
        """出库回传处理编排（§5.3，顺序固定）

        ① 行匹配 → ② 逐行 settle → ③ 差异处理 → ④ 包裹/称重/运单落库
        → ⑤ 状态流转 → ⑥ 发货确认 → ⑦ 发布事件

        幂等：(delivery_id, batch_no) 已处理 → 忽略。
        """
        out = DeliveryOutcome()
        batch_no = str(batch.get("batch_no", "") or "")
        delivery = await self._get(delivery_id)
        if not delivery:
            raise NotFoundError(f"发货单不存在: {delivery_id}")
        out.delivery_id = delivery.id
        out.delivery_bn = delivery.delivery_bn
        out.from_status = delivery.status

        # 幂等：同批次已落库 → 忽略
        exists = await self.s.scalar(
            select(OrdDeliveryPackage)
            .where(
                OrdDeliveryPackage.delivery_id == delivery_id,
                OrdDeliveryPackage.batch_no == batch_no,
            )
            .limit(1)
        )
        if exists is not None:
            out.ok = True
            out.to_status = delivery.status
            out.detail = {"duplicated": True, "batch_no": batch_no}
            return out

        items = list(
            await self.s.scalars(
                select(OrdDeliveryItem).where(OrdDeliveryItem.delivery_id == delivery_id)
            )
        )
        details = list(
            await self.s.scalars(
                select(OrdDeliveryItemDetail).where(
                    OrdDeliveryItemDetail.delivery_id == delivery_id
                )
            )
        )
        detail_by_item: dict[int, list[OrdDeliveryItemDetail]] = {}
        for det in details:
            detail_by_item.setdefault(int(det.delivery_item_id), []).append(det)

        settled_total = 0
        diff_rows: list[dict[str, Any]] = []
        for cb_line in batch.get("lines", []):
            bm_id = int(cb_line.get("bm_id", 0) or 0)
            actual = int(cb_line.get("num", 0) or 0)
            target = None
            for di in items:
                if int(di.bm_id or 0) == bm_id:
                    target = di
                    break
            if target is None:
                diff_rows.append(
                    {
                        "diff_type": "short",
                        "diff_num": actual,
                        "liability": "wms",
                        "handle_way": "recon",
                        "memo": "回传明细匹配不到发货单行（差异登记人工）",
                    }
                )
                continue
            remain = int(target.num or 0) - int(target.settled_num or 0)
            num = min(actual, remain) if remain > 0 else 0
            # 指令量（未核销口径）—— 少发判定用它与实发比
            instruct = remain
            if num > 0:
                target.settled_num = int(target.settled_num or 0) + num
                settled_total += num
                # 订单行 sendnum 回写（detail 溯源到订单行，FR-06a）
                for det in detail_by_item.get(int(target.id), []):
                    ratio = (
                        int(det.split_qty or 0) / int(target.num or 1)
                        if int(target.num or 0) > 0
                        else 0
                    )
                    add = max(1, int(num * ratio)) if ratio > 0 else num
                    src = await self.s.scalar(
                        select(OrdOrderItem).where(
                            OrdOrderItem.id == int(det.order_item_id)
                        )
                    )
                    if src:
                        src.sendnum = int(src.sendnum or 0) + min(
                            add, int(det.split_qty or 0)
                        )
            # 差异（SC-03：少发释放 / 多发直扣）
            # 判定基准 = 指令量（未核销）与实发量之差
            if actual > instruct:
                diff_rows.append(
                    {
                        "diff_type": "over",
                        "diff_num": actual - instruct,
                        "liability": "wms",
                        "handle_way": "recon",
                        "memo": "实发大于指令量（差额直扣实际库存）",
                    }
                )
            elif actual < instruct:
                diff_rows.append(
                    {
                        "diff_type": "short",
                        "diff_num": instruct - actual,
                        "liability": "wms",
                        "handle_way": "reship",
                        "memo": "实发小于指令量（差额预占释放）",
                    }
                )

        # ④ 包裹/称重/运单落库
        self.s.add(
            OrdDeliveryPackage(
                tenant_id=1,
                owner_id=delivery.owner_id,
                delivery_id=delivery_id,
                package_no=str(batch.get("package_no", "") or "") or None,
                waybill_no=str(batch.get("waybill_no", "") or "") or None,
                logi_id=int(batch.get("logi_id", 0) or 0) or None,
                weight=batch.get("weight"),
                volume=batch.get("volume"),
                pack_items=batch.get("pack_items"),
                batch_no=batch_no,
                callback_time=datetime.now(),
            )
        )
        if batch.get("waybill_no"):
            delivery.logi_no = str(batch["waybill_no"])

        # 差异登记
        for drow in diff_rows:
            self.s.add(
                OrdDeliveryDiff(
                    tenant_id=1,
                    owner_id=delivery.owner_id,
                    delivery_id=delivery_id,
                    order_id=delivery.order_id,
                    diff_type=str(drow["diff_type"]),
                    diff_num=int(drow["diff_num"]),
                    liability=drow.get("liability"),
                    handle_way=drow.get("handle_way"),
                    handle_status="open",
                    memo=drow.get("memo"),
                    operator=operator,
                )
            )

        # ⑤ 状态流转：全部核销 → outbound；否则 partial_outbound
        all_settled = all(
            int(di.settled_num or 0) >= int(di.num or 0) for di in items
        )
        target_status = ST_OUTBOUND if all_settled else ST_PARTIAL_OUTBOUND
        if delivery.status != target_status:
            delivery.status = target_status
            self.s.add(
                OrdDeliveryLog(
                    tenant_id=1,
                    delivery_id=delivery_id,
                    command=CMD_CB_OUT,
                    from_status=out.from_status,
                    to_status=target_status,
                    operator=operator,
                    reason=f"出库回传批次 {batch_no}",
                )
            )
        out.to_status = target_status
        await self.s.commit()

        # ⑥ 发货确认（齐套则自动确认）
        if all_settled:
            confirmed = await self.confirm(delivery_id, operator=operator, reason="齐套自动确认")
            out.detail = {
                "settled": settled_total,
                "diff_count": len(diff_rows),
                "confirmed": confirmed.ok,
            }
            out.ok = True
        else:
            out.ok = True
            out.detail = {
                "settled": settled_total,
                "diff_count": len(diff_rows),
                "partial": True,
            }
        return out

    async def _link_order_ship_status(self, delivery_id: int, operator: str) -> None:
        """订单发货状态联动（FR-06a/b：按订单行口径聚合）"""
        delivery = await self._get(delivery_id)
        if not delivery:
            return
        rows = list(
            await self.s.scalars(
                select(OrdOrderItem).where(
                    OrdOrderItem.order_id == delivery.order_id,
                    OrdOrderItem.is_deleted == 0,
                )
            )
        )
        if not rows:
            return
        all_done = all(int(r.sendnum or 0) >= int(r.nums or 0) for r in rows)
        any_done = any(int(r.sendnum or 0) > 0 for r in rows)
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == delivery.order_id).limit(1)
        )
        if not order:
            return
        if all_done:
            order.ship_status = "shipped"
        elif any_done:
            order.ship_status = "partial_shipped"
        else:
            order.ship_status = "unshipped"
        if not order.delivery_time:
            order.delivery_time = datetime.now()
        await self.s.commit()

    # ==================== 查询（FR-10）====================

    async def _get(self, delivery_id: int) -> OrdDelivery | None:
        return await self.s.scalar(
            select(OrdDelivery).where(
                OrdDelivery.id == delivery_id, OrdDelivery.is_deleted == 0
            )
        )

    async def get_detail(self, delivery_id: int) -> dict[str, Any]:
        """发货单详情（FR-10a/c：多向钻取）"""
        delivery = await self._get(delivery_id)
        if not delivery:
            raise NotFoundError(f"发货单不存在: {delivery_id}")
        items = list(
            await self.s.scalars(
                select(OrdDeliveryItem)
                .where(OrdDeliveryItem.delivery_id == delivery_id)
                .order_by(OrdDeliveryItem.id)
            )
        )
        details = list(
            await self.s.scalars(
                select(OrdDeliveryItemDetail).where(
                    OrdDeliveryItemDetail.delivery_id == delivery_id
                )
            )
        )
        packages = list(
            await self.s.scalars(
                select(OrdDeliveryPackage)
                .where(OrdDeliveryPackage.delivery_id == delivery_id)
                .order_by(OrdDeliveryPackage.id)
            )
        )
        logs = list(
            await self.s.scalars(
                select(OrdDeliveryLog)
                .where(OrdDeliveryLog.delivery_id == delivery_id)
                .order_by(OrdDeliveryLog.id)
            )
        )
        diffs = list(
            await self.s.scalars(
                select(OrdDeliveryDiff)
                .where(OrdDeliveryDiff.delivery_id == delivery_id)
                .order_by(OrdDeliveryDiff.id)
            )
        )
        # W7：WMS 通道轨迹（指令下发 / 回传 / 通道日志 / 失败台账）
        channel = await self._get_channel_trace(delivery_id, delivery.delivery_bn)
        return {
            "delivery": {
                "id": delivery.id,
                "delivery_bn": delivery.delivery_bn,
                "order_id": delivery.order_id,
                "status": delivery.status,
                "sync_status": delivery.sync_status,
                "sync_msg": delivery.sync_msg,
                "branch_id": delivery.branch_id,
                "logi_id": delivery.logi_id,
                "logi_no": delivery.logi_no,
                "is_bind": delivery.is_bind,
                "parent_id": delivery.parent_id,
                "is_virtual": delivery.is_virtual,
                "hold_flag": delivery.hold_flag,
                "owner_id": delivery.owner_id,
                "shop_id": delivery.shop_id,
                "plan_id": delivery.plan_id,
                "split_trace_id": delivery.split_trace_id,
                "source": delivery.source,
                "delivery_time": (
                    delivery.delivery_time.isoformat() if delivery.delivery_time else None
                ),
                "finish_time": (
                    delivery.finish_time.isoformat() if delivery.finish_time else None
                ),
                "memo": delivery.memo,
            },
            "allowed_commands": allowed_commands(delivery.status),
            "items": [
                {
                    "id": i.id,
                    "bm_id": i.bm_id,
                    "bm_number": i.bm_number,
                    "num": i.num,
                    "settled_num": i.settled_num,
                    "owner_id": i.owner_id,
                    "price": float(i.price or 0),
                }
                for i in items
            ],
            "details": [
                {
                    "id": d.id,
                    "delivery_item_id": d.delivery_item_id,
                    "order_item_id": d.order_item_id,
                    "split_qty": d.split_qty,
                    "freeze_ref": d.freeze_ref,
                }
                for d in details
            ],
            "packages": [
                {
                    "id": p.id,
                    "package_no": p.package_no,
                    "waybill_no": p.waybill_no,
                    "weight": float(p.weight or 0) if p.weight is not None else None,
                    "volume": float(p.volume or 0) if p.volume is not None else None,
                    "batch_no": p.batch_no,
                }
                for p in packages
            ],
            "logs": [
                {
                    "id": lg.id,
                    "command": lg.command,
                    "from_status": lg.from_status,
                    "to_status": lg.to_status,
                    "operator": lg.operator,
                    "reason": lg.reason,
                    "create_time": lg.create_time.isoformat() if lg.create_time else "",
                }
                for lg in logs
            ],
            "diffs": [
                {
                    "id": d.id,
                    "diff_type": d.diff_type,
                    "diff_num": d.diff_num,
                    "liability": d.liability,
                    "handle_way": d.handle_way,
                    "handle_status": d.handle_status,
                    "memo": d.memo,
                }
                for d in diffs
            ],
            "channel": channel,
        }

    async def _get_channel_trace(
        self, delivery_id: int, delivery_bn: str
    ) -> dict[str, Any]:
        """WMS 通道轨迹（D09.02 留痕，供发货单详情下钻）

        四段：出库指令（ful_outbound_cmd）· 回传登记（ful_outbound_callback）
        · 通道日志（ful_channel_log）· 失败台账（ful_cmd_fail）。
        表可能未部署（早期环境）→ 降级返回空轨迹，不阻断详情。
        """
        out: dict[str, Any] = {
            "cmds": [],
            "callbacks": [],
            "logs": [],
            "fails": [],
            "available": False,
        }

        async def _q(sql: str, **params: Any) -> list[Any]:
            try:
                r = await self.s.execute(text(sql), params)
                return list(r.all())
            except Exception as e:  # 表未部署 → 降级
                logger.warning("通道轨迹查询降级: %s", e)
                await self.s.rollback()
                return []

        rows = await _q(
            "SELECT id, cmd_bn, cmd_type, status, wms_bill_no, fail_reason, "
            "       source, push_round, waybill_no, create_time "
            "FROM oms_fulfill.ful_outbound_cmd WHERE delivery_id = :did "
            "ORDER BY id",
            did=delivery_id,
        )
        for r in rows:
            out["cmds"].append(
                {
                    "id": int(r[0]),
                    "cmd_bn": str(r[1] or ""),
                    "cmd_type": str(r[2] or ""),
                    "status": str(r[3] or ""),
                    "wms_bill_no": str(r[4] or ""),
                    "fail_reason": str(r[5] or "")[:200],
                    "source": str(r[6] or ""),
                    "push_round": int(r[7] or 0),
                    "waybill_no": str(r[8] or ""),
                    "create_time": r[9].isoformat() if r[9] else "",
                }
            )

        rows = await _q(
            "SELECT id, callback_type, wms_batch_no, process_status, "
            "       reject_reason, receive_time, create_time "
            "FROM oms_fulfill.ful_outbound_callback WHERE delivery_id = :did "
            "ORDER BY id",
            did=delivery_id,
        )
        for r in rows:
            out["callbacks"].append(
                {
                    "id": int(r[0]),
                    "callback_type": str(r[1] or ""),
                    "wms_batch_no": str(r[2] or ""),
                    "process_status": str(r[3] or ""),
                    "reject_reason": str(r[4] or "")[:200],
                    "receive_time": r[5].isoformat() if r[5] else "",
                    "create_time": r[6].isoformat() if r[6] else "",
                }
            )

        rows = await _q(
            "SELECT id, cmd_bn, direction, action, err_class, err_code, "
            "       spendtime_ms, create_time "
            "FROM oms_fulfill.ful_channel_log "
            "WHERE cmd_bn LIKE :p1 OR cmd_bn LIKE :p2 "
            "ORDER BY id",
            p1=f"CMD{delivery_bn}-%",
            p2=f"{delivery_bn}-%",
        )
        for r in rows:
            out["logs"].append(
                {
                    "id": int(r[0]),
                    "cmd_bn": str(r[1] or ""),
                    "direction": int(r[2] or 0),
                    "action": str(r[3] or ""),
                    "err_class": str(r[4] or ""),
                    "err_code": str(r[5] or ""),
                    "spend_ms": int(r[6] or 0),
                    "create_time": r[7].isoformat() if r[7] else "",
                }
            )

        rows = await _q(
            "SELECT id, cmd_bn, err_class, err_code, err_msg, retry_times, "
            "       next_retry_time, status, create_time "
            "FROM oms_fulfill.ful_cmd_fail "
            "WHERE cmd_bn LIKE :p1 OR cmd_bn LIKE :p2 "
            "ORDER BY id",
            p1=f"CMD{delivery_bn}-%",
            p2=f"{delivery_bn}-%",
        )
        for r in rows:
            out["fails"].append(
                {
                    "id": int(r[0]),
                    "cmd_bn": str(r[1] or ""),
                    "err_code": str(r[2] or ""),
                    "err_class": str(r[3] or ""),
                    "err_msg": str(r[4] or "")[:200],
                    "retry_times": int(r[5] or 0),
                    "next_retry_time": r[6].isoformat() if r[6] else "",
                    "status": str(r[7] or ""),
                    "create_time": r[8].isoformat() if r[8] else "",
                }
            )

        out["available"] = bool(out["cmds"] or out["callbacks"])
        return out

    async def list_deliveries(
        self,
        *,
        status: str | None = None,
        branch_id: int | None = None,
        shop_id: int | None = None,
        order_id: int | None = None,
        keyword: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """发货单列表（FR-10a：多维筛选 + 行级过滤自动生效）"""
        q = select(OrdDelivery).where(OrdDelivery.is_deleted == 0)
        if status:
            q = q.where(OrdDelivery.status == status)
        if branch_id:
            q = q.where(OrdDelivery.branch_id == branch_id)
        if shop_id:
            q = q.where(OrdDelivery.shop_id == shop_id)
        if order_id:
            q = q.where(OrdDelivery.order_id == order_id)
        if keyword:
            q = q.where(OrdDelivery.delivery_bn.like(f"%{keyword}%"))
        rows = list(
            await self.s.scalars(q.order_by(OrdDelivery.id.desc()).limit(limit))
        )
        return [
            {
                "id": d.id,
                "delivery_bn": d.delivery_bn,
                "order_id": d.order_id,
                "status": d.status,
                "sync_status": d.sync_status,
                "branch_id": d.branch_id,
                "owner_id": d.owner_id,
                "shop_id": d.shop_id,
                "logi_no": d.logi_no,
                "is_virtual": d.is_virtual,
                "source": d.source,
                "create_time": d.create_time.isoformat() if d.create_time else "",
            }
            for d in rows
        ]

    async def abnormal_list(self) -> list[dict[str, Any]]:
        """异常视图（FR-10b：推送失败/叫回失败/回传超时/尾差超期/差异登记）"""
        rows = await self.s.execute(
            text(
                "SELECT id, delivery_bn, status, sync_msg, order_id, branch_id "
                "FROM oms_order.ord_delivery "
                "WHERE is_deleted = 0 AND ("
                "  sync_status = 'fail' OR status IN ('push_failed', 'recalling')"
                ") ORDER BY id DESC LIMIT 100"
            )
        )
        out = [
            {
                "id": r[0],
                "delivery_bn": r[1],
                "status": r[2],
                "sync_msg": r[3],
                "order_id": r[4],
                "branch_id": r[5],
                "abnormal_type": "push_failed" if r[2] == "push_failed" else "sync_fail",
            }
            for r in rows.all()
        ]
        diff_rows = await self.s.execute(
            text(
                "SELECT d.id, d.delivery_id, v.delivery_bn, d.diff_type, d.diff_num, "
                "       d.handle_status, d.memo "
                "FROM oms_order.ord_delivery_diff d "
                "LEFT JOIN oms_order.ord_delivery v ON v.id = d.delivery_id "
                "WHERE d.is_deleted = 0 AND d.handle_status = 'open' "
                "ORDER BY d.id DESC LIMIT 100"
            )
        )
        for r in diff_rows.all():
            out.append(
                {
                    "id": r[0],
                    "delivery_id": r[1],
                    "delivery_bn": r[2],
                    "abnormal_type": "diff",
                    "diff_type": r[3],
                    "diff_num": r[4],
                    "handle_status": r[5],
                    "memo": r[6],
                }
            )
        return out
