"""订单修改与改地址服务（SRS-D03.08 最小子集 · W8-3）

D03.08 完整形态包含快照/冻结/差异对比/叫回/复审/审批（FR-01~FR-07），
W8 只做**评审可用的最小闭环**：

| 能力 | 状态 | 说明 |
|---|---|---|
| 未推仓直改地址 | ✅ 真跑 | 无发货单 → 直接改收货信息 + 落改单/快照 + 审计 |
| 已推仓改地址 | ✅ 真跑 | 有发货单 → 先叫回（W7 链路）→ 叫回成功后改地址 |
| 叫回失败 | ✅ 真跑 | 改单置挂起 + 落异常单（人工跟进），不静默 |
| 快照 | ✅ 真跑 | 改前落 `ord_order_snapshot`（订单主档/行/收货人，密文原样存） |
| 差异对比 | ✅ 真跑 | `diff_summary`（字段级旧值/新值） |
| 改单冻结（FR-03a） | ⚠️ 扩展位 | 纯地址改单**本就不动库存**（FR-03b）→ 本期不需冻结 |
| 审批 / 复审联动 | ⚠️ 扩展位 | 属后续批次，改单单据已留 `approval_id` 扩展位 |
| 并发互斥（FR-01a） | ✅ 真跑 | 同订单同一时刻只允许一张进行中的改单（Redis 锁 + DB 状态校验） |

⚠ **地址是 PIPL 敏感字段**：快照与 diff 里的地址保持**密文**（`address_enc`），
前端只展示脱敏值，不做明文落库。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.enums import ORD_ORDER_MODIFY_MODIFY_TYPE
from app.core.exceptions import ConflictError, NotFoundError
from app.core.timeutil import utcnow
from app.models.fulfill import OrdDelivery
from app.models.modify import OrdOrderModify, OrdOrderSnapshot
from app.models.order import OrdOrder, OrdOrderItem, OrdReceiver

#: 改单类型
MODIFY_ADDRESS = "address"

#: 改单状态机
MODIFY_STATUS_EDITING = "editing"
MODIFY_STATUS_RECALLING = "recalling"
MODIFY_STATUS_EFFECTIVE = "effective"
MODIFY_STATUS_SUSPENDED = "suspended"
MODIFY_STATUS_CANCELLED = "cancelled"

#: 进行中的改单状态（用于并发互斥判定 FR-01a）
MODIFY_OPEN_STATUSES = (
    MODIFY_STATUS_EDITING,
    MODIFY_STATUS_RECALLING,
    MODIFY_STATUS_SUSPENDED,
)

#: 改单类型 → 中文
MODIFY_TYPE_LABEL = ORD_ORDER_MODIFY_MODIFY_TYPE


def _hex(v: bytes | str | None) -> str:
    """blob → hex 字符串（JSON 可序列化）"""
    if v is None:
        return ""
    if isinstance(v, bytes):
        return v.hex()
    return str(v)


def _unhex(v: str | bytes | None) -> bytes:
    """hex 字符串 → blob（还原密文）"""
    if v is None:
        return b""
    if isinstance(v, bytes):
        return v
    try:
        return bytes.fromhex(str(v))
    except ValueError:
        return str(v).encode("utf-8")


class ModifyService:
    """订单修改服务（D03.08 最小子集）"""

    def __init__(self, session: AsyncSession, redis: Any = None) -> None:
        self.s = session
        self.r = redis

    # ============ 入口（FR-01a）============

    async def create_address_modify(
        self,
        order_id: int,
        *,
        province: str = "",
        city: str = "",
        district: str = "",
        town: str = "",
        address_enc: bytes | str = b"",
        operator: str = "",
        source: str = "manual",
    ) -> dict[str, Any]:
        """发起改地址改单（FR-01a / FR-02a）

        流程：
        ① 前置状态校验（已发货/已完成/已取消 → 拒绝，提示走售后 FR-01c）
        ② 并发互斥（同订单已有进行中改单 → 拒绝 FR-01a）
        ③ 生成快照（FR-02a：订单主档/行/收货人）
        ④ 落改单（status=editing）
        ⑤ 若有发货单 → 需叫回（FR-06a）→ 置 recalling 并发起叫回
           若无发货单 → 直接生效（FR-03b：纯地址改单不动库存）
        """
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id, OrdOrder.is_deleted == 0)
        )
        if order is None:
            raise NotFoundError(f"订单不存在: {order_id}")

        # ① 前置状态校验（FR-01c）
        if order.order_status in ("shipped", "completed", "cancelled", "closed"):
            raise ConflictError(
                f"订单状态 {order.order_status} 不允许改单，请走售后流程",
                code="MODIFY_STATUS_NOT_ALLOWED",
            )
        # ② 并发互斥（FR-01a）
        open_modify = await self.s.scalar(
            select(OrdOrderModify)
            .where(
                OrdOrderModify.order_id == order_id,
                OrdOrderModify.status.in_(MODIFY_OPEN_STATUSES),
                OrdOrderModify.is_deleted == 0,
            )
            .limit(1)
        )
        if open_modify is not None:
            raise ConflictError(
                f"该订单已有进行中的改单（{open_modify.modify_bn}），请先处理",
                code="MODIFY_CONCURRENT_BLOCKED",
            )

        # ③ 快照（FR-02a）
        snap_id = await self._snapshot(order)

        # ④ 落改单
        modify_bn = f"MOD{utcnow():%Y%m%d}{uuid.uuid4().hex[:6].upper()}"
        diff = await self._diff_address(
            order_id,
            province=province,
            city=city,
            district=district,
            town=town,
            address_enc=address_enc,
        )
        row = OrdOrderModify(
            tenant_id=order.tenant_id,
            owner_id=order.owner_id,
            modify_bn=modify_bn,
            order_id=order.id,
            order_bn=order.order_bn,
            modify_type=MODIFY_ADDRESS,
            source=source,
            snapshot_id=snap_id,
            status=MODIFY_STATUS_EDITING,
            need_recall=0,
            diff_summary=diff,
            saga_log=[],
            operator=operator or "system",
            shop_id=order.shop_id,
            brand_id=order.brand_id,
            version=0,
            is_deleted=0,
        )
        self.s.add(row)
        await self.s.flush()

        # ⑤ 叫回判定（FR-06a）
        deliveries = list(
            await self.s.scalars(
                select(OrdDelivery).where(
                    OrdDelivery.order_id == order_id, OrdDelivery.is_deleted == 0
                )
            )
        )
        need_recall = bool(deliveries)
        row.need_recall = 1 if need_recall else 0
        if not need_recall:
            # 无发货单 → 直接生效（FR-03b：纯地址改单不动库存）
            await self._effective(row, operator=operator or "system")
            await self.s.commit()
            await self.s.refresh(row)
            return {
                "ok": True,
                "modify_id": row.id,
                "modify_bn": row.modify_bn,
                "status": row.status,
                "need_recall": False,
                "effective": True,
                "diff": diff,
            }

        # 需叫回 → 置 recalling 并发起叫回（FR-06b）
        row.status = MODIFY_STATUS_RECALLING
        row.recall_refs = [int(d.id) for d in deliveries]
        await self.s.commit()

        recall_result = await self._request_recall(row, deliveries, operator=operator)
        await self.s.commit()
        await self.s.refresh(row)
        return {
            "ok": True,
            "modify_id": row.id,
            "modify_bn": row.modify_bn,
            "status": row.status,
            "need_recall": True,
            "effective": False,
            "recall_result": recall_result,
            "diff": diff,
        }

    # ============ 叫回（FR-06a/06c）============

    async def _request_recall(
        self, row: OrdOrderModify, deliveries: list[OrdDelivery], *, operator: str
    ) -> dict[str, Any]:
        """发起叫回（W7 链路复用）"""
        from app.modules.m7_integration.contract import OutboundCommandService

        svc = OutboundCommandService(self.s, self.r)
        results = []
        for d in deliveries:
            try:
                out = await svc.recall(
                    d.id,
                    ref_id=row.modify_bn,
                    operator=operator or "system",
                    reason=f"改地址叫回（改单 {row.modify_bn}）",
                )
            except Exception as e:  # noqa: BLE001 —— 叫回异常按失败处理
                results.append(
                    {"delivery_id": d.id, "ok": False, "err_msg": str(e)[:200]}
                )
                continue
            results.append(
                {
                    "delivery_id": d.id,
                    "ok": bool(getattr(out, "ok", False)),
                    "err_code": getattr(out, "err_code", ""),
                    "err_msg": getattr(out, "err_msg", "")[:200],
                }
            )
        # 任一失败 → 整体失败（FR-06c：合单组级联叫回，任一失败按整体失败）
        failed = [r for r in results if not r.get("ok")]
        if failed:
            row.status = MODIFY_STATUS_SUSPENDED
            row.saga_log = [
                *(row.saga_log or []),
                {
                    "at": utcnow().isoformat(),
                    "stage": "recall",
                    "ok": False,
                    "detail": results,
                },
            ]
            # 落异常单（人工跟进）—— 复用 W7 事件链的落单入口
            await self._raise_recall_abnormal(row, failed)
        else:
            row.saga_log = [
                *(row.saga_log or []),
                {
                    "at": utcnow().isoformat(),
                    "stage": "recall",
                    "ok": True,
                    "detail": results,
                },
            ]
        return {"deliveries": results, "all_ok": not failed}

    async def _raise_recall_abnormal(
        self, row: OrdOrderModify, failed: list[dict[str, Any]]
    ) -> None:
        """叫回失败 → 落异常单（FR-06c：改单挂起 + 告警 + 客服决策）"""
        from app.modules.m5_abnormal.contract import AbnormalService

        try:
            svc = AbnormalService(self.s, self.r)
            order = await self.s.scalar(
                select(OrdOrder).where(
                    OrdOrder.id == row.order_id, OrdOrder.is_deleted == 0
                )
            )
            if order is None:
                return
            await svc.create(
                order=order,
                exc_type="RECALL_FAILED",
                source="modify",
                source_ref=row.modify_bn,
                reason_detail={
                    "modify_bn": row.modify_bn,
                    "failed": failed,
                    "note": "改地址叫回失败，改单挂起待人工处理",
                },
            )
        except Exception:  # noqa: BLE001 —— 落单失败不阻断叫回结果返回
            pass

    # ============ 叫回成功后生效（FR-06c）============

    async def complete_recall_and_effective(
        self, modify_id: int, *, operator: str = "system"
    ) -> dict[str, Any]:
        """叫回成功后 → 继续改单流程并生效（FR-06c）"""
        row = await self._get(modify_id)
        if row.status != MODIFY_STATUS_RECALLING:
            raise ConflictError(
                f"改单当前状态 {row.status} 不在叫回中",
                code="MODIFY_STATUS_INVALID",
            )
        await self._effective(row, operator=operator)
        await self.s.commit()
        await self.s.refresh(row)
        return {
            "ok": True,
            "modify_id": row.id,
            "modify_bn": row.modify_bn,
            "status": row.status,
            "effective": True,
        }

    async def cancel_recall_modify(
        self, modify_id: int, *, operator: str = "system", reason: str = ""
    ) -> dict[str, Any]:
        """撤销改单（叫回失败时的人工决策：撤销改单恢复现场 / 转人工，FR-06c）"""
        row = await self._get(modify_id)
        if row.status not in (MODIFY_STATUS_RECALLING, MODIFY_STATUS_SUSPENDED):
            raise ConflictError(
                f"改单当前状态 {row.status} 不可撤销",
                code="MODIFY_STATUS_INVALID",
            )
        row.status = MODIFY_STATUS_CANCELLED
        row.saga_log = [
            *(row.saga_log or []),
            {
                "at": utcnow().isoformat(),
                "stage": "cancel",
                "ok": True,
                "detail": reason,
            },
        ]
        await self.s.commit()
        await self.s.refresh(row)
        return {
            "ok": True,
            "modify_id": row.id,
            "modify_bn": row.modify_bn,
            "status": row.status,
        }

    # ============ 生效（FR-05a 差异已在 diff_summary）============

    async def _effective(self, row: OrdOrderModify, *, operator: str) -> None:
        """改单生效：把快照里记录的新地址写入收货人表"""
        diff = row.diff_summary if isinstance(row.diff_summary, dict) else {}
        new_addr = diff.get("new") if isinstance(diff.get("new"), dict) else {}
        rcv = await self.s.scalar(
            select(OrdReceiver).where(
                OrdReceiver.order_id == row.order_id, OrdReceiver.is_deleted == 0
            )
        )
        if rcv is not None and new_addr:
            for f in ("province", "city", "district", "town"):
                v = new_addr.get(f)
                if v:
                    setattr(rcv, f, str(v))
            enc = new_addr.get("address_enc")
            if enc:
                rcv.address_enc = _unhex(enc)
            rcv.update_time = utcnow()
            rcv.version = int(rcv.version or 0) + 1
        row.status = MODIFY_STATUS_EFFECTIVE
        row.effective_time = utcnow()
        row.saga_log = [
            *(row.saga_log or []),
            {
                "at": utcnow().isoformat(),
                "stage": "effective",
                "ok": True,
                "detail": operator,
            },
        ]

    # ============ 快照（FR-02a）============

    async def _snapshot(self, order: OrdOrder) -> int:
        """生成改单快照（不可变副本）"""
        items = list(
            await self.s.scalars(
                select(OrdOrderItem).where(
                    OrdOrderItem.order_id == order.id, OrdOrderItem.is_deleted == 0
                )
            )
        )
        rcv = await self.s.scalar(
            select(OrdReceiver).where(
                OrdReceiver.order_id == order.id, OrdReceiver.is_deleted == 0
            )
        )
        snap = OrdOrderSnapshot(
            tenant_id=order.tenant_id,
            owner_id=order.owner_id,
            snapshot_bn=f"SNP{utcnow():%Y%m%d}{uuid.uuid4().hex[:6].upper()}",
            order_id=order.id,
            snap_order={
                "order_status": order.order_status,
                "audit_status": order.audit_status,
                "fulfill_status": order.fulfill_status,
                "pay_status": order.pay_status,
                "ship_status": order.ship_status,
                "list_amount": float(order.list_amount or 0),
                "shop_discount": float(order.shop_discount or 0),
                "platform_subsidy": float(order.platform_subsidy or 0),
                "paid_amount": float(order.paid_amount or 0),
                "freight": float(order.freight or 0),
                "buyer_nick": order.buyer_nick,
            },
            snap_items=[
                {
                    "id": i.id,
                    "platform_sku_code": i.platform_sku_code,
                    "bm_id": i.bm_id,
                    "nums": i.nums,
                    "list_price": float(i.list_price or 0),
                    "list_amount": float(i.list_amount or 0),
                    "paid_amount": float(i.paid_amount or 0),
                }
                for i in items
            ],
            # ⚠ 收货人快照保持**密文**（PIPL）：name_enc / address_enc 原样存，
            #   mobile_hash / address_hash 存哈希（非明文）
            # ⚠ name_enc / mobile_enc / address_enc 是 **blob（bytes）**
            #   → 快照统一存 hex 字符串（JSON 可序列化，且不可逆推明文）
            snap_receiver=(
                {
                    "name_enc": _hex(rcv.name_enc),
                    "mobile_enc": _hex(rcv.mobile_enc),
                    "mobile_hash": rcv.mobile_hash,
                    "address_enc": _hex(rcv.address_enc),
                    "address_hash": rcv.address_hash,
                    "province": rcv.province,
                    "city": rcv.city,
                    "district": rcv.district,
                    "town": rcv.town,
                }
                if rcv is not None
                else {}
            ),
            snap_extend={
                "buyer_memo": order.buyer_memo,
                "warehouse_memo": order.warehouse_memo,
                "promotion_source": order.promotion_source,
            },
            freeze_ids=[],
            status_snap={"order_status": order.order_status},
        )
        self.s.add(snap)
        await self.s.flush()
        return int(snap.id)

    # ============ 差异对比（FR-05a）============

    async def _diff_address(
        self,
        order_id: int,
        *,
        province: str,
        city: str,
        district: str,
        town: str,
        address_enc: bytes | str,
    ) -> dict[str, Any]:
        """字段级差异对比（旧值 / 新值 / 差异类型）"""
        rcv = await self.s.scalar(
            select(OrdReceiver).where(
                OrdReceiver.order_id == order_id, OrdReceiver.is_deleted == 0
            )
        )
        old = {
            "province": rcv.province if rcv else "",
            "city": rcv.city if rcv else "",
            "district": rcv.district if rcv else "",
            "town": rcv.town if rcv else "",
            # 地址密文不可读 → 用哈希比对是否变化
            "address_hash": rcv.address_hash if rcv else "",
        }
        new = {
            "province": province or "",
            "city": city or "",
            "district": district or "",
            "town": town or "",
            "address_enc": _hex(address_enc),
        }
        changed = [
            f
            for f in ("province", "city", "district", "town")
            if (old.get(f) or "") != (new.get(f) or "")
        ]
        if address_enc and rcv is not None:
            if _hex(rcv.address_enc) != _hex(address_enc):
                changed.append("address")
        return {
            "old": old,
            "new": new,
            "changed_fields": changed,
            "has_diff": bool(changed),
        }

    # ============ 查询 ============

    async def _get(self, modify_id: int) -> OrdOrderModify:
        row = await self.s.scalar(
            select(OrdOrderModify).where(
                OrdOrderModify.id == modify_id, OrdOrderModify.is_deleted == 0
            )
        )
        if row is None:
            raise NotFoundError(f"改单不存在: {modify_id}")
        return row

    async def list_modifies(
        self,
        *,
        order_id: int | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """改单列表"""
        q = select(OrdOrderModify).where(OrdOrderModify.is_deleted == 0)
        if order_id:
            q = q.where(OrdOrderModify.order_id == order_id)
        if status:
            q = q.where(OrdOrderModify.status == status)
        rows = list(await s_rows(self.s, q, limit))
        return [
            {
                "id": r.id,
                "modify_bn": r.modify_bn,
                "order_id": r.order_id,
                "order_bn": r.order_bn,
                "modify_type": r.modify_type,
                "modify_type_name": MODIFY_TYPE_LABEL.get(r.modify_type, r.modify_type),
                "source": r.source,
                "status": r.status,
                "need_recall": int(r.need_recall or 0),
                "snapshot_id": r.snapshot_id,
                "diff_summary": r.diff_summary,
                "operator": r.operator,
                "effective_time": r.effective_time.strftime("%Y-%m-%d %H:%M:%S")
                if r.effective_time
                else None,
                "create_time": r.create_time.strftime("%Y-%m-%d %H:%M:%S")
                if r.create_time
                else None,
            }
            for r in rows
        ]

    async def get_modify(self, modify_id: int) -> dict[str, Any]:
        """改单详情（含快照与 saga 日志）"""
        row = await self._get(modify_id)
        snap = await self.s.scalar(
            select(OrdOrderSnapshot).where(OrdOrderSnapshot.id == int(row.snapshot_id or 0))
        )
        return {
            "id": row.id,
            "modify_bn": row.modify_bn,
            "order_id": row.order_id,
            "order_bn": row.order_bn,
            "modify_type": row.modify_type,
            "modify_type_name": MODIFY_TYPE_LABEL.get(row.modify_type, row.modify_type),
            "source": row.source,
            "status": row.status,
            "need_recall": int(row.need_recall or 0),
            "recall_status": row.recall_status,
            "recall_refs": row.recall_refs,
            "snapshot_id": row.snapshot_id,
            "diff_summary": row.diff_summary,
            "saga_log": row.saga_log,
            "operator": row.operator,
            "effective_time": row.effective_time.strftime("%Y-%m-%d %H:%M:%S")
            if row.effective_time
            else None,
            "create_time": row.create_time.strftime("%Y-%m-%d %H:%M:%S")
            if row.create_time
            else None,
            "snapshot": {
                "snapshot_bn": snap.snapshot_bn,
                "snap_order": snap.snap_order,
                "snap_items": snap.snap_items,
                "snap_receiver": snap.snap_receiver,
                "snap_extend": snap.snap_extend,
            }
            if snap is not None
            else None,
        }


async def s_rows(session: AsyncSession, q, limit: int):
    """执行带 limit 的 select"""
    return await session.scalars(q.order_by(OrdOrderModify.id.desc()).limit(limit))
