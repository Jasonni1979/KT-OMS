"""平台售后报文自动同步单测（D05.01 FR-01a · G1 缺口）

覆盖（端到端脚本 `app/scripts/aftersale_pull_e2e.py` 之外的**单元级**口径）：
- 适配器 `refund_list_get`：请求参数构造 + 报文解码（`AdapterResult.refunds`）
- 网关 `refund_list_get`：必须走 Gateway.call（限流 + api_log 留痕）
- 报文映射：售后类型 / 原因码 / 货物状态
- 服务落库：建单（类型 + 金额 + 原单关联 + 待审核）/ 幂等复用 / 待关联异常态 / 不可识别跳过
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

import pytest
from sqlalchemy import text

from app.adapters.base import METHOD_REFUND_LIST_GET, AdapterResult
from app.adapters.taobao import TaobaoAdapter, refund_list_params
from app.core.db import AuthContext, SessionFactory, engine, set_auth_context
from app.modules.m6_aftersale.contract import (
    GOODS_RECEIVED,
    GOODS_SHIPPED,
    GOODS_UNSHIPPED,
    REASON_FALLBACK,
    REFUND_TYPE_MAP,
    ST_PENDING_LINK,
    ST_WAIT_AUDIT,
    TYPE_EXCHANGE,
    TYPE_REFUND_ONLY,
    TYPE_RESHIPMENT,
    TYPE_RETURN_REFUND,
    AftersalePullService,
)

#: 售后申请单号前缀（测试结束后按前缀清理）
APPLY_PREFIX = "TRF"


def _uid() -> str:
    return uuid.uuid4().hex[:8].upper()


class _FakeTransport:
    """假传输层：记录出向报文，返回固定响应（不触网）"""

    def __init__(self, body: dict):
        self.body = body
        self.sent: list[dict] = []

    async def send(self, method, url, payload, timeout):  # noqa: ANN001
        self.sent.append(payload)
        return 200, self.body

    async def close(self) -> None:
        return None


class _FakeGateway:
    """假网关：按脚本返回平台售后报文（不触网）"""

    def __init__(self, messages: list[dict] | None = None, succ: bool = True):
        self.messages = messages or []
        self.succ = succ
        self.calls: list[dict] = []

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
        self.calls.append(
            {
                "shop_id": shop_id,
                "start_modified": start_modified,
                "end_modified": end_modified,
                "page_no": page_no,
                "page_size": page_size,
                "primary_bn": primary_bn,
            }
        )
        if not self.succ:
            return AdapterResult(
                succ=False, err_code="isv.trade-service-error", err_msg="模拟平台失败"
            )
        return AdapterResult(
            succ=True,
            data={"total_results": len(self.messages), "refunds": self.messages},
        )


@pytest.fixture(autouse=True)
async def _ctx():
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    yield


@pytest.fixture(autouse=True)
async def _clean():
    """清理本模块造的数据（售后申请先子表后父表；订单主子表）"""
    yield
    async with engine.begin() as conn:
        for stmt in (
            "DELETE FROM oms_aftersale.aft_return_apply_log WHERE apply_id IN "
            f"(SELECT id FROM oms_aftersale.aft_return_apply "
            f"WHERE platform_aftersale_bn LIKE '{APPLY_PREFIX}%')",
            "DELETE FROM oms_aftersale.aft_return_apply_item WHERE apply_id IN "
            f"(SELECT id FROM oms_aftersale.aft_return_apply "
            f"WHERE platform_aftersale_bn LIKE '{APPLY_PREFIX}%')",
            f"DELETE FROM oms_aftersale.aft_return_apply "
            f"WHERE platform_aftersale_bn LIKE '{APPLY_PREFIX}%'",
            "DELETE FROM oms_order.ord_order_item WHERE order_id IN "
            "(SELECT id FROM oms_order.ord_order WHERE order_bn LIKE 'T\\_PULL%')",
            "DELETE FROM oms_order.ord_order WHERE order_bn LIKE 'T\\_PULL%'",
        ):
            await conn.execute(text(stmt))


async def _mk_order(nums: int = 2, paid: float = 100.0) -> tuple[int, int, str]:
    """造订单 + 1 行（返回 订单 id / 订单行 id / 平台单号）"""
    order_bn = f"T_PULL{_uid()}"
    platform_order_bn = f"TPULL{_uid()}"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_order "
                "(tenant_id, owner_id, order_bn, platform_order_bn, shop_id, brand_id, "
                " createway, order_type, order_status, audit_status, fulfill_status, "
                " pay_status, ship_status, list_amount, shop_discount, platform_subsidy, "
                " paid_amount, freight, is_cod, order_time, pay_time, create_time, "
                " update_time, version, is_deleted) "
                "VALUES (1, 1, :obn, :pon, 0, 0, 'platform', 'normal', 'processing', "
                "'passed', 'pending', 'paid', 'unshipped', :paid, 0, 0, :paid, 0, 0, "
                "NOW(3), NOW(3), NOW(3), NOW(3), 0, 0)"
            ),
            {"obn": order_bn, "pon": platform_order_bn, "paid": paid},
        )
        oid = int(
            (
                await conn.execute(
                    text("SELECT id FROM oms_order.ord_order WHERE order_bn = :obn"),
                    {"obn": order_bn},
                )
            ).scalar()
            or 0
        )
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_order_item "
                "(tenant_id, owner_id, order_id, platform_sku_code, bm_id, bm_number, "
                " bm_name, nums, list_price, list_amount, paid_amount, parse_status, "
                " create_time, update_time, version, is_deleted) "
                "VALUES (1, 1, :oid, :sku, 0, :bmn, '拉取测试物料', :nums, :price, "
                ":amount, :amount, 'parsed', NOW(3), NOW(3), 0, 0)"
            ),
            {
                "oid": oid,
                "sku": f"T_PULL_SKU_{_uid()}",
                "bmn": f"T_PULL_BM_{_uid()}",
                "nums": nums,
                "price": paid / max(nums, 1),
                "amount": paid,
            },
        )
        item_id = int(
            (
                await conn.execute(
                    text(
                        "SELECT id FROM oms_order.ord_order_item WHERE order_id = :oid "
                        "ORDER BY id DESC LIMIT 1"
                    ),
                    {"oid": oid},
                )
            ).scalar()
            or 0
        )
    return oid, item_id, platform_order_bn


def _refund_msg(tid: str, refund_type: str = "ONLY_REFUND", **kw: Any) -> dict:
    """平台售后报文（形状对齐 mock-platform 的 build_refund）"""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    msg = {
        "refund_id": f"{APPLY_PREFIX}{_uid()}",
        "tid": tid,
        "status": "SUCCESS",
        "refund_type": refund_type,
        "reason": "不想要了",
        "refund_amount": 99.0,
        "item_id": "ITEM_TSHIRT_001",
        "sku_id": "SKU_TSHIRT_S",
        "num": 1,
        "created": ts,
        "modified": ts,
        "goods_condition": "NORMAL",
    }
    msg.update(kw)
    return msg


# ============ 适配器层 ============


async def test_adapter_refund_list_get_builds_params():
    """适配器：请求参数按平台口径构造（时间窗 + 分页）"""
    body = {"refund_list_get_response": {"total_results": 1, "refunds": [{"refund_id": "R1"}]}}
    tr = _FakeTransport(body)
    ad = TaobaoAdapter(transport=tr)
    res = await ad.refund_list_get(
        shop_id=7,
        start_modified="2026-01-01 00:00:00",
        end_modified="2026-01-02 00:00:00",
        page_no=2,
        page_size=30,
    )
    assert res.succ is True
    assert tr.sent[0]["method"] == METHOD_REFUND_LIST_GET
    assert tr.sent[0]["start_modified"] == "2026-01-01 00:00:00"
    assert tr.sent[0]["end_modified"] == "2026-01-02 00:00:00"
    assert tr.sent[0]["page_no"] == 2
    assert tr.sent[0]["page_size"] == 30


async def test_adapter_result_refunds_accessor():
    """适配器：报文里的 refunds 数组可取（与 trades 同构）"""
    res = AdapterResult(
        succ=True, data={"total_results": 2, "refunds": [{"refund_id": "R1"}, {"refund_id": "R2"}]}
    )
    assert len(res.refunds) == 2
    assert res.refunds[0]["refund_id"] == "R1"
    assert res.total_results == 2


def test_refund_list_params_shared_by_adapter_and_gateway():
    """参数构造器唯一口径（适配器与网关共用 → 不漂移）"""
    assert refund_list_params("2026-01-01 00:00:00", "2026-01-02 00:00:00") == {
        "start_modified": "2026-01-01 00:00:00",
        "end_modified": "2026-01-02 00:00:00",
        "page_no": 1,
        "page_size": 50,
    }


async def test_gateway_refund_list_get_writes_api_log():
    """网关：售后拉取必须走 Gateway.call（否则无 api_log 留痕 → 丢单不可查）"""
    from app.modules.m7_integration.service.gateway import Gateway

    class _Adapter:
        platform = "taobao"
        adapter_version = "v1"
        mapping_version = "v1"

        class _Cfg:
            def rate_limit_rule(self, method: str, shop_id: int):  # noqa: ANN001
                from app.adapters.base import RateLimitRule

                return RateLimitRule(capacity=40, rate_per_sec=20.0, scope="platform")

        cfg = _Cfg()

        async def call(self, method, params, *, shop_id=0, primary_bn="", session_key=""):  # noqa: ANN001
            return AdapterResult(succ=True, data={"total_results": 0, "refunds": []})

    gw = Gateway(adapter=_Adapter(), redis=None)  # type: ignore[arg-type]
    await gw.refund_list_get(
        shop_id=2015,
        start_modified="2026-01-01 00:00:00",
        end_modified="2026-01-02 00:00:00",
        primary_bn="AFTLOG_1",
    )
    async with SessionFactory() as s:
        row = (
            await s.execute(
                text(
                    "SELECT method, source, primary_bn FROM oms_gateway.gw_api_log "
                    "WHERE primary_bn = :p ORDER BY id DESC LIMIT 1"
                ),
                {"p": "AFTLOG_1"},
            )
        ).mappings().first()
    assert row is not None
    assert row["method"] == METHOD_REFUND_LIST_GET
    assert row["source"] == "aftersale_pull"


# ============ 报文映射 ============


def test_refund_type_map_covers_four_types():
    """FR-01d：平台售后类型 → OMS 售后类型（1/2/3/4）"""
    assert REFUND_TYPE_MAP["ONLY_REFUND"] == TYPE_REFUND_ONLY
    assert REFUND_TYPE_MAP["RETURN_GOODS"] == TYPE_RETURN_REFUND
    assert REFUND_TYPE_MAP["EXCHANGE"] == TYPE_EXCHANGE
    assert REFUND_TYPE_MAP["RESHIPMENT"] == TYPE_RESHIPMENT
    assert len(REFUND_TYPE_MAP) == 4


def test_reason_code_mapping_prefers_defect_then_keywords():
    """D05.01 §5.5：质检不良优先 → 关键词 → 兜底「其他-待归类」"""
    from app.modules.m6_aftersale.service.aftersale_pull import _reason_code

    assert _reason_code({"goods_condition": "QUALITY_DEFECTIVE", "reason": "七天无理由退换"}) == (
        "QUALITY_ISSUE"
    )
    assert _reason_code({"reason": "七天无理由退换"}) == "SEVEN_NO_REASON"
    assert _reason_code({"reason": "不想要了"}) == "WRONG_PURCHASE"
    assert _reason_code({"reason": "拍错/多拍"}) == "WRONG_PURCHASE"
    assert _reason_code({"reason": "商品破损"}) == "DAMAGED"
    assert _reason_code({"reason": "不认识的缘由"}) == REASON_FALLBACK
    assert _reason_code({}) == REASON_FALLBACK


def test_goods_status_derivation():
    """D05.01 goods_status：退货/换货 → 已收货；仅退款按订单发货状态推导"""
    from app.modules.m6_aftersale.service.aftersale_pull import _goods_status

    assert _goods_status(TYPE_RETURN_REFUND, "unshipped") == GOODS_RECEIVED
    assert _goods_status(TYPE_EXCHANGE, "shipped") == GOODS_RECEIVED
    assert _goods_status(TYPE_REFUND_ONLY, "unshipped") == GOODS_UNSHIPPED
    assert _goods_status(TYPE_REFUND_ONLY, "shipped") == GOODS_SHIPPED
    assert _goods_status(TYPE_REFUND_ONLY, "") == GOODS_UNSHIPPED


# ============ 服务落库 ============


async def test_pull_refunds_creates_apply_linked_to_order():
    """平台售后报文 → 售后申请单（类型 / 金额 / 原单关联 / 待审核）"""
    oid, item_id, pon = await _mk_order()
    msg = _refund_msg(pon, "RETURN_GOODS", reason="七天无理由退换")
    gw = _FakeGateway([msg])
    async with SessionFactory() as s:
        svc = AftersalePullService(s, gw)  # type: ignore[arg-type]
        stat = await svc.pull_refunds(
            0, start_modified="2026-01-01 00:00:00", end_modified="2026-01-02 00:00:00"
        )
        row = (
            await s.execute(
                text(
                    "SELECT id, aftersale_type, apply_amount_customer, status, order_id, "
                    "       platform_aftersale_bn, reason_code, platform_extra "
                    "FROM oms_aftersale.aft_return_apply "
                    "WHERE platform_aftersale_bn = :bn"
                ),
                {"bn": msg["refund_id"]},
            )
        ).mappings().first()
        item = (
            await s.execute(
                text(
                    "SELECT order_item_id, apply_num FROM oms_aftersale.aft_return_apply_item "
                    "WHERE apply_id = :aid"
                ),
                {"aid": row["id"] if row else 0},
            )
        ).mappings().first()
    assert stat["ok"] is True
    assert stat["created"] == 1
    assert stat["errors"] == 0
    assert stat["pending_link"] == 0
    assert row is not None
    assert int(row["aftersale_type"]) == TYPE_RETURN_REFUND
    assert int(round(float(row["apply_amount_customer"]) * 100)) == 9900
    assert int(row["status"]) == ST_WAIT_AUDIT
    assert int(row["order_id"]) == oid
    assert row["reason_code"] == "SEVEN_NO_REASON"
    # platform_extra 是 JSON 列（驱动返回字符串，需自行解析）
    extra = row["platform_extra"]
    extra = json.loads(extra) if isinstance(extra, str) else extra
    assert extra["refund_id"] == msg["refund_id"]
    assert item is not None
    assert int(item["order_item_id"]) == item_id
    assert int(item["apply_num"]) == 1


async def test_pull_refunds_is_idempotent():
    """FR-01b：同一平台售后单重复拉取 → 复用已有单，不新增"""
    _oid, _item_id, pon = await _mk_order()
    msg = _refund_msg(pon)
    gw = _FakeGateway([msg])
    async with SessionFactory() as s:
        svc = AftersalePullService(s, gw)  # type: ignore[arg-type]
        first = await svc.pull_refunds(
            0, start_modified="2026-01-01 00:00:00", end_modified="2026-01-02 00:00:00"
        )
        second = await svc.pull_refunds(
            0, start_modified="2026-01-01 00:00:00", end_modified="2026-01-02 00:00:00"
        )
        n = int(
            (
                await s.execute(
                    text(
                        "SELECT COUNT(*) FROM oms_aftersale.aft_return_apply "
                        "WHERE platform_aftersale_bn = :bn"
                    ),
                    {"bn": msg["refund_id"]},
                )
            ).scalar()
            or 0
        )
    assert first["created"] == 1
    assert second["created"] == 0
    assert second["idempotent"] == 1
    assert n == 1


async def test_pull_refunds_order_missing_goes_pending_link():
    """FR-01e：订单未进 OMS → 落「待关联」异常态（不丢单）"""
    msg = _refund_msg("TPULL_NOT_EXIST")
    gw = _FakeGateway([msg])
    async with SessionFactory() as s:
        svc = AftersalePullService(s, gw)  # type: ignore[arg-type]
        stat = await svc.pull_refunds(
            0, start_modified="2026-01-01 00:00:00", end_modified="2026-01-02 00:00:00"
        )
        row = (
            await s.execute(
                text(
                    "SELECT status, order_id FROM oms_aftersale.aft_return_apply "
                    "WHERE platform_aftersale_bn = :bn"
                ),
                {"bn": msg["refund_id"]},
            )
        ).mappings().first()
    assert stat["created"] == 1
    assert stat["pending_link"] == 1
    assert row is not None
    assert int(row["status"]) == ST_PENDING_LINK
    assert int(row["order_id"]) == 0


async def test_pull_refunds_skips_unrecognised_refund_type():
    """平台售后类型不可识别 → 跳过（计入 skipped，不建单）"""
    msg = _refund_msg("TPULL_ANY", refund_type="SOMETHING_NEW")
    gw = _FakeGateway([msg])
    async with SessionFactory() as s:
        svc = AftersalePullService(s, gw)  # type: ignore[arg-type]
        stat = await svc.pull_refunds(
            0, start_modified="2026-01-01 00:00:00", end_modified="2026-01-02 00:00:00"
        )
    assert stat["created"] == 0
    assert stat["skipped"] == 1
    assert stat["errors"] == 0


async def test_pull_refunds_reports_platform_failure():
    """平台调用失败 → ok=False + 错误码（不静默吞掉）"""
    gw = _FakeGateway([], succ=False)
    async with SessionFactory() as s:
        svc = AftersalePullService(s, gw)  # type: ignore[arg-type]
        stat = await svc.pull_refunds(
            0, start_modified="2026-01-01 00:00:00", end_modified="2026-01-02 00:00:00"
        )
    assert stat["ok"] is False
    assert stat["err_code"] == "isv.trade-service-error"
    assert stat["created"] == 0
