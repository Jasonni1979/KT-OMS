"""WmsCmdStoreMixin —— 由 OutboundCommandService 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.wms import (
    WmsCallResult,
    WmsRoute,
)
from app.core.logging import get_logger
from app.models.fulfill import (
    OrdDelivery,
    OrdDeliveryItem,
    OrdDeliveryItemDetail,
)
from app.modules.m7_integration.service.wms_codes import (
    ERR_RETRYABLE,
    _delivery_bn_of,  # noqa: F401
)
from app.modules.m7_integration.service.wms_route import (
    WmsRouteService,
)

logger = get_logger("wms_channel")


class WmsCmdStoreMixin:
    """OutboundCommandService 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Redis
    router: WmsRouteService

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