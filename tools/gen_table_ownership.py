#!/usr/bin/env python3
"""表所有权推导 —— 从**代码实际写入**推导每个模块的可写表清单

**为什么自动推导**：P1 的架构门禁 R3 首次运行就暴露了「人工声明的归属清单」
与「代码真实写入」不一致（WMS 通道写 `oms_fulfill.*`，而清单把整个 oms_fulfill
归给了 M4）。人工维护的清单必然漂移 —— 与枚举契约同一个道理：**单一来源 + 自动生成**。

推导规则：
  1) 扫每个模块 service/ 下的 SQL 写入（INSERT/UPDATE/DELETE）与 ORM 写操作
  2) 表 → 写它的模块集合
     · 单模块 → 归该模块（唯一写者 ✓）
     · 多模块 → **冲突**，需人工裁决（列出，不自动归）
  3) 白名单表（多写者基础设施）：bas_event_outbox

产出：更新 `docs/架构/modules/M*-tables.yaml` 的 write 清单
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
MODULES_DIR = BACKEND / "app" / "modules"
CONTRACT_DIR = ROOT / "docs" / "架构" / "modules"

WRITE_SQL = re.compile(r"(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(oms_\w+\.\w+)", re.I)

#: 多写者白名单（事件基础设施，非业务数据）
SHARED_TABLES = {"oms_base.bas_event_outbox"}

#: 模块 slug → (代码名, 中文名)
MODULE_META = {
    "m1_master": ("M1", "基础主数据"),
    "m2_stock": ("M2", "商品与库存账本"),
    "m3_trade": ("M3", "订单与审单"),
    "m4_fulfill": ("M4", "履约与发货"),
    "m5_abnormal": ("M5", "异常单域"),
    "m6_aftersale": ("M6", "售后与改单"),
    "m7_integration": ("M7", "外部集成"),
    "m8_insight": ("M8", "报表与监控"),
}


def orm_tables() -> dict[str, str]:
    """ORM 类名 → 表全名"""
    sys.path.insert(0, str(BACKEND))
    from app.models.base import Base  # noqa: PLC0415

    import app.models  # noqa: F401,PLC0415

    return {
        m.class_.__name__: f"{m.local_table.schema}.{m.local_table.name}"
        for m in Base.registry.mappers
    }


def scan_module(slug: str, model_map: dict[str, str]) -> set[str]:
    """扫某模块的写入表"""
    svc_dir = MODULES_DIR / slug / "service"
    tables: set[str] = set()
    if not svc_dir.exists():
        return tables
    for f in sorted(svc_dir.rglob("*.py")):
        src = f.read_text(encoding="utf-8")
        for m in WRITE_SQL.finditer(src):
            tables.add(m.group(1).lower())
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            fn = node.func
            name = getattr(fn, "attr", "") or getattr(fn, "id", "")
            if name not in ("add", "insert", "update", "delete"):
                continue
            for arg in node.args:
                cn = getattr(arg, "id", "") or getattr(arg, "attr", "")
                if cn in model_map:
                    tables.add(model_map[cn].lower())
    return tables


def main() -> int:
    model_map = orm_tables()

    # 表 → 写它的模块
    table_mods: dict[str, set[str]] = defaultdict(set)
    for slug in MODULE_META:
        for t in scan_module(slug, model_map):
            table_mods[t].add(slug)

    conflicts = {t: ms for t, ms in table_mods.items() if len(ms) > 1 and t not in SHARED_TABLES}

    # 写回各模块的 tables.yaml
    for slug, (code, cn_name) in MODULE_META.items():
        f = sorted(CONTRACT_DIR.glob(f"{code}-*-tables.yaml"))
        if not f:
            continue
        path = f[0]
        text = path.read_text(encoding="utf-8")
        owned = sorted(t for t, ms in table_mods.items() if ms == {slug})
        block = "write:\n"
        for t in owned:
            block += f"  - {t}\n"
        # 替换原有的 write 段（到下一个顶层键为止）
        text = re.sub(r"^write:\n(?:  - .*\n)+", block, text, count=1, flags=re.M)
        path.write_text(text, encoding="utf-8")
        print(f"  ✓ {slug}：{len(owned)} 张可写表")

    print(f"\n合计归属 {sum(1 for t, ms in table_mods.items() if len(ms) == 1)} 张唯一写者表")
    if conflicts:
        print(f"\n⚠ 跨模块写冲突 {len(conflicts)} 张（需人工裁决）：")
        for t, ms in sorted(conflicts.items()):
            print(f"    {t} ← {', '.join(sorted(ms))}")
    shared = sorted(t for t, ms in table_mods.items() if len(ms) > 1 and t in SHARED_TABLES)
    if shared:
        print(f"\n白名单多写者表：{', '.join(shared)}")
    return 0


from collections import defaultdict  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
