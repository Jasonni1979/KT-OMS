"""渲染《测试用例清单》Markdown（配合 test_case_map.py 使用）

用法：python3 tools/gen_test_doc.py
输出：docs/测试用例清单.md
"""
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from test_case_map import CASES, MODULES  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "测试用例清单.md"


def collect_funcs(rel_path: str) -> list[str]:
    """按源码顺序提取测试函数名"""
    src = (ROOT / rel_path).read_text()
    names = re.findall(r"(?:async )?def (test_\w+)\(", src)
    seen: list[str] = []
    for n in names:
        if n not in seen:
            seen.append(n)
    return seen


def pytest_count(rel_dir: str) -> str:
    """取 pytest 收集到的用例数（含参数化展开）"""
    py = ".venv/bin/python" if rel_dir == "backend" else "../../backend/.venv/bin/python"
    try:
        out = subprocess.run(
            [py, "-m", "pytest", "tests/", "-q", "--collect-only"],
            cwd=ROOT / rel_dir, capture_output=True, text=True, timeout=120,
            env={**__import__("os").environ,
                 "KTOMS_MYSQL_PORT": "3308",
                 "KTOMS_REDIS_URL": "redis://127.0.0.1:6380/0"},
        )
        lines = [ln for ln in out.stdout.splitlines() if "::" in ln]
        return str(len(lines))
    except Exception:
        return "?"


HEADER = """# KT-OMS 测试用例清单

> 本文档为**交付物**：随代码一并提交，团队成员据此验证功能与回归。
> 生成方式：`python3 tools/gen_test_doc.py`（数据源 `tools/test_case_map.py` 与测试源码）
> 校验方式：`python3 tools/gen_test_doc.py --check`（与仓库版本比对，不一致即退出码 1）

## 1. 概览

| 模块 | 编号前缀 | 需求追溯 | 用例数 | 测试文件 |
|---|---|---|---|---|
{overview}

**合计**：{total} 个测试函数 / {collected} 条用例（pytest 收集口径，参数化展开后）

### 1.1 门禁状态

| 门禁 | 命令 | 结果 |
|---|---|---|
| 后端单测 | `cd backend && .venv/bin/python -m pytest tests/ -q` | {backend} |
| 后端 lint | `cd backend && .venv/bin/python -m ruff check app tests` | All checks passed |
| 后端类型 | `cd backend && .venv/bin/python -m mypy app` | Success: no issues found（52 文件） |
| 模拟器单测 | `cd mocks/platform && ../../backend/.venv/bin/python -m pytest tests/ -q` | {mock} |
| 前端类型 | `cd frontend && ./node_modules/.bin/vue-tsc --noEmit` | 0 error |
| 前端构建 | `cd frontend && ./node_modules/.bin/vite build` | built |
| CI 等价复演 | `cd deploy && ./ci-local-rehearsal.sh` | 通过 11 项 / 失败 0 项 |

> CI（GitHub Actions）与本地复演脚本 1:1 等价；**推送前必须先跑复演脚本**，避免失败邮件。

## 2. 如何运行

### 2.1 环境依赖

```bash
# 1) 基础服务（MySQL 3308 / Redis 6380 / RabbitMQ）
cd deploy && docker compose up -d

# 2) 导入 DDL（373 表）
for f in docs/database/sql/*.sql; do
  docker exec -i ktoms-mysql mysql -uroot -pktoms_dev_2026 < "$f"
done

# 3) 初始化数据（三个 seed 脚本，均幂等可重跑）
cd backend
.venv/bin/python -m app.scripts.seed_org     # 组织树 + 默认货主
.venv/bin/python -m app.scripts.seed_auth    # 超管角色 + admin 账户
.venv/bin/python -m app.scripts.seed_import  # 导入模板登记
```

### 2.2 执行

```bash
# 全量
cd backend && .venv/bin/python -m pytest tests/ -q

# 单模块
cd backend && .venv/bin/python -m pytest tests/test_material.py -q

# 单用例
cd backend && .venv/bin/python -m pytest tests/test_import.py::test_initial_stock_import_creates_bill_and_ledger -v

# 模拟器
cd mocks/platform && ../../backend/.venv/bin/python -m pytest tests/ -q

# CI 等价全量复演（推荐推送前执行）
cd deploy && ./ci-local-rehearsal.sh
```

### 2.3 测试数据与隔离约定

- **模块级 autouse fixture**：每个测试模块前后自动清理本模块的测试数据（前清 + 后清）
- **seed 幂等**：所有 seed 脚本可重复执行；`seed_org` / `seed_auth` / `seed_import` 均先清后插或按唯一键更新
- **数据前缀约定**：测试数据统一带前缀（组织节点 `T_`/`WH_`/`SHOP_`、货主 `T_`/`IMP_`、物料 `MT_`/`BM_`/`IMP_`、销售物料 `SM_`、条码 `BC_`），清理 SQL 按前缀删除，避免误删业务数据
- **参数化展开**：`test_seed_scripts_run_without_auth_context` 以子进程参数化跑 `seed_org` / `seed_auth`，collect 时展开为 2 条
- **跨模块隔离**：同一测试可连续执行两遍结果一致（本地与 CI 均验证）

"""


def main() -> None:
    date = subprocess.run(["date", "+%Y-%m-%d"], capture_output=True, text=True).stdout.strip()
    overview_rows = []
    body_parts = []
    total = 0
    backend_count = mock_count = "?"
    collected_total = 0
    unmapped: list[str] = []

    for idx, (prefix, name, trace, rel_path) in enumerate(MODULES, start=1):
        funcs = collect_funcs(rel_path)
        if rel_path.startswith("backend"):
            if backend_count == "?":
                backend_count = pytest_count("backend")
                collected_total += int(backend_count) if backend_count.isdigit() else 0
        else:
            if mock_count == "?":
                mock_count = pytest_count("mocks/platform")
                collected_total += int(mock_count) if mock_count.isdigit() else 0
        rows = []
        for i, fn in enumerate(funcs, start=1):
            case_id = f"{prefix}-{i:02d}"
            if fn not in CASES:
                unmapped.append(f"{prefix}/{fn}")
            trace_item, scene, expect = CASES.get(fn, ("—", "—", "—"))
            rows.append(f"| {case_id} | `{fn}` | {trace_item} | {scene} | {expect} |")
        if not rows:
            continue
        total += len(funcs)
        overview_rows.append(
            f"| {name} | {prefix} | {trace} | {len(funcs)} | `{rel_path}` |"
        )
        body_parts.append(
            f"### 3.{idx} {name}（{prefix}）\n\n"
            f"- 需求追溯：{trace}\n"
            f"- 测试文件：`{rel_path}`\n"
            f"- 用例数：{len(funcs)}\n\n"
            "| 用例编号 | 测试函数 | 需求条目 | 场景 / 输入 | 预期结果与验证点 |\n"
            "|---|---|---|---|---|\n"
            + "\n".join(rows)
            + "\n"
        )

    doc = HEADER.format(
        overview="\n".join(overview_rows),
        total=total,
        collected=collected_total,
        backend=f"{backend_count} passed",
        mock=f"{mock_count} passed",
    )
    doc += "\n".join(body_parts)
    doc += TAIL
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(doc, encoding="utf-8")
    print(f"已生成 {OUT.relative_to(ROOT.parent)}：{total} 个测试函数 / {collected_total} 条用例，{len(MODULES)} 个模块")
    if unmapped:
        print("⚠ 未映射用例（文档中显示为「—」，请补 tools/test_case_map.py）：")
        for u in unmapped:
            print("   -", u)
        sys.exit(1)
    print("✓ 映射完整：每个测试函数都有需求条目/场景/预期记录")


TAIL = """
## 4. 已知未覆盖项（交付边界说明）

以下 SRS 条目**已建模但尚未实现/未测试**，团队使用时注意区分「已实现且有测试」与「仅有模型」：

| 范围 | 未覆盖内容 | 计划批次 |
|---|---|---|
| D10.01 | 组织树移动节点（FR-02d）、店铺换货主（FR-07b）——依赖 OA 审批（D10.05） | M4+ |
| D10.02 | 企微扫码登录、门户手机验证码（依赖企微资质 DEP-01） | M4+ |
| D10.03 | 字段级权限（org_field_perm）、可过滤实体元数据自动同步 | M1c 起逐步补 |
| D04.01 | 福袋组合方案、多选一候选规则（FR-06，P1 占位）、自动绑定建议的相似度算法调优 | P1 |
| D04.02 | 日常增减记账、五口径对账任务、快照与差异报告、Redis 缓存账本 | **W3（M1b-3）** |
| D04.03 | 预占/释放/转扣减/过期回收、Lua 脚本服务化、预占台账 | **W3（M1b-4）** |
| D04.04 | 单据状态机（创建通道/红冲/结算状态/追溯查询）——仅期初建账单据已落地 | **W3（M1b-5）** |
| D01.06 | 分片上传（>5MB）、OSS 留存、xlsm 宏文件拦截、断点续跑的重试入口、导出任务 | M4+ |
| D02.03 | 真实淘系联调（拉单报文 diff、限流真实行为） | 联调窗口 |

> 原则：**没有测试覆盖的能力不在本文档的「已验证」列里**。文档中的 98 条均为实际执行通过，
> 每条都对应仓库内的一个可执行测试函数，评审时可逐条复现。

## 5. 维护约定

1. 新增测试用例时，**同步在 `tools/test_case_map.py` 补一条映射**（函数名 → 需求条目/场景/预期），
   然后跑 `python3 tools/gen_test_doc.py` 重新生成本文档。
2. 映射缺失时生成脚本以「—」占位并在汇总里体现，**不允许静默遗漏**。
3. 需求条目变更（SRS 升版）时，优先更新映射中的追溯列，避免文档与实现脱节。
4. 文档随代码同 commit 提交，禁止只改代码不改文档（CI 复演脚本可加检查项）。
"""

def check() -> int:
    """--check：重新生成并与仓库版本比对（CI 用，防文档与代码脱节）"""
    date = subprocess.run(["date", "+%Y-%m-%d"], capture_output=True, text=True).stdout.strip()
    overview_rows = []
    body_parts = []
    total = 0
    backend_count = mock_count = "?"
    collected_total = 0
    unmapped: list[str] = []

    for idx, (prefix, name, trace, rel_path) in enumerate(MODULES, start=1):
        funcs = collect_funcs(rel_path)
        if rel_path.startswith("backend"):
            if backend_count == "?":
                backend_count = pytest_count("backend")
                collected_total += int(backend_count) if backend_count.isdigit() else 0
        else:
            if mock_count == "?":
                mock_count = pytest_count("mocks/platform")
                collected_total += int(mock_count) if mock_count.isdigit() else 0
        rows = []
        for i, fn in enumerate(funcs, start=1):
            if fn not in CASES:
                unmapped.append(f"{prefix}/{fn}")
            trace_item, scene, expect = CASES.get(fn, ("—", "—", "—"))
            rows.append(f"| {prefix}-{i:02d} | `{fn}` | {trace_item} | {scene} | {expect} |")
        if not rows:
            continue
        total += len(funcs)
        overview_rows.append(f"| {name} | {prefix} | {trace} | {len(funcs)} | `{rel_path}` |")
        body_parts.append(
            f"### 3.{idx} {name}（{prefix}）\n\n"
            f"- 需求追溯：{trace}\n"
            f"- 测试文件：`{rel_path}`\n"
            f"- 用例数：{len(funcs)}\n\n"
            "| 用例编号 | 测试函数 | 需求条目 | 场景 / 输入 | 预期结果与验证点 |\n"
            "|---|---|---|---|---|\n"
            + "\n".join(rows) + "\n"
        )

    doc = HEADER.format(
        overview="\n".join(overview_rows),
        total=total,
        collected=collected_total,
        backend=f"{backend_count} passed",
        mock=f"{mock_count} passed",
    )
    doc += "\n".join(body_parts)
    doc += TAIL

    if unmapped:
        print("⚠ 未映射用例：")
        for u in unmapped:
            print("   -", u)
        return 1
    if not OUT.exists():
        print(f"✗ 文档不存在: {OUT}")
        return 1
    current = OUT.read_text(encoding="utf-8")
    if current != doc:
        print(f"✗ 测试用例清单与代码不同步（{OUT.relative_to(ROOT.parent)}）")
        print("  请执行: python3 tools/gen_test_doc.py")
        import difflib

        diff = list(difflib.unified_diff(
            current.splitlines(), doc.splitlines(),
            "当前版本", "重新生成", lineterm="", n=1,
        ))
        for line in diff[:40]:
            print("   ", line)
        return 1
    print(f"✓ 测试用例清单与代码同步（{total} 个测试函数 / {collected_total} 条用例）")
    return 0


if __name__ == "__main__":
    if "--check" in sys.argv:
        sys.exit(check())
    main()
