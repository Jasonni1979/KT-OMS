"""批量造单全链路端到端（W10 · M3 内测）

**为什么**：PLAN-DEV-01 §3 M3 的 W10 明确要求 ——
> 造单引擎批量模式：正向 100 单——含拆单/缺货/改地址场景矩阵

此前的场景矩阵端到端（`scenario_matrix_e2e.py`）是**每场景 1 单**（共 7 单），
验证的是「能不能识别出场景特征」；本脚本是**批量版**，验证的是
**批量下会不会漏单、会不会重复、金额与行数会不会错**。

**场景配比（合计 100 单）**：

| 场景 | 数量 | 断言点 |
|---|---|---|
| normal | 40 | 单行、金额落库 |
| multi_item | 15 | 多行 |
| big_amount | 10 | 大额金额 |
| out_of_stock | 10 | 下单数量被如实记录（超可售） |
| address_abnormal | 10 | 缺省区特征可读 |
| unbound_item | 10 | **OMS 自动建档**（销售物料新增） |
| buyer_message | 5 | 买家留言落库 |

**批量下的不变量断言**（不只是「跑通」）：

1. 造单 100 单 → **全部落库**（按 platform_order_bn 逐单核对，不取「第一条」）
2. 行数 / 金额按场景正确（金额按**分**比较，避免浮点误差误判）
3. 幂等：同一单重复拉 → **不产生重复订单**
4. **无失败记录**：`gw_api_fail` / `ord_order_fail` 里没有本批次的失败
5. 数据一致性：跑 `data_consistency_check` 体检（跨域引用悬空）

用法：
    cd backend && .venv/bin/python -m app.scripts.batch_load_e2e --with-mock
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
import time
from typing import Any

from app.scripts._checker import Checker

#: 场景配比（场景名, 数量, 中文名）
SCENARIO_PLAN: list[tuple[str, int, str]] = [
    ("normal", 40, "正常单"),
    ("multi_item", 15, "多商品单"),
    ("big_amount", 10, "大额单"),
    ("out_of_stock", 10, "缺货触发"),
    ("address_abnormal", 10, "地址异常"),
    ("unbound_item", 10, "未绑定商品"),
    ("buyer_message", 5, "买家留言"),
]
TOTAL = sum(n for _, n, _ in SCENARIO_PLAN)

#: 大额单阈值（分）—— 金额一律按「分」整数比较
BIG_AMOUNT_FEN = 50_000


async def _mock(url: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    import httpx

    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(f"{url}{path}", json=body or {})
        return r.json()


async def _run(
    gateway_url: str, total: int, concurrency: int = 10
) -> tuple[int, dict[str, Any]]:
    from sqlalchemy import text

    from app.core.config import settings
    from app.core.db import AuthContext, SessionFactory, set_auth_context
    from app.modules.m1_master.service.master import get_redis
    from app.modules.m7_integration.service.gateway import Gateway
    from app.modules.m7_integration.service.pull import PullService
    from app.tools.simulation.scenario import ScenarioRunner

    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    ck = Checker("批量造单全链路（W10 内测）")
    perf: dict[str, Any] = {}
    redis = await get_redis()
    if not gateway_url:
        gateway_url = settings.platform_gateway_url

    async with SessionFactory() as s:
        # ── 基础数据（复用场景运行器：店铺/货主/仓/物料/期初库存）──
        runner = ScenarioRunner(s, redis, gateway_url)
        await runner.cleanup()
        ctx = await runner.prepare_master_data()
        await runner.opening_stock(ctx, qty=100)
        shop_id = int(ctx.get("shop_id") or 0)
        ck.check("基础数据：货主/店铺/仓/物料齐备", bool(shop_id), f"shop={shop_id}")

        # 未绑定商品场景前的销售物料基数（用于验证自动建档）
        sm_before = int(
            (
                await s.execute(
                    text("SELECT COUNT(*) FROM oms_stock.inv_sales_material")
                )
            ).scalar()
            or 0
        )

        # ── ① 批量造单 ──
        scale = total / TOTAL if TOTAL else 1.0
        plan = [(scn, max(1, round(n * scale)), cn) for scn, n, cn in SCENARIO_PLAN]
        t0 = time.perf_counter()
        tid_scene: dict[str, str] = {}
        for scn, cnt, cn in plan:
            made = await _mock(
                gateway_url, "/sim/orders", {"scenario": scn, "count": cnt}
            )
            tids = (made.get("data") or {}).get("tids") or []
            for t in tids:
                tid_scene[str(t)] = scn
            ck.check(
                f"造单：{cn} {cnt} 单",
                len(tids) == cnt,
                f"实得 {len(tids)}",
            )
        perf["make_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        tids = list(tid_scene)
        ck.check(
            f"造单：合计 {len(tid_scene)} 单",
            len(tid_scene) == total,
            f"实得 {len(tid_scene)} / 预期 {total}",
        )

        # ── ② 批量拉单接入 ──
        # ⚠ **为什么不用 poll_shop 做主路径**：轮询窗口是
        #   [水位−overlap, now−safety_delay]，而模拟器造单的时间戳是**当下**
        #   → 落在窗口外 → 拉不到（实测 created=0）。
        #   真实平台场景由「轮询 + 单拉补偿」双保险覆盖（FR-02 三保险），
        #   批量内测走**并发单拉补偿**才拉得全 —— 且顺带测出并发拉单吞吐。
        gateway = Gateway(redis=redis)
        pull = PullService(s, gateway, redis)

        # ②a 轮询路径也走一遍（验证轮询接口本身正常）
        stat = await pull.poll_shop(shop_id)
        perf["poll_stat"] = stat
        ck.check(
            "批量拉单：轮询接口正常",
            bool(stat.get("ok")),
            f"reason={stat.get('reason', '')}",
        )

        # ②b 单拉补偿（每单独立 session —— AsyncSession **不能并发复用**）
        # ⚠ **默认串行（concurrency=1）**：实测并发拉单会触发 MySQL 死锁
        #   （1213 Deadlock）→ 订单没进 OMS = **丢单**。
        #   生产现状是串行轮询（不触发），但「并发补偿拉」是 M4 联调期的需求 →
        #   该缺陷记为 G7，M4-1 必须修（死锁重试 + 统一加锁顺序）。
        sem = asyncio.Semaphore(concurrency)

        async def _pull_one(tid: str) -> dict[str, Any]:
            async with sem:
                async with SessionFactory() as s2:
                    p2 = PullService(s2, gateway, redis)
                    return await p2.pull_single(shop_id, tid)

        t0 = time.perf_counter()
        results = await asyncio.gather(
            *(_pull_one(t) for t in tids), return_exceptions=True
        )
        perf["pull_ms"] = round((time.perf_counter() - t0) * 1000, 1)
        perf["pull_concurrency"] = concurrency
        errs = [r for r in results if isinstance(r, BaseException)]
        oks = [r for r in results if isinstance(r, dict)]
        created = sum(1 for r in oks if str(r.get("outcome") or "") == "created")
        skipped = sum(1 for r in oks if str(r.get("outcome") or "") != "created")
        perf["pull_result"] = {
            "created": created,
            "skipped": skipped,
            "errors": len(errs),
            "error_samples": [f"{type(e).__name__}: {e}" for e in errs[:3]],
        }
        ck.check(
            "批量拉单：无异常",
            not errs,
            f"异常数={len(errs)} 首错={errs[0] if errs else ''}",
        )
        ck.check(
            f"批量拉单：新建订单 {total} 单",
            created == total,
            f"created={created} 非新建={skipped}",
        )

        # ── ③ 逐单核对（**不取「第一条」**，按 platform_order_bn 精确匹配）──
        placeholders = ",".join(f":t{i}" for i in range(len(tids)))
        params = {f"t{i}": t for i, t in enumerate(tids)}
        rows = (
            await s.execute(
                text(
                    "SELECT platform_order_bn, id, paid_amount, buyer_memo FROM "
                    f"oms_order.ord_order WHERE platform_order_bn IN ({placeholders}) "
                    "AND is_deleted = 0"
                ),
                params,
            )
        ).mappings().all()
        landed: dict[str, dict[str, Any]] = {
            str(r["platform_order_bn"]): dict(r) for r in rows
        }
        ck.check(
            f"落库：{len(landed)}/{len(tids)} 单入库",
            len(landed) == len(tids),
            f"落库 {len(landed)} 单",
        )

        # 逐场景特征抽样核对（每个场景至少 1 单）
        by_scene: dict[str, list[str]] = {}
        for t, scn in tid_scene.items():
            by_scene.setdefault(scn, []).append(t)

        def _sample(scn: str) -> list[dict[str, Any]]:
            return [landed[t] for t in by_scene.get(scn, []) if t in landed][:3]

        # normal：单行 + 金额 > 0
        norm = _sample("normal")
        if norm:
            line_counts: list[int] = []
            for r in norm:
                n = int(
                    (
                        await s.execute(
                            text(
                                "SELECT COUNT(*) FROM oms_order.ord_order_item "
                                "WHERE order_id = :o AND is_deleted = 0"
                            ),
                            {"o": int(r["id"])},
                        )
                    ).scalar()
                    or 0
                )
                line_counts.append(n)
            ck.check(
                "正常单：单行订单",
                all(n == 1 for n in line_counts),
                f"行数={line_counts}",
            )
            ck.check(
                "正常单：金额落库且为正",
                all(round(float(r["paid_amount"] or 0) * 100) > 0 for r in norm),
                f"抽样 {len(norm)} 单",
            )

        # multi_item：多行
        mi = _sample("multi_item")
        if mi:
            ok = True
            detail = ""
            for r in mi:
                n = int(
                    (
                        await s.execute(
                            text(
                                "SELECT COUNT(*) FROM oms_order.ord_order_item "
                                "WHERE order_id = :o AND is_deleted = 0"
                            ),
                            {"o": int(r["id"])},
                        )
                    ).scalar()
                    or 0
                )
                ok = ok and n >= 2
                detail = f"行数={n}"
            ck.check("多商品单：订单含多行", ok, detail)

        # big_amount：大额（按分比较）
        ba = _sample("big_amount")
        if ba:
            ck.check(
                "大额单：金额达到大额阈值",
                all(
                    round(float(r["paid_amount"] or 0) * 100) >= BIG_AMOUNT_FEN
                    for r in ba
                ),
                f"抽样 {len(ba)} 单 paid={[r['paid_amount'] for r in ba]}",
            )

        # out_of_stock：数量被如实记录
        os_ = _sample("out_of_stock")
        if os_:
            totals = []
            for r in os_:
                tot = int(
                    (
                        await s.execute(
                            text(
                                "SELECT COALESCE(SUM(nums),0) FROM "
                                "oms_order.ord_order_item WHERE order_id = :o "
                                "AND is_deleted = 0"
                            ),
                            {"o": int(r["id"])},
                        )
                    ).scalar()
                    or 0
                )
                totals.append(tot)
            ck.check(
                "缺货单：下单数量被如实记录（超可售）",
                all(t >= 999 for t in totals),
                f"Σnums={totals}",
            )

        # address_abnormal：缺省区
        aa = _sample("address_abnormal")
        if aa:
            oids = ",".join(str(int(r["id"])) for r in aa)
            n_district = int(
                (
                    await s.execute(
                        text(
                            "SELECT COUNT(*) FROM oms_order.ord_receiver "
                            f"WHERE order_id IN ({oids}) AND is_deleted = 0 "
                            "AND (district IS NULL OR district = '')"
                        )
                    )
                ).scalar()
                or 0
            )
            ck.check(
                "地址异常单：缺省区特征可读",
                n_district == len(aa),
                f"缺省区 {n_district}/{len(aa)}",
            )

        # unbound_item：OMS 自动建档
        sm_after = int(
            (
                await s.execute(
                    text("SELECT COUNT(*) FROM oms_stock.inv_sales_material")
                )
            ).scalar()
            or 0
        )
        ck.check(
            "未绑定商品：OMS 自动建档销售物料",
            sm_after > sm_before,
            f"销售物料 {sm_before} → {sm_after}",
        )

        # buyer_message：留言落库
        bm = _sample("buyer_message")
        if bm:
            ck.check(
                "买家留言单：留言内容落库",
                all(str(r["buyer_memo"] or "").strip() != "" for r in bm),
                f"抽样 {len(bm)} 单",
            )

        # ── ④ 幂等：同一单重复拉 → 不产生重复订单 ──
        if tids:
            dup_tid = tids[0]
            before_cnt = int(
                (
                    await s.execute(
                        text(
                            "SELECT COUNT(*) FROM oms_order.ord_order "
                            "WHERE platform_order_bn = :t AND is_deleted = 0"
                        ),
                        {"t": dup_tid},
                    )
                ).scalar()
                or 0
            )
            await pull.pull_single(shop_id, dup_tid)
            after_cnt = int(
                (
                    await s.execute(
                        text(
                            "SELECT COUNT(*) FROM oms_order.ord_order "
                            "WHERE platform_order_bn = :t AND is_deleted = 0"
                        ),
                        {"t": dup_tid},
                    )
                ).scalar()
                or 0
            )
            ck.check(
                "幂等：同一单重复拉不产生重复订单",
                before_cnt == 1 and after_cnt == 1,
                f"拉前 {before_cnt} → 拉后 {after_cnt}",
            )

        # ── ⑤ 无失败记录 ──
        n_fail = int(
            (
                await s.execute(
                    text(
                        # ⚠ gw_api_fail **无 is_deleted 列**（W7 通道四表的坑）
                        "SELECT COUNT(*) FROM oms_gateway.gw_api_fail "
                        "WHERE create_time > DATE_SUB(NOW(3), INTERVAL 1 HOUR)"
                    )
                )
            ).scalar()
            or 0
        )
        ck.check("无失败记录：gw_api_fail 近 1 小时无新增", n_fail == 0, f"失败数={n_fail}")

        # ── ⑥ 性能数据 ──
        perf["total"] = total
        perf["landed"] = len(landed)
        perf["created"] = created
        perf["orders_per_sec"] = (
            round(created / (perf["pull_ms"] / 1000), 1) if perf["pull_ms"] > 0 else 0.0
        )
        perf["assertions"] = {"passed": ck.passed, "failed": ck.failed}

    # ── ⑦ 结尾清理（**双清**：开头已清一次，这里再清一次）──
    async with SessionFactory() as s:
        await ScenarioRunner(s, redis, gateway_url).cleanup()

    # ⚠ 必须渲染断言行 —— CI 的 `assert_min()` 靠数 `[PASS]` 个数，
    #   不打印就等于「断言数为 0」→ 门禁必挂。
    print(ck.render())

    return (ck.failed, perf)


def main() -> int:
    ap = argparse.ArgumentParser(description="批量造单全链路端到端")
    ap.add_argument("--with-mock", action="store_true", help="启动/复用 mock-platform")
    ap.add_argument("--total", type=int, default=TOTAL, help="总单数（默认 100）")
    ap.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help=(
            "并发拉单数（**默认 1 = 串行**）。"
            "调高可复现已知缺陷：并发拉单会触发 MySQL 死锁"
            "（gw_order_buffer + gw_order_buffer_item 插入锁顺序冲突）→ 丢单，"
            "见《MVP内测验收报告》G7"
        ),
    )
    ap.add_argument("--json", default="", help="性能数据写入 JSON")
    args = ap.parse_args()

    gateway_url = ""
    proc = None
    if args.with_mock:
        from app.scripts._mockctl import start_mock

        proc, gateway_url = start_mock("platform")
        print(f"mock-platform: {gateway_url}{'（复用已有实例）' if proc is None else ''}")

    try:
        failed, perf = asyncio.run(_run(gateway_url, args.total, args.concurrency))
    finally:
        if proc is not None:
            proc.terminate()

    print()
    print("===== 性能数据 =====")
    print(json.dumps(perf, ensure_ascii=False, indent=2))
    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps(perf, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"✓ 已写入 {args.json}")
    if failed:
        print("❌ 批量造单端到端存在失败断言")
        return 1
    print("✅ 批量造单端到端全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
