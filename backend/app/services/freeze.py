"""预占/释放/转扣减服务（SRS-D04.03）

架构（SRS §5.1）：
  预占请求 → Redis Lua freeze_incr（原子，实时口径权威，防超卖）
           → DB 预占台账（业务追溯权威）+ DB 记账行 freeze 口径 + 流水
           → DB 失败 → 立即 freeze_decr 回滚 Redis（同步补偿；M1b 阶段替代 MQ 异步重试）

- 幂等：台账幂等键 = 对象类型:单据号:行:动作（uk_inv_freeze_log_key 唯一索引兜底）
- 释放/核销互斥：二者都消费同一 Redis 台账标记（先到者删标记，后到者返回幂等）
- Saga 补偿（FR-01b）：一单多行逐行预占，任一行失败 → 反向释放已成功行并留痕
- 过期回收（FR-02b）：扫描超期未核销台账 → 自动释放
"""
from datetime import datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.stock import InvFreezeLog, InvStockConfig
from app.schemas import stock as sc
from app.services.stock_ledger import StockLedgerService

DEFAULT_TTL_HOURS = 72


class FreezeService:
    """预占服务"""

    def __init__(self, session: AsyncSession, redis: Redis):
        self.s = session
        self.r = redis
        self.ledger = StockLedgerService(session, redis)

    # ---------- 键 ----------

    @staticmethod
    def marker_key(obj_type: int, obj_bn: str, obj_item_id: int) -> str:
        """Redis 台账标记（release/settle 消费它 → 互斥）"""
        return f"inv:freeze:{obj_type}:{obj_bn}:{obj_item_id}"

    @staticmethod
    def log_key(obj_type: int, obj_bn: str, obj_item_id: int, action: str) -> str:
        """DB 台账幂等键（对象类型+单据+行+动作）"""
        return f"{obj_type}:{obj_bn}:{obj_item_id}:{action}"

    @staticmethod
    def stock_key(branch_id: int, bm_id: int, owner_id: int) -> str:
        return StockLedgerService.stock_key(branch_id, bm_id, owner_id)

    # ---------- 有效期（§5.4：货主 > 店铺 > 全局）----------

    async def _ttl_hours(
        self, owner_id: int, shop_id: int, override: int | None
    ) -> int:
        if override:
            return override
        scopes = [(2, str(owner_id)), (3, str(shop_id)), (1, "")]
        for scope_type, scope_ref in scopes:
            if scope_type == 3 and not shop_id:
                continue
            cfg = await self.s.scalar(
                select(InvStockConfig).where(
                    InvStockConfig.config_type == 3,
                    InvStockConfig.scope_type == scope_type,
                    InvStockConfig.scope_ref == scope_ref,
                    InvStockConfig.status == 1,
                    InvStockConfig.is_deleted == 0,
                )
            )
            if cfg:
                data = cfg.config_json or {}
                if isinstance(data, dict) and data.get("hours"):
                    return int(data["hours"])
        return DEFAULT_TTL_HOURS

    # ---------- 预占（FR-01）----------

    async def reserve(self, req: sc.FreezeReserveRequest) -> sc.FreezeResult:
        """统一预占入口（逐行 Saga：任一行失败 → 反向释放已成功行）"""
        reserved = 0
        available_after = 0
        logs: list[sc.FreezeLogOut] = []
        done_rows: list[tuple[sc.FreezeReserveItem, InvFreezeLog]] = []
        compensated = False

        try:
            for item in req.items:
                log, avail = await self._reserve_one(req, item)
                done_rows.append((item, log))
                reserved += item.num
                available_after = avail
                logs.append(sc.FreezeLogOut.model_validate(log))
        except Exception:
            # Saga 补偿：反向释放已成功行并留痕（is_compensated=1）
            for item, log in reversed(done_rows):
                try:
                    await self._release_one(log, item.num, operator="system:compensate", compensate=True)
                except Exception:
                    pass
            compensated = bool(done_rows)
            raise

        return sc.FreezeResult(
            idempotent=False,
            obj_type=req.obj_type,
            obj_bn=req.obj_bn,
            reserved_num=reserved,
            available_after=available_after,
            logs=logs,
            compensated=compensated,
        )

    async def _reserve_one(
        self, req: sc.FreezeReserveRequest, item: sc.FreezeReserveItem
    ) -> tuple[InvFreezeLog, int]:
        """单行预占：Redis 原子先行 → DB 台账 + 记账行"""
        idem = self.log_key(req.obj_type, req.obj_bn, item.obj_item_id, "reserve")
        marker = self.marker_key(req.obj_type, req.obj_bn, item.obj_item_id)

        # 幂等：台账已存在 → 直接返回首次结果
        existing = await self.s.scalar(
            select(InvFreezeLog).where(InvFreezeLog.idempotent_key == idem)
        )
        if existing:
            avail = await self._available(item.branch_id, item.bm_id, item.owner_id)
            return existing, avail

        ttl_hours = await self._ttl_hours(item.owner_id, item.shop_id, req.ttl_hours)
        ttl_seconds = ttl_hours * 3600

        # ① Redis 原子预占（防超卖；miss → 回填后重试一次）
        code, avail = await self._lua_reserve(item, marker, ttl_seconds)
        if code == -1:
            raise ConflictError(
                f"可用库存不足：当前可用 {avail}，预占 {item.num}",
                code="INSUFFICIENT_STOCK",
                data={"available": avail, "request": item.num},
            )
        if code == 0:
            # Redis 标记已存在（幂等命中）→ 台账可能已存在
            existing2 = await self.s.scalar(
                select(InvFreezeLog).where(InvFreezeLog.idempotent_key == idem)
            )
            if existing2:
                return existing2, avail
            # 标记在但台账缺失（上次补偿未清）→ 视为已占用，拒绝
            raise ConflictError("预占幂等标记已存在但台账缺失，拒绝重复预占", code="FREEZE_MARKER_CONFLICT")

        # ② DB 台账 + 记账行（失败 → 回滚 Redis）
        try:
            log = InvFreezeLog(
                tenant_id=1,
                owner_id=item.owner_id,
                obj_type=req.obj_type,
                obj_bn=req.obj_bn,
                obj_item_id=item.obj_item_id,
                branch_id=item.branch_id,
                bm_id=item.bm_id,
                shop_id=item.shop_id,
                num=item.num,
                settled_num=0,
                released_num=0,
                status=1,
                expire_time=datetime.now() + timedelta(hours=ttl_hours),
                lend_owner_id=req.lend_owner_id,
                source=req.source,
                is_compensated=0,
                idempotent_key=idem,
            )
            self.s.add(log)
            await self.s.flush()
            await self.ledger.apply_change(
                sc.StockChangeRequest(
                    branch_id=item.branch_id,
                    bm_id=item.bm_id,
                    owner_id=item.owner_id,
                    changes=[sc.StockChangeItem(field="freeze", delta=item.num)],
                    bill_type="freeze",
                    bill_bn=req.obj_bn,
                    bill_item_id=item.obj_item_id,
                    action="reserve",
                    operator="",
                    source=req.source,
                    redis_synced=True,
                )
            )
        except Exception:
            await self.s.rollback()
            await self._lua_release(item, marker, item.num)
            raise
        return log, avail

    async def _lua_reserve(
        self, item: sc.FreezeReserveItem, marker: str, ttl_seconds: int
    ) -> tuple[int, int]:
        """调 Lua 预占；Redis miss 时用 DB 余额回填后重试一次（FR-05b 降级）"""
        from app.infra.freeze_service import FreezeService as LuaFreeze

        lua = LuaFreeze(self.r)
        key = self.stock_key(item.branch_id, item.bm_id, item.owner_id)
        code, avail = await lua.reserve(
            item.branch_id, item.bm_id, item.owner_id, item.num, marker, ttl_seconds
        )
        if code == -1 and not await self.r.exists(key):
            # Redis 无缓存 → 回填 DB 余额后重试
            await self._backfill(item.branch_id, item.bm_id, item.owner_id)
            code, avail = await lua.reserve(
                item.branch_id, item.bm_id, item.owner_id, item.num, marker, ttl_seconds
            )
        return code, avail

    async def _lua_release(
        self, item: sc.FreezeReserveItem, marker: str, num: int
    ) -> tuple[int, int]:
        from app.infra.freeze_service import FreezeService as LuaFreeze

        lua = LuaFreeze(self.r)
        return await lua.release(
            item.branch_id, item.bm_id, item.owner_id, num, marker
        )

    async def _backfill(self, branch_id: int, bm_id: int, owner_id: int) -> None:
        row = await self.ledger.get_row(branch_id, bm_id, owner_id)
        if not row:
            return
        await self.r.hset(self.stock_key(branch_id, bm_id, owner_id), mapping={
            "store": int(row.store),
            "freeze": int(row.freeze),
            "arrive": int(row.arrive_store),
            "defective": int(row.defective),
            "safe_locked": int(row.safe_store) if row.is_locked == 1 else 0,
        })

    async def _available(self, branch_id: int, bm_id: int, owner_id: int) -> int:
        row = await self.ledger.get_row(branch_id, bm_id, owner_id)
        if not row:
            return 0
        return StockLedgerService.available_of(
            int(row.store), int(row.freeze), int(row.defective),
            int(row.safe_store), int(row.is_locked),
        )

    # ---------- 释放（FR-02）----------

    async def release(self, req: sc.FreezeReleaseRequest) -> sc.FreezeResult:
        """业务释放（取消/改单减量/审核驳回）"""
        q = select(InvFreezeLog).where(
            InvFreezeLog.obj_type == req.obj_type,
            InvFreezeLog.obj_bn == req.obj_bn,
            InvFreezeLog.status.in_([1, 2]),
        )
        if req.obj_item_id is not None:
            q = q.where(InvFreezeLog.obj_item_id == req.obj_item_id)
        logs = (await self.s.scalars(q.order_by(InvFreezeLog.id))).all()
        if not logs:
            # FR-02c 幂等：台账已全部释放/核销 → 重复释放返回成功（不报错）
            done_q = select(InvFreezeLog).where(
                InvFreezeLog.obj_type == req.obj_type,
                InvFreezeLog.obj_bn == req.obj_bn,
                InvFreezeLog.status.in_([3, 4]),
            )
            if req.obj_item_id is not None:
                done_q = done_q.where(InvFreezeLog.obj_item_id == req.obj_item_id)
            done = (await self.s.scalars(done_q)).all()
            if done:
                return sc.FreezeResult(
                    idempotent=True,
                    obj_type=req.obj_type,
                    obj_bn=req.obj_bn,
                    reserved_num=0,
                    available_after=await self._available(
                        done[0].branch_id, done[0].bm_id, done[0].owner_id
                    ),
                    logs=[sc.FreezeLogOut.model_validate(d) for d in done],
                    compensated=False,
                )
            raise NotFoundError(f"未找到可释放的预占: {req.obj_bn}")

        released = 0
        out: list[sc.FreezeLogOut] = []
        for log in logs:
            remain = log.num - log.settled_num - log.released_num
            if remain <= 0:
                continue
            num = min(remain, req.num) if req.num else remain
            await self._release_one(log, num, req.operator)
            released += num
            out.append(sc.FreezeLogOut.model_validate(log))
        return sc.FreezeResult(
            idempotent=False,
            obj_type=req.obj_type,
            obj_bn=req.obj_bn,
            reserved_num=released,
            available_after=await self._available(
                logs[0].branch_id, logs[0].bm_id, logs[0].owner_id
            ),
            logs=out,
            compensated=False,
        )

    async def _release_one(
        self, log: InvFreezeLog, num: int, operator: str = "", compensate: bool = False
    ) -> None:
        """单行释放：Redis freeze_decr → DB 台账状态 + 记账行 + 流水"""
        marker = self.marker_key(log.obj_type, log.obj_bn, log.obj_item_id)
        item = sc.FreezeReserveItem(
            branch_id=log.branch_id, bm_id=log.bm_id, owner_id=log.owner_id, num=num
        )
        code, _freeze_after = await self._lua_release(item, marker, num)
        if code == 0:
            # 台账标记已不存在（已释放/已核销）→ 幂等返回
            return
        log.released_num += num
        if log.settled_num + log.released_num >= log.num:
            log.status = 4  # 已释放
        else:
            log.status = 2  # 部分核销/部分释放
        log.version += 1
        if compensate:
            log.is_compensated = 1
        await self.s.commit()
        await self.ledger.apply_change(
            sc.StockChangeRequest(
                branch_id=log.branch_id,
                bm_id=log.bm_id,
                owner_id=log.owner_id,
                changes=[sc.StockChangeItem(field="freeze", delta=-num)],
                bill_type="freeze",
                bill_bn=log.obj_bn,
                bill_item_id=log.obj_item_id,
                action="release",
                operator=operator,
                source="compensate" if compensate else "oms",
                redis_synced=True,
            )
        )

    # ---------- 转扣减（FR-03）----------

    async def settle(self, req: sc.FreezeSettleRequest) -> sc.FreezeResult:
        """出库回传触发：freeze-N & store-N 原子（支持部分核销）"""
        log = await self.s.scalar(
            select(InvFreezeLog).where(
                InvFreezeLog.obj_type == req.obj_type,
                InvFreezeLog.obj_bn == req.obj_bn,
                InvFreezeLog.obj_item_id == req.obj_item_id,
                InvFreezeLog.status.in_([1, 2]),
            )
        )
        if not log:
            raise NotFoundError(f"未找到可核销的预占: {req.obj_bn}/{req.obj_item_id}")
        remain = log.num - log.settled_num - log.released_num
        if remain <= 0:
            raise ValidationError(f"预占已全部核销或释放，无法再核销: {log.obj_bn}")
        num = min(remain, req.num)
        if num < req.num:
            raise ValidationError(f"核销数量超过未核销余量 {remain}")

        marker = self.marker_key(log.obj_type, log.obj_bn, log.obj_item_id)
        from app.infra.freeze_service import FreezeService as LuaFreeze

        lua = LuaFreeze(self.r)
        code, store_after, freeze_after = await lua.settle(
            log.branch_id, log.bm_id, log.owner_id, num, marker
        )
        if code == 0:
            raise ConflictError("该预占已被释放或已核销（释放/核销互斥）", code="FREEZE_CONFLICT")

        log.settled_num += num
        log.status = 3 if log.settled_num + log.released_num >= log.num else 2
        log.version += 1
        await self.s.commit()
        await self.ledger.apply_change(
            sc.StockChangeRequest(
                branch_id=log.branch_id,
                bm_id=log.bm_id,
                owner_id=log.owner_id,
                changes=[
                    sc.StockChangeItem(field="freeze", delta=-num),
                    sc.StockChangeItem(field="store", delta=-num),
                ],
                bill_type=req.bill_type,
                bill_bn=req.bill_bn or log.obj_bn,
                bill_item_id=req.bill_item_id,
                action="settle",
                operator=req.operator,
                source="wms",
                redis_synced=True,
            )
        )
        return sc.FreezeResult(
            idempotent=False,
            obj_type=req.obj_type,
            obj_bn=req.obj_bn,
            reserved_num=num,
            available_after=await self._available(log.branch_id, log.bm_id, log.owner_id),
            logs=[sc.FreezeLogOut.model_validate(log)],
            compensated=False,
        )

    # ---------- 过期回收（FR-02b）----------

    async def expire_reclaim(self, limit: int = 500) -> dict:
        """过期回收：扫描超期未核销预占 → 自动释放"""
        now = datetime.now()
        logs = (await self.s.scalars(
            select(InvFreezeLog).where(
                InvFreezeLog.status.in_([1, 2]),
                InvFreezeLog.expire_time < now,
            ).order_by(InvFreezeLog.expire_time).limit(limit)
        )).all()
        reclaimed = 0
        for log in logs:
            remain = log.num - log.settled_num - log.released_num
            if remain <= 0:
                continue
            try:
                await self._release_one(log, remain, operator="system:expire")
                reclaimed += 1
            except Exception:
                continue
        return {"expired_found": len(logs), "reclaimed": reclaimed}

    # ---------- 台账查询（FR-04）----------

    async def query_logs(
        self,
        obj_type: int | None = None,
        obj_bn: str | None = None,
        branch_id: int | None = None,
        bm_id: int | None = None,
        owner_id: int | None = None,
        status: int | None = None,
        limit: int = 100,
    ) -> list[sc.FreezeLogOut]:
        q = select(InvFreezeLog)
        if obj_type:
            q = q.where(InvFreezeLog.obj_type == obj_type)
        if obj_bn:
            q = q.where(InvFreezeLog.obj_bn == obj_bn)
        if branch_id:
            q = q.where(InvFreezeLog.branch_id == branch_id)
        if bm_id:
            q = q.where(InvFreezeLog.bm_id == bm_id)
        if owner_id:
            q = q.where(InvFreezeLog.owner_id == owner_id)
        if status:
            q = q.where(InvFreezeLog.status == status)
        rows = (await self.s.scalars(q.order_by(InvFreezeLog.id.desc()).limit(limit))).all()
        return [sc.FreezeLogOut.model_validate(r) for r in rows]

    async def age_analysis(self, now: datetime | None = None) -> sc.FreezeAgeOut:
        """账龄分析（FR-04a：>24h/>48h/>72h 分级 + 已过期待处理）"""
        now = now or datetime.now()
        rows = (await self.s.scalars(
            select(InvFreezeLog).where(InvFreezeLog.status.in_([1, 2]))
        )).all()
        out = sc.FreezeAgeOut(total=len(rows), age_24h=0, age_48h=0, age_72h=0, expired_pending=0)
        for log in rows:
            age_h = (now - log.create_time).total_seconds() / 3600
            if age_h > 72:
                out.age_72h += 1
            elif age_h > 48:
                out.age_48h += 1
            elif age_h > 24:
                out.age_24h += 1
            if log.expire_time and log.expire_time < now:
                out.expired_pending += 1
        return out
