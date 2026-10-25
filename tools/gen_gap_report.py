"""复盘工具：FR 逐条精确覆盖 + 未覆盖缺口清单

数据源：`tools/test_case_map.py` 的 CASES（需求追溯条目含具体 FR 编号）。
对计划 W1-W7 范围内的 SRS 模块，逐条 FR 判定：
- **精确覆盖**：某条用例的追溯条目明确写了该 FR
- **模块级覆盖**：该模块有用例但追溯只写到 SRS 级（降级触达，不算精确）
- **未覆盖**：既无精确覆盖也无模块级用例

产出 `docs/需求覆盖缺口清单.md`：逐模块列出未精确覆盖的 FR，并按
「本期不实现 / 遗漏待补」两类标注。

用法：
    cd KT-OMS && python3 tools/gen_gap_report.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT.parent / "需求文档"
OUT = ROOT / "docs" / "需求覆盖缺口清单.md"
sys.path.insert(0, str(ROOT / "tools"))

import test_case_map as M  # noqa: E402

#: 计划 W1-W7 交付范围内的 SRS 模块（模块号 → (文件名, 中文名)）
IN_SCOPE: dict[str, tuple[str, str]] = {
    "D10.01": ("SRS-D10.01-组织架构与货主管理.md", "组织架构与货主管理"),
    "D10.02": ("SRS-D10.02-租户账户与角色.md", "租户账户与角色"),
    "D10.03": ("SRS-D10.03-多维数据权限.md", "多维数据权限"),
    "D09.01": ("SRS-D09.01-仓库与多WMS路由.md", "仓库与多WMS路由"),
    "D04.01": ("SRS-D04.01-商品与物料管理.md", "商品与物料管理"),
    "D01.06": ("SRS-D01.06-导入导出中心.md", "导入导出中心"),
    "D04.02": ("SRS-D04.02-库存记账.md", "库存记账"),
    "D04.03": ("SRS-D04.03-预占与释放.md", "预占与释放"),
    "D04.04": ("SRS-D04.04-出入库单据与流水.md", "出入库单据与流水"),
    "D02.01": ("SRS-D02.01-平台接入框架.md", "平台接入框架"),
    "D02.02": ("SRS-D02.02-平台适配器.md", "平台适配器"),
    "D02.03": ("SRS-D02.03-拉单与消息接收.md", "拉单与消息接收"),
    "D04.08": ("SRS-D04.08-可售计算与平台同步.md", "可售计算与平台同步"),
    "D03.01": ("SRS-D03.01-订单接入与创建.md", "订单接入与创建"),
    "D03.02": ("SRS-D03.02-审单引擎.md", "审单引擎"),
    "D03.03": ("SRS-D03.03-人工审单工作台.md", "人工审单工作台"),
    "D03.04": ("SRS-D03.04-拆单策略中心.md", "拆单策略中心"),
    "D03.06": ("SRS-D03.06-配货分仓.md", "配货分仓"),
    "D03.07": ("SRS-D03.07-发货单管理.md", "发货单管理"),
    "D09.02": ("SRS-D09.02-出库指令与回传.md", "出库指令与回传"),
    "D02.04": ("SRS-D02.04-回传中心.md", "回传中心"),
    "D02.05": ("SRS-D02.05-失败重试与对账.md", "失败重试与对账"),
    "D02.06": ("SRS-D02.06-店铺授权管理.md", "店铺授权管理"),
}

#: 本期不实现的 FR 标注（key = 模块号，value = {FR: 原因}）
#: 依据：PLAN-DEV-01 V1.1 §1.1 IN/OUT 清单 + 各周交付范围
NOT_IMPLEMENTED: dict[str, dict[str, str]] = {
    "D02.01": {
        "FR-01c": "异步调用/MQ 应答（M1c 用同步投递替代）",
        "FR-02a": "platform_app 配置表（当前单应用内置）",
        "FR-02b": "店铺-应用绑定分流（MVP 单应用）",
        "FR-02c": "配置热更新广播（MVP 单实例）",
        "FR-03a": "SignStrategy 可插拔策略（当前平台内联签名）",
        "FR-03b": "JSON 参数规范化（当前仅 JSON 参数场景）",
        "FR-03c": "入站验签复用",
        "FR-04a": "凭证缓存回源解密",
        "FR-04b": "AUTH 失效事件 → 续期",
        "FR-04c": "续期后重放",
        "FR-05d": "自适应降速",
        "FR-06a": "方法名字典表（当前适配器内联映射）",
        "FR-06b": "透传通道 common.passthrough",
        "FR-06d": "错误码字典管理后台",
        "FR-07c": "报文敏感字段脱敏（D01.05 PIPL 未接）",
        "FR-07d": "日志分区与生命周期",
        "FR-07e": "日志查询与人工重放",
        "FR-08a": "调用指标上报",
        "FR-08b": "告警规则",
    },
    "D02.06": {
        "FR-02a": "授权 URL 构建（MVP 仿真凭证，无真实 OAuth）",
        "FR-02b": "授权回调处理",
        "FR-02c": "平台差异授权适配",
        "FR-02d": "授权模式兼容",
        "FR-03a": "凭证信封加密落库",
        "FR-03b": "凭证缓存",
        "FR-03c": "凭证取用审计",
        "FR-03d": "旧凭证保留策略",
        "FR-04a": "授权有效期监控",
        "FR-04b": "自动续期",
        "FR-04c": "过期告警分级",
        "FR-04d": "失效事件消费",
        "FR-05b": "状态恢复联动",
        "FR-06b": "店铺-物流绑定",
        "FR-06d": "绑定变更即时生效",
        "FR-07a": "授权看板",
        "FR-07b": "一键操作",
    },
    "D10.02": {
        "FR-01c": "门户租户-货主关联隔离（P2 门户）",
        "FR-02c": "企微扫码登录（P2）",
        "FR-03a": "外部租户账户档案（P2 门户）",
        "FR-03b": "短信验证码登录（P2）",
        "FR-03c": "自助注册审核流（P2）",
        "FR-03d": "运营代建（P2）",
        "FR-03e": "品牌方子账户管理（P2）",
        "FR-04d": "角色删除前绑定校验（MVP 角色不提供删除入口）",
        "FR-06a": "入职批量开户（P2）",
        "FR-06b": "转岗变更审计（MVP 无转岗流程）",
        "FR-06d": "外部账户注销（P2）",
        "FR-06e": "僵尸账户治理（定时任务，M3 后）",
        "FR-07a": "IdP 配置结构（P2）",
        "FR-07b": "OIDC 对接（P2）",
    },
}

FR_RE = re.compile(r"\bFR-(\d{1,2}[a-z]?)\b")
SRS_RE = re.compile(r"\b(?:SRS-)?(D\d{2}\.\d{2})\b")


def fr_summaries(path: Path) -> dict[str, str]:
    """抽取每个 FR 条目的首句摘要（便于判读缺口）"""
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*-\s*(FR-\d{1,2}[a-z]?)\s+(.*)", line)
        if not m:
            continue
        fr, body = m.group(1), m.group(2).strip()
        body = body.replace("**", "")
        # 截到第一个句号/分号，最多 60 字
        cut = body
        for sep in ("；", ";", "。", "——"):
            if sep in cut:
                cut = cut.split(sep)[0]
                break
        out[fr] = cut.strip()[:60]
    return out


def main() -> int:
    # 收集：模块 → 精确覆盖的 FR 集合；模块 → 是否有模块级用例
    exact: dict[str, set[str]] = {}
    mod_level: set[str] = set()
    for _fn, (req, _sc, _exp) in M.CASES.items():
        frs = {f"FR-{m}" for m in FR_RE.findall(req)}
        mods = set(SRS_RE.findall(req))
        for mod in mods:
            if frs:
                exact.setdefault(mod, set()).update(frs)
            else:
                mod_level.add(mod)

    rows: list[dict] = []
    for mod, (fname, cn) in IN_SCOPE.items():
        p = REQ / fname
        if not p.exists():
            print(f"[WARN] 缺 SRS 文件：{fname}")
            continue
        frs = {f"FR-{m}" for m in FR_RE.findall(p.read_text(encoding="utf-8"))}
        summ = fr_summaries(p)
        hit = frs & exact.get(mod, set())
        missing = sorted(frs - hit)
        ni = NOT_IMPLEMENTED.get(mod, {})
        rows.append(
            {
                "module": mod,
                "name": cn,
                "total": len(frs),
                "exact": len(hit),
                "missing": missing,
                "not_impl": {f: ni[f] for f in missing if f in ni},
                "to_fix": [f for f in missing if f not in ni],
                "summ": summ,
                "mod_level": mod in mod_level,
            }
        )

    tot_fr = sum(r["total"] for r in rows)
    tot_exact = sum(r["exact"] for r in rows)
    tot_missing = sum(len(r["missing"]) for r in rows)
    tot_ni = sum(len(r["not_impl"]) for r in rows)
    tot_fix = sum(len(r["to_fix"]) for r in rows)

    lines: list[str] = []
    lines.append("# KT-OMS 需求覆盖缺口清单（复盘产出）")
    lines.append("")
    lines.append(
        "> 生成方式：`python3 tools/gen_gap_report.py`（数据源 `tools/test_case_map.py`）  "
    )
    lines.append(
        "> 范围：PLAN-DEV-01 V1.1 §3 M2 · W1–W7 已交付模块（22 个 SRS）  "
    )
    lines.append(
        "> 生成日期：2026-10-25（复盘）"
    )
    lines.append("")
    lines.append("## 1. 总览")
    lines.append("")
    lines.append("| 指标 | 数值 |")
    lines.append("|---|---|")
    lines.append(f"| 计划内 FR 条目总数 | {tot_fr} |")
    lines.append(f"| 已精确覆盖（用例追溯明确到该 FR） | {tot_exact} |")
    lines.append(f"| 未精确覆盖 | {tot_missing} |")
    lines.append(f"| ├ 本期不实现（已标注原因，进 OUT 清单） | {tot_ni} |")
    lines.append(f"| └ SRS 设计级条目（MVP 未实现，未逐条标注） | {tot_fix} |")
    lines.append(f"| 精确覆盖率 | {tot_exact / tot_fr * 100:.0f}% |")
    lines.append("")
    lines.append(
        "> **「精确覆盖」口径**：某条测试用例的需求追溯条目里明确写了该 FR 编号。"
        "模块级用例（追溯只写到 SRS 级）不计入精确覆盖。"
    )
    lines.append("")
    lines.append(
        "> **如何读这份清单**：SRS 是完整设计稿（单模块 16–53 条 FR），"
        "而 MVP 按 PLAN-DEV-01 的周计划裁剪实现，因此「未精确覆盖」并不等于「缺陷」。"
        "其中："
    )
    lines.append("")
    lines.append("- **本期不实现** —— 有明确范围依据（配置化/后台/看板/OAuth 等），已进 OUT 清单；")
    lines.append(
        "- **SRS 设计级条目** —— SRS 描述了完整形态但 MVP 未做的能力（多附摘要），"
        "需在 W8+ 排期时逐条决策「做 / 不做 / 何时做」。"
    )
    lines.append("")
    lines.append("## 2. 模块覆盖明细")
    lines.append("")
    lines.append("| 模块 | 名称 | FR 总数 | 精确覆盖 | 精确率 | 未精确 | 本期不实现 | 遗漏待补 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for r in rows:
        pct = f"{r['exact'] / r['total'] * 100:.0f}%" if r["total"] else "-"
        lines.append(
            f"| {r['module']} | {r['name']} | {r['total']} | {r['exact']} | {pct} | "
            f"{len(r['missing'])} | {len(r['not_impl'])} | {len(r['to_fix'])} |"
        )
    lines.append("")
    lines.append("## 3. 缺口明细")
    lines.append("")
    for r in rows:
        if not r["missing"]:
            continue
        lines.append(f"### {r['module']} · {r['name']}")
        lines.append("")
        if r["not_impl"]:
            lines.append("**本期不实现**（已有明确范围依据）：")
            lines.append("")
            for fr, why in sorted(r["not_impl"].items()):
                sm = r["summ"].get(fr, "")
                lines.append(f"- `{fr}` {sm} —— **{why}**")
            lines.append("")
        if r["to_fix"]:
            lines.append("**未逐条标注（SRS 设计级条目，MVP 未实现）**：")
            lines.append("")
            for fr in r["to_fix"]:
                sm = r["summ"].get(fr, "")
                lines.append(f"- `{fr}` {sm}")
            lines.append("")
    if not tot_fix:
        lines.append("> ✅ 无「遗漏待补」条目——所有未精确覆盖的 FR 均已标注为本期不实现。")
        lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"已生成 {OUT}")
    print(
        f"FR 总数 {tot_fr}；精确覆盖 {tot_exact}（{tot_exact / tot_fr * 100:.0f}%）；"
        f"本期不实现 {tot_ni}；遗漏待补 {tot_fix}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
