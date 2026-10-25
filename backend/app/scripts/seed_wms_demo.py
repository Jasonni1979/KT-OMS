"""W7 履约通道演示数据装配（发货单工作台「WMS 通道轨迹」下钻演示用）

真实走一遍通道链路：草稿 → 推仓（WMS 模拟器接收）→ 接收确认 → 出库回传
（部分/全量）→ 发货确认 → 平台回传。产生带**通道留痕**（指令/回传/通道日志/
失败台账）的发货单，用于界面演示「一张发货单在 WMS 侧的完整生命线」。

同时造一张**推仓失败**的发货单（模拟器注入超时错误码），演示失败台账与
分级重试。

用法：
    cd backend && .venv/bin/python -m app.scripts.seed_wms_demo

前置：mock-wms（9001）已启动。
"""
from __future__ import annotations

import asyncio
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

MOCK_WMS = os.environ.get("MOCK_WMS_ENDPOINT", "http://127.0.0.1:9001")
DEMO_PREFIX = "DLVW7DEMO"


def _now_ms() -> int:
    from datetime import datetime

    return int(datetime.now().timestamp() * 1000)


async def _mock(method: str, path: str, body: dict[str, Any] | None = None) -> dict:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.request(method, f"{MOCK_WMS}{path}", json=body or {})
        return r.json()


async def _clean(s) -> None:
    """清理上一轮演示数据（含通道侧四表）

    删除顺序有依赖：通道表按 delivery_bn / cmd_bn 前缀删（不依赖发货单存在），
    发货单子表按 delivery_id 删 → 先删子表再删头。
    """
    # ① 通道侧（先删，避免发货单被删后子查询落空导致残留）
    await s.execute(
        text(
            "DELETE FROM oms_fulfill.ful_outbound_callback WHERE delivery_id IN "
            "(SELECT id FROM oms_order.ord_delivery WHERE delivery_bn LIKE 'DLVW7DEMO%')"
        )
    )
    await s.execute(
        text(
            "DELETE FROM oms_fulfill.ful_outbound_cmd WHERE delivery_bn LIKE 'DLVW7DEMO%'"
        )
    )
    await s.execute(
        text(
            "DELETE FROM oms_fulfill.ful_channel_log WHERE cmd_bn LIKE 'DLVW7DEMO%' "
            "   OR cmd_bn LIKE 'CMDDLVW7DEMO%'"
        )
    )
    await s.execute(
        text(
            "DELETE FROM oms_fulfill.ful_cmd_fail WHERE cmd_bn LIKE 'DLVW7DEMO%' "
            "   OR cmd_bn LIKE 'CMDDLVW7DEMO%'"
        )
    )
    # ② 发货单（子表 → 头）
    await s.execute(
        text(
            "DELETE FROM oms_order.ord_delivery_item_detail WHERE delivery_id IN "
            "(SELECT id FROM oms_order.ord_delivery WHERE delivery_bn LIKE 'DLVW7DEMO%')"
        )
    )
    await s.execute(
        text(
            "DELETE FROM oms_order.ord_delivery_item WHERE delivery_id IN "
            "(SELECT id FROM oms_order.ord_delivery WHERE delivery_bn LIKE 'DLVW7DEMO%')"
        )
    )
    await s.execute(
        text(
            "DELETE FROM oms_order.ord_delivery_package WHERE delivery_id IN "
            "(SELECT id FROM oms_order.ord_delivery WHERE delivery_bn LIKE 'DLVW7DEMO%')"
        )
    )
    await s.execute(
        text(
            "DELETE FROM oms_order.ord_delivery_diff WHERE delivery_id IN "
            "(SELECT id FROM oms_order.ord_delivery WHERE delivery_bn LIKE 'DLVW7DEMO%')"
        )
    )
    await s.execute(
        text(
            "DELETE FROM oms_order.ord_delivery_log WHERE delivery_id IN "
            "(SELECT id FROM oms_order.ord_delivery WHERE delivery_bn LIKE 'DLVW7DEMO%')"
        )
    )
    await s.execute(
        text(
            "DELETE FROM oms_order.ord_delivery WHERE delivery_bn LIKE 'DLVW7DEMO%'"
        )
    )
    await s.commit()


async def _ensure_env(s) -> tuple[int, int, int]:
    """确保有「仓 + 物料 + 库存 + WMS 绑定」的环境"""
    from app.scripts.wms_channel_e2e import _ensure_wms_env

    return await _ensure_wms_env(s)


async def _make_delivery(
    s,
    branch_id: int,
    owner_id: int,
    bm_id: int,
    bn: str,
    line_count: int = 1,
    num_per_line: int = 2,
) -> int:
    """造一张草稿发货单（含 N 行）

    line_count=2 用于 partial 场景：WMS 只回传首行 → 形成少发差异登记。
    """
    await s.execute(
        text(
            "INSERT INTO oms_order.ord_delivery "
            "(tenant_id, owner_id, delivery_bn, order_id, status, sync_status, branch_id, "
            " source, shop_id, brand_id, create_time, update_time, version, is_deleted) "
            "VALUES (1, :owner, :bn, 0, 'draft', 'init', :branch, 'auto', 0, 0, "
            " NOW(3), NOW(3), 0, 0)"
        ),
        {"owner": owner_id, "bn": bn, "branch": branch_id},
    )
    await s.commit()
    row = (
        await s.execute(
            text(
                "SELECT id FROM oms_order.ord_delivery WHERE delivery_bn = :bn ORDER BY id DESC"
            ),
            {"bn": bn},
        )
    ).mappings().first()
    did = int(row["id"])
    for i in range(line_count):
        await s.execute(
            text(
                "INSERT INTO oms_order.ord_delivery_item "
                "(tenant_id, delivery_id, bm_id, bm_number, num, settled_num, owner_id, "
                " create_time, update_time, version, is_deleted) "
                "VALUES (1, :did, :bm, :bmn, :num, 0, :owner, NOW(3), NOW(3), 0, 0)"
            ),
            {
                "did": did,
                "bm": bm_id,
                "bmn": f"W7BM{bm_id}-{i + 1}",
                "owner": owner_id,
                "num": num_per_line,
            },
        )
    await s.commit()
    return did


async def main() -> int:
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    redis = await get_redis()

    # ① 模拟器就绪检查
    try:
        hz = await _mock("GET", "/healthz")
    except Exception as e:
        print(f"[FAIL] mock-wms 未启动（{MOCK_WMS}）：{e}")
        return 1
    print(f"[setup] mock-wms 就绪：cmds={hz.get('cmds')} callbacks={hz.get('callbacks')}")

    async with SessionFactory() as s:
        branch_id, owner_id, bm_id = await _ensure_env(s)
        print(f"[setup] 仓={branch_id} 货主={owner_id} 物料={bm_id}")

        await _clean(s)

        # ② 造 4 张发货单：全量发货 / 部分发货 / 推仓失败 / 待推送
        # 单号带轮次后缀：回传幂等键 = 发货单号 + 批次，重复单号会被幂等挡掉
        tag = str(_now_ms())[-6:]
        bns = {
            "full": f"{DEMO_PREFIX}{tag}FULL",
            "partial": f"{DEMO_PREFIX}{tag}PART",
            "fail": f"{DEMO_PREFIX}{tag}FAIL",
            "draft": f"{DEMO_PREFIX}{tag}DRAFT",
        }
        ids: dict[str, int] = {}
        for key, bn in bns.items():
            # 各单 1 行：partial 场景靠「实发 1 < 指令 2」形成量差差异
            lc = 1
            ids[key] = await _make_delivery(
                s, branch_id, owner_id, bm_id, bn, line_count=lc
            )
        print(f"[setup] 造发货单 {ids}")

        dlv = DeliveryService(s, redis)
        chan = OutboundCommandService(s, redis)
        disp = WmsEventDispatcher(s, redis)

        # ③ 推仓（全量 + 部分 + 失败三张）
        #   fail 单：先在 WMS 侧预置「系统繁忙」错误（RETRYABLE）→ 演示失败台账与重试
        fail_cmd_no = f"{bns['fail']}-R1"
        await _mock(
            "POST",
            "/sim/inject",
            {"cmd_no": fail_cmd_no, "error": "SYSTEM_BUSY", "times": 1},
        )
        for key in ("full", "partial", "fail"):
            did = ids[key]
            res = await chan.push([did], push_round=1)
            r0 = res[0] if res else None
            if r0 is None:
                print(f"[FAIL] 推仓无结果：{key}")
                continue
            print(
                f"[push] {bns[key]:16s} ok={r0.ok} status={r0.status} "
                f"err={r0.err_code} bill={r0.wms_bill_no}"
            )

        # ④ 事件编排（消费 outbox：pushed → processing）
        dr = await disp.dispatch_pending(limit=50)
        print(f"[event] 编排 {len(dr)} 条事件")

        # ⑤ WMS 侧回放：接收确认（accepted）+ 出库回传
        #   full    → 全量出库
        #   partial → 只出 1 件（形成差异登记）
        #   流程：模拟器 /sim/playback 生成回传 → 取回 → 喂进 OMS 通道
        for key, action in (("full", "outbound"), ("partial", "partial")):
            did = ids[key]
            d = await dlv._get(did)
            if d is None:
                continue
            #: OMS 下发给 WMS 的指令单号（{发货单号}-R{轮次}）
            cmd_no = f"{d.delivery_bn}-R1"
            # 接收确认
            await _mock(
                "POST",
                "/sim/playback",
                {"cmd_no": cmd_no, "action": "accepted", "batch_no": f"ACC{sfx(d.delivery_bn)}"},
            )
            await chan.receive_callback(
                {
                    "cb_type": "accepted",
                    "cmd_no": cmd_no,
                    "batch_no": f"ACC{sfx(d.delivery_bn)}",
                    "delivery_bn": d.delivery_bn,
                }
            )
            # 出库回传
            #   full    → 全量实发（等于指令量）
            #   partial → 实发 1 件（指令 2 件）→ 少发差异登记（责任方 wms）
            pb: dict[str, Any] = {
                "cmd_no": cmd_no,
                "action": action,
                "batch_no": f"OUT{sfx(d.delivery_bn)}",
                "weight": 1.25,
                "volume": 0.02,
                "waybill_no": f"SF{sfx(d.delivery_bn)}",
            }
            if action == "partial":
                mat_bn = await s.scalar(
                    text("SELECT material_bn FROM oms_stock.inv_material WHERE id = :b"),
                    {"b": bm_id},
                )
                pb["actual_num"] = {str(mat_bn or ""): 1}
            await _mock("POST", "/sim/playback", pb)
            cbs = await _mock("GET", "/sim/callbacks")
            cb = next(
                (
                    c
                    for c in (cbs.get("data") or {}).get("items", [])
                    if c.get("cb_type") == "outbound" and c.get("delivery_bn") == d.delivery_bn
                ),
                None,
            )
            if cb is None:
                print(f"[FAIL] {bns[key]} 未取到出库回传")
                continue
            await chan.receive_callback(
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
            print(f"[wms] {bns[key]:16s} 已回放接收确认 + 出库回传（{action}）")

        # ⑥ 事件编排（消费 outbox：callback → settle → 状态流转）
        dr = await disp.dispatch_pending(limit=100)
        print(f"[event] 编排 {len(dr)} 条事件")

        # ⑦ 发货确认（outbound → shipped）+ 平台回传事件
        for key in ("full", "partial"):
            did = ids[key]
            d = await dlv._get(did)
            if d is None:
                continue
            if d.status in ("outbound", "partial_outbound"):
                cf = await dlv.confirm(did, operator="wms")
                print(f"[confirm] {bns[key]:16s} ok={cf.ok} → {cf.to_status}")

        dr = await disp.dispatch_pending(limit=100)
        print(f"[event] 编排 {len(dr)} 条事件（含平台回传）")

        # ⑧ 汇总
        print("\n=== 演示数据状态 ===")
        rows = await s.execute(
            text(
                "SELECT delivery_bn, status, sync_status, logi_no FROM "
                "oms_order.ord_delivery WHERE delivery_bn LIKE 'DLVW7DEMO%' ORDER BY id"
            )
        )
        for r in rows.all():
            print(f"  {r[0]:18s} status={r[1]:16s} sync={r[2]:8s} 运单={r[3] or '-'}")
        cnt = await s.scalar(
            text(
                "SELECT COUNT(*) FROM oms_fulfill.ful_outbound_cmd "
                "WHERE delivery_bn LIKE 'DLVW7DEMO%'"
            )
        )
        print(f"  通道指令记录：{cnt} 条")
        cnt2 = await s.scalar(
            text(
                "SELECT COUNT(*) FROM oms_fulfill.ful_outbound_callback "
                "WHERE delivery_id IN (SELECT id FROM oms_order.ord_delivery "
                "WHERE delivery_bn LIKE 'DLVW7DEMO%')"
            )
        )
        print(f"  回传登记记录：{cnt2} 条")
        cnt3 = await s.scalar(
            text(
                "SELECT COUNT(*) FROM oms_fulfill.ful_cmd_fail "
                "WHERE cmd_bn LIKE 'CMDDLVW7DEMO%'"
            )
        )
        print(f"  失败台账记录：{cnt3} 条")

    await engine.dispose()
    print("\n[OK] W7 演示数据装配完成")
    return 0


def sfx(bn: str) -> str:
    """单号后缀（生成批次号/运单号用）"""
    return str(bn)[-6:]


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
