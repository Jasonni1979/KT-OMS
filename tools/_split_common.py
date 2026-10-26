#!/usr/bin/env python3
"""拆分工具的共享逻辑：跨文件依赖自动补齐（P3）

**为什么需要**：把一个 service 拆成多个文件后，被切走的定义若引用了
别处的顶层符号（常量 / 类 / 函数），必须显式 import —— 漏一个就是
运行期 `NameError`（而且常常只在某条分支触发，极难发现）。

自动化的做法：
  1. `ruff --select F821` 抓**代码里直接引用**的未定义名
  2. AST 扫**字符串类型注解**（`from __future__ import annotations` 下
     注解是字符串，ruff 抓不到，但 mypy 会报 name-defined）
  3. 在**模块内**找该名字的定义位置 → 自动补 `from app.modules.<mod>.service.<stem> import X`

⚠ 若同名定义在多个文件里 → 不自动补（打印告警，避免拿到错的实现）。
⚠ 若来源是「当前正在被拆分的源文件」→ 不自动补（会形成循环 import）。
"""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1] / "backend"


def collect_defined(mod_dir: pathlib.Path) -> dict[str, list[str]]:
    """模块内所有顶层定义名 → 所在文件 stem 列表"""
    owners: dict[str, list[str]] = {}
    for f in sorted(mod_dir.glob("*.py")):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in tree.body:
            name = None
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        name = t.id
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name = node.target.id
            if name:
                owners.setdefault(name, []).append(f.stem)
    return owners


def undefined_names(path: pathlib.Path) -> set[str]:
    """文件里「引用了但没定义」的名字：ruff F821 + 字符串注解扫描"""
    out: set[str] = set()
    ruff = BACKEND / ".venv" / "bin" / "ruff"
    if ruff.exists():
        r = subprocess.run(
            [str(ruff), "check", "--isolated", "--output-format=concise", "--select", "F821", str(path)],
            cwd=BACKEND, capture_output=True, text=True,
        )
        for line in (r.stdout or "").splitlines():
            if "F821" not in line:
                continue
            seg = line.split("`")
            if len(seg) >= 3:
                out.add(seg[1].strip())
    # 字符串类型注解
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return out
    local: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            local.add(node.id)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            local.add(node.name)
    for node in ast.walk(tree):
        anns: list[ast.expr] = []
        if isinstance(node, ast.AnnAssign):
            anns.append(node.annotation)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.returns:
                anns.append(node.returns)
            for a in list(node.args.args) + list(node.args.kwonlyargs) + list(node.args.posonlyargs):
                if a.annotation:
                    anns.append(a.annotation)
        for a in anns:
            names: list[str] = []
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                try:
                    sub = ast.parse("__x__: " + a.value)
                except SyntaxError:
                    continue
                names = [
                    n.id
                    for n in ast.walk(sub)
                    if isinstance(n, ast.Name)
                ]
            elif isinstance(a, ast.Name):
                names = [a.id]
            for n in names:
                if n not in local and n not in out:
                    out.add(n)
    return out


def insert_import(path: pathlib.Path, stem: str, names: list[str], mod_name: str) -> None:
    """在 import 区末尾插入 `from app.modules.<mod>.service.<stem> import (...)`"""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return
    imp_ends = [
        n.end_lineno for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))
    ]
    insert_at = max(imp_ends) if imp_ends else 0
    block = [f"from app.modules.{mod_name}.service.{stem} import ("]
    for n in names:
        block.append(f"    {n},")
    block.append(")")
    new_lines = lines[:insert_at] + block + lines[insert_at:]
    path.write_text("\n".join(new_lines), encoding="utf-8")


def autofix(
    touched: list[pathlib.Path],
    mod_dir: pathlib.Path,
    mod_name: str,
    forbidden_stems: set[str] | None = None,
) -> list[str]:
    """自动补齐跨文件依赖；返回告警列表"""
    forbidden = forbidden_stems or set()
    owners = collect_defined(mod_dir)
    warnings: list[str] = []
    for path in touched:
        undef = undefined_names(path)
        if not undef:
            continue
        add: dict[str, list[str]] = {}
        for n in sorted(undef):
            cands = [s for s in owners.get(n, []) if s != path.stem]
            if not cands:
                continue
            if len(cands) > 1:
                warnings.append(f"{path.name}: {n} 有多个候选来源 {cands}，需人工指定")
                continue
            if cands[0] in forbidden:
                warnings.append(
                    f"{path.name}: {n} 的来源是 {cands[0]}（会形成循环 import），需调整拆分方案"
                )
                continue
            add.setdefault(cands[0], []).append(n)
        for stem, names in add.items():
            insert_import(path, stem, names, mod_name)
            print(f"  ✓ {path.name}: 自动补 import {{'{stem}': {names}}}")
    if warnings:
        for w in warnings:
            print(f"  ⚠ {w}")
    return warnings


def ruff_fix(paths: list[pathlib.Path]) -> None:
    ruff = BACKEND / ".venv" / "bin" / "ruff"
    if not ruff.exists() or not paths:
        return
    subprocess.run(
        [str(ruff), "check", "--fix", "--isolated", "--select", "F401,F811,F841,I001"]
        + [str(p) for p in paths],
        cwd=BACKEND, capture_output=True, text=True,
    )


if __name__ == "__main__":
    print(__doc__)
    sys.exit(0)
