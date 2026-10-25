"""E2E 脚本的模拟器进程控制（公共）

CI 与本地都需要「跑 E2E 时自带模拟器」的能力：
- 本地：`deploy/ci-local-rehearsal.sh` 自起两个模拟器（9000 平台 / 9001 WMS）
- GitHub Actions：runner 上没有常驻模拟器，每个 E2E job 需自行拉起

统一放在这里，避免每个脚本各抄一份 start_mock。

用法（以 E2E 脚本为例）：
    from app.scripts._mockctl import start_mock, MOCK_KINDS

    proc, url = start_mock("wms")          # 分配空闲端口并起模拟器
    os.environ["MOCK_WMS_ENDPOINT"] = url   # 告知脚本模拟器地址
    ...
    finally:
        stop_mock(proc)
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent

#: 模拟器种类 → (仓库相对目录, 默认端口, 环境变量名)
MOCK_KINDS: dict[str, tuple[str, int, str]] = {
    "platform": ("mocks/platform", 9000, "MOCK_PLATFORM_ENDPOINT"),
    "wms": ("mocks/wms", 9001, "MOCK_WMS_ENDPOINT"),
}


def _free_port() -> int:
    """取一个空闲端口（避免与已有模拟器/服务冲突）"""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def start_mock(
    kind: str, port: int | None = None
) -> tuple[subprocess.Popen | None, str]:
    """启动模拟器子进程，返回 (进程, base_url)

    kind ∈ MOCK_KINDS 的键（platform / wms）。
    端口默认取该模拟器的标准端口；端口已被健康的模拟器占用时**直接复用**
    （返回 proc=None，调用方无需 stop）。

    返回 (进程, base_url)：进程为 None 表示复用了已有实例。
    """
    if kind not in MOCK_KINDS:
        raise ValueError(f"未知模拟器类型: {kind}（可选: {list(MOCK_KINDS)}）")
    rel_dir, default_port, env_name = MOCK_KINDS[kind]
    mock_dir = REPO_ROOT / rel_dir
    if not mock_dir.exists():
        raise RuntimeError(f"模拟器目录不存在: {mock_dir}")

    chosen = port or default_port
    # ⚠ **必须用标准端口**（9000 平台 / 9001 WMS）：
    #   OMS 侧调模拟器的地址来自**数据库配置**（binding.endpoint / platform_config），
    #   指向标准端口。若这里另起随机端口，OMS 打的仍是标准端口上的另一个实例
    #   （或根本没人监听）→ 断言查的模拟器 ≠ 收件方 → 假失败。
    if _port_busy(chosen):
        # 端口已被占用：若该端口上的模拟器活着 → 直接复用（本地开发常驻实例）
        if _health_ok(chosen):
            url = f"http://127.0.0.1:{chosen}"
            os.environ[env_name] = url
            return None, url  # proc=None → 调用方无需 stop
        raise RuntimeError(
            f"端口 {chosen} 被占用但不是健康的 {kind} 模拟器；"
            f"请先释放该端口（本地可用 MOCK_WMS_ENDPOINT / MOCK_PLATFORM_ENDPOINT 指定其他地址）"
        )
    py = str(BACKEND_DIR / ".venv" / "bin" / "python")
    if not Path(py).exists():
        py = sys.executable  # CI 上用 uv run 的解释器
    env = {**os.environ, "PYTHONPATH": str(mock_dir)}
    proc = subprocess.Popen(
        [
            py,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(chosen),
        ],
        cwd=str(mock_dir),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(80):
        if proc.poll() is not None:
            raise RuntimeError(f"{kind} 模拟器启动即退出（端口 {chosen}）")
        try:
            with socket.create_connection(("127.0.0.1", chosen), timeout=1):
                break
        except OSError:
            time.sleep(0.25)
    else:
        proc.kill()
        raise RuntimeError(f"{kind} 模拟器启动超时（端口 {chosen}）")
    url = f"http://127.0.0.1:{chosen}"
    os.environ[env_name] = url
    return proc, url


def _health_ok(port: int) -> bool:
    """该端口上是否跑着健康的模拟器（/healthz 返回 up）"""
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/healthz", timeout=2
        ) as r:
            data = json.loads(r.read().decode())
        return data.get("status") == "up"
    except Exception:
        return False


def _port_busy(port: int) -> bool:
    """端口是否已被占用（避免误杀已有服务）"""
    with socket.socket() as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


def stop_mock(proc: subprocess.Popen | None) -> None:
    """停止模拟器子进程（幂等）"""
    if proc is None:
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    except Exception:
        pass
