"""售后服务 API（D05 售后申请 + 仅退款与退款单 · W9-1）"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.response import ok

router = APIRouter()


class ApplyItemIn(BaseModel):
    """申请行（FR-02f：行级部分售后）"""

    order_item_id: int = Field(gt=0)
    apply_num: int = Field(gt=0)
    apply_amount_customer_line: float = Field(default=0, ge=0)
    apply_amount_platform_bear_line: float = Field(default=0, ge=0)


class ApplyCreateIn(BaseModel):
    """售后申请创建（FR-01d/02a/03a）"""

    aftersale_type: int = Field(ge=1, le=4, description="1=仅退款 2=退货退款 3=换货 4=补发")
    platform: str = Field(default="", max_length=16)
    shop_id: int = Field(default=0, ge=0)
    platform_aftersale_bn: str = Field(default="", max_length=64)
    platform_order_bn: str = Field(default="", max_length=64)
    order_id: int = Field(default=0, ge=0)
    items: list[ApplyItemIn] = Field(default_factory=list)
    reason_code: str = Field(default="", max_length=32)
    reason_raw: str = Field(default="", max_length=512)
    buyer_claim: str = Field(default="", max_length=1024)
    apply_amount_customer: float = Field(default=0, ge=0)
    apply_amount_platform_bear: float = Field(default=0, ge=0)
    source: str = Field(default="platform", max_length=16)
    operator: str = Field(default="", max_length=64)
    goods_status: int = Field(default=0, ge=0, le=2)


class AuditIn(BaseModel):
    """审核（FR-02e）"""

    agree: bool
    operator: str = Field(min_length=1, max_length=64)
    audit_channel: int = Field(default=1, ge=1, le=3)
    reject_reason_code: str = Field(default="", max_length=32)
    approved_amount_customer: float | None = Field(default=None, ge=0)
    approved_amount_platform_bear: float | None = Field(default=None, ge=0)


class RefundTransitIn(BaseModel):
    """退款单状态推进（D05.03 FR-02）"""

    to_status: int = Field(ge=1, le=6)
    operator: str = Field(default="system", max_length=64)
    fail_reason_code: str = Field(default="", max_length=32)
    platform_refund_no: str = Field(default="", max_length=64)


@router.post("/aftersale/apply", summary="创建售后申请单（D05.01 FR-02a）")
async def create_apply(body: ApplyCreateIn, session: AsyncSession = Depends(get_session)):
    """创建售后申请单

    - 平台单按 `(platform, shop_id, platform_aftersale_bn)` **幂等**（FR-01b）
    - 订单缺失 → 落「待关联」异常态（FR-01e）
    - 手工单须填 operator（FR-03a）
    """
    from app.modules.m6_aftersale.service.aftersale import AftersaleService

    svc = AftersaleService(session, None)
    row, created = await svc.create_apply(
        aftersale_type=body.aftersale_type,
        platform=body.platform,
        shop_id=body.shop_id,
        platform_aftersale_bn=body.platform_aftersale_bn,
        platform_order_bn=body.platform_order_bn,
        order_id=body.order_id,
        items=[i.model_dump() for i in body.items],
        reason_code=body.reason_code,
        reason_raw=body.reason_raw,
        buyer_claim=body.buyer_claim,
        apply_amount_customer=body.apply_amount_customer,
        apply_amount_platform_bear=body.apply_amount_platform_bear,
        source=body.source,
        operator=body.operator,
        goods_status=body.goods_status,
    )
    return ok({"id": row.id, "apply_bn": row.apply_bn, "status": row.status, "created": created})


@router.get("/aftersale/apply/list", summary="售后申请列表（工作台队列）")
async def list_applies(
    status: int | None = Query(default=None, ge=0, le=9),
    aftersale_type: int | None = Query(default=None, ge=1, le=4),
    order_id: int | None = Query(default=None, gt=0),
    shop_id: int | None = Query(default=None, ge=0),
    only_open: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """售后申请列表（FR-07a 工作台队列用）"""
    from app.modules.m6_aftersale.service.aftersale import AftersaleService

    svc = AftersaleService(session, None)
    items = await svc.list_applies(
        status=status,
        aftersale_type=aftersale_type,
        order_id=order_id,
        shop_id=shop_id,
        only_open=only_open,
        limit=limit,
    )
    return ok({"items": items, "total": len(items)})


@router.get("/aftersale/apply/{apply_id}", summary="售后申请详情")
async def get_apply(apply_id: int, session: AsyncSession = Depends(get_session)):
    """售后申请详情：行 + 状态变迁日志 + 关联退款单"""
    from app.modules.m6_aftersale.service.aftersale import AftersaleService

    svc = AftersaleService(session, None)
    return ok(await svc.get_apply(apply_id))


@router.post("/aftersale/apply/{apply_id}/audit", summary="售后审核（D05.01 FR-02e）")
async def audit_apply(
    apply_id: int, body: AuditIn, session: AsyncSession = Depends(get_session)
):
    """审核：同意 → 状态推进 + 涉钱类型生成退款单；拒绝 → 记录原因码"""
    from app.modules.m6_aftersale.service.aftersale import AftersaleService

    svc = AftersaleService(session, None)
    return ok(
        await svc.audit(
            apply_id,
            agree=body.agree,
            operator=body.operator,
            audit_channel=body.audit_channel,
            reject_reason_code=body.reject_reason_code,
            approved_amount_customer=body.approved_amount_customer,
            approved_amount_platform_bear=body.approved_amount_platform_bear,
        )
    )


@router.post("/aftersale/apply/{apply_id}/transit", summary="售后单状态推进（FR-02c）")
async def transit_apply(
    apply_id: int,
    to_status: int = Query(..., ge=0, le=9),
    operator: str = Query(default="api", max_length=64),
    session: AsyncSession = Depends(get_session),
):
    """状态推进唯一入口（FR-02c）：校验 §5.1 流转表 + 类型裁剪"""
    from app.modules.m6_aftersale.service.aftersale import AftersaleService

    svc = AftersaleService(session, None)
    row = await svc.transit(apply_id, to_status, operator=operator)
    return ok({"id": row.id, "status": row.status})


@router.post("/aftersale/refund/{refund_id}/transit", summary="退款单状态推进（D05.03 FR-02）")
async def transit_refund(
    refund_id: int, body: RefundTransitIn, session: AsyncSession = Depends(get_session)
):
    """退款单推进：待退款→退款中→已退款；失败可重试"""
    from app.modules.m6_aftersale.service.aftersale import AftersaleService

    svc = AftersaleService(session, None)
    row = await svc.refund_transit(
        refund_id,
        body.to_status,
        operator=body.operator,
        fail_reason_code=body.fail_reason_code,
        platform_refund_no=body.platform_refund_no,
    )
    return ok({"id": row.id, "status": row.status, "refund_bn": row.refund_bn})


@router.get("/aftersale/refund/list", summary="退款单列表")
async def list_refunds(
    apply_id: int | None = Query(default=None, gt=0),
    order_id: int | None = Query(default=None, gt=0),
    status: int | None = Query(default=None, ge=1, le=6),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """退款单列表"""
    from sqlalchemy import select

    from app.models.aftersale import AftRefund

    q = select(AftRefund)
    if apply_id:
        q = q.where(AftRefund.apply_id == apply_id)
    if order_id:
        q = q.where(AftRefund.order_id == order_id)
    if status:
        q = q.where(AftRefund.status == status)
    rows = list(await session.scalars(q.order_by(AftRefund.id.desc()).limit(limit)))
    from app.modules.m6_aftersale.service.aftersale import REFUND_STATUS_LABEL

    items = [
        {
            "id": r.id,
            "refund_bn": r.refund_bn,
            "apply_id": r.apply_id,
            "order_id": r.order_id,
            "order_bn": r.order_bn,
            "status": r.status,
            "status_name": REFUND_STATUS_LABEL.get(r.status, str(r.status)),
            "channel": r.channel,
            "refund_customer": float(r.refund_customer or 0),
            "refund_platform_bear": float(r.refund_platform_bear or 0),
            "platform_refund_no": r.platform_refund_no,
            "fail_reason_code": r.fail_reason_code,
            "create_time": r.create_time.strftime("%Y-%m-%d %H:%M:%S")
            if r.create_time
            else None,
        }
        for r in rows
    ]
    return ok({"items": items, "total": len(items)})
