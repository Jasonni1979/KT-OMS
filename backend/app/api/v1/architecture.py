"""架构契约 API —— 让「模块契约」在界面上可见

**数据源**（全部是仓库里的权威文件，不额外维护副本）：
| 数据 | 来源 |
|---|---|
| 模块职责 / 对外接口 / 允许调用 / 禁止 / 待收口点 | `docs/架构/modules/M*-contract.md` |
| 可写表清单 / 外部依赖 | `docs/架构/modules/M*-tables.yaml` |
| 枚举契约（771 列） | `backend/app/contracts/_generated_meta.json` |

**为什么单独开这个域**：契约是 P0 建立的「单一来源」，但它此前只存在于
Markdown 与生成文件里 —— 开发者要读文件才知道某个模块能对外做什么。
把它做成 API + 页面，契约就成了**界面上一眼可见的东西**，
AI agent 接手时也能先看页面而不是 grep 全库。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter()

#: 仓库根（backend/app/api/v1/architecture.py → parents[4]）
_ROOT = Path(__file__).resolve().parents[4]
_CONTRACT_DIR = _ROOT / "docs" / "架构" / "modules"
_META_JSON = _ROOT / "backend" / "app" / "contracts" / "_generated_meta.json"

#: 契约表摘要（元信息）
_MODULE_ORDER = ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8"]

_SECTION_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$", re.M)
_ROW_RE = re.compile(r"^\|(?P<body>.+)\|\s*$", re.M)
_BULLET_RE = re.compile(r"^-\s+(?P<item>.+?)\s*$", re.M)
_CODE_RE = re.compile(r"`([^`]+)`")


def _sections(md: str) -> dict[str, str]:
    """把 markdown 按 `## 标题` 切段"""
    out: dict[str, str] = {}
    marks = list(_SECTION_RE.finditer(md))
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(md)
        out[m.group("title").strip()] = md[m.end() : end]
    return out


def _table(section: str) -> list[list[str]]:
    """解析 markdown 表格（跳过表头与分隔行），单元格内的反引号内容去壳"""
    rows: list[list[str]] = []
    for line in section.splitlines():
        m = _ROW_RE.match(line.strip())
        if not m:
            continue
        cells = [c.strip() for c in m.group("body").split("|")]
        if len(cells) < 2:
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue  # 分隔行
        if cells[0] in ("接口", "下游模块", "schema", "参数"):
            continue  # 表头
        rows.append(cells)
    return rows


def _bullets(section: str) -> list[str]:
    return [m.group("item").strip() for m in _BULLET_RE.finditer(section)]


def _meta_value(md: str, key: str) -> str:
    m = re.search(rf"\*\*{key}\*\*[：:]\s*(.+)", md)
    return m.group(1).strip() if m else ""


def _load_modules() -> list[dict[str, Any]]:
    """读取并解析 8 份模块契约"""
    modules: list[dict[str, Any]] = []
    if not _CONTRACT_DIR.exists():
        return modules
    for code in _MODULE_ORDER:
        md_files = sorted(_CONTRACT_DIR.glob(f"{code}-*-contract.md"))
        if not md_files:
            continue
        md = md_files[0].read_text(encoding="utf-8")
        yaml_files = sorted(_CONTRACT_DIR.glob(f"{code}-*-tables.yaml"))
        tables: dict[str, Any] = {}
        if yaml_files:
            tables = yaml.safe_load(yaml_files[0].read_text(encoding="utf-8")) or {}

        sec = _sections(md)
        ro = _table(sec.get("对外只读接口（跨模块可自由调用）", ""))
        rw = _table(sec.get("对外写接口（跨模块调用须在本模块登记）", ""))
        deps = _table(sec.get("允许的跨模块调用", ""))
        write_rows = _table(sec.get("可写表", ""))
        slug = tables.get("slug", "")
        files = _service_files(slug) if slug else []

        modules.append(
            {
                "code": code,
                "slug": slug,
                "title": md.splitlines()[0].lstrip("# ").strip() if md else "",
                "duty": _meta_value(md, "职责"),
                "services": [
                    s.strip()
                    for s in _meta_value(md, "收编 service").split(",")
                    if s.strip()
                ],
                "service_files": files,
                "service_file_count": len(files),
                "module_lines": sum(f["lines"] for f in files),
                "max_file_lines": max((f["lines"] for f in files), default=0),
                "meta": _meta_value(md, "目录"),
                "write_tables": tables.get("write", []) or [],
                "forbidden_write": tables.get("forbidden_write", []) or [],
                "external": tables.get("external", []) or [],
                "read_apis": [{"name": r[0], "desc": r[1] if len(r) > 1 else ""} for r in ro],
                "write_apis": [{"name": r[0], "desc": r[1] if len(r) > 1 else ""} for r in rw],
                "allowed_deps": [
                    {"module": r[0], "access": r[1] if len(r) > 1 else "", "note": r[2] if len(r) > 2 else ""}
                    for r in deps
                ],
                "forbidden": _bullets(sec.get("禁止", "")),
                "todos": _bullets(sec.get("已知待收口点", "")),
                "table_summary": [
                    {"schema": r[0], "count": r[1] if len(r) > 1 else "0"}
                    for r in write_rows
                ],
            }
        )
    return modules


def _drift_count() -> int:
    """真实跑一次契约门禁，返回漂移数（不硬编码）

    复用 `tools/check_contract_ddl.py` 的检查逻辑（同一份判据，
    不在这里重复实现 —— 避免两处规则漂移）。
    """
    import sys

    tools_dir = str(_ROOT / "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    try:
        import check_contract_ddl as CCD  # type: ignore[import-not-found]
    except Exception:
        return -1  # 门禁脚本不可用 → 未知
    try:
        enums = CCD.load_enums()
        code_enums = CCD.collect_code_enums()
        all_values: set[str] = set()
        for ev in enums.values():
            all_values |= {str(k) for k in ev}
        drift = 0
        for e in code_enums:
            if e["kind"] != "label_map" or len(e["values"]) < 2:
                continue
            if e["name"] in CCD.ALLOW_UNTRACKED:
                continue
            vals = [v for v in e["values"].values() if v]
            if not vals:
                continue
            cn = sum(1 for v in vals if any(ord(c) > 127 for c in v))
            if cn / len(vals) < 0.5:
                continue  # 非标签映射表（错误码/字段名映射）→ 不比对
            if {str(k) for k in e["values"]} - all_values:
                drift += 1
        return drift
    except Exception:
        return -1


def _load_enum_meta() -> list[dict[str, Any]]:
    if not _META_JSON.exists():
        return []
    data = json.loads(_META_JSON.read_text(encoding="utf-8"))
    return list(data.get("columns", []))


#: 模块 service 目录（backend/app/modules/<slug>/service/）
_MODULES_DIR = _ROOT / "backend" / "app" / "modules"

#: 文件角色判定
_KIND_CODES_SUFFIX = ("_codes.py", "_models.py", "_states.py", "_constants.py")


def _service_files(slug: str) -> list[dict[str, Any]]:
    """实时扫描模块 service 目录 → 文件清单（行数 + 角色）

    **为什么要实时**：P3 把 11 个超大 service 拆成了 40+ 个小文件，
    契约文档里的「service N 个 / 代码行 M」会立刻过时。
    契约页与文档都应反映**当下**的真实结构，而不是手工维护的数字。
    """
    import ast

    svc_dir = _MODULES_DIR / slug / "service"
    if not svc_dir.exists():
        return []
    out: list[dict[str, Any]] = []
    for f in sorted(svc_dir.glob("*.py")):
        if f.name == "__init__.py":
            continue
        src = f.read_text(encoding="utf-8")
        lines = len(src.splitlines())
        kind = "main"
        try:
            tree = ast.parse(src)
        except SyntaxError:
            tree = None
        if tree is not None:
            classes = [
                n.name for n in tree.body if isinstance(n, ast.ClassDef)
            ]
            has_public_class = any(not c.startswith("_") for c in classes)
            all_mixin = bool(classes) and all(c.endswith("Mixin") for c in classes)
            if all_mixin:
                kind = "mixin"
            elif not has_public_class:
                kind = "codes"
        if kind == "main" and f.name.endswith(_KIND_CODES_SUFFIX):
            kind = "codes"
        out.append({"name": f.stem, "lines": lines, "kind": kind})
    return out


@router.get("/architecture/contracts", summary="模块契约总览")
async def contracts() -> JSONResponse:
    """8 个模块的契约（职责 / 可写表 / 对外接口 / 允许调用 / 禁止 / 待收口）"""
    modules = _load_modules()
    enums = _load_enum_meta()

    by_schema: dict[str, int] = {}
    kind_count: dict[str, int] = {}
    for c in enums:
        col = c.get("column", "")
        schema = col.split(".")[0] if "." in col else "?"
        by_schema[schema] = by_schema.get(schema, 0) + 1
        kind = c.get("kind", "int")
        kind_count[kind] = kind_count.get(kind, 0) + 1

    total_tables = sum(len(m["write_tables"]) for m in modules)
    total_files = sum(m["service_file_count"] for m in modules)
    max_file = max(
        (
            {"module": m["code"], "name": f["name"], "lines": f["lines"]}
            for m in modules
            for f in m["service_files"]
        ),
        key=lambda x: x["lines"],
        default={"module": "", "name": "", "lines": 0},
    )
    return JSONResponse(
        {
            "code": 0,
            "message": "ok",
            "data": {
                "module_count": len(modules),
                "enum_count": len(enums),
                "enum_by_schema": [
                    {"schema": k, "count": v} for k, v in sorted(by_schema.items(), key=lambda x: -x[1])
                ],
                "enum_by_kind": kind_count,
                "total_write_tables": total_tables,
                "total_service_files": total_files,
                "total_module_lines": sum(m["module_lines"] for m in modules),
                "largest_service_file": max_file,
                "drift_count": _drift_count(),
                "modules": modules,
            },
        }
    )


@router.get("/architecture/enums", summary="枚举契约清单")
async def enums(q: str | None = None, limit: int = 200) -> JSONResponse:
    """枚举列清单（可按关键字搜索 column / 常量名）"""
    all_cols = _load_enum_meta()
    if q:
        kw = q.strip().lower()
        all_cols = [
            c for c in all_cols
            if kw in c.get("column", "").lower() or kw in c.get("const", "").lower()
        ]
    return JSONResponse(
        {
            "code": 0,
            "message": "ok",
            "data": {
                "total": len(all_cols),
                "items": [
                    {
                        "column": c.get("column", ""),
                        "const": c.get("const", ""),
                        "kind": c.get("kind", "int"),
                        "values": c.get("values", {}),
                    }
                    for c in all_cols[:limit]
                ],
            },
        }
    )


@router.get("/architecture/contracts/{module_code}", summary="单模块契约详情")
async def contract_detail(module_code: str) -> JSONResponse:
    """单个模块的完整契约（含全部可写表名）"""
    for m in _load_modules():
        if m["code"].lower() == module_code.lower():
            return JSONResponse({"code": 0, "message": "ok", "data": m})
    raise HTTPException(status_code=404, detail=f"未知模块：{module_code}")
