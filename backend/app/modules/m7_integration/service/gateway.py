"""平台 Gateway 网关服务（D02.01 五层管线 + FR-05 限流 + FR-07 api_log）

管线顺序：**限流 → 签名 → 传输 → 报文 → 日志**。

- 限流：Redis + Lua 令牌桶，平台级与店铺级**两级串联**（§5.2），
  任一级等待超时 → RATE_LIMITED（不发起调用）
- api_log：出向调用全量留痕（请求/响应超 2KB 截断 + is_truncated 标记），供排查与对账
- 错误分级：RETRYABLE / RATE_LIMITED / AUTH / MANUAL / FATAL（决定重试策略）
"""

import json
import time
from pathlib import Path
from typing import Any

from redis.asyncio import Redis

from app.adapters.base import METHOD_REFUND_LIST_GET, AdapterResult
from app.adapters.taobao import TaobaoAdapter, refund_list_params
from app.core.config import settings
from app.models.gateway import GwApiLog

#: 报文截断阈值（DB-00 §1.3：>2KB 截断 + is_truncated 标记）
MAX_BODY_LEN = 2000

#: 平台错误码 → 统一错误分级（D02.01 FR-06/08）
ERR_LEVEL_MAP = {
    "isv.invalid-signature": "AUTH",
    "isv.invalid-session-key": "AUTH",
    "isv.invalid-app-key": "AUTH",
    "isv.invalid-timestamp": "AUTH",
    "flow-limit": "RATE_LIMITED",
    "isv.trade-service-error": "RETRYABLE",
    "isv.trade-not-exist": "MANUAL",
    "isv.item-not-exist": "MANUAL",
    "isv.method-not-allowed": "FATAL",
    "isv.unknown-error": "RETRYABLE",
    "isv.empty-response": "RETRYABLE",
}

# ⚠ 层级：app/modules/m7_integration/service/x.py → parents[3] 才是 app/
_LUA_DIR = Path(__file__).resolve().parents[3] / "infra" / "lua"


class RateLimitError(Exception):
    """限流拒绝（两级串联任一超时）"""

    def __init__(self, scope: str, wait_ms: int):
        self.scope = scope
        self.wait_ms = wait_ms
        super().__init__(f"限流拒绝({scope})，预估等待 {wait_ms}ms")


class Gateway:
    """网关：业务域唯一的平台调用入口"""

    def __init__(self, adapter: TaobaoAdapter | None = None, redis: Redis | None = None):
        self.adapter = adapter or TaobaoAdapter()
        self.r = redis
        self._rate_script: str | None = None

    # ---------- 限流（FR-05）----------

    def _load_script(self) -> str:
        if self._rate_script is None:
            self._rate_script = (_LUA_DIR / "rate_limit.lua").read_text(encoding="utf-8")
        return self._rate_script

    async def _acquire(self, key: str, capacity: int, rate: float) -> bool:
        """取令牌；返回是否放行"""
        if self.r is None:
            return True
        script = self._load_script()
        now_ms = int(time.time() * 1000)
        res = await self.r.eval(script, 1, key, capacity, rate, now_ms)
        allowed = int(res[0])
        wait_ms = int(res[1])
        if not allowed and wait_ms > 1000:
            raise RateLimitError(key, wait_ms)
        return bool(allowed)

    async def _check_limits(self, method: str, shop_id: int) -> None:
        """两级串联限流：平台级 → 店铺级"""
        if self.r is None:
            return
        rule = self.adapter.cfg.rate_limit_rule(method, shop_id)
        await self._acquire(
            "rl:taobao:platform:app", rule.capacity, rule.rate_per_sec
        )
        if shop_id:
            await self._acquire(
                f"rl:taobao:shop:{shop_id}", rule.capacity, rule.rate_per_sec
            )

    # ---------- api_log（FR-07）----------

    async def _write_log(
        self,
        *,
        method: str,
        shop_id: int,
        primary_bn: str,
        request_params: dict,
        response_body: Any,
        http_status: int,
        err_code: str,
        err_level: str,
        spend_ms: int,
        source: str,
        msg_id: str = "",
    ) -> None:
        from app.core.db import SessionFactory

        req = json.dumps(request_params, ensure_ascii=False, default=str)
        resp = json.dumps(response_body, ensure_ascii=False, default=str)
        truncated = 0
        if len(req) > MAX_BODY_LEN:
            req = req[:MAX_BODY_LEN]
            truncated = 1
        if len(resp) > MAX_BODY_LEN:
            resp = resp[:MAX_BODY_LEN]
            truncated = 1
        async with SessionFactory() as s:
            s.add(
                GwApiLog(
                    log_bn=f"LOG{int(time.time() * 1000)}",
                    direction=1,
                    method=method,
                    native_method=method,
                    platform=self.adapter.platform,
                    shop_id=shop_id,
                    primary_bn=primary_bn,
                    request_params=req,
                    response_body=resp,
                    is_truncated=truncated,
                    http_status=http_status,
                    err_code=err_code,
                    err_level=err_level,
                    spendtime_ms=spend_ms,
                    msg_id=msg_id,
                    source=source,
                )
            )
            await s.commit()

    # ---------- 调用 ----------

    async def call(
        self,
        method: str,
        params: dict,
        *,
        shop_id: int = 0,
        primary_bn: str = "",
        source: str = "pull",
        session_key: str = "",
    ) -> AdapterResult:
        """统一调用入口（限流 → 签名 → 传输 → 报文 → 日志）"""
        try:
            await self._check_limits(method, shop_id)
        except RateLimitError as exc:
            await self._write_log(
                method=method,
                shop_id=shop_id,
                primary_bn=primary_bn,
                request_params=params,
                response_body={"error": str(exc)},
                http_status=429,
                err_code="flow-limit",
                err_level="RATE_LIMITED",
                spend_ms=0,
                source=source,
            )
            return AdapterResult(
                succ=False,
                err_code="flow-limit",
                err_msg=f"限流拒绝({exc.scope})，预估等待 {exc.wait_ms}ms",
            )

        t0 = time.perf_counter()
        res = await self.adapter.call(
            method,
            params,
            shop_id=shop_id,
            primary_bn=primary_bn,
            session_key=session_key,
        )
        spend_ms = int((time.perf_counter() - t0) * 1000)
        err_level = "" if res.succ else ERR_LEVEL_MAP.get(res.err_code, "RETRYABLE")
        await self._write_log(
            method=method,
            shop_id=shop_id,
            primary_bn=primary_bn,
            request_params=params,
            response_body=res.raw or {},
            http_status=200,
            err_code=res.err_code,
            err_level=err_level,
            spend_ms=spend_ms,
            source=source,
            msg_id=res.msg_id,
        )
        return res


    async def refund_list_get(
        self,
        *,
        shop_id: int,
        start_modified: Any,
        end_modified: Any,
        page_no: int = 1,
        page_size: int = 50,
        primary_bn: str = "",
    ) -> AdapterResult:
        """售后增量列表拉取（D05.01 FR-01a）

        **必须走 Gateway.call**（而非直接调适配器）—— 否则绕过限流与 api_log，
        平台调用失败将无留痕（售后丢单是隐蔽故障）。
        """
        return await self.call(
            METHOD_REFUND_LIST_GET,
            refund_list_params(start_modified, end_modified, page_no, page_size),
            shop_id=shop_id,
            primary_bn=primary_bn,
            source="aftersale_pull",
        )

    async def walk_list(
        self,
        method: str,
        params_for_page: Any,
        *,
        shop_id: int = 0,
        primary_bn: str = "",
        source: str = "pull",
        page_size: int = 50,
        max_pages: int = 200,
    ):
        """分页拉取（D02.03 FR-02c）

        **必须走 Gateway.call**（而非直接调适配器）——否则绕过限流与 api_log，
        平台调用失败将无留痕（拉单丢单是隐蔽故障）。
        """
        page_no = 1
        while page_no <= max_pages:
            params = dict(params_for_page)
            params["page_no"] = page_no
            params["page_size"] = page_size
            res = await self.call(
                method, params, shop_id=shop_id, primary_bn=primary_bn, source=source
            )
            yield res
            if not res.succ:
                return
            if not res.trades or len(res.trades) < page_size:
                return
            page_no += 1


_gateway: Gateway | None = None


def get_gateway(redis: Redis | None = None) -> Gateway:
    """全局网关单例（适配器复用连接池）

    单例已存在时补绑 Redis —— 否则限流会被静默跳过（redis=None → 直接放行）。
    """
    global _gateway
    if _gateway is None:
        _gateway = Gateway(redis=redis)
    elif redis is not None and _gateway.r is None:
        _gateway.r = redis
    return _gateway


def gateway_driver() -> str:
    """当前 driver（simulator / taobao），用于接口返回与排查"""
    return settings.platform_driver
