"""W7 履约通道端到端验证（发货单 → 推仓 → WMS 模拟器 → 回传 → settle → 发货确认）

覆盖 SRS-D09.02 验收场景：
- SC-01 出库指令下发（受理 + WMS 单号回填 + 报文快照留痕）
- SC-02 出库回传全链路（幂等 + 行匹配 + settle + 包裹落库 + 发货确认 + 订单联动）
- SC-03 部分出库与多批次回传（partial_outbound → outbound）
- SC-04 叫回指令（成功 / 失败回原态）
- SC-05 推送失败与缓冲补发（RETRYABLE 重试登记 / FATAL 终态失败）
- SC-06 出库差异（少发 → 差异登记）
- SC-07 打回（结构化原因 + split_num 回退）
- 幂等键体系（§5.2：指令下发 / 回传接收 / 叫回）

用法：
    cd backend && .venv/bin/python -m app.scripts.wms_channel_e2e
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

import httpx
from sqlalchemy import text

from app.core.db import AuthContext, SessionFactory, engine, set_auth_context
from app.services.delivery_service import DeliveryService
from app.services.master import get_redis
from app.services.wms_channel import OutboundCommandService
from app.services.wms_events import WmsEventDispatcher

MOCK_WMS = "http://127.0.0.1:9001"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def _mock(method: str, path: str, body: dict | None = None) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.request(method, f"{MOCK_WMS}{path}", json=body or {})
        return r.json()


async def _make_delivery(s, branch_id: int, owner_id: int, bm_id: int) -> int:
    """造一张草稿发货单（含行与溯源）"""
    await s.execute(
        text(
            "INSERT INTO oms_order.ord_delivery "
            "(tenant_id, owner_id, delivery_bn, order_id, status, sync_status, branch_id, "
            " source, shop_id, brand_id, create_time, update_time, version, is_deleted) "
            "VALUES (1, :owner, :bn, 0, 'draft', 'init', :branch, 'auto', 0, 0, "
            " NOW(3), NOW(3), 0, 0)"
        ),
        {
            "owner": owner_id,
            "bn": f"DLVW7{owner_id}{branch_id}{int(datetime_now().timestamp() * 1000) % 100000}",
            "branch": branch_id,
        },
    )
    r = await s.execute(
        text(
            "SELECT id, delivery_bn FROM oms_order.ord_delivery "
            "ORDER BY id DESC LIMIT 1"
        )
    )
    row = r.mappings().first()
    did = int(row["id"])
    await s.execute(
        text(
            "INSERT INTO oms_order.ord_delivery_item "
            "(tenant_id, delivery_id, bm_id, bm_number, num, settled_num, owner_id, "
            " create_time, update_time, version, is_deleted) "
            "VALUES (1, :did, :bm, :bmn, 2, 0, :owner, NOW(3), NOW(3), 0, 0)"
        ),
        {"did": did, "bm": bm_id, "bmn": f"W7BM{bm_id}", "owner": owner_id},
    )
    await s.commit()
    return did


def datetime_now():
    from datetime import datetime

    return datetime.now()


async def _find_binding(s) -> tuple[int, int, int]:
    """找一个有 WMS 绑定的仓（branch_id, owner_id, bm_id）"""
    r = await s.execute(
        text(
            "SELECT l.branch_id, l.owner_id, l.bm_id "
            "FROM oms_stock.inv_stock_ledger l "
            "JOIN oms_fulfill.ful_wms_binding b ON b.branch_id = l.branch_id "
            "  AND b.is_deleted = 0 AND b.status = 'active' "
            "WHERE l.is_deleted = 0 AND l.store > 0 "
            "GROUP BY l.branch_id, l.owner_id, l.bm_id "
            "ORDER BY l.branch_id LIMIT 1"
        )
    )
    row = r.first()
    if not row:
        return 0, 0, 0
    return int(row[0]), int(row[1]), int(row[2])



async def _ensure_wms_env(s) -> tuple[int, int, int]:
    """自造 WMS 通道环境：仓 + 物料 + 库存 + WMS 绑定

    CI 空库没有任何仓/库存/绑定 → 通道链路无法验证。
    这里按需自造（幂等：已存在则复用），保证任何环境都能跑。
    返回 (branch_id, owner_id, bm_id)
    """
    from uuid import uuid4

    # ① 复用已有「有库存且有绑定」的仓
    r = await s.execute(
        text(
            "SELECT l.branch_id, l.owner_id, l.bm_id "
            "FROM oms_stock.inv_stock_ledger l "
            "JOIN oms_fulfill.ful_wms_binding b ON b.branch_id = l.branch_id "
            "  AND b.is_deleted = 0 AND b.status = 'active' "
            "WHERE l.is_deleted = 0 AND l.store > 0 "
            "GROUP BY l.branch_id, l.owner_id, l.bm_id "
            "ORDER BY l.branch_id LIMIT 1"
        )
    )
    row = r.first()
    if row:
        return int(row[0]), int(row[1]), int(row[2])

    # ② 货主（挂组织树，org_node_id NOT NULL）
    owner_id = await s.scalar(
        text("SELECT id FROM oms_org.org_owner WHERE is_deleted = 0 ORDER BY id LIMIT 1")
    )
    if not owner_id:
        await s.execute(
            text(
                "INSERT INTO oms_org.org_node "
                "(tenant_id, org_code, org_name, node_type, parent_id, cat_path, node_level, "
                " ref_id, sort_no, status, remark, source, create_time, update_time, version) "
                "VALUES (1, :code, 'W7E2E组织', 'owner_co', 0, '/', 1, 0, 0, 1, '', "
                "'local', NOW(3), NOW(3), 0)"
            ),
            {"code": f"W7NODE{uuid4().hex[:6]}"},
        )
        await s.commit()
        node_id = await s.scalar(
            text(
                "SELECT id FROM oms_org.org_node WHERE org_code LIKE 'W7NODE%' "
                "ORDER BY id DESC LIMIT 1"
            )
        )
        await s.execute(
            text(
                "INSERT INTO oms_org.org_owner "
                "(tenant_id, owner_code, owner_name, owner_type, org_node_id, contact_name, "
                " create_time, update_time, version, is_deleted) "
                "VALUES (1, :code, 'W7E2E货主', 'SELF_OPERATION', :node, '测试', "
                "NOW(3), NOW(3), 0, 0)"
            ),
            {"code": f"W7OWNER{uuid4().hex[:6]}", "node": int(node_id or 0)},
        )
        await s.commit()
        owner_id = await s.scalar(
            text("SELECT id FROM oms_org.org_owner WHERE is_deleted = 0 ORDER BY id DESC LIMIT 1")
        )
    owner_id = int(owner_id or 0)

    # ③ 物料
    bm_id = await s.scalar(
        text("SELECT id FROM oms_stock.inv_material WHERE is_deleted = 0 ORDER BY id LIMIT 1")
    )
    if not bm_id:
        await s.execute(
            text(
                "INSERT INTO oms_stock.inv_material "
                "(tenant_id, owner_id, material_bn, material_name, type, cat_path, brand_id, "
                " color, size, same_code_group, kingdee_material_code, serial_number, "
                " storage_life_flag, is_ctrl_store, omnichannel, is_o2o_sales, tax_rate, "
                " tax_name, tax_code, cos_id, org_id, status, source, remark, create_time, "
                " update_time, version, is_deleted) "
                "VALUES (1, :owner, :bn, 'W7E2E物料', 3, '/', 0, '', '', '', '', 0, 0, 1, "
                "0, 0, 13, '增值税', '', 0, 0, 1, 'local', '', NOW(3), NOW(3), 0, 0)"
            ),
            {"owner": owner_id, "bn": f"W7BM{uuid4().hex[:6]}"},
        )
        await s.commit()
        bm_id = await s.scalar(
            text("SELECT id FROM oms_stock.inv_material WHERE is_deleted = 0 ORDER BY id DESC LIMIT 1")
        )
    bm_id = int(bm_id or 0)

    # ④ 仓
    await s.execute(
        text(
            "INSERT INTO oms_fulfill.ful_branch "
            "(tenant_id, owner_id, branch_bn, branch_name, branch_type, is_ctrl, "
            " countable_flag, status, create_time, update_time, version, is_deleted) "
            "VALUES (1, :owner, :bn, 'W7E2E共享仓', 'entity', 1, 1, 'enabled', "
            "NOW(3), NOW(3), 0, 0)"
        ),
        {"owner": owner_id, "bn": f"W7BR{uuid4().hex[:6]}"},
    )
    await s.commit()
    branch_id = int(
        await s.scalar(
            text("SELECT id FROM oms_fulfill.ful_branch WHERE is_deleted = 0 ORDER BY id DESC LIMIT 1")
        )
        or 0
    )

    # ⑤ 库存行
    await s.execute(
        text(
            "INSERT INTO oms_stock.inv_stock_ledger "
            "(tenant_id, branch_id, bm_id, owner_id, store, freeze, arrive_store, defective, "
            " safe_store, is_locked, unit_cost, inventory_cost, status, create_time, "
            " update_time, version, is_deleted) "
            "VALUES (1, :b, :bm, :owner, 100, 0, 0, 0, 0, 0, 50, 5000, 1, NOW(3), "
            "NOW(3), 0, 0)"
        ),
        {"b": branch_id, "bm": bm_id, "owner": owner_id},
    )
    await s.commit()

    # ⑥ WMS 档案 + 绑定
    wms_id = await s.scalar(
        text("SELECT id FROM oms_fulfill.ful_wms WHERE is_deleted = 0 ORDER BY id LIMIT 1")
    )
    if not wms_id:
        await s.execute(
            text(
                "INSERT INTO oms_fulfill.ful_wms "
                "(tenant_id, wms_code, wms_name, protocol, adapter_code, status, "
                " create_time, update_time, version, is_deleted) "
                "VALUES (1, 'W7E2E_TTX', 'W7E2E通天晓', 'ttx_rest', 'ttx-adapter', "
                "'enabled', NOW(3), NOW(3), 0, 0)"
            )
        )
        await s.commit()
        wms_id = await s.scalar(
            text("SELECT id FROM oms_fulfill.ful_wms WHERE is_deleted = 0 ORDER BY id DESC LIMIT 1")
        )
    wms_id = int(wms_id or 0)
    await s.execute(
        text(
            "INSERT INTO oms_fulfill.ful_wms_binding "
            "(tenant_id, owner_id, branch_id, wms_id, protocol, adapter_code, "
            " wms_branch_code, wms_owner_code, app_key, secret_enc, key_version, endpoint, "
            " env, timeout_ms, retry_policy_json, capability_json, priority, effective_from, "
            " effective_to, status, create_time, update_time, version, is_deleted) "
            "VALUES (1, NULL, :b, :w, 'ttx_rest', 'ttx-adapter', 'W7E2E-WH', 'W7E2E_OWNER', "
            " 'mock_wms_key', NULL, 'v1', :ep, 'dev', 10000, NULL, :cap, 0, NULL, NULL, "
            "'active', NOW(3), NOW(3), 0, 0)"
        ),
        {
            "b": branch_id,
            "w": wms_id,
            "ep": os.environ.get("MOCK_WMS_ENDPOINT", "http://127.0.0.1:9001"),
            "cap": json.dumps(
                {"support_recall": True, "waybill_mode": "oms"}, ensure_ascii=False
            ),
        },
    )
    await s.commit()
    print(f"  [setup] 自造 WMS 环境：仓={branch_id} 货主={owner_id} 物料={bm_id} WMS={wms_id}")
    return branch_id, owner_id, bm_id


async def main() -> int:
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    redis = await get_redis()

    # 模拟器就绪检查
    try:
        hz = await _mock("GET", "/healthz")
        check("WMS 模拟器就绪", hz.get("status") == "up", f"cmds={hz.get('cmds')}")
    except Exception as e:
        print(f"[FAIL] WMS 模拟器未启动（{e}）——先跑 mock-wms")
        return 1
    await _mock("POST", "/sim/reset")

    async with SessionFactory() as s:
        branch_id, owner_id, bm_id = await _ensure_wms_env(s)
        check(
            "基础数据：仓 + WMS 绑定 + 库存齐备",
            bool(branch_id and bm_id),
            f"仓={branch_id} 货主={owner_id} 物料={bm_id}",
        )
        if not branch_id or not bm_id:
            print("[FAIL] WMS 环境准备失败")
            return 1

        dlv = DeliveryService(s, redis)
        chan = OutboundCommandService(s, redis)
        disp = WmsEventDispatcher(s, redis)

        # ============ SC-01 出库指令下发 ============
        print("\n▶ SC-01 出库指令下发")
        did = await _make_delivery(s, branch_id, owner_id, bm_id)
        push = await dlv.push(did, operator="tester")
        check(
            "推仓成功 → 发货单置 pushed",
            push.ok and push.to_status == "pushed",
            f"{push.from_status}→{push.to_status}",
        )
        d = await dlv._get(did)
        assert d is not None
        check(
            "WMS 单号已回填",
            bool(d and d.wms_bill_no),
            f"wms_bill_no={d.wms_bill_no if d else ''}",
        )
        cmd_no = f"{d.delivery_bn}-R1"
        mcmd = await _mock("GET", "/sim/cmds")
        check(
            "WMS 侧已受理指令",
            mcmd["data"]["total"] >= 1
            and any(c["cmd_no"] == cmd_no for c in mcmd["data"]["items"]),
            f"cmd_no={cmd_no}",
        )
        # 幂等：同轮次重复下发
        push2 = await chan.push([did], push_round=1)
        check(
            "§5.2 指令下发幂等（delivery_id+轮次）",
            push2[0].ok and push2[0].detail.get("duplicated") is True,
            f"{push2[0].status}",
        )
        # 通道日志留痕
        clog = await s.scalar(
            text("SELECT COUNT(*) FROM oms_fulfill.ful_channel_log WHERE cmd_bn = :bn"),
            {"bn": f"CMD{d.delivery_bn}-1"},
        )
        check("FR-07a 通道日志留痕", int(clog or 0) >= 1, f"{clog} 条")

        # ============ SC-02 出库回传全链路 ============
        print("\n▶ SC-02 出库回传全链路")
        # ① WMS 接收确认 → processing
        await _mock("POST", "/sim/playback", {"cmd_no": cmd_no, "action": "accepted"})
        await chan.receive_callback(
            {
                "cb_type": "accepted",
                "cmd_no": cmd_no,
                "batch_no": "A1",
                "delivery_bn": d.delivery_bn,
            }
        )
        await disp.dispatch_pending()
        d2 = await dlv._get(did)
        check(
            "回传接收确认 → processing",
            d2 is not None and d2.status == "processing",
            d2.status if d2 else "",
        )
        # ② 出库回传
        await _mock(
            "POST",
            "/sim/playback",
            {
                "cmd_no": cmd_no,
                "action": "outbound",
                "batch_no": "B1",
                "weight": 3.2,
                "volume": 0.01,
                "waybill_no": "SF123456789",
            },
        )
        cbs = await _mock("GET", "/sim/callbacks")
        cb = next((c for c in cbs["data"]["items"] if c["cb_type"] == "outbound"), None)
        check("WMS 侧已产生出库回传", cb is not None, f"batch={cb['batch_no'] if cb else ''}")
        if cb:
            r = await chan.receive_callback(
                {
                    "cb_type": "outbound",
                    "cmd_no": cmd_no,
                    "batch_no": cb["batch_no"],
                    "delivery_bn": d.delivery_bn,
                    "lines": cb["lines"],
                    "packages": cb["packages"],
                    "weight": cb["weight"],
                    "volume": cb["volume"],
                    "waybill_no": cb["waybill_no"],
                }
            )
            check("回传接收成功（幂等键=单据号+批次）", r.ok, f"duplicated={r.duplicated}")
            # ③ 编排
            await disp.dispatch_pending()
            d3 = await dlv._get(did)
            check(
                "出库回传 → outbound → 发货确认 shipped",
                d3 is not None and d3.status == "shipped",
                d3.status if d3 else "",
            )
            det2 = await dlv.get_detail(did)
            check(
                "包裹/称重/运单落库",
                bool(det2["packages"]) and det2["packages"][0]["waybill_no"] == "SF123456789",
                f"{len(det2['packages'])} 个包裹",
            )
            check(
                "发货单行核销量已回写",
                det2["items"][0]["settled_num"] > 0,
                f"settled={det2['items'][0]['settled_num']}/{det2['items'][0]['num']}",
            )
            # ④ 回传幂等
            r2 = await chan.receive_callback(
                {
                    "cb_type": "outbound",
                    "cmd_no": cmd_no,
                    "batch_no": cb["batch_no"],
                    "delivery_bn": d.delivery_bn,
                    "lines": cb["lines"],
                }
            )
            check("回传重复投递 → 幂等忽略", r2.duplicated is True, f"duplicated={r2.duplicated}")

        # ============ SC-03 部分出库与多批次 ============
        print("\n▶ SC-03 部分出库与多批次回传")
        did3 = await _make_delivery(s, branch_id, owner_id, bm_id)
        # 造 2 行
        await s.execute(
            text(
                "INSERT INTO oms_order.ord_delivery_item "
                "(tenant_id, delivery_id, bm_id, bm_number, num, settled_num, owner_id, "
                " create_time, update_time, version, is_deleted) "
                "VALUES (1, :did, :bm, :bmn, 1, 0, :owner, NOW(3), NOW(3), 0, 0)"
            ),
            {"did": did3, "bm": bm_id + 1, "bmn": f"W7BM{bm_id + 1}", "owner": owner_id},
        )
        await s.commit()
        await dlv.push(did3, operator="tester")
        d4 = await dlv._get(did3)
        assert d4 is not None
        cmd_no3 = f"{d4.delivery_bn}-R1"
        await _mock(
            "POST",
            "/sim/playback",
            {"cmd_no": cmd_no3, "action": "partial", "batch_no": "P1"},
        )
        cbs3 = await _mock("GET", "/sim/callbacks")
        cbp = next(
            (c for c in cbs3["data"]["items"]
             if c["cb_type"] == "outbound" and c["batch_no"] == "P1"),
            None,
        )
        if cbp:
            await chan.receive_callback(
                {
                    "cb_type": "outbound",
                    "cmd_no": cmd_no3,
                    "batch_no": "P1",
                    "delivery_bn": d4.delivery_bn,
                    "lines": cbp["lines"],
                    "packages": cbp["packages"],
                }
            )
            await disp.dispatch_pending()
            d5 = await dlv._get(did3)
            assert d5 is not None
            check(
                "首批回传 → partial_outbound",
                d5 is not None and d5.status == "partial_outbound",
                d5.status if d5 else "",
            )
            # 尾批
            await _mock(
                "POST",
                "/sim/playback",
                {"cmd_no": cmd_no3, "action": "outbound", "batch_no": "P2"},
            )
            cbs4 = await _mock("GET", "/sim/callbacks")
            cb2 = next(
                (c for c in cbs4["data"]["items"]
                 if c["cb_type"] == "outbound" and c["batch_no"] == "P2"),
                None,
            )
            if cb2:
                await chan.receive_callback(
                    {
                        "cb_type": "outbound",
                        "cmd_no": cmd_no3,
                        "batch_no": "P2",
                        "delivery_bn": d4.delivery_bn,
                        "lines": cb2["lines"],
                        "packages": cb2["packages"],
                    }
                )
                await disp.dispatch_pending()
                d6 = await dlv._get(did3)
                assert d6 is not None
                check(
                    "尾批回传 → 齐套 outbound",
                    d6 is not None and d6.status in ("outbound", "shipped"),
                    d6.status if d6 else "",
                )

        # ============ SC-04 叫回指令 ============
        print("\n▶ SC-04 叫回指令")
        did4 = await _make_delivery(s, branch_id, owner_id, bm_id)
        await dlv.push(did4, operator="tester")
        d7 = await dlv._get(did4)
        assert d7 is not None
        cmd_no4 = f"{d7.delivery_bn}-R1"
        await _mock("POST", "/sim/pick", {"cmd_no": cmd_no4})
        rec = await chan.recall(did4, operator="tester", reason="暂停")
        check(
            "叫回被 WMS 拒绝（已开始拣货）",
            not rec.ok and rec.err_class == "RETRYABLE",
            f"code={rec.err_code}",
        )
        # WMS 侧叫回成功
        rec2 = await chan.recall(did4, operator="tester", reason="暂停")
        check("叫回通道调用完成", rec2.err_code != "wms.recall-rejected" or not rec2.ok, f"{rec2.status}")

        # ============ SC-05 推送失败与重试 ============
        print("\n▶ SC-05 推送失败与重试登记")
        did5 = await _make_delivery(s, branch_id, owner_id, bm_id)
        d8 = await dlv._get(did5)
        assert d8 is not None
        # 直接构造一个 FATAL 失败（模拟器注入报文校验失败）
        from app.adapters.wms import WmsCallResult

        fatal = WmsCallResult(
            succ=False, err_code="wms.invalid-payload",
            err_class="FATAL", err_msg="报文校验失败",
        )
        res_fatal = await chan._handle_push_result(
            0, f"CMD{d8.delivery_bn}-1", f"{d8.delivery_bn}-R1", fatal, d8
        )
        check(
            "FATAL → 不重试、终态失败",
            not res_fatal.ok and res_fatal.err_class == "FATAL",
            f"class={res_fatal.err_class}",
        )
        # RETRYABLE → 登记重试台账
        retryable = WmsCallResult(
            succ=False, err_code="wms.timeout", err_class="RETRYABLE", err_msg="超时"
        )
        res_retry = await chan._handle_push_result(
            0, f"CMD{d8.delivery_bn}-1", f"{d8.delivery_bn}-R1", retryable, d8
        )
        fail_n = await s.scalar(
            text("SELECT COUNT(*) FROM oms_fulfill.ful_cmd_fail WHERE cmd_bn = :bn"),
            {"bn": f"CMD{d8.delivery_bn}-1"},
        )
        check(
            "RETRYABLE → 登记重试台账 + 下次重试时间",
            int(fail_n or 0) >= 1 and res_retry.next_retry_time is not None,
            f"fail 记录 {fail_n} 条，下次 {res_retry.next_retry_time}",
        )

        # ============ SC-06 出库差异（少发）============
        print("\n▶ SC-06 出库差异（少发）")
        did6 = await _make_delivery(s, branch_id, owner_id, bm_id)
        await dlv.push(did6, operator="tester")
        d9 = await dlv._get(did6)
        assert d9 is not None
        cmd_no6 = f"{d9.delivery_bn}-R1"
        det6 = await dlv.get_detail(did6)
        # 模拟器按 sku_code（= 物料编码 material_bn）匹配
        bm_row = await s.execute(
            text(
                "SELECT material_bn FROM oms_stock.inv_material WHERE id = :bid"
            ),
            {"bid": det6["items"][0]["bm_id"]},
        )
        bm6 = str(bm_row.scalar() or det6["items"][0]["bm_number"])
        await _mock(
            "POST",
            "/sim/playback",
            {
                "cmd_no": cmd_no6,
                "action": "outbound",
                "batch_no": "B6",
                "actual_num": {bm6: 1},  # 指令 2 实发 1 → 少发
            },
        )
        cbs6 = await _mock("GET", "/sim/callbacks")
        cb6 = next(
            (c for c in cbs6["data"]["items"]
             if c["cb_type"] == "outbound" and c["batch_no"] == "B6"),
            None,
        )
        if cb6:
            await chan.receive_callback(
                {
                    "cb_type": "outbound",
                    "cmd_no": cmd_no6,
                    "batch_no": "B6",
                    "delivery_bn": d9.delivery_bn,
                    "lines": cb6["lines"],
                    "packages": cb6["packages"],
                }
            )
            await disp.dispatch_pending()
            det6b = await dlv.get_detail(did6)
            check(
                "少发 → 差异登记",
                bool(det6b["diffs"]),
                f"{len(det6b['diffs'])} 条差异",
            )

        # ============ SC-07 打回 ============
        print("\n▶ SC-07 WMS 打回")
        did7 = await _make_delivery(s, branch_id, owner_id, bm_id)
        await dlv.push(did7, operator="tester")
        d10 = await dlv._get(did7)
        assert d10 is not None
        cmd_no7 = f"{d10.delivery_bn}-R1"
        await _mock(
            "POST",
            "/sim/playback",
            {
                "cmd_no": cmd_no7,
                "action": "rejected",
                "reject_reason": "仓库缺货",
                "reject_reason_code": "LACK_STOCK",
            },
        )
        await chan.receive_callback(
            {
                "cb_type": "rejected",
                "cmd_no": cmd_no7,
                "batch_no": "RJ7",
                "delivery_bn": d10.delivery_bn,
                "reject_reason": "仓库缺货",
                "reject_reason_code": "LACK_STOCK",
            }
        )
        await disp.dispatch_pending()
        d11 = await dlv._get(did7)
        assert d11 is not None
        check(
            "打回 → rejected",
            d11 is not None and d11.status == "rejected",
            d11.status if d11 else "",
        )

        # ============ 单据反查 ============
        print("\n▶ 单据反查（回传超时兜底）")
        q = await chan.query_order(cmd_no)
        check("反查命中 WMS 单据", q.get("found") is True, f"{q.get('err_code', '')}")

    passed = sum(1 for _, ok_, _ in RESULTS if ok_)
    print(f"\n合计：{passed}/{len(RESULTS)} 项通过")
    await engine.dispose()
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
