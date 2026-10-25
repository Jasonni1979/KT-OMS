"""pytest 全局 fixture（测试隔离 + 测试数据卫生）

**为什么需要清理**：测试通过 API 造数（货主/店铺/物料/销售物料/条码/单据…），
但多数用例只断言不回收；重复跑 pytest 会在开发库里不断累积：
- 孤儿销售物料（店铺被删但 inv_sales_material 残留）→ 前端「所属店铺」显示 `#ID`
- 孤儿物料 / 条码 / 货主 → 列表页噪声，掩盖真实数据
- 库存台账残量 → 库存余额页数字失真

约定：测试造数的业务编码统一用**全大写前缀**，本模块在 session 结束前按前缀清理。
**注意**：SCN_ 前缀是业务场景脚本（app/scripts/scenario_e2e.py）的数据，它自带幂等清理，
不在 pytest 清理范围内（否则会抹掉演示链路数据）。
"""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.db import engine
from app.main import app


def _like(col: str, prefixes: tuple[str, ...]) -> str:
    """构造 (col LIKE 'T\\_%' OR ...) 条件（\\_ 转义下划线，避免通配误伤）"""
    parts = []
    for p in prefixes:
        esc = p.replace("_", "\\_")
        parts.append(f"{col} LIKE '{esc}%' ESCAPE '\\\\'")
    return "(" + " OR ".join(parts) + ")"


#: 测试造数前缀（按表区分，避免误删场景脚本 SCN_* 数据）
T_ = ("T_", "TST_", "TEST_")
MAT = ("BM_", "T_")
SM = ("SM_", "SIMSKU", "T_")
BC = ("BC_", "T_")
DOC = ("T_", "TST_", "TEST_")

#: (schema, table, 编码列, 前缀集合)
#: ⚠️ 列名以真实 DDL 为准（如 inv_bom_item / inv_stock_ledger 无 material_bn 列，
#:    只能按外键 sm_id / bm_id 子查）
CLEANUP_TARGETS: list[tuple[str, str, str, tuple[str, ...]]] = [
    # 子表优先
    ("oms_stock", "inv_io_bill_item", "bill_bn", DOC),
    # 库存流水 / 预占 / 单据
    ("oms_stock", "inv_stock_change_log", "bill_bn", DOC),
    ("oms_stock", "inv_freeze_log", "obj_bn", DOC),
    ("oms_stock", "inv_io_bill", "bill_bn", DOC),
    # 订单主表
    ("oms_order", "ord_order", "order_bn", DOC),
    ("oms_order", "ord_order_fail", "platform_order_bn", DOC),
    # 物料 / 销售物料 / 条码
    ("oms_stock", "inv_sales_material", "sales_material_bn", SM),
    ("oms_stock", "inv_barcode", "barcode", BC),
    ("oms_stock", "inv_material", "material_bn", MAT),
    ("oms_stock", "inv_material_cat", "cat_name", T_),
    ("oms_stock", "inv_brand", "brand_name", T_),
    # 档案
    ("oms_gateway", "gw_shop", "shop_bn", T_),
    ("oms_org", "org_owner", "owner_code", T_),
    ("oms_org", "org_node", "org_code", T_),
    ("oms_org", "org_role", "role_code", T_),
    # 网关缓冲池
    ("oms_gateway", "gw_order_buffer", "platform_order_bn", DOC),
    # 导入任务
    ("oms_base", "bas_import_task", "task_bn", DOC),
]

#: 订单子表（无 order_bn 列，靠 order_id 关联主表）
ORDER_CHILD_TABLES = ("ord_order_item", "ord_order_pmt", "ord_receiver", "ord_status_log")
@pytest.fixture(autouse=True)
async def _dispose_engine():
    """每个测试后释放连接池：模块级 engine 跨 event loop 复用会残留连接，
    dispose 后下个测试在新 loop 重建连接（SQLAlchemy 官方推荐的测试隔离做法）。"""
    yield
    await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
async def _cleanup_test_data():
    """session 结束前清理测试造数（幂等；开发库卫生保障）"""
    yield
    async with engine.begin() as conn:
        # 库存台账（按 bm_id 子查测试物料）
        await conn.execute(text(
            "DELETE FROM oms_stock.inv_stock_ledger WHERE bm_id IN "
            f"(SELECT id FROM oms_stock.inv_material WHERE {_like('material_bn', MAT)})"
        ))
        # BOM 行（按 sm_id / bm_id 子查）
        await conn.execute(text(
            "DELETE FROM oms_stock.inv_bom_item WHERE sm_id IN "
            f"(SELECT id FROM oms_stock.inv_sales_material WHERE {_like('sales_material_bn', SM)})"
            " OR bm_id IN "
            f"(SELECT id FROM oms_stock.inv_material WHERE {_like('material_bn', MAT)})"
        ))
        # BOM 版本（按销售物料子查）
        await conn.execute(text(
            "DELETE FROM oms_stock.inv_bom_version WHERE sm_id IN "
            f"(SELECT id FROM oms_stock.inv_sales_material WHERE {_like('sales_material_bn', SM)})"
        ))
        # 孤儿销售物料（所属店铺已不存在）→ 级联清 BOM 行与版本
        await conn.execute(text(
            "DELETE FROM oms_stock.inv_bom_item WHERE sm_id IN "
            "(SELECT id FROM oms_stock.inv_sales_material sm WHERE NOT EXISTS "
            "(SELECT 1 FROM oms_gateway.gw_shop s WHERE s.id = sm.shop_id))"
        ))
        await conn.execute(text(
            "DELETE FROM oms_stock.inv_bom_version WHERE sm_id IN "
            "(SELECT id FROM oms_stock.inv_sales_material sm WHERE NOT EXISTS "
            "(SELECT 1 FROM oms_gateway.gw_shop s WHERE s.id = sm.shop_id))"
        ))
        await conn.execute(text(
            "DELETE FROM oms_stock.inv_sales_material WHERE NOT EXISTS "
            "(SELECT 1 FROM oms_gateway.gw_shop s WHERE s.id = inv_sales_material.shop_id)"
        ))
        # 订单子表（按 order_id 关联主表）
        for t in ORDER_CHILD_TABLES:
            await conn.execute(text(
                f"DELETE FROM oms_order.{t} WHERE order_id IN "
                f"(SELECT id FROM oms_order.ord_order WHERE {_like('order_bn', DOC)})"
            ))
        for schema, table, col, prefixes in CLEANUP_TARGETS:
            await conn.execute(text(
                f"DELETE FROM {schema}.{table} WHERE {_like(col, prefixes)}"
            ))
        # 网关缓冲行（子表）
        await conn.execute(text(
            "DELETE FROM oms_gateway.gw_order_buffer_item WHERE buffer_id IN "
            f"(SELECT id FROM oms_gateway.gw_order_buffer WHERE {_like('platform_order_bn', DOC)})"
        ))
        # 组织节点关系（孤儿）
        await conn.execute(text(
            "DELETE FROM oms_org.org_node_relation WHERE node_id IN "
            f"(SELECT id FROM oms_org.org_node WHERE {_like('org_code', T_)})"
        ))
        # 导入错误行
        await conn.execute(text(
            "DELETE FROM oms_base.bas_import_error WHERE task_id IN "
            f"(SELECT id FROM oms_base.bas_import_task WHERE {_like('task_bn', DOC)})"
        ))
    await engine.dispose()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def auth_client(client):
    """已登录 client（admin 超管，header 带 access token）——受保护业务域测试用"""
    r = await client.post("/api/v1/auth/login", json={
        "login_name": "admin", "password": "Ktoms@2026",
    })
    assert r.status_code == 200, r.text
    token = r.json()["data"]["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    yield client
    client.headers.pop("Authorization", None)
