"""ModifyRequestMixin —— 由 ModifyService 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.core.timeutil import utcnow
from app.models.fulfill import OrdDelivery
from app.models.modify import OrdOrderModify
from app.models.order import OrdOrder
from app.modules.m6_aftersale.service.modify_codes import (
    MODIFY_ADDRESS,
    MODIFY_OPEN_STATUSES,
    MODIFY_STATUS_CANCELLED,
    MODIFY_STATUS_EDITING,
    MODIFY_STATUS_RECALLING,
    MODIFY_STATUS_SUSPENDED,
    _hex,  # noqa: F401
    _unhex,  # noqa: F401
    )


class ModifyRequestMixin:
    """ModifyService 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Any

    async def create_address_modify(
        self,
        order_id: int,
        *,
        province: str = "",
        city: str = "",
        district: str = "",
        town: str = "",
        address_enc: bytes | str = b"",
        operator: str = "",
        source: str = "manual",
    ) -> dict[str, Any]:
        """发起改地址改单（FR-01a / FR-02a）

        流程：
        ① 前置状态校验（已发货/已完成/已取消 → 拒绝，提示走售后 FR-01c）
        ② 并发互斥（同订单已有进行中改单 → 拒绝 FR-01a）
        ③ 生成快照（FR-02a：订单主档/行/收货人）
        ④ 落改单（status=editing）
        ⑤ 若有发货单 → 需叫回（FR-06a）→ 置 recalling 并发起叫回
           若无发货单 → 直接生效（FR-03b：纯地址改单不动库存）
        """
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id, OrdOrder.is_deleted == 0)
        )
        if order is None:
            raise NotFoundError(f"订单不存在: {order_id}")

        # ① 前置状态校验（FR-01c）
        if order.order_status in ("shipped", "completed", "cancelled", "closed"):
            raise ConflictError(
                f"订单状态 {order.order_status} 不允许改单，请走售后流程",
                code="MODIFY_STATUS_NOT_ALLOWED",
            )
        # ② 并发互斥（FR-01a）
        open_modify = await self.s.scalar(
            select(OrdOrderModify)
            .where(
                OrdOrderModify.order_id == order_id,
                OrdOrderModify.status.in_(MODIFY_OPEN_STATUSES),
                OrdOrderModify.is_deleted == 0,
            )
            .limit(1)
        )
        if open_modify is not None:
            raise ConflictError(
                f"该订单已有进行中的改单（{open_modify.modify_bn}），请先处理",
                code="MODIFY_CONCURRENT_BLOCKED",
            )

        # ③ 快照（FR-02a）
        snap_id = await self._snapshot(order)

        # ④ 落改单
        modify_bn = f"MOD{utcnow():%Y%m%d}{uuid.uuid4().hex[:6].upper()}"
        diff = await self._diff_address(
            order_id,
            province=province,
            city=city,
            district=district,
            town=town,
            address_enc=address_enc,
        )
        row = OrdOrderModify(
            tenant_id=order.tenant_id,
            owner_id=order.owner_id,
            modify_bn=modify_bn,
            order_id=order.id,
            order_bn=order.order_bn,
            modify_type=MODIFY_ADDRESS,
            source=source,
            snapshot_id=snap_id,
            status=MODIFY_STATUS_EDITING,
            need_recall=0,
            diff_summary=diff,
            saga_log=[],
            operator=operator or "system",
            shop_id=order.shop_id,
            brand_id=order.brand_id,
            version=0,
            is_deleted=0,
        )
        self.s.add(row)
        await self.s.flush()

        # ⑤ 叫回判定（FR-06a）
        deliveries = list(
            await self.s.scalars(
                select(OrdDelivery).where(
                    OrdDelivery.order_id == order_id, OrdDelivery.is_deleted == 0
                )
            )
        )
        need_recall = bool(deliveries)
        row.need_recall = 1 if need_recall else 0
        if not need_recall:
            # 无发货单 → 直接生效（FR-03b：纯地址改单不动库存）
            await self._effective(row, operator=operator or "system")
            await self.s.commit()
            await self.s.refresh(row)
            return {
                "ok": True,
                "modify_id": row.id,
                "modify_bn": row.modify_bn,
                "status": row.status,
                "need_recall": False,
                "effective": True,
                "diff": diff,
            }

        # 需叫回 → 置 recalling 并发起叫回（FR-06b）
        row.status = MODIFY_STATUS_RECALLING
        row.recall_refs = [int(d.id) for d in deliveries]
        await self.s.commit()

        recall_result = await self._request_recall(row, deliveries, operator=operator)
        await self.s.commit()
        await self.s.refresh(row)
        return {
            "ok": True,
            "modify_id": row.id,
            "modify_bn": row.modify_bn,
            "status": row.status,
            "need_recall": True,
            "effective": False,
            "recall_result": recall_result,
            "diff": diff,
        }

    async def _request_recall(
        self, row: OrdOrderModify, deliveries: list[OrdDelivery], *, operator: str
    ) -> dict[str, Any]:
        """发起叫回（W7 链路复用）"""
        from app.modules.m7_integration.contract import OutboundCommandService

        svc = OutboundCommandService(self.s, self.r)
        results = []
        for d in deliveries:
            try:
                out = await svc.recall(
                    d.id,
                    ref_id=row.modify_bn,
                    operator=operator or "system",
                    reason=f"改地址叫回（改单 {row.modify_bn}）",
                )
            except Exception as e:  # noqa: BLE001 —— 叫回异常按失败处理
                results.append(
                    {"delivery_id": d.id, "ok": False, "err_msg": str(e)[:200]}
                )
                continue
            results.append(
                {
                    "delivery_id": d.id,
                    "ok": bool(getattr(out, "ok", False)),
                    "err_code": getattr(out, "err_code", ""),
                    "err_msg": getattr(out, "err_msg", "")[:200],
                }
            )
        # 任一失败 → 整体失败（FR-06c：合单组级联叫回，任一失败按整体失败）
        failed = [r for r in results if not r.get("ok")]
        if failed:
            row.status = MODIFY_STATUS_SUSPENDED
            row.saga_log = [
                *(row.saga_log or []),
                {
                    "at": utcnow().isoformat(),
                    "stage": "recall",
                    "ok": False,
                    "detail": results,
                },
            ]
            # 落异常单（人工跟进）—— 复用 W7 事件链的落单入口
            await self._raise_recall_abnormal(row, failed)
        else:
            row.saga_log = [
                *(row.saga_log or []),
                {
                    "at": utcnow().isoformat(),
                    "stage": "recall",
                    "ok": True,
                    "detail": results,
                },
            ]
        return {"deliveries": results, "all_ok": not failed}

    async def _raise_recall_abnormal(
        self, row: OrdOrderModify, failed: list[dict[str, Any]]
    ) -> None:
        """叫回失败 → 落异常单（FR-06c：改单挂起 + 告警 + 客服决策）"""
        from app.modules.m5_abnormal.contract import AbnormalService

        try:
            svc = AbnormalService(self.s, self.r)
            order = await self.s.scalar(
                select(OrdOrder).where(
                    OrdOrder.id == row.order_id, OrdOrder.is_deleted == 0
                )
            )
            if order is None:
                return
            await svc.create(
                order=order,
                exc_type="RECALL_FAILED",
                source="modify",
                source_ref=row.modify_bn,
                reason_detail={
                    "modify_bn": row.modify_bn,
                    "failed": failed,
                    "note": "改地址叫回失败，改单挂起待人工处理",
                },
            )
        except Exception:  # noqa: BLE001 —— 落单失败不阻断叫回结果返回
            pass

    async def complete_recall_and_effective(
        self, modify_id: int, *, operator: str = "system"
    ) -> dict[str, Any]:
        """叫回成功后 → 继续改单流程并生效（FR-06c）"""
        row = await self._get(modify_id)
        if row.status != MODIFY_STATUS_RECALLING:
            raise ConflictError(
                f"改单当前状态 {row.status} 不在叫回中",
                code="MODIFY_STATUS_INVALID",
            )
        await self._effective(row, operator=operator)
        await self.s.commit()
        await self.s.refresh(row)
        return {
            "ok": True,
            "modify_id": row.id,
            "modify_bn": row.modify_bn,
            "status": row.status,
            "effective": True,
        }

    async def cancel_recall_modify(
        self, modify_id: int, *, operator: str = "system", reason: str = ""
    ) -> dict[str, Any]:
        """撤销改单（叫回失败时的人工决策：撤销改单恢复现场 / 转人工，FR-06c）"""
        row = await self._get(modify_id)
        if row.status not in (MODIFY_STATUS_RECALLING, MODIFY_STATUS_SUSPENDED):
            raise ConflictError(
                f"改单当前状态 {row.status} 不可撤销",
                code="MODIFY_STATUS_INVALID",
            )
        row.status = MODIFY_STATUS_CANCELLED
        row.saga_log = [
            *(row.saga_log or []),
            {
                "at": utcnow().isoformat(),
                "stage": "cancel",
                "ok": True,
                "detail": reason,
            },
        ]
        await self.s.commit()
        await self.s.refresh(row)
        return {
            "ok": True,
            "modify_id": row.id,
            "modify_bn": row.modify_bn,
            "status": row.status,
        }
