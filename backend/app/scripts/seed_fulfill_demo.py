"""W6 履约演示数据装配（发货单工作台界面演示用）

造一批**有状态差异**的发货单：草稿 / 已推送 / 出库中 / 部分出库 / 已发货 / 已打回 /
已取消 —— 让工作台界面能展示状态机的各种形态。

复用 app.scripts.fulfill_e2e 的造数逻辑，走真实服务层（分仓→拆单→发货单→状态流转）。

用法：
    cd backend && .venv/bin/python -m app.scripts.seed_fulfill_demo
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from app.core.db import AuthContext, SessionFactory, engine, set_auth_context
from app.services.delivery_service import DeliveryService
from app.services.dispatch_service import DispatchService
from app.services.master import get_redis
from app.services.split_service import SplitService

DEMO_BN_PREFIX = "W6DEMO"


async def _clean(s) -> None:
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
    await s.execute(text("DELETE FROM oms_order.ord_routing_decision_log"))
    await s.execute(
        text(
            "DELETE FROM oms_order.ord_order_item WHERE order_id IN "
            "(SELECT id FROM oms_order.ord_order WHERE order_bn LIKE 'W6DEMO%')"
        )
    )
    await s.execute(
        text(
            "DELETE FROM oms_order.ord_receiver WHERE order_id IN "
            "(SELECT id FROM oms_order.ord_order WHERE order_bn LIKE 'W6DEMO%')"
        )
    )
    await s.execute(text("DELETE FROM oms_order.ord_order WHERE order_bn LIKE 'W6DEMO%'"))
    await s.commit()


async def _make_order(
    s, suffix: str, items: list[tuple[int, int, int]], shop_id: int, owner_id: int
) -> int:
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
                "'processing', 'passed', 'fulfilling', 'paid', 'unshipped', "
                "200, 0, 0, 200, 0, 0, 0, NOW(3), NOW(3), NOW(3), NOW(3), 0, 0)"
            ),
            {
                "obn": f"{DEMO_BN_PREFIX}{suffix}",
                "pon": f"W6DEMOP_{suffix}",
                "sid": shop_id,
                "owner": owner_id,
            },
        )
        r = await conn.execute(
            text("SELECT id FROM oms_order.ord_order WHERE order_bn = :obn"),
            {"obn": f"{DEMO_BN_PREFIX}{suffix}"},
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
                    "VALUES (1, :oid, :order_id, 0, :sku, :bm, :bmn, '演示物料', "
                    ":nums, 0, 0, 100, :amt, :amt, 'parsed', NOW(3), NOW(3), 0, 0)"
                ),
                {
                    "oid": line_owner,
                    "order_id": order_id,
                    "sku": f"SKU_W6D_{suffix}_{i}",
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
    await s.commit()
    return order_id


async def main() -> int:
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    redis = await get_redis()

    async with SessionFactory() as s:
        await _clean(s)

        # 取基础数据：有库存的仓 + 对应货主 + 物料
        stock_rows = list(
            await s.execute(
                text(
                    "SELECT branch_id, bm_id, owner_id FROM oms_stock.inv_stock_ledger "
                    "WHERE is_deleted = 0 AND store > 0 ORDER BY branch_id, bm_id"
                )
            )
        )
        stock_rows = list(stock_rows)
        owner_branch: dict[int, int] = {}
        owner_bms: dict[int, list[int]] = {}
        for r in stock_rows:
            bid, bid_owner = int(r[0]), int(r[2])
            if bid_owner in owner_branch:
                continue
            n = await s.scalar(
                text(
                    "SELECT COUNT(*) FROM oms_org.org_node_relation rr "
                    "JOIN oms_fulfill.ful_branch b ON b.org_node_id = rr.node_id "
                    "WHERE b.id = :bid AND rr.rel_type = 'branch_owner' "
                    "AND rr.status = 1 AND rr.rel_id = :oid"
                ),
                {"bid": bid, "oid": bid_owner},
            )
            if int(n or 0) > 0:
                owner_branch[bid_owner] = bid
                owner_bms[bid_owner] = [
                    int(x[1]) for x in stock_rows if int(x[0]) == bid
                ]
        if not owner_branch:
            print("[FAIL] 无「可服务货主且有库存」的仓，先跑 seed_demo")
            return 1
        main_owner = next(iter(owner_branch))
        main_branch = owner_branch[main_owner]
        main_bms = owner_bms[main_owner]

        shop_id = int(
            await s.scalar(
                text(
                    "SELECT shop_id FROM oms_gateway.gw_shop_config "
                    "WHERE is_deleted = 0 ORDER BY id LIMIT 1"
                )
            )
            or 0
        )
        # 绑定店铺发货仓到有库存的仓
        await s.execute(
            text(
                "UPDATE oms_gateway.gw_shop_config SET branch_bind_json = :bj "
                "WHERE shop_id = :sid AND is_deleted = 0"
            ),
            {"bj": f'[{{"branch_id": {main_branch}, "priority": 1}}]', "sid": shop_id},
        )
        await s.commit()
        print(f"[demo] 店铺 {shop_id} 绑定仓 {main_branch}（货主 {main_owner}）")

        dsvc = DispatchService(s, redis)
        ssvc = SplitService(s, redis)
        dlv = DeliveryService(s, redis)

        # 取 owner 策略规则
        rule = await s.scalar(
            text(
                "SELECT id FROM oms_order.ord_split_rule "
                "WHERE split_type = 'owner' AND status = 'enabled' AND is_deleted = 0 "
                "ORDER BY id LIMIT 1"
            )
        )
        if not rule:
            print("[FAIL] 无 owner 拆单规则，先跑 seed_fulfill")
            return 1
        rule_id = int(rule)

        # 造 6 张单，覆盖不同状态
        specs = [
            ("01", "draft", 1),
            ("02", "pushed", 1),
            ("03", "processing", 1),
            ("04", "partial", 1),
            ("05", "shipped", 1),
            ("06", "rejected", 1),
            ("07", "cancelled", 1),
        ]
        made = 0
        for suffix, kind, _ in specs:
            oid = await _make_order(
                s,
                suffix,
                [(main_bms[0], main_owner, 2), (main_bms[1 % len(main_bms)], main_owner, 1)],
                shop_id,
                main_owner,
            )
            # 分仓
            await dsvc.dispatch(oid)
            # 拆单
            items = await ssvc._load_items(oid)
            if not items:
                continue
            sp = await ssvc.split(
                oid,
                rule_id,
                context={
                    "branch_plan": {
                        "alloc": {
                            str(it.item_id): {main_branch: it.nums} for it in items
                        }
                    }
                },
            )
            if not sp.ok:
                print(f"[demo] {suffix} 拆单失败：{sp.fail_code}")
                continue
            # 生成发货单
            ids = await dlv.create_from_plan(oid, sp.groups, operator="demo")
            if not ids:
                continue
            did = ids[0]
            det = await dlv.get_detail(did)

            if kind == "pushed":
                await dlv.push(did, operator="demo")
            elif kind == "processing":
                await dlv.push(did, operator="demo")
                await dlv.transit(did, "callback_ack", operator="wms")
            elif kind == "partial":
                await dlv.push(did, operator="demo")
                await dlv.transit(did, "callback_ack", operator="wms")
                # 只回传第一行 → 部分出库
                await dlv.handle_callback(
                    did,
                    {
                        "batch_no": f"WP{suffix}",
                        "waybill_no": f"SF{suffix}888",
                        "weight": 2.4,
                        "lines": [{"bm_id": det["items"][0]["bm_id"], "num": det["items"][0]["num"]}],
                    },
                )
            elif kind == "shipped":
                await dlv.push(did, operator="demo")
                await dlv.transit(did, "callback_ack", operator="wms")
                await dlv.handle_callback(
                    did,
                    {
                        "batch_no": f"WP{suffix}",
                        "waybill_no": f"SF{suffix}666",
                        "weight": 3.1,
                        "lines": [
                            {"bm_id": i["bm_id"], "num": i["num"]} for i in det["items"]
                        ],
                    },
                )
            elif kind == "rejected":
                await dlv.push(did, operator="demo")
                await dlv.reject(did, reason="仓库缺货，无法拣货", operator="wms")
            elif kind == "cancelled":
                await dlv.cancel(did, reason="买家申请退款，订单取消", operator="demo")
            made += 1

        print(f"[demo] 装配 {made} 张发货单（覆盖 7 种状态形态）")

        # 汇总
        rows = await s.execute(
            text(
                "SELECT status, COUNT(*) FROM oms_order.ord_delivery "
                "WHERE is_deleted = 0 GROUP BY status ORDER BY status"
            )
        )
        print("[demo] 状态分布：")
        for r in rows.all():
            print(f"        {r[0]} × {r[1]}")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
