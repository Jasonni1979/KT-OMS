"""模型 ↔ DDL 列一致性核对（W6 起强制）

**为什么需要**：W5/W6 连续三轮踩同一个坑——模型按「其他域的基类习惯」写，
但 DDL 逐表不同（有的无 version、有的无 is_deleted、有的无 update_time）。
本脚本用 information_schema 逐表逐列比对 ORM 声明，**不一致即退出码 1**。

用法：
    cd backend && .venv/bin/python ../tools/check_model_ddl.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

#: 定位 backend 目录（脚本在 tools/ 下，app 包在 backend/ 下）
_BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(_BACKEND))

import pymysql  # noqa: E402

import app.models  # noqa: F401,E402  触发全部模型注册

#: 连接参数（支持环境变量覆盖 → CI 复演库可用）
DB = {
    "host": os.environ.get("KTOMS_MYSQL_HOST", "127.0.0.1"),
    "port": int(os.environ.get("KTOMS_MYSQL_PORT", "3308")),
    "user": os.environ.get("KTOMS_MYSQL_USER", "root"),
    "password": os.environ.get("KTOMS_MYSQL_PASSWORD", "ktoms_dev_2026"),
    "charset": "utf8mb4",
}


def ddl_columns(cur, schema: str, table: str) -> set[str]:
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s",
        (schema, table),
    )
    return {r[0] for r in cur.fetchall()}


def main() -> int:
    from app.models.base import Base

    conn = pymysql.connect(**DB)
    cur = conn.cursor()

    problems: list[str] = []
    checked = 0

    for table in sorted(Base.metadata.tables.values(), key=lambda t: t.name):
        schema = table.schema
        if not schema:
            continue
        name = table.name
        try:
            cols = ddl_columns(cur, schema, name)
        except Exception as e:  # pragma: no cover
            problems.append(f"[查询失败] {schema}.{name}: {e}")
            continue
        if not cols:
            problems.append(f"[表不存在] {schema}.{name}")
            continue
        checked += 1
        model_cols = {c.name for c in table.columns}
        extra = model_cols - cols
        missing = cols - model_cols
        if extra:
            problems.append(
                f"[模型多列] {schema}.{name}: {sorted(extra)}（DDL 无此列 → 写入必报错）"
            )
        if missing:
            problems.append(f"[模型缺列] {schema}.{name}: {sorted(missing)}")

    conn.close()

    print(f"核对表数：{checked}")
    if problems:
        print(f"\n发现 {len(problems)} 处不一致：")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    print("全部一致 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
