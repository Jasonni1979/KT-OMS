"""常驻服务守护启动器（double-fork，规避 WorkBuddy 会话回收）

用法：
    python3 tools/daemon.py <pidfile> <logfile> <cmd...>
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    pidfile = sys.argv[1]
    logfile = sys.argv[2]
    cmd = sys.argv[3:]

    # 第一次 fork
    if os.fork() > 0:
        os._exit(0)

    os.setsid()  # 脱离会话
    # 第二次 fork
    if os.fork() > 0:
        os._exit(0)

    # 重定向 stdio
    fd = os.open(os.devnull, os.O_RDONLY)
    os.dup2(fd, 0)
    out = os.open(logfile, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(out, 1)
    os.dup2(out, 2)

    with open(pidfile, "w") as f:
        f.write(str(os.getpid()))

    os.execvp(cmd[0], cmd)
    return 1


if __name__ == "__main__":
    sys.exit(main())
