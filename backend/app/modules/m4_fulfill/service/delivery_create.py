"""DeliveryCreateMixin —— 由 DeliveryService 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.fulfill import (
    OrdDelivery,
    OrdDeliveryItem,
    OrdDeliveryItemDetail,
    OrdDeliveryLog,
)
from app.models.order import OrdOrder, OrdOrderItem
from app.modules.m4_fulfill.service.delivery_states import (
    ST_DRAFT,
    SYNC_INIT,
    SYNC_NONE,
    _FallbackCmdResult,  # noqa: F401
    )

logger = get_logger("delivery")


class DeliveryCreateMixin:
    """DeliveryService 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Redis

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
