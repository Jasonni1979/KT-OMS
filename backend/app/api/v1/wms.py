"""W7 履约通道 API（D09.02 出库指令 + D09.01 路由 + 事件编排）

- /wms/route            —— 路由四元组查询
- /wms/cmd/push         —— 出库指令下发（受理即返回）
- /wms/cmd/recall       —— 叫回指令下发
- /wms/callback         —— WMS 回传接收（幂等 + 事件发布）
- /wms/cmd/query        —— 单据反查
- /wms/events/dispatch  —— 事件编排（消费 outbox，调度任务入口）
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.response import ok
from app.modules.m1_master.contract import get_redis
from app.modules.m7_integration.contract import OutboundCommandService, WmsEventDispatcher, WmsRouteService

router = APIRouter()


async def _redis():
    return await get_redis()


# ==================== 路由 ====================


@router.get("/wms/route", summary="WMS 路由四元组")
async def wms_route(
    branch_id: int = Query(...),
    owner_id: int = Query(default=0),
    direction: str = Query(default="OUT", max_length=8),
    session: AsyncSession = Depends(get_session),
):
    """路由决策（D09.01 FR-04a）——只读幂等"""
    svc = WmsRouteService(session)
    route = await svc.route(branch_id, owner_id, direction)
    return ok(route.to_dict())


# ==================== 指令下发 ====================


@router.post("/wms/cmd/push", summary="出库指令下发（受理即返回）")
async def wms_push(
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """出库指令下发（D09.02 FR-01a）

    幂等键 = delivery_id + 推送轮次；同轮次重复调用返回首次指令记录。
    """
    delivery_ids = [int(x) for x in (payload.get("delivery_ids") or [])]
    if not delivery_ids:
        raise ValueError("delivery_ids 必填")
    push_round = int(payload.get("push_round", 1) or 1)
    svc = OutboundCommandService(session, redis)
    res = await svc.push(delivery_ids, push_round=push_round)
    return ok([r.to_dict() for r in res])


@router.post("/wms/cmd/recall", summary="叫回指令下发")
async def wms_recall(
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """叫回指令（D09.02 FR-04a）"""
    delivery_id = int(payload.get("delivery_id", 0) or 0)
    if not delivery_id:
        raise ValueError("delivery_id 必填")
    svc = OutboundCommandService(session, redis)
    res = await svc.recall(
        delivery_id,
        ref_id=str(payload.get("ref_id", "") or ""),
        operator=str(payload.get("operator", "") or "system"),
    )
    return ok(res.to_dict())


@router.post("/wms/cmd/query", summary="单据反查（回传超时兜底）")
async def wms_query(
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """反查 WMS 单据状态（D09.02 FR-03f）"""
    cmd_no = str(payload.get("cmd_no", "") or "")
    if not cmd_no:
        raise ValueError("cmd_no 必填")
    svc = OutboundCommandService(session, redis)
    return ok(await svc.query_order(cmd_no))


# ==================== 回传接收 ====================


@router.post("/wms/callback", summary="WMS 回传接收（幂等 + 事件发布）")
async def wms_callback(
    payload: dict[str, Any],
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """回传接收与标准化（D09.02 FR-03a~FR-03f）

    五步：解析标准化 → 幂等校验 → 指令匹配回填 → 回传登记 → 应答回执（事件异步）。
    """
    svc = OutboundCommandService(session, redis)
    res = await svc.receive_callback(payload)
    return ok(res.to_dict())


@router.post("/wms/events/dispatch", summary="事件编排（消费 outbox）")
async def wms_events_dispatch(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    redis=Depends(_redis),
):
    """消费 outbox 事件并驱动 D03.07 编排（调度任务入口）"""
    svc = WmsEventDispatcher(session, redis)
    res = await svc.dispatch_pending(limit=limit)
    return ok({"count": len(res), "items": [r.to_dict() for r in res]})
