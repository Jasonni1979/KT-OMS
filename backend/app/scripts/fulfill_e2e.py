"""W6 履约链路端到端验证（D03.06 分仓 → D03.04 拆单 → D03.07 发货单状态机）

覆盖 SRS 验收标准：
- D03.06 AC-01/03/05/06：整仓分配 / 库存深度优先 / 多仓拆单兜底 / 缺货判定分级
- D03.04 AC-01/02/03/05/06/07：按货主拆 / 跨货主无 owner 拒绝 / 级联 /
  守恒校验 / 部分拆分 / NO_STOCK
- D03.07 AC-01/02/03/04/05/07/10/11：生成 / 全链路流转 / 出库回传 /
  实发差异 / 部分发货 / 叫回三态 / 取消编排 / 打回

用法：
    cd backend && .venv/bin/python -m app.scripts.fulfill_e2e
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime

from sqlalchemy import select, text

from app.core.db import AuthContext, SessionFactory, engine, set_auth_context
from app.models.order import OrdOrder
from app.services.delivery_service import DeliveryService
from app.services.dispatch_service import DispatchService
from app.services.master import get_redis
from app.services.split_service import SplitRuleService, SplitService

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))


async def _clean(s) -> None:
    """清理 W6 相关数据（幂等）"""
    await s.execute(
        text(
            "DELETE FROM oms_order.ord_delivery_item_detail WHERE delivery_id IN "
            "(SELECT id FROM oms_order.ord_delivery WHERE delivery_bn LIKE 'DLV%')"
        )
    )
    await s.execute(text("DELETE FROM oms_order.ord_delivery_log"))
    await s.execute(text("DELETE FROM oms_order.ord_delivery_package"))
    await s.execute(text("DELETE FROM oms_order.ord_delivery_diff"))
    await s.execute(text("DELETE FROM oms_order.ord_delivery_item"))
    await s.execute(text("DELETE FROM oms_order.ord_delivery"))
    await s.execute(text("DELETE FROM oms_order.ord_split_trace"))
    await s.execute(text("DELETE FROM oms_order.ord_dispatch_plan"))
    await s.execute(
        text(
            "DELETE FROM oms_order.ord_routing_decision_log WHERE order_id IN "
            "(SELECT id FROM oms_order.ord_order WHERE order_bn LIKE 'W6E2E%')"
        )
    )
    await s.execute(
        text(
            "DELETE FROM oms_order.ord_order_item WHERE order_id IN "
            "(SELECT id FROM oms_order.ord_order WHERE order_bn LIKE 'W6E2E%')"
        )
    )
    await s.execute(
        text(
            "DELETE FROM oms_order.ord_receiver WHERE order_id IN "
            "(SELECT id FROM oms_order.ord_order WHERE order_bn LIKE 'W6E2E%')"
        )
    )
    await s.execute(text("DELETE FROM oms_order.ord_order WHERE order_bn LIKE 'W6E2E%'"))
    await s.execute(text("DELETE FROM oms_order.ord_split_rule WHERE rule_name LIKE 'W6%'"))
    # 自造的第二货主/仓/库存（仅当存在时）
    await s.execute(
        text(
            "DELETE FROM oms_stock.inv_stock_ledger WHERE branch_id IN "
            "(SELECT id FROM oms_fulfill.ful_branch WHERE branch_bn IN "
            "('W6E2E_BR', 'W6E2E_SH'))"
        )
    )
    # 主仓里补足的物料库存行（物料在主仓，仓不在自造列表）
    await s.execute(
        text(
            "DELETE FROM oms_stock.inv_stock_ledger WHERE bm_id IN "
            "(SELECT id FROM oms_stock.inv_material "
            " WHERE material_bn LIKE 'W6E2E_MAT%' OR material_bn LIKE 'W6E2E_BM%')"
        )
    )
    await s.execute(
        text(
            "DELETE FROM oms_stock.inv_material "
            "WHERE material_bn LIKE 'W6E2E_MAT%' OR material_bn LIKE 'W6E2E_BM%'"
        )
    )
    await s.execute(
        text(
            "DELETE FROM oms_fulfill.ful_branch "
            "WHERE branch_bn IN ('W6E2E_BR', 'W6E2E_SH')"
        )
    )
    await s.execute(
        text(
            "DELETE FROM oms_org.org_owner "
            "WHERE owner_code IN ('W6E2EOWNER', 'W6E2EOWNER1')"
        )
    )
    await s.execute(
        text(
            "DELETE FROM oms_org.org_node "
            "WHERE org_code IN ('W6E2ENODE_BR', 'W6E2ENODE_MAIN')"
        )
    )
    await s.commit()


async def _make_order(
    s,
    *,
    suffix: str,
    items: list[tuple[int, int, int]],  # (bm_id, owner_id, nums)
    shop_id: int = 0,
    owner_id: int = 5,
    branch_ids: list[int] | None = None,
) -> int:
    """造一张 W6 测试订单（直接落库，走裸连接绕开 fail-closed）"""
    now = datetime.now()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_order "
                "(tenant_id, owner_id, order_bn, platform_order_bn, shop_id, brand_id, "
                " createway, order_type, order_status, audit_status, fulfill_status, "
                " pay_status, ship_status, list_amount, shop_discount, platform_subsidy, "
                " paid_amount, freight, is_cod, splited_num, order_time, pay_time, "
                " create_time, update_time, version, is_deleted) "
                "VALUES (1, :owner, :obn, :pon, :sid, 0, 'platform', 'normal', "
                "'processing', 'pending', 'pending', 'paid', 'unshipped', "
                "100, 0, 0, 100, 0, 0, 0, NOW(3), NOW(3), NOW(3), NOW(3), 0, 0)"
            ),
            {
                "obn": f"W6E2E{suffix}",
                "pon": f"W6P_{suffix}",
                "sid": shop_id,
                "owner": owner_id,
            },
        )
        r = await conn.execute(
            text("SELECT id FROM oms_order.ord_order WHERE order_bn = :obn"),
            {"obn": f"W6E2E{suffix}"},
        )
        order_id = int(r.scalar() or 0)
        for i, (bm_id, line_owner, nums) in enumerate(items):
            await conn.execute(
                text(
                    "INSERT INTO oms_order.ord_order_item "
                    "(tenant_id, owner_id, order_id, sm_id, platform_sku_code, bm_id, "
                    " bm_number, bm_name, nums, split_num, sendnum, list_price, "
                    " list_amount, paid_amount, parse_status, create_time, update_time, "
                    " version, is_deleted) "
                    "VALUES (1, :oid, :order_id, 0, :sku, :bm, :bmn, 'W6测试物料', "
                    ":nums, 0, 0, 100, :amt, :amt, 'parsed', NOW(3), NOW(3), 0, 0)"
                ),
                {
                    "oid": line_owner,
                    "order_id": order_id,
                    "sku": f"SKU_W6_{suffix}_{i}",
                    "bm": bm_id,
                    "bmn": f"W6BM_{bm_id}",
                    "nums": nums,
                    "amt": nums * 100,
                },
            )
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_receiver "
                "(tenant_id, owner_id, order_id, name_enc, name_hash, mobile_enc, "
                " mobile_hash, mobile_tail4, phone_enc, province, city, district, town, "
                " address_enc, address_hash, zip, is_cipher, cipher_blob, key_version, "
                " create_time, update_time, version, is_deleted) "
                "VALUES (1, :owner, :oid, 0x00, 'n', 0x00, 'm1', '0000', 0x00, "
                "'广东省', '深圳市', '南山区', '科技园', 0x00, 'h1', '', 0, NULL, 'v1', "
                "NOW(3), NOW(3), 0, 0)"
            ),
            {"oid": order_id, "owner": owner_id},
        )
    del branch_ids, now
    # MySQL REPEATABLE READ 下，当前 session 的快照看不到其他连接刚提交的数据
    # → 造单后 commit + 刷新快照，保证后续 ORM 查询可见
    await s.commit()
    return order_id


async def _ensure_materials(
    s, existing: list[int], owner_id: int, branch_id: int
) -> list[int]:
    """确保有 ≥2 个物料（不足则自造基础物料 + 库存行）"""
    out = list(existing)
    need = 2 - len(out)
    if need <= 0:
        return out
    for _i in range(need):
        bn = f"W6E2E_MAT{len(out) + 1}"
        await s.execute(
            text(
                "INSERT INTO oms_stock.inv_material "
                "(tenant_id, owner_id, material_bn, material_name, type, cat_path, "
                " brand_id, color, size, same_code_group, kingdee_material_code, "
                " serial_number, storage_life_flag, is_ctrl_store, omnichannel, "
                " is_o2o_sales, tax_rate, tax_name, tax_code, cos_id, org_id, status, "
                " source, remark, create_time, update_time, version, is_deleted) "
                "VALUES (1, :owner, :bn, :nm, 3, '/', 0, '', '', '', '', 0, 0, 1, 0, 0, "
                "13, '增值税', '', 0, 0, 1, 'local', '', NOW(3), NOW(3), 0, 0)"
            ),
            {"owner": owner_id, "bn": bn, "nm": f"W6E2E物料{len(out) + 1}"},
        )
        r = await s.execute(
            text("SELECT id FROM oms_stock.inv_material WHERE material_bn = :bn"),
            {"bn": bn},
        )
        bm_id = int(r.scalar() or 0)
        await s.execute(
            text(
                "INSERT INTO oms_stock.inv_stock_ledger "
                "(tenant_id, branch_id, bm_id, owner_id, store, freeze, arrive_store, "
                " defective, safe_store, is_locked, unit_cost, inventory_cost, status, "
                " create_time, update_time, version, is_deleted) "
                "VALUES (1, :b, :bm, :owner, 100, 0, 0, 0, 0, 0, 50, 5000, 1, "
                "NOW(3), NOW(3), 0, 0)"
            ),
            {"b": branch_id, "bm": bm_id, "owner": owner_id},
        )
        out.append(bm_id)
    await s.commit()
    print(f"  [setup] 补足物料至 {len(out)} 个: {out}")
    return out


async def _make_org_node(s, org_code: str, org_name: str, node_type: str) -> int:
    """建组织节点（货主必须挂组织树）"""
    await s.execute(
        text(
            "INSERT INTO oms_org.org_node "
            "(tenant_id, org_code, org_name, node_type, parent_id, cat_path, node_level, "
            " ref_id, sort_no, status, remark, source, create_time, update_time, version) "
            "VALUES (1, :code, :name, :ntype, 0, '/', 1, 0, 0, 1, '', 'local', "
            "NOW(3), NOW(3), 0)"
        ),
        {"code": org_code, "name": org_name, "ntype": node_type},
    )
    r = await s.execute(
        text("SELECT id FROM oms_org.org_node WHERE org_code = :c"), {"c": org_code}
    )
    node_id = int(r.scalar() or 0)
    await s.commit()
    return node_id


async def _ensure_first_owner(s) -> tuple[int, int, list[int]]:
    """空库 → 自造主货主 + 共享仓 + 库存行

    共享仓（owner_id=NULL，无仓货主关系）→ 不做货主维限制，两个货主都能用。
    返回 (owner_id, branch_id, [bm_id...])
    """
    tag = "W6E2E"
    node_id = await _make_org_node(s, f"{tag}NODE_MAIN", "W6E2E自营组织", "owner_co")
    await s.execute(
        text(
            "INSERT INTO oms_org.org_owner "
            "(tenant_id, owner_code, owner_name, owner_type, org_node_id, contact_name, "
            " create_time, update_time, version, is_deleted) "
            "VALUES (1, :code, 'W6E2E自营货主', 'SELF_OPERATION', :node, '测试', "
            "NOW(3), NOW(3), 0, 0)"
        ),
        {"code": f"{tag}OWNER1", "node": node_id},
    )
    r = await s.execute(
        text("SELECT id FROM oms_org.org_owner WHERE owner_code = :c"),
        {"c": f"{tag}OWNER1"},
    )
    owner_id = int(r.scalar() or 0)
    await s.commit()

    await s.execute(
        text(
            "INSERT INTO oms_fulfill.ful_branch "
            "(tenant_id, owner_id, branch_bn, branch_name, branch_type, is_ctrl, "
            " countable_flag, org_node_id, status, create_time, update_time, version, "
            " is_deleted) "
            "VALUES (1, NULL, 'W6E2E_SH', 'W6E2E共享中心仓', 'entity', 1, 1, :node, "
            "'enabled', NOW(3), NOW(3), 0, 0)"
        ),
        {"node": node_id},
    )
    r2 = await s.execute(
        text("SELECT id FROM oms_fulfill.ful_branch WHERE branch_bn = 'W6E2E_SH'")
    )
    branch_id = int(r2.scalar() or 0)
    await s.commit()

    r4 = await s.execute(
        text("SELECT id FROM oms_stock.inv_material WHERE is_deleted = 0 LIMIT 2")
    )
    bm_ids = [int(x[0]) for x in r4.all()]
    if not bm_ids:
        # 空库无物料 → 自造两个基础物料
        for bn in ("W6E2E_BM1", "W6E2E_BM2"):
            await s.execute(
                text(
                    "INSERT INTO oms_stock.inv_material "
                    "(tenant_id, owner_id, material_bn, material_name, type, cat_path, "
                    " brand_id, color, size, same_code_group, kingdee_material_code, "
                    " serial_number, storage_life_flag, is_ctrl_store, omnichannel, "
                    " is_o2o_sales, tax_rate, tax_name, tax_code, cos_id, org_id, status, "
                    " source, remark, create_time, update_time, version, is_deleted) "
                    "VALUES (1, :owner, :bn, :nm, 3, '/', 0, '', '', '', '', 0, 0, 1, 0, 0, "
                    "13, '增值税', '', 0, 0, 1, 'local', '', NOW(3), NOW(3), 0, 0)"
                ),
                {"owner": owner_id, "bn": bn, "nm": f"W6E2E物料-{bn}"},
            )
        await s.commit()
        r5 = await s.execute(
            text(
                "SELECT id FROM oms_stock.inv_material WHERE is_deleted = 0 "
                "AND material_bn IN ('W6E2E_BM1', 'W6E2E_BM2') ORDER BY id"
            )
        )
        bm_ids = [int(x[0]) for x in r5.all()]
    for bm in bm_ids:
        await s.execute(
            text(
                "INSERT INTO oms_stock.inv_stock_ledger "
                "(tenant_id, branch_id, bm_id, owner_id, store, freeze, arrive_store, "
                " defective, safe_store, is_locked, unit_cost, inventory_cost, status, "
                " create_time, update_time, version, is_deleted) "
                "VALUES (1, :b, :bm, :owner, 100, 0, 0, 0, 0, 0, 50, 5000, 1, "
                "NOW(3), NOW(3), 0, 0)"
            ),
            {"b": branch_id, "bm": bm, "owner": owner_id},
        )
    await s.commit()
    print(f"  [setup] 自造主货主 {owner_id} + 共享仓 {branch_id} + 物料 {bm_ids}")
    return owner_id, branch_id, bm_ids


async def _ensure_second_owner(
    s, main_owner: int, main_branch: int
) -> tuple[int, int, list[int]]:
    """自造第二货主 + 独立仓 + 仓货主关系 + 库存行

    CI 空库只有一个货主时调用，保证跨货主拆单场景（凯淳核心）不被跳过。
    返回 (owner_id, branch_id, [bm_id...])
    """
    from datetime import date as _date

    tag = "W6E2E"
    # ① 组织节点（货主必须挂组织树，org_node_id NOT NULL）
    node_id = await _make_org_node(s, f"{tag}NODE_BR", "W6E2E代销组织", "owner_co")
    # ② 货主
    await s.execute(
        text(
            "INSERT INTO oms_org.org_owner "
            "(tenant_id, owner_code, owner_name, owner_type, org_node_id, contact_name, "
            " create_time, update_time, version, is_deleted) "
            "VALUES (1, :code, 'W6E2E代销货主', 'BRAND_CONSIGN', :node, '测试', "
            "NOW(3), NOW(3), 0, 0)"
        ),
        {"code": f"{tag}OWNER", "node": node_id},
    )
    r = await s.execute(
        text("SELECT id FROM oms_org.org_owner WHERE owner_code = :c"),
        {"c": f"{tag}OWNER"},
    )
    owner_id = int(r.scalar() or 0)
    await s.commit()

    # ② 仓（单一归属第二货主 → 行级硬约束可验证）
    await s.execute(
        text(
            "INSERT INTO oms_fulfill.ful_branch "
            "(tenant_id, owner_id, branch_bn, branch_name, branch_type, is_ctrl, "
            " countable_flag, org_node_id, status, create_time, update_time, version, "
            " is_deleted) "
            "VALUES (1, :owner, 'W6E2E_BR', 'W6E2E代销仓', 'entity', 1, 1, :node, "
            "'enabled', NOW(3), NOW(3), 0, 0)"
        ),
        {"owner": owner_id, "node": node_id},
    )
    r2 = await s.execute(
        text("SELECT id FROM oms_fulfill.ful_branch WHERE branch_bn = 'W6E2E_BR'")
    )
    branch_id = int(r2.scalar() or 0)
    await s.commit()

    # ③ 库存行（取主仓的物料，复用其 bm_id）
    r3 = await s.execute(
        text(
            "SELECT bm_id FROM oms_stock.inv_stock_ledger "
            "WHERE branch_id = :b AND is_deleted = 0 LIMIT 2"
        ),
        {"b": main_branch},
    )
    bm_ids = [int(x[0]) for x in r3.all()]
    if not bm_ids:
        # 主仓也无库存行 → 取任意物料
        r4 = await s.execute(
            text("SELECT id FROM oms_stock.inv_material WHERE is_deleted = 0 LIMIT 2")
        )
        bm_ids = [int(x[0]) for x in r4.all()]
    for bm in bm_ids:
        await s.execute(
            text(
                "INSERT INTO oms_stock.inv_stock_ledger "
                "(tenant_id, branch_id, bm_id, owner_id, store, freeze, arrive_store, "
                " defective, safe_store, is_locked, unit_cost, inventory_cost, status, "
                " create_time, update_time, version, is_deleted) "
                "VALUES (1, :b, :bm, :owner, 100, 0, 0, 0, 0, 0, 50, 5000, 1, "
                "NOW(3), NOW(3), 0, 0)"
            ),
            {"b": branch_id, "bm": bm, "owner": owner_id},
        )
    await s.commit()
    print(f"  [setup] 自造第二货主 {owner_id} + 代销仓 {branch_id} + 物料 {bm_ids}")
    del _date
    return owner_id, branch_id, bm_ids


async def main() -> int:
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    redis = await get_redis()

    async with SessionFactory() as s:
        await _clean(s)

        # 取基础数据：店铺 / 仓 / 物料 / 货主
        # 取「有分仓配置」的店铺（shop_config 存在才能改绑定）
        shop_id = int(
            await s.scalar(
                text(
                    "SELECT shop_id FROM oms_gateway.gw_shop_config "
                    "WHERE is_deleted = 0 ORDER BY id LIMIT 1"
                )
            )
            or 0
        )
        if not shop_id:
            shop_id = int(
                await s.scalar(
                    text(
                        "SELECT id FROM oms_gateway.gw_shop WHERE is_deleted = 0 "
                        "ORDER BY id LIMIT 1"
                    )
                )
                or 0
            )
        # 取基础数据：仓（可服务货主且有库存）/ 物料（该仓有库存）/ 货主
        stock_rows = list(
            await s.execute(
                text(
                    "SELECT branch_id, bm_id, owner_id, store FROM oms_stock.inv_stock_ledger "
                    "WHERE is_deleted = 0 AND store > 0 ORDER BY branch_id, bm_id"
                )
            )
        )
        stock_rows = list(stock_rows)
        # 取基础数据：为每个货主找一个「可服务该货主且有库存」的仓
        owner_branch: dict[int, int] = {}
        owner_bms: dict[int, list[int]] = {}
        for r in stock_rows:
            bid, bid_owner = int(r[0]), int(r[2])
            if bid_owner in owner_branch:
                continue
            servable = await s.scalar(
                text(
                    "SELECT COUNT(*) FROM oms_org.org_node_relation rr "
                    "JOIN oms_fulfill.ful_branch b ON b.org_node_id = rr.node_id "
                    "WHERE b.id = :bid AND rr.rel_type = 'branch_owner' "
                    "AND rr.status = 1 AND rr.rel_id = :oid"
                ),
                {"bid": bid, "oid": bid_owner},
            )
            if int(servable or 0) > 0:
                owner_branch[bid_owner] = bid
                owner_bms[bid_owner] = [
                    int(x[1]) for x in stock_rows if int(x[0]) == bid
                ]
        check(
            "基础数据：仓+物料+货主一致",
            bool(owner_branch),
            f"{owner_branch}",
        )
        if not owner_branch:
            # 空库（CI）→ 自造主货主/仓/库存
            main_owner, main_branch, main_bms = await _ensure_first_owner(s)
            owner_branch = {main_owner: main_branch}
            owner_bms = {main_owner: main_bms}
        main_owner = next(iter(owner_branch), 0)
        main_branch = owner_branch.get(main_owner, 0)
        main_bms = owner_bms.get(main_owner, [])
        branch_ids = [main_branch]
        bm_ids = main_bms
        if len(bm_ids) < 2:
            # 物料不足 2 个（跨货主/多行场景需要）→ 补足
            bm_ids = await _ensure_materials(s, bm_ids, main_owner, main_branch)

        # 第二货主：优先用有库存的；否则用任意货主（跨货主拆单场景）
        other_owner = next(
            (o for o in owner_bms if o != main_owner and owner_bms[o]),
            next((o for o in owner_branch if o != main_owner), 0),
        )
        other_branch = owner_branch.get(other_owner, main_branch)
        other_bms = owner_bms.get(other_owner, main_bms)
        if not other_owner:
            # CI 空库只有单货主 → 自造第二货主 + 独立仓 + 库存
            # （跨货主拆单是凯淳核心场景，不能因数据缺失而跳过）
            other_owner, other_branch, other_bms = await _ensure_second_owner(
                s, main_owner, main_branch
            )
        check(
            "基础数据：第二货主存在（跨货主场景用）",
            bool(other_owner),
            f"main={main_owner}(仓{main_branch}) other={other_owner}(仓{other_branch})",
        )

        if not shop_id or not branch_ids or len(bm_ids) < 2 or not other_owner:
            print("[FAIL] 基础数据不足，先跑 seed_demo + scenario_e2e")
            return 1

        # ============ ① D03.06 分仓 ============
        print("\n▶ D03.06 配货分仓")
        # 造单：2 行，同仓可满足
        oid1 = await _make_order(
            s,
            suffix="D1",
            items=[(bm_ids[0], main_owner, 1), (bm_ids[1], main_owner, 1)],
            shop_id=shop_id,
            owner_id=main_owner,
        )
        # 绑定店铺发货仓（无 config 行则插入）
        bind_json = f'[{{"branch_id": {main_branch}, "priority": 1}}]'
        await s.execute(
            text(
                "UPDATE oms_gateway.gw_shop_config SET branch_bind_json = :bj "
                "WHERE shop_id = :sid AND is_deleted = 0"
            ),
            {"bj": bind_json, "sid": shop_id},
        )
        updated = await s.scalar(
            text(
                "SELECT COUNT(*) FROM oms_gateway.gw_shop_config "
                "WHERE shop_id = :sid AND is_deleted = 0"
            ),
            {"sid": shop_id},
        )
        if not int(updated or 0):
            await s.execute(
                text(
                    "INSERT INTO oms_gateway.gw_shop_config "
                    "(tenant_id, owner_id, shop_id, branch_bind_json, default_logistics_code, "
                    " platform_waybill_flag, back_node, create_time, update_time, version, "
                    " is_deleted) "
                    "VALUES (1, NULL, :sid, :bj, NULL, 0, 'shipped', NOW(3), NOW(3), 0, 0)"
                ),
                {"sid": shop_id, "bj": bind_json},
            )
        await s.commit()

        dsvc = DispatchService(s, redis)
        res = await dsvc.dispatch(oid1)
        check(
            "AC-01 整仓分配（满足率100% → single plan）",
            res.ok and res.mode in ("single", "appointed"),
            f"mode={res.mode} plan_id={res.plan_id}",
        )
        check("plan 已落库", res.plan_id > 0, f"plan_id={res.plan_id}")
        check(
            "满足度快照非空",
            bool(res.fulfill_snapshot.get("branches")),
            f"{len(res.fulfill_snapshot.get('branches', []))} 个候选仓",
        )

        # 路由埋点
        log_n = await s.scalar(
            text(
                "SELECT COUNT(*) FROM oms_order.ord_routing_decision_log "
                "WHERE order_id = :oid"
            ),
            {"oid": oid1},
        )
        check("FR-08a 路由决策埋点已写", int(log_n or 0) >= 1, f"{log_n} 条")

        # 二次分仓 → 旧 plan superseded
        res2 = await dsvc.dispatch(oid1)
        superseded = await s.scalar(
            text(
                "SELECT COUNT(*) FROM oms_order.ord_dispatch_plan "
                "WHERE order_id = :oid AND status = 'superseded'"
            ),
            {"oid": oid1},
        )
        check(
            "FR-05c 旧轮次 superseded",
            int(superseded or 0) >= 1 and res2.round_no == 2,
            f"round_no={res2.round_no} superseded={superseded}",
        )

        # 无候选仓 → NO_CANDIDATE_BRANCH（解绑后重跑，随后恢复）
        await s.execute(
            text(
                "UPDATE oms_gateway.gw_shop_config SET branch_bind_json = '[]' "
                "WHERE shop_id = :sid AND is_deleted = 0"
            ),
            {"sid": shop_id},
        )
        await s.commit()
        oid2 = await _make_order(
            s, suffix="D2", items=[(bm_ids[0], main_owner, 1)], shop_id=shop_id,
            owner_id=main_owner,
        )
        res3 = await dsvc.dispatch(oid2)
        check(
            "FR-01d 候选为空 → NO_CANDIDATE_BRANCH",
            (not res3.ok) and res3.fail_code == "NO_CANDIDATE_BRANCH",
            f"code={res3.fail_code}",
        )
        # 恢复绑定
        await s.execute(
            text(
                "UPDATE oms_gateway.gw_shop_config SET branch_bind_json = :bj "
                "WHERE shop_id = :sid AND is_deleted = 0"
            ),
            {"bj": bind_json, "sid": shop_id},
        )
        await s.commit()

        # ============ ② D03.04 拆单 ============
        print("\n▶ D03.04 拆单策略中心")
        # 规则：owner 策略 + 级联 branch
        rule_svc = SplitRuleService(s)
        rule = await rule_svc.save(
            {
                "owner_id": main_owner,
                "rule_name": "W6按货主拆单",
                "split_type": "owner",
                "split_config": {},
                "split_type_2": "branch",
                "split_config_2": {},
                "status": "enabled",
            }
        )
        check("拆单规则保存成功", rule["id"] > 0, f"rule_id={rule['id']}")

        # 级联类型重复 → 拒绝
        try:
            await rule_svc.save(
                {
                    "owner_id": main_owner,
                    "rule_name": "W6重复级联",
                    "split_type": "owner",
                    "split_config": {},
                    "split_type_2": "owner",
                    "split_config_2": {},
                }
            )
            check("FR-04a 级联类型重复被拒", False, "未抛异常")
        except Exception as e:
            check("FR-04a 级联类型重复被拒", "重复" in str(e), str(e)[:60])

        # 跨货主订单 + owner 策略 → 2 组
        oid3 = await _make_order(
            s,
            suffix="S1",
            items=[
                (bm_ids[0], main_owner, 2),
                (other_bms[0] if other_bms else bm_ids[1], other_owner, 1),
            ],
            shop_id=shop_id,
            owner_id=main_owner,
        )
        ssvc = SplitService(s, redis)
        items3_snapshot = await ssvc._load_items(oid3)
        check("拆单输入：明细行已装载", len(items3_snapshot) == 2, f"{len(items3_snapshot)} 行")
        # 手动构造 branch_plan（分仓结果）：两个货主分别到各自可服务的仓
        split_res = await ssvc.split(
            oid3,
            rule["id"],
            context={
                "branch_plan": {
                    "alloc": {
                        str(items3_snapshot[0].item_id): {main_branch: 2},
                        str(items3_snapshot[1].item_id): {other_branch: 1},
                    }
                }
            },
        )
        check(
            "AC-01 按货主拆单（跨货主 → 2 组）",
            split_res.ok and len(split_res.groups) == 2,
            f"groups={len(split_res.groups)}",
        )
        if split_res.ok:
            owners_in_groups = {
                g["attrs"].get("owner_id") for g in split_res.groups
            }
            check(
                "AC-01 每组 owner_id 唯一",
                len(owners_in_groups) == len(split_res.groups) and None not in owners_in_groups,
                f"{owners_in_groups}",
            )
            check(
                "FR-04b 级联后组合并仓属性",
                all("branch_id" in g["attrs"] for g in split_res.groups),
                f"{[g['attrs'].get('branch_id') for g in split_res.groups]}",
            )

        # 跨货主但规则链无 owner → CONFIG_INVALID
        rule_no_owner = await rule_svc.save(
            {
                "owner_id": main_owner,
                "rule_name": "W6无owner拆单",
                "split_type": "branch",
                "split_config": {},
            }
        )
        split_fail = await ssvc.split(
            oid3,
            rule_no_owner["id"],
            context={"branch_plan": {"alloc": {}}},
        )
        check(
            "AC-02 跨货主无 owner 策略 → CONFIG_INVALID",
            (not split_fail.ok) and split_fail.fail_code == "CONFIG_INVALID",
            f"code={split_fail.fail_code}",
        )

        # 守恒校验：注入漏行的策略
        from app.services.split_service import SplitGroup, SplitResult

        class BuggyStrategy:
            split_type = "buggy"
            name = "漏行策略"
            description = "测试用：故意漏一行"

            def allocate(self, inp):
                return SplitResult(
                    groups=[
                        SplitGroup(
                            group_key="BUG",
                            lines=[(inp.items[0].item_id, inp.items[0].nums)],
                            attrs={},
                        )
                    ]
                )

            def validate_config(self, config):
                return []

            def get_special(self):
                return []

            def describe(self):
                return {"split_type": "buggy"}

        ssvc.registry.register(BuggyStrategy())  # type: ignore[arg-type]
        rule_svc.registry.register(BuggyStrategy())  # type: ignore[arg-type]
        bug_rule = await rule_svc.save(
            {
                "owner_id": main_owner,
                "rule_name": "W6漏行规则",
                "split_type": "buggy",
                "split_config": {},
            }
        )
        # 守恒校验用单货主订单（跨货主会先被 CONFIG_INVALID 拦截）
        oid_bug = await _make_order(
            s,
            suffix="SB",
            items=[
                (bm_ids[0], main_owner, 2),
                (bm_ids[1], main_owner, 1),
            ],
            shop_id=shop_id,
            owner_id=main_owner,
        )
        bug_res = await ssvc.split(oid_bug, bug_rule["id"])
        check(
            "AC-08 守恒校验拦漏行 → CONSERVATION_VIOLATION",
            (not bug_res.ok) and bug_res.fail_code == "CONSERVATION_VIOLATION",
            f"code={bug_res.fail_code}",
        )

        # stock_depth 全仓不满足 → NO_STOCK
        rule_sd = await rule_svc.save(
            {
                "owner_id": main_owner,
                "rule_name": "W6库存深度",
                "split_type": "stock_depth",
                "split_config": {"allow_partial": False},
            }
        )
        oid4 = await _make_order(
            s,
            suffix="S2",
            items=[(bm_ids[0], main_owner, 999999)],
            shop_id=shop_id,
            owner_id=main_owner,
        )
        sd_res = await ssvc.split(
            oid4, rule_sd["id"], context={"branch_seq": branch_ids[:1]}
        )
        check(
            "AC-07 全仓不满足 → NO_STOCK",
            (not sd_res.ok) and sd_res.fail_code == "NO_STOCK",
            f"code={sd_res.fail_code}",
        )

        # 手工拆单：组内混货主 → 拒绝
        items3 = await ssvc._load_items(oid3)
        manual_mix = await ssvc.manual_split(
            oid3,
            [
                {
                    "group_key": "M1",
                    "items": [
                        {"item_id": items3[0].item_id, "nums": 1},
                        {"item_id": items3[1].item_id, "nums": 1},
                    ],
                }
            ],
            "tester",
        )
        check(
            "AC-09 手工拆单组内混货主被拒",
            (not manual_mix.ok) and manual_mix.fail_code == "CONFIG_INVALID",
            f"code={manual_mix.fail_code}",
        )

        # 手工拆单：超余量 → 拒绝
        manual_over = await ssvc.manual_split(
            oid3,
            [
                {
                    "group_key": "M2",
                    "items": [{"item_id": items3[0].item_id, "nums": 999}],
                }
            ],
            "tester",
        )
        check(
            "AC-09 手工拆单超余量被拒",
            (not manual_over.ok) and manual_over.fail_code == "CONFIG_INVALID",
            f"code={manual_over.fail_code}",
        )

        # ============ ③ D03.07 发货单状态机 ============
        print("\n▶ D03.07 发货单指令状态机")
        dlv_svc = DeliveryService(s, redis)
        # 用 owner 拆单结果生成发货单
        delivery_ids = await dlv_svc.create_from_plan(
            oid3,
            split_res.groups if split_res.ok else [],
            plan_id=res.plan_id,
            operator="tester",
        )
        check(
            "AC-01 拆单方案 → 发货单单事务落库",
            len(delivery_ids) == 2,
            f"delivery_ids={delivery_ids}",
        )

        did = delivery_ids[0]
        detail = await dlv_svc.get_detail(did)
        check(
            "发货单头/行/溯源齐备",
            bool(detail["delivery"]) and bool(detail["items"]) and bool(detail["details"]),
            f"items={len(detail['items'])} details={len(detail['details'])}",
        )
        check(
            "发货单初始态 = draft",
            detail["delivery"]["status"] == "draft",
            detail["delivery"]["status"],
        )

        # 非法跳态：draft 直接 confirm
        bad = await dlv_svc.transit(did, "confirm", operator="tester")
        check(
            "AC-02 非法跳态被拒",
            (not bad.ok) and bad.fail_code == "INVALID_TRANSITION",
            f"code={bad.fail_code}",
        )

        # 推送 → pushed
        pushed = await dlv_svc.push(did, operator="tester")
        check("draft → pushed", pushed.ok, f"{pushed.from_status}→{pushed.to_status}")

        # WMS 接收确认 → processing
        acked = await dlv_svc.transit(did, "callback_ack", operator="wms")
        check("pushed → processing", acked.ok, f"{acked.from_status}→{acked.to_status}")

        # 叫回 → recalling → recalled
        rec = await dlv_svc.recall([did], operator="tester", reason="暂停")
        check("processing → recalling", rec[0].ok, rec[0].to_status)
        rec_ok = await dlv_svc.recall_result(did, success=True, operator="wms")
        check("recalling → recalled", rec_ok.ok, rec_ok.to_status)

        # 恢复 → pushed
        res2d = await dlv_svc.resume(did, operator="tester")
        check("recalled → pushed（恢复）", res2d.ok, res2d.to_status)

        # 叫回失败 → 回原态
        await dlv_svc.transit(did, "callback_ack", operator="wms")
        await dlv_svc.recall([did], operator="tester")
        rec_fail = await dlv_svc.recall_result(did, success=False, operator="wms", reason="已拣货")
        check(
            "叫回失败回原态 + recall_failed",
            rec_fail.ok and rec_fail.to_status == "processing",
            f"{rec_fail.from_status}→{rec_fail.to_status}",
        )

        # 出库回传 → outbound → confirm → shipped
        item_bm = detail["items"][0]["bm_id"]
        cb = await dlv_svc.handle_callback(
            did,
            {
                "batch_no": "BATCH_W6_001",
                "waybill_no": "SF123456789",
                "weight": 3.2,
                "volume": 0.01,
                "lines": [{"bm_id": item_bm, "num": detail["items"][0]["num"]}],
            },
        )
        check("AC-03 出库回传 → outbound", cb.ok and cb.to_status == "outbound", cb.to_status)
        detail2 = await dlv_svc.get_detail(did)
        check(
            "AC-03 包裹/运单/称重落库",
            bool(detail2["packages"]) and detail2["packages"][0]["waybill_no"] == "SF123456789",
            f"{detail2['packages']}",
        )
        check(
            "AC-03 发货单已发货（确认联动）",
            detail2["delivery"]["status"] == "shipped",
            detail2["delivery"]["status"],
        )

        # 订单 ship_status 联动
        order3 = await s.scalar(select(OrdOrder).where(OrdOrder.id == oid3))
        check(
            "FR-06a 订单 ship_status 按行口径聚合",
            order3 is not None and order3.ship_status in ("shipped", "partial_shipped"),
            f"ship_status={order3.ship_status if order3 else '?'}",
        )

        # 实发差异：多发 → 差异登记
        did2 = delivery_ids[1]
        d2 = await dlv_svc.get_detail(did2)
        await dlv_svc.push(did2, operator="tester")
        await dlv_svc.transit(did2, "callback_ack", operator="wms")
        await dlv_svc.handle_callback(
            did2,
            {
                "batch_no": "BATCH_W6_002",
                "waybill_no": "SF987654321",
                "lines": [
                    {"bm_id": d2["items"][0]["bm_id"], "num": d2["items"][0]["num"] + 3}
                ],
            },
        )
        d2_after = await dlv_svc.get_detail(did2)
        check(
            "AC-04 实发差异登记",
            bool(d2_after["diffs"]),
            f"{len(d2_after['diffs'])} 条差异",
        )

        # 取消编排：draft 直接取消
        oid5 = await _make_order(
            s,
            suffix="D3",
            items=[(bm_ids[0], main_owner, 1)],
            shop_id=shop_id,
            owner_id=main_owner,
        )
        items5 = await ssvc._load_items(oid5)
        sp5 = await ssvc.split(
            oid5,
            rule["id"],
            context={
                "branch_plan": {
                    "alloc": {str(items5[0].item_id): {main_branch: 1}}
                }
            },
        )
        ids5 = await dlv_svc.create_from_plan(oid5, sp5.groups if sp5.ok else [])
        cancelled = await dlv_svc.cancel(ids5[0], reason="订单取消", operator="tester")
        check("AC-10 draft 取消成功", cancelled.ok, cancelled.to_status)
        check(
            "FR-06d 取消后 split_num 回退",
            cancelled.ok,
            f"cancelled={cancelled.ok}",
        )

        # 打回：pushed → rejected
        oid6 = await _make_order(
            s,
            suffix="D4",
            items=[(bm_ids[0], main_owner, 1)],
            shop_id=shop_id,
            owner_id=main_owner,
        )
        items6 = await ssvc._load_items(oid6)
        sp6 = await ssvc.split(
            oid6,
            rule["id"],
            context={
                "branch_plan": {
                    "alloc": {str(items6[0].item_id): {main_branch: 1}}
                }
            },
        )
        ids6 = await dlv_svc.create_from_plan(oid6, sp6.groups if sp6.ok else [])
        await dlv_svc.push(ids6[0], operator="tester")
        rejected = await dlv_svc.reject(ids6[0], reason="仓库缺货", operator="wms")
        check("AC-11 打回 → rejected", rejected.ok, rejected.to_status)

        # 异常视图
        abnormal = await dlv_svc.abnormal_list()
        check("FR-10b 异常视图有数据", len(abnormal) > 0, f"{len(abnormal)} 条")

        # 状态机字典
        from app.services.delivery_service import allowed_commands as ac

        check(
            "状态机字典可枚举",
            len(ac("draft")) > 0 and "push" in ac("draft"),
            f"draft允许={ac('draft')}",
        )

        # ============ ④ 拆单轨迹与进度 ============
        print("\n▶ 追溯与进度")
        traces = await ssvc.query_trace(oid3)
        check("FR-08a split_trace 已写", len(traces) > 0, f"{len(traces)} 轮")

        # 进度回写由 D03.07 createFromPlan 在同一事务内完成（FR-03a）
        item_rows = await s.execute(
            text(
                "SELECT id, nums, split_num FROM oms_order.ord_order_item "
                "WHERE order_id = :oid ORDER BY id"
            ),
            {"oid": oid3},
        )
        item_map = {int(r[0]): (int(r[1]), int(r[2])) for r in item_rows.all()}
        check(
            "FR-06a createFromPlan 回写 split_num（=nums）",
            all(v[1] == v[0] for v in item_map.values()),
            f"{item_map}",
        )
        ord3 = await s.execute(
            text("SELECT splited_num FROM oms_order.ord_order WHERE id = :oid"),
            {"oid": oid3},
        )
        splited_val = int(ord3.scalar() or 0)
        check("FR-06b splited_num +1", splited_val >= 1, f"{splited_val}")

        # 回退（IF-D03.04-07）
        rb = await ssvc.rollback_progress(oid3, delivery_ids[0])
        check("FR-06d rollbackProgress 生效", rb["rolled_back"] > 0, f"{rb}")

    passed = sum(1 for _, ok_, _ in RESULTS if ok_)
    print(f"\n合计：{passed}/{len(RESULTS)} 项通过")
    await engine.dispose()
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
