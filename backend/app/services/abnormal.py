"""异常单服务（SRS-D03.09 异常单与缺货处理 · W8）

覆盖：
- FR-01a/01b/01c  异常类型字典 + 原因码→类型映射（未映射兜底「其他异常」并告警）
- FR-02a          创建来源（系统自动 / 事件订阅 / 人工标记 / 联动生成）+ 幂等
- FR-02b          状态机（待分派→已分派→处理中→已解决/已取消/已挂起）+ 时间线
- FR-02c          分派（按类型默认处理组 / 手动改派转派撤销）
- FR-02d          处理动作（重新审单 / 取消订单 / 挂起 / 强制放行）
- FR-02e          闭环（异常单解决后解除订单异常标记；多异常单全部闭环才解除）
- FR-04a          缺货标记（订单级标记 + 三元键明细，多次预占失败按明细合并）
- FR-05a          超卖识别（平台已成交但 OMS 无货 → 超卖标记，SLA 更短）

**时间基准**：全链路用 `app.core.timeutil.utcnow()`（UTC naive）——
SLA 计时 / 账龄统计跨域比较，与 DB 的 DATETIME 同基准，与 DB 服务器时区无关。
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.timeutil import utcnow
from app.models.abnormal import (
    ABNORMAL_CATEGORY_OTHER,
    ABNORMAL_STATUS_ASSIGNED,
    ABNORMAL_STATUS_CANCELLED,
    ABNORMAL_STATUS_PROCESSING,
    ABNORMAL_STATUS_RESOLVED,
    ABNORMAL_STATUS_SUSPENDED,
    ABNORMAL_STATUS_WAIT_DISPATCH,
    ABNORMAL_TRANSITIONS,
    OrdAbnormal,
    OrdAbnormalTypeDict,
    OrdReasonCodeDict,
    OrdStockout,
)
from app.models.audit import OrdAuditReason
from app.models.base import BaseSeq
from app.models.order import OrdOrder

#: 异常类型编码（SRS-D03.09 §5.1 内置类型全集 —— **与 SRS 编码严格一致**）
EXC_PRODUCT_UNBOUND = "PRODUCT_UNBOUND"    # 商品未绑定
EXC_ADDR_REMOTE = "ADDR_REMOTE"            # 收货地址偏远
EXC_ADDR_INCOMPLETE = "ADDR_INCOMPLETE"    # 地址不全/双地址
EXC_ADDR_POBOX = "ADDR_POBOX"              # PO Box 地址
EXC_ADDR_FAKE = "ADDR_FAKE"                # 虚假/不可达地址
EXC_PURCHASE_LIMIT = "PURCHASE_LIMIT"      # 限购命中
EXC_PRICE_ABNORMAL = "PRICE_ABNORMAL"      # 价格异常
EXC_BLACKLIST = "BLACKLIST"                # 黑名单客户
EXC_RISK_HIT = "RISK_HIT"                  # 风控命中
EXC_STOCK_SHORT = "STOCK_SHORT"            # 缺货
EXC_OVERSOLD = "OVERSOLD"                  # 超卖
EXC_PAY_ABNORMAL = "PAY_ABNORMAL"          # 支付异常
EXC_SPLIT_FAILED = "SPLIT_FAILED"          # 拆合单失败
EXC_WMS_PUSH_FAILED = "WMS_PUSH_FAILED"    # 推仓失败
EXC_SYNC_BACK_FAILED = "SYNC_BACK_FAILED"  # 回传失败
EXC_FULFILL_STAGNANT = "FULFILL_STAGNANT"  # 履约停滞
EXC_OTHER = "OTHER"                    # 其他异常（FR-01c：未映射原因码兜底）

#: DB 号段降级域码（与订单号 SEQ_DOMAIN="OD" 区分）
ABNORMAL_SEQ_DOMAIN = "AB"

#: 缺货类异常（超卖是缺货的子集，FR-05a）
STOCKOUT_TYPES = (EXC_STOCK_SHORT, EXC_OVERSOLD)

#: 地址类异常（前端按类筛选用）
ADDRESS_TYPES = (
    EXC_ADDR_REMOTE,
    EXC_ADDR_INCOMPLETE,
    EXC_ADDR_POBOX,
    EXC_ADDR_FAKE,
)

#: 状态机终态
CLOSED_STATUSES = (ABNORMAL_STATUS_RESOLVED, ABNORMAL_STATUS_CANCELLED)


class AbnormalService:
    """异常单服务"""

    def __init__(self, session: AsyncSession, redis: Any = None):
        self.s = session
        self.r = redis

    # ============ 类型字典（FR-01）============

    async def type_of(self, type_code: str) -> OrdAbnormalTypeDict | None:
        return await self.s.scalar(
            select(OrdAbnormalTypeDict).where(
                OrdAbnormalTypeDict.type_code == type_code,
                OrdAbnormalTypeDict.disabled == 0,
                OrdAbnormalTypeDict.is_deleted == 0,
            )
        )

    async def types_all(self) -> list[OrdAbnormalTypeDict]:
        rows = await self.s.scalars(
            select(OrdAbnormalTypeDict)
            .where(
                OrdAbnormalTypeDict.disabled == 0,
                OrdAbnormalTypeDict.is_deleted == 0,
            )
            .order_by(OrdAbnormalTypeDict.id)
        )
        return list(rows)

    async def reason_dict(self, reason_code: str) -> OrdReasonCodeDict | None:
        """查审单原因码字典条目（D03.02 产出）"""
        if not reason_code:
            return None
        return await self.s.scalar(
            select(OrdReasonCodeDict).where(
                OrdReasonCodeDict.reason_code == reason_code,
                OrdReasonCodeDict.disabled == 0,
            )
        )

    async def type_by_reason_code(
        self, reason_code: str
    ) -> OrdAbnormalTypeDict | None:
        """原因码 → 异常类型（FR-01c：多对一；未映射时兜底「其他异常」）

        **权威来源 = `ord_reason_code_dict.exc_type`**（DDL 预置的原因码字典，
        一行一个原因码，直接带映射的异常类型）；类型字典里的 `reason_code_map`
        只是类型侧的汇总 JSON（数组形态），不作为映射判定依据。
        """
        if not reason_code:
            return await self._fallback_type()
        rd = await self.reason_dict(reason_code)
        if rd is not None and rd.exc_type:
            hit = await self.type_of(str(rd.exc_type))
            if hit is not None:
                return hit
        # 未映射 → 兜底「其他异常」（FR-01c：并由调用方告警提示配置）
        return await self._fallback_type()

    async def _fallback_type(self) -> OrdAbnormalTypeDict | None:
        """兜底类型（FR-01c：未映射原因码 → 「其他异常」并告警提示配置）"""
        types = await self.types_all()
        for t in types:
            if t.type_code == EXC_OTHER:
                return t
        return types[0] if types else None

    # ============ 创建（FR-02a）============

    async def _next_bn(self) -> str:
        """异常单号（`ABN` + yyyyMMdd + 6 位序列）

        **三级降级**（照订单号 OrderBnGenerator 的成熟模式）：
        ① Redis `INCR seq:abnormal:{yyyyMMdd}`（原子、跨进程安全）
        ② DB 号段 `bas_seq`（CAS 发号，Redis 故障时用，不重号）
        ③ UUID 短码（DB 也不可用时的最后兜底）

        ⚠ 不可只依赖 Redis：Redis 不可用时若序列恒为 0，单号会退化成
        「日期+000000」→ **第二张异常单就撞唯一键**（实测复现）。
        """
        now = utcnow()
        ymd = now.strftime("%Y%m%d")
        seq = 0
        if self.r is not None:
            try:
                seq = int(await self.r.incr(f"seq:abnormal:{ymd}"))
            except Exception:
                seq = 0
        if seq <= 0:
            seq = await self._next_seq_db(ymd)
        if seq <= 0:
            seq = int(uuid.uuid4().hex[:6], 16) % 1_000_000
        return f"ABN{ymd}{seq:06d}"

    async def _next_seq_db(self, ymd: str) -> int:
        """DB 号段降级（CAS 发号：一次取一段号，段内本地自增）"""
        try:
            seq_date = datetime.strptime(ymd, "%Y%m%d").date()
        except ValueError:
            return 0
        async with self.s.begin_nested():
            row = await self.s.scalar(
                select(BaseSeq).where(
                    BaseSeq.seq_domain == ABNORMAL_SEQ_DOMAIN,
                    BaseSeq.seq_date == seq_date,
                )
            )
            if row is None:
                row = BaseSeq(
                    seq_domain=ABNORMAL_SEQ_DOMAIN,
                    seq_date=seq_date,
                    current_value=0,
                    step_size=100,
                    max_value=99_999_999,
                )
                self.s.add(row)
                await self.s.flush()
            step = int(row.step_size or 100)
            row.current_value = int(row.current_value or 0) + step
            row.version = int(row.version or 0) + 1
        return int(row.current_value)

    async def create(
        self,
        *,
        order: OrdOrder,
        exc_type: str,
        source: str,
        source_ref: str = "",
        reason_detail: dict | None = None,
        group_id: int | None = None,
        op_id: int = 0,
    ) -> tuple[OrdAbnormal, bool]:
        """创建异常单 —— 返回 (异常单, 是否新建)

        **幂等（FR-02a）**：同订单同类型且未闭环 → 复用已有异常单，不重复创建。
        """
        tdict = await self.type_of(exc_type)
        if tdict is None:
            raise NotFoundError(f"异常类型不存在: {exc_type}")

        # 幂等：同订单同类型未闭环
        existing = await self.s.scalar(
            select(OrdAbnormal)
            .where(
                OrdAbnormal.order_id == order.id,
                OrdAbnormal.exc_type == exc_type,
                OrdAbnormal.status.notin_(CLOSED_STATUSES),
                OrdAbnormal.is_deleted == 0,
            )
            .order_by(OrdAbnormal.id.desc())
        )
        if existing is not None:
            return existing, False

        now = utcnow()
        sla_hours = int(tdict.default_sla_hours or 24)
        row = OrdAbnormal(
            tenant_id=order.tenant_id,
            owner_id=order.owner_id,
            abnormal_bn=await self._next_bn(),
            order_id=order.id,
            order_bn=order.order_bn,
            shop_id=order.shop_id,
            exc_type=exc_type,
            exc_category=tdict.category or ABNORMAL_CATEGORY_OTHER,
            source=source,
            source_ref=source_ref[:128],
            reason_detail=reason_detail,
            status=ABNORMAL_STATUS_WAIT_DISPATCH,
            group_id=group_id if group_id is not None else int(tdict.default_group_id or 0),
            op_id=op_id,
            sla_deadline=now + timedelta(hours=sla_hours),
            timeline=[],
            version=0,
            is_deleted=0,
        )
        self.s.add(row)
        await self.s.flush()
        await self._append_timeline(
            row,
            operator="system",
            action="create",
            note=f"来源={source} ref={source_ref[:64]}",
            from_status="",
            to_status=ABNORMAL_STATUS_WAIT_DISPATCH,
        )
        await self.s.commit()
        await self.s.refresh(row)
        return row, True

    # ============ 时间线（FR-02b）============

    async def _append_timeline(
        self,
        row: OrdAbnormal,
        *,
        operator: str,
        action: str,
        note: str = "",
        from_status: str = "",
        to_status: str = "",
    ) -> None:
        tl = list(row.timeline or [])
        tl.append(
            {
                "at": utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "operator": operator,
                "action": action,
                "note": note[:512],
                "from": from_status,
                "to": to_status,
            }
        )
        row.timeline = tl

    # ============ 统一落单入口（FR-03a/FR-03b）============

    async def raise_by_reason(
        self,
        *,
        order_id: int,
        reason_code: str,
        source: str,
        source_ref: str = "",
        detail: dict | None = None,
    ) -> tuple[OrdAbnormal | None, bool]:
        """按原因码落异常单 —— **唯一入口**（FR-03a 审单不通过 / FR-03b 履约链路）

        落单与否由**字典**决定（不写死在代码里）：
        ① `ord_reason_code_dict.exc_type` 为空 → **不落单**
           （普通不通过原因仍留在审单工作台，避免异常池泛滥 —— FR-03a）
        ② 映射到的类型 `need_abnormal_bill=0` → **不落单**
        ③ 否则落异常单；若是缺货类且 detail 带缺口明细 → 一并落缺货明细（FR-04a）

        返回 (异常单 or None, 是否新建)
        """
        rd = await self.reason_dict(reason_code)
        if rd is None or not rd.exc_type:
            return None, False
        tdict = await self.type_of(str(rd.exc_type))
        if tdict is None or not int(tdict.need_abnormal_bill or 0):
            return None, False
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id, OrdOrder.is_deleted == 0)
        )
        if order is None:
            return None, False

        row, created = await self.create(
            order=order,
            exc_type=str(rd.exc_type),
            source=source,
            source_ref=source_ref or reason_code,
            reason_detail={
                "reason_code": reason_code,
                "reason_name": rd.reason_name,
                "plugin": rd.plugin_name,
                "route": rd.default_route,
                "suggest": rd.default_suggest,
                "detail": detail or {},
            },
        )
        # 缺货类 → 落缺货明细（三元键 + 缺口量 + 库存快照）
        if str(rd.exc_type) in STOCKOUT_TYPES:
            shortages = (detail or {}).get("shortages") or []
            if shortages:
                items = []
                for sh in shortages:
                    items.append(
                        {
                            "branch_id": int(sh.get("branch_id") or 0),
                            "bm_id": int(sh.get("bm_id") or 0),
                            "lack_num": int(
                                sh.get("shortage")
                                or (
                                    int(sh.get("need") or 0)
                                    - int(sh.get("available") or 0)
                                )
                            ),
                            "stock_snapshot": {
                                "need": sh.get("need"),
                                "available": sh.get("available"),
                                "owner_id": sh.get("owner_id"),
                            },
                        }
                    )
                await self.mark_stockout(
                    row, items, oversold=(str(rd.exc_type) == EXC_OVERSOLD)
                )
        return row, created

    # ============ 状态机（FR-02b）============

    async def transit(
        self,
        abnormal_id: int,
        to_status: str,
        *,
        operator: str = "system",
        note: str = "",
        action: str = "",
    ) -> OrdAbnormal:
        """状态流转（校验合法性，非法流转抛 409）"""
        row = await self.get(abnormal_id)
        from_status = row.status
        allowed = ABNORMAL_TRANSITIONS.get(from_status, ())
        if to_status not in allowed:
            raise ConflictError(
                f"异常单状态不可从 {from_status} 流转到 {to_status}"
                f"（允许: {', '.join(allowed) or '无'}）",
                code="ABNORMAL_STATUS_INVALID",
            )
        row.status = to_status
        if action:
            row.resolve_action = action
        await self._append_timeline(
            row,
            operator=operator,
            action=action or "transit",
            note=note,
            from_status=from_status,
            to_status=to_status,
        )
        await self.s.commit()
        await self.s.refresh(row)
        return row

    # ============ 分派（FR-02c）============

    async def dispatch(
        self,
        abnormal_id: int,
        *,
        group_id: int,
        op_id: int = 0,
        operator: str = "system",
        note: str = "",
    ) -> OrdAbnormal:
        """分派到处理组/处理人（自动分派与手动改派同一入口）"""
        row = await self.get(abnormal_id)
        if row.status != ABNORMAL_STATUS_WAIT_DISPATCH:
            raise ConflictError(
                f"仅「待分派」可分派，当前状态 {row.status}",
                code="ABNORMAL_STATUS_INVALID",
            )
        row.group_id = group_id
        row.op_id = op_id
        row.dispatch_time = utcnow()
        await self._append_timeline(
            row,
            operator=operator,
            action="dispatch",
            note=note or f"处理组={group_id} 处理人={op_id}",
            from_status=ABNORMAL_STATUS_WAIT_DISPATCH,
            to_status=ABNORMAL_STATUS_ASSIGNED,
        )
        row.status = ABNORMAL_STATUS_ASSIGNED
        await self.s.commit()
        await self.s.refresh(row)
        return row

    # ============ 处理动作（FR-02d）============

    async def start_processing(
        self, abnormal_id: int, *, operator: str = "system", note: str = ""
    ) -> OrdAbnormal:
        return await self.transit(
            abnormal_id,
            ABNORMAL_STATUS_PROCESSING,
            operator=operator,
            note=note or "开始处理",
        )

    async def suspend(
        self,
        abnormal_id: int,
        *,
        until_hours: int,
        operator: str = "system",
        note: str = "",
    ) -> OrdAbnormal:
        """挂起（等货 / 等买家回复）—— 必须填预计恢复时间（FR-02d）"""
        if until_hours <= 0:
            raise ValidationError("挂起必须填写预计恢复时间（小时数 > 0）")
        row = await self.get(abnormal_id)
        row.suspend_until = utcnow() + timedelta(hours=until_hours)
        return await self.transit(
            abnormal_id,
            ABNORMAL_STATUS_SUSPENDED,
            operator=operator,
            note=note or f"挂起 {until_hours}h",
            action="suspend",
        )

    async def resolve(
        self,
        abnormal_id: int,
        *,
        action: str = "re_audit",
        operator: str = "system",
        note: str = "",
        retrial_id: int = 0,
        delivery_ids: list[int] | None = None,
    ) -> OrdAbnormal:
        """解决异常单（FR-02d 动作 + FR-02e 闭环联动）"""
        row = await self.get(abnormal_id)
        if row.status in CLOSED_STATUSES:
            raise ConflictError(
                f"异常单已闭环（{row.status}）", code="ABNORMAL_ALREADY_CLOSED"
            )
        if retrial_id:
            row.rel_retrial_id = retrial_id
        if delivery_ids is not None:
            row.rel_delivery_ids = delivery_ids
        await self.transit(
            abnormal_id,
            ABNORMAL_STATUS_RESOLVED,
            operator=operator,
            note=note or f"解决动作={action}",
            action=action,
        )
        # FR-02e 闭环联动：解除订单异常标记
        await self.release_order_marks(row, operator=operator)
        row = await self.get(abnormal_id)
        return row

    async def cancel(
        self, abnormal_id: int, *, operator: str = "system", note: str = ""
    ) -> OrdAbnormal:
        """取消异常单（订单取消收口，FR-02b）"""
        row = await self.get(abnormal_id)
        await self.transit(
            abnormal_id,
            ABNORMAL_STATUS_CANCELLED,
            operator=operator,
            note=note or "取消",
            action="cancel",
        )
        await self.release_order_marks(row, operator=operator)
        return await self.get(abnormal_id)

    # ============ 闭环联动（FR-02e）============

    async def release_order_marks(
        self, row: OrdAbnormal, *, operator: str = "system"
    ) -> bool:
        """解除订单异常标记

        订单存在多个未闭环异常单时，**全部闭环才解除标记**（对齐 D03.02
        「结构化原因清零才可审」）。解除动作 = 把对应审单原因置为 handled。
        """
        others = await self.s.scalars(
            select(OrdAbnormal).where(
                OrdAbnormal.order_id == row.order_id,
                OrdAbnormal.id != row.id,
                OrdAbnormal.status.notin_(CLOSED_STATUSES),
                OrdAbnormal.is_deleted == 0,
            )
        )
        if list(others):
            return False  # 还有未闭环异常单 → 不解除
        # 审单原因置 handled（D03.02 写入口径：open → handled）
        await self.s.execute(
            update(OrdAuditReason)
            .where(
                OrdAuditReason.order_id == row.order_id,
                OrdAuditReason.handle_status == "open",
            )
            .values(handle_status="handled", handle_way=f"abnormal:{operator}"[:64])
        )
        await self.s.commit()
        return True

    # ============ 缺货标记（FR-04a）============

    async def mark_stockout(
        self,
        row: OrdAbnormal,
        items: list[dict],
        *,
        oversold: bool = False,
    ) -> list[OrdStockout]:
        """缺货标记与明细

        items 每项：{branch_id, bm_id, lack_num, stock_snapshot?}
        **同一订单多次预占失败按明细合并更新缺口**（FR-04a）：
        同 (branch_id, bm_id) 已有明细 → 累加 lack_num 并刷新快照。
        """
        out: list[OrdStockout] = []
        for it in items:
            branch_id = int(it.get("branch_id") or 0)
            bm_id = int(it.get("bm_id") or 0)
            lack = int(it.get("lack_num") or 0)
            exist = await self.s.scalar(
                select(OrdStockout).where(
                    OrdStockout.abnormal_id == row.id,
                    OrdStockout.branch_id == branch_id,
                    OrdStockout.bm_id == bm_id,
                    OrdStockout.is_deleted == 0,
                )
            )
            if exist is not None:
                exist.lack_num = int(exist.lack_num or 0) + lack
                if it.get("stock_snapshot") is not None:
                    exist.stock_snapshot = it["stock_snapshot"]
                exist.oversold_flag = 1 if oversold else exist.oversold_flag
                exist.version += 1
                out.append(exist)
            else:
                detail = OrdStockout(
                    tenant_id=row.tenant_id,
                    owner_id=row.owner_id,
                    abnormal_id=row.id,
                    order_id=row.order_id,
                    branch_id=branch_id,
                    bm_id=bm_id,
                    lack_num=lack,
                    stock_snapshot=it.get("stock_snapshot"),
                    strategy_status="wait_calc",
                    oversold_flag=1 if oversold else 0,
                    version=0,
                    is_deleted=0,
                )
                self.s.add(detail)
                out.append(detail)
        await self.s.commit()
        for d in out:
            await self.s.refresh(d)
        return out

    async def stockouts_of(self, abnormal_id: int) -> list[OrdStockout]:
        rows = await self.s.scalars(
            select(OrdStockout)
            .where(
                OrdStockout.abnormal_id == abnormal_id,
                OrdStockout.is_deleted == 0,
            )
            .order_by(OrdStockout.id)
        )
        return list(rows)

    async def set_strategy_result(
        self,
        detail_id: int,
        *,
        status: str,
        result: dict | None = None,
    ) -> OrdStockout:
        """回写策略链结果（FR-04b）"""
        row = await self.s.scalar(
            select(OrdStockout).where(OrdStockout.id == detail_id)
        )
        if row is None:
            raise NotFoundError(f"缺货明细不存在: {detail_id}")
        row.strategy_status = status
        if result is not None:
            row.strategy_result = result
        row.version += 1
        await self.s.commit()
        await self.s.refresh(row)
        return row

    # ============ 查询（FR-02f）============

    async def get(self, abnormal_id: int) -> OrdAbnormal:
        row = await self.s.scalar(
            select(OrdAbnormal).where(
                OrdAbnormal.id == abnormal_id, OrdAbnormal.is_deleted == 0
            )
        )
        if row is None:
            raise NotFoundError(f"异常单不存在: {abnormal_id}")
        return row

    async def list_abnormals(
        self,
        *,
        status: str | None = None,
        exc_type: str | None = None,
        exc_category: str | None = None,
        order_id: int | None = None,
        shop_id: int | None = None,
        group_id: int | None = None,
        keyword: str | None = None,
        only_open: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[OrdAbnormal], int]:
        """异常单列表（FR-02f：按类型/状态/店铺/处理组过滤 + 分页）"""
        stmt = select(OrdAbnormal).where(OrdAbnormal.is_deleted == 0)
        if status:
            stmt = stmt.where(OrdAbnormal.status == status)
        if exc_type:
            stmt = stmt.where(OrdAbnormal.exc_type == exc_type)
        if exc_category:
            stmt = stmt.where(OrdAbnormal.exc_category == exc_category)
        if order_id:
            stmt = stmt.where(OrdAbnormal.order_id == order_id)
        if shop_id:
            stmt = stmt.where(OrdAbnormal.shop_id == shop_id)
        if group_id:
            stmt = stmt.where(OrdAbnormal.group_id == group_id)
        if only_open:
            stmt = stmt.where(OrdAbnormal.status.notin_(CLOSED_STATUSES))
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                OrdAbnormal.abnormal_bn.like(like) | OrdAbnormal.order_bn.like(like)
            )
        total = await self.s.scalar(
            select(func.count()).select_from(stmt.subquery())
        )
        rows = await self.s.scalars(
            stmt.order_by(OrdAbnormal.id.desc()).limit(limit).offset(offset)
        )
        return list(rows), int(total or 0)

    async def sla_status(self, row: OrdAbnormal) -> dict:
        """SLA 状态（FR-01a：默认 SLA 小时 → 是否超时 / 剩余小时）"""
        now = utcnow()
        deadline = row.sla_deadline
        if deadline is None:
            return {"deadline": None, "overdue": False, "remain_hours": None}
        remain = (deadline - now).total_seconds() / 3600
        return {
            "deadline": deadline.strftime("%Y-%m-%d %H:%M:%S"),
            "overdue": remain < 0 and row.status not in CLOSED_STATUSES,
            "remain_hours": round(remain, 2),
        }
