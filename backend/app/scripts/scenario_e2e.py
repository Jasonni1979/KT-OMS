"""业务场景端到端演示脚本（M1c-5）

一条命令跑通完整业务链路，验证各域契约衔接：

```bash
# 方式1：先起模拟器（另开终端）
cd KT-OMS/mocks/platform && ../../backend/.venv/bin/python -m uvicorn app.main:app --port 9000

# 方式2：本脚本自带模拟器（--with-mock）
cd KT-OMS/backend && .venv/bin/python -m app.scripts.scenario_e2e --with-mock
```

输出：逐步 PASS/FAIL 断言 + 汇总。退出码非 0 即失败（可作 CI 门禁）。
"""
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


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def start_mock() -> tuple[subprocess.Popen, str]:
    """启动 mock-platform 子进程，返回 (进程, base_url)"""
    port = _free_port()
    py = str(BACKEND_DIR / ".venv" / "bin" / "python")
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
        raise RuntimeError("mock-platform 启动失败")
    return proc, f"http://127.0.0.1:{port}"


async def _main(gateway_url: str) -> int:
    from app.tools.simulation.scenario import run_scenario

    report = await run_scenario(gateway_url)
    print("\n=== KT-OMS 业务场景端到端（模拟下单 → 拉单 → 预占 → 出库 → 记账）===\n")
    print(report.render())
    return 0 if report.ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="KT-OMS 业务场景端到端演示")
    parser.add_argument(
        "--gateway", default="", help="模拟器地址（默认取配置 platform_gateway_url）"
    )
    parser.add_argument(
        "--with-mock", action="store_true", help="自动启动 mock-platform 模拟器"
    )
    args = parser.parse_args()

    proc = None
    url = args.gateway
    if args.with_mock:
        proc, url = start_mock()
        print(f"[scenario] mock-platform 已启动：{url}")
    try:
        return asyncio.run(_main(url))
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    sys.exit(main())
