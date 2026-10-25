"""出入库单据中心（SRS-D04.04 FR-01/02/03/04/05/06）

核心机制（§5.1 口径影响模板驱动记账）：
  单据类型（inv_io_bill_type.effect_template）声明口径影响模板
    入库类：[{"field":"store","sign":1},{"field":"arrive_store","sign":-1}]
    销售出库：[{"action":"settle"}]  → 经 D04.03 预占转扣减（§5.5 强制）
  确认动作按模板逐行生成记账指令 → D04.02 change()（幂等键含 单据类型+单据号+行+动作）

状态机（§4.1）：
  本地记账类：草稿(1) → 已确认(5) → 已红冲(6)
  仓执行类：草稿(1) → 已下发(2) → 部分回传(3) → 全部回传(4) → 已确认(5)

§5.5 约束：非销售出库直接扣 store，但需校验 store − freeze ≥ 扣减量（不可动用已预占量）。
"""
from datetime import date, datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.stock import (
    InvIoBill,
    InvIoBillItem,
    InvIoBillType,
    InvStockChangeLog,
)
from app.schemas import stock as sc
from app.services.freeze import FreezeService
from app.services.stock_ledger import StockLedgerService

# 口径影响模板字段名（库内用 Redis hash 命名 arrive）→ 记账契约字段名
TEMPLATE_FIELD_MAP = {
    "store": "store",
    "freeze": "freeze",
    "arrive": "arrive_store",
    "defective": "defective",
}

# 单据状态
STATUS_DRAFT = 1
STATUS_PUSHED = 2
STATUS_PARTIAL = 3
STATUS_FULL = 4
STATUS_CONFIRMED = 5
STATUS_RED_FLUSHED = 6


class IoBillService:
    """出入库单据中心"""

    def __init__(self, session: AsyncSession, redis: Redis):
        self.s = session
        self.r = redis
        self.ledger = StockLedgerService(session, redis)
        self.freeze = FreezeService(session, redis)

    # ---------- 类型（FR-01）----------

    async def get_type(self, type_code: str) -> InvIoBillType:
        spec = await self.s.scalar(
            select(InvIoBillType).where(
                InvIoBillType.type_code == type_code,
                InvIoBillType.status == 1,
                InvIoBillType.is_deleted == 0,
            )
        )
        if not spec:
            raise NotFoundError(f"单据类型不存在或已停用: {type_code}")
        return spec

    async def list_types(self) -> list[InvIoBillType]:
        rows = (await self.s.scalars(
            select(InvIoBillType).where(InvIoBillType.is_deleted == 0).order_by(InvIoBillType.id)
        )).all()
        return list(rows)

    # ---------- 创建（FR-03）----------

    async def _next_bill_bn(self, type_code: str) -> str:
        """单号规则（§5.2）：{类型码}{YYYYMMDD}{6位序列}，全局唯一"""
        seq = await self.r.incr("seq:bill_bn")
        return f"{type_code}{date.today().strftime('%Y%m%d')}{seq % 1000000:06d}"

    async def create(self, req: sc.IoBillCreate, source: str = "local") -> sc.IoBillOut:
        """创建草稿单据（源单自动生成或人工创建）"""
        spec = await self.get_type(req.bill_type)
        bill = InvIoBill(
            tenant_id=1,
            owner_id=req.owner_id,
            bill_bn=await self._next_bill_bn(spec.type_code),
            bill_type=spec.type_code,
            direction=spec.direction,
            branch_id=req.branch_id,
            source_bill_type=req.source_bill_type,
            source_bill_bn=req.source_bill_bn,
            shop_id=req.shop_id,
            status=STATUS_DRAFT,
            settle_status=0 if spec.settle_rel == 0 else 1,
            operator=req.operator,
            memo=req.memo,
            source=source,
        )
        self.s.add(bill)
        await self.s.flush()
        for it in req.items:
            num = it.confirmed_num or it.issued_num
            self.s.add(
                InvIoBillItem(
                    tenant_id=1,
                    owner_id=req.owner_id,
                    bill_id=bill.id,
                    bill_bn=bill.bill_bn,
                    bm_id=it.bm_id,
                    issued_num=it.issued_num or num,
                    returned_num=0,
                    confirmed_num=it.confirmed_num,
                    defect_num=it.defect_num,
                    batch_no=it.batch_no,
                    unit_cost=it.unit_cost,
                    amount=round(it.unit_cost * num, 2),
                    remark=it.remark,
                )
            )
        await self.s.commit()
        return await self.get_bill(bill.id)

    # ---------- 查询 ----------

    async def _get_bill(self, bill_id: int) -> InvIoBill:
        bill = await self.s.scalar(select(InvIoBill).where(InvIoBill.id == bill_id))
        if not bill:
            raise NotFoundError(f"单据不存在: {bill_id}")
        return bill

    async def _items_of(self, bill_id: int) -> list[InvIoBillItem]:
        rows = (await self.s.scalars(
            select(InvIoBillItem).where(InvIoBillItem.bill_id == bill_id).order_by(InvIoBillItem.id)
        )).all()
        return list(rows)

    async def get_bill(self, bill_id: int) -> sc.IoBillOut:
        bill = await self._get_bill(bill_id)
        items = await self._items_of(bill_id)
        out = sc.IoBillOut.model_validate(bill)
        out.items = [sc.IoBillItemOut.model_validate(i) for i in items]
        return out

    async def query(
        self,
        bill_type: str | None = None,
        branch_id: int | None = None,
        status: int | None = None,
        source_bill_bn: str | None = None,
        limit: int = 100,
    ) -> list[sc.IoBillOut]:
        q = select(InvIoBill)
        if bill_type:
            q = q.where(InvIoBill.bill_type == bill_type)
        if branch_id:
            q = q.where(InvIoBill.branch_id == branch_id)
        if status:
            q = q.where(InvIoBill.status == status)
        if source_bill_bn:
            q = q.where(InvIoBill.source_bill_bn == source_bill_bn)
        bills = (await self.s.scalars(q.order_by(InvIoBill.id.desc()).limit(limit))).all()
        out: list[sc.IoBillOut] = []
        for b in bills:
            items = await self._items_of(b.id)
            o = sc.IoBillOut.model_validate(b)
            o.items = [sc.IoBillItemOut.model_validate(i) for i in items]
            out.append(o)
        return out

    # ---------- 生命周期（FR-02）----------

    async def push_to_wms(self, bill_id: int, wms_bill_no: str = "") -> sc.IoBillOut:
        """草稿 → 已下发 WMS（仓执行类）"""
        bill = await self._get_bill(bill_id)
        spec = await self.get_type(bill.bill_type)
        if not spec.need_wms:
            raise ValidationError(f"该类型无需 WMS 执行: {bill.bill_type}")
        if bill.status != STATUS_DRAFT:
            raise ConflictError(f"仅草稿可下发，当前状态 {bill.status}")
        bill.status = STATUS_PUSHED
        bill.wms_bill_no = wms_bill_no or bill.bill_bn
        bill.version += 1
        await self.s.commit()
        return await self.get_bill(bill_id)

    async def receive_callback(self, bill_id: int, cb: sc.IoBillCallback) -> sc.IoBillOut:
        """WMS 回传（FR-02c：分批累计，回传数量 ≤ 下发数量）"""
        bill = await self._get_bill(bill_id)
        if bill.status not in (STATUS_PUSHED, STATUS_PARTIAL):
            raise ConflictError(f"当前状态不可回传: {bill.status}")
        items = await self._items_of(bill_id)
        by_bm = {i.bm_id: i for i in items}
        for cb_item in cb.items:
            row = by_bm.get(cb_item.bm_id)
            if not row:
                raise ValidationError(f"回传物料不在单据内: bm_id={cb_item.bm_id}")
            num = cb_item.confirmed_num or cb_item.issued_num
            row.returned_num += num
            if row.returned_num > row.issued_num:
                raise ValidationError(
                    f"回传累计 {row.returned_num} 超过下发 {row.issued_num}（物料 {row.bm_id}）"
                )
            row.confirmed_num = row.returned_num
            if cb_item.defect_num:
                row.defect_num = cb_item.defect_num
        all_done = all(i.returned_num >= i.issued_num for i in items)
        bill.status = STATUS_FULL if all_done else STATUS_PARTIAL
        bill.version += 1
        await self.s.commit()
        return await self.get_bill(bill_id)

    async def confirm(self, bill_id: int, operator: str = "") -> sc.IoBillOut:
        """确认即记账（FR-02b）：按类型口径模板逐行生成记账指令"""
        bill = await self._get_bill(bill_id)
        spec = await self.get_type(bill.bill_type)
        if bill.status not in (STATUS_DRAFT, STATUS_FULL):
            raise ConflictError(f"当前状态不可确认: {bill.status}")
        items = await self._items_of(bill_id)
        template = spec.effect_template or []
        if not template:
            raise ValidationError(f"单据类型未配置口径影响模板: {bill.bill_type}")

        for item in items:
            owner_id = item.owner_id or bill.owner_id
            num = item.confirmed_num or item.issued_num
            if num <= 0:
                continue
            for eff in template:
                action = eff.get("action")
                if action == "settle":
                    # 销售出库必须经 D04.03 转扣减（§5.5）
                    await self.freeze.settle(
                        sc.FreezeSettleRequest(
                            obj_type=1,
                            obj_bn=bill.source_bill_bn or bill.bill_bn,
                            obj_item_id=item.id,
                            num=num,
                            bill_type=bill.bill_type,
                            bill_bn=bill.bill_bn,
                            bill_item_id=item.id,
                            operator=operator,
                        )
                    )
                    continue
                field = TEMPLATE_FIELD_MAP.get(eff.get("field"), eff.get("field"))
                sign = int(eff.get("sign", 1))
                delta = num * sign
                # §5.5：出库扣实际库存不得动用已预占量
                if field == "store" and delta < 0:
                    await self._assert_not_frozen(
                        bill.branch_id, item.bm_id, owner_id, abs(delta)
                    )
                await self.ledger.apply_change(
                    sc.StockChangeRequest(
                        branch_id=bill.branch_id,
                        bm_id=item.bm_id,
                        owner_id=owner_id,
                        changes=[sc.StockChangeItem(field=field, delta=delta)],
                        bill_type=bill.bill_type,
                        bill_bn=bill.bill_bn,
                        bill_item_id=item.id,
                        action="inbound" if sign > 0 else "outbound",
                        operator=operator or bill.operator,
                        source="oms",
                    )
                )
        bill.status = STATUS_CONFIRMED
        bill.confirm_time = datetime.now()
        bill.version += 1
        await self.s.commit()
        return await self.get_bill(bill_id)

    async def _assert_not_frozen(
        self, branch_id: int, bm_id: int, owner_id: int, need: int
    ) -> None:
        """§5.5：出库扣减量不得超过（实际库存 − 锁定库存）"""
        row = await self.ledger.get_row(branch_id, bm_id, owner_id)
        if not row:
            raise ValidationError("记账行不存在，无法出库")
        free = int(row.store) - int(row.freeze)
        if need > free:
            raise ValidationError(
                f"出库数量 {need} 超过可用（实际 {row.store} − 锁定 {row.freeze} = {free}），"
                "不可动用已预占库存"
            )

    # ---------- 红冲（FR-04）----------

    async def red_flush(self, bill_id: int, req: sc.RedFlushRequest) -> sc.IoBillOut:
        """红冲：生成反向单据并反向记账（已确认单据不可改删，仅可红冲）"""
        bill = await self._get_bill(bill_id)
        if bill.status != STATUS_CONFIRMED:
            raise ConflictError(f"仅已确认单据可红冲，当前状态 {bill.status}")
        if bill.settle_status in (3, 4):
            raise ConflictError("单据已结算/结算锁定，红冲需先在财务侧解锁（FR-05b）")
        spec = await self.get_type(bill.bill_type)
        items = await self._items_of(bill_id)
        template = spec.effect_template or []

        # 生成红冲单（单号 = 原单号 + R）
        red = InvIoBill(
            tenant_id=bill.tenant_id,
            owner_id=bill.owner_id,
            bill_bn=f"{bill.bill_bn}R",
            bill_type=bill.bill_type,
            direction=bill.direction,
            branch_id=bill.branch_id,
            source_bill_type=bill.source_bill_type,
            source_bill_bn=bill.source_bill_bn,
            shop_id=bill.shop_id,
            status=STATUS_CONFIRMED,
            red_flush_of=bill.bill_bn,
            settle_status=0,
            operator=req.operator,
            confirm_time=datetime.now(),
            memo=f"红冲：{req.reason}",
            source="manual",
        )
        self.s.add(red)
        await self.s.flush()
        for it in items:
            num = it.confirmed_num or it.issued_num
            self.s.add(
                InvIoBillItem(
                    tenant_id=bill.tenant_id,
                    owner_id=bill.owner_id,
                    bill_id=red.id,
                    bill_bn=red.bill_bn,
                    bm_id=it.bm_id,
                    issued_num=num,
                    confirmed_num=num,
                    defect_num=it.defect_num,
                    batch_no=it.batch_no,
                    unit_cost=it.unit_cost,
                    amount=round(it.unit_cost * num, 2),
                    remark=f"红冲 {it.remark}".strip(),
                )
            )
        await self.s.flush()

        # 反向记账
        for item in await self._items_of(red.id):
            owner_id = item.owner_id or red.owner_id
            num = item.confirmed_num or item.issued_num
            for eff in template:
                if eff.get("action") == "settle":
                    continue  # 预占转扣减不可反向（需人工核对）
                field = TEMPLATE_FIELD_MAP.get(eff.get("field"), eff.get("field"))
                sign = int(eff.get("sign", 1))
                await self.ledger.apply_change(
                    sc.StockChangeRequest(
                        branch_id=red.branch_id,
                        bm_id=item.bm_id,
                        owner_id=owner_id,
                        changes=[sc.StockChangeItem(field=field, delta=-num * sign)],
                        bill_type=red.bill_type,
                        bill_bn=red.bill_bn,
                        bill_item_id=item.id,
                        action="red_flush",
                        operator=req.operator,
                        source="manual",
                    )
                )
        bill.status = STATUS_RED_FLUSHED
        bill.version += 1
        await self.s.commit()
        return await self.get_bill(red.id)

    # ---------- 结算（FR-05）----------

    async def set_settle(self, bill_id: int, req: sc.SettleUpdateRequest) -> sc.IoBillOut:
        """结算状态回写（由财务/采购对账流程回写）"""
        bill = await self._get_bill(bill_id)
        bill.settle_status = req.settle_status
        bill.settle_bn = req.settle_bn
        bill.settle_num = req.settle_num
        bill.settle_money = req.settle_money
        bill.version += 1
        await self.s.commit()
        return await self.get_bill(bill_id)

    # ---------- 追溯（FR-06）----------

    async def trace(self, bill_id: int) -> sc.IoBillTraceOut:
        """追溯链：单据 → 行 → 流水 → 记账行余额"""
        bill = await self.get_bill(bill_id)
        logs = (await self.s.scalars(
            select(InvStockChangeLog).where(
                (InvStockChangeLog.bill_bn == bill.bill_bn)
                | (InvStockChangeLog.bill_bn == f"{bill.bill_bn}R")
            ).order_by(InvStockChangeLog.id)
        )).all()
        ledger_state: dict[str, int] = {}
        for item in bill.items:
            row = await self.ledger.get_row(bill.branch_id, item.bm_id, item.owner_id or bill.owner_id)
            if row:
                ledger_state.update({
                    f"bm_{item.bm_id}_store": int(row.store),
                    f"bm_{item.bm_id}_freeze": int(row.freeze),
                    f"bm_{item.bm_id}_available": StockLedgerService.available_of(
                        int(row.store), int(row.freeze), int(row.defective),
                        int(row.safe_store), int(row.is_locked),
                    ),
                })
        return sc.IoBillTraceOut(
            bill=bill,
            change_logs=[
                {
                    "id": lg.id,
                    "bm_id": lg.bm_id,
                    "change_field": lg.change_field,
                    "change_num": lg.change_num,
                    "before_balance": lg.before_balance,
                    "after_balance": lg.after_balance,
                    "action": lg.action,
                    "bill_bn": lg.bill_bn,
                    "create_time": str(lg.create_time),
                }
                for lg in logs
            ],
            ledger=ledger_state,
        )
