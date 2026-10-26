#!/usr/bin/env python3
"""契约中心生成器 —— 从 DDL（information_schema.column_comment）生成枚举契约

**DDL 是权威源**（项目既定原则）。枚举值与中文标签只在 DDL 里维护一份，
本脚本把它编译成 `backend/app/contracts/enums.py`，杜绝代码侧手抄漂移。

用法：
    python3 tools/gen_contracts.py            # 生成
    python3 tools/gen_contracts.py --check    # 只校验是否同步（CI 用）
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys

_ROOT = pathlib.Path(__file__).resolve().parents[1]
#: 定位 backend 目录（脚本在 tools/ 下，app 包在 backend/ 下）
sys.path.insert(0, str(_ROOT / "backend"))

try:  # pymysql 仅「数据库模式」需要；DDL 文件模式（默认）零依赖
    import pymysql  # noqa: E402
except ImportError:  # pragma: no cover
    pymysql = None  # type: ignore[assignment]

ROOT = _ROOT
BACKEND = ROOT / "backend"
CONTRACTS = BACKEND / "app" / "contracts"
ENUMS_PY = CONTRACTS / "enums.py"
META_JSON = CONTRACTS / "_generated_meta.json"

#: 连接参数（与 tools/check_model_ddl.py 一致，支持环境变量覆盖 → CI 复演库可用）
DB = {
    "host": os.environ.get("KTOMS_MYSQL_HOST", "127.0.0.1"),
    "port": int(os.environ.get("KTOMS_MYSQL_PORT", "3308")),
    "user": os.environ.get("KTOMS_MYSQL_USER", "root"),
    "password": os.environ.get("KTOMS_MYSQL_PASSWORD", "ktoms_dev_2026"),
    "charset": "utf8mb4",
}

#: ⚠ 注释列用 **HEX()** 取字节，而不是直接取文本 ——
#:   information_schema 的列字符集是 utf8mb3，客户端 charset=utf8mb4 时
#:   服务端转换会产生**混合解码**（实测 "主键" → 'ä¸»é”®'：前 2 字节按
#:   latin-1、末 2 字节按 utf-8），pymysql 侧无法可靠还原。
#:   HEX 返回纯 ASCII → Python 侧按 utf-8 自行解码，零歧义。
SQL = (
    "SELECT CONCAT(table_schema,'|',table_name,'|',column_name,'|',column_type,'|',"
    "HEX(IFNULL(column_comment,''))) FROM information_schema.columns "
    "WHERE table_schema LIKE 'oms\\_%' AND column_comment != '' "
    "ORDER BY table_schema, table_name, ordinal_position"
)

#: 这些列不构成业务枚举（软删/版本/时间戳）
EXCLUDE_COL = {
    "is_deleted", "version", "id", "create_time", "update_time",
    "tenant_id", "update_by", "create_by",
}
EXCLUDE_COMMENT_PREFIX = ("软删标记",)
#: 字符串枚举的排除列（值含 `/` 但语义是引用路径/外键，不是枚举）
EXCLUDE_SUFFIX = ("_ref", "_id", "_path", "_url")

#: 注释里这些标记说明「不是枚举」，避免误解析
_NOT_ENUM_MARKERS = ("LFK", "FOREIGN KEY", "外键")


def strip_parens(text: str) -> str:
    """移除所有配对括号及其内容（括号内是补充说明，不是枚举值）"""
    out: list[str] = []
    depth = 0
    for ch in text:
        # ⚠ DDL 注释里 ASCII 与全角括号混用，两者都要处理
        if ch in ("(", "（"):
            depth += 1
        elif ch in (")", "）") and depth:
            depth -= 1
        elif depth == 0:
            out.append(ch)
    return "".join(out)


def clean_value(raw: str) -> str:
    """清洗枚举标签：截断到第一个 ; ； = 处，去掉首尾标点"""
    raw = raw.split("(")[0]
    raw = re.split(r"[;；]", raw)[0]
    if "=" in raw:
        raw = raw.split("=")[0]
    raw = raw.split(",")[0]
    return raw.strip().strip(";；,，.。:：").strip()


def parse_enum(comment: str) -> dict[int, str]:
    """从 COMMENT 解析 {值: 中文标签}

    例：`退款单状态(§4.1状态机): 1=待退款,2=退款中(平台受理打款),3=已退款(吸收态不回退)`
    → `{1: '待退款', 2: '退款中', 3: '已退款'}`
    """
    if any(mk in comment for mk in _NOT_ENUM_MARKERS):
        return {}
    text = strip_parens(comment)
    marks = list(re.finditer(r"(?<![\d.])(\d+)\s*=", text))
    if not marks:
        return {}
    result: dict[int, str] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        value = clean_value(text[m.end() : end])
        if not value:
            continue
        try:
            code = int(m.group(1))
        except ValueError:
            continue
        result.setdefault(code, value)
    return result


def parse_str_enum(comment: str) -> dict[str, str]:
    """解析**字符串枚举**（DDL 里 varchar 列的取值清单）

    DDL 里有三种写法，全部归一：
      1) `alarm告警/alloc_calc调拨测算/...`   （code + 中文标签）
      2) `create/update/delete/...`            （纯 code，标签兜底用 code）
      3) `string/int/decimal/...`              （同上）
    例：`批次阶段：alarm告警/alloc_calc调拨测算` →
        {'alarm': '告警', 'alloc_calc': '调拨测算'}

    判定从严：每个 token 必须形如 `code` 或 `code+中文`，
    否则视为「结构说明」而非枚举（如 `[{plugin(a/b/c)}]`）。
    """
    if any(mk in comment for mk in _NOT_ENUM_MARKERS):
        return {}
    text = strip_parens(comment)
    if "/" not in text:
        return {}
    # 前缀说明：首个 token 里若有冒号，取冒号后的部分
    head, _, rest = text.partition("/")
    # ⚠ DDL 注释里中文冒号「：」与 ASCII「:」混用，两者都要处理
    for sep in ("：", ":"):
        if sep in head:
            head = head.split(sep)[-1]
    tokens = [head] + rest.split("/")
    result: dict[str, str] = {}
    for tok in tokens:
        tok = tok.strip().strip(";；,，")
        if not tok:
            continue
        # ⚠ code 可能大写（RETRYABLE / FATAL / BIZ_REJECT）
        m = re.match(r"^([A-Za-z][A-Za-z0-9_]*)(.*)$", tok)
        if not m:
            return {}  # 含中文前缀或非法字符 → 不是字符串枚举
        code, label = m.group(1), m.group(2).strip()
        if label:
            # 标签部分必须以非 ASCII 开头（中文），否则说明 token 拼错了
            if label[0].isascii() or not any(ord(c) > 127 for c in label):
                return {}
        result[code] = label or code
    # ⚠ 阈值取 2：像 `BLOCK拦截/WARN提示` 这种只有 2 个值的枚举也要收录
    #   （audit_reason.level 就是这种，漏掉会导致门禁误报「未知值」）
    return result if len(result) >= 2 else {}


def decode_comment(raw: bytes) -> str:
    """把列注释的原始字节解码成中文（对「正常」与「双重编码」两种库都正确）

    ⚠ **开发库的 DDL 注释是双重编码的**（导入时字符集处理不当）：
       存储字节 = UTF-8(UTF-8("主键")) = E4 B8 BB E9 94 AE → C3A4 C2B8 C2BB ...
       直接按 utf-8 解码得到 mojibake（'ä¸»é\x94®'）。
    CI 复演库每次重新导入 DDL（字符集正确）→ 是正常 UTF-8。

    本函数对两种都正确：
      第一次解码 → 若字符码点 ≤255 说明原字节被当 latin-1 逐字节读过
      （双重编码特征）→ 取其单字节重新拼回原始字节再解；
      码点 >255 的字符（本就正确的多字节字符）→ 按 UTF-8 编码保留。
    """
    try:
        step1 = raw.decode("utf-8")
    except UnicodeDecodeError:
        return ""
    out = bytearray()
    for ch in step1:
        cp = ord(ch)
        if cp < 256:
            out.append(cp)  # 双重编码特征 → 取单字节
        else:
            out.extend(ch.encode("utf-8"))  # 本就正确 → 保留
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError:
        return step1


#: DDL SQL 文件目录（**权威源**：UTF-8 文本，不受库字符集影响）
DDL_DIR = ROOT / "docs" / "database" / "sql"

#: 列定义行：`  `col_name`  TYPE ... COMMENT '...'`（COMMENT 里的单引号已转义为 ''）
_COL_RE = re.compile(
    r"^\s*`?(?P<col>[A-Za-z_]\w*)`?\s+[A-Za-z].*?\bCOMMENT\s+"
    r"'(?P<cmt>(?:[^']|'')*)'",
    re.M,
)
#: 建表语句：`CREATE TABLE ord_order (` —— ⚠ **DDL 文件里不带 schema 前缀**，
#:   schema 由文件头的 `USE oms_xxx;` 决定
_CREATE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?`?(?P<table>\w+)`?\s*\(",
    re.I,
)
#: 文件头的 schema：`USE `oms_order`;`
_USE_RE = re.compile(r"^\s*USE\s+`?(?P<schema>\w+)`?\s*;", re.I | re.M)


def fetch_rows_from_ddl() -> list[tuple[str, str, str, str, str]]:
    """从 **DDL SQL 文件** 提取列注释

    ⚠ **为什么不用 information_schema**：
      开发库的 DDL 注释是**双重编码且部分不可逆损坏**的
      （导入时字符集处理不当：utf8mb3→utf8mb4 转换把 0x94 换成了 U+201D），
      从库里读出来的中文已经是坏的，且**无法还原**。
      DDL 文件本身是 UTF-8 源文件 —— 才是真正的权威源。
      附带好处：本地与 CI 结果完全一致（不依赖库状态）。
    """
    rows: list[tuple[str, str, str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for f in sorted(DDL_DIR.glob("DB-*.sql")):
        text = f.read_text(encoding="utf-8")
        # schema 来自文件头的 USE 语句
        um = _USE_RE.search(text)
        if not um:
            continue
        schema = um.group("schema")
        # 按 CREATE TABLE 切块，逐块匹配列定义
        marks = list(_CREATE_RE.finditer(text))
        for i, m in enumerate(marks):
            table = m.group("table")
            end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
            block = text[m.end() : end]
            for cm in _COL_RE.finditer(block):
                key = (schema, table, cm.group("col"))
                if key in seen:
                    continue  # ⚠ 同表在多个 DDL 文件里重复定义 → 去重
                seen.add(key)
                cmt = cm.group("cmt").replace("''", "'")
                rows.append((schema, table, cm.group("col"), "", cmt))
    return rows


def fetch_rows() -> list[tuple[str, str, str, str, str]]:
    """直连 MySQL 读取列注释（与 tools/check_model_ddl.py 同一套连接参数）

    ⚠ **不要用 `docker exec mysql --default-character-set=utf8mb4`**：
      容器内 mysql CLI 在管道（非 tty）模式下会做一次额外的字符集转换，
      导致中文被双重编码成乱码（实测：加参数 → "å¾…"，不加 → 正常）。
      直连 pymysql 没有这个问题，且 GitHub CI 也没有 docker。
    """
    if pymysql is None:  # pragma: no cover
        print("❌ 数据库模式需要 pymysql（pip install pymysql）", file=sys.stderr)
        sys.exit(2)
    conn = pymysql.connect(**DB)
    cur = conn.cursor()
    try:
        cur.execute(SQL)
        raw = cur.fetchall()
    finally:
        cur.close()
        conn.close()
    rows = []
    for r in raw:
        # ⚠ SQL 用 CONCAT 把 5 个字段拼成**一个字符串**（用 `|` 分隔），
        #   不是 5 列 —— 必须按 `|` 拆开，否则整批被过滤（返回 0 行）
        parts = str(r[0]).split("|", 4)
        if len(parts) == 5:
            try:
                comment = decode_comment(bytes.fromhex(parts[4]))
            except ValueError:
                comment = ""  # 非 hex 内容 → 该列跳过
            rows.append((parts[0], parts[1], parts[2], parts[3], comment))
    return rows


def const_name(schema: str, table: str, column: str, used: set[str]) -> str:
    """生成常量名：表名_列名（大写）；冲突时加 schema 前缀"""
    base = f"{table}_{column}".upper()
    if base not in used:
        used.add(base)
        return base
    full = f"{schema}_{base}"
    n = 2
    while full in used:
        full = f"{schema}_{base}_{n}"
        n += 1
    used.add(full)
    return full


def build() -> tuple[str, dict]:
    rows = fetch_rows_from_ddl()
    enums: list[tuple[str, str, str, dict[int, str]]] = []
    str_enums: list[tuple[str, str, str, dict[str, str]]] = []
    for schema, table, column, ctype, comment in rows:
        if column in EXCLUDE_COL or comment.startswith(EXCLUDE_COMMENT_PREFIX):
            continue
        values = parse_enum(comment)
        if len(values) >= 2:
            enums.append((schema, table, column, values))
            continue
        if column.endswith(EXCLUDE_SUFFIX):
            continue
        svals = parse_str_enum(comment)
        # 阈值与 parse_str_enum 内部一致（≥2）—— 两处不一致会漏收录
        if len(svals) >= 2:
            str_enums.append((schema, table, column, svals))

    used: set[str] = set()
    body: list[str] = []
    index: list[str] = []
    meta_cols: list[dict] = []

    cur_schema = ""
    for schema, table, column, values in enums:
        if schema != cur_schema:
            cur_schema = schema
            body.append("")
            body.append(f"# ==================== {schema} ====================")
            body.append("")
        name = const_name(schema, table, column, used)
        body.append(f"{name}: Final[dict[int, str]] = {{")
        for code in sorted(values):
            body.append(f"    {code}: {values[code]!r},")
        body.append("}")
        body.append(f"{name}_VALUES: Final[frozenset[int]] = frozenset({name})")
        body.append("")
        index.append(f'    "{schema}.{table}.{column}": {name},')
        meta_cols.append(
            {
                "column": f"{schema}.{table}.{column}",
                "const": name,
                "type": ctype,
                "kind": "int",
                "values": {str(k): v for k, v in sorted(values.items())},
            }
        )

    header = '''# ruff: noqa: E501
"""枚举契约 —— **自动生成，请勿手工编辑**

生成源：`information_schema.columns.column_comment`（**DDL 是权威源**）
生成器：`tools/gen_contracts.py`
重新生成：`python3 tools/gen_contracts.py`
校验同步：`python3 tools/check_contract_ddl.py`

**为什么存在**：枚举值与中文标签过去散落在 39 个 service 里各抄一份，
DDL 变更时必然漂移（W9 已实测：换货状态机缺边、批次阶段表缺边）。
本文件把「唯一一份」放在 DDL 里，代码侧只允许引用本文件。

⚠ 生成列（VIRTUAL/STORED GENERATED）不参与枚举 —— 派生值，非业务写入。
"""
from __future__ import annotations

from typing import Any, Final
'''

    # ---- 字符串枚举 ----
    if str_enums:
        body.append("")
        body.append("# ==================== 字符串枚举（varchar 取值清单） ====================")
        body.append("")
        for schema, table, column, values in str_enums:
            if schema != cur_schema:
                cur_schema = schema
                body.append(f"# ---- {schema} ----")
                body.append("")
            name = const_name(schema, table, column, used)
            body.append(f"{name}: Final[dict[str, str]] = {{")
            for code in sorted(values):
                body.append(f"    {code!r}: {values[code]!r},")
            body.append("}")
            body.append(f"{name}_VALUES: Final[frozenset[str]] = frozenset({name})")
            body.append("")
            index.append(f'    "{schema}.{table}.{column}": {name},')
            meta_cols.append(
                {
                    "column": f"{schema}.{table}.{column}",
                    "const": name,
                    "type": ctype,
                    "kind": "str",
                    "values": values,
                }
            )

    content = (
        header
        + "\n"
        + "\n".join(body).rstrip()
        + "\n\n#: 全部枚举列索引：`schema.table.column` → 值标签字典\n"
        + "ENUM_COLUMNS: Final[dict[str, dict[Any, str]]] = {\n"
        + "\n".join(index)
        + "\n}\n"
        + "\n#: 反查索引：`schema.table.column` → 中文标签 → 值\n"
        + "#:   （标签写错会在查表时立刻 KeyError，而不是静默取到错误状态码）\n"
        + "ENUM_BY_LABEL: Final[dict[str, dict[str, int]]] = {\n"
        + "\n".join(
            f'    "{c["column"]}": {{v: k for k, v in {c["const"]}.items()}},'
            for c in meta_cols
            if c.get("kind") == "int"
        )
        + "\n}\n"
    )

    meta = {"columns": meta_cols, "count": len(meta_cols)}
    return content, meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验是否同步（不写文件）")
    args = ap.parse_args()

    content, meta = build()

    if args.check:
        if not ENUMS_PY.exists():
            print("❌ contracts/enums.py 不存在，请先运行 tools/gen_contracts.py")
            return 1
        cur = ENUMS_PY.read_text(encoding="utf-8")
        if cur != content:
            print("❌ contracts/enums.py 与 DDL 不同步 —— 请运行 `python3 tools/gen_contracts.py`")
            return 1
        print(f"✓ contracts/enums.py 与 DDL 同步（{meta['count']} 个枚举列）")
        return 0

    CONTRACTS.mkdir(parents=True, exist_ok=True)
    ENUMS_PY.write_text(content, encoding="utf-8")
    META_JSON.write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"✓ 已生成 {ENUMS_PY.relative_to(ROOT)}（{meta['count']} 个枚举列）")
    print(f"✓ 已生成 {META_JSON.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
