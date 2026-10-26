"""AbnormalExtListMixin —— 由 AbnormalExtService 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.timeutil import utcnow
from app.models.abnormal import OrdAbnormal
from app.models.abnormal_ext import (
    OrdPauseCommandLog,
    OrdRiskList,
)
from app.models.order import OrdOrder
from app.modules.m5_abnormal.service.abnormal_ext_codes import (
    DIM_ACCOUNT,
    DIM_ADDRESS,
    DIM_MOBILE,
    DIM_NAME,
    LIST_BLACK,
    LIST_GRAY,
    LIST_TYPE_LABEL,
    LIST_WHITE,
    SCOPE_GLOBAL,
    SCOPE_OWNER,
    SCOPE_TENANT,
    VALUE_PLAIN,
)


class AbnormalExtListMixin:
    """AbnormalExtService 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Any

    async def pause_order(
        self,
        order_id: int,
        *,
        reason: str,
        abnormal_id: int | None = None,
        operator: str = "system",
    ) -> dict[str, Any]:
        """订单暂停编排（FR-06a/06b：逐发货单处理）

        FR-06b 是**分布式动作**：逐发货单处理，任一失败按整体失败处理。
        本期按「订单置暂停 + 逐发货单记命令日志」实现（WMS 侧暂停报文
        属 D03.07/D09.02 范围，标记 pending 不伪造成功）。
        """
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id, OrdOrder.is_deleted == 0)
        )
        if order is None:
            raise NotFoundError(f"订单不存在: {order_id}")
        if order.fulfill_status == "aftersale":
            raise ConflictError(
                "订单处于售后中，暂停语义重叠，请先处理售后",
                code="ORDER_PAUSE_CONFLICT",
            )
        from app.models.fulfill import OrdDelivery

        deliveries = list(
            await self.s.scalars(
                select(OrdDelivery).where(
                    OrdDelivery.order_id == order_id, OrdDelivery.is_deleted == 0
                )
            )
        )
        # 订单置暂停
        order.fulfill_status = "paused"
        order.update_time = utcnow()
        order.version = int(order.version or 0) + 1
        results: list[dict[str, Any]] = []
        for d in deliveries:
            log = OrdPauseCommandLog(
                tenant_id=order.tenant_id,
                owner_id=order.owner_id,
                order_id=order_id,
                delivery_id=d.id,
                command="pause",
                # WMS 侧暂停报文未实现 → 记 pending（不算成功也不算失败）
                result="pending",
                abnormal_id=abnormal_id,
                operator=operator,
            )
            self.s.add(log)
            results.append(
                {"delivery_id": d.id, "result": "pending", "reason": "WMS 暂停报文待实现"}
            )
        await self.s.commit()
        return {
            "ok": True,
            "order_id": order_id,
            "paused": True,
            "deliveries": results,
            "all_done": all(r["result"] == "ok" for r in results) if results else True,
            "wms_pending": True,
            "note": reason,
        }

    async def resume_order(
        self, order_id: int, *, operator: str = "system"
    ) -> dict[str, Any]:
        """订单恢复编排（FR-06c：逐发货单重推指令）

        ⚠ **不半恢复**：任一发货单恢复失败 → 订单保持暂停（FR-06c）。
        """
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id, OrdOrder.is_deleted == 0)
        )
        if order is None:
            raise NotFoundError(f"订单不存在: {order_id}")
        from app.models.fulfill import OrdDelivery

        deliveries = list(
            await self.s.scalars(
                select(OrdDelivery).where(
                    OrdDelivery.order_id == order_id, OrdDelivery.is_deleted == 0
                )
            )
        )
        results: list[dict[str, Any]] = []
        for d in deliveries:
            log = OrdPauseCommandLog(
                tenant_id=order.tenant_id,
                owner_id=order.owner_id,
                order_id=order_id,
                delivery_id=d.id,
                command="resume",
                result="pending",
                operator=operator,
            )
            self.s.add(log)
            results.append({"delivery_id": d.id, "result": "pending"})
        failed = [r for r in results if r["result"] == "fail"]
        if failed:
            # 不半恢复：保持暂停
            await self.s.commit()
            return {
                "ok": False,
                "order_id": order_id,
                "resumed": False,
                "deliveries": results,
                "reason": "任一发货单恢复失败 → 订单保持暂停（不半恢复）",
            }
        order.fulfill_status = "pending"
        order.update_time = utcnow()
        order.version = int(order.version or 0) + 1
        await self.s.commit()
        return {
            "ok": True,
            "order_id": order_id,
            "resumed": True,
            "deliveries": results,
        }

    async def list_pause_logs(self, order_id: int) -> list[dict[str, Any]]:
        """暂停命令日志（FR-06b 留痕）"""
        rows = list(
            await self.s.scalars(
                select(OrdPauseCommandLog)
                .where(OrdPauseCommandLog.order_id == order_id)
                .order_by(OrdPauseCommandLog.id)
            )
        )
        return [
            {
                "id": r.id,
                "order_id": r.order_id,
                "delivery_id": r.delivery_id,
                "command": r.command,
                "result": r.result,
                "fail_code": r.fail_code,
                "fail_reason": r.fail_reason,
                "abnormal_id": r.abnormal_id,
                "operator": r.operator,
                "create_time": r.create_time.strftime("%Y-%m-%d %H:%M:%S")
                if r.create_time
                else None,
            }
            for r in rows
        ]

    async def add_to_list(
        self,
        *,
        list_type: str,
        dimension: str,
        match_value: str,
        scope: str = SCOPE_TENANT,
        owner_id: int | None = None,
        value_type: str = VALUE_PLAIN,
        reason: str = "",
        source: str = "manual",
        oa_approval_id: str = "",
        effective_hours: int = 0,
    ) -> OrdRiskList:
        """加入名单（FR-07b：增删改走审批）

        ⚠ 加入**黑名单**必须带 OA 审批单号（FR-07b：加入黑名单推 OA）→
        缺失时拒绝。
        """
        if list_type not in LIST_TYPE_LABEL:
            raise ValidationError(f"非法名单类型: {list_type}")
        if dimension not in (DIM_MOBILE, DIM_ADDRESS, DIM_ACCOUNT, DIM_NAME):
            raise ValidationError(f"非法名单维度: {dimension}")
        if scope not in (SCOPE_GLOBAL, SCOPE_TENANT, SCOPE_OWNER):
            raise ValidationError(f"非法作用域: {scope}")
        if scope == SCOPE_OWNER and not owner_id:
            raise ValidationError("货主私有名单须填 owner_id")
        if list_type == LIST_BLACK and not oa_approval_id:
            raise ValidationError(
                "加入黑名单必须带 OA 审批单号（FR-07b）", code="RISK_LIST_OA_REQUIRED"
            )
        now = utcnow()
        row = OrdRiskList(
            tenant_id=1,
            owner_id=owner_id,
            list_type=list_type,
            dimension=dimension,
            match_value=match_value,
            value_type=value_type,
            scope=scope,
            effective_start=now,
            effective_end=(now + timedelta(hours=effective_hours))
            if effective_hours > 0
            else None,
            reason=reason,
            source=source,
            oa_approval_id=oa_approval_id,
            disabled=0,
            is_deleted=0,
        )
        self.s.add(row)
        await self.s.commit()
        await self.s.refresh(row)
        return row

    async def remove_from_list(
        self,
        list_id: int,
        *,
        oa_approval_id: str = "",
        operator: str = "system",
    ) -> bool:
        """移出名单（FR-07b：移出黑名单同样推 OA）"""
        row = await self.s.scalar(
            select(OrdRiskList).where(
                OrdRiskList.id == list_id, OrdRiskList.is_deleted == 0
            )
        )
        if row is None:
            raise NotFoundError(f"名单记录不存在: {list_id}")
        if row.list_type == LIST_BLACK and not oa_approval_id:
            raise ValidationError(
                "移出黑名单必须带 OA 审批单号（FR-07b）",
                code="RISK_LIST_OA_REQUIRED",
            )
        row.disabled = 1
        row.update_time = utcnow()
        await self.s.commit()
        return True

    async def match_list(
        self,
        *,
        dimension: str,
        match_value: str,
        owner_id: int | None = None,
        list_type: str | None = None,
    ) -> dict[str, Any]:
        """名单命中判定（FR-07c/07d：私有优先）

        优先级：货主私有 > 租户私有 > 全局基础库。
        命中动作：黑名单 → 异常单+复审单 / 灰名单 → 审单 HOLD 转人工（不生成异常单）/
        白名单 → 跳过对应校验。
        """
        now = utcnow()
        q = select(OrdRiskList).where(
            OrdRiskList.dimension == dimension,
            OrdRiskList.match_value == match_value,
            OrdRiskList.disabled == 0,
            OrdRiskList.is_deleted == 0,
            # 生效期间过滤**下推到 SQL**：
            # ⚠ 不能在 Python 里对 ORM 对象判断——对象可能是过期快照
            #   （同事务内 UPDATE 过但未 refresh）→ 读到旧的有效期 → 误命中
            or_(OrdRiskList.effective_start.is_(None), OrdRiskList.effective_start <= now),
            or_(OrdRiskList.effective_end.is_(None), OrdRiskList.effective_end >= now),
        )
        if list_type:
            q = q.where(OrdRiskList.list_type == list_type)
        rows = list(await self.s.scalars(q))
        valid = rows
        if not valid:
            return {"hit": False, "list_type": "", "action": "", "scope": ""}
        # 私有优先：owner > tenant > global
        priority = {SCOPE_OWNER: 0, SCOPE_TENANT: 1, SCOPE_GLOBAL: 2}
        if owner_id:
            valid = [
                r for r in valid if r.scope == SCOPE_OWNER and r.owner_id == owner_id
            ] or [r for r in valid if r.scope != SCOPE_OWNER]
        valid.sort(key=lambda r: priority.get(r.scope, 9))
        hit = valid[0]
        action = {
            LIST_BLACK: "abnormal_and_retrial",  # 异常单 + 复审单
            LIST_GRAY: "audit_hold",  # 审单 HOLD 转人工（不生成异常单）
            LIST_WHITE: "skip_check",  # 跳过对应校验
        }.get(hit.list_type, "")
        return {
            "hit": True,
            "list_type": hit.list_type,
            "list_type_name": LIST_TYPE_LABEL.get(hit.list_type, hit.list_type),
            "scope": hit.scope,
            "list_id": hit.id,
            "action": action,
            "reason": hit.reason,
        }

    async def list_entries(
        self,
        *,
        list_type: str | None = None,
        dimension: str | None = None,
        scope: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """名单列表（维护视图）"""
        q = select(OrdRiskList).where(OrdRiskList.is_deleted == 0)
        if list_type:
            q = q.where(OrdRiskList.list_type == list_type)
        if dimension:
            q = q.where(OrdRiskList.dimension == dimension)
        if scope:
            q = q.where(OrdRiskList.scope == scope)
        rows = list(await self.s.scalars(q.order_by(OrdRiskList.id.desc()).limit(limit)))
        return [
            {
                "id": r.id,
                "list_type": r.list_type,
                "list_type_name": LIST_TYPE_LABEL.get(r.list_type, r.list_type),
                "dimension": r.dimension,
                "match_value": r.match_value,
                "value_type": r.value_type,
                "scope": r.scope,
                "owner_id": r.owner_id,
                "reason": r.reason,
                "source": r.source,
                "oa_approval_id": r.oa_approval_id,
                "disabled": r.disabled,
                "effective_start": r.effective_start.strftime("%Y-%m-%d %H:%M:%S")
                if r.effective_start
                else None,
                "effective_end": r.effective_end.strftime("%Y-%m-%d %H:%M:%S")
                if r.effective_end
                else None,
            }
            for r in rows
        ]

    async def scan_alerts(self) -> dict[str, Any]:
        """异常单告警扫描（FR-08c：类型级超期 + 数量突增）

        产出「告警待发」清单（企微推送 D01.07 未实现 → 明确 pending）。
        """
        rows = list(
            await self.s.scalars(
                select(OrdAbnormal).where(
                    OrdAbnormal.is_deleted == 0,
                    OrdAbnormal.status.notin_(
                        ("resolved", "cancelled")
                    ),
                )
            )
        )
        now = utcnow()
        overdue: list[dict[str, Any]] = []
        by_type_1h: dict[str, int] = {}
        for r in rows:
            if r.sla_deadline and r.sla_deadline < now:
                overdue.append(
                    {
                        "abnormal_id": r.id,
                        "abnormal_bn": r.abnormal_bn,
                        "exc_type": r.exc_type,
                        "order_bn": r.order_bn,
                        "sla_deadline": r.sla_deadline.strftime("%Y-%m-%d %H:%M:%S"),
                        "overdue_hours": round(
                            (now - r.sla_deadline).total_seconds() / 3600, 2
                        ),
                        "alert_type": "sla_overdue",
                        "push_status": "pending",
                    }
                )
            # 数量突增：1 小时内新增
            if r.create_time and (now - r.create_time).total_seconds() <= 3600:
                by_type_1h[r.exc_type] = by_type_1h.get(r.exc_type, 0) + 1
        surge = [
            {
                "exc_type": t,
                "count": c,
                "alert_type": "count_surge",
                "push_status": "pending",
            }
            for t, c in by_type_1h.items()
            if c >= 20
        ]
        return {"overdue": overdue, "surge": surge, "total": len(overdue) + len(surge)}
