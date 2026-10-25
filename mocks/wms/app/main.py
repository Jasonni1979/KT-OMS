"""WMS 模拟器主服务（mock-wms）

用途（PLAN-DEV-01 V1.1 §3 M2 · W7）：M1-M3 全程在仿真环境开发，
不依赖通天晓/奇门真实环境到位。W7 打通「发货单 → 推仓 → 状态回放 → 出库回传 →
settle 转扣减 → 发货确认 → 平台回传」全链路。

对外接口：
- POST /wms/qimen/{method}      —— 奇门风格入口（deliveryorder.create / .cancel / .query）
- POST /wms/restful/outbound    —— 通天晓风格：出库指令下发
- POST /wms/restful/cancel      —— 通天晓风格：叫回指令
- POST /wms/restful/query       —— 通天晓风格：单据反查
- POST /wms/callback            —— WMS 主动回传（接收确认/出库回传/打回/叫回结果）
- POST /sim/inject              —— 预置错误注入（按指令单号，锻炼重试/终态路径）
- POST /sim/pick                —— 模拟拣货完成（触发叫回被拒）
- POST /sim/playback            —— 状态回放：一键推进指定发货单到目标状态
- GET  /sim/cmds                —— 查看指令池（调试）
- GET  /sim/callbacks           —— 查看回传事件（调试）
- POST /sim/reset               —— 清空
- GET  /healthz                 —— 存活探针

跑法：uvicorn app.main:app --port 9001（或 docker compose service mock-wms）
"""
from __future__ import annotations

import os
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.protocol import (
    APP_KEY,
    INJECTABLE_ERRORS,
    make_error_response,
    make_ok,
    verify_sign,
)
from app.store import Callback, WmsCmd, WmsStore, now_iso

SIGN_REQUIRED = os.getenv("MOCK_WMS_VERIFY_SIGN", "1") == "1"

app = FastAPI(title="KT-OMS WMS 模拟器", version="1.0.0")
store = WmsStore()


# ---------------- 签名与错误注入 ----------------

def _check_sign(request: Request, body: dict[str, Any]) -> dict[str, Any] | None:
    """签名校验 + 错误注入 → 返回错误响应或 None"""
    sign = request.headers.get("X-WMS-Sign") or body.get("sign")
    params = {**body, "sign": sign} if sign else body
    if SIGN_REQUIRED and not verify_sign(params):
        return make_error_response(
            "wms.invalid-signature", "签名验证失败（模拟器要求 sign 正确）", "FATAL"
        )
    # 错误注入（让通道层重试/终态逻辑在仿真期被真实锻炼）
    inject = body.get("_inject_error") or request.query_params.get("_inject_error")
    if inject:
        if inject not in INJECTABLE_ERRORS:
            return make_error_response(
                "wms.unknown-error", f"未支持的注入错误码: {inject}", "FATAL"
            )
        code, msg, cls = INJECTABLE_ERRORS[inject]
        if inject == "TIMEOUT":
            # 模拟网络超时：直接断开（客户端读超时）→ 通道层判 RETRYABLE
            time.sleep(float(os.getenv("MOCK_WMS_TIMEOUT_SEC", "3")))
        return make_error_response(code, msg, cls)
    return None


# ---------------- 奇门风格入口 ----------------

@app.post("/wms/qimen/{method}")
async def qimen_router(method: str, request: Request) -> JSONResponse:
    """奇门风格统一入口"""
    body = dict(await request.json())
    err = _check_sign(request, body)
    if err:
        return JSONResponse(err)

    if method == "deliveryorder.create":
        return JSONResponse(_delivery_create(body))
    if method == "deliveryorder.cancel":
        return JSONResponse(_delivery_cancel(body))
    if method == "deliveryorder.get":
        return JSONResponse(_delivery_query(body))
    return JSONResponse(
        make_error_response("wms.method-not-allowed", f"不支持的方法: {method}", "FATAL")
    )


# ---------------- RESTful 风格入口（通天晓）----------------

@app.post("/wms/restful/outbound")
async def restful_outbound(request: Request) -> JSONResponse:
    """出库指令下发"""
    body = dict(await request.json())
    err = _check_sign(request, body)
    if err:
        return JSONResponse(err)
    return JSONResponse(_delivery_create(body))


@app.post("/wms/restful/cancel")
async def restful_cancel(request: Request) -> JSONResponse:
    """叫回指令"""
    body = dict(await request.json())
    err = _check_sign(request, body)
    if err:
        return JSONResponse(err)
    return JSONResponse(_delivery_cancel(body))


@app.post("/wms/restful/query")
async def restful_query(request: Request) -> JSONResponse:
    """单据反查（回传超时兜底 + 对账）"""
    body = dict(await request.json())
    err = _check_sign(request, body)
    if err:
        return JSONResponse(err)
    return JSONResponse(_delivery_query(body))


# ---------------- 指令处理 ----------------

def _delivery_create(body: dict[str, Any]) -> dict[str, Any]:
    """出库指令受理（幂等：同 cmd_no 返回首次结果）"""
    cmd_no = str(body.get("cmd_no", "") or "")
    if not cmd_no:
        return make_error_response(
            "wms.invalid-payload", "缺少 cmd_no（OMS 侧下发单号）", "FATAL"
        )
    delivery_bn, push_round = WmsStore.parse_cmd_no(cmd_no)
    # 预置错误注入（模拟该指令下发时报错）
    inj = store.take_inject(cmd_no)
    if inj is not None:
        code, msg, cls = inj
        return make_error_response(code, msg, cls)
    exist = store.get_cmd(cmd_no)
    if exist is not None:
        # 幂等：重复下发返回首次受理结果（WMS 侧防重）
        return make_ok(
            {
                "cmd_no": cmd_no,
                "wms_bill_no": exist.wms_bill_no,
                "accepted": True,
                "duplicated": True,
            }
        )

    lines = body.get("lines") or []
    if not lines:
        return make_error_response(
            "wms.invalid-payload", "出库指令缺明细行", "FATAL"
        )
    cmd = WmsCmd(
        cmd_no=cmd_no,
        delivery_bn=delivery_bn,
        push_round=push_round,
        cmd_type="push",
        status="sent",
        wms_bill_no=store.next_bill_no(),
        warehouse_code=str(body.get("warehouse_code", "") or ""),
        owner_code=str(body.get("owner_code", "") or ""),
        lines=lines,
        waybill_no=str(body.get("waybill_no", "") or ""),
        print_ref=str(body.get("print_ref", "") or ""),
        payload=body,
        received_at=now_iso(),
    )
    store.add_cmd(cmd)
    return make_ok(
        {
            "cmd_no": cmd_no,
            "wms_bill_no": cmd.wms_bill_no,
            "accepted": True,
            "duplicated": False,
        }
    )


def _delivery_cancel(body: dict[str, Any]) -> dict[str, Any]:
    """叫回指令受理（已开始拣货 → 拒绝）"""
    cmd_no = str(body.get("cmd_no", "") or "")
    inj = store.take_inject(cmd_no)
    if inj is not None:
        code, msg, cls = inj
        return make_error_response(code, msg, cls)
    cmd = store.get_cmd(cmd_no)
    if cmd is None:
        return make_error_response(
            "wms.order-not-exist", f"指令不存在: {cmd_no}", "FATAL"
        )
    if cmd.cmd_no in store.recall_reject or cmd.cmd_no in store.picked:
        return make_error_response(
            "wms.recall-rejected", "已开始拣货，无法拦截", "RETRYABLE"
        )
    cmd.status = "cancelled"
    return make_ok({"cmd_no": cmd_no, "accepted": True, "cancelled": True})


def _delivery_query(body: dict[str, Any]) -> dict[str, Any]:
    """单据反查（回传超时兜底）"""
    cmd_no = str(body.get("cmd_no", "") or "")
    cmd = store.get_cmd(cmd_no)
    if cmd is None:
        return make_ok({"cmd_no": cmd_no, "found": False})
    return make_ok({"cmd_no": cmd_no, "found": True, "cmd": cmd.to_dict()})


# ---------------- WMS 主动回传 ----------------

class CallbackReq(BaseModel):
    cb_type: str = Field(description="accepted/outbound/rejected/cancelled/recall_failed")
    cmd_no: str = Field(default="", description="OMS 下发单号")
    batch_no: str = Field(default="", description="WMS 回传批次号")
    lines: list[dict[str, Any]] = Field(default_factory=list)
    packages: list[dict[str, Any]] = Field(default_factory=list)
    weight: float = 0.0
    volume: float = 0.0
    waybill_no: str = Field(default="")
    reject_reason: str = Field(default="")
    reject_reason_code: str = Field(default="")


@app.post("/wms/callback")
async def wms_callback(body: CallbackReq) -> dict[str, Any]:
    """WMS 主动回传（接收确认/出库回传/打回/叫回结果）

    幂等：delivery_bn + batch_no + cb_type 唯一，重复投递直接应答成功。
    """
    cmd = store.get_cmd(body.cmd_no)
    delivery_bn = cmd.delivery_bn if cmd else WmsStore.parse_cmd_no(body.cmd_no)[0]
    cb = Callback(
        cb_type=body.cb_type,
        delivery_bn=delivery_bn,
        batch_no=body.batch_no or body.cb_type,
        wms_bill_no=cmd.wms_bill_no if cmd else "",
        lines=body.lines,
        packages=body.packages,
        weight=body.weight,
        volume=body.volume,
        waybill_no=body.waybill_no or (cmd.waybill_no if cmd else ""),
        reject_reason=body.reject_reason,
        reject_reason_code=body.reject_reason_code,
        received_at=now_iso(),
    )
    existed = any(
        c.delivery_bn == cb.delivery_bn
        and c.batch_no == cb.batch_no
        and c.cb_type == cb.cb_type
        for c in store.callbacks
    )
    store.add_callback(cb)
    # 指令状态联动
    if cmd is not None:
        if body.cb_type == "accepted":
            cmd.status = "working"
        elif body.cb_type == "outbound":
            cmd.status = "partial" if len(cmd.callbacks) < 2 else "completed"
            cmd.callbacks.append(cb.batch_no)
        elif body.cb_type in ("rejected", "cancelled"):
            cmd.status = "rejected" if body.cb_type == "rejected" else "cancelled"
    return make_ok(
        {
            "cmd_no": body.cmd_no,
            "delivery_bn": delivery_bn,
            "batch_no": cb.batch_no,
            "duplicated": existed,
            "acked": True,
        }
    )


# ---------------- 状态回放（仿真核心）----------------

class PickReq(BaseModel):
    cmd_no: str
    batch_no: str = Field(default="B1")


@app.post("/sim/pick")
async def sim_pick(body: PickReq) -> dict[str, Any]:
    """模拟拣货完成 → 该指令后续叫回会被拒"""
    cmd = store.get_cmd(body.cmd_no)
    if cmd is None:
        return make_error_response("wms.order-not-exist", "指令不存在", "FATAL")
    store.picked.add(body.cmd_no)
    cmd.status = "working"
    return make_ok({"cmd_no": body.cmd_no, "picked": True})


class PlaybackReq(BaseModel):
    cmd_no: str
    #: 推进目标：accepted / outbound / partial / rejected / recall_success / recall_failed
    action: str = Field(default="outbound")
    batch_no: str = Field(default="B1")
    #: 覆盖实发数量（制造少发/多发差异）
    actual_num: dict[str, int] = Field(default_factory=dict)
    weight: float = 1.5
    volume: float = 0.01
    waybill_no: str = Field(default="SF999888777")
    reject_reason: str = Field(default="仓库缺货")
    reject_reason_code: str = Field(default="LACK_STOCK")


class InjectReq(BaseModel):
    """错误注入请求"""

    cmd_no: str = Field(default="", description="指令单号（{发货单号}-R{轮次}）")
    error: str = Field(default="TIMEOUT", description="INJECTABLE_ERRORS 键")
    times: int = Field(default=1, ge=0, le=100, description="生效次数（0=永久）")


@app.post("/sim/inject")
async def sim_inject(body: InjectReq) -> dict[str, Any]:
    """预置错误注入：命中该指令单号的下发请求时返回指定错误

    用于在仿真期真实锻炼 D09.02 的「分级重试（RETRYABLE 退避）/ 终态（FATAL）」
    与 D02.05 的 api_fail 分级路径——无需真实 WMS 故障。
    """
    if not body.cmd_no:
        return make_error_response(
            "wms.invalid-payload", "cmd_no 必填", "FATAL"
        )
    if body.error not in INJECTABLE_ERRORS:
        return make_error_response(
            "wms.unknown-error", f"未支持的注入错误码: {body.error}", "FATAL"
        )
    code, msg, cls = INJECTABLE_ERRORS[body.error]
    store.inject(body.cmd_no, code, msg, cls, body.times)
    return make_ok(
        {
            "cmd_no": body.cmd_no,
            "injected": body.error,
            "err_code": code,
            "err_class": cls,
            "times": body.times,
        }
    )


@app.post("/sim/playback")
async def sim_playback(body: PlaybackReq) -> dict[str, Any]:
    """状态回放：一键把指令推进到目标状态（自动产生回传事件）

    动作语义：
    - accepted      → 接收确认回传（作业开始）
    - outbound      → 一次性出库回传（全量实发）
    - partial       → 只回传第一行（驱动 partial_outbound）
    - rejected      → 打回回传（缺货/拒单）
    - recall_success→ 叫回成功回传
    - recall_failed → 叫回失败回传（已开始拣货）
    """
    cmd = store.get_cmd(body.cmd_no)
    if cmd is None:
        return make_error_response("wms.order-not-exist", "指令不存在", "FATAL")

    if body.action == "accepted":
        cb = Callback(
            cb_type="accepted",
            delivery_bn=cmd.delivery_bn,
            batch_no=body.batch_no,
            wms_bill_no=cmd.wms_bill_no,
            received_at=now_iso(),
        )
        store.add_callback(cb)
        cmd.status = "working"
        return make_ok({"cmd_no": body.cmd_no, "cb_type": "accepted"})

    if body.action in ("rejected", "recall_success", "recall_failed"):
        cb_type = {
            "rejected": "rejected",
            "recall_success": "cancelled",
            "recall_failed": "recall_failed",
        }[body.action]
        cb = Callback(
            cb_type=cb_type,
            delivery_bn=cmd.delivery_bn,
            batch_no=body.batch_no or cb_type,
            wms_bill_no=cmd.wms_bill_no,
            reject_reason=body.reject_reason if cb_type == "rejected" else "",
            reject_reason_code=(
                body.reject_reason_code if cb_type == "rejected" else ""
            ),
            received_at=now_iso(),
        )
        store.add_callback(cb)
        if cb_type == "rejected":
            cmd.status = "rejected"
        elif cb_type == "cancelled":
            cmd.status = "cancelled"
        else:
            cmd.status = "working"  # 叫回失败 → 保持作业中
        return make_ok({"cmd_no": body.cmd_no, "cb_type": cb_type})

    # outbound / partial → 构造出库回传
    lines: list[dict[str, Any]] = []
    src = cmd.lines[:1] if body.action == "partial" else cmd.lines
    for ln in src:
        bm = str(ln.get("sku_code", "") or ln.get("bm_code", "") or "")
        num = int(ln.get("num", 0) or 0)
        if bm in body.actual_num:
            num = int(body.actual_num[bm])
        lines.append(
            {
                "sku_code": bm,
                "num": num,
                "waybill_no": body.waybill_no,
            }
        )
    packages = [
        {
            "package_no": f"PKG{body.batch_no}",
            "waybill_no": body.waybill_no,
            "weight": body.weight,
            "volume": body.volume,
            "items": lines,
        }
    ]
    cb = Callback(
        cb_type="outbound",
        delivery_bn=cmd.delivery_bn,
        batch_no=body.batch_no,
        wms_bill_no=cmd.wms_bill_no,
        lines=lines,
        packages=packages,
        weight=body.weight,
        volume=body.volume,
        waybill_no=body.waybill_no,
        received_at=now_iso(),
    )
    existed = any(
        c.delivery_bn == cb.delivery_bn
        and c.batch_no == cb.batch_no
        and c.cb_type == "outbound"
        for c in store.callbacks
    )
    store.add_callback(cb)
    cmd.callbacks.append(cb.batch_no)
    cmd.status = "partial" if body.action == "partial" else "completed"
    return make_ok(
        {
            "cmd_no": body.cmd_no,
            "cb_type": "outbound",
            "batch_no": cb.batch_no,
            "duplicated": existed,
        }
    )


# ---------------- 调试接口 ----------------

@app.get("/sim/cmds")
async def list_cmds() -> dict[str, Any]:
    """查看指令池"""
    items = [c.to_dict() for c in store.all_cmds()]
    return make_ok({"total": len(items), "items": items})


@app.get("/sim/callbacks")
async def list_callbacks() -> dict[str, Any]:
    """查看回传事件"""
    items = [c.to_dict() for c in store.all_callbacks()]
    return make_ok({"total": len(items), "items": items})


@app.post("/sim/reset")
async def reset() -> dict[str, Any]:
    n = store.clear()
    return make_ok({"cleared": n})


@app.get("/healthz")
async def healthz() -> dict[str, Any]:
    return {
        "status": "up",
        "cmds": len(store.cmds),
        "callbacks": len(store.callbacks),
        "app_key": APP_KEY,
    }
