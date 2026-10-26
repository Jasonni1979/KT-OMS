"""审单 API（D03.02 审单引擎 + D03.03 人工审单工作台）

- /audit/*：审单引擎（规则管理 / 投审 / 原因查询 / plan 查询回放 / 执行）
- /audit/workbench/*：人工审单工作台（队列 / 分派 / 单单审核 / 批量审核 / 驳回）
"""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.response import ok
from app.models.audit import (
    OrdAuditGroup,
    OrdAuditReason,
    OrdAuditRule,
    OrdAuditTask,
    OrdAuditWorkLog,
    OrdDispatchRule,
    OrdFulfillPlan,
)
from app.models.order import OrdOrder
from app.modules.m1_master.service.master import get_redis
from app.modules.m3_trade.service.audit_engine import AuditEngine, register_audit_chain
from app.modules.m3_trade.service.audit_plugins import register_audit_plugins
from app.modules.m3_trade.service.audit_rule import AuditRuleService
from app.modules.m4_fulfill.service.dispatch import DispatchService
from app.modules.m4_fulfill.service.plan_executor import PlanExecutor

router = APIRouter()

#: 启动时注册链与插件（D01.03 FR-03b：服务发现式注册）
register_audit_chain()
register_audit_plugins()


async def _engine(session: AsyncSession) -> AuditEngine:
    redis = await get_redis()
    return AuditEngine(session, redis, AuditRuleService())


# ============ 审单规则管理（D03.02 FR-03c）============

@router.get("/audit/rules", summary="审单规则列表（weight DESC 排序）")
async def list_rules(
    status: str | None = Query(default=None, max_length=16),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(OrdAuditRule).where(OrdAuditRule.is_deleted == 0)
    if status:
        stmt = stmt.where(OrdAuditRule.status == status)
    rows = list(
        await session.scalars(stmt.order_by(OrdAuditRule.weight.desc(), OrdAuditRule.id.asc()))
    )
    return ok([
        {
            "id": r.id,
            "rule_name": r.rule_name,
            "conditions": r.conditions,
            "weight": r.weight,
            "plugin_config": r.plugin_config,
            "auto_confirm": r.auto_confirm,
            "pass_action": r.pass_action,
            "fail_route": r.fail_route,
            "effective_window": r.effective_window,
            "exclude_window": r.exclude_window,
            "default_audit_group": r.default_audit_group,
            "router_num_limit": r.router_num_limit,
            "status": r.status,
            "is_default": r.is_default,
            "version": r.version,
        }
        for r in rows
    ])


@router.put("/audit/rules/{rule_id}", summary="修改审单规则（变更驱动缓存失效）")
async def update_rule(
    rule_id: int,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
):
    rule = await session.scalar(
        select(OrdAuditRule).where(OrdAuditRule.id == rule_id, OrdAuditRule.is_deleted == 0)
    )
    if rule is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError(f"审单规则不存在: {rule_id}")
    if rule.is_default:
        from app.core.exceptions import ValidationError

        raise ValidationError("系统缺省规则不可修改")
    allowed = {
        "rule_name", "conditions", "weight", "plugin_config", "auto_confirm",
        "pass_action", "fail_route", "effective_window", "exclude_window",
        "default_audit_group", "router_num_limit", "status",
    }
    for k, v in payload.items():
        if k in allowed:
            setattr(rule, k, v)
    rule.version += 1
    await session.commit()
    # 变更事件驱动缓存失效（D01.03 FR-09b）
    AuditRuleService().invalidate()
    return ok({"id": rule.id, "version": rule.version})


@router.get("/audit/rules/{rule_id}/dry-run", summary="规则试算器（不落库不执行）")
async def dry_run_rule(
    rule_id: int,
    order_id: int = Query(gt=0),
    session: AsyncSession = Depends(get_session),
):
    """规则命中查询 + 逐项求值明细（FR-03c：配置上线前验证）"""
    from app.core.exceptions import NotFoundError

    rule = await session.scalar(
        select(OrdAuditRule).where(OrdAuditRule.id == rule_id, OrdAuditRule.is_deleted == 0)
    )
    if rule is None:
        raise NotFoundError(f"审单规则不存在: {rule_id}")
    engine = await _engine(session)
    ctx = await engine.load_context(order_id)
    from app.modules.m3_trade.service.audit_rule import AuditRule

    ar = AuditRule.from_row(rule)
    detail = ar.explain(ctx.dims)
    return ok({
        "rule_id": rule_id,
        "rule_name": rule.rule_name,
        "hit": detail["hit"],
        "details": detail["details"],
        "in_effective_window": ar.in_effective_window(),
        "in_exclude_window": ar.in_exclude_window(),
    })


@router.get("/audit/orders/{order_id}/match", summary="查订单命中的审单规则")
async def match_rule(
    order_id: int,
    session: AsyncSession = Depends(get_session),
):
    engine = await _engine(session)
    ctx = await engine.load_context(order_id)
    svc = AuditRuleService()
    await svc.load(session)
    rule, traces = svc.match_with_explain(ctx.dims)
    return ok({
        "rule_id": rule.id,
        "rule_name": rule.rule_name,
        "auto_confirm": rule.auto_confirm,
        "auto_confirm_effective": rule.auto_confirm_effective(),
        "snapshot_id": rule.snapshot(),
        "traces": traces,
    })


# ============ 审单投审与执行（D03.02）============

@router.post("/audit/orders/{order_id}/submit", summary="投审（插件链决策 + 原因落库 + plan）")
async def submit_audit(
    order_id: int,
    batch_no: str = Query(default="", max_length=32),
    session: AsyncSession = Depends(get_session),
):
    engine = await _engine(session)
    outcome = await engine.submit(order_id, batch_no=batch_no)
    return ok(outcome.to_dict())


@router.get("/audit/orders/{order_id}/reasons", summary="查订单的结构化审核原因")
async def list_reasons(
    order_id: int,
    only_open: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(OrdAuditReason).where(OrdAuditReason.order_id == order_id)
    if only_open:
        stmt = stmt.where(OrdAuditReason.handle_status == "open")
    rows = list(await session.scalars(stmt.order_by(OrdAuditReason.id)))
    return ok([
        {
            "id": r.id,
            "batch_no": r.batch_no,
            "plugin_name": r.plugin_name,
            "reason_code": r.reason_code,
            "level": r.level,
            "description": r.description,
            "detail": r.detail,
            "suggest_action": r.suggest_action,
            "route_target": r.route_target,
            "handle_status": r.handle_status,
            "shop_id": r.shop_id,
            "create_time": str(r.create_time),
        }
        for r in rows
    ])


@router.get("/audit/orders/{order_id}/plans", summary="plan 版本链查询（FR-05e 回放）")
async def list_plans(
    order_id: int,
    session: AsyncSession = Depends(get_session),
):
    redis = await get_redis()
    ex = PlanExecutor(session, redis)
    return ok(await ex.replay(order_id))


@router.post("/audit/plans/{plan_id}/execute", summary="执行 plan（决策执行分离的执行侧）")
async def execute_plan(
    plan_id: int,
    operator: str = Query(default="system", max_length=64),
    session: AsyncSession = Depends(get_session),
):
    redis = await get_redis()
    ex = PlanExecutor(session, redis)
    result = await ex.execute(plan_id, operator=operator)
    return ok(result.to_dict())


@router.post("/audit/plans/{plan_id}/discard", summary="废弃 plan 并释放预占（FR-05d 重算路径）")
async def discard_plan(
    plan_id: int,
    operator: str = Query(default="system", max_length=64),
    session: AsyncSession = Depends(get_session),
):
    redis = await get_redis()
    ex = PlanExecutor(session, redis)
    await ex.discard_plan(plan_id, operator=operator)
    return ok({"plan_id": plan_id, "status": "discarded"})


# ============ 人工审单工作台（D03.03）============

@router.get("/audit/workbench/queue", summary="待审队列（多维筛选 + 时效优先排序）")
async def workbench_queue(
    shop_id: int | None = Query(default=None, ge=1),
    reason_code: str | None = Query(default=None, max_length=64),
    assign_op: int | None = Query(default=None, ge=1),
    task_status: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    """队列数据源：audit_status=待审核 且已分派；未分派在公共池视图"""
    stmt = (
        select(OrdAuditTask, OrdOrder)
        .join(OrdOrder, OrdOrder.id == OrdAuditTask.order_id)
        .where(OrdAuditTask.is_active == 1)
    )
    if shop_id:
        stmt = stmt.where(OrdAuditTask.shop_id == shop_id)
    if assign_op:
        stmt = stmt.where(OrdAuditTask.assign_op == assign_op)
    if task_status:
        stmt = stmt.where(OrdAuditTask.task_status == task_status)
    rows = list(await session.execute(stmt.limit(limit)))
    items: list[dict[str, Any]] = []
    # 原因码徽章（FR-01e：列表行内直接渲染原因码）——始终带出，供筛选与展示
    reason_codes: dict[int, list[str]] = {}
    order_ids = [t.order_id for t, _ in rows]
    if order_ids:
        rc_rows = list(
            await session.scalars(
                select(OrdAuditReason).where(OrdAuditReason.order_id.in_(order_ids))
            )
        )
        for rc in rc_rows:
            reason_codes.setdefault(rc.order_id, []).append(rc.reason_code)
    if reason_code:
        # 按原因码筛选（FR-01b 多维筛选）
        ids = {oid for oid, codes in reason_codes.items() if reason_code in codes}
        rows = [(t, o) for t, o in rows if t.order_id in ids]  # type: ignore[misc]
    for task, order in rows:
        items.append({
            "task_id": task.id,
            "order_id": task.order_id,
            "order_bn": order.order_bn,
            "platform_order_bn": order.platform_order_bn,
            "shop_id": task.shop_id,
            "audit_status": order.audit_status,
            "task_status": task.task_status,
            "assign_group": task.assign_group,
            "assign_op": task.assign_op,
            "assign_time": str(task.assign_time) if task.assign_time else None,
            "assign_way": task.assign_way,
            "paid_amount": float(order.paid_amount),
            "buyer_nick": order.buyer_nick,
            "buyer_memo": order.buyer_memo,
            "pay_time": str(order.pay_time) if order.pay_time else None,
            "sla_deadline": str(task.sla_deadline) if task.sla_deadline else None,
            "overtime_level": task.overtime_level,
            "reason_codes": reason_codes.get(task.order_id, []),
        })
    # 时效优先排序（FR-01d：SLA 剩余时间 ASC，超时置顶）
    items.sort(
        key=lambda x: (
            x["sla_deadline"] is None,
            x["sla_deadline"] or "9999",
            x["pay_time"] or "9999",
        )
    )
    return ok({"total": len(items), "items": items})


@router.get("/audit/workbench/orders/{order_id}", summary="订单审单详情（聚合信息 + 原因 + 建议草稿）")
async def workbench_detail(
    order_id: int,
    session: AsyncSession = Depends(get_session),
):
    """FR-03a：订单聚合展示 + 结构化原因区 + 引擎决策草稿"""
    order = await session.scalar(
        select(OrdOrder).where(OrdOrder.id == order_id, OrdOrder.is_deleted == 0)
    )
    if order is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError(f"订单不存在: {order_id}")
    engine = await _engine(session)
    ctx = await engine.load_context(order_id)
    reasons = list(
        await session.scalars(
            select(OrdAuditReason)
            .where(OrdAuditReason.order_id == order_id)
            .order_by(OrdAuditReason.id)
        )
    )
    plans = list(
        await session.scalars(
            select(OrdFulfillPlan)
            .where(OrdFulfillPlan.order_id == order_id)
            .order_by(OrdFulfillPlan.plan_version.desc())
        )
    )
    latest = plans[0] if plans else None
    task = await session.scalar(
        select(OrdAuditTask)
        .where(OrdAuditTask.order_id == order_id, OrdAuditTask.is_active == 1)
        .limit(1)
    )
    return ok({
        "order": ctx.order,
        "items": ctx.items,
        "receiver": ctx.receiver,
        "reasons": [
            {
                "id": r.id,
                "plugin_name": r.plugin_name,
                "reason_code": r.reason_code,
                "level": r.level,
                "description": r.description,
                "detail": r.detail,
                "suggest_action": r.suggest_action,
                "route_target": r.route_target,
                "handle_status": r.handle_status,
            }
            for r in reasons
        ],
        "decision_draft": (
            {
                "plan_id": latest.id,
                "plan_bn": latest.plan_bn,
                "plan_version": latest.plan_version,
                "plan_status": latest.plan_status,
                "exec_status": latest.exec_status,
                "warehouse_alloc": latest.warehouse_alloc,
                "split_matrix": latest.split_matrix,
                "logistics_alloc": latest.logistics_alloc,
            }
            if latest
            else None
        ),
        "task": (
            {
                "task_id": task.id,
                "task_status": task.task_status,
                "assign_group": task.assign_group,
                "assign_op": task.assign_op,
                "lock_op": task.lock_op,
                "lock_expire": str(task.lock_expire) if task.lock_expire else None,
                "sla_deadline": str(task.sla_deadline) if task.sla_deadline else None,
            }
            if task
            else None
        ),
    })


@router.post("/audit/workbench/orders/{order_id}/pass", summary="审核通过（人工 plan 同源执行）")
async def workbench_pass(
    order_id: int,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
):
    """FR-03c：提交人工 plan → D03.02 executeManualPlan 同源执行"""
    redis = await get_redis()
    operator = str(payload.get("operator", "") or "")
    if not operator:
        from app.core.exceptions import ValidationError

        raise ValidationError("缺少操作人（operator）")
    ex = PlanExecutor(session, redis)
    decision = {
        "branch": payload.get("branch"),
        "split_groups": payload.get("split_groups"),
        "logistics": payload.get("logistics"),
    }
    result = await ex.execute_manual_plan(
        order_id, decision, operator, plan_id=payload.get("plan_id")
    )
    # 埋点（FR-07b：绩效统计源）—— task_id/op_id 为 NOT NULL，取任务与操作人
    order = await session.scalar(
        select(OrdOrder).where(OrdOrder.id == order_id, OrdOrder.is_deleted == 0)
    )
    task = await session.scalar(
        select(OrdAuditTask)
        .where(OrdAuditTask.order_id == order_id, OrdAuditTask.is_active == 1)
        .limit(1)
    )
    session.add(
        OrdAuditWorkLog(
            owner_id=order.owner_id if order is not None else 0,
            task_id=task.id if task is not None else 0,
            order_id=order_id,
            op_id=int(payload.get("op_id", 0) or 0) or (task.assign_op if task else 0) or 0,
            action="pass",
            memo=f"人工审核通过（plan={result.plan_bn}）",
        )
    )
    await session.commit()
    return ok(result.to_dict())


@router.post("/audit/workbench/orders/{order_id}/reject", summary="驳回（原因必填）")
async def workbench_reject(
    order_id: int,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
):
    """FR-05a：驳回原因必填（结构化字典 + 备注）；audit_status=驳回"""
    from app.core.exceptions import ValidationError

    reason_code = str(payload.get("reason_code", "") or "")
    if not reason_code:
        raise ValidationError("驳回原因必填")
    order = await session.scalar(
        select(OrdOrder).where(OrdOrder.id == order_id, OrdOrder.is_deleted == 0)
    )
    if order is None:
        from app.core.exceptions import NotFoundError

        raise NotFoundError(f"订单不存在: {order_id}")
    order.audit_status = "rejected"
    # 原因标记已处理
    for r in await session.scalars(
        select(OrdAuditReason).where(OrdAuditReason.order_id == order_id)
    ):
        r.handle_status = "handled"
        r.handle_way = reason_code
    # 任务置终态
    task = await session.scalar(
        select(OrdAuditTask)
        .where(OrdAuditTask.order_id == order_id, OrdAuditTask.is_active == 1)
        .limit(1)
    )
    if task is not None:
        task.task_status = "rejected"
        task.result = "reject"
        task.result_reason_code = reason_code
        task.is_active = 0
    session.add(
        OrdAuditWorkLog(
            owner_id=order.owner_id,
            task_id=task.id if task is not None else 0,
            order_id=order_id,
            op_id=int(payload.get("op_id", 0) or 0) or (task.assign_op if task else 0) or 0,
            action="reject",
            memo=reason_code,
        )
    )
    await session.commit()
    return ok({"order_id": order_id, "audit_status": "rejected", "reason_code": reason_code})


# ============ 分派（D03.03 FR-02）============

@router.get("/audit/workbench/groups", summary="审核组列表")
async def list_groups(session: AsyncSession = Depends(get_session)):
    rows = list(
        await session.scalars(
            select(OrdAuditGroup)
            .where(OrdAuditGroup.is_deleted == 0, OrdAuditGroup.status == "enabled")
            .order_by(OrdAuditGroup.id)
        )
    )
    return ok([
        {
            "id": g.id,
            "group_name": g.group_name,
            "org_id": g.org_id,
            "leader_op_id": g.leader_op_id,
            "members": g.members,
            "default_shop_scope": g.default_shop_scope,
            "status": g.status,
        }
        for g in rows
    ])


@router.get("/audit/workbench/dispatch-rules", summary="分派规则列表")
async def list_dispatch_rules(session: AsyncSession = Depends(get_session)):
    rows = list(
        await session.scalars(
            select(OrdDispatchRule)
            .where(OrdDispatchRule.is_deleted == 0, OrdDispatchRule.status == "enabled")
            .order_by(OrdDispatchRule.weight.desc(), OrdDispatchRule.id.asc())
        )
    )
    return ok([
        {
            "id": r.id,
            "rule_name": r.rule_name,
            "conditions": r.conditions,
            "weight": r.weight,
            "target_group_id": r.target_group_id,
            "target_op_id": r.target_op_id,
            "strategy": r.strategy,
            "filter_on_duty": r.filter_on_duty,
            "status": r.status,
        }
        for r in rows
    ])


@router.post("/audit/workbench/dispatch", summary="自动分派（规则匹配 + 负载均衡）")
async def auto_dispatch(
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
):
    """IF-D03.03-01：自动分派；幂等（已分派跳过）"""
    redis = await get_redis()
    svc = DispatchService(session, redis)
    result = await svc.auto(
        int(payload.get("order_id", 0) or 0),
        list(payload.get("reason_codes", []) or []),
    )
    return ok(result)
