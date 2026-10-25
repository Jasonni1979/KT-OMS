"""规则引擎框架 · 插件链机制（SRS-D01.03 FR-03）

承载 D03.02 审单引擎五段链与 D05.05 售后审核链。

**插件接口**（FR-03a）：
```
name(): str          # 插件唯一名
phase(): str         # 阶段标识（消费方定义段序）
order(): int         # 段内顺序
process(RuleContext) -> PluginResult
PluginResult = PASS | HOLD(reasons) | SHORT_CIRCUIT(reasons) | MUTATE(context变更)
reasons[] = {plugin, code, level(BLOCK/WARN), description, detail(JSON), suggest_action}
```

**框架职责**（FR-03c/FR-03d/FR-03e/FR-03f）：
- 链注册与发现：chain_id 隔离不同消费方（`order.audit`/`aftersale.audit`）；
  新增插件=实现接口+注册，**不改消费方引擎代码**
- 链编排：按 phase 声明顺序 + 段内 order 排序；段间依赖固定、段内可插拔
- 执行设施：按段声明短路策略（CHECK 段不短路）/ 每插件耗时记录 / 异常策略
  （strict=整链 HOLD 转人工；dual=逐插件可配 strict/loose）/ 单插件超时
- 上下文协议：消费方装载只读数据袋；MUTATE 写入上下文决策区；插件间通过上下文协作不直接互调
- 执行留痕：产出 plugin_trace JSON（各插件输入摘要/输出/耗时/结果）

参考实现溯源：商派 `omeauto_auto_group::getPluginNames` 硬编码插件链顺序。
本模块把「硬编码顺序」改为「段 + 段内 order」的可插拔编排。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

#: 结果类型
PASS = "PASS"
HOLD = "HOLD"
SHORT_CIRCUIT = "SHORT_CIRCUIT"
MUTATE = "MUTATE"

#: 原因级别
LEVEL_BLOCK = "BLOCK"
LEVEL_WARN = "WARN"


@dataclass
class Reason:
    """结构化原因项（FR-03a reasons[]；D03.02 FR-04a 结构化审核原因）"""

    plugin: str
    code: str
    level: str = LEVEL_BLOCK
    description: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    suggest_action: str = ""
    route_target: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin": self.plugin,
            "code": self.code,
            "level": self.level,
            "description": self.description,
            "detail": self.detail,
            "suggest_action": self.suggest_action,
            "route_target": self.route_target,
        }


@dataclass
class PluginResult:
    """插件执行结果"""

    status: str = PASS
    reasons: list[Reason] = field(default_factory=list)
    #: MUTATE 时写入上下文的决策数据
    mutation: dict[str, Any] = field(default_factory=dict)
    #: 插件内部异常信息（异常策略留痕，必填）
    error: str = ""

    @classmethod
    def pass_(cls) -> PluginResult:
        return cls(status=PASS)

    @classmethod
    def hold(cls, reasons: list[Reason]) -> PluginResult:
        return cls(status=HOLD, reasons=reasons)

    @classmethod
    def short_circuit(cls, reasons: list[Reason]) -> PluginResult:
        return cls(status=SHORT_CIRCUIT, reasons=reasons)

    @classmethod
    def mutate(cls, mutation: dict[str, Any], reasons: list[Reason] | None = None) -> PluginResult:
        return cls(status=MUTATE, reasons=reasons or [], mutation=mutation)


@dataclass
class RuleContext:
    """规则上下文（FR-03e）

    - `data`：消费方装载的只读数据袋（订单快照/行 BOM 等）
    - `decision`：决策区（MUTATE 结果写入，插件间通过它协作）
    - `dry_run`：沙箱标记（dry_run 模式下全链禁写）
    """

    data: dict[str, Any] = field(default_factory=dict)
    decision: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False
    #: 上下文附加信息（batch_no / order_id 等）
    meta: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def mutate(self, key: str, value: Any) -> None:
        """写入决策区（插件间协作的唯一通道）"""
        self.decision[key] = value


class RulePlugin(Protocol):
    """插件基接口（FR-03a）"""

    def name(self) -> str: ...
    def phase(self) -> str: ...
    def order(self) -> int: ...
    def process(self, ctx: RuleContext) -> PluginResult: ...


@dataclass
class PhaseSpec:
    """段声明（FR-03d：短路策略按段声明）"""

    name: str
    #: 该段是否短路（CHECK 段 False = 不短路，全收集原因）
    short_circuit: bool = True
    #: 该段异常策略：strict=整链 HOLD；loose=跳过该插件
    exception_policy: str = "strict"


@dataclass
class ChainSpec:
    """链声明（消费方注册）"""

    chain_id: str
    phases: list[PhaseSpec]
    #: 默认单插件超时（秒），插件可覆盖
    plugin_timeout: float = 0.5
    #: 链级异常策略：strict / dual（dual 时按 PhaseSpec.exception_policy）
    exception_policy: str = "strict"


class PluginRegistry:
    """插件注册表（FR-03b：chain_id 隔离；服务发现式注册）"""

    def __init__(self) -> None:
        self._plugins: dict[str, dict[str, RulePlugin]] = {}
        self._chains: dict[str, ChainSpec] = {}

    def register_chain(self, spec: ChainSpec) -> None:
        self._chains[spec.chain_id] = spec

    def register(self, chain_id: str, plugin: RulePlugin) -> None:
        """注册插件到链（同名覆盖，便于测试注入）"""
        self._plugins.setdefault(chain_id, {})[plugin.name()] = plugin

    def list_plugins(self, chain_id: str) -> list[RulePlugin]:
        """列出链内插件（FR-03b：注册表提供 list/get 查询）"""
        return list(self._plugins.get(chain_id, {}).values())

    def get(self, chain_id: str, name: str) -> RulePlugin | None:
        return self._plugins.get(chain_id, {}).get(name)

    def chain_spec(self, chain_id: str) -> ChainSpec | None:
        return self._chains.get(chain_id)

    def ordered(self, chain_id: str) -> list[RulePlugin]:
        """按 phase 声明顺序 + 段内 order 排序成链（FR-03c）"""
        spec = self._chains.get(chain_id)
        if spec is None:
            raise KeyError(f"链未注册: {chain_id}")
        phase_index = {p.name: i for i, p in enumerate(spec.phases)}
        plugins = list(self._plugins.get(chain_id, {}).values())
        return sorted(
            plugins,
            key=lambda p: (phase_index.get(p.phase(), 999), p.order(), p.name()),
        )


#: 全局插件注册表（进程内单例）
REGISTRY = PluginRegistry()


def register_chain(spec: ChainSpec) -> None:
    REGISTRY.register_chain(spec)


def register_plugin(chain_id: str, plugin: RulePlugin) -> None:
    REGISTRY.register(chain_id, plugin)


@dataclass
class PluginTrace:
    """单插件执行留痕（FR-03f：plugin_trace JSON）"""

    plugin: str
    phase: str
    order: int
    status: str
    cost_ms: int
    reason_codes: list[str] = field(default_factory=list)
    mutation: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin": self.plugin,
            "phase": self.phase,
            "order": self.order,
            "status": self.status,
            "cost_ms": self.cost_ms,
            "reason_codes": self.reason_codes,
            "mutation": self.mutation,
            "error": self.error,
        }


@dataclass
class ChainResult:
    """整链执行结果"""

    status: str = PASS
    reasons: list[Reason] = field(default_factory=list)
    traces: list[PluginTrace] = field(default_factory=list)
    #: 是否有 BLOCK 级原因
    blocked: bool = False

    @property
    def reason_codes(self) -> list[str]:
        return [r.code for r in self.reasons]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reasons": [r.to_dict() for r in self.reasons],
            "traces": [t.to_dict() for t in self.traces],
            "blocked": self.blocked,
        }


def _apply_plugin_config(
    plugins: list[RulePlugin], plugin_config: dict[str, Any] | None
) -> list[RulePlugin]:
    """按规则配置过滤/调整插件（FR-01d：逐插件启停 + 参数覆盖）

    plugin_config 形如：
    ```json
    {"memo_flag": {"enable": false}, "price_check": {"enable": true, "params": {"max_ratio": 3}}}
    ```
    """
    if not plugin_config:
        return plugins
    out: list[RulePlugin] = []
    for p in plugins:
        cfg = plugin_config.get(p.name())
        if isinstance(cfg, dict) and cfg.get("enable") is False:
            continue
        out.append(p)
    return out


async def run_chain(
    chain_id: str,
    ctx: RuleContext,
    *,
    plugin_config: dict[str, Any] | None = None,
    timeout: float | None = None,
) -> ChainResult:
    """执行整条插件链（FR-03d）

    - 段间顺序固定（chain spec），段内 order 可配
    - 短路：按段声明（CHECK 段不短路 → 跑完收集全部原因）
    - 异常：strict=整链 HOLD 转人工；loose=跳过该插件并告警（异常必留痕）
    - 超时：按异常策略处理
    """
    spec = REGISTRY.chain_spec(chain_id)
    if spec is None:
        raise KeyError(f"链未注册: {chain_id}")
    plugins = _apply_plugin_config(REGISTRY.ordered(chain_id), plugin_config)

    result = ChainResult()
    for p in plugins:
        phase_spec = next((ps for ps in spec.phases if ps.name == p.phase()), None)
        short_circuit = phase_spec.short_circuit if phase_spec else True
        policy = (
            phase_spec.exception_policy
            if phase_spec and spec.exception_policy == "dual"
            else spec.exception_policy
        )
        t0 = time.perf_counter()
        try:
            pr = await _call_plugin(p, ctx, timeout or spec.plugin_timeout)
        except Exception as e:  # noqa: BLE001 —— 插件异常按策略降级，必留痕
            cost_ms = int((time.perf_counter() - t0) * 1000)
            err = f"{type(e).__name__}: {e}"
            result.traces.append(
                PluginTrace(
                    plugin=p.name(), phase=p.phase(), order=p.order(),
                    status="ERROR", cost_ms=cost_ms, error=err,
                )
            )
            if policy == "loose":
                # 宽松：跳过该插件并告警（不吞异常——已入 trace）
                continue
            # 严格：整链 HOLD 转人工 + 系统异常原因
            result.reasons.append(
                Reason(
                    plugin=p.name(),
                    code="PLUGIN_EXCEPTION",
                    level=LEVEL_BLOCK,
                    description=f"插件 {p.name()} 执行异常：{err}",
                    detail={"error": err, "plugin": p.name(), "phase": p.phase()},
                    suggest_action="人工审核",
                    route_target="manual",
                )
            )
            result.status = HOLD
            result.blocked = True
            return result

        cost_ms = int((time.perf_counter() - t0) * 1000)
        result.traces.append(
            PluginTrace(
                plugin=p.name(),
                phase=p.phase(), order=p.order(),
                status=pr.status, cost_ms=cost_ms,
                reason_codes=[r.code for r in pr.reasons],
                mutation=pr.mutation,
                error=pr.error,
            )
        )
        # MUTATE → 写决策区（插件间协作的唯一通道）
        if pr.mutation:
            for k, v in pr.mutation.items():
                ctx.mutate(k, v)
        if pr.reasons:
            result.reasons.extend(pr.reasons)
            if any(r.level == LEVEL_BLOCK for r in pr.reasons):
                result.blocked = True
        if pr.status in (HOLD, SHORT_CIRCUIT):
            result.status = HOLD
            if short_circuit:
                # 该段短路 → 后续段无决策输入，跑了也无意义
                return result
    return result


async def _call_plugin(p: RulePlugin, ctx: RuleContext, timeout: float) -> PluginResult:
    """调用插件并施加超时（FR-03d：单插件超时按异常策略处理）"""
    coro = p.process(ctx)
    if not asyncio.iscoroutine(coro):
        return coro  # type: ignore[return-value]
    try:
        return await asyncio.wait_for(coro, timeout=timeout)
    except TimeoutError as e:
        raise TimeoutError(f"插件 {p.name()} 执行超时（>{timeout}s）") from e
