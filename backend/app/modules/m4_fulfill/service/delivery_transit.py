"""DeliveryTransitMixin —— 由 DeliveryService 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.fulfill import (
    OrdDelivery,
    OrdDeliveryItemDetail,
    OrdDeliveryLog,
)
from app.models.order import OrdOrderItem
from app.modules.m4_fulfill.service.delivery_states import (
    CMD_CANCEL,
    CMD_CONFIRM,
    CMD_FINISH,
    CMD_PUSH,
    CMD_PUSH_FAILED,
    CMD_RECALL,
    CMD_RECALL_FAIL,
    CMD_REJECT,
    CMD_RESUME,
    FINAL_STATES,
    ST_FINISHED,
    ST_OUTBOUND,
    ST_PARTIAL_OUTBOUND,
    ST_PROCESSING,
    ST_PUSHED,
    ST_RECALLING,
    ST_SHIPPED,
    SYNC_FAIL,
    SYNC_SUCC,
    DeliveryOutcome,
    _FallbackCmdResult,  # noqa: F401
    allowed_commands,
    find_transition,
)

logger = get_logger("delivery")


class DeliveryTransitMixin:
    """DeliveryService 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Redis

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
        from app.modules.m7_integration.contract import OutboundCommandService

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