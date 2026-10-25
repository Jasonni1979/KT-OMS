"""淘系平台模拟器主服务（mock-platform）

用途（V1.1 计划 §2.1/§2.2）：M1-M3 全程在仿真环境开发与内测，不依赖淘系测试环境到位。

对外接口：
- POST /api/taobao/router   —— TOP 风格统一入口（method 参数路由 + 签名校验 + 错误码）
- POST /sim/orders          —— 造单引擎（场景批量生成）
- GET  /sim/orders          —— 查看订单池（调试）
- POST /sim/reset           —— 清空订单池
- GET  /healthz             —— 存活探针

跑法：uvicorn app.main:app --port 9000（或 docker compose service mock-platform）
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.protocol import INJECTABLE_ERRORS, TopError, make_error_response, verify_sign
from app.store import SCENARIOS, TradeStore, build_refund, build_trade

APP_KEY = os.getenv("MOCK_TAOBAO_APP_KEY", "mock_app_key")
APP_SECRET = os.getenv("MOCK_TAOBAO_APP_SECRET", "mock_app_secret")
VALID_SESSIONS = {
    s for s in os.getenv("MOCK_TAOBAO_SESSIONS", "sim_session_001").split(",") if s
}
SIGN_REQUIRED = os.getenv("MOCK_TAOBAO_VERIFY_SIGN", "1") == "1"

app = FastAPI(title="KT-OMS 淘系平台模拟器", version="1.0.0")
store = TradeStore()
_refunds: list[dict] = []
_writebacks: list[dict] = []   # OMS 回传（发货/库存/价格）落点，供断言


# ---------------- TOP 统一入口 ----------------

@app.post("/api/taobao/router")
async def top_router(request: Request) -> JSONResponse:
    params: dict[str, Any] = dict(await request.json())
    method = str(params.get("method", ""))
    ts = params.get("timestamp")
    session = params.get("session")

    # ① 签名校验
    if SIGN_REQUIRED and not verify_sign(params, APP_SECRET):
        return JSONResponse(make_error_response(
            "isv.invalid-signature", "Invalid signature", "isv.invalid-signature",
            "签名验证失败（模拟器要求 sign 正确）",
        ))
    # ② 时间戳防重放（>1h 拒绝）
    if ts:
        try:
            if abs(time.time() - float(ts)) > 3600:
                return JSONResponse(make_error_response(
                    "isv.invalid-timestamp", "Invalid timestamp"))
        except (TypeError, ValueError):
            return JSONResponse(make_error_response("isv.invalid-timestamp", "Invalid timestamp"))
    # ③ Session 校验
    if session is not None and str(session) not in VALID_SESSIONS:
        return JSONResponse(make_error_response(
            "isv.invalid-session-key", "Invalid session key",
            "isv.invalid-session-key", "Session 失效或无效（模拟器可注入该错误）",
        ))
    # ④ 错误注入（让适配器重试/降级逻辑在仿真期被真实锻炼）
    inject = params.get("_inject_error")
    if inject:
        if inject not in INJECTABLE_ERRORS:
            return JSONResponse(make_error_response(
                "isv.unknown-error", f"未支持的注入错误码: {inject}"))
        return JSONResponse(make_error_response(
            inject, INJECTABLE_ERRORS[inject], inject, "由 _inject_error 注入（模拟器）"))

    handler = _ROUTES.get(method)
    if handler is None:
        return JSONResponse(make_error_response(
            "isv.method-not-allowed", f"Method not allowed: {method}"))
    try:
        data = handler(params)
    except TopError as e:
        return JSONResponse(make_error_response(e.code, e.message, e.sub_code, e.sub_msg))
    return JSONResponse(data)


# ---------------- 平台方法实现 ----------------

def _trade_sold_get(params: dict) -> dict:
    """taobao.trade.sold.get —— 增量窗口 + 分页"""
    page_no = int(params.get("page_no", 1))
    page_size = int(params.get("page_size", 50))
    items, total = store.query(
        start_modified=params.get("start_modified"),
        end_modified=params.get("end_modified"),
        status=params.get("status"),
        shop_id=params.get("shop_id"),
        page_no=page_no,
        page_size=page_size,
    )
    return {
        "trade_sold_get_response": {
            "total_results": total,
            "trades": [t.to_dict() for t in items],
        }
    }


def _trade_detail_get(params: dict) -> dict:
    """taobao.trade.detail.get —— 单号详情（含收货人全量）"""
    tid = str(params.get("tid", ""))
    trade = store.get(tid)
    if trade is None:
        raise TopError("isv.trade-not-exist", "Trade not exist", "isv.trade-not-exist",
                       f"订单不存在: {tid}")
    return {"trade_detail_get_response": {"trade": trade.to_dict()}}


def _item_get(params: dict) -> dict:
    """taobao.item.get —— 商品查询（未知商品自动建档 + 可售对账用）"""
    item_id = str(params.get("item_id", ""))
    from app.store import ITEM_POOL, platform_stock
    hit = next((i for i in ITEM_POOL if i[0] == item_id), None)
    if hit is None:
        # 支持按平台 SKU 编码查询（OMS 侧只知 SKU 编码，可售对账用）
        hit = next((i for i in ITEM_POOL if i[1] == item_id), None)
    if hit is None:
        raise TopError("isv.item-not-exist", "Item not exist", "isv.item-not-exist",
                       f"商品不存在: {item_id}")
    return {
        "item_get_response": {
            "item": {
                "item_id": hit[0], "title": hit[2], "num_iid": 100 + abs(hash(hit[0])) % 900,
                "cid": 5000, "props": {"规格": hit[3]},
                "skus": {
                    "sku": [{
                        "sku_id": hit[1], "num_iid": 100 + abs(hash(hit[0])) % 900,
                        "properties": "规格:" + hit[3], "price": "199.00",
                        "quantity": platform_stock(hit[1]), "outer_id": hit[1],
                    }]
                },
            }
        }
    }


def _item_update(params: dict) -> dict:
    """taobao.item.update —— 平台库存（可售数）回写（D04.08 FR-03c）"""
    sku_id = str(params.get("sku_id", ""))
    num = int(params.get("num") or 0)
    if not sku_id:
        raise TopError("isv.item-not-exist", "Item not exist", "isv.item-not-exist",
                       "缺少 sku_id")
    from app.store import set_platform_stock
    set_platform_stock(sku_id, num)
    _writebacks.append({
        "type": "inventory", "sku_id": sku_id, "num": num,
        "received_at": datetime.now().isoformat(timespec="seconds"),
    })
    return {"item_update_response": {"item": {"sku_id": sku_id, "num": num}}}


def _logistics_online_send(params: dict) -> dict:
    """taobao.logistics.online.send —— OMS 发货回传（模拟器接收并留档供断言）"""
    tid = str(params.get("tid", ""))
    if not tid:
        raise TopError("isv.trade-not-exist", "Trade not exist", "isv.trade-not-exist",
                       "缺少 tid")
    trade = store.get(tid)
    if trade is None:
        raise TopError("isv.trade-not-exist", "Trade not exist", "isv.trade-not-exist",
                       f"订单不存在: {tid}")
    trade.status = "WAIT_BUYER_CONFIRM_GOODS"
    trade.modified = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _writebacks.append({
        "type": "logistics", "tid": tid,
        "logistics_company": params.get("logistics_company"),
        "logistics_no": params.get("logistics_no"),
        "received_at": datetime.now().isoformat(timespec="seconds"),
    })
    return {
        "logistics_online_send_response": {
            "shipping": {"tid": tid, "status": "WAIT_BUYER_CONFIRM_GOODS"}
        }
    }


def _refund_get(params: dict) -> dict:
    """taobao.refund.get —— 售后单查询"""
    tid = str(params.get("tid", ""))
    hits = [r for r in _refunds if not tid or r["tid"] == tid]
    return {"refund_get_response": {"total_results": len(hits), "refunds": hits}}


def _refund_list_get(params: dict) -> dict:
    """taobao.refund.list.get —— 售后增量列表（modified 时间窗）"""
    items = list(_refunds)
    sm = params.get("start_modified")
    em = params.get("end_modified")
    if sm:
        st = datetime.strptime(sm, "%Y-%m-%d %H:%M:%S").timestamp()
        items = [r for r in items
                 if datetime.strptime(r["modified"], "%Y-%m-%d %H:%M:%S").timestamp() >= st]
    if em:
        et = datetime.strptime(em, "%Y-%m-%d %H:%M:%S").timestamp()
        items = [r for r in items
                 if datetime.strptime(r["modified"], "%Y-%m-%d %H:%M:%S").timestamp() <= et]
    return {"refund_list_get_response": {"total_results": len(items), "refunds": items}}


_ROUTES = {
    "taobao.trade.sold.get": _trade_sold_get,
    "taobao.trade.detail.get": _trade_detail_get,
    "taobao.item.get": _item_get,
    "taobao.item.update": _item_update,
    "taobao.logistics.online.send": _logistics_online_send,
    "taobao.refund.get": _refund_get,
    "taobao.refund.list.get": _refund_list_get,
}


# ---------------- 造单引擎（仿真下单） ----------------

class GenerateReq(BaseModel):
    scenario: str = Field(default="normal", description=f"场景：{'/'.join(SCENARIOS)}")
    count: int = Field(default=1, ge=1, le=200)
    shop_id: str = "SIM_SHOP_001"
    with_refund: bool = Field(default=False, description="同时生成售后单")


@app.post("/sim/orders")
async def generate_orders(body: GenerateReq) -> dict:
    """造单引擎：按场景批量生成订单（供 M1 开发期供单 + M3 端到端内测造单）"""
    if body.scenario not in SCENARIOS:
        return {"code": 400, "message": f"未知场景: {body.scenario}",
                "data": {"scenarios": list(SCENARIOS)}}
    made = []
    for _ in range(body.count):
        t = build_trade(store, body.scenario, shop_id=body.shop_id)
        store.add(t)
        made.append(t.tid)
        if body.with_refund:
            refund_scn = {"refund_only": "refund_only", "return_refund": "return_refund",
                          "defective_return": "defective_return"}.get(body.scenario)
            if refund_scn:
                _refunds.append(build_refund(t.tid, refund_scn))
    return {"code": 0, "message": "ok",
            "data": {"scenario": body.scenario, "count": len(made), "tids": made,
                     "scenarios": list(SCENARIOS)}}


@app.get("/sim/orders")
async def list_orders() -> dict:
    trades = store.all()
    return {"code": 0, "message": "ok",
            "data": {"total": len(trades), "orders": [t.to_dict() for t in trades]}}


@app.post("/sim/reset")
async def reset() -> dict:
    n = store.clear()
    _refunds.clear()
    _writebacks.clear()
    return {"code": 0, "message": "ok", "data": {"cleared": n}}


@app.get("/sim/writebacks")
async def list_writebacks() -> dict:
    """查看 OMS 回传到模拟器的记录（发货等），用于链路断言"""
    return {"code": 0, "message": "ok", "data": {"total": len(_writebacks), "items": _writebacks}}


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "up", "orders": len(store.all()), "refunds": len(_refunds)}
