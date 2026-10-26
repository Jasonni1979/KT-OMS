#!/usr/bin/env python3
"""契约一致性门禁 —— 校验「代码侧枚举」与「DDL 权威枚举」是否一致

四项检查：
  C1  contracts/enums.py 与 DDL 同步（重新生成后无 diff）
  C2  手抄枚举映射表 ↔ DDL 枚举列：**漂移即失败**
  C3  裸常量取值必须落在某个 DDL 枚举列的值集合内（未知状态码 = 失败）
  C4  contracts/transitions.py 里的状态值必须在 DDL 枚举集合内

**匹配原理**：中文标签是 DDL 与代码之间的天然公共键 ——
代码里 `ST_WAIT_AUDIT = 1` + `APPLY_STATUS_LABEL = {ST_WAIT_AUDIT: "待审核"}`
拼出的 `{1: "待审核"}`，与 DDL 的 `aft_return_apply.status` 标签集求交即可定位。

用法：
    python3 tools/check_contract_ddl.py           # warn 模式（观察期）
    python3 tools/check_contract_ddl.py --strict  # fail 模式（转正后）
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
CONTRACTS = BACKEND / "app" / "contracts"

sys.path.insert(0, str(ROOT / "tools"))
import gen_contracts as G  # noqa: E402

#: 匹配阈值（Jaccard 相似度）：低于此值视为「无法追溯」，需人工判定
MATCH_THRESHOLD = 0.5

#: 人工确认「非 DDL 枚举」的白名单（模块级常量表、SLA 小时表等）
ALLOW_UNTRACKED: set[str] = {
    # 错误码 → 中文描述表（平台原始错误码，不是枚举定义）
    "_ERROR_CODE_DESC",
}

#: C3 白名单：名字像枚举但实际是配置量 / 动作名（非状态码）
ALLOW_UNKNOWN_VALUE: set[str] = {
    "SCOPE_CACHE_TTL",        # 权限范围缓存秒数
    "SCOPE_CACHE_PREFIX",     # Redis key 前缀
    "ACTION_DELIVERY_SEND",   # 平台发货回传动作名
    "REL_TYPE_BRANCH_OWNER",  # 组织关系类型（值域在 org_node_relation，非枚举列）
}


def load_enums() -> dict[str, dict[int, str]]:
    """读取 contracts/enums.py 的 ENUM_COLUMNS"""
    path = CONTRACTS / "enums.py"
    if not path.exists():
        print("❌ contracts/enums.py 不存在，请先运行 tools/gen_contracts.py")
        sys.exit(2)
    src = path.read_text(encoding="utf-8")
    ns: dict = {"Final": None}
    exec(compile(src, str(path), "exec"), ns)  # noqa: S102
    raw = ns.get("ENUM_COLUMNS")
    if not isinstance(raw, dict):
        print("❌ contracts/enums.py 缺少 ENUM_COLUMNS")
        sys.exit(2)
    return {k: dict(v) for k, v in raw.items()}


def collect_code_enums() -> list[dict]:
    """扫描业务代码里的枚举定义

    返回 [{file, name, values: {int: 中文}, kind: 'label_map'|'const'}]
    """
    out: list[dict] = []
    targets = list((BACKEND / "app" / "services").glob("*.py")) + list(
        (BACKEND / "app" / "core").glob("*.py")
    )
    for p in sorted(targets):
        if "contracts" in p.parts:
            continue
        src = p.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue

        # ① 常量赋值：NAME = <int> / <str>
        consts: dict[str, int | str] = {}
        pending_refs: list[tuple[str, str]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                t = node.targets[0]
                if isinstance(t, ast.Name) and t.id.isupper():
                    if isinstance(node.value, ast.Constant) and isinstance(
                        node.value.value, (int, str)
                    ):
                        consts[t.id] = node.value.value
                    elif isinstance(node.value, ast.Name):
                        # ⚠ 常量引用（`ERROR_TYPE = FORMAT_TYPE`）→ 解析到被引用的值，
                        #   否则会把常量名当成枚举值（误报）。
                        #   引用可能先于定义出现 → 记下来，第二轮再解析。
                        pending_refs.append((t.id, node.value.id))
                    elif isinstance(node.value, ast.UnaryOp) and isinstance(
                        node.value.operand, ast.Constant
                    ):
                        v = node.value.operand.value
                        if isinstance(v, int):
                            consts[t.id] = -v if isinstance(
                                node.value.op, ast.USub
                            ) else v

        # ①-b 第二轮：解析常量引用（引用可能先于定义出现）
        for _ in range(3):
            if not pending_refs:
                break
            still: list[tuple[str, str]] = []
            for tgt, src in pending_refs:
                if src in consts and tgt not in consts:
                    consts[tgt] = consts[src]
                else:
                    still.append((tgt, src))
            if len(still) == len(pending_refs):
                break
            pending_refs = still

        # ② 映射表：NAME = {K: "中文"}
        #    ⚠ 带类型注解的是 ast.AnnAssign（`X: dict[int, str] = {...}`），
        #      不带注解的是 ast.Assign —— 两种都要处理，否则漏掉一半
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign):
                t = node.target
                val = node.value
            elif isinstance(node, ast.Assign) and len(node.targets) == 1:
                t = node.targets[0]
                val = node.value
            else:
                continue
            if not (isinstance(t, ast.Name) and t.id.isupper()):
                continue
            if not isinstance(val, ast.Dict):
                continue
            values: dict[int | str, str] = {}
            for k, v in zip(val.keys, val.values):
                if not isinstance(v, ast.Constant):
                    continue
                label = v.value
                if not isinstance(label, str) or not label:
                    continue
                # 键可能是「字面量」也可能是「常量名」（ast.Name）
                if isinstance(k, ast.Constant) and isinstance(k.value, (int, str)):
                    values[k.value] = label
                elif isinstance(k, ast.Name) and k.id in consts:
                    cv = consts[k.id]
                    if isinstance(cv, (int, str)):
                        values[cv] = label
            if values:
                out.append(
                    {
                        "file": p,
                        "name": t.id,
                        "values": values,
                        "kind": "label_map",
                    }
                )

        # ③ 裸常量（供 C3 检查）
        for cname, cval in consts.items():
            out.append(
                {
                    "file": p,
                    "name": cname,
                    "values": {cval: ""},
                    "kind": "const",
                }
            )
    return out


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def best_match(values: dict, enums: dict):
    """用中文标签做公共键，找最佳匹配的 DDL 枚举列

    ⚠ 只在**键类型相同**的枚举列里匹配（int 表对 int 列、str 表对 str 列），
       否则「{0: '待退款'}」会误匹配到某个 str 枚举。
    """
    labels = {v for v in values.values() if v}
    if not labels:
        return None, 0.0
    keys = {str(k) for k in values}
    key_kind = type(next(iter(values)))
    best, best_score = None, 0.0
    for col, ev in enums.items():
        if ev and type(next(iter(ev))) is not key_kind:
            continue
        # ⚠ **键集必须高度相似**才算同一枚举 ——
        #   否则「错误码→分级」「Redis字段→DB字段」这类映射表会被误判成枚举
        #   （实测 ERR_LEVEL_MAP 会被误匹配到 gw_api_fail.err_level）
        ekeys = {str(k) for k in ev}
        key_score = jaccard(keys, ekeys)
        if key_score < 0.6:
            continue
        # ⚠ 标签相似度**不作为门槛** —— 标签不同正是「漂移」本身，
        #   若用它筛掉候选，真漂移（如 MODIFY_TYPE_LABEL）反而抓不到
        score = 0.6 * jaccard(labels, set(ev.values())) + 0.4 * key_score
        if score > best_score:
            best, best_score = col, score
    return best, best_score


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="有漂移即失败（转正模式）")
    args = ap.parse_args()

    print("===== 契约一致性门禁 =====\n")

    problems: list[str] = []
    warnings: list[str] = []

    # ---------- C1 enums.py 与 DDL 同步 ----------
    content, _meta = G.build()
    enums_path = CONTRACTS / "enums.py"
    if not enums_path.exists():
        problems.append("C1 contracts/enums.py 不存在")
    elif enums_path.read_text(encoding="utf-8") != content:
        problems.append(
            "C1 contracts/enums.py 与 DDL 不同步 —— 请运行 `python3 tools/gen_contracts.py`"
        )
    else:
        print(f"✓ C1 enums.py 与 DDL 同步（{len(load_enums())} 个枚举列）")

    enums = load_enums()

    # ---------- C2 映射表漂移 ----------
    code_enums = collect_code_enums()
    def is_label_table(e: dict) -> bool:
        """判定是否为「枚举标签表」

        ⚠ 值必须是**中文标签**形态。若值是英文标识符
           （如 `arrive_store`→`arrive` 的字段名映射、错误码→分级），
           那它不是枚举标签表，不参与漂移比对（否则大量误报）。
        """
        vals = [v for v in e["values"].values() if v]
        if not vals:
            return False
        cn = sum(1 for v in vals if any(ord(c) > 127 for c in v))
        return cn / len(vals) >= 0.5

    label_maps = [
        e
        for e in code_enums
        if e["kind"] == "label_map" and len(e["values"]) >= 2 and is_label_table(e)
    ]
    non_label = [
        e
        for e in code_enums
        if e["kind"] == "label_map" and len(e["values"]) >= 2 and not is_label_table(e)
    ]
    consts = [e for e in code_enums if e["kind"] == "const"]

    print(f"\n--- C2 手抄映射表 ↔ DDL 枚举列（{len(label_maps)} 张表）---")
    drift = 0
    untracked = 0
    for e in label_maps:
        col, score = best_match(e["values"], enums)
        rel = e["file"].relative_to(BACKEND)
        if col is None or score < MATCH_THRESHOLD:
            if e["name"] in ALLOW_UNTRACKED:
                print(f"  – {rel}::{e['name']}  白名单（非枚举定义）")
                continue
            untracked += 1
            warnings.append(
                f"UNTRACKED {rel}::{e['name']} —— 无法追溯到 DDL 枚举列"
                f"（值集 {sorted(e['values'])}）"
            )
            print(f"  ? {rel}::{e['name']}  无法追溯（最佳匹配 {col} 相似度 {score:.2f}）")
            continue
        ddl_values = enums[col]
        if ddl_values == e["values"]:
            print(f"  ✓ {rel}::{e['name']} → {col}")
            continue
        drift += 1
        only_code = {k: v for k, v in e["values"].items() if k not in ddl_values}
        only_ddl = {k: v for k, v in ddl_values.items() if k not in e["values"]}
        diff_label = {
            k: (e["values"][k], ddl_values[k])
            for k in e["values"]
            if k in ddl_values and e["values"][k] != ddl_values[k]
        }
        msg = (
            f"DRIFT {rel}::{e['name']} → {col}\n"
            f"        代码多出: {only_code}\n"
            f"        DDL 多出: {only_ddl}\n"
            f"        标签不同: {diff_label}"
        )
        problems.append(msg)
        print(f"  ✗ {rel}::{e['name']} → {col}")
        if only_code:
            print(f"        代码多出: {only_code}")
        if only_ddl:
            print(f"        DDL 多出: {only_ddl}")
        if diff_label:
            print(f"        标签不同: {diff_label}")
    # ---------- C2-b 兜底：代码用的枚举值是否都在 DDL 里 ----------
    #    键集 jaccard 门槛会把「键集差异大」的真漂移滤掉
    #    （实测 MODIFY_TYPE_LABEL：代码 item/memo vs DDL item_add/remark）
    #    → 用「键是否存在于任一 DDL 枚举值集合」兜底
    all_enum_values: set[str] = set()
    for ev in enums.values():
        all_enum_values |= {str(k) for k in ev}
    bad_key = 0
    for e in label_maps:
        if e["name"] in ALLOW_UNTRACKED:
            continue
        missing = sorted(
            {str(k) for k in e["values"]} - all_enum_values
        )
        if missing:
            bad_key += 1
            rel = e["file"].relative_to(BACKEND)
            msg = (
                f"DRIFT {rel}::{e['name']} —— 使用了 DDL 中不存在的枚举值：{missing}"
            )
            problems.append(msg)
            print(f"  ✗ {rel}::{e['name']} 使用了 DDL 中不存在的枚举值：{missing}")
    if bad_key:
        print(f"  → 键合法性兜底：{bad_key} 处使用非法枚举值")

    print(f"  → 漂移 {drift} 处 / 无法追溯 {untracked} 处")
    if non_label:
        print(
            f"  （另有 {len(non_label)} 张非标签映射表按字段名/错误码映射处理，不参与比对："
            f"{', '.join(e['name'] for e in non_label[:6])}"
            f"{' ...' if len(non_label) > 6 else ''}）"
        )

    # ---------- C3 裸常量未知值 ----------
    print(f"\n--- C3 裸常量取值必须在 DDL 枚举集合内（{len(consts)} 个）---")
    all_values: set[int] = set()
    for ev in enums.values():
        all_values |= set(ev)
    # ⚠ 只检查「像状态码」的常量（名字含枚举语义词），
    #   否则 TTL / 批次大小 / 权重这类配置量全是噪音
    ENUMISH = ("STATUS", "STATE", "TYPE", "STAGE", "MODE", "ACTION", "KIND",
               "LEVEL", "CLASS", "SCOPE", "CHANNEL", "PRIORITY", "DECISION",
               "RESULT", "FLAG", "DIMENSION", "LIST", "ST_", "REFUND_", "APPLY_")
    unknown = 0
    for e in consts:
        name = e["name"]
        if not any(tok in name for tok in ENUMISH):
            continue
        if name.startswith("_") or name in ALLOW_UNKNOWN_VALUE:
            continue
        for v in e["values"]:
            if v not in all_values:
                rel = e["file"].relative_to(BACKEND)
                msg = f"UNKNOWN_VALUE {rel}::{name} = {v} —— 该值不在任何 DDL 枚举集合内"
                warnings.append(msg)
                print(f"  ? {rel}::{name} = {v}")
                unknown += 1
                break
    print(f"  → 未知值 {unknown} 个（warning，不阻断）")

    # ---------- C4 状态机状态值 ----------
    print("\n--- C4 状态机状态值必须在 DDL 枚举集合内 ---")
    trans_path = CONTRACTS / "transitions.py"
    if not trans_path.exists():
        warnings.append("C4 contracts/transitions.py 不存在（尚未建立状态机契约）")
        print("  ? contracts/transitions.py 不存在")
    else:
        sys.path.insert(0, str(BACKEND))
        try:
            from app.contracts.transitions import TRANSITIONS

            bad = 0
            for col, table in TRANSITIONS.items():
                if col not in enums:
                    bad += 1
                    msg = f"C4 流转表引用了不存在的枚举列 {col}"
                    problems.append(msg)
                    print(f"  ✗ 未知枚举列 {col}")
                    continue
                valid_labels = set(enums[col].values())
                for src_label, dst_labels in table.items():
                    if src_label not in valid_labels:
                        bad += 1
                        msg = (
                            f"C4 {col} 的起始状态「{src_label}」不在 DDL 枚举里"
                            f"（合法：{sorted(valid_labels)}）"
                        )
                        problems.append(msg)
                        print(f"  ✗ {col} 起始状态「{src_label}」非法")
                    for dl in dst_labels:
                        if dl not in valid_labels:
                            bad += 1
                            msg = (
                                f"C4 {col} 从「{src_label}」迁移到「{dl}」"
                                f"—— 目标状态不在 DDL 枚举里"
                            )
                            problems.append(msg)
                            print(f"  ✗ {col} 目标状态「{dl}」非法")
            print(f"  → 非法状态引用 {bad} 处")
        except Exception as e:  # pragma: no cover
            warnings.append(f"C4 无法加载 transitions.py：{e}")
            print(f"  ? 无法加载 transitions.py：{e}")

    # ---------- 汇总 ----------
    print("\n" + "=" * 50)
    print(f"漂移(PROBLEM) {len(problems)} 项 / 待人工判定(WARN) {len(warnings)} 项")
    if problems:
        print("\n【PROBLEM 明细】")
        for p in problems:
            print("  " + p.replace("\n", "\n  "))
    if warnings and args.strict:
        print("\n【WARN 明细】")
        for w in warnings:
            print("  " + w)
    print("=" * 50)

    if problems:
        print(f"\n❌ 契约门禁未通过（{len(problems)} 项漂移）")
        if args.strict:
            return 1
        print("   （当前为 warn 模式，未阻断；--strict 时返回非零）")
        return 0
    print("\n✓ 契约门禁通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
