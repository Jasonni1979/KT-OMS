"""AuditContextMixin —— 由 AuditEngine 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.order import OrdOrder, OrdOrderItem, OrdReceiver
from app.modules.m3_trade.service.audit_models import (
    AuditContextData,
    _num,  # noqa: F401
    _plugin_params,  # noqa: F401
)

logger = get_logger("audit")


class AuditContextMixin:
    """AuditEngine 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Redis
    rule_service: Any

    # ---------- 上下文装载 ----------

    async def load_context(self, order_id: int) -> AuditContextData:
        """装载审单上下文（FR-01b：只读装载订单快照+行BOM+收货人）"""
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id, OrdOrder.is_deleted == 0)
        )
        if order is None:
            raise NotFoundError(f"订单不存在: {order_id}")
        items = list(
            await self.s.scalars(
                select(OrdOrderItem)
                .where(OrdOrderItem.order_id == order_id, OrdOrderItem.is_deleted == 0)
                .order_by(OrdOrderItem.id)
            )
        )
        receiver = await self.s.scalar(
            select(OrdReceiver).where(OrdReceiver.order_id == order_id)
        )
        item_dicts = [
            {
                "id": it.id,
                "owner_id": it.owner_id,
                "bm_id": it.bm_id,
                "bm_number": it.bm_number,
                "bm_name": it.bm_name,
                "nums": it.nums,
                # ⚠ weight / tax_amount 是**可空列** → float(None) 会抛
                #   TypeError 让整个审单 500。统一用 _num() 兜底为 0。
                "paid_amount": _num(it.paid_amount),
                "list_price": _num(it.list_price),
                "parse_status": it.parse_status,
                "is_virtual": it.is_virtual,
                "is_gift": it.is_gift,
                "weight": _num(it.weight),
                "platform_sku_code": it.platform_sku_code,
            }
            for it in items
        ]
        recv: dict[str, Any] = {
            "province": receiver.province if receiver else "",
            "city": receiver.city if receiver else "",
            "district": receiver.district if receiver else "",
            "town": receiver.town if receiver else "",
            "mobile_hash": receiver.mobile_hash if receiver else "",
            "address_hash": receiver.address_hash if receiver else "",
            # 详址密文长度（PIPL：地址密文不可读，长度可作为「详址是否填写」的判据）
            "address_len": len(receiver.address_enc) if receiver and receiver.address_enc else 0,
            "is_cipher": receiver.is_cipher if receiver else 0,
        }
        order_dict = {
            "id": order.id,
            "order_bn": order.order_bn,
            "shop_id": order.shop_id,
            "brand_id": order.brand_id,
            "owner_id": order.owner_id,
            "order_status": order.order_status,
            "audit_status": order.audit_status,
            "fulfill_status": order.fulfill_status,
            "pay_status": order.pay_status,
            "ship_status": order.ship_status,
            "paid_amount": float(order.paid_amount),
            "list_amount": float(order.list_amount),
            "order_type": order.order_type,
            "createway": order.createway,
            "is_cod": order.is_cod,
            "is_pause": order.is_pause,
            "buyer_memo": order.buyer_memo,
            "warehouse_memo": order.warehouse_memo,
            "warehouse_hint": order.warehouse_memo,
            "buyer_id": order.buyer_nick,
            "batch_no": order.batch_no,
            "pay_time": order.pay_time,
            "order_time": order.order_time,
        }
        # 规则维度上下文（18 维取值；缺失维度不命中）
        dims: dict[str, Any] = {
            "shop_id": [order.shop_id],
            "brand_id": [order.brand_id],
            "owner_id": [order.owner_id],
            "order.amount_paid": float(order.paid_amount),
            "order.amount_list": float(order.list_amount),
            "order_type": [order.order_type],
            "order.is_cod": bool(order.is_cod),
            "order.receiver_province": [receiver.province] if receiver and receiver.province else [],
            "order.receiver_city": [receiver.city] if receiver and receiver.city else [],
            "order.has_memo": bool(order.buyer_memo),
            "order.createway": [order.createway],
            "order.items.sku": [it.platform_sku_code for it in items if it.platform_sku_code],
            "order.items.count": len({it.platform_sku_code for it in items}),
            "order.items.nums": sum(it.nums for it in items),
            "order.weight": sum(_num(it.weight) for it in items),
        }
        # 插件元信息（ctx.meta：插件运行期依赖的外部句柄与候选集）
        meta: dict[str, Any] = {
            "session": self.s,
            "redis": self.r,
            "items": item_dicts,
            "branch_candidates": await self._branch_candidates(order.shop_id),
            "logistics_candidates": [],
            "blacklist_entries": [],
            "order_weight": dims["order.weight"],
        }
        # 插件只读取数据袋（ctx.data）——收货人等只读字段必须进数据袋
        dims.update(
            {
                "receiver_province": recv["province"],
                "receiver_city": recv["city"],
                "receiver_district": recv["district"],
                "receiver_town": recv["town"],
                "receiver_address_hash": recv["address_hash"],
                "receiver_mobile_hash": recv["mobile_hash"],
                "receiver_address_len": recv["address_len"],
                "receiver_is_cipher": recv["is_cipher"],
            }
        )
        return AuditContextData(
            order=order_dict, items=item_dicts, receiver=recv, dims=dims, meta=meta
        )

    async def _branch_candidates(self, shop_id: int) -> list[dict[str, Any]]:
        """候选发货仓（店铺发货仓绑定 gw_shop_config.branch_bind_json）"""
        from sqlalchemy import text

        row = await self.s.execute(
            text(
                "SELECT branch_bind_json FROM oms_gateway.gw_shop_config "
                "WHERE shop_id = :sid AND is_deleted = 0 LIMIT 1"
            ),
            {"sid": shop_id},
        )
        raw = row.scalar()
        if not raw:
            return []
        try:
            binds = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            return []
        if not isinstance(binds, list):
            return []
        out: list[dict[str, Any]] = []
        for b in binds:
            branch_id = int(b.get("branch_id", 0) or 0)
            if branch_id <= 0:
                continue
            name = await self.s.scalar(
                text("SELECT branch_name FROM oms_fulfill.ful_branch WHERE id = :bid"),
                {"bid": branch_id},
            )
            out.append(
                {
                    "branch_id": branch_id,
                    "branch_name": name or "",
                    "priority": int(b.get("priority", 999) or 999),
                }
            )
        return out

    async def _logistics_candidates(self, branch_id: int) -> list[dict[str, Any]]:
        """候选物流（仓-物流绑定 ful_store_carrier_map）"""
        from sqlalchemy import text

        rows = await self.s.execute(
            text(
                "SELECT m.carrier_code, m.carrier_store_id, c.carrier_name "
                "FROM oms_fulfill.ful_store_carrier_map m "
                "LEFT JOIN oms_fulfill.ful_carrier c ON c.carrier_code = m.carrier_code "
                "WHERE m.store_branch_id = :bid AND m.is_deleted = 0 "
                "ORDER BY m.id"
            ),
            {"bid": branch_id},
        )
        return [
            {
                "carrier_code": r[0],
                "carrier_store_id": r[1],
                "carrier_name": r[2] or r[0],
                "priority": i,
            }
            for i, r in enumerate(rows.all())
        ]