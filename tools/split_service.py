#!/usr/bin/env python3
"""把一个超限 service 文件按「顶层定义」拆成多个文件（P3 · R4 上下文体积治理）

**为什么要有这个工具**：R4 要求单 service ≤ 500 行。11 个超限文件合计约 1 万行，
手工复制粘贴极易切错（漏行、缩进错、import 漏带）→ 做一个**机械可复现**的切分器。

用法：
    python3 tools/split_service.py <源文件> --plan <目标文件>:<顶层名1>,<顶层名2> [...]

行为（**只做物理重排，不改任何业务逻辑**）：
  1. 读源文件，按 AST 切出每个顶层定义（class / def / 常量赋值）的完整代码块
  2. 每个目标文件 = 【新 docstring】+【源文件的全部 import 区】+【指派的代码块】
  3. 源文件被改写为：【保留原 docstring】+【re-export 全部原有符号】+【原 import 区保留】
  4. 随后必须跑 `ruff check --fix` 清掉未使用的 import（工具会自动调用）

⚠ 依赖关系由 agent 负责核对：被切走的定义若引用了留在源文件的符号，
  目标文件需要显式 `from app.modules.mX.service.<源文件stem> import <符号>`。
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"


def parse_module(path: pathlib.Path) -> tuple[ast.Module, list[ast.stmt]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    # import 区 = 第一个「顶层定义」之前的所有语句（含 module docstring）
    defs: list[ast.stmt] = []
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            t = node.targets[0] if isinstance(node, ast.Assign) else node.target
            if isinstance(t, ast.Name) and t.id.isupper():
                defs.append(node)
    return tree, defs


def stmt_name(node: ast.stmt) -> str | None:
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.name
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        t = node.targets[0] if isinstance(node, ast.Assign) else node.target
        if isinstance(t, ast.Name):
            return t.id
    return None


def node_start(node: ast.stmt) -> int:
    """节点起始行（**含装饰器**）—— 切块时必须带上 `@dataclass` 等装饰器行"""
    start = node.lineno
    decs = getattr(node, "decorator_list", None)
    if decs:
        start = min(start, min(d.lineno for d in decs))
    return start


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument(
        "--plan",
        action="append",
        required=True,
        metavar="目标文件:顶层名1,顶层名2",
        help="可重复；顶层名为 * 表示「留在源文件的其余全部定义」",
    )
    ap.add_argument("--docstring", action="append", default=[], metavar="目标文件=说明")
    args = ap.parse_args()

    src_path = pathlib.Path(args.src)
    if not src_path.is_absolute():
        src_path = BACKEND / args.src
    src_path = src_path.resolve()
    src_lines = src_path.read_text(encoding="utf-8").splitlines()
    tree, defs = parse_module(src_path)

    # ---- 定位 import 区结束位置 ----
    first_def_line = min(d.lineno for d in defs)
    header_lines = src_lines[: first_def_line - 1]
    # header 里可能含 module docstring + import + 注释
    # import 语句行范围（用于目标文件复制）
    import_ranges: list[tuple[int, int]] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            import_ranges.append((node.lineno, node.end_lineno))
    if import_ranges:
        imp_start = min(r[0] for r in import_ranges)
        imp_end = max(r[1] for r in import_ranges)
        import_block = src_lines[imp_start - 1 : imp_end]
    else:
        import_block = []

    # ---- 源文件的 module docstring ----
    src_doc = ast.get_docstring(tree, clean=False)
    src_doc_lines: list[str] = []
    if src_doc is not None:
        # 找到 docstring 节点的行范围
        for node in tree.body:
            if (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                src_doc_lines = src_lines[node.lineno - 1 : node.end_lineno]
                break

    by_name: dict[str, ast.stmt] = {}
    for d in defs:
        n = stmt_name(d)
        if n:
            by_name[n] = d

    # ---- 解析 plan ----
    plan: list[tuple[pathlib.Path, list[str] | None, str]] = []
    for item in args.plan:
        target, _, names = item.partition(":")
        tpath = pathlib.Path(target)
        if not tpath.is_absolute():
            tpath = src_path.parent / tpath
        tpath = tpath.resolve()
        if names.strip() == "*":
            plan.append((tpath, None, ""))
        else:
            plan.append((tpath, [x.strip() for x in names.split(",") if x.strip()], ""))
    docs = {}
    for d in args.docstring:
        k, _, v = d.partition("=")
        docs[pathlib.Path(k).name] = v

    assigned: set[str] = set()
    for _tpath, names, _ in plan:
        if names:
            for n in names:
                if n not in by_name:
                    print(f"❌ 源文件中不存在顶层定义：{n}")
                    return 2
                if n in assigned:
                    print(f"❌ 顶层定义被指派两次：{n}")
                    return 2
                assigned.add(n)

    # ---- 生成目标文件 ----
    rest = [d for d in defs if stmt_name(d) not in assigned]
    for tpath, names, _ in plan:
        if names is None:
            chosen = rest
            rest = []
        else:
            chosen = [by_name[n] for n in names]
        chosen = sorted(chosen, key=lambda d: d.lineno)
        if tpath == src_path:
            # 「留在源文件」：不生成新文件，定义并回 rest
            rest = sorted(rest + chosen, key=lambda d: d.lineno)
            continue
        doc = docs.get(tpath.name, tpath.stem)
        out: list[str] = []
        out.append(f'"""{doc}"""')
        out.append("")
        if import_block:
            out.extend(import_block)
            out.append("")
        for d in chosen:
            out.extend(src_lines[node_start(d) - 1 : d.end_lineno])
            out.append("")
        tpath.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
        print(f"  ✓ {tpath.relative_to(BACKEND)}（{len(out)} 行，{len(chosen)} 个定义）")

    # ---- 改写源文件为 re-export ----
    # ⚠ 保留**所有未被移走的顶层节点**（小写赋值如 `logger = get_logger(__name__)`、
    #   `if __name__ == "__main__":` 块等）—— 只按「定义」切会把它们悄悄丢掉。
    moved_ids = {id(by_name[n]) for n in assigned if n in by_name}
    doc_node = None
    for node in tree.body:
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            doc_node = node
            break
    remain_blocks: list[str] = []
    for node in tree.body:
        if id(node) in moved_ids:
            continue
        if node is doc_node:
            continue
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue  # 已在 import_block 中
        remain_blocks.extend(src_lines[node_start(node) - 1 : node.end_lineno])
        remain_blocks.append("")

    reexport: list[str] = []
    moved: dict[str, list[str]] = {}
    for tpath, names, _ in plan:
        if names is None:
            continue
        stem = tpath.stem
        for n in names:
            moved.setdefault(stem, []).append(n)
    for stem, names in moved.items():
        reexport.append(
            f"from app.modules.{src_path.parents[1].name}.service.{stem} import ("
        )
        for n in names:
            # ⚠ 私有名（_ 开头）不在 `__all__` 里 → ruff 会当成未使用删掉 → 单独 noqa
            reexport.append(f"    {n},  # noqa: F401" if n.startswith("_") else f"    {n},")
        reexport.append(")")
    reexport.append("")

    # ⚠ **必须显式列 `__all__`**：否则 ruff 的 F401 会把「仅用于 re-export、
    #   本文件内未使用」的 import 删掉 → 向后兼容路径全部断掉。
    all_names = [stmt_name(d) for d in defs if stmt_name(d)]
    all_names = [n for n in all_names if n and not n.startswith("_")]
    existing_all: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "__all__":
                    existing_all = [
                        e.value for e in node.value.elts  # type: ignore[attr-defined]
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    ]
    merged_all = list(dict.fromkeys(existing_all + all_names))
    all_block = ["__all__ = ["]
    for n in merged_all:
        all_block.append(f'    "{n}",')
    all_block.append("]")
    all_block.append("")

    body: list[str] = []
    notice = [
        "",
        "⚠ 本文件在 P3（上下文体积治理）中拆分为多个文件；",
        "   此处保留 re-export，**原有 import 路径全部保持可用**。",
    ]
    if src_doc_lines:
        # 把说明并入原 module docstring（不能放在 docstring 之外 —— 那是非法语法）
        body.extend(src_doc_lines[:-1])
        body.extend(notice)
        body.append(src_doc_lines[-1])
    else:
        body.append('"""M2 物料域服务层"""')
        body.extend(notice)
        body.append('"""')
    body.append("")
    body.extend(import_block)
    body.append("")
    body.extend(reexport)
    body.extend(all_block)
    if remain_blocks:
        body.append("")
        body.extend(remain_blocks)
    src_path.write_text("\n".join(body).rstrip() + "\n", encoding="utf-8")
    print(f"  ✓ {src_path.relative_to(BACKEND)}（{len(body)} 行，re-export {len(assigned)} 个符号）")

    # ---- ruff 清理未使用 import + 排序 ----
    ruff = BACKEND / ".venv" / "bin" / "ruff"
    touched = [str(src_path)] + [str(t) for t, _, _ in plan]
    if ruff.exists():
        r = subprocess.run(
            [str(ruff), "check", "--fix", "--isolated", "--select", "F401,F811,F841,I001"] + touched,
            cwd=BACKEND, capture_output=True, text=True,
        )
        print(f"  ✓ ruff 清理：{(r.stdout or r.stderr or '').strip().splitlines()[-1:]}")

    # ---- 自动补齐跨文件依赖（被切走的定义引用了留在别处的顶层名）----
    if ruff.exists():
        r = subprocess.run(
            [str(ruff), "check", "--isolated", "--output-format=concise", "--select", "F821"]
            + touched,
            cwd=BACKEND, capture_output=True, text=True,
        )
        undefined: dict[str, set[str]] = {}
        for line in (r.stdout or "").splitlines():
            if "F821" not in line:
                continue
            parts = line.split(":")
            if len(parts) < 4:
                continue
            fpath = parts[0]
            seg = line.split("`")
            name = seg[1].strip() if len(seg) >= 3 else ""
            if not name:
                continue
            undefined.setdefault(fpath, set()).add(name)
        if undefined:
            mod_dir = src_path.parent
            mod_name = src_path.parents[1].name
            # 模块内所有顶层定义名 → 来源文件
            owners: dict[str, list[str]] = {}
            for f in sorted(mod_dir.glob("*.py")):
                try:
                    t = ast.parse(f.read_text(encoding="utf-8"))
                except SyntaxError:
                    continue
                for node in t.body:
                    n = stmt_name(node)
                    if n:
                        owners.setdefault(n, []).append(f.stem)
            for fpath, names in undefined.items():
                fp = pathlib.Path(fpath)
                lines = fp.read_text(encoding="utf-8").splitlines()
                add: dict[str, list[str]] = {}
                for n in sorted(names):
                    cands = [s for s in owners.get(n, []) if s != fp.stem]
                    if not cands:
                        print(f"  ⚠ {fp.name}: 未定义名 {n} —— 模块内找不到定义，需人工处理")
                        continue
                    if len(cands) > 1:
                        print(f"  ⚠ {fp.name}: 未定义名 {n} 有多个候选来源 {cands}，需人工指定")
                        continue
                    if cands[0] == src_path.stem:
                        print(
                            f"  ⚠ {fp.name}: 未定义名 {n} 的来源是源文件 {src_path.name}"
                            f" —— 会形成循环 import，需调整拆分方案"
                        )
                        continue
                    add.setdefault(cands[0], []).append(n)
                if not add:
                    continue
                block: list[str] = []
                for stem, ns in add.items():
                    block.append(
                        f"from app.modules.{mod_name}.service.{stem} import ("
                    )
                    for n in ns:
                        block.append(f"    {n},")
                    block.append(")")
                # 插到最后一个顶层 import 之后（AST 定位，不用猜）
                try:
                    t2 = ast.parse(fp.read_text(encoding="utf-8"))
                except SyntaxError:
                    continue
                imp_ends = [
                    n.end_lineno
                    for n in t2.body
                    if isinstance(n, (ast.Import, ast.ImportFrom))
                ]
                insert_at = max(imp_ends) if imp_ends else 0
                lines = fp.read_text(encoding="utf-8").splitlines()
                new_lines = lines[:insert_at] + block + lines[insert_at:]
                fp.write_text("\n".join(new_lines), encoding="utf-8")
                print(f"  ✓ {fp.name}: 自动补 import { {k: v for k, v in add.items()} }")
        # 自动补的 import 需要重新排序
        subprocess.run(
            [str(ruff), "check", "--fix", "--isolated", "--select", "I001"] + touched,
            cwd=BACKEND, capture_output=True, text=True,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
