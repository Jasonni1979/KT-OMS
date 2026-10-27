"""平台售后报文自动同步端到端（D05.01 FR-01a · G1 缺口补齐）

**为什么补这个**：D05.01 FR-01a 要求「平台售后报文自动进 OMS」，
但此前售后申请单只能**人工建单**（`aftersale_scenario_e2e.py` 覆盖的是手工建单侧），
平台侧买家发起的「仅退款 / 退货退款」报文**没有任何自动进单链路** —— MVP 内测验收列为 G1 缺口。

本脚本覆盖「平台售后报文 → 售后申请单」全链路：

| 场景 | 平台售后类型 | OMS 售后类型 | 断言要点 |
|---|---|---|---|
| `refund_only`（仅退款） | ONLY_REFUND | 1 | 建单 + 金额一致 + 订单关联 + 待审核 |
| `return_refund`（退货退款） | RETURN_GOODS | 2 | 同上 + 货物状态=已收货 |
| `defective_return`（质检不良） | RETURN_GOODS | 2 | 同上 + 原因码=商品质量问题 |
| 幂等（FR-01b） | — | — | 重复拉取不新增申请单（复用同一单） |

**金额按「分」比较**：平台报文是浮点数，直接比浮点会因精度误差误判。

用法：
    cd backend && .venv/bin/python -m app.scripts.aftersale_pull_e2e [--with-mock]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import text

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
MOCK_DIR = REPO_ROOT / "mocks" / "platform"

#: 场景矩阵（场景名, 中文名, 期望售后类型, 期望原因码, 期望货物状态）
SCENARIOS: list[tuple[str, str, int, str, int]] = [
    ("refund_only", "仅退款", 1, "WRONG_PURCHASE", 0),
    ("return_refund", "退货退款", 2, "SEVEN_NO_REASON", 2),
    ("defective_return", "质检不良退货", 2, "QUALITY_ISSUE", 2),
]

#: 相邻场景造单的最小间隔（秒）
#:   模拟器的售后报文 `modified` 只到**秒**精度 → 间隔不足 1 秒时两个场景的
#:   增量窗口会互相重叠（后一个场景会把前一个的售后报文一起拉进来）。
#:   间隔 ≥ 1.05s → 相邻场景的窗口按秒对齐后天然错开。
SCENARIO_GAP_SEC = 1.05


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def start_mock() -> tuple[subprocess.Popen, str]:
    """自起 mock-platform（随机端口 → 场景数据从零开始，可重复执行）"""
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


def _cents(value: Any) -> int:
    """金额 → 分（整数比较，规避浮点精度误差）"""
    return int(round(float(value or 0) * 100))


async def _clean_applies(session, refund_ids: list[str]) -> int:
    """清理售后申请（**先子表后父表** —— 顺序反了整段 rollback 且静默不删）"""
    if not refund_ids:
        return 0
    lst = ",".join("'" + rid.replace("'", "") + "'" for rid in refund_ids)
    n = 0
    for stmt in (
        "DELETE FROM oms_aftersale.aft_return_apply_log WHERE apply_id IN "
        f"(SELECT id FROM oms_aftersale.aft_return_apply "
        f"WHERE platform_aftersale_bn IN ({lst}))",
        "DELETE FROM oms_aftersale.aft_return_apply_item WHERE apply_id IN "
        f"(SELECT id FROM oms_aftersale.aft_return_apply "
        f"WHERE platform_aftersale_bn IN ({lst}))",
        f"DELETE FROM oms_aftersale.aft_return_apply "
        f"WHERE platform_aftersale_bn IN ({lst})",
    ):
        res = await session.execute(text(stmt))
        n += int(getattr(res, "rowcount", 0) or 0)
    await session.commit()
    return n


async def _platform_refund(
    gateway, win_start: datetime, win_end: datetime, tid: str
) -> dict | None:
    """从平台侧取本单对应的售后报文（拿期望值 + 幂等键 refund_id）"""
    res = await gateway.refund_list_get(
        shop_id=0,
        start_modified=win_start,
        end_modified=win_end,
        page_size=50,
        primary_bn=f"aftersale_pull_e2e:{tid}",
    )
    if not res.succ:
        return None
    for item in res.refunds:
        if str(item.get("tid") or "") == tid:
            return item
    return None


async def _scenario(
    ck,
    session,
    gateway,
    pull,
    aft_pull,
    shop_id: int,
    gateway_url: str,
    scenario: str,
    cn: str,
    want_type: int,
    want_reason: str,
    want_goods: int,
    refund_ids: list[str],
) -> None:
    """单场景：造单 → 拉单接入 → 售后拉取 → 断言 → 幂等复拉"""
    from sqlalchemy import select

    from app.models.aftersale import AftReturnApply, AftReturnApplyItem
    from app.models.order import OrdOrder, OrdOrderItem
    from app.modules.m6_aftersale.contract import ST_WAIT_AUDIT

    ck.section(f"场景 {cn}（{scenario}）")

    # ① 模拟器造单（带售后单）
    await asyncio.sleep(SCENARIO_GAP_SEC)
    t_before = datetime.now()
    made = await _mock(
        "POST",
        gateway_url,
        "/sim/orders",
        {"scenario": scenario, "count": 1, "with_refund": True},
    )
    t_after = datetime.now()
    tids = (made.get("data") or {}).get("tids") or []
    if not ck.check(f"{cn}：模拟器造单成功（带售后单）", bool(tids), f"tid={tids[:1]}"):
        return
    tid = str(tids[0])

    # 增量窗口按**秒**对齐（平台报文 modified 只到秒）
    win_start = t_before.replace(microsecond=0)
    win_end = (t_after + timedelta(seconds=1)).replace(microsecond=0)

    # ② 取平台售后报文（期望值 + 幂等键）
    refund = await _platform_refund(gateway, win_start, win_end, tid)
    if not ck.check(
        f"{cn}：平台售后报文已生成",
        refund is not None,
        f"refund_id={refund.get('refund_id') if refund else '-'}",
    ):
        return
    assert refund is not None  # mypy 收窄
    refund_id = str(refund.get("refund_id") or "")
    refund_ids.append(refund_id)

    # ③ 开头清（清掉同名残留 → 幂等断言可复现）
    await _clean_applies(session, [refund_id])

    # ④ 拉单接入 OMS（订单必须先在 OMS，售后单才有原单可关联）
    res = await pull.pull_single(shop_id, tid)
    if not ck.check(
        f"{cn}：拉单接入建单成功",
        bool(res.get("ok")) and res.get("outcome") == "created",
        f"outcome={res.get('outcome')} reason={res.get('reason', '')}",
    ):
        return
    order = await session.scalar(
        select(OrdOrder).where(
            OrdOrder.platform_order_bn == tid, OrdOrder.is_deleted == 0
        )
    )
    if not ck.check(f"{cn}：订单已落库", order is not None, f"tid={tid}"):
        return
    assert order is not None  # mypy 收窄
    order_item_ids = set(
        await session.scalars(
            select(OrdOrderItem.id).where(
                OrdOrderItem.order_id == order.id, OrdOrderItem.is_deleted == 0
            )
        )
    )

    # ⑤ 售后拉取（首次）
    stat = await aft_pull.pull_refunds(
        shop_id, start_modified=win_start, end_modified=win_end
    )
    ck.check(
        f"{cn}：售后拉取成功且无错误",
        bool(stat.get("ok")) and int(stat.get("errors") or 0) == 0,
        f"ok={stat.get('ok')} errors={stat.get('errors')} err_msg={stat.get('err_msg', '')}",
    )
    ck.check(
        f"{cn}：新建 1 张售后申请单",
        int(stat.get("created") or 0) == 1,
        f"created={stat.get('created')} total={stat.get('total')}",
    )
    ck.check(
        f"{cn}：无跳过 / 无待关联",
        int(stat.get("skipped") or 0) == 0
        and int(stat.get("pending_link") or 0) == 0,
        f"skipped={stat.get('skipped')} pending_link={stat.get('pending_link')}",
    )

    # ⑥ 断言申请单
    apply = await session.scalar(
        select(AftReturnApply).where(
            AftReturnApply.platform_aftersale_bn == refund_id
        )
    )
    if not ck.check(f"{cn}：售后申请单已落库", apply is not None, f"refund_id={refund_id}"):
        return
    assert apply is not None  # mypy 收窄
    ck.check(
        f"{cn}：售后类型正确",
        int(apply.aftersale_type) == want_type,
        f"aftersale_type={apply.aftersale_type} 期望={want_type}",
    )
    ck.check(
        f"{cn}：申请金额与平台报文一致（按分比较）",
        _cents(apply.apply_amount_customer) == _cents(refund.get("refund_amount")),
        f"apply={apply.apply_amount_customer} 平台={refund.get('refund_amount')}",
    )
    ck.check(
        f"{cn}：原因码映射正确",
        str(apply.reason_code) == want_reason,
        f"reason_code={apply.reason_code} 期望={want_reason}",
    )
    ck.check(
        f"{cn}：货物状态正确",
        int(apply.goods_status) == want_goods,
        f"goods_status={apply.goods_status} 期望={want_goods}",
    )
    ck.check(
        f"{cn}：状态为待审核（订单已关联）",
        int(apply.status) == ST_WAIT_AUDIT,
        f"status={apply.status}",
    )
    ck.check(
        f"{cn}：关联到 OMS 订单",
        int(apply.order_id) == int(order.id),
        f"apply.order_id={apply.order_id} order.id={order.id}",
    )
    apply_items = list(
        await session.scalars(
            select(AftReturnApplyItem).where(
                AftReturnApplyItem.apply_id == apply.id,
                AftReturnApplyItem.is_deleted == 0,
            )
        )
    )
    ck.check(
        f"{cn}：申请行关联真实订单行",
        len(apply_items) == 1
        and int(apply_items[0].order_item_id) in order_item_ids,
        f"申请行数={len(apply_items)} "
        f"order_item_id={apply_items[0].order_item_id if apply_items else '-'} "
        f"订单行={sorted(order_item_ids)}",
    )

    # ⑦ 幂等复拉（FR-01b）
    stat2 = await aft_pull.pull_refunds(
        shop_id, start_modified=win_start, end_modified=win_end
    )
    ck.check(
        f"{cn}：重复拉取不新增申请单（幂等 FR-01b）",
        int(stat2.get("created") or 0) == 0
        and int(stat2.get("idempotent") or 0) == 1,
        f"created={stat2.get('created')} idempotent={stat2.get('idempotent')}",
    )
    n_apply = len(
        (
            await session.scalars(
                select(AftReturnApply.id).where(
                    AftReturnApply.platform_aftersale_bn == refund_id
                )
            )
        ).all()
    )
    ck.check(f"{cn}：申请单仍只有 1 张", n_apply == 1, f"申请单数={n_apply}")


async def _run(gateway_url: str) -> int:
    from app.core.config import settings
    from app.core.db import AuthContext, SessionFactory, engine, set_auth_context
    from app.modules.m1_master.service.master import get_redis
    from app.modules.m6_aftersale.contract import AftersalePullService
    from app.modules.m7_integration.service.gateway import Gateway
    from app.modules.m7_integration.service.pull import PullService
    from app.scripts._checker import Checker
    from app.tools.simulation.scenario import ScenarioRunner

    # ⚠ 数据权限中间件 fail-closed：无 AuthContext 的 ORM 查询会被拒绝
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    ck = Checker("平台售后报文自动同步端到端（D05.01 FR-01a）")
    redis = await get_redis()
    if not gateway_url:
        gateway_url = settings.platform_gateway_url

    async with SessionFactory() as s:
        # ── 基础数据：货主 / 店铺 / 仓 / 物料 / 期初库存（订单行要 BOM 展开才可关联）
        runner = ScenarioRunner(s, redis, gateway_url)
        await runner.cleanup()
        ctx = await runner.prepare_master_data()
        await runner.opening_stock(ctx, qty=100)
        shop_id = int(ctx.get("shop_id") or 0)
        ck.check("基础数据：货主/店铺/仓/物料齐备", shop_id > 0, f"shop={shop_id}")

        gateway = Gateway(redis=redis)
        pull = PullService(s, gateway, redis)
        aft_pull = AftersalePullService(s, gateway, redis)

        refund_ids: list[str] = []
        for scenario, cn, want_type, want_reason, want_goods in SCENARIOS:
            await _scenario(
                ck,
                s,
                gateway,
                pull,
                aft_pull,
                shop_id,
                gateway_url,
                scenario,
                cn,
                want_type,
                want_reason,
                want_goods,
                refund_ids,
            )

        # ── 结尾清：售后申请（先子表后父表）→ 主数据 / 订单
        removed = await _clean_applies(s, refund_ids)
        ck.check("清理：本次产生的售后申请已删除", removed >= 3, f"删除行数={removed}")
        await runner.cleanup()

    await engine.dispose()
    print(ck.render())
    print(f"\n断言合计：{ck.total}（通过 {ck.passed} / 失败 {ck.failed}）")
    if ck.failed:
        print("❌ 平台售后报文自动同步端到端存在失败断言")
        return 1
    print("✅ 平台售后报文自动同步端到端全部通过")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="平台售后报文自动同步端到端")
    parser.add_argument("--gateway", default="", help="模拟器地址")
    parser.add_argument("--with-mock", action="store_true", help="自动启动 mock-platform")
    args = parser.parse_args()

    proc = None
    url = args.gateway
    if args.with_mock:
        proc, url = start_mock()
        print(f"[aftersale-pull] mock-platform 已启动：{url}")
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
