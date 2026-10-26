"""W10 · 压测复跑（性能基线）

**为什么要有**：M0 spike 当时验证过三个风险点的性能，但那是 **spike 级**（纯逻辑、
短平快）。M1-M9 把真实依赖接进来之后（DB 事务 / Redis Lua / HTTP 平台调用），
「规则计算很快、瓶颈在 IO」这个结论**必须复跑验证** —— 否则验收报告里的性能数据
是 M0 的旧账，不能代表现在的系统。

**复跑哪些基线**（M0-spike验证报告 §5 / §6）：

1. **风险点② Lua 预占 200 并发抢 100 件**
   M0 声称：恰好 100 成功 / 100 拒绝 / **零超卖**（1.2s）
   本脚本：并发档位 10 / 50 / 100 / 200 全扫描 + 不变量断言
2. **风险点② 同幂等键 50 次并发**
   M0 声称：仅预占 1 次，49 次幂等命中
   本脚本：复跑 + 不变量断言
3. **风险点③ 审单链吞吐** —— ⚠ 本次**不复跑**
   M0 的 4000 万单/分钟是**无 IO 的纯规则计算**基准；真实链路里 IO 等待占主导，
   拿纯计算数字当验收指标会误导。端到端吞吐见 `batch_load_e2e.py` 的真实链路数据。

**不变量断言**（压测不能只看延迟数字 —— 必须同时证明业务正确性）：
- 预占并发：**恰好 100 件被抢走**，冻结数 == 100，可用 == 0 → **零超卖**
- 幂等：同一幂等键重复预占只生效一次
- 释放/转扣减后库存口径正确

用法：
    cd backend && .venv/bin/python -m app.scripts.load_test
    cd backend && .venv/bin/python -m app.scripts.load_test --json /tmp/loadtest.json

⚠ 本脚本会写 Redis 的测试 key（`inv:lt:*` 前缀），结束时会清理。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from redis.asyncio import Redis

from app.core.config import settings
from app.infra.freeze_service import FreezeService

#: 测试用三元键（**独立前缀**，不与业务数据冲突）
LT_BRANCH = 999_001
LT_BM = 999_002
LT_OWNER = 999_003

#: 库存数量（与 M0 spike 一致：100 件）
LT_STORE = 100

#: 并发档位（每个档位都是「N 个并发同时抢 100 件」）
CONCURRENCY_LEVELS = (10, 50, 100, 200)

#: Redis 连接池上限
#: ⚠ redis-py **8.x 默认 max_connections=100** → 200 并发直接
#:   `MaxConnectionsError: Too many connections`。
#:   压测脚本自建大池（**不改业务代码**）——
#:   但这个默认值本身是**生产风险**：业务侧若出现 >100 并发打 Redis 会同样炸。
MAX_CONN = 512

PASS = 0
FAIL = 0


def ok(msg: str) -> None:
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def bad(msg: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}")


@dataclass
class BenchResult:
    """一个并发档位的压测结果"""

    name: str
    concurrency: int
    total: int
    succeeded: int
    rejected: int
    elapsed_ms: float
    latencies_ms: list[float] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def rps(self) -> float:
        return self.total / (self.elapsed_ms / 1000) if self.elapsed_ms > 0 else 0.0

    def pct(self, p: float) -> float:
        """分位数（就近取整法，不引第三方库）"""
        if not self.latencies_ms:
            return 0.0
        data = sorted(self.latencies_ms)
        idx = min(len(data) - 1, max(0, round(p / 100 * len(data)) - 1))
        return data[idx]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "concurrency": self.concurrency,
            "total": self.total,
            "succeeded": self.succeeded,
            "rejected": self.rejected,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "rps": round(self.rps, 1),
            "p50_ms": round(self.pct(50), 2),
            "p95_ms": round(self.pct(95), 2),
            "p99_ms": round(self.pct(99), 2),
            "max_ms": round(max(self.latencies_ms), 2) if self.latencies_ms else 0.0,
            **self.extra,
        }


async def _conn() -> Redis:
    """压测专用 Redis 连接（大连接池；不共用业务单例，避免互相挤占）"""
    return Redis.from_url(
        settings.redis_url, decode_responses=True, max_connections=MAX_CONN
    )


async def _cleanup(fs: FreezeService, r: Any, idem_keys: list[str]) -> None:
    """清理测试 key（不留残留污染其它测试）

    ⚠ 幂等键 TTL 是 600s —— 上一次跑崩了/中断了，键会**活到过期**，
      下一次跑就会「命中幂等」被误判成业务异常（实测踩到）。
      故：① 幂等键带运行唯一后缀 ② 清理时按前缀扫掉全部残留。
    """
    key = fs.stock_key(LT_BRANCH, LT_BM, LT_OWNER)
    await r.delete(key)
    if idem_keys:
        await r.delete(*[fs.freeze_key(k) for k in idem_keys])
    # 按前缀扫掉历史残留（inv:freeze:lt:*）
    stale = [k async for k in r.scan_iter(match="inv:freeze:lt:*", count=500)]
    if stale:
        await r.delete(*stale)


async def bench_reserve(concurrency: int, total: int = 200) -> BenchResult:
    """压测 1：Lua 预占并发（复跑 M0 风险点②）

    场景：库存 100 件，`total` 个并发同时各抢 1 件
    期望：**恰好 100 成功 / (total-100) 拒绝**，冻结数 == 100，可用 == 0
    """
    r = await _conn()
    fs = FreezeService(r)
    await _cleanup(fs, r, [])

    # 期初：100 件可用
    await fs.init_stock(LT_BRANCH, LT_BM, LT_OWNER, store=LT_STORE)

    run_id = uuid.uuid4().hex[:8]
    idem_keys = [f"lt:{run_id}:{concurrency}:{i}" for i in range(total)]
    latencies: list[float] = []
    codes: list[int] = []

    # ⚠ **必须真限流**：直接 gather 200 个任务 = 实际并发 200，
    #   档位形同虚设（实测四档数据几乎一样）。Semaphore 才控得住在途数。
    sem = asyncio.Semaphore(concurrency)

    async def one(idx: int) -> None:
        async with sem:
            t0 = time.perf_counter()
            code, _ = await fs.reserve(
                LT_BRANCH, LT_BM, LT_OWNER, 1, idem_keys[idx], ttl_seconds=600
            )
            latencies.append((time.perf_counter() - t0) * 1000)
            codes.append(code)

    t0 = time.perf_counter()
    await asyncio.gather(*(one(i) for i in range(total)))
    elapsed = (time.perf_counter() - t0) * 1000

    succeeded = sum(1 for c in codes if c == 1)
    rejected = sum(1 for c in codes if c == -1)
    stock = await fs.get_stock(LT_BRANCH, LT_BM, LT_OWNER)
    freeze = int(stock.get("freeze", 0))
    store = int(stock.get("store", 0))
    available = store - freeze

    await _cleanup(fs, r, idem_keys)

    return BenchResult(
        name="lua_reserve_concurrent",
        concurrency=concurrency,
        total=total,
        succeeded=succeeded,
        rejected=rejected,
        elapsed_ms=elapsed,
        latencies_ms=latencies,
        extra={
            "store": store,
            "freeze": freeze,
            "available": available,
            "idempotent_hit": sum(1 for c in codes if c == 0),
        },
    )


async def bench_idempotent(rounds: int = 50) -> BenchResult:
    """压测 2：同幂等键重复提交（复跑 M0 风险点② 的幂等项）

    期望：**只生效 1 次**，其余 49 次幂等命中，冻结数始终 == 1
    """
    r = await _conn()
    fs = FreezeService(r)
    await _cleanup(fs, r, [])
    await fs.init_stock(LT_BRANCH, LT_BM, LT_OWNER, store=LT_STORE)

    idem = "lt:idem:fixed"
    latencies: list[float] = []
    codes: list[int] = []

    async def one() -> None:
        t0 = time.perf_counter()
        code, _ = await fs.reserve(LT_BRANCH, LT_BM, LT_OWNER, 1, idem, ttl_seconds=600)
        latencies.append((time.perf_counter() - t0) * 1000)
        codes.append(code)

    t0 = time.perf_counter()
    await asyncio.gather(*(one() for _ in range(rounds)))
    elapsed = (time.perf_counter() - t0) * 1000

    stock = await fs.get_stock(LT_BRANCH, LT_BM, LT_OWNER)
    freeze = int(stock.get("freeze", 0))
    await _cleanup(fs, r, [idem])

    return BenchResult(
        name="lua_reserve_idempotent",
        concurrency=rounds,
        total=rounds,
        succeeded=sum(1 for c in codes if c == 1),
        rejected=sum(1 for c in codes if c == -1),
        elapsed_ms=elapsed,
        latencies_ms=latencies,
        extra={
            "freeze": freeze,
            "idempotent_hit": sum(1 for c in codes if c == 0),
            "rounds": rounds,
        },
    )


async def bench_release_settle() -> BenchResult:
    """压测 3：预占 → 释放 / 转扣减（口径正确性）

    期望：
    - 预占 30 件 → freeze=30, store=30
    - 释放 10 件 → freeze=20, store=30
    - 转扣减 20 件 → freeze=0, store=10（实扣 20，可用相应减少）
    """
    r = await _conn()
    fs = FreezeService(r)
    await _cleanup(fs, r, [])
    await fs.init_stock(LT_BRANCH, LT_BM, LT_OWNER, store=LT_STORE)

    steps: list[dict[str, Any]] = []

    k1 = "lt:rs:1"
    code, _ = await fs.reserve(LT_BRANCH, LT_BM, LT_OWNER, 30, k1, ttl_seconds=600)
    s = await fs.get_stock(LT_BRANCH, LT_BM, LT_OWNER)
    steps.append({"step": "reserve_30", "code": code, "store": s["store"], "freeze": s["freeze"]})

    k2 = "lt:rs:2"
    code, _ = await fs.reserve(LT_BRANCH, LT_BM, LT_OWNER, 10, k2, ttl_seconds=600)
    rcode, _ = await fs.release(LT_BRANCH, LT_BM, LT_OWNER, 10, k2)
    s = await fs.get_stock(LT_BRANCH, LT_BM, LT_OWNER)
    steps.append({"step": "reserve_10_release_10", "code": code, "release_code": rcode,
                  "store": s["store"], "freeze": s["freeze"]})

    scode, store_after, freeze_after = await fs.settle(
        LT_BRANCH, LT_BM, LT_OWNER, 30, k1
    )
    s = await fs.get_stock(LT_BRANCH, LT_BM, LT_OWNER)
    steps.append({"step": "settle_30", "code": scode, "store": s["store"], "freeze": s["freeze"]})

    await _cleanup(fs, r, [k1])

    return BenchResult(
        name="reserve_release_settle",
        concurrency=1,
        total=1,
        succeeded=1,
        rejected=0,
        elapsed_ms=0,
        extra={"steps": steps, "settle_store_after": store_after,
               "settle_freeze_after": freeze_after},
    )


def _assert_reserve(res: BenchResult) -> None:
    """压测 1 的不变量：零超卖"""
    label = f"并发 {res.concurrency} · 抢 {LT_STORE} 件"
    if res.succeeded == LT_STORE:
        ok(f"{label}：恰好 {LT_STORE} 件成功（实际 {res.succeeded}）")
    else:
        bad(f"{label}：成功数 {res.succeeded} ≠ {LT_STORE}（超卖或少卖）")
    if res.extra["freeze"] == LT_STORE:
        ok(f"{label}：冻结数 == {LT_STORE}（实际 {res.extra['freeze']}）")
    else:
        bad(f"{label}：冻结数 {res.extra['freeze']} ≠ {LT_STORE}")
    if res.extra["available"] == 0:
        ok(f"{label}：可用归零（实际 {res.extra['available']}）")
    else:
        bad(f"{label}：可用 {res.extra['available']} ≠ 0")
    if res.extra["idempotent_hit"] == 0:
        ok(f"{label}：无幂等误命中（本场景幂等键唯一）")
    else:
        bad(f"{label}：出现 {res.extra['idempotent_hit']} 次幂等命中（幂等键被复用）")
    if res.rejected == res.total - LT_STORE:
        ok(f"{label}：其余 {res.rejected} 次按可用不足拒绝")
    else:
        bad(f"{label}：拒绝数 {res.rejected} ≠ {res.total - LT_STORE}")


async def run_all(levels: tuple[int, ...]) -> list[dict[str, Any]]:
    print("=== W10 压测复跑（M0 基线对照）===\n")

    # ---------- 压测 1：预占并发扫描 ----------
    print("▶ 压测 1 · Lua 预占并发（复跑 M0 风险点②：200 并发抢 100 件零超卖）")
    results: list[dict[str, Any]] = []
    for c in levels:
        res = await bench_reserve(c)
        d = res.to_dict()
        results.append(d)
        print(
            f"  并发 {c:>3}：{res.total} 次 / {res.elapsed_ms:8.1f}ms "
            f"| {res.rps:9.1f} 次/秒 | P50 {res.pct(50):6.2f}ms "
            f"P95 {res.pct(95):6.2f}ms P99 {res.pct(99):6.2f}ms"
        )
        _assert_reserve(res)
    print()

    # ---------- 压测 2：幂等 ----------
    print("▶ 压测 2 · 同幂等键重复提交（复跑 M0 风险点② 幂等项）")
    idem = await bench_idempotent()
    print(
        f"  {idem.total} 次并发同键：{idem.elapsed_ms:.1f}ms "
        f"| 生效 {idem.succeeded} 次 | 幂等命中 {idem.extra['idempotent_hit']} 次 "
        f"| 冻结 {idem.extra['freeze']}"
    )
    if idem.succeeded == 1 and idem.extra["freeze"] == 1:
        ok("同幂等键 50 次并发：仅生效 1 次，冻结数 == 1")
    else:
        bad(
            f"同幂等键 50 次并发：生效 {idem.succeeded} 次 / 冻结 {idem.extra['freeze']}（应各为 1）"
        )
    results.append(idem.to_dict())
    print()

    # ---------- 压测 3：释放/转扣减口径 ----------
    print("▶ 压测 3 · 预占→释放→转扣减（口径正确性）")
    rs = await bench_release_settle()
    steps = {s["step"]: s for s in rs.extra["steps"]}
    s1, s2, s3 = steps["reserve_30"], steps["reserve_10_release_10"], steps["settle_30"]
    if s1["freeze"] == 30 and s1["store"] == LT_STORE:
        ok(f"预占 30 件：freeze={s1['freeze']} store={s1['store']}")
    else:
        bad(f"预占 30 件口径错：freeze={s1['freeze']} store={s1['store']}")
    if s2["freeze"] == 30 and s2["store"] == LT_STORE:
        ok(f"再预占 10 后释放 10：freeze={s2['freeze']} store={s2['store']}")
    else:
        bad(f"预占/释放口径错：freeze={s2['freeze']} store={s2['store']}")
    if s3["freeze"] == 0 and s3["store"] == LT_STORE - 30:
        ok(f"转扣减 30 件：freeze={s3['freeze']} store={s3['store']}（实扣生效）")
    else:
        bad(f"转扣减口径错：freeze={s3['freeze']} store={s3['store']}（应 0 / {LT_STORE - 30}）")
    results.append(rs.to_dict())
    print()

    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="W10 压测复跑")
    ap.add_argument(
        "--levels",
        default=",".join(str(c) for c in CONCURRENCY_LEVELS),
        help="并发档位，逗号分隔",
    )
    ap.add_argument("--json", default="", help="结果写入 JSON 文件（供验收报告引用）")
    args = ap.parse_args()

    levels = tuple(int(x) for x in args.levels.split(",") if x.strip())
    results = asyncio.run(run_all(levels))

    print("=" * 60)
    print(f"断言：通过 {PASS} / 失败 {FAIL}")
    summary = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "assertions": {"passed": PASS, "failed": FAIL},
        "results": results,
    }
    if args.json:
        pathlib.Path(args.json).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"✓ 结果已写入 {args.json}")
    if FAIL:
        print("❌ 压测存在失败断言")
        return 1
    print("✅ 压测全部通过（零超卖 + 幂等 + 口径正确）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
