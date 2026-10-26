"""异常单扩展域 API（W9-2 · SRS-D03.09 FR-05b/FR-06/FR-07/FR-08c）"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.response import ok

router = APIRouter()


# ============ 超卖应急批次（FR-05b~05e）============


class BatchAggregateIn(BaseModel):
    """超卖单聚合入参"""

    shop_id: int = Field(ge=0)
    bm_id: int = Field(ge=0)
    owner_id: int = Field(ge=0)
    abnormal_ids: list[int] = Field(min_length=1)


@router.post("/abnormal/batch/aggregate", summary="超卖单聚合为应急批次（FR-05b）")
async def aggregate_batch(body: BatchAggregateIn, session: AsyncSession = Depends(get_session)):
    """同店铺同 SKU 的超卖单聚合为应急批次（批次级统一决策）"""
    from app.modules.m5_abnormal.service.abnormal_ext import AbnormalExtService

    svc = AbnormalExtService(session, None)
    row = await svc.aggregate_oversold_batch(
        shop_id=body.shop_id,
        bm_id=body.bm_id,
        owner_id=body.owner_id,
        abnormal_ids=body.abnormal_ids,
    )
    return ok(
        {
            "batch_id": row.id,
            "batch_bn": row.batch_bn,
            "stage": row.stage,
            "total_orders": row.total_orders,
        }
    )


@router.post("/abnormal/batch/{batch_id}/advance", summary="批次阶段推进（FR-05c）")
async def advance_batch(
    batch_id: int,
    to_stage: str = Query(..., max_length=16),
    operator: str = Query(default="api", max_length=64),
    session: AsyncSession = Depends(get_session),
):
    """按 §5.1 阶段顺序推进（不可跳阶段、不可回退）"""
    from app.modules.m5_abnormal.service.abnormal_ext import AbnormalExtService

    svc = AbnormalExtService(session, None)
    row = await svc.advance_batch(batch_id, to_stage, operator=operator)
    return ok({"batch_id": row.id, "stage": row.stage})


@router.get("/abnormal/batch/{batch_id}/sla", summary="批次 SLA 状态（FR-05c）")
async def batch_sla(batch_id: int, session: AsyncSession = Depends(get_session)):
    """分级 SLA：各阶段到达时间 / 截止 / 剩余小时 / 是否超期"""
    from app.modules.m5_abnormal.service.abnormal_ext import AbnormalExtService

    svc = AbnormalExtService(session, None)
    return ok(await svc.batch_sla_status(batch_id))


@router.post("/abnormal/batch/{batch_id}/promo-mode", summary="大促模式开关（FR-05d）")
async def set_promo(
    batch_id: int,
    promo: bool = Query(...),
    operator: str = Query(default="api", max_length=64),
    session: AsyncSession = Depends(get_session),
):
    """大促模式：SLA 收紧（T+4h→T+2h）+ 告警升级"""
    from app.modules.m5_abnormal.service.abnormal_ext import AbnormalExtService

    svc = AbnormalExtService(session, None)
    row = await svc.set_promo_mode(batch_id, promo=promo, operator=operator)
    return ok({"batch_id": row.id, "promo_mode": row.promo_mode})


@router.post("/abnormal/batch/{batch_id}/compensation", summary="赔付登记（FR-05e）")
async def register_compensation(
    batch_id: int,
    body: dict,
    session: AsyncSession = Depends(get_session),
):
    """赔付登记（平台罚金 / 补偿券 / 运费）"""
    from app.modules.m5_abnormal.service.abnormal_ext import AbnormalExtService

    svc = AbnormalExtService(session, None)
    row = await svc.register_compensation(
        batch_id,
        order_id=int(body.get("order_id") or 0),
        comp_type=str(body.get("type") or ""),
        amount=float(body.get("amount") or 0),
        liability=str(body.get("liability") or ""),
        oa_approval_id=str(body.get("oa_approval_id") or ""),
    )
    return ok({"batch_id": row.id, "compensation": row.compensation})


@router.post("/abnormal/batch/{batch_id}/close", summary="批次关闭复盘（FR-05e）")
async def close_batch(batch_id: int, session: AsyncSession = Depends(get_session)):
    """生成复盘摘要：单量 / 解决路径分布 / 平均解决时长 / 赔付金额"""
    from app.modules.m5_abnormal.service.abnormal_ext import AbnormalExtService

    svc = AbnormalExtService(session, None)
    return ok(await svc.close_batch_review(batch_id))


# ============ 订单暂停编排（FR-06）============


@router.post("/abnormal/order/{order_id}/pause", summary="订单暂停编排（FR-06a/06b）")
async def pause_order(
    order_id: int,
    body: dict,
    session: AsyncSession = Depends(get_session),
):
    """订单暂停：逐发货单分布式动作（WMS 侧暂停报文待实现 → pending）"""
    from app.modules.m5_abnormal.service.abnormal_ext import AbnormalExtService

    svc = AbnormalExtService(session, None)
    return ok(
        await svc.pause_order(
            order_id,
            reason=str(body.get("reason") or ""),
            abnormal_id=int(body.get("abnormal_id") or 0) or None,
            operator=str(body.get("operator") or "api"),
        )
    )


@router.post("/abnormal/order/{order_id}/resume", summary="订单恢复编排（FR-06c）")
async def resume_order(
    order_id: int,
    operator: str = Query(default="api", max_length=64),
    session: AsyncSession = Depends(get_session),
):
    """订单恢复：任一发货单失败 → 保持暂停（不半恢复）"""
    from app.modules.m5_abnormal.service.abnormal_ext import AbnormalExtService

    svc = AbnormalExtService(session, None)
    return ok(await svc.resume_order(order_id, operator=operator))


@router.get("/abnormal/order/{order_id}/pause-logs", summary="暂停命令日志")
async def pause_logs(order_id: int, session: AsyncSession = Depends(get_session)):
    """逐发货单的暂停/恢复命令留痕"""
    from app.modules.m5_abnormal.service.abnormal_ext import AbnormalExtService

    svc = AbnormalExtService(session, None)
    items = await svc.list_pause_logs(order_id)
    return ok({"items": items, "total": len(items)})


# ============ 名单服务（FR-07）============


class RiskListIn(BaseModel):
    """名单维护入参（FR-07b）"""

    list_type: str = Field(pattern="^(black|gray|white)$")
    dimension: str = Field(pattern="^(mobile|address|account|name)$")
    match_value: str = Field(min_length=1, max_length=256)
    scope: str = Field(default="tenant", pattern="^(global|tenant|owner)$")
    owner_id: int | None = Field(default=None)
    value_type: str = Field(default="plain", pattern="^(plain|hash)$")
    reason: str = Field(default="", max_length=256)
    source: str = Field(default="manual", max_length=32)
    oa_approval_id: str = Field(default="", max_length=64)
    effective_hours: int = Field(default=0, ge=0)


@router.post("/abnormal/risk-list", summary="加入名单（FR-07b）")
async def add_risk_list(body: RiskListIn, session: AsyncSession = Depends(get_session)):
    """加入名单（加/移黑名单必须带 OA 审批单号）"""
    from app.modules.m5_abnormal.service.abnormal_ext import AbnormalExtService

    svc = AbnormalExtService(session, None)
    row = await svc.add_to_list(
        list_type=body.list_type,
        dimension=body.dimension,
        match_value=body.match_value,
        scope=body.scope,
        owner_id=body.owner_id,
        value_type=body.value_type,
        reason=body.reason,
        source=body.source,
        oa_approval_id=body.oa_approval_id,
        effective_hours=body.effective_hours,
    )
    return ok({"id": row.id, "list_type": row.list_type, "scope": row.scope})


@router.delete("/abnormal/risk-list/{list_id}", summary="移出名单（FR-07b）")
async def remove_risk_list(
    list_id: int,
    oa_approval_id: str = Query(default="", max_length=64),
    operator: str = Query(default="api", max_length=64),
    session: AsyncSession = Depends(get_session),
):
    """移出名单（移出黑名单同样须 OA 审批）"""
    from app.modules.m5_abnormal.service.abnormal_ext import AbnormalExtService

    svc = AbnormalExtService(session, None)
    await svc.remove_from_list(list_id, oa_approval_id=oa_approval_id, operator=operator)
    return ok({"id": list_id, "removed": True})


@router.get("/abnormal/risk-list/list", summary="名单列表")
async def list_risk_list(
    list_type: str | None = Query(default=None, pattern="^(black|gray|white)$"),
    dimension: str | None = Query(default=None),
    scope: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    """名单维护视图"""
    from app.modules.m5_abnormal.service.abnormal_ext import AbnormalExtService

    svc = AbnormalExtService(session, None)
    items = await svc.list_entries(
        list_type=list_type, dimension=dimension, scope=scope, limit=limit
    )
    return ok({"items": items, "total": len(items)})


@router.get("/abnormal/risk-list/match", summary="名单命中判定（FR-07c/07d）")
async def match_risk_list(
    dimension: str = Query(..., pattern="^(mobile|address|account|name)$"),
    match_value: str = Query(..., min_length=1, max_length=256),
    owner_id: int | None = Query(default=None),
    list_type: str | None = Query(default=None, pattern="^(black|gray|white)$"),
    session: AsyncSession = Depends(get_session),
):
    """命中判定：私有优先（货主 > 租户 > 全局）；返回命中动作"""
    from app.modules.m5_abnormal.service.abnormal_ext import AbnormalExtService

    svc = AbnormalExtService(session, None)
    return ok(
        await svc.match_list(
            dimension=dimension,
            match_value=match_value,
            owner_id=owner_id,
            list_type=list_type,
        )
    )


# ============ 告警扫描（FR-08c）============


@router.get("/abnormal/alerts/scan", summary="异常单告警扫描（FR-08c）")
async def scan_alerts(session: AsyncSession = Depends(get_session)):
    """类型级超期 + 数量突增 → 告警待发清单（企微推送 D01.07 未实现 → pending）"""
    from app.modules.m5_abnormal.service.abnormal_ext import AbnormalExtService

    svc = AbnormalExtService(session, None)
    return ok(await svc.scan_alerts())
