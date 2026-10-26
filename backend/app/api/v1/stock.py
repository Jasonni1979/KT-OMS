"""库存记账与对账 API（SRS-D04.02）

路由前缀 /api/v1/stock
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.response import ok
from app.models.stock import InvSyncStrategy
from app.modules.m1_master.service.master import get_redis
from app.modules.m2_stock.service.freeze import FreezeService
from app.modules.m2_stock.service.io_bill import IoBillService
from app.modules.m2_stock.service.sellable import SellableService
from app.modules.m2_stock.service.stock_ledger import StockLedgerService
from app.modules.m2_stock.service.stock_recon import ReconService
from app.modules.m7_integration.service.gateway import get_gateway
from app.modules.m7_integration.service.sync import StockSyncService
from app.schemas import stock as sc

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


# ============ 出入库单据（SRS-D04.04）============

@router.get("/bill/types", summary="单据类型目录（口径影响模板）")
async def list_bill_types(session: AsyncSession = Depends(get_session)):
    redis = await get_redis()
    types = await IoBillService(session, redis).list_types()
    return ok(
        [
            {
                "type_code": t.type_code,
                "type_name": t.type_name,
                "direction": t.direction,
                "effect_template": t.effect_template,
                "need_wms": t.need_wms,
                "need_approval": t.need_approval,
                "settle_rel": t.settle_rel,
            }
            for t in types
        ]
    )


@router.get("/bills", summary="单据列表（多维）")
async def list_bills(
    bill_type: str | None = Query(default=None, max_length=32),
    branch_id: int | None = Query(default=None, ge=1),
    status: int | None = Query(default=None, ge=1, le=7),
    source_bill_bn: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
):
    redis = await get_redis()
    bills = await IoBillService(session, redis).query(
        bill_type, branch_id, status, source_bill_bn, limit
    )
    return ok(bills)


@router.post("/bills", summary="创建单据（草稿）")
async def create_bill(
    data: sc.IoBillCreate, session: AsyncSession = Depends(get_session)
):
    redis = await get_redis()
    return ok(await IoBillService(session, redis).create(data))


@router.get("/bills/{bill_id}", summary="单据详情")
async def get_bill(bill_id: int, session: AsyncSession = Depends(get_session)):
    redis = await get_redis()
    return ok(await IoBillService(session, redis).get_bill(bill_id))


@router.post("/bills/{bill_id}/push-wms", summary="下发 WMS")
async def push_bill(
    bill_id: int,
    wms_bill_no: str = Query(default="", max_length=64),
    session: AsyncSession = Depends(get_session),
):
    redis = await get_redis()
    return ok(await IoBillService(session, redis).push_to_wms(bill_id, wms_bill_no))


@router.post("/bills/{bill_id}/callback", summary="WMS 回传（分批累计）")
async def callback_bill(
    bill_id: int, data: sc.IoBillCallback, session: AsyncSession = Depends(get_session)
):
    redis = await get_redis()
    return ok(await IoBillService(session, redis).receive_callback(bill_id, data))


@router.post("/bills/{bill_id}/confirm", summary="确认即记账（按类型口径模板）")
async def confirm_bill(
    bill_id: int,
    operator: str = Query(default="", max_length=64),
    session: AsyncSession = Depends(get_session),
):
    redis = await get_redis()
    return ok(await IoBillService(session, redis).confirm(bill_id, operator))


@router.post("/bills/{bill_id}/red-flush", summary="红冲（反向记账）")
async def red_flush_bill(
    bill_id: int, data: sc.RedFlushRequest, session: AsyncSession = Depends(get_session)
):
    redis = await get_redis()
    return ok(await IoBillService(session, redis).red_flush(bill_id, data))


@router.put("/bills/{bill_id}/settle", summary="结算状态回写")
async def settle_bill(
    bill_id: int, data: sc.SettleUpdateRequest, session: AsyncSession = Depends(get_session)
):
    redis = await get_redis()
    return ok(await IoBillService(session, redis).set_settle(bill_id, data))


@router.get("/bills/{bill_id}/trace", summary="追溯链（单据→行→流水→余额）")
async def trace_bill(bill_id: int, session: AsyncSession = Depends(get_session)):
    redis = await get_redis()
    return ok(await IoBillService(session, redis).trace(bill_id))


# ============ 可售计算与平台同步（SRS-D04.08）============

@router.get("/sellable/{shop_id}/{sm_id}", summary="可售计算（IF-D04.08-01）")
async def calc_sellable(
    shop_id: int,
    sm_id: int,
    refresh: bool = Query(default=False, description="跳过缓存强制重算"),
    session: AsyncSession = Depends(get_session),
):
    redis = await get_redis()
    svc = SellableService(session, redis)
    result = await svc.calc(shop_id, sm_id, use_cache=not refresh)
    return ok(sc.SellableOut(**result.as_dict()))


@router.post("/sellable/{shop_id}/{sm_id}/writeback", summary="可售回写单个 SKU（FR-03）")
async def writeback_sellable(
    shop_id: int,
    sm_id: int,
    force: bool = Query(default=False, description="跳过阈值节流强制回写"),
    trigger: int = Query(default=1, ge=1, le=5, description="1事件,2水位,3定时,4手动,5对账"),
    session: AsyncSession = Depends(get_session),
):
    redis = await get_redis()
    svc = StockSyncService(session, redis, get_gateway(redis))
    strategy = await svc.sellable.get_strategy(shop_id)
    rate = float(strategy.threshold_rate or 0) if strategy else 0.0
    res = await svc.writeback(shop_id, sm_id, trigger=trigger, force=force, threshold_rate=rate)
    return ok(sc.WritebackResultOut(**res.as_dict()))


@router.post("/sellable/{shop_id}/writeback-all", summary="店铺全量回写（FR-03a③/FR-01d）")
async def writeback_sellable_all(
    shop_id: int,
    force: bool = Query(default=False),
    session: AsyncSession = Depends(get_session),
):
    redis = await get_redis()
    svc = StockSyncService(session, redis, get_gateway(redis))
    results = await svc.writeback_shop(shop_id, trigger=3, force=force)
    written = sum(1 for r in results if r.written)
    return ok({"total": len(results), "written": written, "results": [r.as_dict() for r in results]})


@router.post("/sellable/{shop_id}/recon", summary="同步对账（FR-05a：差异强制回写）")
async def recon_sellable(shop_id: int, session: AsyncSession = Depends(get_session)):
    redis = await get_redis()
    svc = StockSyncService(session, redis, get_gateway(redis))
    report = await svc.recon_shop(shop_id)
    return ok(sc.SellableReconOut(**report))


@router.get("/sellable/{shop_id}/status", summary="同步状态查询（IF-D04.08-04）")
async def sellable_status(
    shop_id: int,
    skus: str | None = Query(default=None, description="平台SKU列表（逗号分隔）"),
    session: AsyncSession = Depends(get_session),
):
    redis = await get_redis()
    svc = StockSyncService(session, redis, get_gateway(redis))
    sku_list = [s for s in (skus or "").split(",") if s] or None
    return ok(await svc.sync_status(shop_id, sku_list))


@router.get("/sync-strategies", summary="可售同步策略列表（FR-01）")
async def list_sync_strategies(
    shop_id: int | None = Query(default=None, ge=1),
    session: AsyncSession = Depends(get_session),
):
    q = select(InvSyncStrategy).where(InvSyncStrategy.is_deleted == 0)
    if shop_id:
        q = q.where(InvSyncStrategy.shop_id == shop_id)
    rows = await session.scalars(q.order_by(InvSyncStrategy.id))
    return ok([sc.SyncStrategyOut.model_validate(r) for r in list(rows)])


@router.post("/sync-strategies", summary="配置可售同步策略（FR-01c：变更即时生效）")
async def upsert_sync_strategy(
    data: sc.SyncStrategyIn, session: AsyncSession = Depends(get_session)
):
    svc = SellableService(session, await get_redis())
    existing = await session.scalar(
        select(InvSyncStrategy).where(
            InvSyncStrategy.shop_id == data.shop_id,
            InvSyncStrategy.scope_type == data.scope_type,
            InvSyncStrategy.is_deleted == 0,
        )
    )
    if existing is None:
        existing = InvSyncStrategy(shop_id=data.shop_id, scope_type=data.scope_type)
        session.add(existing)
    for field in (
        "scope_ref", "strategy_type", "safe_num", "safe_ratio", "alloc_ratio",
        "oversell_mode", "quota_num", "water_level", "min_sellable", "max_sellable",
        "writeback_mode", "threshold_rate", "status",
    ):
        setattr(existing, field, getattr(data, field))
    existing.version += 1
    await session.commit()
    await session.refresh(existing)
    # FR-01d：策略变更即时生效 → 清缓存 + 全量重算回写
    await svc.invalidate_all(data.shop_id)
    return ok(sc.SyncStrategyOut.model_validate(existing))
