"""造单场景矩阵端到端（复盘补齐 · W7 收尾）

mock-platform 的场景库定义了 10 个场景，但此前只有 `normal` 被端到端验证过。
本脚本对**正向/异常场景**逐个跑「造单 → 拉单接入 → OMS 侧识别」，
验证 OMS 侧能正确落库并识别出该场景的特征。

**范围边界**（对齐 Jason 2026-10-25 决策）：
- 本脚本只验证「订单被正确拉入 + 特征被正确识别」
- **异常单的处置逻辑（缺货五步策略链 / 地址异常拦截 / 未绑定商品处置）属 W8 D03.09，
  本期不实现**，此处只断言「订单已入库且可被识别」

场景覆盖：
| 场景 | 断言点 |
|---|---|
| normal | 正常单：建单成功 + 行数与金额 |
| multi_item | 多商品单：订单含多行 |
| big_amount | 大额单：金额正确落库 |
| out_of_stock | 缺货触发：下单量超可售（订单仍入库，缺货处置留 W8） |
| address_abnormal | 地址异常：收货地址缺省区（订单入库，地址异常处置留 W8） |
| unbound_item | 未绑定商品：平台商品未建档 → OMS 自动建档 |
| buyer_message | 买家留言：留言内容落库 |

用法：
    cd backend && .venv/bin/python -m app.scripts.scenario_matrix_e2e [--with-mock]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
MOCK_DIR = REPO_ROOT / "mocks" / "platform"

#: 场景矩阵（场景名 → 中文名）
SCENARIOS: list[tuple[str, str]] = [
    ("normal", "正常单"),
    ("multi_item", "多商品单"),
    ("big_amount", "大额单"),
    ("out_of_stock", "缺货触发"),
    ("address_abnormal", "地址异常"),
    ("unbound_item", "未绑定商品"),
    ("buyer_message", "买家留言"),
]


class Checker:
    """断言收集器"""

    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.lines: list[str] = []

    def check(self, name: str, cond: bool, detail: str = "") -> bool:
        if cond:
            self.passed += 1
            self.lines.append(f"  [PASS] {name}" + (f" | {detail}" if detail else ""))
        else:
            self.failed += 1
            self.lines.append(f"  [FAIL] {name}" + (f" | {detail}" if detail else ""))
        return cond

    def render(self) -> str:
        out = [f"\n=== 造单场景矩阵端到端（{len(SCENARIOS)} 场景）===\n"]
        out.extend(self.lines)
        out.append(f"\n合计：{self.passed}/{self.passed + self.failed} 项通过")
        return "\n".join(out)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def start_mock() -> tuple[subprocess.Popen, str]:
    port = _free_port()
    py = str(BACKEND_DIR / ".venv" / "bin" / "python")
    env = {**os.environ, "PYTHONPATH": str(MOCK_DIR)}
    proc = subprocess.Popen(
        [
            py,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=str(MOCK_DIR),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                break
        except OSError:
            time.sleep(0.25)
    else:
        proc.kill()
        raise RuntimeError("mock-platform 启动失败")
    return proc, f"http://127.0.0.1:{port}"


async def _mock(method: str, url: str, path: str, body: dict | None = None) -> dict:
    import httpx

    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.request(method, f"{url}{path}", json=body or {})
        return r.json()


async def _run(gateway_url: str) -> int:
    from sqlalchemy import text

    from app.core.config import settings
    from app.core.db import AuthContext, SessionFactory, engine, set_auth_context
    from app.services.gateway import Gateway
    from app.services.master import get_redis
    from app.services.pull import PullService

    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    ck = Checker()
    redis = await get_redis()
    if not gateway_url:
        gateway_url = settings.platform_gateway_url

    async with SessionFactory() as s:
        # ── 基础数据：货主 / 店铺 / 物料 / 仓 / 期初库存（复用 scenario_e2e 的准备逻辑）
        from app.services.scenario import ScenarioRunner

        runner = ScenarioRunner(s, redis, gateway_url)
        await runner.cleanup()
        ctx = await runner.prepare_master_data()
        await runner.opening_stock(ctx, qty=100)
        shop_id = int(ctx.get("shop_id") or 0)
        ck.check("基础数据：货主/店铺/仓/物料齐备", bool(shop_id), f"shop={shop_id}")

        gateway = Gateway(redis=redis)
        pull = PullService(s, gateway, redis)

        for scenario, cn in SCENARIOS:
            print(f"\n▶ 场景 {scenario}（{cn}）")
            # ① 模拟器造单
            made = await _mock(
                "POST", gateway_url, "/sim/orders", {"scenario": scenario, "count": 1}
            )
            tids = (made.get("data") or {}).get("tids") or []
            if not ck.check(f"{cn}：模拟器造单成功", bool(tids), f"tid={tids[:1]}"):
                continue
            tid = str(tids[0])

            # ② 拉单接入 OMS
            res = await pull.pull_single(shop_id, tid)
            outcome = str(res.get("outcome") or "")
            if not ck.check(
                f"{cn}：拉单接入建单成功",
                bool(res.get("ok")) and outcome == "created",
                f"outcome={outcome} reason={res.get('reason', '')}",
            ):
                continue

            # ③ OMS 侧识别：查订单主表 + 行 + 收货信息
            row = (
                await s.execute(
                    text(
                        "SELECT id, order_bn, paid_amount, list_amount, ship_status, "
                        "       audit_status FROM oms_order.ord_order "
                        "WHERE platform_order_bn = :t ORDER BY id DESC LIMIT 1"
                    ),
                    {"t": tid},
                )
            ).mappings().first()
            if not ck.check(f"{cn}：订单已落库", row is not None, f"tid={tid}"):
                continue
            assert row is not None  # mypy 收窄

            oid = int(row["id"])
            items = (
                await s.execute(
                    text(
                        "SELECT COUNT(*) FROM oms_order.ord_order_item "
                        "WHERE order_id = :o AND is_deleted = 0"
                    ),
                    {"o": oid},
                )
            ).scalar()
            n_items = int(items or 0)
            # 收货人：district 为明文（PIPL 加密的是 name/address）
            rcv = (
                await s.execute(
                    text(
                        "SELECT district, city, province FROM oms_order.ord_receiver "
                        "WHERE order_id = :o AND is_deleted = 0 LIMIT 1"
                    ),
                    {"o": oid},
                )
            ).mappings().first()
            # 买家留言在订单头（ord_order.buyer_memo）
            memo = await s.scalar(
                text("SELECT buyer_memo FROM oms_order.ord_order WHERE id = :o"),
                {"o": oid},
            )

            if scenario == "normal":
                ck.check(f"{cn}：单行订单", n_items == 1, f"行数={n_items}")
                ck.check(
                    f"{cn}：金额落库",
                    float(row["paid_amount"] or 0) > 0,
                    f"paid={row['paid_amount']}",
                )
            elif scenario == "multi_item":
                ck.check(f"{cn}：多行订单", n_items >= 2, f"行数={n_items}")
            elif scenario == "big_amount":
                ck.check(
                    f"{cn}：大额金额落库",
                    float(row["paid_amount"] or 0) > 500,
                    f"paid={row['paid_amount']}",
                )
            elif scenario == "out_of_stock":
                # 缺货处置属 W8；本期只验证订单已入库且数量被如实记录
                ck.check(f"{cn}：订单已入库", oid > 0, f"oid={oid}")
                total = (
                    await s.execute(
                        text(
                            "SELECT COALESCE(SUM(nums),0) FROM oms_order.ord_order_item "
                            "WHERE order_id = :o AND is_deleted = 0"
                        ),
                        {"o": oid},
                    )
                ).scalar()
                ck.check(
                    f"{cn}：下单数量被如实记录（超可售）",
                    int(total or 0) >= 999,
                    f"Σnums={total}",
                )
            elif scenario == "address_abnormal":
                # 地址异常处置属 W8；本期验证异常特征可被读取到
                ck.check(f"{cn}：订单已入库", oid > 0, f"oid={oid}")
                ck.check(
                    f"{cn}：地址缺省区（可被识别）",
                    rcv is not None and not str(rcv["district"] or "").strip(),
                    f"district={rcv['district'] if rcv else 'N/A'}",
                )
            elif scenario == "unbound_item":
                # 未绑定商品的处置属 W8；本期验证未建档商品被自动建档
                # （自动建档落在**销售物料** inv_sales_material，D02.03 FR-05a）
                ck.check(f"{cn}：订单已入库", oid > 0, f"oid={oid}")
                sm = (
                    await s.execute(
                        text(
                            "SELECT id, sales_material_bn, source, bind_status "
                            "FROM oms_stock.inv_sales_material "
                            "WHERE sales_material_bn = 'SKU_NOT_ONBOARD_999' "
                            "AND is_deleted = 0 ORDER BY id DESC LIMIT 1"
                        )
                    )
                ).mappings().first()
                ck.check(
                    f"{cn}：未建档商品已自动建档（销售物料）",
                    sm is not None,
                    f"sm={dict(sm) if sm else '未建档'}",
                )
                if sm is not None:
                    ck.check(
                        f"{cn}：自动建档来源标记为 api",
                        str(sm["source"]) == "api",
                        f"source={sm['source']} bind_status={sm['bind_status']}",
                    )
            elif scenario == "buyer_message":
                ck.check(f"{cn}：订单已入库", oid > 0, f"oid={oid}")
                ck.check(
                    f"{cn}：买家留言落库",
                    bool(str(memo or "").strip()),
                    f"memo={memo}",
                )

            # ④ 该场景订单不污染后续场景（清理）
            await s.execute(
                text(
                    "DELETE FROM oms_order.ord_order_item WHERE order_id IN "
                    "(SELECT id FROM oms_order.ord_order WHERE platform_order_bn = :t)"
                ),
                {"t": tid},
            )
            await s.execute(
                text(
                    "DELETE FROM oms_order.ord_receiver WHERE order_id IN "
                    "(SELECT id FROM oms_order.ord_order WHERE platform_order_bn = :t)"
                ),
                {"t": tid},
            )
            await s.execute(
                text(
                    "DELETE FROM oms_order.ord_order WHERE platform_order_bn = :t"
                ),
                {"t": tid},
            )
            # 清掉本场景自动建档的销售物料（保持下次重跑是「首次建档」）
            await s.execute(
                text(
                    "DELETE FROM oms_stock.inv_sales_material "
                    "WHERE sales_material_bn = 'SKU_NOT_ONBOARD_999'"
                )
            )
            await s.commit()

        await runner.cleanup()

    await engine.dispose()
    print(ck.render())
    return 0 if ck.failed == 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="造单场景矩阵端到端")
    parser.add_argument("--gateway", default="", help="模拟器地址")
    parser.add_argument("--with-mock", action="store_true", help="自动启动 mock-platform")
    args = parser.parse_args()

    proc = None
    url = args.gateway
    if args.with_mock:
        proc, url = start_mock()
        print(f"[scenario-matrix] mock-platform 已启动：{url}")
    try:
        return asyncio.run(_run(url))
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
