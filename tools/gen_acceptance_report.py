#!/usr/bin/env python3
"""生成《MVP 内测验收报告》（PLAN-DEV-01 §3 M3 的 W10 出口交付物）

**为什么要生成器而不是手写**：验收报告的价值全在**数据准确**。
覆盖率、断言数、模块规模这些数字一手动就过时（参考「契约文档元信息漂移」教训）。
故：**客观数据全部自动采集**，人工判断部分（差距评估 / 路线图）以模板注入。

数据来源：
| 章节 | 来源 |
|---|---|
| FR 覆盖率 | `tools/review_coverage.py`（同一份判据，不重复实现） |
| 场景覆盖清单 | `deploy/ci-local-rehearsal.sh` 的 `assert_min` 行（每个 E2E 的断言数下限） |
| 性能数据 | `backend/app/scripts/load_test.py --json` / `batch_load_e2e.py --json` 的输出 |
| 模块规模 | `docs/架构/modules/M*-contract.md` + `backend/app/modules/*/service/` 实时扫描 |
| 测试规模 | `tools/test_case_map.py`（用例映射表） |
| 门禁状态 | `tools/check_arch_rules.py` / `tools/check_contract_ddl.py` 实时跑 |

用法：
    python3 tools/gen_acceptance_report.py                    # 生成
    python3 tools/gen_acceptance_report.py --check            # 只校验数据是否已过期
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
MODULES_DIR = BACKEND / "app" / "modules"
CONTRACT_DIR = ROOT / "docs" / "架构" / "modules"
OUT = ROOT / "docs" / "MVP内测验收报告.md"
CI_SCRIPT = ROOT / "deploy" / "ci-local-rehearsal.sh"
LOADTEST_JSON = ROOT / "backend" / "var" / "loadtest.json"

MODULE_ORDER = ["M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8"]


# ---------------------------------------------------------------- 采集


def _run(cmd: list[str], cwd: pathlib.Path | None = None) -> str:
    r = subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True)
    return r.stdout or ""


def collect_coverage() -> dict:
    """FR 覆盖率（复用 review_coverage 的判据）"""
    sys.path.insert(0, str(ROOT / "tools"))
    import review_coverage as RC  # type: ignore[import-not-found]

    covered, module_level, _ = RC.build_covered()
    rows = []
    total_fr = total_cov = 0
    for code in sorted(set(covered) | set(module_level)):
        # SRS 文件名带中文后缀（SRS-D10.01-组织架构与货主管理.md）→ 用 glob
        cands = sorted(RC.REQ.glob(f"SRS-{code}*.md"))
        frs = RC.srs_frs(cands[0]) if cands else set()
        n = len(frs)
        # ⚠ 口径与 review_coverage.py 一致：
        #   显式 FR（追溯条目里点名了该 FR）∪ 模块级触达（该模块有用例整体触达）
        cov_set = set(covered.get(code, set()))
        if "*" in module_level.get(code, set()):
            cov_set = set(frs)
        c = len(frs & cov_set)
        total_fr += n
        total_cov += c
        rows.append({"code": code, "fr": n, "covered": c})
    return {
        "rows": rows,
        "total_fr": total_fr,
        "total_covered": total_cov,
        "rate": round(total_cov / total_fr * 100, 1) if total_fr else 0.0,
    }


def collect_scenarios() -> list[dict]:
    """场景覆盖清单：CI 脚本里每个 E2E 的断言数下限"""
    if not CI_SCRIPT.exists():
        return []
    text = CI_SCRIPT.read_text(encoding="utf-8")
    out = []
    for m in re.finditer(
        r'assert_min\s+(\S+)\s+(\d+)\s+"([^"]+)"', text
    ):
        out.append({"log": m.group(1), "min": int(m.group(2)), "name": m.group(3)})
    return out


def collect_modules() -> list[dict]:
    """各模块规模：service 文件数 / 总行数 / 最大文件 / 对外接口数"""
    out = []
    for code in MODULE_ORDER:
        cands = sorted(CONTRACT_DIR.glob(f"{code}-*-contract.md"))
        if not cands:
            continue
        md = cands[0].read_text(encoding="utf-8")
        slug = ""
        yml = sorted(CONTRACT_DIR.glob(f"{code}-*-tables.yaml"))
        if yml:
            import yaml

            slug = (yaml.safe_load(yml[0].read_text(encoding="utf-8")) or {}).get("slug", "")
        files, lines, mx = 0, 0, 0
        if slug:
            svc = MODULES_DIR / slug / "service"
            if svc.exists():
                for f in svc.glob("*.py"):
                    if f.name == "__init__.py":
                        continue
                    files += 1
                    n = len(f.read_text(encoding="utf-8").splitlines())
                    lines += n
                    mx = max(mx, n)
        apis = len(re.findall(r"^\| `[^`]+` \|", md, re.M))
        tables = len(re.findall(r"`\w+\.\w+`", md))
        out.append(
            {
                "code": code,
                "slug": slug,
                "files": files,
                "lines": lines,
                "max_file": mx,
                "apis": apis,
            }
        )
    return out


def collect_tests() -> dict:
    """测试规模：用例映射表 + 实际测试文件数"""
    sys.path.insert(0, str(ROOT / "tools"))
    import test_case_map as TC  # type: ignore[import-not-found]

    test_files = sorted((BACKEND / "tests").glob("test_*.py"))
    mock_tests = sorted((ROOT / "mocks" / "platform" / "tests").glob("test_*.py"))
    return {
        "modules": len(TC.MODULES),
        "cases": len(TC.CASES),
        "test_files": len(test_files) + len(mock_tests),
        "mock_test_files": len(mock_tests),
    }


def collect_perf() -> dict:
    """性能数据（压测脚本的 JSON 输出；没有就标「未采集」）"""
    out: dict = {}
    if LOADTEST_JSON.exists():
        try:
            out["lua_reserve"] = json.loads(LOADTEST_JSON.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    for name, path in (
        ("batch_load", BACKEND / "var" / "batch_load.json"),
        ("batch_load", ROOT / "var" / "batch_load.json"),
    ):
        if path.exists():
            try:
                out["batch_load"] = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
            break
    return out


def collect_gates() -> list[dict]:
    """门禁状态：架构门禁 + 契约门禁（实时跑）"""
    out = []
    log = _run([str(BACKEND / ".venv" / "bin" / "python"), "tools/check_arch_rules.py"])
    m = re.search(r"合计违规 (\d+) 处", log)
    out.append({"name": "架构门禁（R1-R4）", "violations": int(m.group(1)) if m else -1})
    log2 = _run(
        [str(BACKEND / ".venv" / "bin" / "python"), "tools/check_contract_ddl.py"]
    )
    m2 = re.search(r"漂移\(PROBLEM\)\s*(\d+) 项", log2)
    out.append({"name": "契约一致性（枚举↔DDL）", "violations": int(m2.group(1)) if m2 else -1})
    return out


# ---------------------------------------------------------------- 人工章节

GAP_ANALYSIS = """\
### 7.3 仿真环境 vs 真实环境的差距评估

| 维度 | 仿真环境（MVP 内测覆盖） | 真实环境 | 差距性质 | 收敛动作 |
|---|---|---|---|---|
| 平台拉单 | mock-platform 自建 TOP 协议（签名/分页/双水位/错误码保真） | 淘系开放平台真实接口 | **协议保真度** —— 模拟器按 D02.02 契约写，但真实平台的字段与边界以官方文档为准 | 联调窗口逐字段 diff，收敛在**适配器层** |
| 平台回传 | mock-platform 接收 `logistics.online.send` | 真实发货回传 | 同上 | 同上 |
| WMS 通道 | mock-wms（指令下发/叫回/状态回放/错误注入 8 类） | 通天晓真实沙箱 | **报文保真度** + 真实 WMS 有本地编排/波次概念 | 联调窗口 0.5 周 |
| 库存真值 | 本地 MySQL + Redis Lua（五口径记账） | 同 | **无差距**（内测即真实实现） | — |
| 性能 | 本机 Docker（MySQL/Redis 容器） | 生产规格机器 | **硬件差距** —— 本机吞吐不等于生产吞吐 | M4 前用生产规格机复跑 `load_test.py` |
| 数据量 | 造单引擎百单级 | 生产百万级历史单 | **数据规模差距** —— 索引与归档策略未在生产量级验证 | M4 补归档任务 + 慢查询巡检 |
| 合规资质 | 无（未申请平台资质） | 需淘系/通天晓资质 | **流程差距**（非技术） | 商务侧推进，与开发并行 |
"""

ROADMAP = """\
### 8. M4 生产化路线图建议

**准入前置**（M3 gate④ 通过后启动）：
1. 淘系店铺授权到位（联调窗口）
2. 通天晓 WMS 沙箱账号 + 报文文档
3. 生产规格机器（≥8C16G）+ 独立 MySQL/Redis

**M4 阶段建议（按依赖顺序）**：

| 阶段 | 内容 | 出口标准 |
|---|---|---|
| M4-0 联调窗口 | 真实平台 + 真实 WMS 逐字段 diff，收敛在适配器层 | 真实环境跑通正向 20 单 + 售后 5 单 |
| M4-1 缺口补齐 | 本报告 §7.2 列出的已知缺口按优先级补 | 缺口清单归零或转 M5 |
| M4-2 性能与容量 | 生产规格机复跑压测 + 数据量级压测 + 归档任务 | 目标吞吐达标 · 无慢查询 |
| M4-3 可观测 | 监控看板从 3 指标扩到全量（拉单水位/审单积压/回传失败/WMS 健康） | 故障可发现、可定位 |
| M4-4 灰度 | 首品牌小流量灰度（建议 1 店 → 3 店 → 全量） | 每档观察 24h 无资金/履约差错 |
| M4-5 验收 | 生产化验收报告 + 运维手册 + 应急预案 | 生产上线评审通过 |

**不进入 M4 的项**（仍按 PLAN-DEV-01 §1.2 OUT 清单后置）：
采购全域（D06）· 财务全域（D08）· 报表全域（D11）· 合单（D03.05）·
促销赠品（D03.14）· 特殊单型/即时零售/O2O/跨境（D03.10-12/15）· 客服 360（D03.16）·
品牌方门户（D10.04）· OA 审批集成（D10.05）· 抖音等 5 平台适配器
"""


# ---------------------------------------------------------------- 渲染


def render(cov: dict, scen: list[dict], mods: list[dict], tests: dict,
            perf: dict, gates: list[dict]) -> str:
    L: list[str] = []
    A = L.append

    A("# KT-OMS MVP 内测验收报告")
    A("")
    A("> PLAN-DEV-01 V1.1 §3 · M3（W9-W10）出口交付物")
    A("> ")
    A("> **本报告由 `tools/gen_acceptance_report.py` 生成** —— 客观数据（覆盖率 / 场景清单 /")
    A("> 性能 / 模块规模 / 门禁状态）全部实时采集，人工判断章节（差距评估 / 路线图）以模板注入。")
    A("> 数据过期请跑 `python3 tools/gen_acceptance_report.py` 重新生成。")
    A("")

    # 1 摘要
    A("## 一、验收摘要")
    A("")
    A("| 指标 | 数值 | 说明 |")
    A("|---|---|---|")
    A(f"| 计划内 FR 条目 | {cov['total_fr']} | SRS 逐条抽取 |")
    A(f"| 已触达 FR | {cov['total_covered']} | 覆盖率 **{cov['rate']}%** |")
    A(f"| 端到端场景套件 | {len(scen)} | 每个都带断言数下限（防静默跳过） |")
    A(f"| 端到端断言数下限合计 | {sum(s['min'] for s in scen)} | 实际断言 ≥ 下限才算过 |")
    A(f"| 单元/集成测试用例 | {tests['cases']} | 映射 {tests['modules']} 个测试模块 |")
    A(f"| 测试文件 | {tests['test_files']} | 含 mock 模拟器 {tests['mock_test_files']} 个 |")
    A(f"| 业务模块 | {len(mods)} | 契约化模块（M1-M8） |")
    A(f"| 架构门禁 | {', '.join(f'{g['name']} {g['violations']}' for g in gates)} | 违规即阻断 |")
    A("")

    # 2 场景覆盖
    A("## 二、场景覆盖清单")
    A("")
    A("> 来源：`deploy/ci-local-rehearsal.sh` 的 `assert_min` 声明 ——")
    A("> 每个端到端套件在 CI 里必须打满这么多条 `[PASS]`，否则**失败**")
    A("> （防止「数据前置条件不满足 → 断言被 if 跳过 → 门禁显示通过」的假绿）。")
    A("")
    A("| 场景套件 | 断言数下限 |")
    A("|---|---|")
    for s in scen:
        A(f"| {s['name']} | {s['min']} |")
    A(f"| **合计** | **{sum(s['min'] for s in scen)}** |")
    A("")

    # 3 模块规模
    A("## 三、模块交付规模")
    A("")
    A("| 模块 | slug | service 文件 | 总行数 | 最大单文件 | 契约接口行 |")
    A("|---|---|---|---|---|---|")
    for m in mods:
        A(
            f"| {m['code']} | {m['slug']} | {m['files']} | {m['lines']:,} "
            f"| {m['max_file']} | {m['apis']} |"
        )
    A("")

    # 4 性能
    A("## 四、性能数据")
    A("")
    lr = perf.get("lua_reserve")
    if lr:
        A("### 4.1 Lua 预占并发压测（复跑 M0 风险点②基线）")
        A("")
        A("| 并发 | 请求数 | 耗时(ms) | 吞吐(次/秒) | P50(ms) | P95(ms) | P99(ms) | 零超卖 |")
        A("|---|---|---|---|---|---|---|---|")
        for r in lr.get("results", []):
            if r["name"] != "lua_reserve_concurrent":
                continue
            A(
                f"| {r['concurrency']} | {r['total']} | {r['elapsed_ms']:.1f} "
                f"| {r['rps']:.1f} | {r['p50_ms']:.2f} | {r['p95_ms']:.2f} | {r['p99_ms']:.2f} "
                f"| {'✓' if r['succeeded'] == 100 and r['freeze'] == 100 else '✗'} |"
            )
        A("")
        A(f"> 断言：{lr.get('assertions', {}).get('passed', 0)} 通过 / "
          f"{lr.get('assertions', {}).get('failed', 0)} 失败")
        A("")
        A("> **零超卖**是硬不变量：无论并发多少，抢 100 件必须恰好成功 100 件、冻结数 == 100。")
        A("> M0 声称 200 并发耗时 1.2s —— 本次在本机 Docker 环境复跑见上表。")
    else:
        A("### 4.1 Lua 预占并发压测")
        A("")
        A("⚠ 未采集（跑 `backend/.venv/bin/python -m app.scripts.load_test "
          "--json backend/var/loadtest.json` 生成）")
        A("")

    bl = perf.get("batch_load")
    A("")
    A("### 4.2 端到端批量链路吞吐")
    A("")
    if bl:
        A("```json")
        A(json.dumps(bl, ensure_ascii=False, indent=2)[:2000])
        A("```")
    else:
        A("⚠ 未采集（跑 `backend/.venv/bin/python -m app.scripts.batch_load_e2e "
          "--with-mock --json backend/var/batch_load.json` 生成）")
    A("")

    # 5 覆盖率
    A("## 五、需求覆盖")
    A("")
    A("| SRS 模块 | FR 条目 | 已触达 | 覆盖率 |")
    A("|---|---|---|---|")
    for r in cov["rows"]:
        rate = round(r["covered"] / r["fr"] * 100, 1) if r["fr"] else 0.0
        A(f"| {r['code']} | {r['fr']} | {r['covered']} | {rate}% |")
    A(f"| **合计** | **{cov['total_fr']}** | **{cov['total_covered']}** | **{cov['rate']}%** |")
    A("")
    A("> 口径：与 `tools/review_coverage.py` 一致 —— 「已触达」= 明确引用该 FR 编号")
    A("> 或该模块用例整体触达（FR 追溯未写 SRS 号时降级）。")
    A("> **测试用例追溯的精确率**（用例的追溯条目里明确写了 FR 编号）另见")
    A("> `docs/需求覆盖缺口清单.md` —— 两个口径都诚实呈现，不混为一谈。")
    A("")

    # 6 门禁
    A("## 六、门禁与质量基线")
    A("")
    A("| 门禁 | 违规数 |")
    A("|---|---|")
    for g in gates:
        A(f"| {g['name']} | {g['violations']} |")
    A("")
    A("CI 等价流程（`deploy/ci-local-rehearsal.sh`）逐项：ruff · mypy · pytest ·")
    A("模型↔DDL 一致性 · 契约一致性 · 架构门禁 · 契约元信息一致性 · 跨域数据一致性体检 ·")
    A("8 个端到端套件 · 前端 type-check + build。")
    A("")

    # 7 缺口
    A("## 七、已知缺口与边界")
    A("")
    A("### 7.1 功能缺口（按优先级）")
    A("")
    A("| # | 缺口 | 影响 | 归属 |")
    A("|---|---|---|---|")
    A("| G1 | **售后报文自动同步**（D05.01 FR-01a）未实现 —— 售后申请单目前只能"
      "经 API 手工建，平台侧售后消息不会自动落 OMS | 真实场景下售后单需人工录入，"
      "违背「平台售后自动进单」的产品预期 | 建议 M4-1 |")
    A("| G2 | **D01.03 规则引擎覆盖 10.6%**（47 条 FR 仅触达 5 条） | 规则引擎的 FR "
      "多为框架设计级条目（条件求值/规则缓存/版本快照），实际由审单链间接覆盖 | "
      "建议 M4-1 补规则引擎专项测试 |")
    A("| G3 | **D10.02 租户账户与角色覆盖 48.5%**（17 条 FR 未触达） | 多账号/角色/权限"
      "组合的场景化验证不足 | 建议 M4-1 补测 |")
    A("| G4 | D02.02 平台适配器 FR **精确追溯**为 0（D02.01/D02.04/D02.05 同） | "
      "**追溯口径问题非功能缺失** —— 能力已实现并被其它 FR 覆盖 | 补追溯即可 |")
    A("| G5 | 性能数据取自本机 Docker，未在生产规格机复跑 | 吞吐数字不可直接外推 | M4-2 |")
    A("| G6 | redis-py 8.x 默认连接池上限 100 —— 业务侧 >100 并发打 Redis 会抛 "
      "`MaxConnectionsError` | **生产风险**：压测时实测触发；业务单例连接池未上调 | "
      "建议 M4-1 上调 `get_redis()` 的 max_connections |")
    A("| G7 | **并发拉单触发 MySQL 死锁 → 丢单**（`gw_order_buffer` + "
      "`gw_order_buffer_item` 插入锁顺序冲突，1213 Deadlock） | **高**：批量内测实测 "
      "并发 3 → 死锁 3/20、并发 10 → 死锁 7/20；死锁订单**没进 OMS**。"
      "当前生产是串行轮询（不触发），但 M4 联调期需要「并发补偿拉」 | "
      "建议 M4-1：① 死锁重试（幂等键保证重试安全）② 统一加锁顺序 |")
    A("| G8 | **未发货仅退款 → 发货拦截未实现** —— 履约侧（发货单创建/推仓）"
      "**完全不检查订单是否有在途售后** | **高**：W9 计划承诺的功能漏做；"
      "已退款订单仍可能继续发货 → 资金与履约差错 | 建议 M4-1 优先补 |")
    A("")
    A("### 7.2 边界（PLAN-DEV-01 §1.2 OUT 清单）")
    A("")
    A("以下能力**本期明确不实现**（架构预留位已在 IN 项中留好），不属于缺陷：")
    A("")
    A("合单（D03.05）· 促销赠品（D03.14）· 特殊单型 / 即时零售 / O2O / 跨境")
    A("（D03.10-12/15）· 客服 360 视图（D03.16）· 采购全域（D06）· 财务全域（D08）·")
    A("品牌方门户（D10.04）· OA 审批集成（D10.05）· 报表全域（D11，仅留监控看板最小版）·")
    A("价格管理（D04.11）· 抖音等 5 平台适配器 · 电子面单（D09.05）·")
    A("盘点/调拨/借调/成本核算/批次效期 SN（D04.05-07/09，表已建、服务后置）")
    A("")
    A(GAP_ANALYSIS)

    # 8 路线图
    A("## 八、下一步")
    A("")
    A(ROADMAP)

    # 9 附
    A("---")
    A("")
    A("## 附：数据来源与复现")
    A("")
    A("| 内容 | 复现命令 |")
    A("|---|---|")
    A("| 本报告 | `python3 tools/gen_acceptance_report.py` |")
    A("| FR 覆盖率 | `python3 tools/review_coverage.py` |")
    A("| 需求缺口清单 | `python3 tools/gen_gap_report.py` |")
    A("| 架构门禁 | `backend/.venv/bin/python tools/check_arch_rules.py` |")
    A("| 契约一致性 | `backend/.venv/bin/python tools/check_contract_ddl.py` |")
    A("| 压测 | `backend/.venv/bin/python -m app.scripts.load_test --json backend/var/loadtest.json` |")
    A("| CI 全量复演 | `bash deploy/ci-local-rehearsal.sh` |")
    A("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只检查数据是否与仓库现状一致")
    args = ap.parse_args()

    cov = collect_coverage()
    scen = collect_scenarios()
    mods = collect_modules()
    tests = collect_tests()
    perf = collect_perf()
    gates = collect_gates()
    text = render(cov, scen, mods, tests, perf, gates)

    if args.check:
        if not OUT.exists():
            print(f"✗ 报告不存在：{OUT}")
            return 1
        cur = OUT.read_text(encoding="utf-8")
        if cur == text:
            print("✓ 验收报告与仓库现状一致")
            return 0
        print("✗ 验收报告已过时（跑 tools/gen_acceptance_report.py 重新生成）")
        return 1

    OUT.write_text(text, encoding="utf-8")
    print(f"✓ 已生成 {OUT.relative_to(ROOT)}（{len(text.splitlines())} 行）")
    print(
        f"  FR 覆盖 {cov['total_covered']}/{cov['total_fr']}（{cov['rate']}%）"
        f" · 场景套件 {len(scen)} · 断言下限合计 {sum(s['min'] for s in scen)}"
        f" · 门禁违规 {sum(g['violations'] for g in gates)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
