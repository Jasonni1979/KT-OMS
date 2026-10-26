"""DispatchDecideMixin —— 由 DispatchService 拆分而来（P3 上下文体积治理）"""

# ⚠ mixin 的 `self.<其它 mixin 的方法>` 在静态检查里不可见（方法分散在多个文件）
#   → 仅关闭 attr-defined 误报；其余类型检查照常生效。
# mypy: disable-error-code="attr-defined"

from __future__ import annotations

from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.fulfill import (
    OrdBranchChangeLog,
    OrdDispatchPlan,
    OrdRoutingDecisionLog,
)
from app.models.order import OrdOrder, OrdOrderItem
from app.modules.m4_fulfill.service.dispatch_models import (
    FAIL_FULL_LACK,
    FAIL_PARTIAL_LACK,
    MODE_APPOINTED,
    MODE_LACK,
    MODE_MULTI,
    MODE_SINGLE,
    BranchCandidate,
    DispatchResult,
    _in_window,  # noqa: F401
    )

logger = get_logger("dispatch")


class DispatchDecideMixin:
    """DispatchService 的部分能力（混入主类，行为等价）"""

    s: AsyncSession
    r: Redis

    async def _decide(
        self,
        order: OrdOrder,
        items: list[OrdOrderItem],
        candidates: list[BranchCandidate],
        stock_view: dict[tuple[int, int, int], int],
        rule_hit: dict[str, Any],
        source: str,
        started: datetime,
    ) -> DispatchResult:
        """整仓优先 → 贪心多仓 → 缺货判定（FR-03b/FR-04a）"""
        res = DispatchResult(ok=True, rule_hit=rule_hit)

        # ① 整仓优先
        for cand in candidates:
            if cand.fulfill_rate >= 1.0:
                cand.priority = 0
                res.mode = (
                    MODE_APPOINTED if cand.source == "platform" else MODE_SINGLE
                )
                res.alloc = self._alloc_single(cand, items)
                res.candidates = candidates
                res.fulfill_snapshot = self._snapshot(candidates)
                return await self._finish(order, res, source, started)

        # ② 贪心多仓组合
        remain: dict[int, int] = {}
        for it in items:
            need = int(it.nums or 0) - int(getattr(it, "split_num", 0) or 0)
            if need > 0 and it.bm_id:
                remain[int(it.id)] = need
        alloc: dict[int, dict[int, int]] = {}
        for cand in candidates:
            if not remain:
                break
            for it in items:
                iid = int(it.id)
                if iid not in remain or remain[iid] <= 0:
                    continue
                # 行级货主约束（FR-01c）：仓不服务该行货主 → 该行不可在此仓发
                if not self._can_serve(cand, int(it.owner_id or 0)):
                    continue
                avail = stock_view.get(
                    (cand.branch_id, int(it.bm_id), int(it.owner_id or 0)), 0
                )
                take = min(avail, remain[iid])
                if take > 0:
                    alloc.setdefault(iid, {})[cand.branch_id] = (
                        alloc.get(iid, {}).get(cand.branch_id, 0) + take
                    )
                    remain[iid] -= take
        if not remain:
            res.mode = MODE_MULTI
            res.alloc = alloc
            res.split_required = True
            res.candidates = candidates
            res.fulfill_snapshot = self._snapshot(candidates)
            return await self._finish(order, res, source, started)

        # ③ 缺货判定（FR-04a）
        res.ok = False
        res.mode = MODE_LACK
        res.alloc = alloc
        res.split_required = True
        res.candidates = candidates
        res.fulfill_snapshot = self._snapshot(candidates)
        gap_rows = []
        for it in items:
            iid = int(it.id)
            if remain.get(iid, 0) <= 0:
                continue
            gap_rows.append(
                {
                    "order_item_id": iid,
                    "bm_id": int(it.bm_id or 0),
                    "bm_number": str(it.bm_number or ""),
                    "need": int(it.nums or 0),
                    "gap": remain[iid],
                    "best_available": sum(
                        stock_view.get(
                            (c.branch_id, int(it.bm_id), int(it.owner_id or 0)), 0
                        )
                        for c in candidates
                    ),
                    "candidate_count": len(candidates),
                }
            )
        res.lack_detail = {"gaps": gap_rows, "gap_total": sum(remain.values())}
        res.fail_code = (
            FAIL_PARTIAL_LACK if alloc else FAIL_FULL_LACK
        )
        res.fail_message = (
            f"{len(gap_rows)} 行缺货，缺口 {res.lack_detail['gap_total']} 件"
        )
        res.lack_route = "transfer_to_lack"  # 转 D03.09 缺货流程
        return await self._finish(order, res, source, started)

    def _alloc_single(
        self, cand: BranchCandidate, items: list[OrdOrderItem]
    ) -> dict[int, dict[int, int]]:
        """整仓分配（整仓满足率=100% 时调用；行级货主约束已由满足度保证）"""
        alloc: dict[int, dict[int, int]] = {}
        for it in items:
            need = int(it.nums or 0) - int(getattr(it, "split_num", 0) or 0)
            if need <= 0:
                continue
            alloc[int(it.id)] = {cand.branch_id: need}
        return alloc

    def _snapshot(self, candidates: list[BranchCandidate]) -> dict[str, Any]:
        """满足度快照（FR-03c：人工界面「建议仓+各仓库存」数据源）"""
        return {
            "branches": [c.to_dict() for c in candidates],
            "generated_at": datetime.now().isoformat(timespec="milliseconds"),
        }

    async def _finish(
        self,
        order: OrdOrder,
        res: DispatchResult,
        source: str,
        started: datetime,
    ) -> DispatchResult:
        """plan 落库 + 旧轮次 superseded + 埋点"""
        res.cost_ms = int((datetime.now() - started).total_seconds() * 1000)
        round_no = await self._next_round(order.id)
        plan = OrdDispatchPlan(
            owner_id=int(order.owner_id or 0),
            order_id=order.id,
            round_no=round_no,
            alloc={str(k): {str(b): q for b, q in v.items()} for k, v in res.alloc.items()},
            mode=res.mode,
            split_required=1 if res.split_required else 0,
            fulfill_snapshot=res.fulfill_snapshot,
            lack_detail=res.lack_detail or None,
            rule_hit=res.rule_hit,
            source=source,
            status="effective",
            lack_route=res.lack_route or None,
            shop_id=int(order.shop_id or 0),
        )
        self.s.add(plan)
        await self.s.flush()
        res.plan_id = plan.id
        res.round_no = round_no

        # 旧轮次 superseded（FR-05c：plan 不可变、只追加）
        await self.s.execute(
            text(
                "UPDATE oms_order.ord_dispatch_plan SET status = 'superseded' "
                "WHERE order_id = :oid AND id <> :pid AND status = 'effective'"
            ),
            {"oid": order.id, "pid": plan.id},
        )

        # 路由决策埋点（FR-08a：DOM 寻源数据地基）
        chosen = 0
        for v in res.alloc.values():
            for b in v:
                chosen = chosen or b
        self.s.add(
            OrdRoutingDecisionLog(
                owner_id=int(order.owner_id or 0),
                order_id=order.id,
                round_no=round_no,
                candidate_branches=[c.to_dict() for c in res.candidates],
                branch_features=self._features(res.candidates),
                rule_hit=res.rule_hit,
                chosen_branch=chosen or None,
                cost_compare=self._cost_compare(res),
                decision_mode="rule",
                duration_ms=res.cost_ms,
                shop_id=int(order.shop_id or 0),
            )
        )
        await self.s.commit()
        return res

    def _features(self, candidates: list[BranchCandidate]) -> dict[str, Any]:
        """各仓特征快照（FR-08a：可用量/深度/满足率）"""
        return {
            str(c.branch_id): {
                "fulfill_rate": round(c.fulfill_rate, 4),
                "available": c.available_map,
                "source": c.source,
                "priority": c.priority,
            }
            for c in candidates
        }

    def _cost_compare(self, res: DispatchResult) -> dict[str, Any]:
        """拆单 vs 等货 vs 调拨成本对比（FR-08b，规则式打分）"""
        if res.mode == MODE_MULTI:
            return {
                "decision": "split",
                "split_cost": res.split_required,
                "reason": "无单一仓整单满足，拆单履约",
            }
        if res.mode == MODE_LACK:
            return {
                "decision": "lack",
                "split_cost": 0,
                "reason": "全仓不可满足，转缺货流程",
            }
        return {"decision": "single", "split_cost": 0, "reason": "整仓满足"}

    async def _next_round(self, order_id: int) -> int:
        rows = await self.s.execute(
            text(
                "SELECT COALESCE(MAX(round_no), 0) FROM oms_order.ord_dispatch_plan "
                "WHERE order_id = :oid"
            ),
            {"oid": order_id},
        )
        return int(rows.scalar() or 0) + 1

    async def _fail(
        self,
        order: OrdOrder,
        items: list[OrdOrderItem],
        candidates: list[BranchCandidate],
        code: str,
        message: str,
        source: str,
        started: datetime,
    ) -> DispatchResult:
        res = DispatchResult(
            ok=False,
            mode=MODE_LACK,
            candidates=candidates,
            fail_code=code,
            fail_message=message,
            lack_route="transfer_to_lack",
        )
        return await self._finish(order, res, source, started)

    async def retry_with_gap(
        self,
        order_id: int,
        gap_item_ids: list[int],
        exclude_branches: list[int],
        *,
        operator: str = "system",
    ) -> DispatchResult:
        """换仓重试（FR-04b-1：缺口行重算、排除已试仓）"""
        return await self.dispatch(
            order_id,
            exclude_branches=exclude_branches,
            source="retry",
            operator=operator,
        )

    async def get_fulfill_view(self, order_id: int) -> dict[str, Any]:
        """人工审单界面：建议仓 + 各仓库存满足度快照"""
        plan = await self.s.scalar(
            select(OrdDispatchPlan)
            .where(
                OrdDispatchPlan.order_id == order_id,
                OrdDispatchPlan.status == "effective",
            )
            .order_by(OrdDispatchPlan.round_no.desc())
            .limit(1)
        )
        if not plan:
            return {"found": False, "candidates": []}
        snap = plan.fulfill_snapshot or {}
        return {
            "found": True,
            "plan_id": plan.id,
            "round_no": plan.round_no,
            "mode": plan.mode,
            "split_required": bool(plan.split_required),
            "alloc": plan.alloc,
            "lack_detail": plan.lack_detail,
            "candidates": snap.get("branches", []),
            "rule_hit": plan.rule_hit,
        }

    async def change_branch(
        self,
        order_id: int,
        new_branch_id: int,
        reason: str,
        operator: str,
        *,
        forced: bool = False,
    ) -> DispatchResult:
        """手工改仓（FR-06b/c/d：校验 + 审计 + 新轮次 plan source=manual）"""
        if not reason:
            raise ValidationError("改仓原因必填")
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == order_id, OrdOrder.is_deleted == 0)
        )
        if not order:
            raise NotFoundError(f"订单不存在: {order_id}")

        old_plan = await self.s.scalar(
            select(OrdDispatchPlan)
            .where(
                OrdDispatchPlan.order_id == order_id,
                OrdDispatchPlan.status == "effective",
            )
            .order_by(OrdDispatchPlan.round_no.desc())
            .limit(1)
        )
        old_branch = 0
        old_rate = 0.0
        if old_plan:
            for v in (old_plan.alloc or {}).values():
                for b in v:
                    old_branch = old_branch or int(b)
            snap = old_plan.fulfill_snapshot or {}
            for b in snap.get("branches", []):
                if int(b.get("branch_id", 0)) == old_branch:
                    old_rate = float(b.get("fulfill_rate", 0) or 0)

        # 货主仓属硬约束不可绕过（FR-06b + AC-04）
        items = list(
            await self.s.scalars(
                select(OrdOrderItem)
                .where(OrdOrderItem.order_id == order_id, OrdOrderItem.is_deleted == 0)
            )
        )
        servable = await self._branch_servable_owners(new_branch_id)
        item_owners = {int(it.owner_id or 0) for it in items if it.bm_id}
        if servable and item_owners and not item_owners.issubset(set(servable)):
            raise ValidationError(
                f"新仓不可服务本单货主（仓可服务货主={servable}，本单货主={sorted(item_owners)}）"
            )

        # 新仓满足度校验（不足时警示，强制需走审批——本实现记 forced 标记）
        view = await self.get_fulfill_view(order_id)
        new_rate = 0.0
        for b in view.get("candidates", []):
            if int(b.get("branch_id", 0)) == new_branch_id:
                new_rate = float(b.get("fulfill_rate", 0) or 0)
        if new_rate < 1.0 and not forced:
            raise ValidationError(
                f"新仓满足度不足（{new_rate:.2%}），如需强制改仓请带 forced 标记"
            )

        # 写审计（FR-06c）
        self.s.add(
            OrdBranchChangeLog(
                owner_id=int(order.owner_id or 0),
                order_id=order.id,
                plan_round=old_plan.round_no if old_plan else None,
                old_branch=old_branch or None,
                new_branch=new_branch_id,
                old_fulfill=old_rate,
                new_fulfill=new_rate,
                reason=reason,
                forced=1 if forced else 0,
                operator=operator,
                shop_id=int(order.shop_id or 0),
            )
        )
        await self.s.commit()

        # 新轮次 plan（source=manual，与自动 plan 同构可追溯）
        res = await self.dispatch(
            order_id,
            source="manual",
            appointed_branch_id=new_branch_id,
            operator=operator,
        )
        return res