"""复盘工具：SRS 需求条目 × 测试覆盖矩阵盘点

数据源：`tools/test_case_map.py`（CASES 映射表，需求追溯条目 + 场景 + 预期），
比解析 markdown 更准确（markdown 的需求追溯列只到 SRS 级，FR 级在 CASES 里）。

覆盖判定：CASES 的「需求追溯条目」里若出现 `FR-xx` 则视为引用该 FR；
未出现 FR 的条目（如仅写 SRS 级）视为**模块级覆盖**，该模块下所有
FR 都算被触达（降级处理，避免虚高缺口）。

用法：
    cd KT-OMS && python3 tools/review_coverage.py [--detail] [--json]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _req_dir() -> Path:
    """需求文档目录（优先仓库内，回退仓库外）

    仓库内 `docs/requirements/` 是 SRS 的**权威副本**（与仓库外 `需求文档/`
    内容一致，已 md5 全量比对）；优先用仓库内 → clone 后工具仍可运行。
    """
    inner = ROOT / "docs" / "requirements"
    if inner.exists():
        return inner
    return ROOT.parent / "需求文档"

REQ = _req_dir()  # 见 _req_dir()：优先仓库内 docs/requirements/


sys.path.insert(0, str(ROOT / "tools"))

import test_case_map as M  # noqa: E402

#: 计划 W1-W7 交付范围内的 SRS 模块（模块号 → 文件名）
IN_SCOPE: dict[str, str] = {
    "D10.01": "SRS-D10.01-组织架构与货主管理.md",
    "D10.02": "SRS-D10.02-租户账户与角色.md",
    "D10.03": "SRS-D10.03-多维数据权限.md",
    "D09.01": "SRS-D09.01-仓库与多WMS路由.md",
    "D04.01": "SRS-D04.01-商品与物料管理.md",
    "D01.06": "SRS-D01.06-导入导出中心.md",
    "D04.02": "SRS-D04.02-库存记账.md",
    "D04.03": "SRS-D04.03-预占与释放.md",
    "D04.04": "SRS-D04.04-出入库单据与流水.md",
    "D02.01": "SRS-D02.01-平台接入框架.md",
    "D02.02": "SRS-D02.02-平台适配器.md",
    "D02.03": "SRS-D02.03-拉单与消息接收.md",
    "D04.08": "SRS-D04.08-可售计算与平台同步.md",
    "D03.01": "SRS-D03.01-订单接入与创建.md",
    "D03.02": "SRS-D03.02-审单引擎.md",
    "D03.03": "SRS-D03.03-人工审单工作台.md",
    "D03.04": "SRS-D03.04-拆单策略中心.md",
    "D03.06": "SRS-D03.06-配货分仓.md",
    "D03.07": "SRS-D03.07-发货单管理.md",
    "D09.02": "SRS-D09.02-出库指令与回传.md",
    "D02.04": "SRS-D02.04-回传中心.md",
    "D02.05": "SRS-D02.05-失败重试与对账.md",
    "D02.06": "SRS-D02.06-店铺授权管理.md",
}

#: 测试模块前缀 → 该模块主要覆盖的 SRS 模块（一个前缀可覆盖多个 SRS 模块）
PREFIX_TO_SRS: dict[str, list[str]] = {
    "SMOKE": [],
    "AUTH": ["D10.02"],
    "PERM": ["D10.03"],
    "MST": ["D10.01"],
    "BOR": ["D10.01", "D09.01", "D04.02"],
    "MAT": ["D04.01"],
    "BOM": ["D04.01"],
    "BAR": ["D04.01"],
    "LED": ["D04.02"],
    "FRZ": ["D04.03"],
    "BILL": ["D04.04"],
    "OI": ["D02.03", "D03.01"],
    "SCN": [],
    "SELL": ["D04.08"],
    "IMP": ["D01.06", "D04.01", "D04.04"],
    "AUD": ["D03.02", "D03.03"],
    "FUL": ["D03.06", "D03.04", "D03.07"],
    "WMS": ["D09.01", "D09.02", "D02.04", "D02.05"],
    "SEED": ["D10.03"],
    "MOCK": ["D02.02", "D02.03"],
    # ---- W8 新增模块（复盘发现：新增前缀未登记 → 该模块用例**完全不参与**覆盖统计）
    "GW": ["D02.01"],              # 平台接入框架（Gateway）
    "ACC": ["D10.02"],             # 租户账户与角色
    "SHOP": ["D02.06"],            # 店铺授权与档案
    "ABN": ["D03.09"],             # 异常单域
    "ABNACT": ["D03.09"],          # 异常单分派与动作
    "ABNAPI": ["D03.09"],          # 异常单 API
    "STOCKOUT": ["D03.09"],        # 缺货策略链
    "ABNEXT": ["D03.09"],          # 应急批次/暂停编排/名单服务
    "MODIFY": ["D03.08"],          # 订单修改与改地址
    "AFT": ["D05.01", "D05.03"],   # 售后服务
    "SCHEMA": ["D03.01"],          # Schema 空值安全（接口 500 守门）
}

FR_RE = re.compile(r"\bFR-(\d{1,2}[a-z]?)\b")
#: 从追溯条目里提取 SRS 模块号（兼容 "SRS-D03.07 FR-02a" 与裸 "D03.07 FR-02a"）
SRS_RE = re.compile(r"\b(?:SRS-)?(D\d{2}\.\d{2})\b")


def srs_frs(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    return {f"FR-{m}" for m in FR_RE.findall(text)}


def build_covered() -> tuple[dict[str, set[str]], dict[str, set[str]], dict[str, int]]:
    """返回 (srs模块→显式FR集合, srs模块→模块级覆盖标记, 前缀→用例数)"""
    explicit: dict[str, set[str]] = {}
    module_level: dict[str, set[str]] = {}
    per_prefix: dict[str, int] = {}
    for fname, (req, _scene, _exp) in M.CASES.items():
        for pfx, mods in PREFIX_TO_SRS.items():
            if fname in _fnames_of(pfx):
                per_prefix[pfx] = per_prefix.get(pfx, 0) + 1
                frs = {f"FR-{m}" for m in FR_RE.findall(req)}
                srs_in_req = set(SRS_RE.findall(req))
                # 追溯条目里点名的 SRS 模块 → 其中的 FR 精确归属该模块
                for mod in srs_in_req:
                    if frs:
                        explicit.setdefault(mod, set()).update(frs)
                    else:
                        module_level.setdefault(mod, set()).add("*")
                # 未点名的模块 → 前缀覆盖的其余模块，记为模块级触达
                for mod in mods:
                    if mod not in srs_in_req:
                        module_level.setdefault(mod, set()).add("*")
                break
    return explicit, module_level, per_prefix


_FN_CACHE: dict[str, set[str]] = {}


def _fnames_of(prefix: str) -> set[str]:
    """某测试模块前缀下的所有用例函数名"""
    if prefix in _FN_CACHE:
        return _FN_CACHE[prefix]
    path = None
    for pfx, _name, _srs, f in M.MODULES:
        if pfx == prefix:
            path = ROOT / f
            break
    names: set[str] = set()
    if path and path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*(?:async\s+)?def\s+(test_\w+)", line)
            if m:
                names.add(m.group(1))
    _FN_CACHE[prefix] = names
    return names


def check_prefix_coverage() -> list[str]:
    """自检：test_case_map 里出现的每个模块前缀都必须在 PREFIX_TO_SRS 中登记

    ⚠ **复盘发现的真实缺陷**：W8 新增了 GW/ACC/SHOP 等前缀，但没更新
    PREFIX_TO_SRS → 这些模块的用例**完全不参与覆盖统计**（既不贡献显式覆盖
    也不贡献模块级触达）→ D02.01 显示 4%、D10.02 显示 18% 的**假低覆盖**。
    本自检防止以后再犯。
    """
    missing = []
    for pfx, _name, _srs, _path in M.MODULES:
        if pfx not in PREFIX_TO_SRS:
            missing.append(pfx)
    return missing


def main() -> int:
    if not REQ.exists():
        print(
            f"[FAIL] 找不到需求文档目录：{REQ}\n"
            "       应为仓库内 docs/requirements/（或仓库外 需求文档/）"
        )
        return 1
    detail = "--detail" in sys.argv
    as_json = "--json" in sys.argv

    explicit, module_level, per_prefix = build_covered()

    rows: list[dict] = []
    for mod, fname in IN_SCOPE.items():
        p = REQ / fname
        if not p.exists():
            print(f"[WARN] 缺 SRS 文件：{fname}")
            continue
        frs = srs_frs(p)
        hit = frs & explicit.get(mod, set())
        mod_level = "*" in module_level.get(mod, set())
        touched = frs if mod_level else (frs & module_level.get(mod, set()))
        miss = [] if mod_level else sorted(frs - hit - touched)
        rows.append(
            {
                "module": mod,
                "total": len(frs),
                "covered": len(frs - set(miss)),
                "miss": miss,
                "explicit": len(hit),
                "touched": len(touched),
            }
        )

    total_fr = sum(r["total"] for r in rows)
    total_cov = sum(r["covered"] for r in rows)

    if as_json:
        print(json.dumps({"rows": rows, "per_prefix": per_prefix}, ensure_ascii=False, indent=2))
        return 0

    print("=" * 96)
    print("SRS 需求条目 × 测试覆盖矩阵（计划 W1-W7 范围内）")
    print("=" * 96)
    print(
        f"{'模块':<9} {'FR条目':>6} {'已触达':>6} {'明确':>5} {'覆盖率':>7}   未触达条目"
    )
    print("-" * 96)
    for r in rows:
        pct = f"{r['covered'] / r['total'] * 100:.0f}%" if r["total"] else "-"
        print(
            f"{r['module']:<9} {r['total']:>6} {r['covered']:>6} {r['explicit']:>5} "
            f"{pct:>7}   {', '.join(r['miss']) if r['miss'] else '—'}"
        )
    print("-" * 96)
    print(
        f"{'合计':<9} {total_fr:>6} {total_cov:>6} "
        f"{'':>5} {(total_cov / total_fr * 100 if total_fr else 0):>6.0f}%"
    )
    print()
    print("口径：已触达 = 明确引用该 FR + 该模块用例整体触达（FR 追溯未写 SRS 号时降级）")
    print(f"用例总数（映射表）：{len(M.CASES)}；测试模块数：{len(M.MODULES)}")

    if detail:
        print()
        print("=== 各模块未触达 FR 明细 ===")
        for r in rows:
            if r["miss"]:
                print(f"  {r['module']}（{len(r['miss'])}）: {', '.join(r['miss'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
