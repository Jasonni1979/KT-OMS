#!/usr/bin/env python3
"""架构门禁 —— 4 条模块边界规则（P1 · 先 warn 观察 2 周，再转 fail）

| 规则 | 内容 |
|---|---|
| **R1** | 底层不依赖高层：M1/M2 不得 import M3+ 的符号 |
| **R2** | 跨模块只走 `contract.py`：不得从对方的 `service/` 直接 import |
| **R3** | 一表一写者：模块写的表必须在 `tables.yaml` 的可写表清单内 |
| **R4** | 上下文体积：单 service ≤ 500 行；单模块 ≤ 12 个 service 文件 |

**为什么 R2 是核心机制**：每个模块只有一个公开面（`contract.py`），
`service/` 是内部实现。跨模块只能从公开面 import →
① 边界清晰可机器判定 ② 实现可自由重构 ③ 契约稳定后抽服务零改动。

用法：
    python3 tools/check_arch_rules.py            # warn 模式（输出清单，退出码 0）
    python3 tools/check_arch_rules.py --strict   # fail 模式（有问题退出码 1）
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
MODULES_DIR = BACKEND / "app" / "modules"
CONTRACT_DIR = ROOT / "docs" / "架构" / "modules"

#: 模块分层（数字越小越底层）
LAYER: dict[str, int] = {
    "m1_master": 1,
    "m2_stock": 2,
    "m3_trade": 3,
    "m4_fulfill": 3,
    "m5_abnormal": 4,
    "m6_aftersale": 4,
    "m7_integration": 4,
    "m8_insight": 5,
}
#: 底层模块（不得依赖高层）
LOW_LAYERS = (1, 2)

MAX_SERVICE_LINES = 500
MAX_MODULE_FILES = 12

#: 多写者白名单表（事件基础设施，非业务数据）
SHARED_TABLES = {"oms_base.bas_event_outbox"}

#: 表写入的 SQL 形态
WRITE_SQL = re.compile(
    r"(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(oms_\w+\.\w+)", re.I
)


def module_of(path: pathlib.Path) -> str | None:
    """文件所属模块（app/modules/mN/... → mN）"""
    try:
        rel = path.relative_to(MODULES_DIR)
    except ValueError:
        return None
    return rel.parts[0] if rel.parts else None


#: R2 不检查这些目录（测试与 E2E **允许**直接测内部实现 —— 它们是验证工具，
#:   不是业务消费者；收紧它们只会逼着测试绕路）
R2_EXCLUDE_DIRS = ("tests", "scripts", "tools")


def py_files() -> list[pathlib.Path]:
    """R2/R1 检查范围：**生产代码**（app/modules + app/api + app/core）"""
    out: list[pathlib.Path] = []
    base = BACKEND / "app"
    if not base.exists():
        return out
    for p in base.rglob("*.py"):
        if ".venv" in p.parts or "__pycache__" in p.parts:
            continue
        rel = p.relative_to(base)
        if rel.parts and rel.parts[0] in R2_EXCLUDE_DIRS:
            continue
        out.append(p)
    return out


def load_write_tables() -> dict[str, set[str]]:
    """模块 → 可写表清单（来自 docs/架构/modules/M*-tables.yaml，与契约页同源）"""
    import yaml

    out: dict[str, set[str]] = {}
    for f in sorted(CONTRACT_DIR.glob("M*-tables.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        slug = data.get("slug")
        if slug:
            out[slug] = set(data.get("write") or [])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="有问题即失败")
    args = ap.parse_args()

    print("===== 架构门禁（P1 · 4 条边界规则）=====\n")
    violations: dict[str, list[str]] = {"R1": [], "R2": [], "R3": [], "R4": []}

    files = py_files()

    # ---------- R1 + R2：import 方向 ----------
    for p in files:
        src = p.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        own = module_of(p)
        rel = p.relative_to(BACKEND)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            mod = node.module
            if not mod.startswith("app.modules."):
                continue
            parts = mod.split(".")
            if len(parts) < 3:
                continue
            target_mod = parts[2]  # app.modules.mN...
            if target_mod not in LAYER:
                continue
            # R1：底层不得依赖高层
            if own and LAYER.get(own, 9) in LOW_LAYERS and LAYER[target_mod] > max(LOW_LAYERS):
                violations["R1"].append(
                    f"{rel}（{own}）→ {target_mod}：底层模块不得依赖高层"
                )
            # R2：跨模块 import 必须走 contract.py
            if own == target_mod:
                continue  # 模块内部 → 合法
            if parts[3:4] == ["contract"]:
                continue  # 走公开面 → 合法
            kind = "service" if parts[3:4] == ["service"] else "其它"
            violations["R2"].append(
                f"{rel} → {mod}（跨模块直接 import 对方的 {kind}/，应走 contract.py）"
            )

    # ---------- R3：一表一写者 ----------
    write_tables = load_write_tables()
    for mod, allowed in write_tables.items():
        svc_dir = MODULES_DIR / mod / "service"
        if not svc_dir.exists():
            continue
        for f in sorted(svc_dir.rglob("*.py")):
            src = f.read_text(encoding="utf-8")
            for m in WRITE_SQL.finditer(src):
                table = m.group(1).lower()
                if table in SHARED_TABLES:
                    continue  # 多写者白名单（outbox 是事件基础设施）
                if table not in allowed:
                    violations["R3"].append(
                        f"{f.relative_to(BACKEND)} 写了 {table}"
                        f"（不在 {mod} 的可写表清单内）"
                    )

    # ---------- R4：上下文体积 ----------
    for mod in sorted(LAYER):
        svc_dir = MODULES_DIR / mod / "service"
        if not svc_dir.exists():
            continue
        py_list = [p for p in svc_dir.rglob("*.py") if p.name != "__init__.py"]
        if len(py_list) > MAX_MODULE_FILES:
            violations["R4"].append(
                f"{mod}：{len(py_list)} 个 service 文件 > {MAX_MODULE_FILES}"
            )
        for p in py_list:
            n = len(p.read_text(encoding="utf-8").splitlines())
            if n > MAX_SERVICE_LINES:
                violations["R4"].append(
                    f"{p.relative_to(BACKEND)}：{n} 行 > {MAX_SERVICE_LINES}"
                )

    # ---------- 输出 ----------
    titles = {
        "R1": "底层不依赖高层",
        "R2": "跨模块只走 contract.py（核心机制）",
        "R3": "一表一写者",
        "R4": "上下文体积",
    }
    for rule in ("R1", "R2", "R3", "R4"):
        items = violations[rule]
        mark = "✓" if not items else "✗"
        print(f"{mark} {rule} {titles[rule]}：{len(items)} 处违规")
        for it in items[:12]:
            print(f"    - {it}")
        if len(items) > 12:
            print(f"    ... 另有 {len(items) - 12} 处")

    total = sum(len(v) for v in violations.values())
    print("\n" + "=" * 50)
    print(f"合计违规 {total} 处")
    if total:
        print(
            "\n⚠ 当前为 **warn 模式**（P1 先观察 2 周再转 fail）。"
            "\n  R2 的违规是 **P2 跨模块收口** 的工作量清单。"
        )
        if args.strict:
            return 1
    else:
        print("\n✓ 架构门禁通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
