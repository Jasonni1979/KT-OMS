"""履约监控看板 API（SRS-D11.03 最小可用版 · W8-3）"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.response import ok

router = APIRouter()


@router.get("/monitor/overview", summary="监控看板总览")
async def overview(session: AsyncSession = Depends(get_session)):
    """看板总览（顶部指标卡 + 各域明细）

    口径：实时快照（直查业务表），非 D11.01 报表口径 —— 差异已在返回体
    `caliber_note` 中明示（FR-01d）。
    """
    from app.modules.m8_insight.contract import MonitorService

    return ok(await MonitorService(session).overview())


@router.get("/monitor/pull-watermark", summary="拉单水位")
async def pull_watermark(session: AsyncSession = Depends(get_session)):
    """拉单水位落后时长（FR-01b：D02.03 域）"""
    from app.modules.m8_insight.contract import MonitorService

    return ok(await MonitorService(session).pull_watermark())


@router.get("/monitor/audit-backlog", summary="审单积压")
async def audit_backlog(session: AsyncSession = Depends(get_session)):
    """审单积压 + SLA 超期分级（FR-01b：D03.02 域）"""
    from app.modules.m8_insight.contract import MonitorService

    return ok(await MonitorService(session).audit_backlog())


@router.get("/monitor/writeback-failures", summary="回传失败")
async def writeback_failures(session: AsyncSession = Depends(get_session)):
    """平台回传 + WMS 指令失败台账（FR-01b：D02.05 + D09.02 域）"""
    from app.modules.m8_insight.contract import MonitorService

    return ok(await MonitorService(session).writeback_failures())


@router.get("/monitor/abnormal-realtime", summary="异常单实时监控")
async def abnormal_realtime(session: AsyncSession = Depends(get_session)):
    """未闭环异常单分布 + 超期分级（FR-08a：D03.09 供数）"""
    from app.modules.m8_insight.contract import MonitorService

    return ok(await MonitorService(session).abnormal_realtime())
