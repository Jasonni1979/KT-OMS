"""缺货策略链（SRS-D03.09 FR-04b 换仓重试 + FR-04c 解除重审 · W8-2）

## 策略链编排（FR-04b：顺序执行，每步产出「建议/自动动作」）
| 步 | 动作 | 本期状态 |
|---|---|---|
| ① | **换仓重试**（自动测算其他候选仓可用量） | ✅ 本期实现 |
| ② | 借调建议（D04.05 额度服务） | ⏸ P1 —— 本期只留扩展位，不伪造数据 |
| ③ | 采购加急 / 调拨入库 | ⏸ P1 —— 同上 |
| ④ | 协商（部分发货 / 延迟发货） | ⏸ 后续 |

## 换仓重试的关键机制（复用 D03.06，不重复造）
- `DispatchService.dispatch(order_id, exclude_branches=[已试仓], source="retry")`
  → 生成新一轮 plan（缺口行重算 + 排除已试仓）
- `PlanExecutor.execute(plan_id)` → 重新预占（幂等键 = plan_bn）
- 预占成功 → **缺货异常单闭环**（FR-04c：预占成功异常单闭环）

## 可用量口径
统一取 `StockLedgerService.available_of(branch_id, bm_id, owner_id)`
（D04.02 全局唯一公式），与审单 stock_check 插件同源。
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.models.abnormal import OrdAbnormal, OrdStockout
from app.models.order import OrdOrder
from app.modules.m4_fulfill.contract import DispatchService_dispatch_service as DispatchService
from app.modules.m4_fulfill.contract import PlanExecutor
from app.modules.m5_abnormal.service.abnormal import AbnormalService

#: 换仓测算结果状态
STRATEGY_FULL = "full"        # 整单满足（某候选仓可满足全部缺口行）
STRATEGY_PARTIAL = "partial"  # 部分满足（提示拆单换仓）
STRATEGY_NONE = "none"        # 无候选仓可满足


class StockoutStrategyService:
    """缺货策略链服务"""

    def __init__(self, session: AsyncSession, redis: Any = None):
        self.s = session
        self.r = redis

    # ============ ① 换仓测算（FR-04b-1）============

    async def calc_switch_branch(self, abnormal_id: int) -> dict[str, Any]:
        """测算其他候选仓可用量（**只测算不执行**）

        返回：
        ```
        {
          "status": "full" | "partial" | "none",
          "current_branch_ids": [已试仓],
          "candidates": [
            {"branch_id", "branch_name", "available", "lack_num", "enough",
             "satisfied_lines": n, "total_lines": m}
          ],
          "suggest": {...}          # 建议动作
          "borrow_stock": {"enabled": False, "reason": "D04.05 额度服务未实现（P1）"}
        }
        ```
        """
        abn, details = await self._load(abnormal_id)
        if not details:
            return {
                "status": STRATEGY_NONE,
                "current_branch_ids": [],
                "candidates": [],
                "suggest": {"action": "none", "reason": "无缺货明细"},
                "borrow_stock": {"enabled": False, "reason": "D04.05 额度服务未实现（P1）"},
            }

        from app.modules.m2_stock.contract import StockLedgerService

        ledger = StockLedgerService(self.s, self.r)
        current_branches = sorted({int(d.branch_id or 0) for d in details if d.branch_id})

        # 候选仓 = 订单店铺的仓绑定（D03.06 分仓规则同源），排除已试仓
        candidates = await self._candidate_branches(abn, exclude=current_branches)
        out: list[dict[str, Any]] = []
        best_full: dict[str, Any] | None = None
        best_partial: dict[str, Any] | None = None

        for c in candidates:
            branch_id = int(c["branch_id"])
            available_total = 0
            satisfied = 0
            per_line: list[dict[str, Any]] = []
            for d in details:
                owner_id = int((d.stock_snapshot or {}).get("owner_id") or 0)
                bm_id = int(d.bm_id or 0)
                lack = int(d.lack_num or 0)
                avail = 0
                if bm_id > 0:
                    try:
                        # 与审单 stock_check 插件同源（D04.02 全局唯一公式）
                        bal = await ledger.get_balance(branch_id, bm_id, owner_id)
                        avail = int(getattr(bal, "available", 0) or 0)
                    except Exception:  # noqa: BLE001 —— 余额查询失败按 0 可用量
                        avail = 0
                enough = avail >= lack
                if enough:
                    satisfied += 1
                available_total += min(avail, lack)
                per_line.append(
                    {"bm_id": bm_id, "lack_num": lack, "available": avail, "enough": enough}
                )
            item = {
                "branch_id": branch_id,
                "branch_name": c.get("branch_name", ""),
                "priority": c.get("priority", 999),
                "available_total": available_total,
                "satisfied_lines": satisfied,
                "total_lines": len(details),
                "lines": per_line,
                "enough": satisfied == len(details),
            }
            out.append(item)
            if item["enough"] and best_full is None:
                best_full = item
            elif satisfied > 0 and best_partial is None:
                best_partial = item

        if best_full is not None:
            status = STRATEGY_FULL
            suggest = {
                "action": "switch_branch",
                "branch_id": best_full["branch_id"],
                "branch_name": best_full["branch_name"],
                "reason": "该仓可整单满足缺口 → 一键换仓重审",
            }
        elif best_partial is not None:
            status = STRATEGY_PARTIAL
            suggest = {
                "action": "split_switch_branch",
                "branch_id": best_partial["branch_id"],
                "branch_name": best_partial["branch_name"],
                "reason": "仅部分行可满足 → 提示拆单换仓（D03.06 联动）",
            }
        else:
            status = STRATEGY_NONE
            suggest = {
                "action": "none",
                "reason": "无候选仓可满足缺口 → 建议借调/采购加急（P1）或转售后协商",
            }

        return {
            "status": status,
            "current_branch_ids": current_branches,
            "candidates": out,
            "suggest": suggest,
            "borrow_stock": {
                "enabled": False,
                "reason": "D04.05 货主借调额度服务未实现（P1），本期不提供该建议",
            },
        }

    async def _candidate_branches(
        self, abn: OrdAbnormal, *, exclude: list[int]
    ) -> list[dict[str, Any]]:
        """候选仓（店铺仓绑定，排除已试仓）"""
        from sqlalchemy import text

        if not abn.shop_id:
            return []
        row = await self.s.execute(
            text(
                "SELECT branch_bind_json FROM oms_gateway.gw_shop_config "
                "WHERE shop_id = :sid AND is_deleted = 0 LIMIT 1"
            ),
            {"sid": abn.shop_id},
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
            if branch_id <= 0 or branch_id in exclude:
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
        out.sort(key=lambda x: x["priority"])
        return out

    # ============ ① 换仓重试执行（FR-04b-1）============

    async def switch_branch(
        self,
        abnormal_id: int,
        *,
        operator: str = "system",
        exclude_branches: list[int] | None = None,
    ) -> dict[str, Any]:
        """换仓重试：缺口行重算（排除已试仓）→ 新 plan → 重新预占 → 成功则闭环

        复用 D03.06 `DispatchService.dispatch(exclude_branches=..., source="retry")`
        与 `PlanExecutor.execute`（幂等键 = plan_bn）。
        """
        abn, details = await self._load(abnormal_id)
        if not details:
            raise ValidationError("异常单无缺货明细，无法换仓重试")
        current = sorted({int(d.branch_id or 0) for d in details if d.branch_id})
        exclude = sorted(set(current) | set(exclude_branches or []))

        dispatch_svc = DispatchService(self.s, self.r)
        plan_svc = PlanExecutor(self.s, self.r)
        abnormal_svc = AbnormalService(self.s, self.r)

        # ① 换仓重算（缺口行重算 + 排除已试仓）
        # ⚠ dispatch 可能抛业务异常（如订单无明细行 → ValidationError），
        #   必须捕获并回写策略结果，否则异常单既没闭环也没留痕（实测踩到）
        try:
            res = await dispatch_svc.dispatch(
                abn.order_id,
                exclude_branches=exclude,
                source="retry",
                operator=operator,
            )
        except Exception as e:  # noqa: BLE001 —— 换仓失败不应打断异常单流程
            payload = {
                "action": "switch_branch",
                "ok": False,
                "stage": "dispatch",
                "fail_message": str(e)[:200],
                "excluded_branches": exclude,
            }
            await abnormal_svc.set_strategy_result_of(
                abnormal_id, status="failed", result=payload
            )
            return {"ok": False, "stage": "dispatch", **payload}
        if not res.ok or not res.plan_id:
            await abnormal_svc.set_strategy_result_of(
                abnormal_id,
                status="none",
                result={
                    "action": "switch_branch",
                    "ok": False,
                    "fail_code": res.fail_code,
                    "fail_message": res.fail_message,
                    "excluded_branches": exclude,
                },
            )
            return {
                "ok": False,
                "stage": "dispatch",
                "fail_code": res.fail_code,
                "fail_message": res.fail_message,
                "excluded_branches": exclude,
            }

        # ② 重新预占
        try:
            exec_res = await plan_svc.execute(res.plan_id, operator=operator)
        except Exception as e:  # noqa: BLE001 —— 预占异常同样回写结果
            payload = {
                "action": "switch_branch",
                "ok": False,
                "stage": "execute",
                "plan_id": res.plan_id,
                "fail_message": str(e)[:200],
                "excluded_branches": exclude,
            }
            await abnormal_svc.set_strategy_result_of(
                abnormal_id, status="failed", result=payload
            )
            return {"ok": False, "stage": "execute", **payload}
        ok = exec_res.status == "success"
        payload = {
            "action": "switch_branch",
            "ok": ok,
            "plan_id": res.plan_id,
            "round_no": res.round_no,
            "excluded_branches": exclude,
            "fail_code": exec_res.fail_code,
            "fail_message": exec_res.fail_message,
        }
        await abnormal_svc.set_strategy_result_of(
            abnormal_id, status="done" if ok else "failed", result=payload
        )
        # ③ 预占成功 → 异常单闭环（FR-04c）
        if ok:
            await abnormal_svc.resolve(
                abnormal_id,
                action="reaudit",
                operator=operator,
                note=f"换仓重试成功（plan {res.plan_id} 预占通过）",
            )
        return {"ok": ok, "stage": "execute", **payload}

    # ============ ③ 解除重审（FR-04c）============

    async def release_and_retry(
        self, abnormal_id: int, *, operator: str = "system"
    ) -> dict[str, Any]:
        """库存补足后重审：同仓重新预占 → 成功则异常单闭环

        FR-04c：任一策略补足库存后 → 缺货异常单提示「重审」→ 一键触发
        订单回审单池重新预占；**预占成功异常单闭环**。
        """
        abn, details = await self._load(abnormal_id)
        if not details:
            raise ValidationError("异常单无缺货明细")
        abnormal_svc = AbnormalService(self.s, self.r)
        plan_svc = PlanExecutor(self.s, self.r)

        # 找当前有效 plan（最新一轮）
        from sqlalchemy import select as _sel

        from app.models.audit import OrdFulfillPlan

        plan = await self.s.scalar(
            _sel(OrdFulfillPlan)
            .where(
                OrdFulfillPlan.order_id == abn.order_id,
                OrdFulfillPlan.is_deleted == 0,
            )
            .order_by(OrdFulfillPlan.id.desc())
        )
        if plan is None:
            raise NotFoundError(f"订单无履约方案，无法重审: order_id={abn.order_id}")

        # ① 废弃旧 plan（释放预占，FR-05d）
        await plan_svc.discard_plan(plan.id, operator=operator)
        # ② 同仓重新预占（库存已补足）
        try:
            exec_res = await plan_svc.execute(plan.id, operator=operator)
        except Exception as e:  # noqa: BLE001 —— 预占异常回写结果，不打断流程
            payload = {
                "action": "release_retry",
                "ok": False,
                "stage": "execute",
                "plan_id": plan.id,
                "fail_message": str(e)[:200],
            }
            await abnormal_svc.set_strategy_result_of(
                abnormal_id, status="failed", result=payload
            )
            return {"ok": False, "stage": "execute", **payload}
        ok = exec_res.status == "success"
        payload = {
            "action": "release_retry",
            "ok": ok,
            "plan_id": plan.id,
            "fail_code": exec_res.fail_code,
            "fail_message": exec_res.fail_message,
        }
        await abnormal_svc.set_strategy_result_of(
            abnormal_id, status="done" if ok else "failed", result=payload
        )
        if ok:
            await abnormal_svc.resolve(
                abnormal_id,
                action="reaudit",
                operator=operator,
                note="库存已补足，重审预占通过",
            )
        return {"ok": ok, "stage": "execute", **payload}

    # ============ 内部 ============

    async def _load(self, abnormal_id: int) -> tuple[OrdAbnormal, list[OrdStockout]]:
        abn = await self.s.scalar(
            select(OrdAbnormal).where(
                OrdAbnormal.id == abnormal_id, OrdAbnormal.is_deleted == 0
            )
        )
        if abn is None:
            raise NotFoundError(f"异常单不存在: {abnormal_id}")
        details = list(
            await self.s.scalars(
                select(OrdStockout)
                .where(
                    OrdStockout.abnormal_id == abnormal_id,
                    OrdStockout.is_deleted == 0,
                )
                .order_by(OrdStockout.id)
            )
        )
        return abn, details

    async def order_of(self, abnormal_id: int) -> OrdOrder:
        abn, _ = await self._load(abnormal_id)
        order = await self.s.scalar(
            select(OrdOrder).where(OrdOrder.id == abn.order_id, OrdOrder.is_deleted == 0)
        )
        if order is None:
            raise NotFoundError(f"订单不存在: {abn.order_id}")
        return order
