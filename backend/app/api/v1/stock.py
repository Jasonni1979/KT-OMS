"""库存记账与对账 API（SRS-D04.02）

路由前缀 /api/v1/stock
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.response import ok
from app.schemas import stock as sc
from app.services.freeze import FreezeService
from app.services.master import get_redis
from app.services.stock_ledger import StockLedgerService
from app.services.stock_recon import ReconService

router = APIRouter(tags=["stock-库存记账"])


@router.get("/ledger", summary="五口径余额查询（仓/货主/品牌/分类多维）")
async def query_ledger(
    branch_id: int | None = Query(default=None, ge=1),
    owner_id: int | None = Query(default=None, ge=1),
    brand_id: int | None = Query(default=None, ge=0),
    cat_id: int | None = Query(default=None, ge=0),
    keyword: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_session),
):
    redis = await get_redis()
    rows = await StockLedgerService(session, redis).query(
        branch_id, owner_id, brand_id, cat_id, keyword, limit
    )
    return ok(rows)


@router.get("/ledger/{branch_id}/{bm_id}/{owner_id}", summary="单个三元键的五口径余额")
async def get_ledger_balance(
    branch_id: int, bm_id: int, owner_id: int, session: AsyncSession = Depends(get_session)
):
    redis = await get_redis()
    bal = await StockLedgerService(session, redis).get_balance(branch_id, bm_id, owner_id)
    return ok(bal)


@router.post("/ledger/change", summary="口径记账（其他业务域调用；幂等键防重复）")
async def apply_change(
    data: sc.StockChangeRequest, session: AsyncSession = Depends(get_session)
):
    redis = await get_redis()
    result = await StockLedgerService(session, redis).apply_change(data)
    return ok(result)


@router.post("/ledger/adjust", summary="人工库存调整（FR-04：原因必填，生效即记账+流水）")
async def apply_adjust(
    data: sc.StockAdjustRequest, session: AsyncSession = Depends(get_session)
):
    redis = await get_redis()
    result = await StockLedgerService(session, redis).adjust(data)
    return ok(result)


@router.post("/recon/run", summary="触发 Redis vs DB 对账（FR-05c；默认自动修复）")
async def run_recon(
    fix: bool = Query(default=True, description="是否自动以 DB 余额修复 Redis"),
    session: AsyncSession = Depends(get_session),
):
    redis = await get_redis()
    report = await ReconService(session, redis).recon_redis_vs_db(fix)
    return ok(report)


@router.get("/recon/diffs", summary="对账差异列表")
async def list_diffs(
    status: int | None = Query(default=None, ge=1, le=4),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    redis = await get_redis()
    diffs = await ReconService(session, redis).list_diffs(status, limit)
    return ok(diffs)


@router.post("/recon/diffs/{diff_id}/handle", summary="人工处理对账差异")
async def handle_diff(
    diff_id: int,
    status: int = Query(ge=3, le=4, description="3=已人工处理,4=误报忽略"),
    remark: str = Query(default="", max_length=512),
    handler: str = Query(default="", max_length=64),
    session: AsyncSession = Depends(get_session),
):
    redis = await get_redis()
    diff = await ReconService(session, redis).handle_diff(diff_id, status, remark, handler)
    return ok(diff)


@router.post("/recon/rebuild-cache", summary="Redis 缓存重建（FR-05d：发布/故障恢复）")
async def rebuild_cache(
    branch_id: int | None = Query(default=None, ge=1),
    owner_id: int | None = Query(default=None, ge=1),
    session: AsyncSession = Depends(get_session),
):
    redis = await get_redis()
    count = await ReconService(session, redis).rebuild_cache(branch_id, owner_id)
    return ok({"rebuilt": count})


@router.post("/snapshot", summary="生成日终库存快照（FR-06a）")
async def make_snapshot(session: AsyncSession = Depends(get_session)):
    redis = await get_redis()
    count = await StockLedgerService(session, redis).make_snapshot()
    return ok({"created": count})


# ============ 预占（SRS-D04.03）============

@router.post("/freeze/reserve", summary="预占（Redis 原子防超卖 + 台账 + Saga 补偿）")
async def freeze_reserve(
    data: sc.FreezeReserveRequest, session: AsyncSession = Depends(get_session)
):
    redis = await get_redis()
    result = await FreezeService(session, redis).reserve(data)
    return ok(result)


@router.post("/freeze/release", summary="释放（取消/驳回；重复释放幂等）")
async def freeze_release(
    data: sc.FreezeReleaseRequest, session: AsyncSession = Depends(get_session)
):
    redis = await get_redis()
    result = await FreezeService(session, redis).release(data)
    return ok(result)


@router.post("/freeze/settle", summary="转扣减（出库回传：freeze-N & store-N，支持部分核销）")
async def freeze_settle(
    data: sc.FreezeSettleRequest, session: AsyncSession = Depends(get_session)
):
    redis = await get_redis()
    result = await FreezeService(session, redis).settle(data)
    return ok(result)


@router.post("/freeze/expire-reclaim", summary="过期回收（FR-02b：超期未核销自动释放）")
async def freeze_expire_reclaim(session: AsyncSession = Depends(get_session)):
    redis = await get_redis()
    result = await FreezeService(session, redis).expire_reclaim()
    return ok(result)


@router.get("/freeze/logs", summary="预占台账查询（多维）")
async def freeze_logs(
    obj_type: int | None = Query(default=None, ge=1, le=5),
    obj_bn: str | None = Query(default=None, max_length=32),
    branch_id: int | None = Query(default=None, ge=1),
    bm_id: int | None = Query(default=None, ge=1),
    owner_id: int | None = Query(default=None, ge=1),
    status: int | None = Query(default=None, ge=1, le=4),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    redis = await get_redis()
    logs = await FreezeService(session, redis).query_logs(
        obj_type, obj_bn, branch_id, bm_id, owner_id, status, limit
    )
    return ok(logs)


@router.get("/freeze/age", summary="在途预占账龄分析（FR-04a）")
async def freeze_age(session: AsyncSession = Depends(get_session)):
    redis = await get_redis()
    age = await FreezeService(session, redis).age_analysis()
    return ok(age)
