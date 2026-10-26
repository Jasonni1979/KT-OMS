"""订单修改 API（D03.08 订单修改与复审 · W8-3 最小子集）"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.response import ok

router = APIRouter()


class AddressModifyIn(BaseModel):
    """改地址请求（FR-01a：改单类型固定为地址）"""

    order_id: int = Field(gt=0)
    province: str = Field(default="", max_length=32)
    city: str = Field(default="", max_length=32)
    district: str = Field(default="", max_length=32)
    town: str = Field(default="", max_length=64)
    #: 详址**密文**（前端不传明文地址 —— PIPL 合规）
    address_enc: str = Field(default="", max_length=4096)
    operator: str = Field(default="", max_length=64)
    source: str = Field(default="manual", max_length=16)


@router.post("/modify/address", summary="发起改地址改单（D03.08 FR-01a）")
async def create_address_modify(
    body: AddressModifyIn, session: AsyncSession = Depends(get_session)
):
    """发起改地址改单

    - 无发货单 → 直接生效（FR-03b：纯地址改单不动库存）
    - 有发货单 → 先叫回（W7 链路），叫回成功后需再调 `/recall-complete` 才生效
    """
    from app.modules.m1_master.contract import get_redis
    from app.modules.m6_aftersale.contract import ModifyService

    svc = ModifyService(session, await get_redis())
    return ok(
        await svc.create_address_modify(
            body.order_id,
            province=body.province,
            city=body.city,
            district=body.district,
            town=body.town,
            address_enc=body.address_enc,
            operator=body.operator,
            source=body.source,
        )
    )


@router.get("/modify/list", summary="改单列表")
async def list_modifies(
    order_id: int | None = Query(default=None, gt=0),
    status: str | None = Query(default=None, max_length=16),
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """改单列表（按订单 / 状态筛选）"""
    from app.modules.m6_aftersale.contract import ModifyService

    svc = ModifyService(session, None)
    items = await svc.list_modifies(order_id=order_id, status=status, limit=limit)
    return ok({"items": items, "total": len(items)})


@router.get("/modify/{modify_id}", summary="改单详情（含快照与 Saga 日志）")
async def get_modify(modify_id: int, session: AsyncSession = Depends(get_session)):
    """改单详情：快照 + 差异对比 + Saga 编排日志"""
    from app.modules.m6_aftersale.contract import ModifyService

    svc = ModifyService(session, None)
    return ok(await svc.get_modify(modify_id))


@router.post("/modify/{modify_id}/recall-complete", summary="叫回成功后生效")
async def recall_complete(
    modify_id: int, session: AsyncSession = Depends(get_session)
):
    """叫回成功后继续改单流程并生效（FR-06c）"""
    from app.modules.m1_master.contract import get_redis
    from app.modules.m6_aftersale.contract import ModifyService

    svc = ModifyService(session, await get_redis())
    return ok(await svc.complete_recall_and_effective(modify_id, operator="api"))


@router.post("/modify/{modify_id}/cancel", summary="撤销改单")
async def cancel_modify(
    modify_id: int, session: AsyncSession = Depends(get_session)
):
    """撤销改单（叫回失败时的人工决策之一：撤销改单恢复现场，FR-06c）"""
    from app.modules.m6_aftersale.contract import ModifyService

    svc = ModifyService(session, None)
    return ok(await svc.cancel_recall_modify(modify_id, operator="api"))
