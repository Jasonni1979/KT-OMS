"""DeliveryCallbackMixin —— 由 DeliveryService 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
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
from app.models.order import OrdOrder, OrdOrderItem
from app.modules.m4_fulfill.service.delivery_states import (
    CMD_CB_OUT,
    ST_OUTBOUND,
    ST_PARTIAL_OUTBOUND,
    DeliveryOutcome,
    _FallbackCmdResult,  # noqa: F401
    )

logger = get_logger("delivery")


class DeliveryCallbackMixin:
    """DeliveryService 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Redis

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

    async def _get(self, delivery_id: int) -> OrdDelivery | None:
        return await self.s.scalar(
            select(OrdDelivery).where(
                OrdDelivery.id == delivery_id, OrdDelivery.is_deleted == 0
            )
        )