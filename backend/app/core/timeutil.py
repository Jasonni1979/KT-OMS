"""时间基准工具（统一 UTC）

## 为什么必须统一
MySQL `DATETIME` **不带时区**。若某处写入用本地时区、另一处比较用另一个时区
（或 DB 容器时区与应用主机时区不同），就会出现：
- 锁定中的账户被判为「已过期」→ 自动放行（**越权风险**）
- SLA / 账龄 / 超时判定错乱（少算或多算时长）

因此**所有跨域时间比较统一用 UTC**（naive，秒级精度足够）。

## 用法
```python
from app.core.timeutil import utcnow

now = utcnow()                      # UTC naive，与 DB 的 DATETIME 同基准
deadline = now + timedelta(hours=24)
```

写入 DB 时直接写 `utcnow()`，比较时也用 `utcnow()` —— 两侧同基准，
与 DB 服务器时区无关。
"""
from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """当前 UTC 时间（naive datetime）

    返回值与 MySQL `DATETIME` 同基准（无时区信息的 UTC），
    可直接写入 DB 并与 DB 读出的值比较。
    """
    return datetime.now(UTC).replace(tzinfo=None)


def to_utc(dt: datetime | None) -> datetime | None:
    """把带时区的 datetime 转成 UTC naive；naive 的按已是 UTC 处理"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(UTC).replace(tzinfo=None)
