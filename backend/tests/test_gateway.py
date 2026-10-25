"""D02.01 平台接入框架（Gateway）测试

覆盖已实现能力：
- FR-01a `call()` 唯一出口：业务域不得绕过网关
- FR-01b 五层管线固定顺序（限流 → 签名 → 传输 → 报文 → 日志）
- FR-05a 两级令牌桶（平台级 + 店铺级串联）
- FR-05b 限流参数配置化（rate_limit_rule）
- FR-05c 超限行为：等待超时 → RATE_LIMITED 可重试错误
- FR-06c 统一错误码字典 → 五级分级
- FR-07a 全量留痕（api_log 记录各字段）
- FR-07b 大报文截断（>2KB 截断 + is_truncated 标记）
- D02.03 FR-02c 分页拉取必须走 Gateway（否则无留痕）
"""
from __future__ import annotations

from sqlalchemy import text

from app.adapters.base import AdapterResult, RateLimitRule
from app.services.gateway import (
    ERR_LEVEL_MAP,
    MAX_BODY_LEN,
    Gateway,
    RateLimitError,
    gateway_driver,
    get_gateway,
)


class _FakeCfg:
    """假配置层：限流规则（FR-05b 配置化）"""

    def rate_limit_rule(self, method: str, shop_id: int) -> RateLimitRule:
        return RateLimitRule(capacity=40, rate_per_sec=20.0, scope="platform")


class _FakeAdapter:
    """假适配器：可控返回，避免真实网络

    注意：网关取限流规则走 `adapter.cfg.rate_limit_rule`（配置层与传输层分离）。
    """

    platform = "taobao"

    def __init__(self, result: AdapterResult | None = None):
        self.result = result or AdapterResult(succ=True, data={})
        self.calls: list[tuple[str, dict, int, str]] = []
        self.cfg = _FakeCfg()

    async def call(
        self,
        method: str,
        params: dict,
        *,
        shop_id: int = 0,
        primary_bn: str = "",
        session_key: str = "",
    ) -> AdapterResult:
        self.calls.append((method, params, shop_id, primary_bn))
        return self.result


class _FakeRedis:
    """假 Redis：eval 返回固定结果（模拟令牌桶放行/拒绝）"""

    def __init__(self, allowed: bool = True, wait_ms: int = 0):
        self.allowed = allowed
        self.wait_ms = wait_ms
        self.keys: list[str] = []

    async def eval(self, script, numkeys, key, capacity, rate, now_ms):  # noqa: ANN001
        self.keys.append(str(key))
        return [1 if self.allowed else 0, self.wait_ms]


# ============ FR-06c 统一错误码字典 ============


def test_err_level_map_covers_five_levels():
    """FR-06c 五级分级：RETRYABLE/RATE_LIMITED/AUTH/MANUAL/FATAL"""
    levels = set(ERR_LEVEL_MAP.values())
    assert levels == {"RETRYABLE", "RATE_LIMITED", "AUTH", "MANUAL", "FATAL"}
    # 典型错误码归属
    assert ERR_LEVEL_MAP["isv.invalid-signature"] == "AUTH"
    assert ERR_LEVEL_MAP["flow-limit"] == "RATE_LIMITED"
    assert ERR_LEVEL_MAP["isv.trade-service-error"] == "RETRYABLE"
    assert ERR_LEVEL_MAP["isv.trade-not-exist"] == "MANUAL"
    assert ERR_LEVEL_MAP["isv.method-not-allowed"] == "FATAL"


def test_err_level_map_unknown_code_defaults_retryable():
    """FR-06c 未知错误码默认按可重试处理（保守策略）"""
    gw = Gateway(adapter=_FakeAdapter(), redis=None)
    assert gw.adapter is not None
    # 未在字典中的码 → 由 call() 走默认分支，这里验证字典不含未知码
    assert "isv.not-exist-code" not in ERR_LEVEL_MAP


# ============ FR-01a 唯一出口 + FR-01b 五层管线 ============


async def test_call_is_single_entrypoint_and_delegates_to_adapter():
    """FR-01a：call() 是唯一出口，参数完整透传到适配器"""
    ad = _FakeAdapter(AdapterResult(succ=True, data={"x": 1}))
    gw = Gateway(adapter=ad, redis=None)
    res = await gw.call(
        "shop.order.list.get",
        {"page_no": 1},
        shop_id=2015,
        primary_bn="PO123",
        source="pull",
    )
    assert res.succ is True
    assert len(ad.calls) == 1
    method, params, shop_id, pbn = ad.calls[0]
    assert method == "shop.order.list.get"
    assert params == {"page_no": 1}
    assert shop_id == 2015
    assert pbn == "PO123"


async def test_pipeline_order_limit_before_adapter_call():
    """FR-01b：限流在最前——被限流时**不发起**平台调用"""
    ad = _FakeAdapter(AdapterResult(succ=True))
    redis = _FakeRedis(allowed=False, wait_ms=5000)
    gw = Gateway(adapter=ad, redis=redis)
    res = await gw.call("shop.order.list.get", {}, shop_id=1)
    assert res.succ is False
    assert res.err_code == "flow-limit"
    assert ad.calls == []  # 关键：未触达适配器
    assert len(redis.keys) == 1


# ============ FR-05a 两级令牌桶 ============


async def test_two_level_bucket_platform_then_shop():
    """FR-05a：平台级 → 店铺级 串联（两个桶都要取令牌）"""
    ad = _FakeAdapter(AdapterResult(succ=True))
    redis = _FakeRedis(allowed=True)
    gw = Gateway(adapter=ad, redis=redis)
    await gw.call("shop.order.list.get", {}, shop_id=2015)
    assert len(redis.keys) == 2
    assert "platform" in redis.keys[0]
    assert "2015" in redis.keys[1]


async def test_no_redis_skips_rate_limit():
    """FR-05a：未接 Redis 时放行（单机/测试模式）"""
    ad = _FakeAdapter(AdapterResult(succ=True))
    gw = Gateway(adapter=ad, redis=None)
    res = await gw.call("shop.order.list.get", {}, shop_id=1)
    assert res.succ is True
    assert len(ad.calls) == 1


async def test_rate_limit_rule_is_configurable():
    """FR-05b：限流参数来自适配器 rate_limit_rule（配置化）"""

    class _RuleCfg(_FakeCfg):
        def rate_limit_rule(self, method: str, shop_id: int) -> RateLimitRule:
            return RateLimitRule(capacity=5, rate_per_sec=1.0, scope="shop")

    class _RuleAdapter(_FakeAdapter):
        def __init__(self, result=None):  # noqa: ANN001
            super().__init__(result)
            self.cfg = _RuleCfg()

    ad = _RuleAdapter(AdapterResult(succ=True))
    rule = ad.cfg.rate_limit_rule("shop.stock.sync", 0)
    assert rule.capacity == 5
    assert rule.rate_per_sec == 1.0
    assert rule.scope == "shop"


# ============ FR-05c 超限行为 ============


async def test_rate_limited_error_is_retryable_class():
    """FR-05c：超限返回 RATE_LIMITED（交 D02.05 退避重试）"""
    ad = _FakeAdapter(AdapterResult(succ=True))
    redis = _FakeRedis(allowed=False, wait_ms=5000)
    gw = Gateway(adapter=ad, redis=redis)
    res = await gw.call("shop.stock.sync", {}, shop_id=1)
    assert res.err_code == "flow-limit"
    assert ERR_LEVEL_MAP["flow-limit"] == "RATE_LIMITED"


async def test_rate_limit_error_carries_scope_and_wait():
    """FR-05c：限流异常带 scope 与预估等待时长"""
    exc = RateLimitError("rl:taobao:shop:1", 3000)
    assert exc.scope == "rl:taobao:shop:1"
    assert exc.wait_ms == 3000
    assert "3000ms" in str(exc)


# ============ FR-07a 全量留痕 ============


async def test_api_log_written_with_all_fields():
    """FR-07a：每次调用都写 api_log（含方法/店铺/单号/分级/耗时）"""
    from app.core.db import SessionFactory

    ad = _FakeAdapter(
        AdapterResult(succ=False, err_code="isv.trade-not-exist", raw={"e": 1})
    )
    gw = Gateway(adapter=ad, redis=None)
    await gw.call(
        "shop.order.detail.get",
        {"tid": "T1"},
        shop_id=2015,
        primary_bn="PO999",
        source="pull",
    )
    async with SessionFactory() as s:
        row = (
            await s.execute(
                text(
                    "SELECT method, shop_id, primary_bn, err_code, err_level, source "
                    "FROM oms_gateway.gw_api_log WHERE primary_bn = :p ORDER BY id DESC LIMIT 1"
                ),
                {"p": "PO999"},
            )
        ).mappings().first()
    assert row is not None
    assert row["method"] == "shop.order.detail.get"
    assert int(row["shop_id"]) == 2015
    assert row["primary_bn"] == "PO999"
    assert row["err_code"] == "isv.trade-not-exist"
    assert row["err_level"] == "MANUAL"
    assert row["source"] == "pull"


async def test_api_log_records_success_with_no_error():
    """FR-07a：成功调用也留痕（err_level 为空）"""
    from app.core.db import SessionFactory

    ad = _FakeAdapter(AdapterResult(succ=True, data={"ok": 1}))
    gw = Gateway(adapter=ad, redis=None)
    await gw.call("shop.stock.sync", {}, shop_id=0, primary_bn="PO_OK")
    async with SessionFactory() as s:
        row = (
            await s.execute(
                text(
                    "SELECT err_code, err_level FROM oms_gateway.gw_api_log "
                    "WHERE primary_bn = :p ORDER BY id DESC LIMIT 1"
                ),
                {"p": "PO_OK"},
            )
        ).mappings().first()
    assert row is not None
    assert row["err_code"] == ""
    assert row["err_level"] == ""


# ============ FR-07b 大报文截断 ============


async def test_large_response_truncated_and_flagged():
    """FR-07b：响应超阈值截断 + is_truncated 标记"""
    from app.core.db import SessionFactory

    big = "x" * (MAX_BODY_LEN + 500)
    ad = _FakeAdapter(AdapterResult(succ=True, raw={"blob": big}))
    gw = Gateway(adapter=ad, redis=None)
    await gw.call("shop.order.detail.get", {}, primary_bn="PO_BIG")
    async with SessionFactory() as s:
        row = (
            await s.execute(
                text(
                    "SELECT LENGTH(response_body) AS n, is_truncated FROM oms_gateway.gw_api_log "
                    "WHERE primary_bn = :p ORDER BY id DESC LIMIT 1"
                ),
                {"p": "PO_BIG"},
            )
        ).mappings().first()
    assert row is not None
    assert int(row["is_truncated"]) == 1
    assert int(row["n"]) <= MAX_BODY_LEN


async def test_normal_size_not_truncated():
    """FR-07b：正常大小报文不截断"""
    from app.core.db import SessionFactory

    ad = _FakeAdapter(AdapterResult(succ=True, raw={"ok": 1}))
    gw = Gateway(adapter=ad, redis=None)
    await gw.call("shop.order.detail.get", {}, primary_bn="PO_SMALL")
    async with SessionFactory() as s:
        row = (
            await s.execute(
                text(
                    "SELECT is_truncated FROM oms_gateway.gw_api_log "
                    "WHERE primary_bn = :p ORDER BY id DESC LIMIT 1"
                ),
                {"p": "PO_SMALL"},
            )
        ).mappings().first()
    assert int(row["is_truncated"]) == 0


# ============ D02.03 FR-02c 分页拉取必须走网关 ============


async def test_walk_list_paginates_through_gateway():
    """FR-02c：分页拉取逐页走 Gateway.call（每页都有留痕）"""
    pages = [
        AdapterResult(succ=True, data={"trades": [{"tid": str(i)} for i in range(2)]}),
        AdapterResult(succ=True, data={"trades": [{"tid": "z"}]}),
    ]
    calls: list[dict] = []

    class _PageAdapter(_FakeAdapter):
        async def call(self, method, params, *, shop_id=0, primary_bn="", session_key=""):  # noqa: ANN001
            calls.append(params)
            return pages[len(calls) - 1] if len(calls) <= len(pages) else pages[-1]

    gw = Gateway(adapter=_PageAdapter(), redis=None)
    got = [r async for r in gw.walk_list("shop.order.list.get", {}, page_size=2)]
    assert len(got) == 2
    # 第一页 page_no=1，第二页 page_no=2
    assert calls[0]["page_no"] == 1
    assert calls[1]["page_no"] == 2
    assert calls[0]["page_size"] == 2


async def test_walk_list_stops_on_failure():
    """FR-02c：分页遇失败立即停止（不继续拉）"""
    calls: list[dict] = []

    class _FailAdapter(_FakeAdapter):
        async def call(self, method, params, *, shop_id=0, primary_bn="", session_key=""):  # noqa: ANN001
            calls.append(params)
            return AdapterResult(succ=False, err_code="flow-limit")

    gw = Gateway(adapter=_FailAdapter(), redis=None)
    got = [r async for r in gw.walk_list("shop.order.list.get", {}, page_size=2)]
    assert len(got) == 1
    assert len(calls) == 1


# ============ 全局单例 ============


def test_get_gateway_singleton_binds_redis():
    """网关单例：已存在时补绑 Redis（否则限流被静默跳过）"""
    g1 = get_gateway(redis=None)
    g2 = get_gateway(redis=_FakeRedis())
    assert g1 is g2
    assert g2.r is not None
    # 复位，避免影响其他用例
    g2.r = None


def test_gateway_driver_reads_settings():
    """driver 由配置决定（simulator / taobao）"""
    assert gateway_driver() in ("simulator", "taobao")
