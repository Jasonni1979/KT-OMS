"""W7 履约通道种子数据（WMS 档案 + 仓×WMS 绑定）

幂等：按 wms_code / (branch_id, wms_id) 判重。

用法：
    cd backend && .venv/bin/python -m app.scripts.seed_wms
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any

from sqlalchemy import text

from app.core.db import AuthContext, SessionFactory, engine, set_auth_context
from app.modules.m1_master.service.master import get_redis

#: WMS 模拟器地址
MOCK_WMS_ENDPOINT = os.getenv("MOCK_WMS_ENDPOINT", "http://127.0.0.1:9001")

#: WMS 档案（协议 + 适配器）
WMS_LIST: list[dict[str, Any]] = [
    {
        "wms_code": "MOCK_TTX",
        "wms_name": "模拟通天晓WMS",
        "protocol": "ttx_rest",
        "adapter_code": "ttx-adapter",
    },
    {
        "wms_code": "MOCK_QIMEN",
        "wms_name": "模拟奇门WMS",
        "protocol": "qimen",
        "adapter_code": "qimen-adapter",
    },
]

#: 仓 × WMS 绑定（endpoint 指向 mock-wms）
BINDING_LIST: list[dict[str, Any]] = [
    {
        "wms_code": "MOCK_TTX",
        "wms_branch_code": "MOCK-WH-01",
        "wms_owner_code": "MOCK_OWNER",
        "capability": {
            "support_recall": True,
            "support_batch": False,
            "support_sn": False,
            "waybill_mode": "oms",
        },
        "priority": 0,
    },
]


async def main() -> int:
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    redis = await get_redis()
    del redis

    async with SessionFactory() as s:
        # ① WMS 档案
        wms_ids: dict[str, int] = {}
        for spec in WMS_LIST:
            row = await s.scalar(
                text(
                    "SELECT id FROM oms_fulfill.ful_wms "
                    "WHERE wms_code = :c AND is_deleted = 0"
                ),
                {"c": spec["wms_code"]},
            )
            if row:
                wms_ids[spec["wms_code"]] = int(row)
                await s.execute(
                    text(
                        "UPDATE oms_fulfill.ful_wms SET wms_name = :n, protocol = :p, "
                        "adapter_code = :a, status = 'enabled' WHERE id = :id"
                    ),
                    {
                        "n": spec["wms_name"],
                        "p": spec["protocol"],
                        "a": spec["adapter_code"],
                        "id": int(row),
                    },
                )
                print(f"[seed] WMS 已存在（更新）：{spec['wms_name']}")
            else:
                await s.execute(
                    text(
                        "INSERT INTO oms_fulfill.ful_wms "
                        "(tenant_id, wms_code, wms_name, protocol, adapter_code, status, "
                        " create_time, update_time, version, is_deleted) "
                        "VALUES (1, :c, :n, :p, :a, 'enabled', NOW(3), NOW(3), 0, 0)"
                    ),
                    {
                        "c": spec["wms_code"],
                        "n": spec["wms_name"],
                        "p": spec["protocol"],
                        "a": spec["adapter_code"],
                    },
                )
                r = await s.scalar(
                    text(
                        "SELECT id FROM oms_fulfill.ful_wms "
                        "WHERE wms_code = :c AND is_deleted = 0"
                    ),
                    {"c": spec["wms_code"]},
                )
                wms_ids[spec["wms_code"]] = int(r or 0)
                print(f"[seed] 新建 WMS：{spec['wms_name']}（id={int(r or 0)}）")
        await s.commit()

        # ② 仓 × WMS 绑定（给所有有库存的仓各建一条）
        # 仓来源：有库存的仓优先；无则取全部仓（保证 CI 空库也能建绑定）
        branches = await s.execute(
            text(
                "SELECT DISTINCT branch_id FROM oms_stock.inv_stock_ledger "
                "WHERE is_deleted = 0 AND store > 0 ORDER BY branch_id LIMIT 20"
            )
        )
        branch_ids = [int(r[0]) for r in branches.all()]
        if not branch_ids:
            all_branches = await s.execute(
                text(
                    "SELECT id FROM oms_fulfill.ful_branch "
                    "WHERE is_deleted = 0 AND status = 'enabled' ORDER BY id LIMIT 20"
                )
            )
            branch_ids = [int(r[0]) for r in all_branches.all()]
        if not branch_ids:
            # CI 空库无仓 → 自造一个共享仓（保证 WMS 绑定可建）
            from uuid import uuid4

            owner_id = await s.scalar(
                text("SELECT id FROM oms_org.org_owner WHERE is_deleted = 0 LIMIT 1")
            )
            await s.execute(
                text(
                    "INSERT INTO oms_fulfill.ful_branch "
                    "(tenant_id, owner_id, branch_bn, branch_name, branch_type, is_ctrl, "
                    " countable_flag, status, create_time, update_time, version, is_deleted) "
                    "VALUES (1, :owner, :bn, '种子共享仓', 'entity', 1, 1, 'enabled', "
                    "NOW(3), NOW(3), 0, 0)"
                ),
                {"owner": int(owner_id or 0), "bn": f"SEEDBR{uuid4().hex[:6]}"},
            )
            await s.commit()
            bid = await s.scalar(
                text("SELECT id FROM oms_fulfill.ful_branch WHERE is_deleted = 0 ORDER BY id DESC LIMIT 1")
            )
            branch_ids = [int(bid or 0)]
            print(f"[seed] CI 空库 → 自造共享仓 {branch_ids[0]}")

        n = 0
        for spec in BINDING_LIST:
            wms_id = wms_ids.get(spec["wms_code"], 0)
            if not wms_id:
                continue
            for bid in branch_ids:
                exist = await s.scalar(
                    text(
                        "SELECT id FROM oms_fulfill.ful_wms_binding "
                        "WHERE branch_id = :b AND wms_id = :w AND is_deleted = 0 "
                        "AND status = 'active'"
                    ),
                    {"b": bid, "w": wms_id},
                )
                if exist:
                    continue
                await s.execute(
                    text(
                        "INSERT INTO oms_fulfill.ful_wms_binding "
                        "(tenant_id, owner_id, branch_id, wms_id, protocol, adapter_code, "
                        " wms_branch_code, wms_owner_code, app_key, secret_enc, key_version, "
                        " endpoint, env, timeout_ms, retry_policy_json, capability_json, "
                        " priority, effective_from, effective_to, status, create_time, "
                        " update_time, version, is_deleted) "
                        "VALUES (1, NULL, :b, :w, :proto, :adapter, :whc, :woc, "
                        " 'mock_wms_key', NULL, 'v1', :ep, 'dev', 10000, NULL, :cap, "
                        " :prio, NULL, NULL, 'active', NOW(3), NOW(3), 0, 0)"
                    ),
                    {
                        "b": bid,
                        "w": wms_id,
                        "proto": "ttx_rest",
                        "adapter": spec["wms_code"] == "MOCK_QIMEN"
                        and "qimen-adapter" or "ttx-adapter",
                        "whc": spec["wms_branch_code"],
                        "woc": spec["wms_owner_code"],
                        "ep": MOCK_WMS_ENDPOINT,
                        "cap": json.dumps(spec["capability"], ensure_ascii=False),
                        "prio": spec["priority"],
                    },
                )
                n += 1
        await s.commit()
        print(f"[seed] 新建仓×WMS 绑定 {n} 条（仓 {branch_ids} → {MOCK_WMS_ENDPOINT}）")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
