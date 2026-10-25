#!/usr/bin/env python3
"""扫描/修复全库中文 mojibake（双重编码乱码）

**背景**：M0.1 的 DDL 导入用 `mysql` CLI 管道执行，客户端字符集为 cp1252/latin1，
把 SQL 文件里的 UTF-8 字节误解码后按 UTF-8 重新编码写入 → 中文变成乱码
（如「采购入库」→「é‡‡è´­å…¥åº"」）。
- 源头：deploy/init-db.sh 未显式指定 --default-character-set=utf8mb4
- 逆向变换：stored.encode('cp1252').decode('utf-8') 可无损还原

用法：
    python3 tools/scan_mojibake.py            # 只报告
    python3 tools/scan_mojibake.py --fix      # 报告 + 修复（逐行 UPDATE）

注意：**必须用 pymysql 直连**，mysql CLI 自身字符集会让检测失真。
"""
from __future__ import annotations

import re
import sys

import pymysql

DB = dict(host="127.0.0.1", port=3308, user="root", password="ktoms_dev_2026", charset="utf8mb4")

#: cp1252 误解码特征字符（西欧字母 + 排版符号区）
MOJI_HINT = re.compile(r"[ÃÂâäåæçèéêëìíîïðñòóôõö÷øùúûüýþÿ¡¢£¤¥¦§¨©ª«¬®¯°±²³´µ¶·¸¹º»¼½¾¿×÷]")

#: cp1252 反查表（含 U+0080-U+009F 中 cp1252 有定义的 0x80-0x9F）
_CP1252_REVERSE: dict[str, int] = {}
for _b in range(256):
    try:
        _ch = bytes([_b]).decode("cp1252")
    except UnicodeDecodeError:
        continue  # cp1252 未定义字节（0x81/0x8D/0x8F/0x90/0x9D）
    _CP1252_REVERSE[_ch] = _b


def _to_bytes(val: str) -> bytes | None:
    """把误解码后的字符串还原成原始字节。

    MySQL 客户端在 cp1252 下解码：cp1252 有定义的字节 → 对应排版字符；
    cp1252 未定义的 5 个字节 → 由 MySQL 替换/透传为 latin-1 控制字符（U+0081 等）。
    因此还原时逐字符查表：cp1252 优先，其次按 latin-1 码位直取。
    """
    out = bytearray()
    for ch in val:
        b = _CP1252_REVERSE.get(ch)
        if b is None:
            o = ord(ch)
            if o < 256:
                b = o
            else:
                return None
        out.append(b)
    return bytes(out)


def conn():
    return pymysql.connect(**DB)


def text_columns(c) -> list[tuple[str, str, str]]:
    with c.cursor() as cur:
        cur.execute(
            "SELECT table_schema, table_name, column_name FROM information_schema.columns "
            "WHERE table_schema LIKE 'oms%' AND data_type IN "
            "('varchar','char','text','mediumtext','longtext')"
        )
        return [(r[0], r[1], r[2]) for r in cur.fetchall()]


def repair(val: str) -> str | None:
    """cp1252/latin-1 误解码的逆向还原（最多两层）"""
    cur = val
    for _ in range(2):
        raw = _to_bytes(cur)
        if raw is None:
            break
        try:
            fixed = raw.decode("utf-8")
        except UnicodeDecodeError:
            break
        if fixed == cur:
            break
        cur = fixed
        if not MOJI_HINT.search(cur):
            return cur
    return cur if cur != val else None


def scan() -> list[dict]:
    c = conn()
    hits: list[dict] = []
    try:
        for schema, table, col in text_columns(c):
            with c.cursor() as cur:
                try:
                    cur.execute(
                        f"SELECT id, `{col}` FROM `{schema}`.`{table}` "
                        f"WHERE `{col}` IS NOT NULL AND `{col}` <> '' LIMIT 5000"
                    )
                    rows = cur.fetchall()
                except pymysql.err.Error:
                    continue
            bad, samples = 0, []
            for _pk, val in rows:
                if not isinstance(val, str) or not val:
                    continue
                if MOJI_HINT.search(val) and repair(val):
                    bad += 1
                    if len(samples) < 3:
                        samples.append(val[:40])
            if bad:
                hits.append(
                    {"schema": schema, "table": table, "column": col,
                     "bad": bad, "total": len(rows), "samples": samples}
                )
    finally:
        c.close()
    return hits


def fix_all(hits: list[dict]) -> int:
    c = conn()
    total = 0
    try:
        for h in hits:
            schema, table, col = h["schema"], h["table"], h["column"]
            with c.cursor() as cur:
                cur.execute(
                    f"SELECT id, `{col}` FROM `{schema}`.`{table}` "
                    f"WHERE `{col}` IS NOT NULL AND `{col}` <> ''"
                )
                rows = cur.fetchall()
                n = 0
                for pk, val in rows:
                    if not isinstance(val, str) or not val:
                        continue
                    fixed = repair(val)
                    if not fixed or fixed == val:
                        continue
                    cur.execute(
                        f"UPDATE `{schema}`.`{table}` SET `{col}`=%s WHERE id=%s", (fixed, pk)
                    )
                    n += 1
                c.commit()
            total += n
            print(f"  {schema}.{table}.{col}: 修复 {n} 行")
    finally:
        c.close()
    return total


def main() -> int:
    hits = scan()
    total_bad = sum(h["bad"] for h in hits)
    print(f"=== mojibake 扫描：{len(hits)} 个列命中，共 {total_bad} 行 ===\n")
    for h in hits:
        print(f"{h['schema']}.{h['table']}.{h['column']}: {h['bad']}/{h['total']} 行")
        for s in h["samples"]:
            print(f"    样例: {s!r} → {repair(s)!r}")

    if "--fix" in sys.argv and hits:
        print("\n>>> 开始修复…")
        n = fix_all(hits)
        print(f"\n>>> 修复 {n} 行。建议再跑一次扫描确认归零。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
