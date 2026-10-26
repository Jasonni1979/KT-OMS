"""W6 履约 API（D03.06 分仓 + D03.04 拆单 + D03.07 发货单）

- /dispatch/*：分仓（方案 / 满足度视图 / 换仓重试 / 手工改仓 / 规则）
- /split/*：拆单（规则 / 执行 / 手工拆 / 轨迹）
- /delivery/*：发货单（列表 / 详情 / 四指令 / 回传 / 异常视图）
"""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.exceptions import ValidationError
from app.core.response import ok
from app.models.fulfill import OrdBranchDispatchRule
from app.modules.m1_master.contract import get_redis
from app.modules.m4_fulfill.contract import DeliveryService, SplitRuleService, SplitService, allowed_commands
from app.modules.m4_fulfill.contract import DispatchService_dispatch_service as DispatchService

router = APIRouter()


async def _redis():
    return await get_redis()


# ==================== D03.06 配货分仓 ====================


@router.post("/dispatch/orders/{order_id}", summary="分仓（产出 plan）")
async def dispatch_order(
    order_id: int,
    source: str = Query(default="auto", max_length=16),
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """分仓主入口（IF-D03.06-01）

    返回 plan（含满足度快照/缺货明细/规则命中）；缺货时 ok=false + 缺口明细。
    """
    svc = DispatchService(session, redis)
    res = await svc.dispatch(order_id, source=source)
    return ok(res.to_dict())


@router.get("/dispatch/orders/{order_id}/view", summary="满足度视图（建议仓+各仓库存）")
async def dispatch_view(
    order_id: int,
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """人工审单界面数据源（IF-D03.06-04）"""
    svc = DispatchService(session, redis)
    return ok(await svc.get_fulfill_view(order_id))


@router.post("/dispatch/orders/{order_id}/retry", summary="换仓重试（排除已试仓重算）")
async def dispatch_retry(
    order_id: int,
    exclude_branches: list[int] = Query(default_factory=list),
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """换仓重试（IF-D03.06-02 / FR-04b-1）"""
    svc = DispatchService(session, redis)
    res = await svc.retry_with_gap(order_id, [], exclude_branches)
    return ok(res.to_dict())


@router.post("/dispatch/orders/{order_id}/change-branch", summary="手工改仓（敏感操作审计）")
async def change_branch(
    order_id: int,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """手工改仓（IF-D03.06-03 / FR-06b/c/d）

    校验：新仓满足度足够（不足需 forced）、货主仓属允许、原因必填。
    """
    new_branch = int(payload.get("new_branch_id", 0) or 0)
    reason = str(payload.get("reason", "") or "")
    operator = str(payload.get("operator", "") or "")
    forced = bool(payload.get("forced", False))
    if new_branch <= 0:
        raise ValidationError("新仓必填")
    if not reason:
        raise ValidationError("改仓原因必填")
    svc = DispatchService(session, redis)
    res = await svc.change_branch(
        order_id, new_branch, reason, operator or "system", forced=forced
    )
    return ok(res.to_dict())


@router.get("/dispatch/rules", summary="分仓规则列表")
async def list_dispatch_rules(
    session: AsyncSession = Depends(get_session),
):
    rows = list(
        await session.scalars(
            select(OrdBranchDispatchRule)
            .where(OrdBranchDispatchRule.is_deleted == 0)
            .order_by(OrdBranchDispatchRule.weight.desc(), OrdBranchDispatchRule.id)
        )
    )
    return ok(
        [
            {
                "id": r.id,
                "rule_name": r.rule_name,
                "conditions": r.conditions,
                "strategy_type": r.strategy_type,
                "branch_seq": r.branch_seq,
                "weight": r.weight,
                "effective_period": r.effective_period,
                "exclude_period": r.exclude_period,
                "default_flag": r.default_flag,
                "status": r.status,
            }
            for r in rows
        ]
    )


# ==================== D03.04 拆单 ====================


@router.get("/split/rules", summary="拆单规则列表")
async def list_split_rules(
    session: AsyncSession = Depends(get_session),
):
    svc = SplitRuleService(session)
    return ok(await svc.list_rules())


@router.post("/split/rules", summary="保存拆单规则（保存期校验）")
async def save_split_rule(
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
):
    """保存规则（FR-01c：策略 schema 校验 + 级联类型不重复 + 兼容清单）"""
    svc = SplitRuleService(session)
    return ok(await svc.save(payload))


@router.put("/split/rules/{rule_id}", summary="修改拆单规则")
async def update_split_rule(
    rule_id: int,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
):
    svc = SplitRuleService(session)
    data = {**payload, "id": rule_id}
    return ok(await svc.save(data))


@router.delete("/split/rules/{rule_id}", summary="停用拆单规则")
async def disable_split_rule(
    rule_id: int,
    session: AsyncSession = Depends(get_session),
):
    svc = SplitRuleService(session)
    await svc.disable(rule_id)
    return ok({"id": rule_id, "status": "disabled"})


@router.get("/split/strategies", summary="策略注册表（可插拔能力自描述）")
async def list_split_strategies(
    session: AsyncSession = Depends(get_session),
):
    """策略注册表 describe（FR-01b/AC-14：新增策略零引擎改动即可被引用）"""
    svc = SplitRuleService(session)
    return ok(svc.registry.describe_all())


@router.post("/split/orders/{order_id}", summary="执行拆单（产出分配方案）")
async def split_order(
    order_id: int,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """拆单统一入口（IF-D03.04-01）

    幂等键=(order_id, split_rule_id, 触发轮次)；失败返回结构化错误码。
    """
    rule_id = int(payload.get("split_rule_id", 0) or 0)
    if rule_id <= 0:
        raise ValidationError("split_rule_id 必填")
    context = dict(payload.get("context") or {})
    source = str(payload.get("source", "auto") or "auto")
    operator = str(payload.get("operator", "") or "system")
    svc = SplitService(session, redis)
    res = await svc.split(order_id, rule_id, context, source=source, operator=operator)
    return ok(res.to_dict())


@router.post("/split/orders/{order_id}/manual", summary="手工拆单（人工介入）")
async def manual_split(
    order_id: int,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """手工拆单（IF-D03.04-02 / FR-07）

    校验：各组数量之和 ≤ 未拆余量；组内货主唯一。
    """
    groups = payload.get("groups") or []
    if not groups:
        raise ValidationError("分组不能为空")
    operator = str(payload.get("operator", "") or "system")
    svc = SplitService(session, redis)
    res = await svc.manual_split(order_id, groups, operator)
    return ok(res.to_dict())


@router.get("/split/orders/{order_id}/trace", summary="拆单轨迹（历史时间线）")
async def split_trace(
    order_id: int,
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """拆单历史（IF-D03.04-06 / FR-08b）"""
    svc = SplitService(session, redis)
    return ok(await svc.query_trace(order_id))


# ==================== D03.07 发货单 ====================


@router.get("/delivery/list", summary="发货单列表（多维筛选）")
async def list_deliveries(
    status: str | None = Query(default=None, max_length=20),
    branch_id: int | None = Query(default=None),
    shop_id: int | None = Query(default=None),
    order_id: int | None = Query(default=None),
    keyword: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """发货单列表（FR-10a；行级过滤自动生效）"""
    svc = DeliveryService(session, redis)
    return ok(
        await svc.list_deliveries(
            status=status,
            branch_id=branch_id,
            shop_id=shop_id,
            order_id=order_id,
            keyword=keyword,
            limit=limit,
        )
    )


@router.get("/delivery/states", summary="状态机字典（状态 + 允许指令）")
async def delivery_states():
    """状态枚举与各状态允许指令（前端渲染按钮用）"""
    from app.modules.m4_fulfill.contract import FINAL_STATES, TRANSITIONS

    # ⚠ 原本用 `vars(ds)` 动态枚举模块里的 ST_* 常量 —— P2 收口后不再持有
    #   service 模块对象（跨模块只能走 contract.py）→ 改用契约里的流转表推导：
    #   全部状态 = 流转表出现的 from/to 状态 ∪ 终态集合
    states = sorted(
        {t.from_status for t in TRANSITIONS}
        | {t.to_status for t in TRANSITIONS}
        | set(FINAL_STATES)
    )
    return ok(
        {
            "states": sorted(set(states)),
            "commands": sorted({t.command for t in TRANSITIONS}),
            "allowed": {s: allowed_commands(s) for s in sorted(set(states))},
            "final_states": sorted(FINAL_STATES),
        }
    )


@router.get("/delivery/abnormal/list", summary="发货单异常视图")
async def delivery_abnormal(
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """异常队列（FR-10b：推送失败/叫回失败/回传超时/尾差超期/差异登记）"""
    svc = DeliveryService(session, redis)
    return ok(await svc.abnormal_list())
@router.get("/delivery/{delivery_id}", summary="发货单详情（含行/溯源/包裹/日志/差异）")
async def delivery_detail(
    delivery_id: int,
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """发货单详情（FR-10a/c：多向钻取）"""
    svc = DeliveryService(session, redis)
    return ok(await svc.get_detail(delivery_id))


@router.post("/delivery/{delivery_id}/push", summary="推送指令")
async def delivery_push(
    delivery_id: int,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """推送指令（draft/recalled → pushed）"""
    svc = DeliveryService(session, redis)
    res = await svc.push(
        delivery_id,
        operator=str(payload.get("operator", "") or "system"),
        reason=str(payload.get("reason", "") or ""),
    )
    return ok(res.to_dict())


@router.post("/delivery/{delivery_id}/recall", summary="叫回指令")
async def delivery_recall(
    delivery_id: int,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """叫回指令（pushed/processing → recalling → recalled）"""
    svc = DeliveryService(session, redis)
    res = await svc.recall(
        [delivery_id],
        operator=str(payload.get("operator", "") or "system"),
        reason=str(payload.get("reason", "") or ""),
        ref_id=str(payload.get("ref_id", "") or ""),
    )
    return ok(res[0].to_dict() if res else {})


@router.post("/delivery/{delivery_id}/recall-result", summary="叫回结果回传")
async def delivery_recall_result(
    delivery_id: int,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """WMS 叫回结果回传（成功→recalled / 失败→回原态）"""
    svc = DeliveryService(session, redis)
    res = await svc.recall_result(
        delivery_id,
        success=bool(payload.get("success", False)),
        operator=str(payload.get("operator", "") or "wms"),
        reason=str(payload.get("reason", "") or ""),
    )
    return ok(res.to_dict())


@router.post("/delivery/{delivery_id}/resume", summary="恢复指令")
async def delivery_resume(
    delivery_id: int,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """恢复指令（recalled → pushed；恢复前复核）"""
    svc = DeliveryService(session, redis)
    res = await svc.resume(
        delivery_id,
        operator=str(payload.get("operator", "") or "system"),
        reason=str(payload.get("reason", "") or ""),
    )
    return ok(res.to_dict())


@router.post("/delivery/{delivery_id}/confirm", summary="确认指令（发货确认）")
async def delivery_confirm(
    delivery_id: int,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """确认指令（outbound → shipped + 订单 ship_status 联动）"""
    svc = DeliveryService(session, redis)
    res = await svc.confirm(
        delivery_id,
        operator=str(payload.get("operator", "") or "system"),
        reason=str(payload.get("reason", "") or ""),
    )
    return ok(res.to_dict())


@router.post("/delivery/{delivery_id}/cancel", summary="取消发货单")
async def delivery_cancel(
    delivery_id: int,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """取消（原子编排：状态 + 预占释放 + split_num 回退）"""
    svc = DeliveryService(session, redis)
    res = await svc.cancel(
        delivery_id,
        reason=str(payload.get("reason", "") or ""),
        operator=str(payload.get("operator", "") or "system"),
    )
    return ok(res.to_dict())


@router.post("/delivery/{delivery_id}/reject", summary="WMS 打回")
async def delivery_reject(
    delivery_id: int,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """打回（结构化原因 + split_num 回退 + 订单回审单池）"""
    svc = DeliveryService(session, redis)
    res = await svc.reject(
        delivery_id,
        reason=str(payload.get("reason", "") or ""),
        operator=str(payload.get("operator", "") or "wms"),
    )
    return ok(res.to_dict())


@router.post("/delivery/{delivery_id}/callback", summary="出库回传处理（行匹配→settle→差异→包裹→确认）")
async def delivery_callback(
    delivery_id: int,
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """出库回传（IF-D03.07-D1 事件入口；幂等键=delivery_id+batch_no）"""
    svc = DeliveryService(session, redis)
    res = await svc.handle_callback(delivery_id, payload)
    return ok(res.to_dict())


