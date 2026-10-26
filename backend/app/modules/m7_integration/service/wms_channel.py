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
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.wms import (
    WmsCallResult,
    WmsRoute,
    get_adapter,
)
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.fulfill import (
    OrdDelivery,
    OrdDeliveryItem,
    OrdDeliveryItemDetail,
)

logger = get_logger("wms_channel")

#: 指令状态（§4.2 通道侧状态机投影）
CMD_ACCEPTED = "accepted"      # 已受理
CMD_SENT = "sent"              # 已下发
CMD_WORKING = "working"        # WMS 作业中
CMD_PARTIAL = "partial"        # 部分回传
CMD_COMPLETED = "completed"    # 回传闭环
CMD_CANCELLED = "cancelled"    # 已取消
CMD_REJECTED = "rejected"      # 已打回
CMD_FAILED = "failed"          # 下发失败
CMD_BUFFERED = "buffered"      # 缓冲中（熔断降级）

#: 错误分类
ERR_RETRYABLE = "RETRYABLE"
ERR_FATAL = "FATAL"
ERR_BIZ_REJECT = "BIZ_REJECT"

#: 退避序列（分钟，D02.05 同款）
BACKOFF_MINUTES = (1, 5, 15, 60)
#: 重试上限（超限进终态失败 + 告警）
MAX_RETRY = 5

#: 回传类型
CB_ACCEPTED = "accepted"
CB_OUTBOUND = "outbound"
CB_REJECTED = "rejected"
CB_CANCELLED = "cancelled"
CB_RECALL_FAILED = "recall_failed"

#: 标准化事件名（FR-03e）
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


class WmsRouteService:
    """WMS 路由服务（D09.01 FR-04a：路由四元组）"""

    def __init__(self, session: AsyncSession):
        self.s = session

    async def route(
        self, branch_id: int, owner_id: int, direction: str = "OUT"
    ) -> WmsRoute:
        """路由决策（幂等只读）

        查有效 wms_binding（按 branch + owner 匹配、优先级降序、有效期），
        返回四元组；无绑定 → 结构化失败（ValueError）。
        """
        rows = await self.s.execute(
            text(
                "SELECT b.id, b.wms_id, b.protocol, b.adapter_code, b.wms_branch_code, "
                "       COALESCE(b.wms_owner_code, '') AS wms_owner_code, "
                "       COALESCE(b.app_key, '') AS app_key, "
                "       b.endpoint, b.timeout_ms, b.capability_json, b.priority "
                "FROM oms_fulfill.ful_wms_binding b "
                "JOIN oms_fulfill.ful_wms w ON w.id = b.wms_id "
                "WHERE b.branch_id = :bid AND b.is_deleted = 0 AND b.status = 'active' "
                "  AND w.status = 'enabled' AND w.is_deleted = 0 "
                "  AND (b.owner_id IS NULL OR b.owner_id = :oid) "
                "  AND (b.effective_from IS NULL OR b.effective_from <= NOW(3)) "
                "  AND (b.effective_to IS NULL OR b.effective_to > NOW(3)) "
                "ORDER BY b.priority ASC, b.id ASC LIMIT 1"
            ),
            {"bid": branch_id, "oid": owner_id},
        )
        row = rows.mappings().first()
        if not row:
            raise NotFoundError(
                f"无 WMS 绑定（仓 {branch_id} · 货主 {owner_id} · 方向 {direction}）"
            )
        cap = row["capability_json"]
        if isinstance(cap, str):
            try:
                cap = json.loads(cap)
            except (TypeError, ValueError):
                cap = {}
        return WmsRoute(
            wms_id=int(row["wms_id"]),
            binding_id=int(row["id"]),
            adapter_code=str(row["adapter_code"] or ""),
            app_key=str(row["app_key"] or ""),
            # secret：生产从 secret_enc 解密；仿真期取环境变量默认值
            secret=os.environ.get("MOCK_WMS_SECRET", "mock_wms_secret"),
            wms_branch_code=str(row["wms_branch_code"] or ""),
            wms_owner_code=str(row["wms_owner_code"] or ""),
            protocol=str(row["protocol"] or "qimen"),
            endpoint=str(row["endpoint"] or ""),
            timeout_ms=int(row["timeout_ms"] or 10000),
            capability=cap or {},
        )


class OutboundCommandService:
    """出库指令通道服务（D09.02 FR-01/02/03/04）"""

    def __init__(self, session: AsyncSession, redis: Redis):
        self.s = session
        self.r = redis
        self.router = WmsRouteService(session)

    # ==================== 指令下发（FR-01）====================

    async def push(
        self, delivery_ids: list[int], push_round: int = 1
    ) -> list[CmdOutcome]:
        """出库指令下发（FR-01a：受理即返回）

        幂等：delivery_id + 推送轮次。同一轮次重复调用返回首次指令记录。
        """
        out: list[CmdOutcome] = []
        for did in delivery_ids:
            out.append(await self._push_one(did, push_round))
        return out

    async def _push_one(self, delivery_id: int, push_round: int) -> CmdOutcome:
        delivery = await self.s.scalar(
            select(OrdDelivery).where(
                OrdDelivery.id == delivery_id, OrdDelivery.is_deleted == 0
            )
        )
        if not delivery:
            raise NotFoundError(f"发货单不存在: {delivery_id}")

        # 幂等：同轮次已存在指令 → 直接返回
        idem_key = f"{delivery_id}:{push_round}"
        exist = await self.s.execute(
            text(
                "SELECT id, cmd_bn, status, wms_bill_no FROM oms_fulfill.ful_outbound_cmd "
                "WHERE idempotent_key = :k LIMIT 1"
            ),
            {"k": idem_key},
        )
        exist_row = exist.mappings().first()
        if exist_row:
            return CmdOutcome(
                ok=True,
                cmd_id=int(exist_row["id"]),
                cmd_bn=str(exist_row["cmd_bn"]),
                status=str(exist_row["status"]),
                wms_bill_no=str(exist_row["wms_bill_no"] or ""),
                accepted=True,
                detail={"duplicated": True},
            )

        # 能力前置：叫回不支持等（FR-04c 口径，推送侧校验 WMS 绑定有效性）
        try:
            route = await self.router.route(delivery.branch_id, delivery.owner_id, "OUT")
        except NotFoundError as e:
            return CmdOutcome(
                ok=False,
                err_code="wms.no-binding",
                err_class=ERR_FATAL,
                err_msg=str(e),
            )

        dto = await self._build_dto(delivery, push_round, route)
        if not dto.get("lines"):
            return CmdOutcome(
                ok=False,
                err_code="wms.invalid-payload",
                err_class=ERR_FATAL,
                err_msg="发货单无有效明细行（物料未映射）",
            )

        # 指令记录落库（受理态）
        cmd_bn = f"CMD{delivery.delivery_bn}-{push_round}"
        cmd_no = f"{delivery.delivery_bn}-R{push_round}"
        cmd_id = await self._save_cmd(
            delivery=delivery,
            route=route,
            cmd_bn=cmd_bn,
            cmd_no=cmd_no,
            push_round=push_round,
            dto=dto,
            idem_key=idem_key,
        )

        # 下发（同步执行；生产走 MQ 异步消费，语义一致）
        adapter = get_adapter(route.adapter_code)
        if adapter is None:
            await self._mark_failed(cmd_id, "wms.unknown-error", ERR_FATAL,
                                   f"未注册的适配器: {route.adapter_code}")
            return CmdOutcome(
                ok=False,
                cmd_id=cmd_id,
                cmd_bn=cmd_bn,
                cmd_no=cmd_no,
                err_code="wms.unknown-error",
                err_class=ERR_FATAL,
                err_msg=f"未注册的适配器: {route.adapter_code}",
            )

        payload = adapter.build_payload(dto, route)
        res = await adapter.outbound_push(route, payload)
        await self._log_channel(
            cmd_id=cmd_id,
            cmd_bn=cmd_bn,
            wms_id=route.wms_id,
            action="outbound_push",
            payload=payload,
            res=res,
        )
        return await self._handle_push_result(cmd_id, cmd_bn, cmd_no, res, delivery)

    async def _handle_push_result(
        self,
        cmd_id: int,
        cmd_bn: str,
        cmd_no: str,
        res: WmsCallResult,
        delivery: OrdDelivery | None = None,
    ) -> CmdOutcome:
        """下发结果处理（FR-01c/FR-01d/FR-01f）"""
        if res.succ:
            await self.s.execute(
                text(
                    "UPDATE oms_fulfill.ful_outbound_cmd "
                    "SET status = :st, wms_bill_no = :bn WHERE id = :id"
                ),
                {"st": CMD_SENT, "bn": res.wms_bill_no, "id": cmd_id},
            )
            await self.s.commit()
            # 事件：wms.outbound.pushed → D03.07 置 pushed
            await self._publish(
                EVENT_PUSHED,
                {
                    "cmd_id": cmd_id,
                    "cmd_bn": cmd_bn,
                    "cmd_no": cmd_no,
                    "delivery_id": delivery.id if delivery else 0,
                    "delivery_bn": delivery.delivery_bn if delivery else "",
                    "wms_bill_no": res.wms_bill_no,
                },
            )
            return CmdOutcome(
                ok=True,
                cmd_id=cmd_id,
                cmd_bn=cmd_bn,
                cmd_no=cmd_no,
                wms_bill_no=res.wms_bill_no,
                status=CMD_SENT,
                accepted=True,
                detail={"duplicated": res.duplicated},
            )

        # 失败：分级处理（FR-01d）
        err_class = res.err_class or ERR_RETRYABLE
        if err_class == ERR_RETRYABLE:
            retry_times = await self._bump_retry(cmd_id, res)
            if retry_times < MAX_RETRY:
                nxt = datetime.now() + timedelta(
                    minutes=BACKOFF_MINUTES[min(retry_times - 1, len(BACKOFF_MINUTES) - 1)]
                )
                await self._register_fail(
                    cmd_id, cmd_bn, res, retry_times, nxt
                )
                return CmdOutcome(
                    ok=False,
                    cmd_id=cmd_id,
                    cmd_bn=cmd_bn,
                    cmd_no=cmd_no,
                    err_code=res.err_code,
                    err_class=err_class,
                    err_msg=res.err_msg,
                    next_retry_time=nxt,
                    retry_times=retry_times,
                    detail={"will_retry": True},
                )
            # 超限 → 终态失败
            await self._mark_failed(cmd_id, res.err_code, ERR_RETRYABLE,
                                   f"重试超限（{retry_times}次）: {res.err_msg}")
            await self._publish(
                EVENT_PUSH_FAILED,
                {
                    "cmd_id": cmd_id,
                    "cmd_bn": cmd_bn,
                    "cmd_no": cmd_no,
                    "delivery_id": delivery.id if delivery else 0,
                    "delivery_bn": delivery.delivery_bn if delivery else "",
                    "err_code": res.err_code,
                    "err_class": err_class,
                    "err_msg": res.err_msg,
                    "retry_times": retry_times,
                },
            )
            return CmdOutcome(
                ok=False,
                cmd_id=cmd_id,
                cmd_bn=cmd_bn,
                cmd_no=cmd_no,
                err_code=res.err_code,
                err_class=err_class,
                err_msg=f"重试超限: {res.err_msg}",
                retry_times=retry_times,
            )

        # FATAL / BIZ_REJECT → 不重试
        await self._mark_failed(cmd_id, res.err_code, err_class, res.err_msg)
        await self._publish(
            EVENT_PUSH_FAILED,
            {
                "cmd_id": cmd_id,
                "cmd_bn": cmd_bn,
                "cmd_no": cmd_no,
                "delivery_id": delivery.id if delivery else 0,
                "delivery_bn": delivery.delivery_bn if delivery else "",
                "err_code": res.err_code,
                "err_class": err_class,
                "err_msg": res.err_msg,
            },
        )
        return CmdOutcome(
            ok=False,
            cmd_id=cmd_id,
            cmd_bn=cmd_bn,
            cmd_no=cmd_no,
            err_code=res.err_code,
            err_class=err_class,
            err_msg=res.err_msg,
        )

    async def _build_dto(
        self, delivery: OrdDelivery, push_round: int, route: WmsRoute
    ) -> dict[str, Any]:
        """指令组装（FR-01b / §5.1）"""
        items = list(
            await self.s.scalars(
                select(OrdDeliveryItem).where(
                    OrdDeliveryItem.delivery_id == delivery.id
                )
            )
        )
        details = list(
            await self.s.scalars(
                select(OrdDeliveryItemDetail).where(
                    OrdDeliveryItemDetail.delivery_id == delivery.id
                )
            )
        )
        det_by_item: dict[int, list[OrdDeliveryItemDetail]] = {}
        for d in details:
            det_by_item.setdefault(int(d.delivery_item_id), []).append(d)

        # 物料外部编码映射（缺失 → FATAL，§5.1）
        lines: list[dict[str, Any]] = []
        for it in items:
            bm_row = await self.s.execute(
                text(
                    "SELECT material_bn, kingdee_material_code FROM oms_stock.inv_material "
                    "WHERE id = :bid AND is_deleted = 0"
                ),
                {"bid": it.bm_id},
            )
            bm = bm_row.mappings().first()
            sku_code = str(bm["material_bn"] or "") if bm else ""
            if not sku_code and bm:
                sku_code = str(bm["kingdee_material_code"] or "")
            if not sku_code:
                return {"cmd_no": "", "lines": []}
            lines.append(
                {
                    "sku_code": sku_code,
                    "num": int(it.num or 0),
                    "owner_id": int(it.owner_id or 0),
                    "detail_ids": [int(d.id) for d in det_by_item.get(int(it.id), [])],
                }
            )

        cmd_no = f"{delivery.delivery_bn}-R{push_round}"
        return {
            "cmd_no": cmd_no,
            "delivery_id": delivery.id,
            "delivery_bn": delivery.delivery_bn,
            "owner_code": route.wms_owner_code,
            "waybill_no": delivery.logi_no or "",
            "print_ref": "",
            "lines": lines,
            "remark": delivery.memo or "",
        }

    async def _save_cmd(
        self,
        *,
        delivery: OrdDelivery,
        route: WmsRoute,
        cmd_bn: str,
        cmd_no: str,
        push_round: int,
        dto: dict[str, Any],
        idem_key: str,
    ) -> int:
        """指令记录落库（FR-01a）"""
        await self.s.execute(
            text(
                "INSERT INTO oms_fulfill.ful_outbound_cmd "
                "(tenant_id, owner_id, branch_id, cmd_bn, delivery_id, delivery_bn, "
                " push_round, wms_id, binding_id, adapter_code, wms_bill_no, cmd_type, "
                " status, waybill_no, print_ref, payload_oss_ref, diff_flag, fail_reason, "
                " idempotent_key, source, create_time, update_time, version) "
                "VALUES (1, :owner, :branch, :cmd_bn, :did, :d_bn, :round, :wms_id, "
                " :binding_id, :adapter, NULL, 'push', 'accepted', :waybill, '', NULL, "
                " 0, NULL, :idem, 'local', NOW(3), NOW(3), 0)"
            ),
            {
                "owner": delivery.owner_id,
                "branch": delivery.branch_id,
                "cmd_bn": cmd_bn,
                "did": delivery.id,
                "d_bn": delivery.delivery_bn,
                "round": push_round,
                "wms_id": route.wms_id,
                "binding_id": route.binding_id,
                "adapter": route.adapter_code,
                "waybill": delivery.logi_no or "",
                "idem": idem_key,
            },
        )
        await self.s.commit()
        r = await self.s.execute(
            text(
                "SELECT id FROM oms_fulfill.ful_outbound_cmd "
                "WHERE idempotent_key = :k LIMIT 1"
            ),
            {"k": idem_key},
        )
        return int(r.scalar() or 0)

    async def _mark_failed(
        self, cmd_id: int, err_code: str, err_class: str, err_msg: str
    ) -> None:
        await self.s.execute(
            text(
                "UPDATE oms_fulfill.ful_outbound_cmd "
                "SET status = 'failed', fail_reason = :fc WHERE id = :id"
            ),
            {"fc": f"{err_code}:{err_msg}"[:64], "id": cmd_id},
        )
        await self.s.commit()

    async def _bump_retry(self, cmd_id: int, res: WmsCallResult) -> int:
        """累加重试次数（该指令的 waiting 失败记录数）"""
        await self.s.execute(
            text(
                "UPDATE oms_fulfill.ful_outbound_cmd SET status = 'failed' WHERE id = :id"
            ),
            {"id": cmd_id},
        )
        await self.s.commit()
        r = await self.s.execute(
            text(
                "SELECT COUNT(*) FROM oms_fulfill.ful_cmd_fail "
                "WHERE cmd_bn = (SELECT cmd_bn FROM oms_fulfill.ful_outbound_cmd "
                "               WHERE id = :id) AND status = 'waiting'"
            ),
            {"id": cmd_id},
        )
        n = int(r.scalar() or 0) + 1
        return n

    async def _register_fail(
        self,
        cmd_id: int,
        cmd_bn: str,
        res: WmsCallResult,
        retry_times: int,
        next_retry: datetime,
    ) -> None:
        """失败登记（ful_cmd_fail：重试台账）"""
        await self.s.execute(
            text(
                "INSERT INTO oms_fulfill.ful_cmd_fail "
                "(tenant_id, owner_id, cmd_type, cmd_id, cmd_bn, wms_id, binding_id, "
                " err_class, err_code, err_msg, retry_times, next_retry_time, status, "
                " create_time, update_time, version) "
                "VALUES (1, NULL, 'push', :id, :bn, 0, NULL, :cls, :code, :msg, "
                " :rt, :nxt, 'waiting', NOW(3), NOW(3), 0)"
            ),
            {
                "id": cmd_id,
                "bn": cmd_bn,
                "cls": res.err_class or ERR_RETRYABLE,
                "code": res.err_code,
                "msg": (res.err_msg or "")[:512],
                "rt": retry_times,
                "nxt": next_retry,
            },
        )
        await self.s.commit()

    async def _log_channel(
        self,
        *,
        cmd_id: int,
        cmd_bn: str,
        wms_id: int,
        action: str,
        payload: dict[str, Any],
        res: WmsCallResult,
    ) -> None:
        """通道日志（FR-07a：报文留痕）"""
        await self.s.execute(
            text(
                "INSERT INTO oms_fulfill.ful_channel_log "
                "(tenant_id, cmd_id, cmd_bn, wms_id, direction, action, payload_ref, "
                " err_class, err_code, spendtime_ms, retry_times, create_time) "
                "VALUES (1, :id, :bn, :wms_id, 1, :act, :pref, :cls, :code, :spend, 0, NOW(3))"
            ),
            {
                "id": cmd_id,
                "bn": cmd_bn,
                "wms_id": wms_id,
                "act": action,
                "pref": json.dumps(payload, ensure_ascii=False)[:250],
                "cls": res.err_class or None,
                "code": res.err_code or None,
                "spend": res.spend_ms,
            },
        )
        await self.s.commit()

    # ==================== 叫回与恢复（FR-04）====================

    async def recall(
        self,
        delivery_id: int,
        ref_id: str = "",
        operator: str = "system",
        reason: str = "",
    ) -> CmdOutcome:
        """叫回指令（FR-04a：取消报文下发）"""
        delivery = await self.s.scalar(
            select(OrdDelivery).where(
                OrdDelivery.id == delivery_id, OrdDelivery.is_deleted == 0
            )
        )
        if not delivery:
            raise NotFoundError(f"发货单不存在: {delivery_id}")
        try:
            route = await self.router.route(delivery.branch_id, delivery.owner_id, "OUT")
        except NotFoundError as e:
            return CmdOutcome(
                ok=False,
                err_code="wms.no-binding",
                err_class=ERR_FATAL,
                err_msg=str(e),
            )
        # 能力前置（FR-04c：WMS 不支持叫回 → 结构化失败，不空发报文）
        cap = route.capability or {}
        if cap.get("support_recall") is False:
            return CmdOutcome(
                ok=False,
                err_code="wms.capability-unsupported",
                err_class=ERR_BIZ_REJECT,
                err_msg="该 WMS 绑定不支持叫回",
            )
        adapter = get_adapter(route.adapter_code)
        if adapter is None:
            return CmdOutcome(
                ok=False,
                err_code="wms.unknown-error",
                err_class=ERR_FATAL,
                err_msg=f"未注册的适配器: {route.adapter_code}",
            )
        # 叫回引用原 push 指令单号（WMS 侧按原单拦截）
        cmd_no = f"{delivery.delivery_bn}-R1"
        payload = {
            "cmd_no": cmd_no,
            "delivery_bn": delivery.delivery_bn,
            "ref_id": ref_id,
            "operator": operator,
            "reason": reason,
        }
        res = await adapter.outbound_cancel(route, payload)
        await self._log_channel(
            cmd_id=0,
            cmd_bn=cmd_no,
            wms_id=route.wms_id,
            action="outbound_cancel",
            payload=payload,
            res=res,
        )
        if res.succ:
            return CmdOutcome(
                ok=True, cmd_no=cmd_no, status=CMD_CANCELLED, accepted=True
            )
        return CmdOutcome(
            ok=False,
            cmd_no=cmd_no,
            err_code=res.err_code,
            err_class=res.err_class or ERR_RETRYABLE,
            err_msg=res.err_msg,
        )

    async def resume(self, delivery_id: int) -> list[CmdOutcome]:
        """恢复指令（FR-04b：重推通道，新轮次）"""
        return await self.push([delivery_id], push_round=2)

    # ==================== 回传接收（FR-03）====================

    async def receive_callback(
        self, body: dict[str, Any]
    ) -> CallbackOutcome:
        """回传接收与标准化（FR-03a~FR-03f）

        五步：① 解析标准化 → ② 幂等校验 → ③ 指令记录匹配回填 →
        ④ 出库单据回传登记 → ⑤ 应答回执（发布事件异步）
        """
        cb_type = str(body.get("cb_type", "") or "")
        cmd_no = str(body.get("cmd_no", "") or "")
        batch_no = str(body.get("batch_no", "") or cb_type)
        delivery_bn = str(body.get("delivery_bn", "") or "")

        # ③ 匹配指令记录
        cmd_id = 0
        delivery_id = 0
        if cmd_no:
            r = await self.s.execute(
                text(
                    "SELECT id, delivery_id, delivery_bn FROM oms_fulfill.ful_outbound_cmd "
                    "WHERE delivery_bn = :dbn ORDER BY push_round DESC LIMIT 1"
                ),
                {"dbn": delivery_bn or _delivery_bn_of(cmd_no)},
            )
            row = r.mappings().first()
            if row:
                cmd_id = int(row["id"])
                delivery_id = int(row["delivery_id"])
                delivery_bn = str(row["delivery_bn"])
        if not delivery_bn and cmd_no:
            delivery_bn = _delivery_bn_of(cmd_no)

        # ② 幂等校验（单据号 + 批次号 + 类型）
        idem_key = f"{delivery_bn}:{batch_no}:{cb_type}"
        exist = await self.s.scalar(
            text(
                "SELECT id FROM oms_fulfill.ful_outbound_callback "
                "WHERE idempotent_key = :k LIMIT 1"
            ),
            {"k": idem_key},
        )
        if exist is not None:
            return CallbackOutcome(
                ok=True,
                duplicated=True,
                delivery_id=delivery_id,
                batch_no=batch_no,
                cb_type=cb_type,
            )

        # ④ 回传登记（先做标准化：物料编码 → bm_id，见 FR-03a「解析标准化」）
        std_lines = await self._standardize_lines(body.get("lines") or [])
        lines_json = json.dumps(std_lines, ensure_ascii=False)
        packages_json = json.dumps(body.get("packages") or [], ensure_ascii=False)
        await self.s.execute(
            text(
                "INSERT INTO oms_fulfill.ful_outbound_callback "
                "(tenant_id, owner_id, cmd_id, delivery_id, wms_batch_no, idempotent_key, "
                " callback_type, lines_json, packages_json, reject_reason, process_status, "
                " raw_payload_ref, receive_time, ack_time, create_time, update_time, version) "
                "VALUES (1, NULL, :cmd_id, :did, :batch, :idem, :ctype, :lines, :pkgs, "
                " :reason, 'registered', NULL, NOW(3), NOW(3), NOW(3), NOW(3), 0)"
            ),
            {
                "cmd_id": cmd_id or None,
                "did": delivery_id or None,
                "batch": batch_no,
                "idem": idem_key,
                "ctype": cb_type,
                "lines": lines_json,
                "pkgs": packages_json,
                "reason": str(body.get("reject_reason", "") or "")[:64] or None,
            },
        )
        await self.s.commit()

        # 指令状态联动（§4.2 通道侧投影）
        if cmd_id:
            status_map = {
                CB_ACCEPTED: CMD_WORKING,
                CB_REJECTED: CMD_REJECTED,
                CB_CANCELLED: CMD_CANCELLED,
            }
            new_status = status_map.get(cb_type)
            if cb_type == CB_OUTBOUND:
                # §4.2：一次性回传 → 回传闭环；批次 1..n-1 → 部分回传
                # 判定口径 = 累计回传量 vs 指令量（齐套 → 闭环）
                new_status = await self._outbound_cmd_status(cmd_id, delivery_id)
            if new_status:
                await self.s.execute(
                    text(
                        "UPDATE oms_fulfill.ful_outbound_cmd SET status = :st WHERE id = :id"
                    ),
                    {"st": new_status, "id": cmd_id},
                )
                await self.s.commit()

        # ⑤ 发布标准化事件（FR-03e）
        event_map = {
            CB_ACCEPTED: EVENT_ACCEPTED,
            CB_OUTBOUND: EVENT_CALLBACK,
            CB_REJECTED: EVENT_REJECTED,
            CB_CANCELLED: EVENT_RECALL_SUCC,
            CB_RECALL_FAILED: EVENT_RECALL_FAILED,
        }
        event = event_map.get(cb_type, EVENT_CALLBACK)
        payload = {
            "cmd_id": cmd_id,
            "delivery_id": delivery_id,
            "delivery_bn": delivery_bn,
            "batch_no": batch_no,
            "cb_type": cb_type,
            "lines": std_lines,
            "packages": body.get("packages") or [],
            "weight": body.get("weight", 0),
            "volume": body.get("volume", 0),
            "waybill_no": body.get("waybill_no", ""),
            "reject_reason": body.get("reject_reason", ""),
            "reject_reason_code": body.get("reject_reason_code", ""),
        }
        await self._publish(event, payload)
        return CallbackOutcome(
            ok=True,
            duplicated=False,
            delivery_id=delivery_id,
            batch_no=batch_no,
            cb_type=cb_type,
            event=event,
            detail=payload,
        )

    # ==================== 单据反查（FR-03f）====================

    async def query_order(self, cmd_no: str) -> dict[str, Any]:
        """适配器反查（回传超时兜底 / 对账）"""
        # 指令单号 → 发货单号（cmd_bn = CMD{delivery_bn}-{round}）
        delivery_bn = _delivery_bn_of(cmd_no)
        r = await self.s.execute(
            text(
                "SELECT branch_id, owner_id, adapter_code, binding_id, wms_id "
                "FROM oms_fulfill.ful_outbound_cmd "
                "WHERE delivery_bn = :dbn ORDER BY push_round DESC LIMIT 1"
            ),
            {"dbn": delivery_bn},
        )
        row = r.mappings().first()
        if not row:
            raise NotFoundError(f"指令记录不存在: {cmd_no}")
        route = await self.router.route(
            int(row["branch_id"]), int(row["owner_id"] or 0), "OUT"
        )
        adapter = get_adapter(route.adapter_code)
        if adapter is None:
            return {"found": False, "err": "adapter-not-registered"}
        res = await adapter.query_order(route, cmd_no)
        return {
            "found": res.succ,
            "raw": res.raw,
            "err_code": res.err_code,
            "err_msg": res.err_msg,
        }

    async def _standardize_lines(
        self, lines: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """回传明细标准化（FR-03a：解析标准化）

        WMS 侧用**物料编码**（sku_code / material_code）回传，OMS 侧发货单行用
        **bm_id** —— 通道层在此做编码 → bm_id 的映射，编排层只认 bm_id。
        映射缺失的行保留原编码（由 D03.07 登记差异人工处理）。
        """
        if not lines:
            return []
        codes = [
            str(ln.get("sku_code", "") or ln.get("material_code", "") or "")
            for ln in lines
        ]
        codes = [c for c in codes if c]
        mapping: dict[str, int] = {}
        if codes:
            r = await self.s.execute(
                text(
                    "SELECT material_bn, id FROM oms_stock.inv_material "
                    "WHERE is_deleted = 0 AND material_bn IN :codes"
                ),
                {"codes": codes},
            )
            for row in r.all():
                mapping[str(row[0])] = int(row[1])
        out: list[dict[str, Any]] = []
        for ln in lines:
            code = str(ln.get("sku_code", "") or ln.get("material_code", "") or "")
            bm_id = int(ln.get("bm_id", 0) or 0) or mapping.get(code, 0)
            item = dict(ln)
            item["bm_id"] = bm_id
            item["sku_code"] = code
            out.append(item)
        return out

    async def _outbound_cmd_status(self, cmd_id: int, delivery_id: int) -> str:
        """出库回传后的通道侧指令状态（§4.2 投影）

        - 累计回传量 ≥ 指令量 → 回传闭环（completed）
        - 否则 → 部分回传（partial），等尾批

        指令量取发货单行的 Σnum；累计回传量取该发货单已登记的全部出库回传
        的 Σ实发量（含本批次——本批次已落库）。
        """
        if not delivery_id:
            return CMD_PARTIAL
        instruct = await self.s.scalar(
            text(
                "SELECT COALESCE(SUM(num), 0) FROM oms_order.ord_delivery_item "
                "WHERE delivery_id = :did AND is_deleted = 0"
            ),
            {"did": delivery_id},
        )
        total_instruct = int(instruct or 0)
        if total_instruct <= 0:
            return CMD_PARTIAL
        # 累计已登记的出库回传实发量
        rows = await self.s.execute(
            text(
                "SELECT lines_json FROM oms_fulfill.ful_outbound_callback "
                "WHERE delivery_id = :did AND callback_type = :ct"
            ),
            {"did": delivery_id, "ct": CB_OUTBOUND},
        )
        total_actual = 0
        for (lj,) in rows.all():
            try:
                arr = json.loads(lj) if isinstance(lj, str) else (lj or [])
            except (TypeError, ValueError):
                arr = []
            for ln in arr if isinstance(arr, list) else []:
                total_actual += int(ln.get("num", 0) or 0)
        return CMD_COMPLETED if total_actual >= total_instruct else CMD_PARTIAL

    # ==================== 事件发布（FR-03e）====================

    async def _publish(self, event: str, payload: dict[str, Any]) -> None:
        """发布标准化事件（FR-03e）

        落 outbox（本地事务表）→ 由 `WmsEventDispatcher.dispatch_pending` 消费编排。
        outbox 不可用时降级为本地直调（不阻断主流程）。
        """
        try:
            await self.s.execute(
                text(
                    "INSERT INTO oms_base.bas_event_outbox "
                    "(tenant_id, event_id, event_name, reliability, idempotent_key, "
                    " aggregate_type, aggregate_id, owner_id, trace_id, partition_key, "
                    " payload, schema_version, delay_seconds, status, retry_count, "
                    " next_retry_time, publish_time, create_time, update_time, version) "
                    "VALUES (1, :eid, :code, 'reliable', :idem, 'delivery', :aid, 0, '', "
                    " :pkey, :payload, 'v1', 0, 0, 0, NULL, NULL, NOW(3), NOW(3), 0)"
                ),
                {
                    "eid": uuid4().hex[:26],
                    "code": event,
                    "idem": (
                        f"{event}:"
                        f"{payload.get('delivery_id') or payload.get('cmd_id')}:"
                        f"{payload.get('batch_no', '')}"
                    ),
                    "aid": str(payload.get("delivery_id") or payload.get("cmd_id") or ""),
                    "pkey": str(payload.get("delivery_id") or ""),
                    "payload": json.dumps(payload, ensure_ascii=False, default=str),
                },
            )
            await self.s.commit()
        except Exception as e:  # 事件表不可用不阻断主流程
            logger.warning("事件入 outbox 失败（降级为本地直调）: %s event=%s", e, event)
            await self.s.rollback()
            await self._dispatch_local(event, payload)

    async def _dispatch_local(self, event: str, payload: dict[str, Any]) -> None:
        """本地直调分发（outbox 不可用时的降级路径）"""
        try:
            from app.modules.m7_integration.service.wms_events import WmsEventDispatcher

            await WmsEventDispatcher(self.s, self.r).dispatch(event, payload)
        except Exception as e:
            logger.warning("本地事件分发失败: %s event=%s", e, event)


def _delivery_bn_of(cmd_no: str) -> str:
    """从下发单号解析发货单号（DLV...-R1 → DLV...）"""
    if "-R" in cmd_no:
        return cmd_no.rsplit("-R", 1)[0]
    if "-C" in cmd_no:
        return cmd_no.rsplit("-C", 1)[0]
    return cmd_no
