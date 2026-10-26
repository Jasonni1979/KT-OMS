"""AbnormalCreateMixin —— 由 AbnormalService 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.core.timeutil import utcnow
from app.models.abnormal import (
    ABNORMAL_CATEGORY_OTHER,
    ABNORMAL_STATUS_WAIT_DISPATCH,
    OrdAbnormal,
    OrdAbnormalTypeDict,
    OrdReasonCodeDict,
)
from app.models.base import BaseSeq
from app.models.order import OrdOrder
from app.modules.m5_abnormal.service.abnormal_codes import (
    ABNORMAL_SEQ_DOMAIN,
    CLOSED_STATUSES,
    EXC_OTHER,
)

logger = get_logger("abnormal")


class AbnormalCreateMixin:
    """AbnormalService 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Any

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
        # FR-02c：落单后自动分派（规则引擎 → 类型默认组 → 留待人工）
        # ⚠ 失败不阻断落单（异常单已创建是事实，分派可人工补）
        try:
            await self.auto_dispatch(row.id, operator="system")
        except Exception as e:  # noqa: BLE001 —— 自动分派失败不影响异常单落库
            logger.warning(
                "abnormal_auto_dispatch_failed", detail=str(e), abnormal_id=row.id
            )
        await self.s.refresh(row)
        return row, True

    async def auto_dispatch(
        self, abnormal_id: int, *, operator: str = "system", note: str = ""
    ) -> tuple[OrdAbnormal | None, dict]:
        """自动分派（FR-02c：按类型默认处理组 / 分派规则引擎）

        分派规则引擎维度：异常类型/店铺/货主/品牌（+ 存量规则的 reason_code）。
        规则未命中 → 类型默认处理组 → 都没有则留「待分派」等人工分派。
        """
        from app.modules.m5_abnormal.service.abnormal_dispatch import (
            AbnormalDispatchEngine,
        )

        row = await self.get(abnormal_id)
        if row.status != ABNORMAL_STATUS_WAIT_DISPATCH:
            return None, {"ok": False, "reason": "非待分派状态"}
        engine = AbnormalDispatchEngine(self.s)
        decision = await engine.decide(row)
        gid = int(decision.get("group_id") or 0)
        if gid <= 0:
            return None, {**decision, "ok": False, "reason": "无匹配规则且类型无默认处理组"}
        updated = await self.dispatch(
            abnormal_id,
            group_id=gid,
            op_id=int(decision.get("op_id") or 0),
            operator=operator,
            note=note or f"自动分派（{decision.get('rule_name') or decision.get('source')}）",
        )
        return updated, {**decision, "ok": True}

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
