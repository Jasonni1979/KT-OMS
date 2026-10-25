"""库存对账服务（SRS-D04.02 FR-05c/FR-05d/FR-06b）

- 定时对账：每 5 分钟抽样 + 每小时全量比对 Redis vs DB（§5.3 rebalance 重算算法）
- 差异处理：以 DB（快照 S0 + 流水重算）为准修复 Redis，差异落 inv_stock_recon_diff 留痕
- 连续差异升级人工（同一三元键累计差异 ≥2 次 → status 保持待处理，不自动修复）
"""
from datetime import date, datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.stock import InvStockChangeLog, InvStockLedger, InvStockReconDiff, InvStockSnapshot
from app.schemas import stock as sc
from app.services.stock_ledger import REDIS_FIELD, StockLedgerService

# 口径 → 流水 change_field（arrive_store 在流水中叫 arrive）
RECON_FIELDS = ("store", "freeze", "arrive_store", "defective")
FLOW_FIELD = {"store": "store", "freeze": "freeze", "arrive_store": "arrive", "defective": "defective"}


class ReconService:
    """对账与差异修复"""

    def __init__(self, session: AsyncSession, redis: Redis):
        self.s = session
        self.r = redis
        self.ledger = StockLedgerService(session, redis)

    async def rebalance(self, branch_id: int, bm_id: int, owner_id: int) -> dict[str, int]:
        """§5.3 流水重算：最近日终快照 S0 + 回放 S0 之后的全部流水 → 各口径应有余额"""
        snap = await self.s.scalar(
            select(InvStockSnapshot)
            .where(
                InvStockSnapshot.branch_id == branch_id,
                InvStockSnapshot.bm_id == bm_id,
                InvStockSnapshot.owner_id == owner_id,
            )
            .order_by(InvStockSnapshot.snapshot_date.desc(), InvStockSnapshot.id.desc())
            .limit(1)
        )
        balances = {f: 0 for f in RECON_FIELDS}
        if snap:
            balances = {
                "store": int(snap.store),
                "freeze": int(snap.freeze),
                "arrive_store": int(snap.arrive_store),
                "defective": int(snap.defective),
            }
            since = snap.create_time
        else:
            since = datetime(1970, 1, 1)

        logs = (await self.s.scalars(
            select(InvStockChangeLog).where(
                InvStockChangeLog.branch_id == branch_id,
                InvStockChangeLog.bm_id == bm_id,
                InvStockChangeLog.owner_id == owner_id,
                InvStockChangeLog.create_time > since,
            ).order_by(InvStockChangeLog.id)
        )).all()
        for log in logs:
            for f, flow_name in FLOW_FIELD.items():
                if log.change_field == flow_name:
                    balances[f] += int(log.change_num)
        return balances

    async def recon_redis_vs_db(self, fix: bool = True) -> sc.ReconReportOut:
        """Redis vs DB 全量对账（FR-05c）"""
        rows = (await self.s.scalars(
            select(InvStockLedger).where(InvStockLedger.is_deleted == 0)
        )).all()
        diffs: list[sc.ReconDiffOut] = []
        fixed = 0
        today = date.today()
        now = datetime.now()

        for row in rows:
            key = self.ledger.stock_key(row.branch_id, row.bm_id, row.owner_id)
            raw = await self.r.hgetall(key)
            redis_vals: dict[str, int] = {f: 0 for f in RECON_FIELDS}
            for f in RECON_FIELDS:
                v = raw.get(REDIS_FIELD[f])
                if v is None:
                    continue
                if isinstance(v, bytes):
                    v = v.decode()
                redis_vals[f] = int(v)

            for f in RECON_FIELDS:
                oms_num = int(getattr(row, f))
                peer_num = redis_vals[f]
                if oms_num == peer_num:
                    continue
                diff_num = peer_num - oms_num
                # 连续差异升级人工：同三元键同口径已有未处理差异 → 不自动修复
                pending = await self.s.scalar(
                    select(InvStockReconDiff.id).where(
                        InvStockReconDiff.branch_id == row.branch_id,
                        InvStockReconDiff.bm_id == row.bm_id,
                        InvStockReconDiff.owner_id == row.owner_id,
                        InvStockReconDiff.change_field == FLOW_FIELD[f],
                        InvStockReconDiff.status == 1,
                    )
                )
                auto_fix = fix and not pending
                diff = InvStockReconDiff(
                    tenant_id=row.tenant_id,
                    owner_id=row.owner_id,
                    recon_date=today,
                    recon_type=1,
                    branch_id=row.branch_id,
                    bm_id=row.bm_id,
                    change_field=FLOW_FIELD[f],
                    oms_num=oms_num,
                    peer_num=peer_num,
                    diff_num=diff_num,
                    status=2 if auto_fix else 1,
                    handle_remark=(
                        "自动修复：以 DB 余额为准覆盖 Redis" if auto_fix else "待人工处理（连续差异）"
                    ),
                    handler="system:recon" if auto_fix else "",
                    handle_time=now if auto_fix else None,
                )
                self.s.add(diff)
                await self.s.flush()
                if auto_fix:
                    await self.r.hset(key, REDIS_FIELD[f], oms_num)
                    fixed += 1
                diffs.append(
                    sc.ReconDiffOut(
                        id=diff.id,
                        owner_id=diff.owner_id,
                        recon_date=diff.recon_date,
                        recon_type=diff.recon_type,
                        branch_id=diff.branch_id,
                        bm_id=diff.bm_id,
                        change_field=diff.change_field,
                        oms_num=diff.oms_num,
                        peer_num=diff.peer_num,
                        diff_num=diff.diff_num,
                        status=diff.status,
                        handle_remark=diff.handle_remark,
                        handler=diff.handler,
                        handle_time=diff.handle_time,
                    )
                )
        await self.s.commit()
        return sc.ReconReportOut(
            recon_type=1,
            checked=len(rows),
            diff_count=len(diffs),
            fixed=fixed,
            diffs=diffs,
        )

    async def rebuild_cache(
        self, branch_id: int | None = None, owner_id: int | None = None
    ) -> int:
        """缓存重建（FR-05d：按仓/货主手动触发全量重建）"""
        q = select(InvStockLedger).where(InvStockLedger.is_deleted == 0)
        if branch_id:
            q = q.where(InvStockLedger.branch_id == branch_id)
        if owner_id:
            q = q.where(InvStockLedger.owner_id == owner_id)
        rows = (await self.s.scalars(q)).all()
        for row in rows:
            key = self.ledger.stock_key(row.branch_id, row.bm_id, row.owner_id)
            await self.r.hset(key, mapping={
                "store": int(row.store),
                "freeze": int(row.freeze),
                "arrive": int(row.arrive_store),
                "defective": int(row.defective),
                "safe_locked": int(row.safe_store) if row.is_locked == 1 else 0,
            })
        return len(rows)

    async def list_diffs(
        self, status: int | None = None, limit: int = 100
    ) -> list[sc.ReconDiffOut]:
        q = select(InvStockReconDiff)
        if status is not None:
            q = q.where(InvStockReconDiff.status == status)
        rows = (await self.s.scalars(q.order_by(InvStockReconDiff.id.desc()).limit(limit))).all()
        return [sc.ReconDiffOut.model_validate(r) for r in rows]

    async def handle_diff(
        self, diff_id: int, status: int, remark: str = "", handler: str = ""
    ) -> sc.ReconDiffOut:
        """人工处理差异（FR-06b：走调整单/盘点闭环时记单号）"""
        diff = await self.s.scalar(
            select(InvStockReconDiff).where(InvStockReconDiff.id == diff_id)
        )
        if not diff:
            raise NotFoundError(f"对账差异不存在: {diff_id}")
        diff.status = status
        diff.handle_remark = remark
        diff.handler = handler
        diff.handle_time = datetime.now()
        await self.s.commit()
        await self.s.refresh(diff)
        return sc.ReconDiffOut.model_validate(diff)
