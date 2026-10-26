"""DeliveryQueryMixin —— 由 DeliveryService 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.fulfill import (
    OrdDelivery,
    OrdDeliveryDiff,
    OrdDeliveryItem,
    OrdDeliveryItemDetail,
    OrdDeliveryLog,
    OrdDeliveryPackage,
)
from app.modules.m4_fulfill.service.delivery_states import (
    _FallbackCmdResult,  # noqa: F401
    allowed_commands,
)

logger = get_logger("delivery")


class DeliveryQueryMixin:
    """DeliveryService 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Redis

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
