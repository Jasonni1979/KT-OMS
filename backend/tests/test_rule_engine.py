"""规则引擎框架单元测试（SRS-D01.03）

**为什么补这块**：D01.03 是**框架域**（47 条 FR），但覆盖率长期只有 10.6% ——
因为框架的实现是**纯逻辑**（不查库、不依赖 IO），而项目此前的测试都集中在
业务域（审单/履约/库存），框架层只有零星几条。

本文件覆盖三块**纯逻辑**（跑得快、稳、不需要 DB）：

| 条款 | 内容 | 实现 |
|---|---|---|
| FR-02a/b/d/e | 条件 DSL 两层模型 / 操作符字典 / 求值引擎 / 可视化数据契约 | `app/core/rule_engine.py` |
| FR-03a-f | 插件接口 / 链注册发现 / 编排 / 执行 / 上下文协议 / 留痕 | `app/core/plugin_chain.py` |
| FR-08a/b | 字典模型与字典服务（注册 / 查询 / 校验） | `app/core/dicts.py` |

⚠ **只测已实现的**（FR-05 版本发布、FR-06 样本试跑、FR-07 命中采集、FR-09 缓存
属规划或未落地能力，不在这里假装覆盖）。
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.core.dicts import DICTS, DictItem, DictService
from app.core.plugin_chain import (
    HOLD,
    MUTATE,
    PASS,
    REGISTRY,
    SHORT_CIRCUIT,
    ChainSpec,
    PhaseSpec,
    PluginResult,
    Reason,
    RuleContext,
    register_chain,
    register_plugin,
)
from app.core.rule_engine import (
    ALL_OPS,
    DIMENSIONS,
    OPS_BY_TYPE,
    ConditionGroup,
    ConditionItem,
    DimensionSpec,
    evaluate,
    register_dimensions,
    validate_condition_group,
)

# ---------------------------------------------------------------- 维度注册

GROUP = "test.rule"


@pytest.fixture(autouse=True)
def _register_test_dims():
    """注册测试维度（FR-02c：维度字典由消费方注册，框架只校验）"""
    register_dimensions(
        GROUP,
        [
            DimensionSpec(key="amount", value_type="number", label="金额"),
            DimensionSpec(key="tags", value_type="set", label="标签集"),
            DimensionSpec(key="name", value_type="string", label="名称"),
            DimensionSpec(key="flag", value_type="bool", label="开关"),
            DimensionSpec(key="remark", value_type="null", label="备注"),
            DimensionSpec(key="created_at", value_type="datetime", label="创建时间"),
        ],
    )
    yield


# ---------------------------------------------------------------- FR-02a


def test_condition_group_from_dict_two_level():
    """FR-02a：条件组 = 逻辑符 + 条件项列表（两层）"""
    g = ConditionGroup.from_dict(
        {
            "logic": "and",
            "items": [
                {"dim": "amount", "op": "gte", "value": 100},
                {"dim": "tags", "op": "in", "value": ["A", "B"]},
            ],
        }
    )
    assert g.logic == "AND"  # 小写归一为���写
    assert len(g.items) == 2
    assert g.items[0].dim == "amount"
    assert g.items[1].value == ["A", "B"]


def test_condition_group_to_dict_roundtrip():
    """FR-02e：条件组可序列化回前端构建器数据契约"""
    raw = {
        "logic": "AND",
        "items": [{"dim": "amount", "op": "between", "value": [10, 20]}],
    }
    assert ConditionGroup.from_dict(raw).to_dict() == raw


def test_condition_group_empty_is_empty_group():
    """FR-02a：空条件组 → 空 AND 组（不是 None）"""
    g = ConditionGroup.from_dict(None)
    assert g.logic == "AND"
    assert g.items == []


def test_condition_item_defaults_missing_fields():
    """FR-02a：条件项缺字段 → 空串/None（不抛错）"""
    it = ConditionItem.from_dict({})
    assert it.dim == "" and it.op == "" and it.value is None


# ---------------------------------------------------------------- FR-02b


def test_ops_by_type_covers_all_value_types():
    """FR-02b：操作符按值类型分组（数值/集合/字符串/布尔/空值/时间）"""
    assert set(OPS_BY_TYPE) == {
        "number", "set", "string", "bool", "null", "datetime"
    }
    assert "between" in OPS_BY_TYPE["number"]
    assert "any_in" in OPS_BY_TYPE["set"]
    assert "regex" in OPS_BY_TYPE["string"]
    assert "is_true" in OPS_BY_TYPE["bool"]
    assert "is_null" in OPS_BY_TYPE["null"]
    assert "in_window" in OPS_BY_TYPE["datetime"]


def test_all_ops_is_union_of_type_groups():
    """FR-02b：全部操作符 = 各类型操作符的并集"""
    union = {op for ops in OPS_BY_TYPE.values() for op in ops}
    assert ALL_OPS == union


@pytest.mark.parametrize(
    "op,actual,expected,hit",
    [
        # 数值
        ("eq", 100, 100, True),
        ("eq", 100, 101, False),
        ("neq", 100, 101, True),
        ("gt", 100, 99, True),
        ("gt", 100, 100, False),
        ("gte", 100, 100, True),
        ("lt", 100, 101, True),
        ("lte", 100, 100, True),
        ("between", 15, [10, 20], True),
        ("between", 25, [10, 20], False),
        ("between", 15, [10], False),      # 区间长度必须为 2
        # 集合
        ("in", "A", ["A", "B"], True),
        ("in", "C", ["A", "B"], False),
        ("not_in", "C", ["A", "B"], True),
        ("any_in", "A", ["A", "B"], True),
        ("all_in", ["A", "B"], ["A", "B"], True),
        ("all_in", ["A", "C"], ["A", "B"], False),
        # 字符串
        ("eq", "abc", "abc", True),
        ("contains", "hello world", "world", True),
        ("contains", "hello", "xx", False),
        ("starts_with", "abcdef", "abc", True),
        ("regex", "abc123", r"^abc\d+$", True),
        ("regex", "xyz", r"^abc\d+$", False),
    ],
)
def test_operators_behaviour(op: str, actual: Any, expected: Any, hit: bool):
    """FR-02b：各操作符的真值表"""
    g = ConditionGroup(items=[ConditionItem(dim="d", op=op, value=expected)])
    assert evaluate(g, {"d": actual}).hit is hit


def test_operator_type_mismatch_is_not_hit_not_error():
    """FR-02b：类型不匹配 → 不命中（**不抛错**，框架不查库不猜语义）"""
    g = ConditionGroup(items=[ConditionItem(dim="d", op="gt", value="abc")])
    res = evaluate(g, {"d": "not-a-number"})
    assert res.hit is False


def test_operator_regex_invalid_pattern_is_not_hit():
    """FR-02b：非法正则 → 不命中（不抛错打断链路）"""
    g = ConditionGroup(items=[ConditionItem(dim="d", op="regex", value="([")])
    assert evaluate(g, {"d": "abc"}).hit is False


# ---------------------------------------------------------------- FR-02c


def test_dimension_registry_register_and_lookup():
    """FR-02c：维度注册后可查（key / 类型 / 标签）"""
    spec = DIMENSIONS.get(GROUP, "amount")
    assert spec is not None
    assert spec.value_type == "number"
    assert DIMENSIONS.known(GROUP, "amount") is True
    assert DIMENSIONS.known(GROUP, "not_registered") is False


def test_dimension_registry_list_dims():
    """FR-02c：可列出该 rule_group 的全部维度"""
    dims = {d.key for d in DIMENSIONS.list_dims(GROUP)}
    assert {"amount", "tags", "name", "flag", "remark", "created_at"} <= dims


def test_validate_rejects_unknown_dimension():
    """FR-02c：保存期校验拦截未注册维度"""
    g = ConditionGroup(items=[ConditionItem(dim="unknown_dim", op="eq", value=1)])
    errs = validate_condition_group(g, GROUP)
    assert any("未知维度" in e for e in errs)


def test_validate_rejects_unknown_operator():
    """FR-02c：保存期校验拦截未知操作符"""
    g = ConditionGroup(items=[ConditionItem(dim="amount", op="not_an_op", value=1)])
    errs = validate_condition_group(g, GROUP)
    assert any("未知操作符" in e for e in errs)


def test_validate_rejects_type_mismatch_operator():
    """FR-02c：操作符与维度值类型不匹配 → 报错（如数值维度用 contains）"""
    g = ConditionGroup(items=[ConditionItem(dim="amount", op="contains", value="x")])
    errs = validate_condition_group(g, GROUP)
    assert errs  # 数值维度不允许 contains


def test_validate_rejects_empty_group_and_bad_logic():
    """FR-02c/02f：空条件组 + 非法逻辑符 → 报错"""
    assert any("条件组为空" in e for e in validate_condition_group(ConditionGroup(), GROUP))
    bad = ConditionGroup(logic="XOR", items=[ConditionItem(dim="amount", op="eq", value=1)])
    assert any("逻辑运算符" in e for e in validate_condition_group(bad, GROUP))


def test_validate_allows_type_agnostic_ops_on_any_type():
    """FR-02c：eq/neq/in/not_in 跨类型可用（类型自适应）"""
    g = ConditionGroup(items=[ConditionItem(dim="amount", op="eq", value=1)])
    assert validate_condition_group(g, GROUP) == []


# ---------------------------------------------------------------- FR-02d


def test_evaluate_all_items_must_hit_for_and():
    """FR-02d：AND 逻辑 → 全部命中才算命中"""
    g = ConditionGroup(
        items=[
            ConditionItem(dim="amount", op="gte", value=100),
            ConditionItem(dim="name", op="eq", value="张三"),
        ]
    )
    assert evaluate(g, {"amount": 200, "name": "张三"}).hit is True
    assert evaluate(g, {"amount": 200, "name": "李四"}).hit is False


def test_evaluate_missing_dimension_is_not_hit():
    """FR-02d：维度缺失 → 视为不命中（**不抛错**）"""
    g = ConditionGroup(items=[ConditionItem(dim="amount", op="gte", value=100)])
    res = evaluate(g, {})
    assert res.hit is False


def test_evaluate_short_circuits_without_explain():
    """FR-02d：非明细模式短路（首项不命中即止）"""
    g = ConditionGroup(
        items=[
            ConditionItem(dim="amount", op="gte", value=100),
            ConditionItem(dim="name", op="eq", value="张三"),
        ]
    )
    res = evaluate(g, {"amount": 1, "name": "李四"})
    assert res.hit is False
    assert len(res.details) == 0  # 短路 → 无明细


def test_evaluate_explain_returns_per_item_details():
    """FR-02d：明细模式逐项返回「实际值 + 不命中原因」"""
    g = ConditionGroup(
        items=[
            ConditionItem(dim="amount", op="gte", value=100),
            ConditionItem(dim="name", op="eq", value="张三"),
        ]
    )
    res = evaluate(g, {"amount": 1, "name": "李四"}, explain=True)
    assert res.hit is False
    assert len(res.details) == 2
    assert res.details[0].actual == 1
    assert res.details[0].expected == 100
    assert res.details[0].hit is False
    assert "不满足" in res.details[0].message
    assert len(res.failed_details) == 2


def test_eval_result_to_dict_contract():
    """FR-02e：求值结果可序列化（dry-run 报告数据源）"""
    g = ConditionGroup(items=[ConditionItem(dim="amount", op="gte", value=100)])
    d = evaluate(g, {"amount": 1}, explain=True).to_dict()
    assert d["hit"] is False
    assert d["details"][0]["dim"] == "amount"
    assert set(d["details"][0]) == {"dim", "op", "expected", "actual", "hit", "message"}


def test_evaluate_or_logic():
    """FR-02d：OR 逻辑 → 任一命中即命中"""
    g = ConditionGroup(
        logic="OR",
        items=[
            ConditionItem(dim="amount", op="gte", value=1000),
            ConditionItem(dim="name", op="eq", value="张三"),
        ],
    )
    assert evaluate(g, {"amount": 1, "name": "张三"}, explain=True).hit is True


def test_evaluate_datetime_in_window():
    """FR-02b/02d：时间维度 in_window（起止区间）"""
    g = ConditionGroup(
        items=[
            ConditionItem(
                dim="created_at",
                op="in_window",
                value=["2026-01-01 00:00:00", "2026-12-31 23:59:59"],
            )
        ]
    )
    assert evaluate(g, {"created_at": "2026-06-01 12:00:00"}).hit is True
    assert evaluate(g, {"created_at": "2025-06-01 12:00:00"}).hit is False


def test_evaluate_bool_and_null_operators():
    """FR-02b：布尔/空值操作符"""
    g_true = ConditionGroup(items=[ConditionItem(dim="flag", op="is_true", value=True)])
    assert evaluate(g_true, {"flag": True}).hit is True
    assert evaluate(g_true, {"flag": False}).hit is False
    g_null = ConditionGroup(items=[ConditionItem(dim="remark", op="is_null", value=None)])
    assert evaluate(g_null, {"remark": None}).hit is True
    assert evaluate(g_null, {"remark": "x"}).hit is False


# ---------------------------------------------------------------- FR-03


class _EchoPlugin:
    """最小插件实现（FR-03a：name/phase/order/process 四要素）"""

    def __init__(self, name: str, phase: str, order: int, result: PluginResult | None = None):
        self._name = name
        self._phase = phase
        self._order = order
        self._result = result

    def name(self) -> str:
        return self._name

    def phase(self) -> str:
        return self._phase

    def order(self) -> int:
        return self._order

    def process(self, ctx: RuleContext) -> PluginResult:
        return self._result or PluginResult.pass_()


def test_plugin_result_variants():
    """FR-03d：四类插件结果（PASS/HOLD/SHORT_CIRCUIT/MUTATE）"""
    assert PluginResult.pass_().status == PASS
    hold = PluginResult.hold([Reason(plugin="p", code="X", level="WARN", description="需人工")])
    assert hold.status == HOLD
    assert hold.reasons[0].code == "X"
    sc = PluginResult.short_circuit(
        [Reason(plugin="p", code="Y", level="BLOCK", description="阻断")]
    )
    assert sc.status == SHORT_CIRCUIT
    mut = PluginResult.mutate({"branch": 7})
    assert mut.status == MUTATE
    assert mut.mutation == {"branch": 7}


def test_registry_register_and_lookup_plugin():
    """FR-03b：插件注册后可按名字发现"""
    spec = ChainSpec(chain_id="test.chain", phases=[PhaseSpec(name="p1")])
    register_chain(spec)
    plugin = _EchoPlugin("echo", "p1", 10)
    register_plugin("test.chain", plugin)
    assert REGISTRY.get("test.chain", "echo") is plugin
    assert "echo" in [p.name() for p in REGISTRY.list_plugins("test.chain")]
    assert REGISTRY.chain_spec("test.chain") is spec


def test_registry_ordered_by_phase_then_order():
    """FR-03c：链编排 = 先按 phase 序，再按段内 order"""
    spec = ChainSpec(
        chain_id="test.chain2",
        phases=[PhaseSpec(name="p1"), PhaseSpec(name="p2")],
    )
    register_chain(spec)
    register_plugin("test.chain2", _EchoPlugin("late", "p1", 99))
    register_plugin("test.chain2", _EchoPlugin("early", "p1", 1))
    register_plugin("test.chain2", _EchoPlugin("next_phase", "p2", 1))
    names = [p.name() for p in REGISTRY.ordered("test.chain2")]
    assert names == ["early", "late", "next_phase"]


def test_registry_unknown_chain_or_plugin():
    """FR-03b：查不到时返回 None（不抛错）"""
    assert REGISTRY.get("no.such.chain", "x") is None
    assert REGISTRY.chain_spec("no.such.chain") is None


def test_run_chain_passes_and_records_trace():
    """FR-03d/03f：链执行产出留痕（插件 trace）"""
    from app.core.plugin_chain import run_chain

    spec = ChainSpec(chain_id="test.chain3", phases=[PhaseSpec(name="p1")])
    register_chain(spec)
    register_plugin("test.chain3", _EchoPlugin("ok", "p1", 1))

    ctx = RuleContext(data={"a": 1}, decision={}, dry_run=True, meta={})
    result = asyncio.run(run_chain("test.chain3", ctx))
    assert result.status == PASS
    assert len(result.traces) == 1
    assert result.traces[0].plugin == "ok"
    assert result.traces[0].cost_ms >= 0


def test_run_chain_hold_carries_reasons():
    """FR-03d/03f：HOLD 结果携带原因（转人工）"""
    from app.core.plugin_chain import run_chain

    spec = ChainSpec(chain_id="test.chain4", phases=[PhaseSpec(name="p1")])
    register_chain(spec)
    register_plugin(
        "test.chain4",
        _EchoPlugin(
            "hold",
            "p1",
            1,
            PluginResult.hold(
                [Reason(plugin="hold", code="NEED_MANUAL", level="WARN", description="需人工")]
            ),
        ),
    )
    ctx = RuleContext(data={}, decision={}, dry_run=True, meta={})
    result = asyncio.run(run_chain("test.chain4", ctx))
    assert result.status == HOLD
    assert "NEED_MANUAL" in result.reason_codes


def test_run_chain_unknown_chain_raises():
    """FR-03b：链未注册 → 明确报错（fail fast，不静默）"""
    from app.core.plugin_chain import run_chain

    ctx = RuleContext(data={}, decision={}, dry_run=True, meta={})
    with pytest.raises(KeyError):
        asyncio.run(run_chain("no.such.chain.at.all", ctx))


def test_rule_context_get_and_mutate():
    """FR-03e：上下文 = 只读数据袋 + 决策区（MUTATE 写决策区）"""
    ctx = RuleContext(data={"a": 1}, decision={}, dry_run=False, meta={"m": 2})
    assert ctx.get("a") == 1
    assert ctx.get("missing", "def") == "def"
    assert ctx.meta["m"] == 2
    ctx.mutate("branch", 7)
    assert ctx.decision["branch"] == 7


# ---------------------------------------------------------------- FR-08


def test_dict_item_defaults_and_helpers():
    """FR-08a：字典项模型（含默认路由 / 审核组 / 建议动作）"""
    item = DictItem(code="X1", name="原因一", dict_type="audit_reason_code")
    assert item.code == "X1"
    assert item.name == "原因一"
    assert item.dict_type == "audit_reason_code"
    assert isinstance(item.default_route, str)
    assert isinstance(item.audit_group, str)
    assert isinstance(item.suggest_action, str)


def test_dict_service_register_get_list():
    """FR-08b：字典注册 → 查询 → 列举"""
    svc = DictService()
    svc.register_preset("test_dict", [DictItem(code="C1", name="码一", dict_type="test_dict")])
    assert svc.get("test_dict", "C1") is not None
    assert svc.get("test_dict", "NOPE") is None
    assert [i.code for i in svc.list_items("test_dict")] == ["C1"]
    assert "test_dict" in svc.all_types()


def test_dict_service_exists_and_validate():
    """FR-08b：存在性判定 + 校验（不在字典内 → 报错）"""
    svc = DictService()
    svc.register_preset("test_dict2", [DictItem(code="C2", name="码二", dict_type="test_dict2")])
    assert svc.exists("test_dict2", "C2") is True
    assert svc.exists("test_dict2", "C9") is False
    svc.validate("test_dict2", "C2")  # 存在 → 不抛
    with pytest.raises(ValueError):
        svc.validate("test_dict2", "C9")


def test_global_dicts_service_is_singleton():
    """FR-08b：全局字典服务是单例（消费方启动时注册预置项）"""
    assert DICTS is DICTS  # 单例
    assert isinstance(DICTS.all_types(), list)
    assert DICTS.get("no.such.type", "x") is None
