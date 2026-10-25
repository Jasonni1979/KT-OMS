"""系统级脚本护栏（D10.03 FR-04d 豁免通道的回归防线）

背景：M1a-3 上线 fail-closed 后，seed 脚本因无 AuthContext 崩溃 → CI 的
「seed → pytest」链路全断（admin 账户未建 → 所有需登录的用例失败）。
本文件把「脚本可在无上下文下独立跑通」固化为测试，防止后续新增脚本再次踩坑。
"""
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio

BACKEND = Path(__file__).resolve().parent.parent


def _run_script(module: str) -> subprocess.CompletedProcess:
    """以子进程跑脚本（独立进程 = 无 AuthContext，最接近 CI 场景）"""
    return subprocess.run(
        [sys.executable, "-m", module],
        cwd=BACKEND, capture_output=True, text=True, timeout=120,
        env={**__import__("os").environ, "PYTHONPATH": str(BACKEND)},
    )


@pytest.mark.parametrize("module", ["app.scripts.seed_org", "app.scripts.seed_auth"])
async def test_seed_scripts_run_without_auth_context(module):
    """seed 脚本必须能在无 AuthContext 下跑通（system_scope 豁免已加）"""
    r = _run_script(module)
    assert r.returncode == 0, f"{module} 失败:\nSTDOUT{r.stdout}\nSTDERR{r.stderr[-2000:]}"
    assert "完成" in r.stdout, f"{module} 未正常完成:\n{r.stdout[-500:]}"


async def test_seed_scripts_are_idempotent():
    """幂等：连续跑两次都成功（CI 每次重跑都要求）"""
    for module in ("app.scripts.seed_org", "app.scripts.seed_auth"):
        r1 = _run_script(module)
        r2 = _run_script(module)
        assert r1.returncode == 0 and r2.returncode == 0, f"{module} 非幂等"
        assert "幂等跳过" in r2.stdout, f"{module} 第二次未走幂等分支"
