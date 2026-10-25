"""平台回传中心（D02.04）+ 失败重试（D02.05 登记侧）

**定位**：消费 `order.delivery.shipped` 事件 → 组装 canonical 发货指令 →
适配器翻译平台原生调用 → 回传台账记结果。失败按**统一错误分级**登记 api_fail，
由 D02.05 的重试调度消费。

**回传时机（back_node）**：
| back_node | 触发事件 | 说明 |
|---|---|---|
| `shipped`（默认） | order.delivery.shipped | 发货确认后回传 |
| `print` | delivery.printed | 打印面单即回传（大促抢时效） |
| `verify` | delivery.verified | 校验完成回传 |

同一发货单**只回传一次**（台账幂等键 = 发货单 + 动作），时机切换不产生重复回传。

**错误分级（D02.01 FR-06c 统一字典）**：
RETRYABLE（网络/超时/系统错误）/ RATE_LIMITED（限流，退避）/ AUTH（凭证失效）/
MANUAL（业务错误需人工）/ FATAL（永久失败，不重试）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.order import OrdOrder, OrdOrderItem, OrdReceiver

logger = get_logger("writeback")

#: 回传类型
SYNC_DELIVERY = "delivery"       # 发货回传
SYNC_STOCK = "stock"             # 库存回写

#: 平台动作
#: 平台动作（统一方法名 → 适配器映射为平台原生名）
ACTION_DELIVERY_SEND = "taobao.logistics.online.send"

#: 回传时机
BACK_NODE_SHIPPED = "shipped"
BACK_NODE_PRINT = "print"
BACK_NODE_VERIFY = "verify"

#: 台账状态
WB_PENDING = "pending"
WB_RUNNING = "running"
WB_SUCC = "succ"
WB_FAIL = "fail"
WB_SKIP = "skip"

#: 统一错误分级（D02.01 FR-06c）
LEVEL_RETRYABLE = "RETRYABLE"
LEVEL_RATE_LIMITED = "RATE_LIMITED"
LEVEL_AUTH = "AUTH"
LEVEL_MANUAL = "MANUAL"
LEVEL_FATAL = "FATAL"

#: 退避序列（分钟，D02.05 同款）
BACKOFF_MINUTES = (1, 5, 15, 60)
MAX_RETRY = 10

#: 平台错误码 → 分级
PLATFORM_ERR_LEVEL: dict[str, str] = {
    "isv.invalid-signature": LEVEL_FATAL,
    "isv.invalid-session-key": LEVEL_AUTH,
    "isv.session-expired": LEVEL_AUTH,
    "isv.trade-not-exist": LEVEL_MANUAL,
    "isv.trade-service-error": LEVEL_RETRYABLE,
    "flow-limit": LEVEL_RATE_LIMITED,
    "isv.permission-api-call-limit": LEVEL_MANUAL,
    "isv.item-not-exist": LEVEL_MANUAL,
}


@dataclass
class WritebackResult:
    """回传结果"""

    ok: bool
    task_id: int = 0
    status: str = ""
    err_code: str = ""
    err_level: str = ""
    err_msg: str = ""
    #: 是否跳过（已回传过 / 时机未到 / 无主）
    skipped: bool = False
    skip_reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "task_id": self.task_id,
            "status": self.status,
            "err_code": self.err_code,
            "err_level": self.err_level,
            "err_msg": self.err_msg,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "detail": self.detail,
        }


class WritebackService:
    """回传中心（D02.04）"""

    def __init__(self, session: AsyncSession, redis: Redis):
        self.s = session
        self.r = redis

    # ==================== 发货回传（SC-01）====================

    async def send_delivery(
        self, delivery_id: int, back_node: str = BACK_NODE_SHIPPED
    ) -> WritebackResult:
        """发货回传（IF-D02.04-01）

        幂等：台账幂等键 = 发货单 + 动作；已 succ → 跳过（时机切换不重复回传）。
        """
        delivery_row = await self.s.execute(
            text(
                "SELECT id, delivery_bn, order_id, branch_id, owner_id, shop_id, "
                "       logi_id, logi_no, source, status "
                "FROM oms_order.ord_delivery WHERE id = :id AND is_deleted = 0"
            ),
            {"id": delivery_id},
        )
        delivery = delivery_row.mappings().first()
        if not delivery:
            return WritebackResult(
                ok=False, err_code="DELIVERY_NOT_FOUND", err_level=LEVEL_MANUAL
            )
        d = delivery
        order_id = int(d["order_id"] or 0)
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id, OrdOrder.is_deleted == 0)
        )
        if not order:
            return WritebackResult(
                ok=False, err_code="ORDER_NOT_FOUND", err_level=LEVEL_MANUAL
            )

        # 幂等：同一发货单同一动作只回传一次
        idem_key = f"delivery:{delivery_id}:{ACTION_DELIVERY_SEND}"
        exist_row = await self.s.execute(
            text(
                "SELECT id, status FROM oms_gateway.gw_writeback_task "
                "WHERE idempotent_key = :k LIMIT 1"
            ),
            {"k": idem_key},
        )
        exist = exist_row.mappings().first()
        if exist is not None:
            return WritebackResult(
                ok=True,
                task_id=int(exist["id"]),
                status=str(exist["status"]),
                skipped=True,
                skip_reason="已回传过（幂等）",
            )

        # 组装 canonical 发货指令（SC-01）
        items = list(
            await self.s.scalars(
                select(OrdOrderItem).where(
                    OrdOrderItem.order_id == order_id,
                    OrdOrderItem.is_deleted == 0,
                )
            )
        )
        receiver = await self.s.scalar(
            select(OrdReceiver).where(OrdReceiver.order_id == order_id).limit(1)
        )
        dto = {
            "tid": order.platform_order_bn or order.order_bn,
            "oid": "",
            "shop_id": int(d["shop_id"] or 0),
            "logistics_company": str(d["logi_id"] or ""),
            "logistics_no": str(d["logi_no"] or ""),
            "ship_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "lines": [
                {
                    "oid": "",
                    "item_id": str(i.bm_number or i.id),
                    "num": int(i.nums or 0),
                }
                for i in items
            ],
            "receiver": {
                "name": receiver.name_hash if receiver else "",
                "mobile": receiver.mobile_hash if receiver else "",
                "province": receiver.province if receiver else "",
                "city": receiver.city if receiver else "",
                "district": receiver.district if receiver else "",
                "address": receiver.address_hash if receiver else "",
            },
        }

        # 台账登记（pending）
        await self.s.execute(
            text(
                "INSERT INTO oms_gateway.gw_writeback_task "
                "(tenant_id, owner_id, sync_type, biz_ref, platform, shop_id, action, "
                " payload_snapshot, trigger_event_id, back_node, status, retry_count, "
                " idempotent_key, create_time, update_time, version) "
                "VALUES (1, :owner, :stype, :ref, :plat, :shop, :act, :payload, "
                " 'order.delivery.shipped', :bnode, 'pending', 0, :idem, NOW(3), NOW(3), 0)"
            ),
            {
                "owner": d["owner_id"],
                "stype": SYNC_DELIVERY,
                "ref": str(d["delivery_bn"]),
                "plat": await self._shop_platform(int(d["shop_id"] or 0)),
                "shop": int(d["shop_id"] or 0),
                "act": ACTION_DELIVERY_SEND,
                "payload": json.dumps(dto, ensure_ascii=False, default=str),
                "bnode": back_node,
                "idem": idem_key,
            },
        )
        await self.s.commit()
        task_id = int(
            await self.s.scalar(
                text(
                    "SELECT id FROM oms_gateway.gw_writeback_task "
                    "WHERE idempotent_key = :k LIMIT 1"
                ),
                {"k": idem_key},
            )
            or 0
        )

        # 执行回传
        return await self._execute(task_id, dto, int(d["shop_id"] or 0))

    async def _shop_platform(self, shop_id: int) -> str:
        """取店铺平台（订单表无 platform 列，平台归属店铺档案）"""
        if not shop_id:
            return "taobao"
        plat = await self.s.scalar(
            text(
                "SELECT platform FROM oms_gateway.gw_shop WHERE id = :sid AND is_deleted = 0"
            ),
            {"sid": shop_id},
        )
        return str(plat or "taobao")

    async def _execute(
        self, task_id: int, dto: dict[str, Any], shop_id: int
    ) -> WritebackResult:
        """执行平台调用（走 D02.02 适配器）"""
        from app.adapters.taobao import TaobaoAdapter

        adapter = TaobaoAdapter()
        await self.s.execute(
            text(
                "UPDATE oms_gateway.gw_writeback_task SET status = 'running' WHERE id = :id"
            ),
            {"id": task_id},
        )
        await self.s.commit()
        res = await adapter.call(
            ACTION_DELIVERY_SEND, dto, shop_id=shop_id, primary_bn=str(dto.get("tid", ""))
        )
        if res.succ:
            await self.s.execute(
                text(
                    "UPDATE oms_gateway.gw_writeback_task "
                    "SET status = 'succ', platform_msg_id = :mid, platform_receipt = :rcpt, "
                    "    err_code = NULL, err_level = NULL "
                    "WHERE id = :id"
                ),
                {
                    "mid": res.msg_id,
                    "rcpt": json.dumps(res.raw, ensure_ascii=False, default=str)[:512],
                    "id": task_id,
                },
            )
            await self.s.commit()
            return WritebackResult(
                ok=True, task_id=task_id, status=WB_SUCC, detail={"msg_id": res.msg_id}
            )
        # 失败：按分级登记（成功回传后由 D02.05 重试）
        level = self._classify(res.err_code)
        return await self._mark_fail(task_id, res.err_code, level, res.err_msg)

    async def _mark_fail(
        self, task_id: int, err_code: str, level: str, err_msg: str
    ) -> WritebackResult:
        """失败登记（D02.05 消费侧）"""
        retryable = level in (LEVEL_RETRYABLE, LEVEL_RATE_LIMITED)
        retry_count = 0
        nxt: datetime | None = None
        if retryable:
            r = await self.s.scalar(
                text(
                    "SELECT retry_count FROM oms_gateway.gw_writeback_task WHERE id = :id"
                ),
                {"id": task_id},
            )
            retry_count = int(r or 0) + 1
            if retry_count >= MAX_RETRY:
                level = LEVEL_FATAL  # 超限进死信
            else:
                nxt = datetime.now() + timedelta(
                    minutes=BACKOFF_MINUTES[
                        min(retry_count - 1, len(BACKOFF_MINUTES) - 1)
                    ]
                )
        await self.s.execute(
            text(
                "UPDATE oms_gateway.gw_writeback_task "
                "SET status = 'fail', err_code = :code, err_level = :lvl, "
                "    retry_count = :rc, platform_receipt = :msg "
                "WHERE id = :id"
            ),
            {
                "code": err_code[:64],
                "lvl": level,
                "rc": retry_count,
                "msg": (err_msg or "")[:512],
                "id": task_id,
            },
        )
        await self.s.commit()
        if retryable and nxt:
            await self._register_api_fail(task_id, err_code, level, err_msg, retry_count, nxt)
        return WritebackResult(
            ok=False,
            task_id=task_id,
            status=WB_FAIL,
            err_code=err_code,
            err_level=level,
            err_msg=err_msg,
        )

    async def _register_api_fail(
        self,
        task_id: int,
        err_code: str,
        level: str,
        err_msg: str,
        retry_count: int,
        next_retry: datetime,
    ) -> None:
        """失败登记到 api_fail（D02.05 重试调度消费）"""
        await self.s.execute(
            text(
                "INSERT INTO oms_gateway.gw_api_fail "
                "(tenant_id, obj_type, primary_bn, sub_bn, method, native_method, "
                " platform, shop_id, replay_ref, err_code, err_msg, err_level, "
                " write_flag, fail_times, next_retry_time, is_dead, status, "
                " writeback_task_id, create_time, update_time, version) "
                "VALUES (1, 'writeback', :ref, NULL, :method, :method, 'taobao', 0, "
                " NULL, :code, :msg, :lvl, 0, :ft, :nxt, 0, 'waiting', :task, "
                " NOW(3), NOW(3), 0)"
            ),
            {
                "method": ACTION_DELIVERY_SEND,
                "ref": f"writeback:{task_id}"[:64],
                "code": err_code[:64],
                "msg": (err_msg or "")[:512],
                "lvl": level,
                "ft": retry_count,
                "nxt": next_retry,
                "task": task_id,
            },
        )
        await self.s.commit()

    @staticmethod
    def _classify(err_code: str) -> str:
        """错误分级（D02.01 FR-06c 统一字典）"""
        return PLATFORM_ERR_LEVEL.get(err_code, LEVEL_RETRYABLE)

    # ==================== 消费发货事件（SC-01 入口）====================

    async def on_order_shipped(self, payload: dict[str, Any]) -> WritebackResult:
        """消费 `order.delivery.shipped` 事件"""
        delivery_id = int(payload.get("delivery_id") or 0)
        if not delivery_id:
            return WritebackResult(
                ok=False, err_code="NO_DELIVERY", err_level=LEVEL_MANUAL
            )
        return await self.send_delivery(delivery_id, BACK_NODE_SHIPPED)

    # ==================== 重试消费（D02.05 侧）====================

    async def retry_pending(self, limit: int = 50) -> list[WritebackResult]:
        """消费 api_fail 重试队列（D02.05 调度入口）"""
        rows = await self.s.execute(
            text(
                "SELECT f.id, f.writeback_task_id, f.err_code, f.err_level, f.err_msg, "
                "       f.fail_times "
                "FROM oms_gateway.gw_api_fail f "
                "WHERE f.status = 'waiting' AND f.next_retry_time <= NOW(3) "
                "AND f.writeback_task_id IS NOT NULL "
                "ORDER BY f.next_retry_time LIMIT :lim"
            ),
            {"lim": limit},
        )
        out: list[WritebackResult] = []
        for fid, task_id, _ec, _el, _em, _ft in rows.all():
            row = await self.s.execute(
                text(
                    "SELECT payload_snapshot, shop_id FROM oms_gateway.gw_writeback_task "
                    "WHERE id = :id"
                ),
                {"id": int(task_id)},
            )
            r = row.mappings().first()
            if not r:
                await self.s.execute(
                    text(
                        "UPDATE oms_gateway.gw_api_fail SET status = 'resolved' "
                        "WHERE id = :id"
                    ),
                    {"id": int(fid)},
                )
                continue
            dto = json.loads(r["payload_snapshot"] or "{}")
            res = await self._execute(int(task_id), dto, int(r["shop_id"] or 0))
            await self.s.execute(
                text(
                    "UPDATE oms_gateway.gw_api_fail SET status = :st, "
                    "       fail_times = fail_times + 1, last_retry_time = NOW(3) "
                    "WHERE id = :id"
                ),
                {"st": "succ" if res.ok else "waiting", "id": int(fid)},
            )
            out.append(res)
        await self.s.commit()
        return out

    # ==================== 台账查询 ====================

    async def list_tasks(
        self, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """回传台账查询（工作台）"""
        q = "FROM oms_gateway.gw_writeback_task WHERE 1=1"
        params: dict[str, Any] = {"lim": limit}
        if status:
            q += " AND status = :st"
            params["st"] = status
        rows = await self.s.execute(
            text(
                "SELECT id, sync_type, biz_ref, platform, shop_id, action, status, "
                "       err_code, err_level, retry_count, back_node, create_time "
                f" {q} ORDER BY id DESC LIMIT :lim"
            ),
            params,
        )
        return [
            {
                "id": r[0],
                "sync_type": r[1],
                "biz_ref": r[2],
                "platform": r[3],
                "shop_id": r[4],
                "action": r[5],
                "status": r[6],
                "err_code": r[7],
                "err_level": r[8],
                "retry_count": r[9],
                "back_node": r[10],
                "create_time": r[11].isoformat() if r[11] else "",
            }
            for r in rows.all()
        ]
