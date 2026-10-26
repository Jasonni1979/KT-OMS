#!/usr/bin/env python3
"""生成各模块的 `contract.py`（唯一公开面）

**为什么**：`app/modules/mN/service/` 里的实现不对外承诺稳定性；
跨模块 import **只能**从 `app/modules/mN/contract.py` 导入（门禁 R2）。
这样「一个模块能对外做什么」有唯一入口 —— 契约化的物理体现。

生成方式：扫描该模块 service/ 下的 public 符号 → re-export。
⚠ 生成后自动 `ruff --fix`（import 排序由 ruff 判定，手写规则易不一致；ruff 确定性 → 幂等）。
"""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
MODULES_DIR = BACKEND / "app" / "modules"

TITLES = {
    "m1_master": "M1 基础主数据", "m2_stock": "M2 商品与库存账本",
    "m3_trade": "M3 订单与审单", "m4_fulfill": "M4 履约与发货",
    "m5_abnormal": "M5 异常单域", "m6_aftersale": "M6 售后与改单",
    "m7_integration": "M7 外部集成", "m8_insight": "M8 报表与监控",
}


def public_symbols(path: pathlib.Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    out: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            out.append(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            out.append(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id.isupper():
                    out.append(t.id)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id.isupper():
                out.append(node.target.id)
    return out


def main() -> int:
    if not MODULES_DIR.exists():
        print("❌ 未找到 app/modules/")
        return 2
    total = 0
    for mod_dir in sorted(MODULES_DIR.iterdir()):
        if not mod_dir.is_dir() or not mod_dir.name.startswith("m"):
            continue
        svc_dir = mod_dir / "service"
        if not svc_dir.exists():
            continue
        by_file: dict[str, list[str]] = {}
        seen: set[str] = set()
        conflicts: list[str] = []
        # ⚠ **同名冲突必须用别名导出**（`<Name>_<stem>`）——
        #   跨模块调用方要的是**具体某个 service 的**那个符号，
        #   若 contract 只导出「第一个同名符号」→ 调用方拿到**错的类**（行为静默改变）。
        #   实测：M4 的 DispatchService（dispatch.py / dispatch_service.py 各一个）、
        #        M7 的 MAX_RETRY（wms_channel=5 / writeback=10，值都不同！）
        alias: dict[str, str] = {}  # (stem, 原名) → 别名
        for f in sorted(svc_dir.glob("*.py")):
            if f.name == "__init__.py":
                continue
            for sym in public_symbols(f):
                if sym in seen:
                    conflicts.append(sym)
                    ali = f"{sym}_{f.stem}"
                    alias[(f.stem, sym)] = ali
                    by_file.setdefault(f.stem, []).append((sym, ali))
                    continue
                seen.add(sym)
                by_file.setdefault(f.stem, []).append((sym, sym))
        if not by_file:
            continue
        title = TITLES.get(mod_dir.name, mod_dir.name)
        lines = [
            f'"""{title} —— **契约公开面（唯一对外接口）**',
            "",
            "⚠ **跨模块 import 只能从本文件导入**（门禁 R2 强制）。",
            "   `service/` 下的实现是内部细节，不对外承诺稳定性 ——",
            "   需要跨模块用的能力，在此显式导出。",
            "",
            "本文件由 `tools/gen_module_public_api.py` 生成，请勿手工编辑。",
            '"""',
            "from __future__ import annotations",
            "",
        ]
        for stem, syms in by_file.items():
            lines.append(f"from app.modules.{mod_dir.name}.service.{stem} import (")
            for orig, exported in sorted(syms):
                # ⚠ 别名必须写成 `import X as X_stem`（源模块里没有 X_stem 这个名字）
                lines.append(f"    {orig} as {exported}," if orig != exported else f"    {orig},")
            lines.append(")")
            lines.append("")
        lines.append("__all__ = [")
        for syms in by_file.values():
            for _orig, exported in sorted(syms):
                lines.append(f'    "{exported}",')
        lines.append("]")
        lines.append("")
        (mod_dir / "contract.py").write_text("\n".join(lines), encoding="utf-8")
        total += 1
        msg = f"  ✓ {mod_dir.name}/contract.py（{len(seen)} 个符号）"
        if conflicts:
            msg += f" ⚠ 同名冲突已跳过: {', '.join(conflicts[:5])}"
        print(msg)

    ruff = BACKEND / ".venv" / "bin" / "ruff"
    if ruff.exists():
        r = subprocess.run(
            [str(ruff), "check", "--fix", str(MODULES_DIR)],
            cwd=BACKEND, capture_output=True, text=True,
        )
        print(f"✓ ruff --fix：{(r.stdout or '').strip().splitlines()[-1] if r.stdout.strip() else 'OK'}")
    print(f"✓ 共生成 {total} 个 contract.py")
    # 输出符号来源映射（供 P2 改写脚本精确对应，避免拿到错的同名符号）
    import json

    mapping = {}
    for mod_dir in sorted(MODULES_DIR.iterdir()):
        if not mod_dir.is_dir() or not mod_dir.name.startswith("m"):
            continue
        svc_dir = mod_dir / "service"
        if not svc_dir.exists():
            continue
        entry: dict[str, dict[str, str]] = {}
        used: set[str] = set()
        for f in sorted(svc_dir.glob("*.py")):
            if f.name == "__init__.py":
                continue
            for sym in public_symbols(f):
                if sym in used:
                    entry[f"{f.stem}.{sym}"] = f"{sym}_{f.stem}"
                else:
                    entry[f"{f.stem}.{sym}"] = sym
                used.add(sym)
        mapping[mod_dir.name] = entry
    (ROOT / "tools" / "_module_symbol_map.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print("✓ 符号来源映射 → tools/_module_symbol_map.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
