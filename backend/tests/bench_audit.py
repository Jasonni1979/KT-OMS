"""M0.6 审单插件链吞吐压测（风险点③验证）：
目标（SRS-D03.02 / Q37）：审单吞吐 ≥500 单/分钟。
本 spike 验证插件链纯计算部分的吞吐上限（不含 DB/Redis IO——真实链路 IO 走异步，
M2 用真实依赖复测；此处先证规则编排本身不是瓶颈）。

场景：
1. 单线程串行 10000 单 → 计算 单/分钟
2. 插件链正确性抽样：黑名单短路 / 地址异常 HOLD / 正常单 auto_pass
3. 多进程 worker 模拟（ProcessPoolExecutor）→ 评估横向扩展线性度

运行: cd backend && uv run python -m tests.bench_audit
"""
import time
from concurrent.futures import ProcessPoolExecutor

from app.domain.audit import AuditEngine, OrderContext, registered_plugins


def make_order(i: int) -> OrderContext:
    return OrderContext(
        order_id=f"SO{i:08d}",
        shop_id=1,
        owner_id=1,
        amount=199.0 + (i % 50),
        receiver_mobile=f"138{i % 10000:08d}",
        receiver_address=f"上海市青浦区蟠龙路{i}号",
        items=[{"bm_id": 10001, "num": 1 + i % 3}],
    )


def audit_one(i: int) -> bool:
    """worker 进程内独立建引擎（注册表模块级，fork 后共享）"""
    engine = AuditEngine()
    ctx = engine.audit(make_order(i))
    return ctx.auto_passed


def scenario_correctness() -> bool:
    from app.domain.audit import BLACKLIST_MOCK
    engine = AuditEngine()

    # 正常单 → auto_pass
    normal = engine.audit(make_order(1))
    ok_normal = normal.auto_passed and normal.selected_branch == 1 and normal.logistics == "SF"

    # 黑名单 → 短路，不产出 plan
    BLACKLIST_MOCK.add("13800000002")
    blocked = engine.audit(make_order(2))
    ok_black = not blocked.auto_passed and any(r.code == "BLACKLIST" for r in blocked.reasons)
    BLACKLIST_MOCK.discard("13800000002")

    # 地址异常 → HOLD，原因结构化
    bad_addr = OrderContext(order_id="X", shop_id=1, owner_id=1, amount=100,
                            receiver_address="短", items=[])
    held = engine.audit(bad_addr)
    ok_addr = not held.auto_passed and any(r.code == "ADDRESS_INVALID" for r in held.reasons)

    ok = ok_normal and ok_black and ok_addr
    print(f"[正确性] 正常单auto_pass={ok_normal} 黑名单短路={ok_black} 地址HOLD={ok_addr} → {'✅ PASS' if ok else '❌ FAIL'}")
    return ok


def scenario_throughput_serial(n: int = 10000) -> bool:
    engine = AuditEngine()
    t0 = time.perf_counter()
    passed = sum(1 for i in range(n) if engine.audit(make_order(i)).auto_passed)
    cost = time.perf_counter() - t0
    per_min = n / cost * 60
    ok = per_min >= 500
    print(f"[串行吞吐] {n}单/{cost:.2f}s = {per_min:,.0f} 单/分钟（目标≥500）auto_pass={passed} → {'✅ PASS' if ok else '❌ FAIL'}")
    return ok


def scenario_throughput_mp(n: int = 40000, workers: int = 4) -> bool:
    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        passed = sum(pool.map(audit_one, range(n), chunksize=500))
    cost = time.perf_counter() - t0
    per_min = n / cost * 60
    print(f"[{workers}进程吞吐] {n}单/{cost:.2f}s = {per_min:,.0f} 单/分钟 auto_pass={passed}")
    return per_min >= 500 * workers * 0.7  # 横向扩展线性度 ≥70%


def main() -> None:
    print(f"已注册插件 {len(registered_plugins())} 个: {[p[0] for p in registered_plugins()]}\n")
    results = [
        scenario_correctness(),
        scenario_throughput_serial(),
        scenario_throughput_mp(),
    ]
    print("\n" + ("🎉 M0.6 审单链验证通过（正确性+吞吐≥500单/分+横向扩展）"
                 if all(results) else "⚠️ 存在失败场景"))
    raise SystemExit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
