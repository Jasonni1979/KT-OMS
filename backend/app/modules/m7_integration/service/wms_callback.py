"""WmsCallbackMixin —— 由 OutboundCommandService 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.wms import (
    get_adapter,
)
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.fulfill import (
    OrdDelivery,
)
from app.modules.m7_integration.service.wms_codes import (
    CB_ACCEPTED,
    CB_CANCELLED,
    CB_OUTBOUND,
    CB_RECALL_FAILED,
    CB_REJECTED,
    CMD_CANCELLED,
    CMD_COMPLETED,
    CMD_PARTIAL,
    CMD_REJECTED,
    CMD_WORKING,
    ERR_BIZ_REJECT,
    ERR_FATAL,
    ERR_RETRYABLE,
    EVENT_ACCEPTED,
    EVENT_CALLBACK,
    EVENT_RECALL_FAILED,
    EVENT_RECALL_SUCC,
    EVENT_REJECTED,
    CallbackOutcome,
    CmdOutcome,
    _delivery_bn_of,  # noqa: F401
)
from app.modules.m7_integration.service.wms_route import (
    WmsRouteService,
)

logger = get_logger("wms_channel")


class WmsCallbackMixin:
    """OutboundCommandService 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Redis
    router: WmsRouteService

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