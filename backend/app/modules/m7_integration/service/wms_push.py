"""WmsPushMixin —— 由 OutboundCommandService 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

from datetime import datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.wms import (
    WmsCallResult,
    get_adapter,
)
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.fulfill import (
    OrdDelivery,
)
from app.modules.m7_integration.service.wms_codes import (
    BACKOFF_MINUTES,
    CMD_SENT,
    ERR_FATAL,
    ERR_RETRYABLE,
    EVENT_PUSH_FAILED,
    EVENT_PUSHED,
    MAX_RETRY,
    CmdOutcome,
    _delivery_bn_of,  # noqa: F401
)
from app.modules.m7_integration.service.wms_route import (
    WmsRouteService,
)

logger = get_logger("wms_channel")


class WmsPushMixin:
    """OutboundCommandService 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Redis
    router: WmsRouteService

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