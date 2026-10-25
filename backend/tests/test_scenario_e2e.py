"""业务场景端到端回归测试（M1c-5）

把已完成的各域按一条真实业务链路跑通，验证跨模块契约衔接：
主数据 → 期初建账 → 平台下单 → 拉单接入 → 库存预占 → 出库单据 → 账实核对。

这是「避免返工」的门禁：任何跨模块契约（订单行 BOM 快照 ↔ 预占台账 ↔ 出库核销）
被改动导致衔接断裂时，本用例立即失败。
"""
import os
import socket
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
MOCK_DIR = REPO_ROOT / "mocks" / "platform"

pytestmark = pytest.mark.asyncio


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def mock_platform():
    """启动 mock-platform（独立进程，动态端口）"""
    port = _free_port()
    py = str(REPO_ROOT / "backend" / ".venv" / "bin" / "python")
    env = {**os.environ, "PYTHONPATH": str(MOCK_DIR)}
    proc = subprocess.Popen(
        [py, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(MOCK_DIR), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(60):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                break
        except OSError:
            time.sleep(0.25)
    else:
        proc.kill()
        pytest.skip("mock-platform 启动失败（跳过场景用例）")
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


async def test_business_scenario_end_to_end(mock_platform):
    """完整业务场景跑通（11 项断言全过）"""
    from app.services.scenario import run_scenario

    report = await run_scenario(mock_platform)
    print("\n" + report.render())
    failed = [s for s in report.steps if not s.passed]
    assert not failed, "场景断言失败: " + "; ".join(s.line() for s in failed)
    assert len(report.steps) >= 11


async def test_scenario_is_idempotent(mock_platform):
    """场景可重复执行（清理 → 重跑，结果一致）"""
    from app.services.scenario import run_scenario

    r1 = await run_scenario(mock_platform)
    r2 = await run_scenario(mock_platform)
    assert r1.ok, r1.render()
    assert r2.ok, r2.render()
    # 两次的关键实测值必须一致（库存回到同一基准）
    v1 = {s.step: s.values for s in r1.steps}
    v2 = {s.step: s.values for s in r2.steps}
    assert v1["7"]["store"] == v2["7"]["store"] == 98
    assert v1["7b"]["freeze"] == v2["7b"]["freeze"] == 0
