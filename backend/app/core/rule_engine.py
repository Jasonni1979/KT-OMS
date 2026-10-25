"""规则引擎框架 · 条件 DSL 与求值引擎（SRS-D01.03 FR-02）

**条件组语法**（两层：条件项 AND 组合，同维度多值 OR）：

```json
{
  "logic": "AND",
  "items": [
    {"dim": "order.amount_paid", "op": "gte", "value": 1000},
    {"dim": "shop_id", "op": "in", "value": [101, 102, 103]},
    {"dim": "order.items.category", "op": "any_in", "value": ["美妆"]}
  ]
}
```

**设计要点**（FR-02c/FR-02d/FR-02f）：
- 框架**不查库**：维度取值由消费方在装载上下文时注入 → 求值纯内存（性能与纯函数保障）
- 维度字典由消费方注册（dim 键/值类型/取值来源说明），框架只做合法性与类型校验
- 操作符按值类型分组（数值/集合/字符串/布尔/空值/时间），类型不匹配即不命中（不抛错）
- 明细模式（`explain=True`）不短路，返回逐项求值明细（dry-run 报告与排障数据源）
- 明确不做：跨维度运算表达式、嵌套多层 AND/OR（两层足够覆盖消费方全部规则）

参考实现溯源：商派 `sdb_omeauto_order_type` 17 维分组条件 LEFT JOIN autoconfirm，weight DESC 首命中。
本模块把该「维度+操作符+值集」的隐式 JOIN 显式化为可解释的 DSL。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

#: 值类型分组（SRS-D01.03 FR-02b）
ValueType = Literal["number", "set", "string", "bool", "null", "datetime"]

#: 各值类型允许的操作符
OPS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "number": ("eq", "neq", "gt", "gte", "lt", "lte", "between"),
    "set": ("in", "not_in", "any_in", "all_in"),
    "string": ("eq", "neq", "contains", "starts_with", "regex"),
    "bool": ("is_true", "is_false"),
    "null": ("is_null", "not_null"),
    "datetime": ("in_window", "before", "after"),
}

#: 全部操作符（校验用）
ALL_OPS: frozenset[str] = frozenset(op for ops in OPS_BY_TYPE.values() for op in ops)

#: 匹配任意维度的操作符（值类型自适应，如 eq/neq/in/not_in 跨类型可用）
_TYPE_AGNOSTIC_OPS = frozenset({"eq", "neq", "in", "not_in"})

#: 正则超时保护（FR-02b：regex 执行超时保护）
REGEX_TIMEOUT_SEC = 0.5


@dataclass(frozen=True)
class DimensionSpec:
    """维度字典项（消费方注册，框架只校验）"""

    key: str
    value_type: ValueType
    label: str = ""
    source: str = ""
    remark: str = ""


@dataclass
class ConditionItem:
    """单个条件项"""

    dim: str
    op: str
    value: Any = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ConditionItem:
        return cls(dim=str(d.get("dim", "")), op=str(d.get("op", "")), value=d.get("value"))


@dataclass
class ConditionGroup:
    """条件组（logic 仅支持 AND —— FR-02f 明确不做嵌套多层逻辑）"""

    logic: str = "AND"
    items: list[ConditionItem] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> ConditionGroup:
        if not d:
            return cls()
        raw_items = d.get("items") or []
        return cls(
            logic=str(d.get("logic", "AND")).upper(),
            items=[ConditionItem.from_dict(i) for i in raw_items],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "logic": self.logic,
            "items": [{"dim": i.dim, "op": i.op, "value": i.value} for i in self.items],
        }


@dataclass
class EvalDetail:
    """逐项求值明细（FR-02d：哪一项不命中 + 实际值）"""

    dim: str
    op: str
    expected: Any
    actual: Any
    hit: bool
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "dim": self.dim,
            "op": self.op,
            "expected": self.expected,
            "actual": self.actual,
            "hit": self.hit,
            "message": self.message,
        }


@dataclass
class EvalResult:
    """条件组求值结果"""

    hit: bool
    details: list[EvalDetail] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"hit": self.hit, "details": [d.to_dict() for d in self.details]}

    @property
    def failed_details(self) -> list[EvalDetail]:
        return [d for d in self.details if not d.hit]


class ConditionError(ValueError):
    """条件 DSL 非法（保存期校验用）"""


class DimensionRegistry:
    """维度字典注册表（FR-02c：每个 rule_group 注册可用维度）"""

    def __init__(self) -> None:
        self._dims: dict[str, dict[str, DimensionSpec]] = {}

    def register(self, group: str, specs: list[DimensionSpec]) -> None:
        """注册某 rule_group 的维度字典（同 dim 后注册覆盖先注册）"""
        bucket = self._dims.setdefault(group, {})
        for s in specs:
            bucket[s.key] = s

    def get(self, group: str, dim: str) -> DimensionSpec | None:
        return self._dims.get(group, {}).get(dim)

    def list_dims(self, group: str) -> list[DimensionSpec]:
        return list(self._dims.get(group, {}).values())

    def known(self, group: str, dim: str) -> bool:
        return dim in self._dims.get(group, {})


#: 全局维度注册表（进程内单例）
DIMENSIONS = DimensionRegistry()


def register_dimensions(group: str, specs: list[DimensionSpec]) -> None:
    """便捷入口：注册维度字典"""
    DIMENSIONS.register(group, specs)


# ---------- 操作符实现 ----------

def _as_number(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip())
        except ValueError:
            return None
    return None


def _as_datetime(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(v.strip(), fmt)
            except ValueError:
                continue
    return None


def _norm_set(v: Any) -> set[Any]:
    if v is None:
        return set()
    if isinstance(v, (list, tuple, set)):
        return {_hashable(x) for x in v}
    return {_hashable(v)}


def _hashable(v: Any) -> Any:
    if isinstance(v, (list, tuple, set)):
        return tuple(_hashable(x) for x in v)
    return v


def _op_eq(actual: Any, expected: Any) -> bool:
    if actual is None or expected is None:
        return actual is expected
    if isinstance(actual, bool) or isinstance(expected, bool):
        return bool(actual) == bool(expected)
    na, ne = _as_number(actual), _as_number(expected)
    if na is not None and ne is not None:
        return na == ne
    return str(actual) == str(expected)


def _op_in(actual: Any, expected: Any) -> bool:
    """实际值在期望集合内；集合型维度（明细行数组）时取交集非空"""
    exp = _norm_set(expected)
    if not exp:
        return False
    if isinstance(actual, (list, tuple, set)):
        return bool(_norm_set(actual) & exp)
    return _hashable(actual) in exp


def _op_not_in(actual: Any, expected: Any) -> bool:
    return not _op_in(actual, expected)


def _op_any_in(actual: Any, expected: Any) -> bool:
    """明细行任一命中（actual 为行数组，元素可再为数组）"""
    exp = _norm_set(expected)
    if not exp:
        return False
    rows = actual if isinstance(actual, (list, tuple)) else [actual]
    for row in rows:
        vals = row if isinstance(row, (list, tuple, set)) else [row]
        if _norm_set(vals) & exp:
            return True
    return False


def _op_all_in(actual: Any, expected: Any) -> bool:
    """明细行全部命中"""
    exp = _norm_set(expected)
    if not exp:
        return False
    rows = actual if isinstance(actual, (list, tuple)) else [actual]
    for row in rows:
        vals = row if isinstance(row, (list, tuple, set)) else [row]
        if not (_norm_set(vals) & exp):
            return False
    return True


def _op_regex(actual: Any, expected: Any) -> bool:
    if not isinstance(expected, str) or actual is None:
        return False
    try:
        return re.search(expected, str(actual)) is not None
    except re.error:
        return False


def _op_in_window(actual: Any, expected: Any) -> bool:
    """时段命中：expected = [start, end]（"HH:MM" 或 "YYYY-MM-DD HH:MM:SS"）"""
    if actual is None:
        return False
    if not isinstance(expected, (list, tuple)) or len(expected) != 2:
        return False
    start, end = expected
    cur = _as_datetime(actual)
    if cur is None:
        return False
    s, e = _as_datetime(start), _as_datetime(end)
    if s is not None and e is not None:
        return s <= cur <= e
    # HH:MM 形式：与当前时间比较（时刻区间，跨零点由 start>end 判定）
    try:
        sh, sm = (int(x) for x in str(start).split(":"))
        eh, em = (int(x) for x in str(end).split(":"))
    except (ValueError, AttributeError):
        return False
    now = datetime.now()
    minutes = now.hour * 60 + now.minute
    begin, finish = sh * 60 + sm, eh * 60 + em
    if begin <= finish:
        return begin <= minutes <= finish
    return minutes >= begin or minutes <= finish


def _apply_op(op: str, actual: Any, expected: Any) -> bool:
    if op == "eq":
        return _op_eq(actual, expected)
    if op == "neq":
        return not _op_eq(actual, expected)
    if op == "in":
        return _op_in(actual, expected)
    if op == "not_in":
        return _op_not_in(actual, expected)
    if op == "any_in":
        return _op_any_in(actual, expected)
    if op == "all_in":
        return _op_all_in(actual, expected)
    if op == "gt":
        na, ne = _as_number(actual), _as_number(expected)
        return na is not None and ne is not None and na > ne
    if op == "gte":
        na, ne = _as_number(actual), _as_number(expected)
        return na is not None and ne is not None and na >= ne
    if op == "lt":
        na, ne = _as_number(actual), _as_number(expected)
        return na is not None and ne is not None and na < ne
    if op == "lte":
        na, ne = _as_number(actual), _as_number(expected)
        return na is not None and ne is not None and na <= ne
    if op == "between":
        if not isinstance(expected, (list, tuple)) or len(expected) != 2:
            return False
        na = _as_number(actual)
        lo, hi = _as_number(expected[0]), _as_number(expected[1])
        return na is not None and lo is not None and hi is not None and lo <= na <= hi
    if op == "contains":
        return actual is not None and str(expected) in str(actual)
    if op == "starts_with":
        return actual is not None and str(actual).startswith(str(expected))
    if op == "regex":
        return _op_regex(actual, expected)
    if op == "is_true":
        return bool(actual) is True
    if op == "is_false":
        return bool(actual) is False
    if op == "is_null":
        return actual is None
    if op == "not_null":
        return actual is not None
    if op == "in_window":
        return _op_in_window(actual, expected)
    if op == "before":
        ca, ce = _as_datetime(actual), _as_datetime(expected)
        return ca is not None and ce is not None and ca < ce
    if op == "after":
        ca, ce = _as_datetime(actual), _as_datetime(expected)
        return ca is not None and ce is not None and ca > ce
    return False


def validate_condition_group(
    group: ConditionGroup, dim_group: str = ""
) -> list[str]:
    """保存期校验（FR-02c：维度合法 + 操作符与值类型匹配）

    返回错误列表（空 = 合法）。
    """
    errors: list[str] = []
    if group.logic not in ("AND", "OR"):
        errors.append(f"不支持的逻辑运算符: {group.logic}（FR-02f 仅支持两层 AND）")
    if not group.items:
        errors.append("条件组为空")
    for it in group.items:
        spec = DIMENSIONS.get(dim_group, it.dim) if dim_group else None
        if spec is None and dim_group:
            errors.append(f"未知维度: {it.dim}")
            continue
        if it.op not in ALL_OPS:
            errors.append(f"未知操作符: {it.dim}.{it.op}")
            continue
        if spec is None:
            continue
        if it.op in _TYPE_AGNOSTIC_OPS:
            continue
        allowed = OPS_BY_TYPE.get(spec.value_type, ())
        if it.op not in allowed:
            errors.append(
                f"维度 {it.dim}（{spec.value_type}）不支持操作符 {it.op}"
                f"（允许: {', '.join(allowed) or '无'}）"
            )
    return errors


def evaluate(
    group: ConditionGroup,
    context: dict[str, Any],
    *,
    explain: bool = False,
) -> EvalResult:
    """条件组求值（FR-02d：纯内存；短路求值，明细模式除外）

    - 维度取值从 context 取（缺失维度视为不命中，不抛错）
    - `explain=True` 时不短路，返回逐项明细
    """
    details: list[EvalDetail] = []
    all_hit = True
    for it in group.items:
        actual = context.get(it.dim)
        hit = _apply_op(it.op, actual, it.value)
        if not hit:
            all_hit = False
        if explain:
            details.append(
                EvalDetail(
                    dim=it.dim,
                    op=it.op,
                    expected=it.value,
                    actual=actual,
                    hit=hit,
                    message="" if hit else f"维度 {it.dim} 不满足 {it.op} {it.value!r}（实际 {actual!r}）",
                )
            )
        if not hit and not explain:
            # 短路：首项不命中即止
            return EvalResult(hit=False, details=details)
    if group.logic == "OR" and group.items:
        all_hit = any(d.hit for d in details) if explain else all_hit
    return EvalResult(hit=all_hit, details=details)
