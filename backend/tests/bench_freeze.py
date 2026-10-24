"""M0.5 预占并发压测（风险点②验证）：
场景1：200 并发抢 100 件库存 → 必须恰好 100 成功、0 超卖
场景2：同幂等键重复提交 50 次 → 只预占 1 次
场景3：release/settle 幂等 → 重复调用不重复扣
运行: cd backend && uv run python -m tests.bench_freeze
前置: deploy/docker-compose.yml 的 redis 已启动（127.0.0.1:6380）
"""
import asyncio
import time
import uuid

from redis.asyncio import Redis

from app.core.config import settings
from app.infra.freeze_service import FreezeService

BRANCH, BM, OWNER = 1, 10001, 1


async def scenario_no_oversell(svc: FreezeService) -> bool:
    """场景1：200 并发抢 100 件，恰好 100 成功"""
    await svc.init_stock(BRANCH, BM, OWNER, store=100)

    async def one(i: int) -> int:
        code, _ = await svc.reserve(BRANCH, BM, OWNER, 1, f"bench-order-{i}")
        return code

    t0 = time.perf_counter()
    results = await asyncio.gather(*(one(i) for i in range(200)))
    cost = (time.perf_counter() - t0) * 1000
    succ = sum(1 for r in results if r == 1)
    fail = sum(1 for r in results if r == -1)
    stock = await svc.get_stock(BRANCH, BM, OWNER)
    ok = succ == 100 and fail == 100 and stock["freeze"] == 100 and stock["store"] == 100
    print(f"[场景1 防超卖] 200并发抢100件: 成功={succ} 不足={fail} freeze={stock['freeze']} "
          f"耗时={cost:.0f}ms → {'✅ PASS' if ok else '❌ FAIL'}")
    return ok


async def scenario_idempotent_reserve(svc: FreezeService) -> bool:
    """场景2：同幂等键 50 次并发重复提交，只预占 1 次"""
    await svc.init_stock(BRANCH, BM, OWNER, store=100)
    key = f"bench-idem-{uuid.uuid4().hex[:8]}"

    async def one(_: int) -> int:
        code, _avail = await svc.reserve(BRANCH, BM, OWNER, 5, key)
        return code

    results = await asyncio.gather(*(one(i) for i in range(50)))
    succ = sum(1 for r in results if r == 1)
    dup = sum(1 for r in results if r == 0)
    stock = await svc.get_stock(BRANCH, BM, OWNER)
    ok = succ == 1 and dup == 49 and stock["freeze"] == 5
    print(f"[场景2 幂等预占] 50次同键: 首次成功={succ} 幂等命中={dup} freeze={stock['freeze']}(应=5) "
          f"→ {'✅ PASS' if ok else '❌ FAIL'}")
    return ok


async def scenario_release_settle(svc: FreezeService) -> bool:
    """场景3：release/settle 幂等 + 数量守恒"""
    await svc.init_stock(BRANCH, BM, OWNER, store=100)
    k1, k2 = "bench-rel", "bench-settle"
    await svc.reserve(BRANCH, BM, OWNER, 10, k1)
    await svc.reserve(BRANCH, BM, OWNER, 10, k2)
    # release 两次（第二次应幂等 code=0）
    c1, _ = await svc.release(BRANCH, BM, OWNER, 10, k1)
    c1b, _ = await svc.release(BRANCH, BM, OWNER, 10, k1)
    # settle 两次（第二次应幂等）
    c2, store_a, freeze_a = await svc.settle(BRANCH, BM, OWNER, 10, k2)
    c2b, _, _ = await svc.settle(BRANCH, BM, OWNER, 10, k2)
    stock = await svc.get_stock(BRANCH, BM, OWNER)
    # 期望：release 回 10（freeze 20→10），settle 扣 store 100→90 freeze 10→0
    ok = (c1 == 1 and c1b == 0 and c2 == 1 and c2b == 0
          and stock["store"] == 90 and stock["freeze"] == 0)
    print(f"[场景3 释放/转扣] release({c1},{c1b}) settle({c2},{c2b}) "
          f"store={stock['store']}(应90) freeze={stock['freeze']}(应0) → {'✅ PASS' if ok else '❌ FAIL'}")
    return ok


async def main() -> None:
    redis = Redis.from_url(settings.redis_url, decode_responses=False, max_connections=500)
    await redis.flushdb()
    svc = FreezeService(redis)
    results = [
        await scenario_no_oversell(svc),
        await scenario_idempotent_reserve(svc),
        await scenario_release_settle(svc),
    ]
    await redis.aclose()
    print("\n" + ("🎉 M0.5 预占原型全部通过（防超卖/幂等/守恒）" if all(results) else "⚠️ 存在失败场景，需修复"))
    raise SystemExit(0 if all(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
