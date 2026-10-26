"""ModifyApplyMixin —— 由 ModifyService 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.timeutil import utcnow
from app.models.modify import OrdOrderModify, OrdOrderSnapshot
from app.models.order import OrdOrder, OrdOrderItem, OrdReceiver
from app.modules.m6_aftersale.service.modify_codes import (
    MODIFY_STATUS_EFFECTIVE,
    MODIFY_TYPE_LABEL,
    _hex,  # noqa: F401
    _unhex,  # noqa: F401
    s_rows,
)


class ModifyApplyMixin:
    """ModifyService 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Any

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
