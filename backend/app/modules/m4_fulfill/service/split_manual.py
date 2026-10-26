"""SplitManualMixin —— 由 SplitService 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.models.fulfill import OrdSplitRule, OrdSplitTrace
from app.models.order import OrdOrder, OrdOrderItem
from app.modules.m4_fulfill.service.split_models import (
    FAIL_CONFIG_INVALID,
    FAIL_NO_ITEMS,
    SplitGroup,
    SplitItem,
    SplitOutcome,
    SplitResult,
)
from app.modules.m4_fulfill.service.split_strategies import (
    SplitStrategyRegistry,
)

logger = get_logger("split")


class SplitManualMixin:
    """SplitService 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Redis
    registry: SplitStrategyRegistry

    async def _trace_success(
        self,
        order_id: int,
        rule: OrdSplitRule,
        items: list[SplitItem],
        ctx: dict[str, Any],
        result: SplitResult,
        source: str,
        operator: str,
        started: datetime,
    ) -> SplitOutcome:
        cost = int((datetime.now() - started).total_seconds() * 1000)
        round_no = await self._next_round(order_id)
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id).limit(1)
        )
        trace = OrdSplitTrace(
            owner_id=int(order.owner_id or 0) if order else 0,
            order_id=order_id,
            round_no=round_no,
            split_rule_id=rule.id,
            rule_snapshot={
                "rule_name": rule.rule_name,
                "split_type": rule.split_type,
                "split_config": rule.split_config,
                "split_type_2": rule.split_type_2,
                "split_config_2": rule.split_config_2,
                "split_type_3": rule.split_type_3,
                "split_config_3": rule.split_config_3,
            },
            input_snapshot={"items": [i.to_dict() for i in items]},
            group_result={"groups": [g.to_dict() for g in result.groups]},
            source=source,
            result_status="success",
            cost_ms=cost,
            operator=operator,
            shop_id=int(order.shop_id or 0) if order else 0,
        )
        self.s.add(trace)
        await self.s.commit()
        await self.s.refresh(trace)
        return SplitOutcome(
            ok=True,
            groups=[g.to_dict() for g in result.groups],
            trace_id=trace.id,
            round_no=round_no,
            cost_ms=cost,
        )

    async def _trace_fail(
        self,
        order_id: int,
        rule: OrdSplitRule,
        items: list[SplitItem],
        ctx: dict[str, Any],
        source: str,
        operator: str,
        started: datetime,
        code: str,
        detail: dict[str, Any],
    ) -> SplitOutcome:
        cost = int((datetime.now() - started).total_seconds() * 1000)
        round_no = await self._next_round(order_id)
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id).limit(1)
        )
        trace = OrdSplitTrace(
            owner_id=int(order.owner_id or 0) if order else 0,
            order_id=order_id,
            round_no=round_no,
            split_rule_id=rule.id,
            rule_snapshot={"split_type": rule.split_type},
            input_snapshot={"items": [i.to_dict() for i in items]},
            group_result={"groups": []},
            source=source,
            result_status="failed",
            err_code=code,
            err_detail=detail,
            cost_ms=cost,
            operator=operator,
            shop_id=int(order.shop_id or 0) if order else 0,
        )
        self.s.add(trace)
        await self.s.commit()
        await self.s.refresh(trace)
        return SplitOutcome(
            ok=False,
            fail_code=code,
            fail_detail=detail,
            trace_id=trace.id,
            round_no=round_no,
            cost_ms=cost,
        )

    async def _next_round(self, order_id: int) -> int:
        rows = await self.s.execute(
            text(
                "SELECT COALESCE(MAX(round_no), 0) FROM oms_order.ord_split_trace "
                "WHERE order_id = :oid"
            ),
            {"oid": order_id},
        )
        return int(rows.scalar() or 0) + 1

    async def manual_split(
        self,
        order_id: int,
        groups: list[dict[str, Any]],
        operator: str,
    ) -> SplitOutcome:
        """手工拆单（FR-07：人工审单工作台入口）

        校验（FR-07c）：各组数量之和 ≤ 行未拆余量；组内货主唯一；
        走同一引擎落库通道（source=manual，操作人=真实账号）。
        """
        started = datetime.now()
        items = await self._load_items(order_id)
        if not items:
            return SplitOutcome(ok=False, fail_code=FAIL_NO_ITEMS)
        by_id = {it.item_id: it for it in items}

        # 各组数量之和 ≤ 未拆余量
        per_item: dict[int, int] = {}
        parsed: list[SplitGroup] = []
        for g in groups:
            lines = g.get("items") or g.get("lines") or []
            attrs = dict(g.get("attrs") or {})
            sg = SplitGroup(
                group_key=str(g.get("group_key") or f"MANUAL_{len(parsed) + 1}"),
                attrs=attrs,
            )
            owners: set[int] = set()
            for ln in lines:
                item_id = int(ln.get("item_id", 0) or 0)
                nums = int(ln.get("nums", 0) or 0)
                if item_id not in by_id:
                    return SplitOutcome(
                        ok=False,
                        fail_code=FAIL_CONFIG_INVALID,
                        fail_detail={"reason": f"明细行不存在: {item_id}"},
                    )
                if nums <= 0:
                    return SplitOutcome(
                        ok=False,
                        fail_code=FAIL_CONFIG_INVALID,
                        fail_detail={"reason": "分配数量必须为正"},
                    )
                owners.add(by_id[item_id].owner_id)
                per_item[item_id] = per_item.get(item_id, 0) + nums
                sg.add(item_id, nums)
            if len(owners) > 1:
                return SplitOutcome(
                    ok=False,
                    fail_code=FAIL_CONFIG_INVALID,
                    fail_detail={
                        "reason": "组内货主不唯一（手工拆单不豁免）",
                        "group_key": sg.group_key,
                        "owners": sorted(owners),
                    },
                )
            parsed.append(sg)

        for it in items:
            got = per_item.get(it.item_id, 0)
            if got > it.nums:
                return SplitOutcome(
                    ok=False,
                    fail_code=FAIL_CONFIG_INVALID,
                    fail_detail={
                        "reason": "各组数量之和超过行未拆余量",
                        "item_id": it.item_id,
                        "remain": it.nums,
                        "submitted": got,
                    },
                )
        # 部分拆分允许（未分配余量留给续拆）→ 守恒校验用「≤」口径
        result = SplitResult(groups=parsed)
        # 写 trace（source=manual）
        rule = await self.s.scalar(
            select(OrdSplitRule).where(OrdSplitRule.is_deleted == 0).limit(1)
        )
        if rule is None:
            # 无规则时用占位规则记录手工拆单轨迹
            cost = int((datetime.now() - started).total_seconds() * 1000)
            order = await self.s.scalar(
                select(OrdOrder).where(OrdOrder.id == order_id).limit(1)
            )
            round_no = await self._next_round(order_id)
            trace = OrdSplitTrace(
                owner_id=int(order.owner_id or 0) if order else 0,
                order_id=order_id,
                round_no=round_no,
                split_rule_id=0,
                rule_snapshot={"source": "manual"},
                input_snapshot={"items": [i.to_dict() for i in items]},
                group_result={"groups": [g.to_dict() for g in parsed]},
                source="manual",
                result_status="success",
                cost_ms=cost,
                operator=operator,
                shop_id=int(order.shop_id or 0) if order else 0,
            )
            self.s.add(trace)
            await self.s.commit()
            await self.s.refresh(trace)
            return SplitOutcome(
                ok=True,
                groups=[g.to_dict() for g in parsed],
                trace_id=trace.id,
                round_no=round_no,
                cost_ms=cost,
            )
        return await self._trace_success(
            order_id, rule, items, {}, result, "manual", operator, started
        )

    async def write_progress(
        self, order_id: int, groups: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """回写拆单进度（FR-06a/b：split_num 累加 + splited_num +1）"""
        rows = await self.s.execute(
            select(OrdOrderItem).where(
                OrdOrderItem.order_id == order_id,
                OrdOrderItem.is_deleted == 0,
            )
        )
        items = {int(r.id): r for r in rows.scalars().all()}
        for g in groups:
            for ln in g.get("items", []):
                item_id = int(ln.get("item_id", 0) or 0)
                nums = int(ln.get("nums", 0) or 0)
                it = items.get(item_id)
                if not it:
                    continue
                new_split = int(it.split_num or 0) + nums
                if new_split > int(it.nums or 0):
                    raise ValidationError(
                        f"split_num 超过行数量（行{item_id}: {new_split} > {it.nums}）"
                    )
                it.split_num = new_split
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id).limit(1)
        )
        if order:
            order.splited_num = int(order.splited_num or 0) + 1
        await self.s.commit()
        return {
            "splited_num": int(order.splited_num or 0) if order else 0,
            "split_num_map": {
                str(i.id): int(i.split_num or 0) for i in items.values()
            },
        }

    async def rollback_progress(
        self, order_id: int, delivery_id: int
    ) -> dict[str, Any]:
        """拆单进度回退（FR-06d：发货单取消/打回 → split_num 扣减）

        splited_num **不回退**（轮次历史保留）。
        """
        from app.models.fulfill import OrdDeliveryItem, OrdDeliveryItemDetail

        details = list(
            await self.s.scalars(
                select(OrdDeliveryItemDetail).where(
                    OrdDeliveryItemDetail.delivery_id == delivery_id
                )
            )
        )
        rows = await self.s.execute(
            select(OrdOrderItem).where(
                OrdOrderItem.order_id == order_id,
                OrdOrderItem.is_deleted == 0,
            )
        )
        items = {int(r.id): r for r in rows.scalars().all()}
        del OrdDeliveryItem
        for d in details:
            it = items.get(int(d.order_item_id))
            if not it:
                continue
            it.split_num = max(0, int(it.split_num or 0) - int(d.split_qty or 0))
        await self.s.commit()
        return {
            "rolled_back": len(details),
            "split_num_map": {str(i): int(v.split_num or 0) for i, v in items.items()},
        }

    async def query_trace(self, order_id: int) -> list[dict[str, Any]]:
        """拆单历史时间线（FR-08b）"""
        rows = list(
            await self.s.scalars(
                select(OrdSplitTrace)
                .where(OrdSplitTrace.order_id == order_id)
                .order_by(OrdSplitTrace.round_no)
            )
        )
        return [
            {
                "id": r.id,
                "round_no": r.round_no,
                "split_rule_id": r.split_rule_id,
                "rule_snapshot": r.rule_snapshot,
                "group_result": r.group_result,
                "source": r.source,
                "result_status": r.result_status,
                "err_code": r.err_code,
                "err_detail": r.err_detail,
                "delivery_ids": r.delivery_ids,
                "cost_ms": r.cost_ms,
                "operator": r.operator,
                "create_time": (
                    r.create_time.isoformat() if r.create_time else ""
                ),
            }
            for r in rows
        ]