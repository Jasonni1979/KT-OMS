"""三元记账 + 五口径余额维护（SRS-D04.02 FR-01/02/03，本模块 = 全局契约定义源）

核心契约：
- 三元键 = 仓(branch_id) × 物料(bm_id) × 货主(owner_id)
- 五口径：store(实际) / freeze(锁定) / arrive_store(在途) / defective(次品) / safe_store(安全库存)
- **可用库存为派生计算值（不落库）**：
      available = store − freeze − defective − (is_locked ? safe_store : 0)   （§5.1 唯一公式）
- 记账写序：**DB 权威先行（行锁串行）→ 同步 Redis**；Redis 失败由对账兜底（≤5 分钟），
  对应 §5.4「流水落库与余额缓存最终一致」
- 流水只增不改不删（FR-03b）：每口径一条，含 before/after 快照 + 幂等键
- 幂等：idempotent_key = bill_type:bill_item_id:action:field（§5.2 幂等责任在调用方）
"""
from datetime import date, datetime
from pathlib import Path

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.models.material import InvMaterial
from app.models.org import OrgOwner
from app.models.stock import (
    InvStockChangeLog,
    InvStockConfig,
    InvStockLedger,
    InvStockSnapshot,
)
from app.schemas import stock as sc

LUA_DIR = Path(__file__).resolve().parents[1] / "infra" / "lua"

# 口径 → Redis hash field（对齐 M0 Lua 脚本族命名：arrive_store → arrive）
REDIS_FIELD = {
    "store": "store",
    "freeze": "freeze",
    "arrive_store": "arrive",
    "defective": "defective",
}
# 各口径下限（freeze/arrive/defective 恒 >=0；store 受负卖开关控制）
FIELD_MIN = {"store": 0, "freeze": 0, "arrive_store": 0, "defective": 0}


class StockLedgerService:
    """五口径记账服务"""

    def __init__(self, session: AsyncSession, redis: Redis):
        self.s = session
        self.r = redis
        self._change_script = redis.register_script(
            (LUA_DIR / "stock_change.lua").read_text()
        )

    # ---------- 键与可用量 ----------

    @staticmethod
    def stock_key(branch_id: int, bm_id: int, owner_id: int) -> str:
        return f"inv:{branch_id}:{bm_id}:{owner_id}"

    @staticmethod
    def available_of(
        store: int, freeze: int, defective: int, safe_store: int, is_locked: int
    ) -> int:
        """可用库存（§5.1 全局唯一公式，任何模块不得自行另算）"""
        locked_safe = safe_store if is_locked == 1 else 0
        return store - freeze - defective - locked_safe

    # ---------- 记账行 ----------

    async def get_row(
        self, branch_id: int, bm_id: int, owner_id: int, for_update: bool = False
    ) -> InvStockLedger | None:
        q = select(InvStockLedger).where(
            InvStockLedger.branch_id == branch_id,
            InvStockLedger.bm_id == bm_id,
            InvStockLedger.owner_id == owner_id,
            InvStockLedger.is_deleted == 0,
        )
        if for_update:
            q = q.with_for_update()
        return await self.s.scalar(q)

    async def open_row(
        self, branch_id: int, bm_id: int, owner_id: int, tenant_id: int = 1
    ) -> InvStockLedger:
        """自动开立记账行（FR-01a：任何记账动作遇无行时开立，初始全口径 0）"""
        row = await self.get_row(branch_id, bm_id, owner_id)
        if row:
            return row
        # 引用校验：货主必须存在
        owner = await self.s.scalar(
            select(OrgOwner).where(OrgOwner.id == owner_id, OrgOwner.is_deleted == 0)
        )
        if not owner:
            raise ValidationError(f"货主不存在: {owner_id}")
        row = InvStockLedger(
            tenant_id=tenant_id,
            owner_id=owner_id,
            branch_id=branch_id,
            bm_id=bm_id,
            status=1,
        )
        self.s.add(row)
        await self.s.flush()
        return row

    # ---------- 负卖开关（FR-02c）----------

    async def allow_negative(self, branch_id: int, owner_id: int) -> bool:
        """负卖开关：按「仓库×货主 > 仓库 > 货主 > 全局」优先级取配置"""
        scopes = [
            (5, f"branch:{branch_id}:owner:{owner_id}"),
            (4, str(branch_id)),
            (2, str(owner_id)),
            (1, ""),
        ]
        for scope_type, scope_ref in scopes:
            cfg = await self.s.scalar(
                select(InvStockConfig).where(
                    InvStockConfig.config_type == 1,
                    InvStockConfig.scope_type == scope_type,
                    InvStockConfig.scope_ref == scope_ref,
                    InvStockConfig.status == 1,
                    InvStockConfig.is_deleted == 0,
                )
            )
            if cfg:
                data = cfg.config_json or {}
                if isinstance(data, dict):
                    return bool(data.get("allow_negative", 0))
        return False

    # ---------- 核心记账 ----------

    async def apply_change(self, req: sc.StockChangeRequest) -> sc.StockChangeResult:
        """口径记账（FR-02/FR-03）

        流程：幂等检查 → 行锁取行 → 逐口径计算与校验 → DB 落库（行+流水）→ 同步 Redis
        """
        # ① 幂等检查（FR-03d：同一幂等键不重复记账）
        keys = [self._idem_key(req, c.field) for c in req.changes]
        existing = (
            await self.s.scalars(
                select(InvStockChangeLog).where(
                    InvStockChangeLog.idempotent_key.in_(keys)
                )
            )
        ).all()
        if existing:
            row = await self.get_row(req.branch_id, req.bm_id, req.owner_id)
            balances = {
                f: getattr(row, f) if row else 0
                for f in ("store", "freeze", "arrive_store", "defective")
            }
            return sc.StockChangeResult(
                idempotent=True,
                balances=balances,
                available=self._available_of_row(row),
                change_log_ids=[e.id for e in existing],
            )

        # ② 行锁取记账行（同一三元键的并发记账串行化）
        row = await self.get_row(req.branch_id, req.bm_id, req.owner_id, for_update=True)
        if not row:
            row = await self.open_row(req.branch_id, req.bm_id, req.owner_id)

        allow_neg = await self.allow_negative(req.branch_id, req.owner_id)
        now = datetime.now()

        # ③ 逐口径计算 + 负库存下限校验
        planned: list[tuple[sc.StockChangeItem, int, int]] = []
        for c in req.changes:
            before = int(getattr(row, c.field))
            after = before + c.delta
            min_allowed = FIELD_MIN[c.field]
            if after < min_allowed and not (c.field == "store" and allow_neg):
                raise ValidationError(
                    f"{c.field} 余额不足：当前 {before}，本次变动 {c.delta}，"
                    f"下限 {min_allowed}（如需负卖请在库存配置开启负卖开关）"
                )
            planned.append((c, before, after))

        # ④ DB 落库（记账行 + 流水，同事务）
        log_ids: list[int] = []
        for c, before, after in planned:
            setattr(row, c.field, after)
            log = InvStockChangeLog(
                tenant_id=row.tenant_id,
                owner_id=req.owner_id,
                branch_id=req.branch_id,
                bm_id=req.bm_id,
                change_field=c.field,
                change_num=c.delta,
                before_balance=before,
                after_balance=after,
                bill_type=req.bill_type,
                bill_bn=req.bill_bn,
                bill_item_id=req.bill_item_id,
                action=req.action,
                operator=req.operator,
                source=req.source,
                idempotent_key=self._idem_key(req, c.field),
                create_time=now,
            )
            self.s.add(log)
            await self.s.flush()
            log_ids.append(log.id)

        if row.status != 1:
            row.status = 1  # 新记账动作自动重开停用行
        row.version += 1
        row.update_time = now
        await self.s.commit()

        # ⑤ 同步 Redis（Lua 原子；miss → 回填；失败不影响 DB 权威，由对账兜底）
        #    预占/核销场景 Redis 已由 FreezeService 的 Lua 原子更新 → 跳过，避免重复累加
        if not req.redis_synced:
            await self._sync_redis(req, planned)

        fresh = await self.get_row(req.branch_id, req.bm_id, req.owner_id)
        balances = {
            f: int(getattr(fresh, f))
            for f in ("store", "freeze", "arrive_store", "defective")
        }
        return sc.StockChangeResult(
            idempotent=False,
            balances=balances,
            available=self._available_of_row(fresh),
            change_log_ids=log_ids,
        )

    async def _sync_redis(
        self, req: sc.StockChangeRequest, planned: list[tuple[sc.StockChangeItem, int, int]]
    ) -> None:
        """Redis 同步：miss 时用 DB 余额回填后再应用变更（FR-05b 降级路径）"""
        key = self.stock_key(req.branch_id, req.bm_id, req.owner_id)
        allow_neg = "1" if await self.allow_negative(req.branch_id, req.owner_id) else "0"
        try:
            if not await self.r.exists(key):
                # miss 降级（FR-05b）：DB 已是变更后的权威值 → 直接回填最终余额，
                # 不可再叠加 delta（否则重复累加）
                row = await self.get_row(req.branch_id, req.bm_id, req.owner_id)
                if row:
                    await self.r.hset(key, mapping={
                        "store": int(row.store),
                        "freeze": int(row.freeze),
                        "arrive": int(row.arrive_store),
                        "defective": int(row.defective),
                        "safe_locked": int(row.safe_store) if row.is_locked == 1 else 0,
                    })
                return
            for c, _before, _after in planned:
                await self._change_script(
                    keys=[key],
                    args=[REDIS_FIELD[c.field], c.delta, allow_neg, FIELD_MIN[c.field]],
                )
        except Exception:
            # Redis 不可用不阻断记账（DB 为权威）；由 5 分钟对账兜底
            pass

    @staticmethod
    def _idem_key(req: sc.StockChangeRequest, field: str) -> str:
        """幂等键 = 单据类型 + 单据号 + 行 + 动作 + 口径（§5.2「单据+行+动作」）

        必须含单据号：否则不同单据的同 (类型,行,动作) 会互相撞键，导致后续单据被误判为重复。
        """
        return f"{req.bill_type}:{req.bill_bn}:{req.bill_item_id}:{req.action}:{field}"

    @staticmethod
    def _available_of_row(row: InvStockLedger | None) -> int:
        if not row:
            return 0
        return StockLedgerService.available_of(
            int(row.store), int(row.freeze), int(row.defective),
            int(row.safe_store), int(row.is_locked),
        )

    # ---------- 查询（FR-01c）----------

    async def get_balance(
        self, branch_id: int, bm_id: int, owner_id: int
    ) -> sc.StockLedgerOut:
        row = await self.get_row(branch_id, bm_id, owner_id)
        if not row:
            raise NotFoundError(f"记账行不存在: 仓{branch_id}/物料{bm_id}/货主{owner_id}")
        mat = await self.s.scalar(
            select(InvMaterial).where(InvMaterial.id == row.bm_id)
        )
        return sc.StockLedgerOut(
            branch_id=row.branch_id,
            bm_id=row.bm_id,
            owner_id=row.owner_id,
            store=int(row.store),
            freeze=int(row.freeze),
            arrive_store=int(row.arrive_store),
            defective=int(row.defective),
            safe_store=int(row.safe_store),
            is_locked=int(row.is_locked),
            available=self._available_of_row(row),
            unit_cost=float(row.unit_cost),
            inventory_cost=float(row.inventory_cost),
            status=int(row.status),
            material_bn=mat.material_bn if mat else "",
            material_name=mat.material_name if mat else "",
        )

    async def query(
        self,
        branch_id: int | None = None,
        owner_id: int | None = None,
        brand_id: int | None = None,
        cat_id: int | None = None,
        keyword: str | None = None,
        limit: int = 200,
    ) -> list[sc.StockLedgerOut]:
        """多维查询五口径余额（仓/货主/品牌/分类；数据权限自动过滤）"""
        q = select(InvStockLedger).where(InvStockLedger.is_deleted == 0)
        if branch_id:
            q = q.where(InvStockLedger.branch_id == branch_id)
        if owner_id:
            q = q.where(InvStockLedger.owner_id == owner_id)
        q = q.join(InvMaterial, InvMaterial.id == InvStockLedger.bm_id)
        if brand_id:
            q = q.where(InvMaterial.brand_id == brand_id)
        if cat_id:
            q = q.where(InvMaterial.cat_id == cat_id)
        if keyword:
            like = f"%{keyword}%"
            q = q.where(
                (InvMaterial.material_bn.like(like)) | (InvMaterial.material_name.like(like))
            )
        rows = (await self.s.scalars(q.order_by(InvStockLedger.id).limit(limit))).all()
        out: list[sc.StockLedgerOut] = []
        for row in rows:
            mat = await self.s.scalar(select(InvMaterial).where(InvMaterial.id == row.bm_id))
            out.append(
                sc.StockLedgerOut(
                    branch_id=row.branch_id,
                    bm_id=row.bm_id,
                    owner_id=row.owner_id,
                    store=int(row.store),
                    freeze=int(row.freeze),
                    arrive_store=int(row.arrive_store),
                    defective=int(row.defective),
                    safe_store=int(row.safe_store),
                    is_locked=int(row.is_locked),
                    available=self._available_of_row(row),
                    unit_cost=float(row.unit_cost),
                    inventory_cost=float(row.inventory_cost),
                    status=int(row.status),
                    material_bn=mat.material_bn if mat else "",
                    material_name=mat.material_name if mat else "",
                )
            )
        return out

    # ---------- 人工调整（FR-04）----------

    async def adjust(self, req: sc.StockAdjustRequest) -> sc.StockChangeResult:
        """人工库存调整（FR-04c：生效即记账 + 流水，单据号=调整单号）"""
        if req.adjust_num == 0:
            raise ValidationError("调整数量不可为 0")
        change = sc.StockChangeRequest(
            branch_id=req.branch_id,
            bm_id=req.bm_id,
            owner_id=req.owner_id,
            changes=[sc.StockChangeItem(field=req.field, delta=req.adjust_num)],
            bill_type="adjust",
            bill_bn=f"ADJ{req.operator or 'SYS'}{datetime.now().strftime('%Y%m%d%H%M%S')}",
            bill_item_id=0,
            action="adjust",
            operator=req.operator,
            source="manual",
            remark=req.reason,
        )
        return await self.apply_change(change)

    # ---------- 快照（FR-06a）----------

    async def make_snapshot(self, snap_date: date | None = None) -> int:
        """日终库存快照（FR-06a）"""
        snap_date = snap_date or date.today()
        rows = (await self.s.scalars(
            select(InvStockLedger).where(InvStockLedger.is_deleted == 0)
        )).all()
        count = 0
        for row in rows:
            exists = await self.s.scalar(
                select(InvStockSnapshot.id).where(
                    InvStockSnapshot.snapshot_date == snap_date,
                    InvStockSnapshot.branch_id == row.branch_id,
                    InvStockSnapshot.bm_id == row.bm_id,
                    InvStockSnapshot.owner_id == row.owner_id,
                )
            )
            if exists:
                continue
            self.s.add(
                InvStockSnapshot(
                    tenant_id=row.tenant_id,
                    owner_id=row.owner_id,
                    snapshot_date=snap_date,
                    branch_id=row.branch_id,
                    bm_id=row.bm_id,
                    store=int(row.store),
                    freeze=int(row.freeze),
                    arrive_store=int(row.arrive_store),
                    defective=int(row.defective),
                    safe_store=int(row.safe_store),
                    available_num=self._available_of_row(row),
                    unit_cost=float(row.unit_cost),
                    inventory_cost=float(row.inventory_cost),
                )
            )
            count += 1
        await self.s.commit()
        return count
