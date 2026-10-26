#!/usr/bin/env python3
"""同步模块契约文档里的「代码行 / service 个数」（P3 拆分后会过时）

**为什么需要**：P3 把 11 个超大 service 拆成了 40+ 个小文件，
契约文档头部写的「代码行 4,402 · service 5 个」立刻变成假信息。
契约页已改成实时扫描，但 Markdown 文档也要跟上 —— 否则**两份契约不一致**
比一份过时更糟（agent 读到哪份就信哪份）。

用法：
    python3 tools/sync_contract_meta.py            # 检查并更新
    python3 tools/sync_contract_meta.py --check    # 只检查（CI 用，有漂移则退出码 1）
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
CONTRACT_DIR = ROOT / "docs" / "架构" / "modules"
MODULES_DIR = ROOT / "backend" / "app" / "modules"

META_RE = re.compile(
    r"\*\*代码行\*\*\s*([\d,]+)\s*·\s*\*\*service\*\*\s*(\d+)\s*个"
)


def module_stats(slug: str) -> tuple[int, int]:
    """(service 文件数, 总行数)"""
    svc = MODULES_DIR / slug / "service"
    if not svc.exists():
        return 0, 0
    files = [p for p in svc.glob("*.py") if p.name != "__init__.py"]
    lines = sum(len(p.read_text(encoding="utf-8").splitlines()) for p in files)
    return len(files), lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查，不写入")
    args = ap.parse_args()

    import yaml

    drift = 0
    for md in sorted(CONTRACT_DIR.glob("M*-contract.md")):
        code = md.name.split("-")[0]
        yaml_file = sorted(CONTRACT_DIR.glob(f"{code}-*-tables.yaml"))
        if not yaml_file:
            continue
        data = yaml.safe_load(yaml_file[0].read_text(encoding="utf-8")) or {}
        slug = data.get("slug")
        if not slug:
            continue
        n_files, n_lines = module_stats(slug)
        text = md.read_text(encoding="utf-8")
        m = META_RE.search(text)
        if not m:
            print(f"⚠ {md.name}: 未找到「代码行 / service 个数」标记，跳过")
            continue
        want = f"**代码行** {n_lines:,} · **service** {n_files} 个"
        have = m.group(0)
        if have == want:
            print(f"✓ {md.name}: {have}")
            continue
        drift += 1
        if args.check:
            print(f"✗ {md.name}: 契约元信息漂移\n    现文档：{have}\n    实际值：{want}")
            continue
        new_text = text[: m.start()] + want + text[m.end() :]
        md.write_text(new_text, encoding="utf-8")
        print(f"✓ {md.name}: {have} → {want}")
    if args.check and drift:
        print(f"\n❌ {drift} 份契约文档元信息漂移（跑 tools/sync_contract_meta.py 修复）")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
