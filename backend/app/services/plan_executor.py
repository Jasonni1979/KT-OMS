"""plan 执行器（D03.02 FR-05c/FR-05d/FR-05f：决策执行分离的执行侧）

**执行器序列**（FR-05c，每 plan 一个执行事务编排）：
```
① FreezeService.reserveBatch（按拆单方案逐发货单组预占，Saga 补偿）
   失败 → plan=失败已补偿；原因 STOCK_RACE → 路由 D03.09 或回待审重算
② 发货单生成（D03.07，按 plan 矩阵；合单组生成母单）—— W6 接入
   失败 → 释放预占 + plan=失败已补偿 + 最高级告警人工
③ StatusService.transit（audit=已审核，fulfill=履约中）
④ 推仓触发（D03.07→D09.02）—— W6/W7 接入
```

**W5 范围**：①（预占）+ ③（状态 transit）真实实现；
② 发货单生成与 ④ 推仓在 W6/W7 接入（W5 先落 delivery_refs 占位并标记 pending）。

**关键约束**：
- plan 先落库（状态=待执行）→ 执行器异步消费（FR-05b）
- 执行失败**不回改 plan**（plan 是决策事实），执行状态独立字段
- 人工决策走**同源执行**（FR-05f）：executeManualPlan 与自动链路唯一执行路径
- 幂等：各步幂等键 = plan_id + 步骤（§5.2 崩溃恢复可续跑）
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.audit import OrdAuditReason, OrdFulfillPlan
from app.models.order import OrdOrder
from app.schemas import stock as sc
from app.services.freeze import FreezeService

logger = get_logger("audit_exec")

#: 预占对象类型：1=订单
FREEZE_OBJ_TYPE_ORDER = 1


@dataclass
class ExecResult:
    """执行结果"""

    plan_id: int
    plan_bn: str
    order_id: int
    #: 成功 / 失败已补偿
    status: str = "success"
    fail_code: str = ""
    fail_message: str = ""
    #: 预占结果（供发货单生成定位）
    freeze_refs: list[dict[str, Any]] = field(default_factory=list)
    #: 生成的发货单（W6 接入）
    delivery_ids: list[str] = field(default_factory=list)
    cost_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "success"

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "plan_bn": self.plan_bn,
            "order_id": self.order_id,
            "status": self.status,
            "fail_code": self.fail_code,
            "fail_message": self.fail_message,
            "freeze_refs": self.freeze_refs,
            "delivery_ids": self.delivery_ids,
            "cost_ms": self.cost_ms,
        }


class PlanExecutor:
    """plan 执行器"""

    def __init__(self, session: AsyncSession, redis: Redis):
        self.s = session
        self.r = redis

    # ---------- plan 读取 ----------

    async def get_plan(self, order_id: int, plan_id: int | None = None) -> OrdFulfillPlan:
        """取 plan（IF-D03.02-03）"""
        stmt = select(OrdFulfillPlan).where(OrdFulfillPlan.order_id == order_id)
        if plan_id:
            stmt = stmt.where(OrdFulfillPlan.id == plan_id)
        plan = await self.s.scalar(
            stmt.order_by(OrdFulfillPlan.plan_version.desc()).limit(1)
        )
        if plan is None:
            raise NotFoundError(f"履约方案不存在: order={order_id} plan={plan_id}")
        return plan

    async def list_plans(self, order_id: int) -> list[OrdFulfillPlan]:
        """plan 版本链（FR-05d：版本链完整保留，回放依据）"""
        return list(
            await self.s.scalars(
                select(OrdFulfillPlan)
                .where(OrdFulfillPlan.order_id == order_id)
                .order_by(OrdFulfillPlan.plan_version)
            )
        )

    # ---------- 执行 ----------

    async def execute(
        self, plan_id: int, *, operator: str = "system"
    ) -> ExecResult:
        """执行 plan（FR-05c 序列）"""
        import time

        t0 = time.perf_counter()
        plan = await self.s.scalar(
            select(OrdFulfillPlan).where(OrdFulfillPlan.id == plan_id)
        )
        if plan is None:
            raise NotFoundError(f"履约方案不存在: {plan_id}")
        if plan.exec_status == "success":
            # 幂等：已成功直接返回（崩溃恢复续跑安全）
            return ExecResult(
                plan_id=plan.id,
                plan_bn=plan.plan_bn,
                order_id=plan.order_id,
                status="success",
                cost_ms=0,
            )
        # CAS：待执行/执行中 → 执行中
        plan.exec_status = "running"
        plan.plan_status = "executing"
        await self.s.commit()

        result = ExecResult(plan_id=plan.id, plan_bn=plan.plan_bn, order_id=plan.order_id)

        # ① 预占（按拆单方案逐组；SAGA 内部已回滚）
        try:
            refs = await self._reserve(plan)
            result.freeze_refs = refs
        except Exception as e:  # noqa: BLE001 —— 预占失败走 STOCK_RACE 补偿路径
            logger.warning("plan_reserve_failed", detail=str(e), plan_id=plan.id)
            plan.exec_status = "failed"
            plan.plan_status = "failed"
            plan.fail_code = "STOCK_RACE"
            await self.s.commit()
            await self._write_reason(
                plan,
                code="STOCK_RACE",
                description=f"预占失败（决策到执行间隙库存被抢）：{e}",
                route="shortage",
            )
            result.status = "failed"
            result.fail_code = "STOCK_RACE"
            result.fail_message = str(e)
            result.cost_ms = int((time.perf_counter() - t0) * 1000)
            return result

        # ② 发货单生成（W6 接入；W5 落占位引用）
        result.delivery_ids = await self._create_deliveries(plan)

        # ③ 状态 transit（audit=已审核，fulfill=履约中）
        await self._transit(plan)

        # ④ 推仓触发（W7 接入）
        await self._push_wms(plan, result.delivery_ids)

        plan.exec_status = "success"
        plan.plan_status = "executed"
        plan.delivery_ids = json.dumps(result.delivery_ids, ensure_ascii=False)
        await self.s.commit()
        result.cost_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            "plan_executed",
            plan_id=plan.id,
            order_id=plan.order_id,
            cost_ms=result.cost_ms,
            deliveries=len(result.delivery_ids),
        )
        return result

    async def _reserve(self, plan: OrdFulfillPlan) -> list[dict[str, Any]]:
        """① 按拆单方案逐发货单组预占（幂等键=plan_id+组+行）"""
        matrix = plan.split_matrix or {}
        groups = matrix.get("groups", []) if isinstance(matrix, dict) else []
        if not groups:
            raise ValidationError("plan 缺少拆单方案，无法预占")
        freeze = FreezeService(self.s, self.r)
        items: list[sc.FreezeReserveItem] = []
        for g in groups:
            branch_id = int(g.get("branch_id", 0) or 0)
            owner_id = int(g.get("owner_id", 0) or 0)
            for line in g.get("lines", []):
                bm_id = int(line.get("bm_id", 0) or 0)
                if bm_id <= 0:
                    # 行未解析出基础物料 → 无法预占（FR-03 阶段已拦截，这里兜底）
                    continue
                items.append(
                    sc.FreezeReserveItem(
                        branch_id=branch_id,
                        bm_id=bm_id,
                        owner_id=owner_id,
                        num=int(line.get("nums", 0) or 0),
                        obj_item_id=int(line.get("item_id", 0) or 0),
                    )
                )
        if not items:
            raise ValidationError("plan 拆单方案无可预占明细行（基础物料缺失）")
        # 幂等：对象单号用 plan_bn（同一 plan 重复执行 → 预占幂等命中）
        res = await freeze.reserve(
            sc.FreezeReserveRequest(
                obj_type=FREEZE_OBJ_TYPE_ORDER,
                obj_bn=plan.plan_bn,
                items=items,
                source="audit",
            )
        )
        return [
            {
                "obj_bn": plan.plan_bn,
                "obj_item_id": getattr(log, "obj_item_id", 0),
                "bm_id": getattr(log, "bm_id", 0),
                "owner_id": getattr(log, "owner_id", 0),
                "branch_id": getattr(log, "branch_id", 0),
                "num": getattr(log, "num", 0),
            }
            for log in res.logs
        ]

    async def _create_deliveries(self, plan: OrdFulfillPlan) -> list[str]:
        """② 发货单生成（W6 接入 D03.07；W5 落占位引用）"""
        matrix = plan.split_matrix or {}
        groups = matrix.get("groups", []) if isinstance(matrix, dict) else []
        refs = [f"D{plan.plan_bn[-10:]}-G{i + 1}" for i, _ in enumerate(groups)]
        if refs:
            logger.info("delivery_pending_wms6", plan_id=plan.id, count=len(refs))
        return refs

    async def _transit(self, plan: OrdFulfillPlan) -> None:
        """③ 状态 transit（audit=已审核，fulfill=履约中）"""
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == plan.order_id)
        )
        if order is None:
            return
        order.audit_status = "audited"
        order.fulfill_status = "fulfilling"
        await self.s.commit()

    async def _push_wms(self, plan: OrdFulfillPlan, delivery_ids: list[str]) -> None:
        """④ 推仓触发（W7 接入 D09.02；W5 留痕占位）"""
        if delivery_ids:
            logger.info("push_wms_pending_w7", plan_id=plan.id, count=len(delivery_ids))

    async def _write_reason(
        self, plan: OrdFulfillPlan, *, code: str, description: str, route: str
    ) -> None:
        """执行失败补写结构化原因（FR-05c：预占失败 → STOCK_RACE）"""
        self.s.add(
            OrdAuditReason(
                order_id=plan.order_id,
                batch_no=plan.plan_bn,
                plugin_name="plan_executor",
                reason_code=code,
                level="BLOCK",
                description=description[:1024],
                detail={"plan_id": plan.id, "plan_bn": plan.plan_bn},
                suggest_action="重审重算",
                route_target=route,
                handle_status="open",
                shop_id=plan.shop_id,
                owner_id=plan.owner_id,
            )
        )
        await self.s.commit()

    # ---------- 人工同源执行（FR-05f） ----------

    async def execute_manual_plan(
        self,
        order_id: int,
        decision: dict[str, Any],
        operator: str,
        *,
        plan_id: int | None = None,
    ) -> ExecResult:
        """人工决策同源执行（IF-D03.02-02）

        人工审核（采纳引擎建议或人工指定仓/拆/物流）→ 产出**人工 plan**
        （决策者=账户 ID）→ 走**同一执行器** → 预占生成发货单推仓。
        与自动链路产物结构一致（消除商派 mkDelivery 双路径不一致隐患）。
        """
        plan = await self.get_plan(order_id, plan_id)
        # 人工决策覆盖 plan 决策要素
        if decision.get("branch"):
            plan.warehouse_alloc = decision["branch"]
        if decision.get("split_groups"):
            plan.split_matrix = {"groups": decision["split_groups"]}
        if decision.get("logistics"):
            plan.logistics_alloc = decision["logistics"]
        plan.decision_by = operator
        plan.decision_time = datetime.now()
        plan.plan_status = "pending"
        plan.exec_status = "waiting"
        await self.s.commit()
        return await self.execute(plan.id, operator=operator)

    # ---------- 重算（FR-05d） ----------

    async def discard_plan(self, plan_id: int, *, operator: str = "system") -> bool:
        """废弃 plan 并释放预占（FR-05d：打回重审路径）"""
        plan = await self.s.scalar(
            select(OrdFulfillPlan).where(OrdFulfillPlan.id == plan_id)
        )
        if plan is None:
            raise NotFoundError(f"履约方案不存在: {plan_id}")
        if plan.exec_status == "success":
            raise ValidationError("已执行的 plan 不可废弃")
        # 释放预占
        if plan.exec_status in ("running", "waiting"):
            freeze = FreezeService(self.s, self.r)
            await freeze.release(
                sc.FreezeReleaseRequest(
                    obj_type=FREEZE_OBJ_TYPE_ORDER,
                    obj_bn=plan.plan_bn,
                    operator=operator,
                )
            )
        plan.plan_status = "discarded"
        plan.exec_status = "discarded"
        await self.s.commit()
        return True

    # ---------- 回放（FR-05e） ----------

    async def replay(self, order_id: int) -> dict[str, Any]:
        """plan 回放（IF-D03.02-03：完整决策上下文，供审计与排障）"""
        plans = await self.list_plans(order_id)
        return {
            "order_id": order_id,
            "versions": [
                {
                    "plan_id": p.id,
                    "plan_bn": p.plan_bn,
                    "plan_version": p.plan_version,
                    "plan_status": p.plan_status,
                    "exec_status": p.exec_status,
                    "rule_snapshot_id": p.rule_snapshot_id,
                    "warehouse_alloc": p.warehouse_alloc,
                    "split_matrix": p.split_matrix,
                    "logistics_alloc": p.logistics_alloc,
                    "decision_by": p.decision_by,
                    "decision_time": str(p.decision_time) if p.decision_time else None,
                    "plugin_trace": p.plugin_trace,
                    "delivery_ids": p.delivery_ids,
                    "fail_code": p.fail_code,
                }
                for p in plans
            ],
        }
