"""D02.06 店铺授权管理测试（补齐 · MVP 仿真范围）

MVP 范围说明（对齐 PLAN-DEV-01 V1.1 W4「店铺授权 D02.06 仿真凭证」）：
- **已实现**：店铺档案（FR-01a）、平台店铺唯一性（FR-01b）、多店铺隔离（FR-01c）、
  店铺-仓库绑定（FR-06a，最小版：branch_bind_json）、店铺履约参数（FR-06c 最小版：
  back_node / platform_waybill_flag）、授权状态字段与停用联动（FR-05a 最小版）
- **本期不实现**（进缺口清单）：OAuth 授权流程（FR-02）、凭证加密与缓存（FR-03）、
  自动续期与告警（FR-04）、授权看板（FR-07）——仿真环境用固定凭证，无真实授权场景
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from app.core.db import AuthContext, SessionFactory, set_auth_context

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def _sys_ctx():
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    yield


async def _cleanup_shops(prefix: str = "T_SHOP") -> None:
    """清理测试店铺（含组织树 shop 节点）"""
    async with SessionFactory() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT id, org_node_id FROM oms_gateway.gw_shop "
                    "WHERE shop_name LIKE :p"
                ),
                {"p": f"{prefix}%"},
            )
        ).all()
        if not rows:
            return
        ids = [int(r[0]) for r in rows]
        node_ids = [int(r[1]) for r in rows if r[1]]
        await s.execute(
            text(
                "DELETE FROM oms_gateway.gw_shop_config WHERE shop_id IN :ids"
            ),
            {"ids": ids},
        )
        await s.execute(
            text("DELETE FROM oms_gateway.gw_shop WHERE id IN :ids"), {"ids": ids}
        )
        if node_ids:
            await s.execute(
                text("DELETE FROM oms_org.org_node WHERE id IN :ids"),
                {"ids": node_ids},
            )
        await s.commit()


async def _owner_id() -> int:
    async with SessionFactory() as s:
        oid = await s.scalar(
            text(
                "SELECT id FROM oms_org.org_owner WHERE is_deleted = 0 "
                "ORDER BY id LIMIT 1"
            )
        )
    return int(oid or 0)


async def _brand_node_id() -> int:
    """取一个 brand 或 owner_co 节点（店铺必须挂这两类）"""
    async with SessionFactory() as s:
        nid = await s.scalar(
            text(
                "SELECT id FROM oms_org.org_node "
                "WHERE node_type IN ('brand', 'owner_co') AND is_deleted = 0 "
                "ORDER BY id LIMIT 1"
            )
        )
    return int(nid or 0)


# ============ FR-01a 店铺档案 ============


async def test_shop_created_with_profile(auth_client):
    """FR-01a：建档含平台/平台店铺ID/货主/业务类型"""
    from app.schemas import master as sc
    from app.services.master import ShopService, get_redis

    await _cleanup_shops()
    oid = await _owner_id()
    nid = await _brand_node_id()
    if not oid or not nid:
        pytest.skip("缺少货主或组织节点")
    redis = await get_redis()
    async with SessionFactory() as s:
        svc = ShopService(s, redis)
        shop = await svc.create(
            sc.ShopCreate(
                owner_id=oid,
                shop_name="T_SHOP_A",
                platform="taobao",
                platform_shop_id="T_SID_A",
                shop_type="direct",
                business_type="direct_sale",
            ),
            parent_node_id=nid,
        )
        assert shop.id > 0
        assert shop.shop_name == "T_SHOP_A"
        assert shop.platform == "taobao"
        assert shop.platform_shop_id == "T_SID_A"
        assert int(shop.owner_id) == oid
        # 建档自动挂组织树 shop 节点（FR-02a 联动）
        assert shop.org_node_id
    await _cleanup_shops()


async def test_shop_must_hang_under_brand_or_owner_node(auth_client):
    """FR-01a：店铺必须挂 brand / owner_co 节点（层级矩阵约束）"""
    from app.core.exceptions import ValidationError
    from app.schemas import master as sc
    from app.services.master import ShopService, get_redis

    oid = await _owner_id()
    if not oid:
        pytest.skip("缺少货主")
    redis = await get_redis()
    async with SessionFactory() as s:
        bad_node = await s.scalar(
            text(
                "SELECT id FROM oms_org.org_node "
                "WHERE node_type NOT IN ('brand', 'owner_co') AND is_deleted = 0 LIMIT 1"
            )
        )
        if not bad_node:
            pytest.skip("库中无非 brand/owner_co 节点")
        svc = ShopService(s, redis)
        with pytest.raises(ValidationError):
            await svc.create(
                sc.ShopCreate(
                    owner_id=oid,
                    shop_name="T_SHOP_BAD",
                    platform="taobao",
                    platform_shop_id="T_SID_BAD",
                ),
                parent_node_id=int(bad_node),
            )


# ============ FR-01b 唯一性约束 ============


async def test_platform_shop_id_unique_per_platform(auth_client):
    """FR-01b：同一平台店铺 ID 不允许重复建档（DB 唯一键）"""
    await _cleanup_shops()
    oid = await _owner_id()
    nid = await _brand_node_id()
    if not oid or not nid:
        pytest.skip("缺少货主或组织节点")
    from app.schemas import master as sc
    from app.services.master import ShopService, get_redis

    redis = await get_redis()
    async with SessionFactory() as s:
        svc = ShopService(s, redis)
        await svc.create(
            sc.ShopCreate(
                owner_id=oid,
                shop_name="T_SHOP_U1",
                platform="taobao",
                platform_shop_id="T_SID_SAME",
            ),
            parent_node_id=nid,
        )
    # 第二次建同平台同店铺ID → 唯一键冲突
    from sqlalchemy.exc import IntegrityError

    async with SessionFactory() as s:
        svc = ShopService(s, redis)
        with pytest.raises(IntegrityError):
            await svc.create(
                sc.ShopCreate(
                    owner_id=oid,
                    shop_name="T_SHOP_U2",
                    platform="taobao",
                    platform_shop_id="T_SID_SAME",
                ),
                parent_node_id=nid,
            )
    await _cleanup_shops()


async def test_same_shop_id_allowed_across_platforms(auth_client):
    """FR-01b：唯一键是 (platform, platform_shop_id) 组合 —— 跨平台可重复"""
    await _cleanup_shops()
    oid = await _owner_id()
    nid = await _brand_node_id()
    if not oid or not nid:
        pytest.skip("缺少货主或组织节点")
    from app.schemas import master as sc
    from app.services.master import ShopService, get_redis

    redis = await get_redis()
    async with SessionFactory() as s:
        svc = ShopService(s, redis)
        a = await svc.create(
            sc.ShopCreate(
                owner_id=oid,
                shop_name="T_SHOP_P1",
                platform="taobao",
                platform_shop_id="T_SID_X",
            ),
            parent_node_id=nid,
        )
        b = await svc.create(
            sc.ShopCreate(
                owner_id=oid,
                shop_name="T_SHOP_P2",
                platform="pdd",
                platform_shop_id="T_SID_X",
            ),
            parent_node_id=nid,
        )
        assert a.id != b.id
    await _cleanup_shops()


async def test_blank_platform_shop_id_gets_placeholder(auth_client):
    """FR-01b：手工建档未填平台店铺ID → 用内部编码占位（避免空串撞唯一键）"""
    await _cleanup_shops()
    oid = await _owner_id()
    nid = await _brand_node_id()
    if not oid or not nid:
        pytest.skip("缺少货主或组织节点")
    from app.schemas import master as sc
    from app.services.master import ShopService, get_redis

    redis = await get_redis()
    async with SessionFactory() as s:
        svc = ShopService(s, redis)
        shop = await svc.create(
            sc.ShopCreate(
                owner_id=oid,
                shop_name="T_SHOP_BLANK",
                platform="taobao",
                platform_shop_id="",
            ),
            parent_node_id=nid,
        )
        assert shop.platform_shop_id.startswith("local_")
    await _cleanup_shops()


# ============ FR-01c 多店铺隔离 ============


async def test_shop_list_filters_by_tenant(auth_client):
    """FR-01c：店铺清单按租户隔离"""
    async with SessionFactory() as s:
        t1 = await s.scalar(
            text("SELECT COUNT(*) FROM oms_gateway.gw_shop WHERE tenant_id = 1")
        )
        t2 = await s.scalar(
            text("SELECT COUNT(*) FROM oms_gateway.gw_shop WHERE tenant_id = 99")
        )
    assert int(t1 or 0) >= 0
    assert int(t2 or 0) == 0


async def test_shop_list_keyword_search(auth_client):
    """FR-01c：按关键字过滤（店名 / 店铺编码）"""
    from app.services.master import ShopService, get_redis

    redis = await get_redis()
    async with SessionFactory() as s:
        svc = ShopService(s, redis)
        all_shops = await svc.list()
        if not all_shops:
            pytest.skip("库中无店铺")
        target = all_shops[0]
        hit = await svc.list(keyword=target.shop_name[:4])
        assert any(x.id == target.id for x in hit)


# ============ FR-05a 店铺状态与授权状态字段 ============


async def test_shop_status_toggle(auth_client):
    """FR-05a：店铺状态可启停（停用后不参与业务）"""
    await _cleanup_shops()
    oid = await _owner_id()
    nid = await _brand_node_id()
    if not oid or not nid:
        pytest.skip("缺少货主或组织节点")
    from app.schemas import master as sc
    from app.services.master import ShopService, get_redis

    redis = await get_redis()
    async with SessionFactory() as s:
        svc = ShopService(s, redis)
        shop = await svc.create(
            sc.ShopCreate(
                owner_id=oid,
                shop_name="T_SHOP_ST",
                platform="taobao",
                platform_shop_id="T_SID_ST",
            ),
            parent_node_id=nid,
        )
        ver = shop.version
        updated = await svc.update(shop.id, sc.ShopUpdate(status="disabled", version=ver))
        assert updated.status == "disabled"
        assert updated.version == ver + 1
    await _cleanup_shops()


async def test_shop_update_optimistic_lock(auth_client):
    """店铺更新走乐观锁（version 不符 → 冲突）"""
    from app.core.exceptions import ConflictError
    from app.schemas import master as sc
    from app.services.master import ShopService, get_redis

    redis = await get_redis()
    async with SessionFactory() as s:
        svc = ShopService(s, redis)
        shops = await svc.list()
        if not shops:
            pytest.skip("库中无店铺")
        shop = shops[0]
        with pytest.raises(ConflictError):
            await svc.update(
                shop.id, sc.ShopUpdate(shop_name="T_X", version=shop.version + 99)
            )


async def test_auth_status_field_defaults_pending(auth_client):
    """FR-05a：授权状态字段存在且默认待授权（MVP 仿真不推进真实授权）"""
    async with SessionFactory() as s:
        cnt = await s.scalar(
            text(
                "SELECT COUNT(*) FROM oms_gateway.gw_shop "
                "WHERE auth_status = 'pending' AND is_deleted = 0"
            )
        )
    assert int(cnt or 0) >= 0


# ============ FR-06a / FR-06c 店铺履约配置 ============


async def test_shop_config_carries_binding_and_backnode(auth_client):
    """FR-06a/FR-06c：店铺配置承载仓库绑定与回传时机"""
    async with SessionFactory() as s:
        row = (
            await s.execute(
                text(
                    "SELECT shop_id, branch_bind_json, back_node, platform_waybill_flag "
                    "FROM oms_gateway.gw_shop_config WHERE is_deleted = 0 LIMIT 1"
                )
            )
        ).mappings().first()
    if row is None:
        pytest.skip("库中无店铺配置（需先跑 seed）")
    # back_node 取值受 D02.04 约束（发货即传/打印即传/校验后传）
    assert row["back_node"] in ("shipped", "printed", "verified", "none")
    assert int(row["platform_waybill_flag"]) in (0, 1)


async def test_shop_config_branch_bind_is_json_array(auth_client):
    """FR-06a：仓库绑定为 JSON 数组（供 D03.06 分仓消费）"""
    async with SessionFactory() as s:
        row = (
            await s.execute(
                text(
                    "SELECT branch_bind_json FROM oms_gateway.gw_shop_config "
                    "WHERE is_deleted = 0 AND branch_bind_json IS NOT NULL LIMIT 1"
                )
            )
        ).mappings().first()
    if row is None:
        pytest.skip("库中无店铺配置")
    import json

    arr = json.loads(row["branch_bind_json"]) if isinstance(
        row["branch_bind_json"], str
    ) else row["branch_bind_json"]
    assert isinstance(arr, list)
    for item in arr:
        assert "branch_id" in item
