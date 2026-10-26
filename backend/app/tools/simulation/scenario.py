"""业务场景串联执行器（M1c-5）

把已完成的各域按**一条真实业务链路**串起来跑通，验证跨模块契约衔接无冲突
（避免 W5+ 履约域开工后返工）。

链路：

```
① 主数据准备  货主 → 店铺 → 仓库 → 仓货主关系 → 基础物料 → 销售物料 → BOM 绑定
② 期初建账    期初入库 → 记账行(仓×物料×货主) + 库存流水
③ 平台下单    模拟器造单（平台 SKU = 本地销售物料编码）
④ 拉单接入    水位窗口拉取 → canonical → 缓冲池 → 订单落库（BOM 展开快照）
⑤ 库存预占    按订单行（仓×物料×货主）预占 → freeze 口径增加、可用减少
⑥ 出库单据    销售出库单（源单=订单号，源行=订单行ID）→ 下发 → 回传 → 确认即记账
⑦ 账实核对    断言：store 扣减、freeze 核销归零、可用库存、流水条数、单据状态
```

每步产出断言结果（PASS/FAIL + 实测值），可作为交付演示与回归基线。
"""

from dataclasses import dataclass, field

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AuthContext, SessionFactory, set_auth_context
from app.models.order import OrdOrder, OrdOrderItem
from app.models.shop import GwShop
from app.models.stock import InvStockChangeLog, InvStockLedger
from app.modules.m1_master.service.master import get_redis
from app.modules.m2_stock.service.freeze import FreezeService
from app.modules.m2_stock.service.io_bill import IoBillService
from app.modules.m2_stock.service.stock_ledger import StockLedgerService
from app.modules.m7_integration.service.gateway import get_gateway
from app.modules.m7_integration.service.pull import PullService
from app.schemas import stock as sc

#: 模拟器内置商品池（**必须与 mocks/platform/app/store.py 的 ITEM_POOL 完全一致**）
#: 模拟器造单时随机取池内商品 → 少建一个 SKU 就会随机落空（订单行未解析）
SIM_ITEM_POOL = [
    ("ITEM_TSHIRT_001", "SKU_TSHIRT_S", "纯棉圆领T恤", "S/白色"),
    ("ITEM_TSHIRT_002", "SKU_TSHIRT_M", "纯棉圆领T恤", "M/黑色"),
    ("ITEM_PANTS_001", "SKU_PANTS_32", "休闲直筒长裤", "32/深蓝"),
    ("ITEM_JACKET_001", "SKU_JACKET_L", "防风夹克", "L/军绿"),
    ("ITEM_SOCKS_001", "SKU_SOCKS_35", "纯棉中筒袜", "35/均码"),
]


@dataclass
class StepResult:
    """单步断言结果"""

    step: str
    name: str
    passed: bool
    detail: str = ""
    values: dict = field(default_factory=dict)

    def line(self) -> str:
        mark = "PASS" if self.passed else "FAIL"
        detail = f" | {self.detail}" if self.detail else ""
        return f"[{mark}] {self.step}. {self.name}{detail}"


@dataclass
class ScenarioReport:
    """场景执行报告"""

    steps: list[StepResult] = field(default_factory=list)

    def add(self, step: str, name: str, passed: bool, detail: str = "", **values) -> None:
        self.steps.append(StepResult(step, name, passed, detail, values))

    @property
    def ok(self) -> bool:
        return all(s.passed for s in self.steps)

    def render(self) -> str:
        lines = [s.line() for s in self.steps]
        passed = sum(1 for s in self.steps if s.passed)
        lines.append("-" * 72)
        lines.append(f"合计：{passed}/{len(self.steps)} 项通过")
        return "\n".join(lines)


class ScenarioRunner:
    """业务场景执行器（超管上下文，直连服务层）"""

    def __init__(self, session: AsyncSession, redis: Redis, gateway_url: str = ""):
        self.s = session
        self.r = redis
        if gateway_url:
            from app.core.config import settings

            settings.platform_gateway_url = gateway_url
        set_auth_context(AuthContext(tenant_id=1, is_superuser=True))

    # ---------- ⓪ 幂等清理 ----------

    async def cleanup(self) -> int:
        """清理上次场景残留（保证脚本可重复执行，数据不膨胀）"""
        from sqlalchemy import text

        stmts = [
            # 库存侧
            "DELETE FROM oms_stock.inv_stock_change_log WHERE bill_bn LIKE 'SCN_%'",
            "DELETE FROM oms_stock.inv_stock_ledger WHERE bm_id IN "
            "(SELECT id FROM oms_stock.inv_material WHERE material_bn LIKE 'SCN\\_%')",
            "DELETE FROM oms_stock.inv_freeze_log WHERE obj_bn LIKE 'P%' AND source = 'scenario'",
            "DELETE FROM oms_stock.inv_io_bill_item WHERE bill_id IN "
            "(SELECT id FROM oms_stock.inv_io_bill WHERE bill_bn LIKE 'SCN_%' "
            " OR owner_id IN (SELECT id FROM oms_org.org_owner WHERE owner_code LIKE 'SCN\\_%'))",
            "DELETE FROM oms_stock.inv_io_bill WHERE bill_bn LIKE 'SCN_%' "
            "OR owner_id IN (SELECT id FROM oms_org.org_owner WHERE owner_code LIKE 'SCN\\_%')",
            # 物料侧
            "DELETE FROM oms_stock.inv_bom_item WHERE sm_id IN "
            "(SELECT id FROM oms_stock.inv_sales_material WHERE sales_material_bn LIKE 'SKU\\_%')",
            "DELETE FROM oms_stock.inv_bom_version WHERE sm_id IN "
            "(SELECT id FROM oms_stock.inv_sales_material WHERE sales_material_bn LIKE 'SKU\\_%')",
            "DELETE FROM oms_stock.inv_sales_material WHERE sales_material_bn LIKE 'SKU\\_%'",
            "DELETE FROM oms_stock.inv_material WHERE material_bn LIKE 'SCN\\_%'",
            # 订单侧
            "DELETE FROM oms_order.ord_order_item WHERE order_id IN "
            "(SELECT id FROM oms_order.ord_order WHERE shop_id IN "
            "(SELECT id FROM oms_gateway.gw_shop WHERE shop_bn LIKE 'SCN\\_%'))",
            "DELETE FROM oms_order.ord_order_pmt WHERE order_id IN "
            "(SELECT id FROM oms_order.ord_order WHERE shop_id IN "
            "(SELECT id FROM oms_gateway.gw_shop WHERE shop_bn LIKE 'SCN\\_%'))",
            "DELETE FROM oms_order.ord_receiver WHERE order_id IN "
            "(SELECT id FROM oms_order.ord_order WHERE shop_id IN "
            "(SELECT id FROM oms_gateway.gw_shop WHERE shop_bn LIKE 'SCN\\_%'))",
            "DELETE FROM oms_order.ord_status_log WHERE order_id IN "
            "(SELECT id FROM oms_order.ord_order WHERE shop_id IN "
            "(SELECT id FROM oms_gateway.gw_shop WHERE shop_bn LIKE 'SCN\\_%'))",
            "DELETE FROM oms_order.ord_order WHERE shop_id IN "
            "(SELECT id FROM oms_gateway.gw_shop WHERE shop_bn LIKE 'SCN\\_%')",
            "DELETE FROM oms_order.ord_order_fail WHERE shop_id IN "
            "(SELECT id FROM oms_gateway.gw_shop WHERE shop_bn LIKE 'SCN\\_%')",
            # 网关侧
            "DELETE FROM oms_gateway.gw_order_buffer_item WHERE buffer_id IN "
            "(SELECT id FROM oms_gateway.gw_order_buffer WHERE shop_id IN "
            "(SELECT id FROM oms_gateway.gw_shop WHERE shop_bn LIKE 'SCN\\_%'))",
            "DELETE FROM oms_gateway.gw_order_buffer WHERE shop_id IN "
            "(SELECT id FROM oms_gateway.gw_shop WHERE shop_bn LIKE 'SCN\\_%')",
            "DELETE FROM oms_gateway.gw_pull_watermark WHERE shop_id IN "
            "(SELECT id FROM oms_gateway.gw_shop WHERE shop_bn LIKE 'SCN\\_%')",
            # 档案侧
            "DELETE FROM oms_gateway.gw_shop WHERE shop_bn LIKE 'SCN\\_%'",
            "DELETE FROM oms_org.org_node_relation WHERE node_id IN "
            "(SELECT id FROM oms_org.org_node WHERE org_code LIKE 'SHOP\\_SCN%')",
            "DELETE FROM oms_org.org_node WHERE org_code LIKE 'SHOP\\_SCN%'",
            "DELETE FROM oms_org.org_owner WHERE owner_code LIKE 'SCN\\_%'",
        ]
        n = 0
        for stmt in stmts:
            res = await self.s.execute(text(stmt))
            n += int(getattr(res, 'rowcount', 0) or 0)
        await self.s.commit()
        return n

    # ---------- ① 主数据 ----------

    async def prepare_master_data(self) -> dict:
        """准备货主/店铺/仓库/仓货主关系/物料/BOM"""
        from app.models.material import InvMaterial
        from app.models.org import OrgOwner
        from app.modules.m2_stock.service.material import BomService, SalesMaterialService
        from app.schemas.material import BomBind, BomItemIn, SalesMaterialCreate

        owner = OrgOwner(
            tenant_id=1,
            owner_code="SCN_OWNER",
            owner_name="场景货主",
            owner_type="KC_BUYOUT",
            org_node_id=await self._owner_co_node_id(),
            status=1,
        )
        self.s.add(owner)
        await self.s.flush()

        shop = GwShop(
            tenant_id=1,
            owner_id=owner.id,
            shop_bn="SCN_SHOP_001",
            shop_name="场景天猫店",
            platform="taobao",
            platform_shop_id="scn_shop_001",
            shop_type="flagship",
            business_type="direct_sale",
            auth_status="normal",
            status="enabled",
        )
        self.s.add(shop)
        await self.s.flush()

        # 仓（复用档案域建仓逻辑 → 自动联动组织树与归属货主绑定）
        branch = await self._make_branch(shop, owner)

        # 店铺-发货仓绑定（可售计算的多仓聚合依据，FR-02c）
        await self._bind_shop_branches(shop.id, [branch["id"]])

        material = InvMaterial(
            tenant_id=1,
            owner_id=owner.id,
            material_bn="SCN_MAT_001",
            material_name="场景基础物料",
            type=3,
            cat_id=0,
            cat_path="",
            brand_id=0,
            status=1,
        )
        self.s.add(material)
        await self.s.flush()

        # 为模拟器商品池中的**全部 SKU** 建销售物料并绑定 BOM
        # （模拟器造单时随机取池内商品 → 只建一个 SKU 会随机落空，导致订单行未解析）
        sm = SalesMaterialService(self.s)
        bom = BomService(self.s)
        sm_ids: dict[str, int] = {}
        for _item_id, sku_id, title, spec in SIM_ITEM_POOL:
            sales_material = await sm.create(
                SalesMaterialCreate(
                    shop_id=shop.id,
                    sales_material_bn=sku_id,
                    sales_material_name=title,
                    spec_text=spec,
                )
            )
            await bom.bind(
                sales_material.id,
                BomBind(
                    items=[BomItemIn(bm_id=material.id, bind_num=1, rate=100, fixed_price=0)]
                ),
            )
            sm_ids[sku_id] = sales_material.id
        await self.s.commit()
        return {
            "owner_id": owner.id,
            "shop_id": shop.id,
            "branch_id": branch["id"],
            "bm_id": material.id,
            "sm_id": sm_ids[SIM_ITEM_POOL[0][1]],
            "sm_ids": sm_ids,
            "sku": SIM_ITEM_POOL[0][1],
        }

    async def _bind_shop_branches(self, shop_id: int, branch_ids: list[int]) -> None:
        """配店铺-发货仓绑定（gw_shop_config.branch_bind_json）"""
        import json

        from sqlalchemy import text

        binds = json.dumps([{"branch_id": b, "priority": i} for i, b in enumerate(branch_ids)])
        await self.s.execute(
            text(
                "INSERT INTO oms_gateway.gw_shop_config "
                "(tenant_id, owner_id, shop_id, branch_bind_json, create_time, update_time, version) "
                "VALUES (1, 0, :sid, CAST(:binds AS JSON), NOW(3), NOW(3), 0) "
                "ON DUPLICATE KEY UPDATE branch_bind_json = CAST(:binds AS JSON)"
            ),
            {"sid": shop_id, "binds": binds},
        )
        await self.s.commit()

    async def _owner_co_node_id(self) -> int:
        from app.models.org import OrgNode

        node = await self.s.scalar(
            select(OrgNode).where(OrgNode.node_type == "owner_co", OrgNode.is_deleted == 0).limit(1)
        )
        return int(node.id) if node else 0

    async def _make_branch(self, shop: GwShop, owner) -> dict:
        """建仓（走档案域服务 → 联动组织树 + 自动绑定归属货主）"""
        from app.modules.m1_master.service.master import BranchService
        from app.schemas.master import BranchCreate

        branch = await BranchService(self.s, self.r).create(
            BranchCreate(
                branch_name="场景发货仓",
                owner_id=owner.id,
                branch_type="entity",
                is_ctrl=1,
                countable_flag=1,
            )
        )
        await self.s.commit()
        return {"id": branch.id, "branch_bn": branch.branch_bn}

    # ---------- ② 期初建账 ----------

    async def opening_stock(self, ctx: dict, qty: int = 100) -> None:
        """期初入库（记账行起点快照 + 流水），等价于期初建账的记账部分"""
        ledger = StockLedgerService(self.s, self.r)
        await ledger.apply_change(
            sc.StockChangeRequest(
                branch_id=ctx["branch_id"],
                bm_id=ctx["bm_id"],
                owner_id=ctx["owner_id"],
                changes=[sc.StockChangeItem(field="store", delta=qty)],
                bill_type="opening_in",
                bill_bn="SCN_OPENING_001",
                bill_item_id=1,
                action="inbound",
                source="migration",
            )
        )

    # ---------- ③ 平台造单 ----------

    async def platform_create_order(self, count: int = 1) -> list[str]:
        """调模拟器造单（真实 HTTP，验证平台侧链路）"""
        import httpx

        from app.core.config import settings

        url = f"{settings.platform_gateway_url.rstrip('/')}/sim/orders"
        async with httpx.AsyncClient() as hc:
            r = await hc.post(url, json={"scenario": "normal", "count": count})
            data = r.json()["data"]
            return list(data.get("tids", []))

    # ---------- ④ 拉单接入 ----------

    async def pull_and_create(self, ctx: dict) -> dict:
        """拉单 → canonical → 缓冲 → 建单（返回订单与断言信息）"""
        pull = PullService(self.s, get_gateway(self.r), self.r)
        # 店铺级覆写：把安全延迟设为 0（默认 60s 会把"刚刚造的单"挡在窗口外）
        await self._patch_watermark(ctx["shop_id"])
        stat = await pull.poll_shop(ctx["shop_id"])
        order = await self.s.scalar(
            select(OrdOrder)
            .where(OrdOrder.shop_id == ctx["shop_id"], OrdOrder.is_deleted == 0)
            .order_by(OrdOrder.id.desc())
            .limit(1)
        )
        items = []
        if order:
            items = list(
                await self.s.scalars(
                    select(OrdOrderItem)
                    .where(OrdOrderItem.order_id == order.id, OrdOrderItem.is_deleted == 0)
                    .order_by(OrdOrderItem.id)
                )
            )
        return {"stat": stat, "order": order, "items": items}

    async def _patch_watermark(self, shop_id: int) -> None:
        from sqlalchemy import text

        await self.s.execute(
            text(
                "INSERT INTO oms_gateway.gw_pull_watermark "
                "(tenant_id, shop_id, channel, last_download_time, overlap_sec, "
                " safety_delay_sec, poll_interval_sec, lag_alert_threshold_sec, "
                " create_time, update_time, version) "
                "VALUES (1, :sid, 'order', NOW(3), 300, 0, 60, 1800, NOW(3), NOW(3), 0) "
                "ON DUPLICATE KEY UPDATE safety_delay_sec = 0"
            ),
            {"sid": shop_id},
        )
        await self.s.commit()

    # ---------- ⑤ 库存预占 ----------

    async def reserve(self, ctx: dict, order, items, qty: int) -> dict:
        """按订单行预占（仓×物料×货主）"""
        freeze = FreezeService(self.s, self.r)
        result = await freeze.reserve(
            sc.FreezeReserveRequest(
                obj_type=1,
                obj_bn=order.order_bn,
                items=[
                    sc.FreezeReserveItem(
                        branch_id=ctx["branch_id"],
                        bm_id=item.bm_id,
                        owner_id=item.owner_id,
                        num=qty,
                        obj_item_id=item.id,
                    )
                    for item in items
                ],
            )
        )
        return {"result": result}

    # ---------- ⑥ 出库单据 ----------

    async def outbound(self, ctx: dict, order, items, qty: int) -> dict:
        """销售出库单：创建 → 下发 → 回传 → 确认即记账"""
        bills = IoBillService(self.s, self.r)
        bill = await bills.create(
            sc.IoBillCreate(
                bill_type="sale_out",
                branch_id=ctx["branch_id"],
                owner_id=ctx["owner_id"],
                source_bill_type="order",
                source_bill_bn=order.order_bn,
                items=[
                    sc.IoBillItemIn(
                        bm_id=item.bm_id,
                        issued_num=qty,
                        confirmed_num=qty,
                        unit_cost=10.0,
                        source_item_id=item.id,
                    )
                    for item in items
                ],
                operator="scenario",
            )
        )
        await bills.push_to_wms(bill.id, "WMS_SCN_001")
        await bills.receive_callback(
            bill.id,
            sc.IoBillCallback(
                wms_bill_no="WMS_SCN_001",
                items=[
                    sc.IoBillItemIn(bm_id=item.bm_id, confirmed_num=qty)
                    for item in items
                ],
                operator="scenario",
            ),
        )
        confirmed = await bills.confirm(bill.id, operator="scenario")
        return {"bill": confirmed}

    # ---------- ⑧ 可售计算与平台回写 ----------

    async def sellable_and_writeback(self, ctx: dict, sm_id: int) -> dict:
        """可售计算 → 平台回写（D04.08：可售=可用−安全库存，回写经适配器到平台）"""
        from app.modules.m2_stock.service.sellable import SellableService
        from app.modules.m7_integration.service.sync import StockSyncService

        await self._set_strategy(ctx["shop_id"])
        sellable = SellableService(self.s, self.r)
        calc = await sellable.calc(ctx["shop_id"], sm_id, use_cache=False)
        sync = StockSyncService(self.s, self.r, get_gateway(self.r))
        wb = await sync.writeback(ctx["shop_id"], sm_id, trigger=4, force=True)
        return {"calc": calc, "writeback": wb}

    async def _set_strategy(self, shop_id: int) -> None:
        """配可售同步策略（全量共享-安全库存）"""
        from sqlalchemy import text

        await self.s.execute(
            text(
                "INSERT INTO oms_stock.inv_sync_strategy "
                "(tenant_id, shop_id, scope_type, strategy_type, safe_num, safe_ratio, "
                " alloc_ratio, oversell_mode, quota_num, water_level, water_level_type, "
                " min_sellable, max_sellable, writeback_mode, threshold_rate, status, "
                " create_time, update_time, version) "
                "VALUES (1, :sid, 1, 'shared_safe', 0, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0, 1, "
                " NOW(3), NOW(3), 0) "
                "ON DUPLICATE KEY UPDATE strategy_type = 'shared_safe', safe_num = 0"
            ),
            {"sid": shop_id},
        )
        await self.s.commit()

    async def platform_writebacks(self) -> list[dict]:
        """取模拟器收到的回写留档（断言平台侧确实收到）"""
        import httpx

        from app.core.config import settings

        url = f"{settings.platform_gateway_url.rstrip('/')}/sim/writebacks"
        async with httpx.AsyncClient() as hc:
            r = await hc.get(url)
            data = r.json().get("data") or {}
            # 模拟器返回 {total, items:[...]}
            items = data.get("items") if isinstance(data, dict) else data
            return list(items or [])

    # ---------- ⑦ 账实核对 ----------

    async def balances(self, ctx: dict) -> dict:
        """查当前余额与流水"""
        row = await self.s.scalar(
            select(InvStockLedger).where(
                InvStockLedger.branch_id == ctx["branch_id"],
                InvStockLedger.bm_id == ctx["bm_id"],
                InvStockLedger.owner_id == ctx["owner_id"],
            )
        )
        logs = list(
            await self.s.scalars(
                select(InvStockChangeLog)
                .where(
                    InvStockChangeLog.branch_id == ctx["branch_id"],
                    InvStockChangeLog.bm_id == ctx["bm_id"],
                    InvStockChangeLog.owner_id == ctx["owner_id"],
                )
                .order_by(InvStockChangeLog.id)
            )
        )
        return {"ledger": row, "logs": logs}


async def run_scenario(gateway_url: str = "") -> ScenarioReport:
    """执行完整业务场景（可独立运行的演示脚本入口）"""
    report = ScenarioReport()
    redis = await get_redis()
    async with SessionFactory() as session:
        runner = ScenarioRunner(session, redis, gateway_url)

        # ⓪ 幂等清理（保证脚本可重复执行）
        removed = await runner.cleanup()
        report.add("0", "幂等清理（上次场景残留）", True, f"清理 {removed} 行")

        # ① 主数据
        ctx = await runner.prepare_master_data()
        report.add("1", "主数据准备（货主/店铺/仓/物料/BOM）", True,
                   f"shop={ctx['shop_id']} branch={ctx['branch_id']} bm={ctx['bm_id']}")

        # ② 期初
        await runner.opening_stock(ctx, qty=100)
        bal = await runner.balances(ctx)
        report.add("2", "期初建账（入库 100）", bal["ledger"].store == 100,
                   f"store={bal['ledger'].store}", store=bal["ledger"].store)

        # ③ 平台造单
        tids = await runner.platform_create_order(count=1)
        report.add("3", "平台下单（模拟器造单）", bool(tids),
                   f"平台单号={tids[0] if tids else '-'}")

        # ④ 拉单接入
        pulled = await runner.pull_and_create(ctx)
        order = pulled["order"]
        items = pulled["items"]
        report.add("4", "拉单接入（canonical→缓冲→建单）", order is not None,
                   f"订单={order.order_bn if order else '-'}",
                   created=pulled["stat"].get("created"))
        report.add("4b", "订单行 BOM 展开快照", bool(items) and items[0].bm_id == ctx["bm_id"],
                   f"bm_id={items[0].bm_id if items else '-'} owner_id={items[0].owner_id if items else '-'}",
                   bm_id=items[0].bm_id if items else 0)

        if not order or not items:
            report.add("5", "库存预占", False, "无订单行，跳过")
            return report

        # ⑤ 预占
        reserve_result = await runner.reserve(ctx, order, items, qty=2)
        bal = await runner.balances(ctx)
        available = StockLedgerService.available_of(
            bal["ledger"].store,
            bal["ledger"].freeze,
            bal["ledger"].defective,
            bal["ledger"].safe_store,
            bal["ledger"].is_locked,
        )
        reserved_ok = bal["ledger"].freeze == 2 and reserve_result["result"].reserved_num == 2
        report.add("5", "库存预占（2 件）", reserved_ok,
                   f"freeze={bal['ledger'].freeze} available={available}",
                   freeze=bal["ledger"].freeze)

        # ⑥ 出库
        out = await runner.outbound(ctx, order, items, qty=2)
        bill = out["bill"]
        report.add("6", "出库单据（下发→回传→确认记账）", bill.status == 5,
                   f"单据={bill.bill_bn} 状态={bill.status}", status=bill.status)

        # ⑧ 可售计算与平台回写（库存 98 → 可售 98 → 回写平台）
        sellable_res = await runner.sellable_and_writeback(ctx, ctx["sm_id"])
        calc = sellable_res["calc"]
        wb = sellable_res["writeback"]
        report.add("8", "可售计算（可用−安全库存）", calc.sellable == 98,
                   f"可售={calc.sellable}（基础可用={calc.base_available}）",
                   sellable=calc.sellable)
        report.add("8b", "可售回写平台（模拟器断言）", wb.written and wb.calc_sellable == 98,
                   f"回写={wb.calc_sellable} written={wb.written}",
                   written=wb.written)
        writebacks = await runner.platform_writebacks()
        inv_wb = [w for w in writebacks if w.get("type") == "inventory"]
        report.add("8c", "平台侧收到可售回写", bool(inv_wb),
                   f"平台回写记录={inv_wb[-1] if inv_wb else '无'}")

        # ⑦ 账实核对
        bal = await runner.balances(ctx)
        ledger = bal["ledger"]
        ok_store = ledger.store == 98
        ok_freeze = ledger.freeze == 0
        ok_logs = len(bal["logs"]) >= 3
        report.add("7", "库存扣减核对（store 100→98）", ok_store,
                   f"store={ledger.store}", store=ledger.store)
        report.add("7b", "预占核销（freeze 归零）", ok_freeze,
                   f"freeze={ledger.freeze}", freeze=ledger.freeze)
        report.add("7c", "流水完整性（期初+预占+核销）", ok_logs,
                   f"流水条数={len(bal['logs'])}", logs=len(bal["logs"]))

    return report
