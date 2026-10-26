"""订单接入 API（D02 拉单 / D03 订单查询）

- /pull/*：拉单触发（轮询 / 单拉补偿 / 水位）
- /orders/*：订单查询（列表 / 详情 / 行 / 收货人脱敏 / 优惠分摊 / 失败单）
- /gateway/logs：api_log 调用留痕
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.pipl import mask_mobile, mask_name
from app.core.response import ok
from app.models.gateway import GwApiLog, GwOrderBuffer
from app.models.order import OrdOrder, OrdOrderFail, OrdOrderItem, OrdOrderPmt, OrdReceiver
from app.modules.m1_master.contract import get_redis
from app.modules.m7_integration.contract import PullService, get_gateway
from app.schemas import order as sc

router = APIRouter()


async def _pull_svc(session: AsyncSession) -> PullService:
    redis = await get_redis()
    gw = get_gateway(redis)
    return PullService(session, gw, redis)


@router.post("/pull/shop/{shop_id}/poll", summary="触发店铺轮询拉单（D02.03 FR-02）")
async def poll_shop(shop_id: int, session: AsyncSession = Depends(get_session)):
    svc = await _pull_svc(session)
    stat = await svc.poll_shop(shop_id)
    return ok(sc.PullStatOut(**{k: v for k, v in stat.items() if k != "window_start"}))


@router.post("/pull/single", summary="单拉补偿（D02.03 FR-03a）")
async def pull_single(
    shop_id: int = Query(gt=0),
    platform_order_bn: str = Query(min_length=1, max_length=64),
    reason: str = Query(default="manual", max_length=32),
    session: AsyncSession = Depends(get_session),
):
    svc = await _pull_svc(session)
    res = await svc.pull_single(shop_id, platform_order_bn, reason)
    return ok(sc.PullSingleOut(**res))


@router.get("/pull/watermark/{shop_id}", summary="查拉单水位")
async def get_watermark(shop_id: int, session: AsyncSession = Depends(get_session)):
    svc = await _pull_svc(session)
    wm = await svc.get_watermark(shop_id)
    return ok(sc.WatermarkOut.model_validate(wm))


@router.get("/pull/buffer", summary="订单缓冲池列表（D02.03 §6.1）")
async def list_buffer(
    shop_id: int | None = Query(default=None, ge=1),
    deliver_status: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    q = select(GwOrderBuffer).where(GwOrderBuffer.is_deleted == 0)
    if shop_id:
        q = q.where(GwOrderBuffer.shop_id == shop_id)
    if deliver_status:
        q = q.where(GwOrderBuffer.deliver_status == deliver_status)
    rows = await session.scalars(q.order_by(GwOrderBuffer.id.desc()).limit(limit))
    return ok([sc.BufferItemOut.model_validate(r) for r in list(rows)])


@router.get("/orders", summary="订单列表（D03.01 FR-10）")
async def list_orders(
    shop_id: int | None = Query(default=None, ge=1),
    platform_order_bn: str | None = Query(default=None, max_length=64),
    audit_status: str | None = Query(default=None, max_length=16),
    pay_status: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    q = select(OrdOrder).where(OrdOrder.is_deleted == 0)
    if shop_id:
        q = q.where(OrdOrder.shop_id == shop_id)
    if platform_order_bn:
        q = q.where(OrdOrder.platform_order_bn == platform_order_bn)
    if audit_status:
        q = q.where(OrdOrder.audit_status == audit_status)
    if pay_status:
        q = q.where(OrdOrder.pay_status == pay_status)
    rows = await session.scalars(q.order_by(OrdOrder.id.desc()).limit(limit))
    return ok([sc.OrderOut.model_validate(r) for r in list(rows)])


@router.get("/orders/fail/list", summary="接入失败单列表（FR-04c 硬失败）")
async def list_fail_orders(
    handle_status: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    q = select(OrdOrderFail).where(OrdOrderFail.is_deleted == 0)
    if handle_status:
        q = q.where(OrdOrderFail.handle_status == handle_status)
    rows = await session.scalars(q.order_by(OrdOrderFail.id.desc()).limit(limit))
    return ok([sc.OrderFailOut.model_validate(r) for r in list(rows)])


@router.get("/orders/{order_id}", summary="订单详情（含行）")
async def get_order(order_id: int, session: AsyncSession = Depends(get_session)):
    order = await session.scalar(
        select(OrdOrder).where(OrdOrder.id == order_id, OrdOrder.is_deleted == 0)
    )
    if order is None:
        return ok(None)
    items = await session.scalars(
        select(OrdOrderItem)
        .where(OrdOrderItem.order_id == order_id, OrdOrderItem.is_deleted == 0)
        .order_by(OrdOrderItem.id)
    )
    out = sc.OrderOut.model_validate(order)
    out.items = [sc.OrderItemOut.model_validate(i) for i in list(items)]
    return ok(out)


@router.get("/orders/{order_id}/receiver", summary="收货人（脱敏展示，FR-04f）")
async def get_receiver(order_id: int, session: AsyncSession = Depends(get_session)):
    rcv = await session.scalar(
        select(OrdReceiver).where(OrdReceiver.order_id == order_id, OrdReceiver.is_deleted == 0)
    )
    if rcv is None:
        return ok(None)
    from app.core.pipl import decrypt

    out = sc.ReceiverOut.model_validate(rcv)
    out.name_masked = mask_name(decrypt(rcv.name_enc))
    out.mobile_masked = mask_mobile(decrypt(rcv.mobile_enc))
    out.address_masked = "***" if rcv.address_enc else ""
    return ok(out)


@router.get("/orders/{order_id}/pmt", summary="订单优惠分摊明细（FR-06c）")
async def get_order_pmt(order_id: int, session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(
        select(OrdOrderPmt)
        .where(OrdOrderPmt.order_id == order_id, OrdOrderPmt.is_deleted == 0)
        .order_by(OrdOrderPmt.id)
    )
    return ok([sc.OrderPmtOut.model_validate(r) for r in list(rows)])


@router.get("/gateway/logs", summary="api_log 调用留痕（D02.01 FR-07）")
async def list_api_logs(
    shop_id: int | None = Query(default=None, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    q = select(GwApiLog)
    if shop_id:
        q = q.where(GwApiLog.shop_id == shop_id)
    rows = await session.scalars(q.order_by(GwApiLog.id.desc()).limit(limit))
    return ok([sc.ApiLogOut.model_validate(r) for r in list(rows)])
