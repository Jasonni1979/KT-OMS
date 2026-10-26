#!/usr/bin/env python3
"""把一个「大 Service 类」拆成多个 mixin 文件（P3 · R4 上下文体积治理）

**背景**：M2–M7 里有 7 个 service 的核心是一个 500~800 行的类。
按方法组拆成 mixin 后：
  · 每个文件 ≤ 500 行（过 R4）
  · 行为**完全等价**（方法体逐字搬迁，self 解析不变）

用法：
    python3 tools/split_class.py <源文件> --class DeliveryService \\
        --mixin delivery_create.py=DeliveryCreateMixin:create_from_plan,_write_progress \\
        --mixin delivery_transit.py=DeliveryTransitMixin:transit,push \\
        [--keep __init__] [--keep-attr]

⚠ 前提：mixin **不得**反向 import 源文件（会形成循环 import）。
  若 mixin 依赖源文件里的模块级常量 → 先用 `split_service.py` 把常量切到独立文件。
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def method_start(node: ast.stmt) -> int:
    """方法起始行（**含装饰器** @staticmethod/@classmethod 等）"""
    start = node.lineno
    decs = getattr(node, "decorator_list", None)
    if decs:
        start = min(start, min(d.lineno for d in decs))
    return start


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("--class", dest="cls", required=True)
    ap.add_argument(
        "--mixin",
        action="append",
        required=True,
        metavar="目标文件=Mixin类名:方法1,方法2",
    )
    ap.add_argument("--keep", default="", help="留在主类的成员（逗号分隔）")
    args = ap.parse_args()

    src_path = pathlib.Path(args.src)
    if not src_path.is_absolute():
        src_path = BACKEND / args.src
    src_path = src_path.resolve()
    src_lines = src_path.read_text(encoding="utf-8").splitlines()
    tree = ast.parse("\n".join(src_lines))

    cls = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == args.cls:
            cls = node
    if cls is None:
        print(f"❌ 未找到类 {args.cls}")
        return 2

    # 顶层 import 区
    imp_nodes = [
        n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))
    ]
    if imp_nodes:
        imp_start = min(n.lineno for n in imp_nodes)
        imp_end = max(n.end_lineno for n in imp_nodes)
        import_block = src_lines[imp_start - 1 : imp_end]
    else:
        import_block = []

    # 类体成员
    methods: dict[str, ast.stmt] = {}
    attrs: list[ast.stmt] = []
    for sub in cls.body:
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods[sub.name] = sub
        elif isinstance(sub, ast.Assign):
            attrs.append(sub)
        elif isinstance(sub, ast.Expr) and isinstance(sub.value, ast.Constant):
            pass  # docstring
        else:
            print(f"⚠ 类体中存在未识别成员 L{sub.lineno}: {ast.unparse(sub)[:60]}")
            attrs.append(sub)

    keep = {k.strip() for k in args.keep.split(",") if k.strip()}
    # 从 `__init__` 推断实例属性类型 → 在 mixin 里声明，保住类型检查
    attr_types: dict[str, str] = {}
    for k in keep:
        if k not in methods:
            continue
        m = methods[k]
        arg_ann = {
            a.arg: ast.unparse(a.annotation) for a in m.args.args if a.annotation
        }
        for sub in ast.walk(m):
            if isinstance(sub, ast.Assign):
                tgt = sub.targets[0]
                if (
                    isinstance(tgt, ast.Attribute)
                    and isinstance(tgt.value, ast.Name)
                    and tgt.value.id == "self"
                ):
                    val = sub.value
                    if isinstance(val, ast.Name) and val.id in arg_ann:
                        attr_types[tgt.attr] = arg_ann[val.id]
                    elif isinstance(val, ast.Call):
                        attr_types[tgt.attr] = ast.unparse(val.func)
                    else:
                        attr_types.setdefault(tgt.attr, "Any")
    plan: list[tuple[pathlib.Path, str, list[str]]] = []
    assigned: set[str] = set()
    for item in args.mixin:
        target, _, rest = item.partition("=")
        mname, _, mlist = rest.partition(":")
        tpath = (src_path.parent / target).resolve()
        names = [x.strip() for x in mlist.split(",") if x.strip()]
        for n in names:
            if n not in methods:
                print(f"❌ 类 {args.cls} 中不存在方法 {n}")
                return 2
            if n in assigned:
                print(f"❌ 方法被指派两次: {n}")
                return 2
            assigned.add(n)
        plan.append((tpath, mname.strip(), names))

    # 模块级 logger（`logger = get_logger(__name__)`）—— mixin 需各自持有一份
    logger_stmt: str | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "logger":
                    logger_stmt = " ".join(src_lines[node.lineno - 1 : node.end_lineno])

    # ---- 生成 mixin 文件 ----
    for tpath, mname, names in plan:
        body: list[str] = []
        body.append(f'"""{mname} —— 由 {args.cls} 拆分而来（P3 上下文体积治理）"""')
        body.append("")
        body.append("# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）")
        body.append("#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。")
        body.append("# mypy: disable-error-code=\"attr-defined\"")
        body.append("")
        body.append("from __future__ import annotations")
        body.append("")
        if import_block:
            body.extend(import_block)
            body.append("")
        if logger_stmt:
            body.append(logger_stmt)
            body.append("")
        body.append("")
        body.append(f"class {mname}:")
        body.append(f'    """{args.cls} 的部分能力（混入主类，行为等价）"""')
        body.append("")
        for aname, atype in attr_types.items():
            body.append(f"    {aname}: {atype}")
        if attr_types:
            body.append("")
        for n in names:
            m = methods[n]
            body.extend(src_lines[method_start(m) - 1 : m.end_lineno])
            body.append("")
        tpath.write_text("\n".join(body).rstrip() + "\n", encoding="utf-8")
        print(f"  ✓ {tpath.relative_to(BACKEND)}（{len(body)} 行，{len(names)} 个方法）")

    # ---- 改写源文件：主类只留 keep 成员 + 继承 mixin ----
    base_indent = "    "
    head: list[str] = []
    # 类 docstring
    doc = ast.get_docstring(cls, clean=False)
    for sub in cls.body:
        if (
            isinstance(sub, ast.Expr)
            and isinstance(sub.value, ast.Constant)
            and isinstance(sub.value.value, str)
        ):
            head.extend(src_lines[sub.lineno - 1 : sub.end_lineno])
            break
    mixin_names = [m for _, m, _ in plan]
    bases = ", ".join(mixin_names)
    out: list[str] = []
    out.append(f"class {args.cls}({bases}):")
    out.extend(head)
    out.append("")
    for a in attrs:
        out.extend(src_lines[a.lineno - 1 : a.end_lineno])
        out.append("")
    for n in sorted(keep):
        if n in methods:
            m = methods[n]
            out.extend(src_lines[method_start(m) - 1 : m.end_lineno])
            out.append("")

    # 主文件需要 import 各 mixin
    imp_lines: list[str] = []
    for tpath, mname, _ in plan:
        imp_lines.append(
            f"from app.modules.{src_path.parents[1].name}.service.{tpath.stem} import {mname}"
        )

    # 定位类的位置，替换；mixin 的 import 放到**文件顶部 import 区之后**（否则 E402）
    start = cls.lineno - 1
    end = cls.end_lineno
    head_part = src_lines[:start]
    # 找到 import 区末尾行（AST 定位，避免把 __all__ 的缩进行误判成 import 延续）
    imp_end_line = 0
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)) and node.end_lineno <= start:
            imp_end_line = max(imp_end_line, node.end_lineno)
    new_src = (
        head_part[:imp_end_line]
        + imp_lines
        + head_part[imp_end_line:]
        + out
        + src_lines[end:]
    )
    src_path.write_text("\n".join(new_src).rstrip() + "\n", encoding="utf-8")
    print(f"  ✓ {src_path.relative_to(BACKEND)}（主类保留 {len(keep)} 个成员）")

    # ---- ruff ----
    ruff = BACKEND / ".venv" / "bin" / "ruff"
    touched = [src_path] + [t for t, _, _ in plan]
    if ruff.exists():
        r = subprocess.run(
            [str(ruff), "check", "--fix", "--isolated", "--select", "F401,F811,F841,I001"]
            + [str(p) for p in touched],
            cwd=BACKEND, capture_output=True, text=True,
        )
        print(f"  ✓ ruff：{(r.stdout or r.stderr or '').strip().splitlines()[-1:]}")

    # ---- 自动补齐跨文件依赖（mixin 不得反向 import 源文件 → 循环）----
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from _split_common import autofix, ruff_fix  # type: ignore

    autofix(
        [t for t, _, _ in plan],
        src_path.parent,
        src_path.parents[1].name,
        forbidden_stems={src_path.stem},
    )
    ruff_fix(touched)
    return 0


if __name__ == "__main__":
    sys.exit(main())
