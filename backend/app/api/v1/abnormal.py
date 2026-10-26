"""异常单 API（W8 · SRS-D03.09 异常单与缺货处理）

- /abnormal/types          异常类型字典（前端筛选用）
- /abnormal/reason-codes  审单原因码字典（含 exc_type 映射）
- /abnormal/list          异常单列表（FR-02f：多维过滤 + 分页）
- /abnormal/{id}          异常单详情（含缺货明细 + 时间线 + SLA）
- /abnormal               人工标记（FR-03d：类型 + 备注必填）
- /abnormal/{id}/dispatch 分派 / 改派（FR-02c）
- /abnormal/{id}/process  开始处理（FR-02d）
- /abnormal/{id}/suspend  挂起（FR-02d：须填预计恢复时间）
- /abnormal/{id}/resolve  解决（FR-02d + FR-02e 闭环联动）
- /abnormal/{id}/cancel   取消（FR-02b）
- /abnormal/stockouts     缺货明细列表（FR-04d 看板用）
"""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.exceptions import NotFoundError, ValidationError
from app.core.response import ok
from app.models.abnormal import OrdReasonCodeDict
from app.models.order import OrdOrder
from app.services.abnormal import AbnormalService
from app.services.master import get_redis

router = APIRouter()


async def _svc(session: AsyncSession) -> AbnormalService:
    redis = await get_redis()
    return AbnormalService(session, redis)


# ============ 入参 ============


class ManualCreate(BaseModel):
    """人工标记异常单（FR-03d：类型 + 备注必填）"""

    order_id: int = Field(gt=0)
    exc_type: str = Field(min_length=1, max_length=32)
    note: str = Field(min_length=1, max_length=512)


class DispatchIn(BaseModel):
    group_id: int = Field(default=0, ge=0)
    op_id: int = Field(default=0, ge=0)
    note: str = Field(default="", max_length=512)


class SuspendIn(BaseModel):
    until_hours: int = Field(gt=0, le=24 * 90, description="预计恢复时间（小时）")
    note: str = Field(default="", max_length=512)


class ResolveIn(BaseModel):
    action: str = Field(default="reaudit", max_length=16)
    note: str = Field(default="", max_length=512)


# ============ 字典 ============


@router.get("/abnormal/types", summary="异常类型字典")
async def list_types(session: AsyncSession = Depends(get_session)):
    svc = await _svc(session)
    rows = await svc.types_all()
    return ok(
        {
            "items": [
                {
                    "type_code": r.type_code,
                    "type_name": r.type_name,
                    "category": r.category,
                    "default_group_id": int(r.default_group_id or 0),
                    "default_sla_hours": int(r.default_sla_hours or 24),
                    "need_abnormal_bill": int(r.need_abnormal_bill or 0),
                    "block_fulfill": int(r.block_fulfill or 0),
                    "action_set": r.action_set or [],
                    "is_system": int(r.is_system or 0),
                }
                for r in rows
            ]
        }
    )


@router.get("/abnormal/reason-codes", summary="审单原因码字典（含异常类型映射）")
async def list_reason_codes(session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(
        select(OrdReasonCodeDict)
        .where(OrdReasonCodeDict.disabled == 0)
        .order_by(OrdReasonCodeDict.id)
    )
    return ok(
        {
            "items": [
                {
                    "reason_code": r.reason_code,
                    "reason_name": r.reason_name,
                    "plugin_name": r.plugin_name,
                    "level": r.level,
                    "default_route": r.default_route,
                    "default_suggest": r.default_suggest,
                    "exc_type": r.exc_type,
                }
                for r in rows
            ]
        }
    )


# ============ 列表 / 详情（FR-02f）============


@router.get("/abnormal/list", summary="异常单列表")
async def list_abnormals(
    status: str | None = Query(default=None, max_length=16),
    exc_type: str | None = Query(default=None, max_length=32),
    exc_category: str | None = Query(default=None, max_length=16),
    order_id: int | None = Query(default=None, gt=0),
    shop_id: int | None = Query(default=None, ge=0),
    group_id: int | None = Query(default=None, ge=0),
    keyword: str | None = Query(default=None, max_length=64),
    only_open: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    svc = await _svc(session)
    rows, total = await svc.list_abnormals(
        status=status,
        exc_type=exc_type,
        exc_category=exc_category,
        order_id=order_id,
        shop_id=shop_id,
        group_id=group_id,
        keyword=keyword,
        only_open=only_open,
        limit=limit,
        offset=offset,
    )
    items = []
    for r in rows:
        sla = await svc.sla_status(r)
        items.append(
            {
                "id": r.id,
                "abnormal_bn": r.abnormal_bn,
                "order_id": r.order_id,
                "order_bn": r.order_bn,
                "shop_id": r.shop_id,
                "exc_type": r.exc_type,
                "exc_category": r.exc_category,
                "source": r.source,
                "status": r.status,
                "group_id": r.group_id,
                "op_id": r.op_id,
                "sla": sla,
                "create_time": r.create_time.strftime("%Y-%m-%d %H:%M:%S")
                if r.create_time
                else None,
            }
        )
    return ok({"items": items, "total": total, "limit": limit, "offset": offset})


@router.get("/abnormal/stockouts", summary="缺货明细列表（FR-04d）")
async def list_stockouts(
    abnormal_id: int | None = Query(default=None, gt=0),
    branch_id: int | None = Query(default=None, ge=0),
    bm_id: int | None = Query(default=None, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    from app.models.abnormal import OrdStockout

    stmt = select(OrdStockout).where(OrdStockout.is_deleted == 0)
    if abnormal_id:
        stmt = stmt.where(OrdStockout.abnormal_id == abnormal_id)
    if branch_id:
        stmt = stmt.where(OrdStockout.branch_id == branch_id)
    if bm_id:
        stmt = stmt.where(OrdStockout.bm_id == bm_id)
    rows = await session.scalars(stmt.order_by(OrdStockout.id.desc()).limit(limit))
    return ok(
        {
            "items": [
                {
                    "id": r.id,
                    "abnormal_id": r.abnormal_id,
                    "order_id": r.order_id,
                    "branch_id": r.branch_id,
                    "bm_id": r.bm_id,
                    "lack_num": r.lack_num,
                    "strategy_status": r.strategy_status,
                    "strategy_result": r.strategy_result,
                    "oversold_flag": r.oversold_flag,
                    "stock_snapshot": r.stock_snapshot,
                }
                for r in rows
            ]
        }
    )


@router.get("/abnormal/{abnormal_id}", summary="异常单详情")
async def get_abnormal(
    abnormal_id: int, session: AsyncSession = Depends(get_session)
):
    svc = await _svc(session)
    row = await svc.get(abnormal_id)
    details = await svc.stockouts_of(abnormal_id)
    sla = await svc.sla_status(row)
    return ok(
        {
            "id": row.id,
            "abnormal_bn": row.abnormal_bn,
            "order_id": row.order_id,
            "order_bn": row.order_bn,
            "shop_id": row.shop_id,
            "exc_type": row.exc_type,
            "exc_category": row.exc_category,
            "source": row.source,
            "source_ref": row.source_ref,
            "reason_detail": row.reason_detail,
            "status": row.status,
            "group_id": row.group_id,
            "op_id": row.op_id,
            "dispatch_time": row.dispatch_time.strftime("%Y-%m-%d %H:%M:%S")
            if row.dispatch_time
            else None,
            "sla": sla,
            "escalate_level": row.escalate_level,
            "resolve_action": row.resolve_action,
            "rel_retrial_id": row.rel_retrial_id,
            "suspend_until": row.suspend_until.strftime("%Y-%m-%d %H:%M:%S")
            if row.suspend_until
            else None,
            "timeline": row.timeline or [],
            "stockouts": [
                {
                    "id": d.id,
                    "branch_id": d.branch_id,
                    "bm_id": d.bm_id,
                    "lack_num": d.lack_num,
                    "strategy_status": d.strategy_status,
                    "strategy_result": d.strategy_result,
                    "oversold_flag": d.oversold_flag,
                    "stock_snapshot": d.stock_snapshot,
                }
                for d in details
            ],
        }
    )


# ============ 人工标记（FR-03d）============


@router.post("/abnormal", summary="人工标记异常单")
async def create_manual(
    body: ManualCreate, session: AsyncSession = Depends(get_session)
):
    svc = await _svc(session)
    order = await session.scalar(
        select(OrdOrder).where(
            OrdOrder.id == body.order_id, OrdOrder.is_deleted == 0
        )
    )
    if order is None:
        raise NotFoundError(f"订单不存在: {body.order_id}")
    t = await svc.type_of(body.exc_type)
    if t is None:
        raise ValidationError(f"异常类型不存在: {body.exc_type}")
    row, created = await svc.create(
        order=order,
        exc_type=body.exc_type,
        source="manual",
        source_ref=body.note[:128],
        reason_detail={"note": body.note, "by": "manual"},
    )
    return ok({"id": row.id, "abnormal_bn": row.abnormal_bn, "created": created})


# ============ 处理动作（FR-02c/02d）============


@router.post("/abnormal/{abnormal_id}/dispatch", summary="分派 / 改派")
async def dispatch(
    abnormal_id: int, body: DispatchIn, session: AsyncSession = Depends(get_session)
):
    svc = await _svc(session)
    row = await svc.dispatch(
        abnormal_id,
        group_id=body.group_id,
        op_id=body.op_id,
        operator="api",
        note=body.note,
    )
    return ok({"id": row.id, "status": row.status, "group_id": row.group_id})


@router.post("/abnormal/{abnormal_id}/process", summary="开始处理")
async def start_processing(
    abnormal_id: int, session: AsyncSession = Depends(get_session)
):
    svc = await _svc(session)
    row = await svc.start_processing(abnormal_id, operator="api")
    return ok({"id": row.id, "status": row.status})


@router.post("/abnormal/{abnormal_id}/suspend", summary="挂起（等货 / 等买家回复）")
async def suspend(
    abnormal_id: int, body: SuspendIn, session: AsyncSession = Depends(get_session)
):
    svc = await _svc(session)
    row = await svc.suspend(
        abnormal_id, until_hours=body.until_hours, operator="api", note=body.note
    )
    return ok({"id": row.id, "status": row.status, "suspend_until": row.suspend_until})


@router.post("/abnormal/{abnormal_id}/resolve", summary="解决异常单")
async def resolve(
    abnormal_id: int, body: ResolveIn, session: AsyncSession = Depends(get_session)
):
    svc = await _svc(session)
    row = await svc.resolve(
        abnormal_id, action=body.action, operator="api", note=body.note
    )
    return ok({"id": row.id, "status": row.status, "resolve_action": row.resolve_action})


@router.post("/abnormal/{abnormal_id}/cancel", summary="取消异常单")
async def cancel(
    abnormal_id: int, body: ResolveIn, session: AsyncSession = Depends(get_session)
):
    svc = await _svc(session)
    row = await svc.cancel(abnormal_id, operator="api", note=body.note)
    return ok({"id": row.id, "status": row.status})
