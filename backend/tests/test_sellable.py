"""可售计算与平台同步测试（M1c-4，SRS-D04.08）

覆盖：策略链（安全库存/比例/独立配额）、组合装最小套数、多仓聚合、上下限修正、
活动锁定池扣减、平台回写（含 api_log 与回写日志）、节流防抖、售罄熔断与恢复、
同步对账强制回写、策略变更即时生效。
"""
import os
import socket
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.db import SessionFactory, engine
from app.modules.m1_master.service.master import get_redis

pytestmark = pytest.mark.asyncio

REPO_ROOT = Path(__file__).resolve().parents[2]
MOCK_DIR = REPO_ROOT / "mocks" / "platform"

CLEANUP_SQL = [
    "DELETE FROM oms_stock.inv_sync_log WHERE shop_id IN "
    "(SELECT id FROM oms_gateway.gw_shop WHERE shop_bn LIKE 'SB\\_%')",
    "DELETE FROM oms_stock.inv_sync_strategy WHERE shop_id IN "
    "(SELECT id FROM oms_gateway.gw_shop WHERE shop_bn LIKE 'SB\\_%')",
    "DELETE FROM oms_stock.inv_activity_lock_pool WHERE bm_id IN "
    "(SELECT id FROM oms_stock.inv_material WHERE material_bn LIKE 'SBM\\_%')",
    "DELETE FROM oms_stock.inv_stock_change_log WHERE bm_id IN "
    "(SELECT id FROM oms_stock.inv_material WHERE material_bn LIKE 'SBM\\_%')",
    "DELETE FROM oms_stock.inv_stock_ledger WHERE bm_id IN "
    "(SELECT id FROM oms_stock.inv_material WHERE material_bn LIKE 'SBM\\_%')",
    "DELETE FROM oms_stock.inv_bom_item WHERE sm_id IN "
    "(SELECT id FROM oms_stock.inv_sales_material WHERE shop_id IN "
    "(SELECT id FROM oms_gateway.gw_shop WHERE shop_bn LIKE 'SB\\_%'))",
    "DELETE FROM oms_stock.inv_bom_version WHERE sm_id IN "
    "(SELECT id FROM oms_stock.inv_sales_material WHERE shop_id IN "
    "(SELECT id FROM oms_gateway.gw_shop WHERE shop_bn LIKE 'SB\\_%'))",
    "DELETE FROM oms_stock.inv_sales_material WHERE sales_material_bn LIKE 'SBS\\_%'",
    "DELETE FROM oms_stock.inv_material WHERE material_bn LIKE 'SBM\\_%'",
    "DELETE FROM oms_gateway.gw_shop_config WHERE shop_id IN "
    "(SELECT id FROM oms_gateway.gw_shop WHERE shop_bn LIKE 'SB\\_%')",
    "DELETE FROM oms_gateway.gw_shop WHERE shop_bn LIKE 'SB\\_%'",
    "DELETE FROM oms_org.org_node WHERE org_code LIKE 'SHOP\\_SB\\_%'",
    "DELETE FROM oms_org.org_owner WHERE owner_code LIKE 'SB\\_%'",
]


async def _cleanup() -> None:
    async with engine.begin() as conn:
        for sql in CLEANUP_SQL:
            await conn.execute(text(sql))


@pytest.fixture(autouse=True, scope="module")
async def isolate_sellable_data():
    from app.core.db import AuthContext, set_auth_context

    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    await _cleanup()
    yield
    await _cleanup()
    set_auth_context(None)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def mock_platform():
    """启动 mock-platform（动态端口）"""
    port = _free_port()
    py = str(REPO_ROOT / "backend" / ".venv" / "bin" / "python")
    env = {**os.environ, "PYTHONPATH": str(MOCK_DIR)}
    proc = subprocess.Popen(
        [py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(MOCK_DIR), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                break
        except OSError:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.skip("mock-platform 启动失败（跳过回写用例）")
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


# ============ 基础数据 ============


async def _make_shop(owner_id: int, name: str, branch_ids: list[int]) -> dict:
    """建店铺 + 配店铺-发货仓绑定（gw_shop_config.branch_bind_json）"""
    async with engine.begin() as conn:
        r = await conn.execute(
            text(
                "SELECT id FROM oms_org.org_node "
                "WHERE node_type='owner_co' AND is_deleted=0 LIMIT 1"
            )
        )
        node_id = int(r.scalar())
    async with SessionFactory() as s:
        from app.models.shop import GwShop
        from app.modules.m1_master.service.master import ShopService

        shop = GwShop(
            tenant_id=1,
            owner_id=owner_id,
            shop_bn=f"SB_{name}",
            shop_name=f"可售测试店{name}",
            platform="taobao",
            platform_shop_id=f"sb_{name}",
            shop_type="flagship",
            business_type="direct_sale",
            auth_status="normal",
            status="enabled",
        )
        s.add(shop)
        await s.flush()
        await s.commit()
        await s.refresh(shop)
        del node_id, ShopService
    import json

    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO oms_gateway.gw_shop_config "
                "(tenant_id, owner_id, shop_id, branch_bind_json, create_time, update_time, version) "
                "VALUES (1, :oid, :sid, CAST(:binds AS JSON), NOW(3), NOW(3), 0)"
            ),
            {"oid": owner_id, "sid": shop.id,
             "binds": json.dumps([{"branch_id": b, "priority": i} for i, b in enumerate(branch_ids)])},
        )
    return {"id": shop.id, "shop_bn": shop.shop_bn}


async def _make_owner(code: str) -> dict:
    async with engine.begin() as conn:
        r = await conn.execute(
            text("SELECT id FROM oms_org.org_node WHERE node_type='owner_co' AND is_deleted=0 LIMIT 1")
        )
        node_id = int(r.scalar())
    async with SessionFactory() as s:
        from app.models.org import OrgOwner

        owner = OrgOwner(
            tenant_id=1, owner_code=code, owner_name=f"可售货主{code}",
            owner_type="KC_BUYOUT", org_node_id=node_id, status=1,
        )
        s.add(owner)
        await s.commit()
        await s.refresh(owner)
    return {"id": owner.id}


async def _make_branch(owner_id: int, name: str) -> dict:
    async with SessionFactory() as s:
        from app.modules.m1_master.service.master import BranchService, get_redis
        from app.schemas.master import BranchCreate

        redis = await get_redis()
        branch = await BranchService(s, redis).create(
            BranchCreate(
                branch_name=f"可售测试仓{name}", owner_id=owner_id,
                branch_type="entity", is_ctrl=1, countable_flag=1,
            )
        )
        await s.commit()
    return {"id": branch.id}


async def _make_material(bn: str, name: str, owner_id: int) -> dict:
    async with SessionFactory() as s:
        from app.models.material import InvMaterial

        mat = InvMaterial(
            tenant_id=1, owner_id=owner_id, material_bn=bn, material_name=name,
            type=3, cat_id=0, cat_path="", brand_id=0, status=1,
        )
        s.add(mat)
        await s.commit()
        await s.refresh(mat)
    return {"id": mat.id}


async def _make_sales_material(shop_id: int, bn: str, name: str) -> dict:
    async with SessionFactory() as s:
        from app.modules.m2_stock.service.material import SalesMaterialService
        from app.schemas.material import SalesMaterialCreate

        sm = await SalesMaterialService(s).create(
            SalesMaterialCreate(shop_id=shop_id, sales_material_bn=bn, sales_material_name=name)
        )
        await s.commit()
    return {"id": sm.id}


async def _bind_bom(sm_id: int, items: list[tuple[int, int]]) -> None:
    """绑定 BOM（items: [(bm_id, bind_num)]；占比合计必须 100%）"""
    async with SessionFactory() as s:
        from app.modules.m2_stock.service.material import BomService
        from app.schemas.material import BomBind, BomItemIn

        n = len(items)
        rates = [100 // n] * n
        rates[-1] += 100 - sum(rates)  # 尾差补齐，保证合计 100
        await BomService(s).bind(
            sm_id,
            BomBind(
                items=[
                    BomItemIn(bm_id=b, bind_num=q, rate=r, fixed_price=0)
                    for (b, q), r in zip(items, rates, strict=True)
                ]
            ),
        )
        await s.commit()


async def _stock(branch_id: int, bm_id: int, owner_id: int, qty: int) -> None:
    """入库记账（造库存）"""
    async with SessionFactory() as s:
        from app.modules.m1_master.service.master import get_redis
        from app.modules.m2_stock.service.stock_ledger import StockLedgerService
        from app.schemas.stock import StockChangeItem, StockChangeRequest

        redis = await get_redis()
        await StockLedgerService(s, redis).apply_change(
            StockChangeRequest(
                branch_id=branch_id, bm_id=bm_id, owner_id=owner_id,
                changes=[StockChangeItem(field="store", delta=qty)],
                bill_type="opening_in", bill_bn=f"SB_OPEN_{branch_id}_{bm_id}",
                bill_item_id=1, action="inbound", source="migration",
            )
        )


async def _set_strategy(shop_id: int, **kwargs) -> None:
    async with SessionFactory() as s:
        from app.models.stock import InvSyncStrategy

        row = InvSyncStrategy(shop_id=shop_id, scope_type=1, **kwargs)
        s.add(row)
        await s.commit()


# ============ ① 可售计算（FR-02）============


async def test_sellable_shared_safe_strategy():
    """共享-安全库存策略：可售 = available − 安全库存"""
    from app.modules.m2_stock.service.sellable import SellableService

    owner = await _make_owner("SB_01")
    branch = await _make_branch(owner["id"], "01")
    shop = await _make_shop(owner["id"], "01", [branch["id"]])
    mat = await _make_material("SBM_01", "可售物料01", owner["id"])
    sm = await _make_sales_material(shop["id"], "SKU_TSHIRT_S", "可售销售物料01")
    await _bind_bom(sm["id"], [(mat["id"], 1)])
    await _stock(branch["id"], mat["id"], owner["id"], 100)
    await _set_strategy(shop["id"], strategy_type="shared_safe", safe_num=10)

    async with SessionFactory() as s:
        redis = await get_redis()
        result = await SellableService(s, redis).calc(shop["id"], sm["id"], use_cache=False)
    assert result.base_available == 100
    assert result.sellable == 90
    assert result.strategy_type == "shared_safe"


async def test_sellable_shared_ratio_strategy():
    """共享比例策略：可售 = floor((available − 安全库存) × 比例%)"""
    from app.modules.m2_stock.service.sellable import SellableService

    owner = await _make_owner("SB_02")
    branch = await _make_branch(owner["id"], "02")
    shop = await _make_shop(owner["id"], "02", [branch["id"]])
    mat = await _make_material("SBM_02", "可售物料02", owner["id"])
    sm = await _make_sales_material(shop["id"], "SKU_PANTS_32", "可售销售物料02")
    await _bind_bom(sm["id"], [(mat["id"], 1)])
    await _stock(branch["id"], mat["id"], owner["id"], 100)
    await _set_strategy(shop["id"], strategy_type="shared_ratio", safe_num=0, alloc_ratio=70)

    async with SessionFactory() as s:
        redis = await get_redis()
        result = await SellableService(s, redis).calc(shop["id"], sm["id"], use_cache=False)
    assert result.sellable == 70


async def test_sellable_independent_quota():
    """独立配额策略：可售 = 配额（不共享池）"""
    from app.modules.m2_stock.service.sellable import SellableService

    owner = await _make_owner("SB_03")
    branch = await _make_branch(owner["id"], "03")
    shop = await _make_shop(owner["id"], "03", [branch["id"]])
    mat = await _make_material("SBM_03", "可售物料03", owner["id"])
    sm = await _make_sales_material(shop["id"], "SKU_JACKET_L", "可售销售物料03")
    await _bind_bom(sm["id"], [(mat["id"], 1)])
    await _stock(branch["id"], mat["id"], owner["id"], 500)
    await _set_strategy(shop["id"], strategy_type="independent", quota_num=30)

    async with SessionFactory() as s:
        redis = await get_redis()
        result = await SellableService(s, redis).calc(shop["id"], sm["id"], use_cache=False)
    assert result.base_available == 500
    assert result.sellable == 30  # 配额封顶，不随库存增长


async def test_sellable_combo_min_sets():
    """组合装：可售 = min(成员可售 / 需求量)（AC-02：min(50,30,100)=30）"""
    from app.modules.m2_stock.service.sellable import SellableService

    owner = await _make_owner("SB_04")
    branch = await _make_branch(owner["id"], "04")
    shop = await _make_shop(owner["id"], "04", [branch["id"]])
    m1 = await _make_material("SBM_04A", "组合成员A", owner["id"])
    m2 = await _make_material("SBM_04B", "组合成员B", owner["id"])
    m3 = await _make_material("SBM_04C", "组合成员C", owner["id"])
    sm = await _make_sales_material(shop["id"], "SKU_SOCKS_35", "组合装销售物料")
    await _bind_bom(sm["id"], [(m1["id"], 1), (m2["id"], 1), (m3["id"], 1)])
    await _stock(branch["id"], m1["id"], owner["id"], 50)
    await _stock(branch["id"], m2["id"], owner["id"], 30)
    await _stock(branch["id"], m3["id"], owner["id"], 100)
    await _set_strategy(shop["id"], strategy_type="shared_safe", safe_num=0)

    async with SessionFactory() as s:
        redis = await get_redis()
        result = await SellableService(s, redis).calc(shop["id"], sm["id"], use_cache=False)
    assert result.is_combo
    assert result.sellable == 30  # 最小成员可售


async def test_sellable_multi_branch_aggregate():
    """多仓聚合：可售 = 各发货仓可用之和（AC-09）"""
    from app.modules.m2_stock.service.sellable import SellableService

    owner = await _make_owner("SB_05")
    b1 = await _make_branch(owner["id"], "05A")
    b2 = await _make_branch(owner["id"], "05B")
    shop = await _make_shop(owner["id"], "05", [b1["id"], b2["id"]])
    mat = await _make_material("SBM_05", "可售物料05", owner["id"])
    sm = await _make_sales_material(shop["id"], "SKU_TSHIRT_M", "可售销售物料05")
    await _bind_bom(sm["id"], [(mat["id"], 1)])
    await _stock(b1["id"], mat["id"], owner["id"], 40)
    await _stock(b2["id"], mat["id"], owner["id"], 60)
    await _set_strategy(shop["id"], strategy_type="shared_safe", safe_num=0)

    async with SessionFactory() as s:
        redis = await get_redis()
        result = await SellableService(s, redis).calc(shop["id"], sm["id"], use_cache=False)
    assert len(result.branch_ids) == 2
    assert result.base_available == 100
    assert result.sellable == 100


async def test_sellable_clamp_min_max():
    """上下限修正：可售被夹在 [min, max] 之间"""
    from app.modules.m2_stock.service.sellable import SellableService

    owner = await _make_owner("SB_06")
    branch = await _make_branch(owner["id"], "06")
    shop = await _make_shop(owner["id"], "06", [branch["id"]])
    mat = await _make_material("SBM_06", "可售物料06", owner["id"])
    sm = await _make_sales_material(shop["id"], "SKU_TSHIRT_S", "可售销售物料06")
    await _bind_bom(sm["id"], [(mat["id"], 1)])
    await _stock(branch["id"], mat["id"], owner["id"], 500)
    await _set_strategy(shop["id"], strategy_type="shared_safe", safe_num=0, max_sellable=200)

    async with SessionFactory() as s:
        redis = await get_redis()
        result = await SellableService(s, redis).calc(shop["id"], sm["id"], use_cache=False)
    assert result.sellable == 200  # 上限修正


async def test_activity_lock_reduces_sellable():
    """活动锁定池：非本渠道活动占用从常规可售中扣减（FR-01e / AC-11）"""
    from app.models.stock import InvActivityLockPool
    from app.modules.m2_stock.service.sellable import SellableService

    owner = await _make_owner("SB_07")
    branch = await _make_branch(owner["id"], "07")
    shop = await _make_shop(owner["id"], "07", [branch["id"]])
    mat = await _make_material("SBM_07", "可售物料07", owner["id"])
    sm = await _make_sales_material(shop["id"], "SKU_PANTS_32", "可售销售物料07")
    await _bind_bom(sm["id"], [(mat["id"], 1)])
    await _stock(branch["id"], mat["id"], owner["id"], 100)
    await _set_strategy(shop["id"], strategy_type="shared_safe", safe_num=0)

    # 活动池：绑定其他店铺 → 本店常规可售应扣减 30
    async with SessionFactory() as s:
        s.add(
            InvActivityLockPool(
                tenant_id=1, activity_id=9001, activity_name="大促活动",
                branch_id=branch["id"], bm_id=mat["id"], owner_id=owner["id"],
                lock_num=30, sold_num=0, remain_num=30,
                channel_scope=[{"shop_id": 99999}],
                start_time=datetime.now() - timedelta(days=1),
                end_time=datetime.now() + timedelta(days=1),
                status="active",
            )
        )
        await s.commit()

    async with SessionFactory() as s:
        redis = await get_redis()
        result = await SellableService(s, redis).calc(shop["id"], sm["id"], use_cache=False)
    assert result.base_available == 70  # 100 − 30
    assert result.sellable == 70


# ============ ② 平台回写（FR-03/04/05）============


async def test_writeback_to_platform(mock_platform, monkeypatch):
    """回写平台库存：调适配器 → 模拟器库存更新 + 回写日志落库"""
    from app.core.config import settings
    from app.modules.m7_integration.service.gateway import get_gateway
    from app.modules.m7_integration.service.sync import StockSyncService

    monkeypatch.setattr(settings, "platform_gateway_url", mock_platform)
    redis = await get_redis()

    owner = await _make_owner("SB_08")
    branch = await _make_branch(owner["id"], "08")
    shop = await _make_shop(owner["id"], "08", [branch["id"]])
    mat = await _make_material("SBM_08", "可售物料08", owner["id"])
    sm = await _make_sales_material(shop["id"], "SKU_JACKET_L", "可售销售物料08")
    await _bind_bom(sm["id"], [(mat["id"], 1)])
    await _stock(branch["id"], mat["id"], owner["id"], 100)
    await _set_strategy(shop["id"], strategy_type="shared_safe", safe_num=0)

    async with SessionFactory() as s:
        svc = StockSyncService(s, redis, get_gateway(redis))
        res = await svc.writeback(shop["id"], sm["id"], trigger=4, force=True)
        assert res.written, res.reason
        assert res.calc_sellable == 100
        assert res.log_id > 0

    # 回写日志
    async with engine.begin() as conn:
        r = await conn.execute(
            text(
                "SELECT calc_sellable, writeback_num, sync_status, trigger_type "
                "FROM oms_stock.inv_sync_log WHERE sm_id = :sid"
            ),
            {"sid": sm["id"]},
        )
        row = r.fetchone()
    assert row is not None
    assert int(row[0]) == 100
    assert int(row[2]) == 1  # 成功
    assert int(row[3]) == 4  # 手动触发


async def test_writeback_throttle_skips_small_change(mock_platform, monkeypatch):
    """节流防抖：变化未超阈值 → 本轮不回写（AC-07）"""
    from app.core.config import settings
    from app.modules.m7_integration.service.gateway import get_gateway
    from app.modules.m7_integration.service.sync import StockSyncService

    monkeypatch.setattr(settings, "platform_gateway_url", mock_platform)
    redis = await get_redis()

    owner = await _make_owner("SB_09")
    branch = await _make_branch(owner["id"], "09")
    shop = await _make_shop(owner["id"], "09", [branch["id"]])
    mat = await _make_material("SBM_09", "可售物料09", owner["id"])
    sm = await _make_sales_material(shop["id"], "SKU_SOCKS_35", "可售销售物料09")
    await _bind_bom(sm["id"], [(mat["id"], 1)])
    await _stock(branch["id"], mat["id"], owner["id"], 100)
    # 阈值率 50% → 变化 < 50 才跳过
    await _set_strategy(shop["id"], strategy_type="shared_safe", safe_num=0, threshold_rate=0.5)

    async with SessionFactory() as s:
        svc = StockSyncService(s, redis, get_gateway(redis))
        first = await svc.writeback(shop["id"], sm["id"], trigger=4, force=True)
        assert first.written
        # 库存 +1（变化 1 < max(1, 100×0.5)=50）→ 跳过
        await StockLedgerServiceHelper(s, redis).apply_change(
            _change_req(branch["id"], mat["id"], owner["id"], 1)
        )
        second = await svc.writeback(
            shop["id"], sm["id"], trigger=1, threshold_rate=0.5
        )
        assert not second.written
        assert "阈值" in second.reason


async def test_sellable_fuse_on_zero_and_recover(mock_platform, monkeypatch):
    """售罄熔断：可售 0 → 回写 0 并暂停；补货后自动恢复（FR-04b / AC-05）"""
    from app.core.config import settings
    from app.modules.m7_integration.service.gateway import get_gateway
    from app.modules.m7_integration.service.sync import StockSyncService

    monkeypatch.setattr(settings, "platform_gateway_url", mock_platform)
    redis = await get_redis()

    owner = await _make_owner("SB_10")
    branch = await _make_branch(owner["id"], "10")
    shop = await _make_shop(owner["id"], "10", [branch["id"]])
    mat = await _make_material("SBM_10", "可售物料10", owner["id"])
    sm = await _make_sales_material(shop["id"], "SKU_TSHIRT_M", "可售销售物料10")
    await _bind_bom(sm["id"], [(mat["id"], 1)])
    await _stock(branch["id"], mat["id"], owner["id"], 5)
    await _set_strategy(shop["id"], strategy_type="shared_safe", safe_num=0)

    async with SessionFactory() as s:
        svc = StockSyncService(s, redis, get_gateway(redis))
        # 库存出清 → 可售 0
        await StockLedgerServiceHelper(s, redis).apply_change(
            _change_req(branch["id"], mat["id"], owner["id"], -5)
        )
        res = await svc.writeback(shop["id"], sm["id"], trigger=1)
        assert res.written
        assert res.calc_sellable == 0
        # 再次触发 → 熔断中，不再回写
        res2 = await svc.writeback(shop["id"], sm["id"], trigger=1)
        assert not res2.written
        assert "熔断" in res2.reason
        # 补货 → 恢复
        await StockLedgerServiceHelper(s, redis).apply_change(
            _change_req(branch["id"], mat["id"], owner["id"], 20)
        )
        res3 = await svc.writeback(shop["id"], sm["id"], trigger=1)
        assert res3.written
        assert res3.calc_sellable == 20


async def test_recon_forces_writeback(mock_platform, monkeypatch):
    """同步对账：平台库存 vs OMS 可售 差异 → 强制回写（FR-05a）"""
    from app.core.config import settings
    from app.modules.m7_integration.service.gateway import get_gateway
    from app.modules.m7_integration.service.sync import StockSyncService

    monkeypatch.setattr(settings, "platform_gateway_url", mock_platform)
    redis = await get_redis()

    owner = await _make_owner("SB_11")
    branch = await _make_branch(owner["id"], "11")
    shop = await _make_shop(owner["id"], "11", [branch["id"]])
    mat = await _make_material("SBM_11", "可售物料11", owner["id"])
    sm = await _make_sales_material(shop["id"], "SKU_TSHIRT_S", "可售销售物料11")
    await _bind_bom(sm["id"], [(mat["id"], 1)])
    await _stock(branch["id"], mat["id"], owner["id"], 80)
    await _set_strategy(shop["id"], strategy_type="shared_safe", safe_num=0)

    async with SessionFactory() as s:
        svc = StockSyncService(s, redis, get_gateway(redis))
        report = await svc.recon_shop(shop["id"])
        # 平台侧默认库存 100 ≠ OMS 可售 80 → 差异并强制回写
        assert report["diff_count"] >= 1
        diff = report["diffs"][0]
        assert diff["platform_num"] != diff["oms_num"]
        assert diff["action"] == "强制回写"


async def test_strategy_change_invalidates_cache(mock_platform, monkeypatch):
    """策略变更即时生效：清缓存后计算结果随之改变（FR-01d）"""
    from app.core.config import settings
    from app.modules.m2_stock.service.sellable import SellableService

    monkeypatch.setattr(settings, "platform_gateway_url", mock_platform)
    redis = await get_redis()

    owner = await _make_owner("SB_12")
    branch = await _make_branch(owner["id"], "12")
    shop = await _make_shop(owner["id"], "12", [branch["id"]])
    mat = await _make_material("SBM_12", "可售物料12", owner["id"])
    sm = await _make_sales_material(shop["id"], "SKU_PANTS_32", "可售销售物料12")
    await _bind_bom(sm["id"], [(mat["id"], 1)])
    await _stock(branch["id"], mat["id"], owner["id"], 100)
    await _set_strategy(shop["id"], strategy_type="shared_safe", safe_num=0)

    async with SessionFactory() as s:
        svc = SellableService(s, redis)
        first = await svc.calc(shop["id"], sm["id"])
        assert first.sellable == 100

    # 改策略：安全库存 30（**必须在 session 事务之外**——MySQL RR 快照看不到别处提交的变更）
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE oms_stock.inv_sync_strategy SET safe_num = 30 "
                "WHERE shop_id = :sid"
            ),
            {"sid": shop["id"]},
        )

    async with SessionFactory() as s:
        svc = SellableService(s, redis)
        await svc.invalidate_all(shop["id"])
        second = await svc.calc(shop["id"], sm["id"])
    assert second.sellable == 70


# ============ 辅助 ============


def StockLedgerServiceHelper(session, redis):
    from app.modules.m2_stock.service.stock_ledger import StockLedgerService

    return StockLedgerService(session, redis)


_CHANGE_SEQ = [0]


def _change_req(branch_id: int, bm_id: int, owner_id: int, delta: int):
    """构造记账请求（单号唯一：幂等键含单据号，否则同号会被幂等吸收）"""
    from app.schemas.stock import StockChangeItem, StockChangeRequest

    _CHANGE_SEQ[0] += 1
    return StockChangeRequest(
        branch_id=branch_id, bm_id=bm_id, owner_id=owner_id,
        changes=[StockChangeItem(field="store", delta=delta)],
        bill_type="sb_test", bill_bn=f"SBT_{branch_id}_{bm_id}_{_CHANGE_SEQ[0]}",
        bill_item_id=1, action="inbound" if delta > 0 else "outbound",
        source="oms",
    )
