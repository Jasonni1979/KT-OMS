"""AbnormalProcessMixin —— 由 AbnormalService 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, ValidationError
from app.core.logging import get_logger
from app.core.timeutil import utcnow
from app.models.abnormal import (
    ABNORMAL_STATUS_ASSIGNED,
    ABNORMAL_STATUS_CANCELLED,
    ABNORMAL_STATUS_PROCESSING,
    ABNORMAL_STATUS_RESOLVED,
    ABNORMAL_STATUS_SUSPENDED,
    ABNORMAL_STATUS_WAIT_DISPATCH,
    ABNORMAL_TRANSITIONS,
    OrdAbnormal,
)
from app.models.order import OrdOrder
from app.modules.m5_abnormal.service.abnormal_codes import (
    CLOSED_STATUSES,
    EXC_OVERSOLD,
    STOCKOUT_TYPES,
)

logger = get_logger("abnormal")


class AbnormalProcessMixin:
    """AbnormalService 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Any

    async def raise_by_reason(
        self,
        *,
        order_id: int,
        reason_code: str,
        source: str,
        source_ref: str = "",
        detail: dict | None = None,
    ) -> tuple[OrdAbnormal | None, bool]:
        """按原因码落异常单 —— **唯一入口**（FR-03a 审单不通过 / FR-03b 履约链路）

        落单与否由**字典**决定（不写死在代码里）：
        ① `ord_reason_code_dict.exc_type` 为空 → **不落单**
           （普通不通过原因仍留在审单工作台，避免异常池泛滥 —— FR-03a）
        ② 映射到的类型 `need_abnormal_bill=0` → **不落单**
        ③ 否则落异常单；若是缺货类且 detail 带缺口明细 → 一并落缺货明细（FR-04a）

        返回 (异常单 or None, 是否新建)
        """
        rd = await self.reason_dict(reason_code)
        if rd is None or not rd.exc_type:
            return None, False
        tdict = await self.type_of(str(rd.exc_type))
        if tdict is None or not int(tdict.need_abnormal_bill or 0):
            return None, False
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id, OrdOrder.is_deleted == 0)
        )
        if order is None:
            return None, False

        row, created = await self.create(
            order=order,
            exc_type=str(rd.exc_type),
            source=source,
            source_ref=source_ref or reason_code,
            reason_detail={
                "reason_code": reason_code,
                "reason_name": rd.reason_name,
                "plugin": rd.plugin_name,
                "route": rd.default_route,
                "suggest": rd.default_suggest,
                "detail": detail or {},
            },
        )
        # 缺货类 → 落缺货明细（三元键 + 缺口量 + 库存快照）
        if str(rd.exc_type) in STOCKOUT_TYPES:
            shortages = (detail or {}).get("shortages") or []
            if shortages:
                items = []
                for sh in shortages:
                    items.append(
                        {
                            "branch_id": int(sh.get("branch_id") or 0),
                            "bm_id": int(sh.get("bm_id") or 0),
                            "lack_num": int(
                                sh.get("shortage")
                                or (
                                    int(sh.get("need") or 0)
                                    - int(sh.get("available") or 0)
                                )
                            ),
                            "stock_snapshot": {
                                "need": sh.get("need"),
                                "available": sh.get("available"),
                                "owner_id": sh.get("owner_id"),
                            },
                        }
                    )
                await self.mark_stockout(
                    row, items, oversold=(str(rd.exc_type) == EXC_OVERSOLD)
                )
        return row, created

    async def transit(
        self,
        abnormal_id: int,
        to_status: str,
        *,
        operator: str = "system",
        note: str = "",
        action: str = "",
    ) -> OrdAbnormal:
        """状态流转（校验合法性，非法流转抛 409）"""
        row = await self.get(abnormal_id)
        from_status = row.status
        allowed = ABNORMAL_TRANSITIONS.get(from_status, ())
        if to_status not in allowed:
            raise ConflictError(
                f"异常单状态不可从 {from_status} 流转到 {to_status}"
                f"（允许: {', '.join(allowed) or '无'}）",
                code="ABNORMAL_STATUS_INVALID",
            )
        row.status = to_status
        if action:
            row.resolve_action = action
        await self._append_timeline(
            row,
            operator=operator,
            action=action or "transit",
            note=note,
            from_status=from_status,
            to_status=to_status,
        )
        await self.s.commit()
        await self.s.refresh(row)
        return row

    async def dispatch(
        self,
        abnormal_id: int,
        *,
        group_id: int,
        op_id: int = 0,
        operator: str = "system",
        note: str = "",
    ) -> OrdAbnormal:
        """分派到处理组/处理人（自动分派与手动改派同一入口）"""
        row = await self.get(abnormal_id)
        if row.status != ABNORMAL_STATUS_WAIT_DISPATCH:
            raise ConflictError(
                f"仅「待分派」可分派，当前状态 {row.status}",
                code="ABNORMAL_STATUS_INVALID",
            )
        row.group_id = group_id
        row.op_id = op_id
        row.dispatch_time = utcnow()
        await self._append_timeline(
            row,
            operator=operator,
            action="dispatch",
            note=note or f"处理组={group_id} 处理人={op_id}",
            from_status=ABNORMAL_STATUS_WAIT_DISPATCH,
            to_status=ABNORMAL_STATUS_ASSIGNED,
        )
        row.status = ABNORMAL_STATUS_ASSIGNED
        await self.s.commit()
        await self.s.refresh(row)
        return row

    async def start_processing(
        self, abnormal_id: int, *, operator: str = "system", note: str = ""
    ) -> OrdAbnormal:
        return await self.transit(
            abnormal_id,
            ABNORMAL_STATUS_PROCESSING,
            operator=operator,
            note=note or "开始处理",
        )

    async def suspend(
        self,
        abnormal_id: int,
        *,
        until_hours: int,
        operator: str = "system",
        note: str = "",
    ) -> OrdAbnormal:
        """挂起（等货 / 等买家回复）—— 必须填预计恢复时间（FR-02d）"""
        if until_hours <= 0:
            raise ValidationError("挂起必须填写预计恢复时间（小时数 > 0）")
        row = await self.get(abnormal_id)
        row.suspend_until = utcnow() + timedelta(hours=until_hours)
        return await self.transit(
            abnormal_id,
            ABNORMAL_STATUS_SUSPENDED,
            operator=operator,
            note=note or f"挂起 {until_hours}h",
            action="suspend",
        )

    async def resolve(
        self,
        abnormal_id: int,
        *,
        action: str = "re_audit",
        operator: str = "system",
        note: str = "",
        retrial_id: int = 0,
        delivery_ids: list[int] | None = None,
    ) -> OrdAbnormal:
        """解决异常单（FR-02d 动作 + FR-02e 闭环联动）"""
        row = await self.get(abnormal_id)
        if row.status in CLOSED_STATUSES:
            raise ConflictError(
                f"异常单已闭环（{row.status}）", code="ABNORMAL_ALREADY_CLOSED"
            )
        if retrial_id:
            row.rel_retrial_id = retrial_id
        if delivery_ids is not None:
            row.rel_delivery_ids = delivery_ids
        # 落解决动作（FR-02d：动作集里的具体动作，用于事后追溯）
        if action:
            row.resolve_action = str(action)[:16]
        await self.transit(
            abnormal_id,
            ABNORMAL_STATUS_RESOLVED,
            operator=operator,
            note=note or f"解决动作={action}",
            action=action,
        )
        # FR-02e 闭环联动：解除订单异常标记
        await self.release_order_marks(row, operator=operator)
        row = await self.get(abnormal_id)
        return row

    async def cancel(
        self, abnormal_id: int, *, operator: str = "system", note: str = ""
    ) -> OrdAbnormal:
        """取消异常单（订单取消收口，FR-02b）"""
        row = await self.get(abnormal_id)
        await self.transit(
            abnormal_id,
            ABNORMAL_STATUS_CANCELLED,
            operator=operator,
            note=note or "取消",
            action="cancel",
        )
        await self.release_order_marks(row, operator=operator)
        return await self.get(abnormal_id)
