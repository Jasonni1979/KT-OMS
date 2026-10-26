"""WMS 事件分发（D09.02 → D03.07 编排桥接）

通道层发布标准化事件（FR-03e），本服务是**编排层的订阅者**：

| 事件 | 编排动作（D03.07 契约） |
|---|---|
| `wms.outbound.pushed` | 发货单 draft → pushed |
| `wms.outbound.push.failed` | 发货单 → push_failed（人工介入） |
| `wms.outbound.accepted` | 发货单 pushed → processing（作业开始） |
| `wms.outbound.callback` | 出库回传七步编排（行匹配→settle→差异→包裹→状态→确认→事件） |
| `wms.outbound.rejected` | 打回（split_num 回退 + 预占释放 + 订单回审单池） |
| `wms.outbound.recall.succ` | recalling → recalled |
| `wms.outbound.recall.failed` | recalling → 回原态 + 结构化原因 |

**关键约束（SRS-D09.02 §5.3）**：
- 通道层快速应答：回执不等待编排完成（异步化）；
- 编排层容错归 D03.07：settle 失败进补偿队列，不阻塞状态落库；
- 幂等：事件按 (delivery_id, batch_no, cb_type) 幂等，重复投递不重复编排。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.m4_fulfill.service.delivery_service import (
    CMD_PUSH,
    CMD_PUSH_FAILED,
    CMD_RECALL,
    CMD_RECALL_FAIL,
    DeliveryService,
)
from app.modules.m5_abnormal.service.abnormal import (
    EXC_WMS_PUSH_FAILED,
)
from app.modules.m7_integration.service.wms_channel import (
    EVENT_ACCEPTED,
    EVENT_CALLBACK,
    EVENT_PUSH_FAILED,
    EVENT_PUSHED,
    EVENT_RECALL_FAILED,
    EVENT_RECALL_SUCC,
    EVENT_REJECTED,
)

#: 平台回传事件（DB-00 附录 A 关键事件）
EVENT_ORDER_SHIPPED = "order.delivery.shipped"

logger = get_logger("wms_events")


@dataclass
class DispatchResult:
    """事件编排结果"""

    ok: bool
    event: str = ""
    delivery_id: int = 0
    action: str = ""
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "event": self.event,
            "delivery_id": self.delivery_id,
            "action": self.action,
            "message": self.message,
            "detail": self.detail,
        }


class WmsEventDispatcher:
    """WMS 标准化事件 → D03.07 编排分发"""

    def __init__(self, session: AsyncSession, redis: Redis):
        self.s = session
        self.r = redis

    async def _raise_abnormal(
        self,
        delivery_id: int,
        *,
        exc_type: str,
        source: str,
        source_ref: str = "",
        note: str = "",
    ) -> None:
        """履约链路事件落异常单（FR-03b）

        落单失败**不阻断事件编排**（事件主流程已由 DeliveryService 落库）。
        """
        from app.models.fulfill import OrdDelivery
        from app.models.order import OrdOrder
        from app.modules.m5_abnormal.service.abnormal import AbnormalService

        try:
            dlv = await self.s.scalar(
                select(OrdDelivery).where(
                    OrdDelivery.id == delivery_id, OrdDelivery.is_deleted == 0
                )
            )
            if dlv is None or not dlv.order_id:
                return
            order = await self.s.scalar(
                select(OrdOrder).where(
                    OrdOrder.id == dlv.order_id, OrdOrder.is_deleted == 0
                )
            )
            if order is None:
                return
            svc = AbnormalService(self.s, self.r)
            await svc.create(
                order=order,
                exc_type=exc_type,
                source=source,
                source_ref=source_ref,
                reason_detail={"note": note, "delivery_id": delivery_id},
            )
        except Exception as e:  # noqa: BLE001 —— 落单失败不阻断事件编排
            logger.warning(
                "abnormal_raise_failed",
                detail=str(e),
                delivery_id=delivery_id,
                exc_type=exc_type,
            )

    async def dispatch(self, event: str, payload: dict[str, Any]) -> DispatchResult:
        """按事件类型分发到编排动作"""
        delivery_id = int(payload.get("delivery_id") or 0)
        if not delivery_id and event != EVENT_ORDER_SHIPPED:
            # 无主事件（历史脏数据 / 缺 delivery_id）→ 跳过，不阻断其他事件
            logger.warning("跳过无主 WMS 事件: %s payload=%s", event, payload)
            return DispatchResult(
                ok=False, event=event, delivery_id=0,
                message="事件缺少 delivery_id（无主事件）",
            )
        svc = DeliveryService(self.s, self.r)

        if event == EVENT_ORDER_SHIPPED:
            # 平台发货回传（D02.04 消费 order.delivery.shipped）
            from app.modules.m7_integration.service.writeback import WritebackService

            wb = WritebackService(self.s, self.r)
            wb_res = await wb.on_order_shipped(payload)
            return DispatchResult(
                ok=wb_res.ok, event=event, delivery_id=delivery_id,
                action=f"platform回传→{wb_res.status}", detail=wb_res.to_dict(),
            )

        if event == EVENT_PUSHED:
            res = await svc.transit(
                delivery_id, CMD_PUSH, operator="wms", reason="WMS 已受理指令"
            )
            if res.ok and payload.get("wms_bill_no"):
                d = await svc._get(delivery_id)
                if d:
                    d.wms_bill_no = str(payload["wms_bill_no"])
                    await self.s.commit()
            return DispatchResult(
                ok=res.ok, event=event, delivery_id=delivery_id,
                action="pushed", message=res.fail_message, detail=res.to_dict(),
            )

        if event == EVENT_PUSH_FAILED:
            res = await svc.transit(
                delivery_id, CMD_PUSH_FAILED, operator="wms",
                reason=str(payload.get("err_msg", "") or "")[:200],
            )
            # FR-03b 履约链路事件落单：推仓失败 → WMS_PUSH_FAILED 异常单
            await self._raise_abnormal(
                delivery_id,
                exc_type=EXC_WMS_PUSH_FAILED,
                source="push",
                source_ref=str(payload.get("cmd_no") or "")[:128],
                note=str(payload.get("err_msg", "") or "")[:512],
            )
            return DispatchResult(
                ok=res.ok, event=event, delivery_id=delivery_id,
                action="push_failed", message=res.fail_message, detail=res.to_dict(),
            )

        if event == EVENT_ACCEPTED:
            res = await svc.transit(
                delivery_id, "callback_ack", operator="wms", reason="WMS 接收确认"
            )
            return DispatchResult(
                ok=res.ok, event=event, delivery_id=delivery_id,
                action="processing", message=res.fail_message, detail=res.to_dict(),
            )

        if event == EVENT_CALLBACK:
            # 出库回传七步编排（D03.07 FR-05c，通道层只供数）
            res = await svc.handle_callback(delivery_id, payload, operator="wms")
            return DispatchResult(
                ok=res.ok, event=event, delivery_id=delivery_id,
                action=f"outbound→{res.to_status}", detail=res.to_dict(),
            )

        if event == EVENT_REJECTED:
            res = await svc.reject(
                delivery_id,
                reason=str(payload.get("reject_reason", "") or "WMS 打回"),
                operator="wms",
            )
            # FR-03b：WMS 打回 → 履约类异常单（人工事后处理）
            await self._raise_abnormal(
                delivery_id,
                exc_type=EXC_WMS_PUSH_FAILED,
                source="push",
                source_ref=str(payload.get("cmd_no") or "")[:128],
                note=str(payload.get("reject_reason", "") or "WMS 打回")[:512],
            )
            return DispatchResult(
                ok=res.ok, event=event, delivery_id=delivery_id,
                action="rejected", message=res.fail_message, detail=res.to_dict(),
            )

        if event == EVENT_RECALL_SUCC:
            res = await svc.transit(
                delivery_id, CMD_RECALL, operator="wms", reason="WMS 拦截成功"
            )
            return DispatchResult(
                ok=res.ok, event=event, delivery_id=delivery_id,
                action="recalled", message=res.fail_message, detail=res.to_dict(),
            )

        if event == EVENT_RECALL_FAILED:
            res = await svc.transit(
                delivery_id, CMD_RECALL_FAIL, operator="wms",
                reason=str(payload.get("reject_reason", "") or "WMS 拒绝叫回")[:200],
            )
            return DispatchResult(
                ok=res.ok, event=event, delivery_id=delivery_id,
                action="recall_failed", message=res.fail_message, detail=res.to_dict(),
            )

        return DispatchResult(
            ok=False, event=event, delivery_id=delivery_id,
            message=f"未订阅的事件: {event}",
        )

    async def dispatch_pending(self, limit: int = 50) -> list[DispatchResult]:
        """扫描 outbox 未发布事件并编排（调度任务入口，D01.02 挂载）"""
        rows = await self.s.execute(
            text(
                "SELECT id, event_name, payload FROM oms_base.bas_event_outbox "
                "WHERE status = 0 AND (event_name LIKE 'wms.outbound.%' "
                "  OR event_name = 'order.delivery.shipped') "
                "ORDER BY id LIMIT :lim"
            ),
            {"lim": limit},
        )
        out: list[DispatchResult] = []
        for rid, name, payload in rows.all():
            import json

            try:
                data = json.loads(payload) if isinstance(payload, str) else (payload or {})
            except (TypeError, ValueError):
                data = {}
            try:
                res = await self.dispatch(str(name), data)
            except Exception as e:
                # 单条事件失败不阻断其他事件（FR-03d：编排失败不回滚回执）
                logger.warning("事件编排失败（跳过）: %s event=%s err=%s", rid, name, e)
                res = DispatchResult(
                    ok=False, event=str(name), message=f"编排异常: {e}"
                )
            await self.s.execute(
                text(
                    "UPDATE oms_base.bas_event_outbox SET status = 1, publish_time = NOW(3) "
                    "WHERE id = :id"
                ),
                {"id": int(rid)},
            )
            out.append(res)
        await self.s.commit()
        return out
