"""异常单动作执行器（FR-02d）

按**类型字典的 `action_set`** 做白名单校验，只允许该异常类型被配置允许的动作。

动作清单（DDL 预置的 7 个）：

| action         | 语义                        | 本期实现                          |
|----------------|-----------------------------|-----------------------------------|
| `reaudit`      | 修复后重新审单（解除标记回审单池）| ✅ 真跑：释放预占 → 重新投审      |
| `to_retrial`   | 转复审（D03.08 改单）        | ✅ 真跑：落 `ord_retrial` 复审单   |
| `suspend`      | 挂起（等货/等买家回复）      | ✅ 真跑（AbnormalService.suspend）|
| `cancel`       | 取消订单（联动 D03.01 取消链路）| ✅ 真跑：释放预占 + 订单置取消      |
| `force_pass`   | 强制放行（跳过该校验继续审单）| ✅ 真跑：落审计留痕 + 解除标记      |
| `to_aftersale` | 转售后（D05）                | ⚠️ **扩展位**：D05 属 W9，返明确提示 |
| `refund`       | 退款                        | ⚠️ **扩展位**：平台退款属 W9，返回明确提示 |

⚠️ **扩展位不伪造结果**：`to_aftersale` / `refund` 不落任何假单据，
返回 `enabled: false` + 原因，由调用方与前端明示「W9 实现」。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.core.timeutil import utcnow
from app.models.abnormal import OrdAbnormal
from app.models.audit import OrdAuditReason

logger = get_logger("abnormal_action")

#: 异常单动作常量
ACT_REAUDIT = "reaudit"
ACT_TO_RETRIAL = "to_retrial"
ACT_TO_AFTERSALE = "to_aftersale"
ACT_SUSPEND = "suspend"
ACT_CANCEL = "cancel"
ACT_FORCE_PASS = "force_pass"
ACT_REFUND = "refund"

#: 全部合法动作
ALL_ACTIONS = (
    ACT_REAUDIT,
    ACT_TO_RETRIAL,
    ACT_TO_AFTERSALE,
    ACT_SUSPEND,
    ACT_CANCEL,
    ACT_FORCE_PASS,
    ACT_REFUND,
)

#: 可执行动作的前置状态（已分派 / 处理中）
#: ⚠ 待分派（wait_dispatch）不允许直接执行动作——否则会绕过状态机
#:   直接改订单/释放预占，而异常单还挂在待分派池里无人负责。
ACTION_ALLOWED_STATUS = ("assigned", "processing")

#: 本期未实现（后续批次）的动作 → 说明
PENDING_ACTIONS = {
    ACT_TO_AFTERSALE: "转售后（D05 售后服务）属 W9 范围，本期未实现",
    ACT_REFUND: "平台退款属 W9 范围，本期未实现",
}


class AbnormalActionService:
    """异常单动作执行器（FR-02d）"""

    def __init__(self, session: AsyncSession, redis: Any = None) -> None:
        self.s = session
        self.r = redis

    # ---------- 白名单 ----------

    async def allowed_actions(self, abnormal_id: int) -> list[str]:
        """取该异常类型允许的动作集（FR-02d：按类型配置可用动作集）"""
        from app.models.abnormal import OrdAbnormalTypeDict

        row = await self._abnormal(abnormal_id)
        tdict = await self.s.scalar(
            select(OrdAbnormalTypeDict).where(
                OrdAbnormalTypeDict.type_code == row.exc_type,
                OrdAbnormalTypeDict.is_deleted == 0,
            )
        )
        if tdict is None:
            return []
        raw = tdict.action_set or []
        if isinstance(raw, str):
            import json

            try:
                raw = json.loads(raw)
            except Exception:
                raw = []
        return [str(x) for x in raw if str(x) in ALL_ACTIONS]

    async def _abnormal(self, abnormal_id: int) -> OrdAbnormal:
        row = await self.s.scalar(
            select(OrdAbnormal).where(
                OrdAbnormal.id == abnormal_id, OrdAbnormal.is_deleted == 0
            )
        )
        if row is None:
            raise ValidationError(f"异常单不存在: {abnormal_id}")
        return row

    # ---------- 动作派发 ----------

    async def execute(
        self,
        abnormal_id: int,
        action: str,
        *,
        operator: str = "system",
        note: str = "",
        extra: dict | None = None,
    ) -> dict[str, Any]:
        """执行动作（FR-02d）

        ① 校验动作在该类型的 action_set 白名单内
        ② 未实现的动作 → 明确返回「本期未实现」，**不落任何假数据**
        ③ 执行成功 → 异常单闭环（解决）+ 写 resolve_action
        """
        action = str(action or "").strip()
        if action not in ALL_ACTIONS:
            raise ValidationError(f"非法动作: {action}", code="ABNORMAL_ACTION_INVALID")

        row = await self._abnormal(abnormal_id)
        # 前置状态校验：动作只能在「已分派 / 处理中」执行
        # （待分派的异常单必须先分派，否则动作会绕过状态机直接改订单）
        if row.status not in ACTION_ALLOWED_STATUS:
            raise ValidationError(
                f"异常单当前状态 {row.status} 不可执行动作"
                f"（需先分派为 assigned 或处理中 processing）",
                code="ABNORMAL_STATUS_INVALID",
            )
        allowed = await self.allowed_actions(abnormal_id)
        if action not in allowed:
            raise ValidationError(
                f"动作 {action} 不在类型 {row.exc_type} 的允许动作集内",
                code="ABNORMAL_ACTION_NOT_ALLOWED",
            )

        if action in PENDING_ACTIONS:
            return {
                "ok": False,
                "action": action,
                "enabled": False,
                "reason": PENDING_ACTIONS[action],
                "abnormal_id": abnormal_id,
            }

        handler = {
            ACT_REAUDIT: self._do_reaudit,
            ACT_TO_RETRIAL: self._do_to_retrial,
            ACT_SUSPEND: self._do_suspend,
            ACT_CANCEL: self._do_cancel,
            ACT_FORCE_PASS: self._do_force_pass,
        }[action]
        result = await handler(row, operator=operator, note=note, extra=extra or {})
        result.setdefault("ok", True)
        result["action"] = action
        result["abnormal_id"] = abnormal_id

        # 终态动作 → 异常单闭环（FR-02d 动作完成 + FR-02e 联动清标记）
        # ⚠ suspend 是**中间态**（等货/等买家回复）→ 不闭环，异常单保持挂起
        if action != ACT_SUSPEND and result.get("ok"):
            await self._close(row.id, action=action, operator=operator, note=note)
            result["closed"] = True
        return result

    async def _close(
        self, abnormal_id: int, *, action: str, operator: str, note: str
    ) -> None:
        """动作完成后闭环异常单（FR-02e：解除订单异常标记）"""
        from app.services.abnormal import AbnormalService

        svc = AbnormalService(self.s, self.r)
        try:
            await svc.resolve(
                abnormal_id, action=action, operator=operator, note=note
            )
        except Exception as e:  # noqa: BLE001 —— 闭环失败不掩盖动作结果
            logger.warning(
                "abnormal_action_close_failed",
                detail=str(e),
                abnormal_id=abnormal_id,
                action=action,
            )

    # ============ 具体动作实现 ============

    async def _do_reaudit(
        self, row: OrdAbnormal, *, operator: str, note: str, extra: dict
    ) -> dict[str, Any]:
        """修复后重新审单（FR-02d）

        流程：释放该订单的预占 → 订单重新投审（回审单池）→ 异常单闭环。
        """
        from app.services.audit_engine import AuditEngine
        from app.services.plan_executor import PlanExecutor

        plan_svc = PlanExecutor(self.s, self.r)
        # ① 释放旧 plan 的预占（打回重审路径 FR-05d）
        released = 0
        plans = await plan_svc.list_plans(row.order_id) if row.order_id else []
        for p in plans:
            if p.exec_status in ("running", "waiting"):
                try:
                    await plan_svc.discard_plan(p.id, operator=operator)
                    released += 1
                except Exception as e:  # noqa: BLE001 —— 释放失败不阻断重审
                    note = f"{note} | 释放预占失败:{e}"[:512]

        # ② 重新投审（回审单池）
        outcome = await AuditEngine(self.s, self.r).submit(
            row.order_id, decision_by=operator
        )
        decision = str(getattr(outcome, "decision", "") or "")
        return {
            # 重新投审已执行即算动作成功；是否通过由 decision 表达
            "ok": True,
            "stage": "reaudit",
            "released_plans": released,
            "audit_decision": decision,
            "audit_passed": decision == "auto_pass",
            "reason_codes": [
                getattr(r, "code", "") for r in (getattr(outcome, "reasons", []) or [])
            ],
            "note": note,
        }

    async def _do_to_retrial(
        self, row: OrdAbnormal, *, operator: str, note: str, extra: dict
    ) -> dict[str, Any]:
        """转复审（FR-02d → D03.08 改单复审）

        落 `ord_retrial` 复审单（表已存在），关联 `rel_retrial_id`。
        D03.08 的改单执行链路在 W8-3 落地，本期完成「复审单落库 + 关联」。
        """
        from app.models.audit import OrdRetrial
        from app.services.order_bn import OrderBnGenerator

        # 发号器签名：next(prefix, shop_bn)
        bn = await OrderBnGenerator(self.s, self.r).next("RT", "")
        ret = OrdRetrial(
            tenant_id=row.tenant_id,
            owner_id=int(row.owner_id or 0),
            retrial_bn=bn,
            order_id=row.order_id,
            retrial_type="abnormal",
            status="wait",
            hit_detail={"abnormal_id": row.id, "exc_type": row.exc_type, "note": note},
            assign_group=row.group_id,
            shop_id=row.shop_id,
        )
        self.s.add(ret)
        await self.s.flush()
        row.rel_retrial_id = ret.id
        await self.s.commit()
        return {
            "ok": True,
            "stage": "to_retrial",
            "retrial_id": ret.id,
            "retrial_bn": ret.retrial_bn,
            "note": note,
        }

    async def _do_suspend(
        self, row: OrdAbnormal, *, operator: str, note: str, extra: dict
    ) -> dict[str, Any]:
        """挂起（等货 / 等买家回复，须填预计恢复时间）"""
        from app.services.abnormal import AbnormalService

        hours = int(extra.get("suspend_hours") or 0)
        if hours <= 0:
            raise ValidationError(
                "挂起须填预计恢复时间（suspend_hours > 0）",
                code="ABNORMAL_SUSPEND_TIME_REQUIRED",
            )
        await AbnormalService(self.s, self.r).suspend(
            row.id, operator=operator, note=note, until_hours=hours
        )
        return {"ok": True, "stage": "suspend", "suspend_hours": hours, "note": note}

    async def _do_cancel(
        self, row: OrdAbnormal, *, operator: str, note: str, extra: dict
    ) -> dict[str, Any]:
        """取消订单（联动 D03.01 取消链路）

        释放该订单全部预占 + 订单置已取消 + 未闭环异常单收口（FR-02e）。
        """
        from app.models.order import OrdOrder
        from app.services.plan_executor import PlanExecutor

        released = 0
        if row.order_id:
            plan_svc = PlanExecutor(self.s, self.r)
            plans = await plan_svc.list_plans(row.order_id)
            for p in plans:
                if p.exec_status in ("running", "waiting"):
                    try:
                        await plan_svc.discard_plan(p.id, operator=operator)
                        released += 1
                    except Exception as e:  # noqa: BLE001 —— 释放失败不阻断取消
                        note = f"{note} | 释放预占失败:{e}"[:512]
            order = await self.s.scalar(
                select(OrdOrder).where(
                    OrdOrder.id == row.order_id, OrdOrder.is_deleted == 0
                )
            )
            if order is not None:
                order.order_status = "cancelled"
                order.update_time = utcnow()
                order.version = int(order.version or 0) + 1
        await self.s.commit()
        return {
            "ok": True,
            "stage": "cancel",
            "released_plans": released,
            "order_id": row.order_id,
            "note": note,
        }

    async def _do_force_pass(
        self, row: OrdAbnormal, *, operator: str, note: str, extra: dict
    ) -> dict[str, Any]:
        """强制放行（跳过该校验继续审单）

        敏感操作：必须留痕（FR-02d「敏感操作推 OA + 审计」——OA 推送属 W8-3，
        本期先落库审计 + 时间线，记录推送待办）。
        """
        from app.services.abnormal import AbnormalService

        svc = AbnormalService(self.s, self.r)
        # 解除该订单的未处理审单原因标记（跳过该校验）
        released = await svc.release_order_marks(
            row, operator=f"force_pass:{operator}"
        )
        row.reason_detail = {
            **(row.reason_detail if isinstance(row.reason_detail, dict) else {}),
            "force_pass": {
                "operator": operator,
                "note": note,
                "time": utcnow().isoformat(),
                "oa_push": "pending",
            },
        }
        await self.s.commit()
        return {
            "ok": True,
            "stage": "force_pass",
            "released_reasons": released,
            "audit_trail": "已落库审计 + 异常单时间线（OA 推送待 W8-3）",
            "note": note,
        }

    # ---------- 审单原因清零辅助 ----------

    async def clear_reasons(self, order_id: int, operator: str) -> int:
        """清零该订单的未处理审单原因（强制放行/重新审单用）"""
        res = await self.s.execute(
            update(OrdAuditReason)
            .where(
                OrdAuditReason.order_id == order_id,
                OrdAuditReason.handle_status == "open",
            )
            .values(handle_status="handled", handle_way=f"abnormal:{operator}"[:64])
        )
        await self.s.commit()
        return int(getattr(res, "rowcount", 0) or 0)
