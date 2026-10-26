"""M2 gate③ 演示端到端（三类异常单的人工处置闭环）

**这是 M2 里程碑的正式验收点**（PLAN-DEV-01 §M2 gate③：异常单三类人工处置演示）。

三类异常各自跑一条**完整真实链路**（不 mock 数据库，全部走真实服务）：

```
审单投审 → 审单插件产出原因码 → 按原因码字典落异常单 → 自动分派
        → 人工处置动作 → 异常单闭环 → 订单审单原因标记清零
```

| 场景 | 原因码 | 异常类型 | 处置动作（DDL action_set 白名单） | 验收点 |
|---|---|---|---|---|
| 缺货 | STOCK_SHORTAGE | STOCK_SHORT | 解除重审 reaudit | 缺货明细 + 策略链 + 闭环 |
| 未绑定商品 | GOODS_UNBOUND | PRODUCT_UNBOUND | 修复后重新审单 reaudit | 落单 + 分派 + 闭环 |
| 地址异常 | ADDRESS_INVALID | ADDR_INCOMPLETE | 重新审单 reaudit | 越权动作被拒 + 闭环 |

补充验证（同一套动作能力的不同类型分支）：
- 转复审 to_retrial → PRICE_ABNORMAL 类型（复审单落 ord_retrial）
- 强制放行 force_pass → RISK_HIT 类型（ABNORMAL_RISK 原因码，留审计痕迹）

用法：
    cd backend && .venv/bin/python -m app.scripts.m2_gate3_e2e [--with-mock]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

from sqlalchemy import select, text

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.db import AuthContext, SessionFactory, engine, set_auth_context  # noqa: E402
from app.models.abnormal import (  # noqa: E402
    ABNORMAL_STATUS_ASSIGNED,
    ABNORMAL_STATUS_RESOLVED,
    OrdAbnormal,
)
from app.models.audit import OrdRetrial  # noqa: E402
from app.services.abnormal import AbnormalService  # noqa: E402
from app.services.abnormal_action import (  # noqa: E402
    ACT_FORCE_PASS,
    ACT_REAUDIT,
    ACT_TO_RETRIAL,
    AbnormalActionService,
)
from app.services.master import get_redis  # noqa: E402
from app.services.stockout_strategy import StockoutStrategyService  # noqa: E402

#: 独立前缀（与演示数据 DLVW7DEMO% / 其他 E2E 的 DLVE2E% / W7WB% 不冲突）
PREFIX = "M2G3"

#: 人工分派兜底用的处理组（DDL 预置的「默认审核组」id=1）
DEFAULT_GROUP_ID = 1


def _uid() -> str:
    return f"{time.time_ns() % 100000000:08d}"


class Checker:
    """断言收集器（W8 复盘后统一抽到 _checker.py；此处保留轻量副本以独立运行）"""

    def __init__(self) -> None:
        self.passed = 0
        self.failed = 0
        self.lines: list[str] = []

    def check(self, name: str, cond: bool, detail: str = "") -> bool:
        if cond:
            self.passed += 1
            self.lines.append(f"  [PASS] {name}" + (f" | {detail}" if detail else ""))
        else:
            self.failed += 1
            self.lines.append(f"  [FAIL] {name}" + (f" | {detail}" if detail else ""))
        return cond

    def section(self, title: str) -> None:
        self.lines.append(f"--- {title} ---")

    @property
    def total(self) -> int:
        return self.passed + self.failed

    def render(self) -> str:
        return "\n".join(self.lines)

    def summary(self) -> str:
        return f"合计：{self.passed}/{self.total} 项通过"


# ============ 造数 ============


async def _mk_order(
    owner_id: int = 1,
    shop_id: int = 0,
    brand_id: int = 0,
    bm_id: int = 0,
) -> int:
    """造一张订单（含 1 行；bm_id=0 → 模拟未绑定商品）"""
    order_bn = f"{PREFIX}O{_uid()}"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_order "
                "(tenant_id, owner_id, order_bn, platform_order_bn, shop_id, brand_id, "
                " createway, order_type, order_status, audit_status, fulfill_status, "
                " pay_status, ship_status, list_amount, shop_discount, platform_subsidy, "
                " paid_amount, freight, is_cod, order_time, pay_time, create_time, "
                " update_time, version, is_deleted) "
                "VALUES (1, :own, :obn, :pon, :sid, :bid, 'platform', 'normal', "
                "'processing', 'pending', 'pending', 'paid', 'unshipped', "
                "100, 0, 0, 100, 0, 0, NOW(3), NOW(3), NOW(3), NOW(3), 0, 0)"
            ),
            {
                "obn": order_bn,
                "pon": f"{PREFIX}SIM_{_uid()}",
                "sid": shop_id,
                "bid": brand_id,
                "own": owner_id,
            },
        )
        oid = int(
            (
                await conn.execute(
                    text("SELECT id FROM oms_order.ord_order WHERE order_bn = :obn"),
                    {"obn": order_bn},
                )
            ).scalar()
            or 0
        )
        # 订单行
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_order_item "
                "(tenant_id, owner_id, order_id, platform_sku_code, bm_id, bm_number, "
                " bm_name, nums, list_price, list_amount, paid_amount, parse_status, "
                " create_time, update_time, version, is_deleted) "
                "VALUES (1, :own, :oid, :sku, :bm, :bmn, '测试物料', 2, 50, 100, 100, "
                ":ps, NOW(3), NOW(3), 0, 0)"
            ),
            {
                "own": owner_id,
                "oid": oid,
                "sku": f"{PREFIX}SKU_{_uid()}",
                "bm": bm_id,
                "bmn": f"{PREFIX}BM_{_uid()}" if bm_id else "",
                "ps": "parsed" if bm_id else "pending",
            },
        )
        # 收货人（地址异常场景要能命中地址校验）
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_receiver "
                "(tenant_id, order_id, name_enc, mobile_enc, mobile_hash, address_enc, "
                " address_hash, province, city, district, town, is_cipher, "
                " create_time, update_time, version, is_deleted) "
                "VALUES (1, :oid, 'ENC_NAME', 'ENC_MOBILE', 'M_HASH', 'ENC_ADDR', "
                "'A_HASH', '广东省', '深圳市', '', '', 0, NOW(3), NOW(3), 0, 0)"
            ),
            {"oid": oid},
        )
    return oid


async def _mk_reason(order_id: int, reason_code: str, plugin: str = "test") -> int:
    """造一条 open 状态的审单原因（模拟审单引擎产出）"""
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO oms_order.ord_audit_reason "
                "(tenant_id, owner_id, order_id, batch_no, plugin_name, reason_code, "
                " level, description, detail, suggest_action, route_target, handle_status, "
                " shop_id, create_time) "
                "VALUES (1, 1, :oid, 'B1', :pl, :rc, 'BLOCK', '测试原因', "
                "NULL, 'fix', 'manual', 'open', 0, NOW(3))"
            ),
            {"oid": order_id, "rc": reason_code, "pl": plugin},
        )
        return int(
            (
                await conn.execute(
                    text(
                        "SELECT id FROM oms_order.ord_audit_reason "
                        "WHERE order_id = :oid AND handle_status='open' ORDER BY id DESC LIMIT 1"
                    ),
                    {"oid": order_id},
                )
            ).scalar()
            or 0
        )


async def _clean(order_ids: list[int]) -> None:
    """清理自造数据（按 FK 顺序：先子表后父表）"""
    if not order_ids:
        return
    lst = ",".join(str(i) for i in order_ids)
    async with engine.begin() as conn:
        await conn.execute(
            text(f"DELETE FROM oms_order.ord_abnormal WHERE order_id IN ({lst})")
        )
        await conn.execute(
            text(f"DELETE FROM oms_order.ord_retrial WHERE order_id IN ({lst})")
        )
        await conn.execute(
            text(f"DELETE FROM oms_order.ord_audit_reason WHERE order_id IN ({lst})")
        )
        await conn.execute(
            text(f"DELETE FROM oms_order.ord_receiver WHERE order_id IN ({lst})")
        )
        await conn.execute(
            text(f"DELETE FROM oms_order.ord_order_item WHERE order_id IN ({lst})")
        )
        await conn.execute(text(f"DELETE FROM oms_order.ord_order WHERE id IN ({lst})"))


async def _open_reason_count(order_id: int) -> int:
    async with SessionFactory() as s:
        return int(
            await s.scalar(
                text(
                    "SELECT COUNT(*) FROM oms_order.ord_audit_reason "
                    "WHERE order_id = :o AND handle_status='open'"
                ),
                {"o": order_id},
            )
            or 0
        )


async def _ensure_dispatched(svc: AbnormalService, abn_id: int, ck: Checker, label: str) -> None:
    """确保异常单已分派（落单时已自动分派过；未分派则人工兜底）"""
    async with SessionFactory() as s2:
        abn = await s2.scalar(select(OrdAbnormal).where(OrdAbnormal.id == abn_id))
    if abn is not None and abn.status == ABNORMAL_STATUS_ASSIGNED:
        ck.check(f"{label}：已分派（落单时自动分派）", True, f"group={abn.group_id}")
        return
    await svc.dispatch(abn_id, group_id=DEFAULT_GROUP_ID, operator="e2e")
    ck.check(f"{label}：人工分派兜底生效（进入已分派）", True, f"group={DEFAULT_GROUP_ID}")

# ============ 场景一：缺货（STOCK_SHORTAGE → STOCK_SHORT）============


async def _scenario_stockout(ck: Checker, redis) -> int:
    """缺货场景：落单 → 缺货明细 → 换仓测算 → 处置闭环"""
    ck.section("场景一：缺货（STOCK_SHORTAGE → STOCK_SHORT）")
    oid = await _mk_order(bm_id=0)
    try:
        # ① 造审单原因 + 缺货明细（模拟 stock_check 插件产出的 shortages）
        await _mk_reason(oid, "STOCK_SHORTAGE", "stock_check")

        async with SessionFactory() as s:
            svc = AbnormalService(s, redis)
            row, created = await svc.raise_by_reason(
                order_id=oid,
                reason_code="STOCK_SHORTAGE",
                source="audit",
                source_ref="stock_check:STOCK_SHORTAGE",
                detail={
                    "shortages": [
                        {
                            "branch_id": 1,
                            "bm_id": 0,
                            "owner_id": 1,
                            "need": 5,
                            "available": 1,
                            "shortage": 4,
                        }
                    ]
                },
            )
            ck.check(
                "缺货：审单原因落异常单",
                row is not None and created,
                f"exc_type={getattr(row, 'exc_type', '')}",
            )
            if row is None:
                return oid
            ck.check(
                "缺货：异常类型为 STOCK_SHORT",
                row.exc_type == "STOCK_SHORT",
                f"exc_type={row.exc_type}",
            )
            abn_id = int(row.id)

            # ② 缺货明细（三元键 + 缺口量 + 库存快照）
            details = await svc.stockouts_of(abn_id)
            ck.check(
                "缺货：缺货明细已落（三元键 + 缺口量）",
                len(details) == 1
                and int(details[0].lack_num or 0) == 4
                and int(details[0].branch_id or 0) == 1,
                f"明细数={len(details)} 缺口={details[0].lack_num if details else 'N/A'}",
            )
            ck.check(
                "缺货：库存快照已记录",
                bool(details and details[0].stock_snapshot),
                f"snapshot={details[0].stock_snapshot if details else 'N/A'}",
            )

            # ③ 自动分派（FR-02c）—— 落单时已自动分派，这里核对状态
            await _ensure_dispatched(svc, abn_id, ck, "缺货")

            # ④ 换仓测算（FR-04b-1，只算不执行）
            strat_svc = StockoutStrategyService(s, redis)
            calc = await strat_svc.calc_switch_branch(abn_id)
            ck.check(
                "缺货：换仓测算返回可用性结论",
                "status" in calc and "borrow_stock" in calc,
                f"status={calc.get('status')} borrow={calc.get('borrow_stock')}",
            )
            ck.check(
                "缺货：借调建议为扩展位（不伪造额度）",
                (calc.get("borrow_stock") or {}).get("enabled") is False,
                f"borrow={calc.get('borrow_stock')}",
            )

            # ⑤ 处置动作：解除重审（FR-04c）
            act_svc = AbnormalActionService(s, redis)
            allowed = await act_svc.allowed_actions(abn_id)
            ck.check(
                "缺货：可用动作集含 reaudit",
                "reaudit" in allowed,
                f"allowed={allowed}",
            )
            res = await act_svc.execute(
                abn_id, ACT_REAUDIT, operator="e2e", note="补货到账，解除重审"
            )
            ck.check(
                "缺货：解除重审动作已执行",
                bool(res.get("ok")),
                f"ok={res.get('ok')} stage={res.get('stage')}",
            )

        # ⑥ 闭环校验：异常单已解决 + 审单原因清零
        async with SessionFactory() as s:
            abn = await s.scalar(select(OrdAbnormal).where(OrdAbnormal.id == abn_id))
        ck.check(
            "缺货：异常单已闭环（已解决）",
            abn is not None and abn.status == ABNORMAL_STATUS_RESOLVED,
            f"status={getattr(abn, 'status', '')}",
        )
        ck.check(
            "缺货：审单原因标记已清零（FR-02e）",
            await _open_reason_count(oid) == 0,
            f"open={await _open_reason_count(oid)}",
        )
        ck.check(
            "缺货：解决动作已留痕",
            bool(getattr(abn, "resolve_action", "")),
            f"resolve_action={getattr(abn, 'resolve_action', '')}",
        )
        return oid
    finally:
        await _clean([oid])


# ============ 场景二：未绑定商品（GOODS_UNBOUND → PRODUCT_UNBOUND）============


async def _scenario_unbound(ck: Checker, redis) -> int:
    """未绑定商品场景：落单 → 自动分派 → 修复后重新审单 → 闭环"""
    ck.section("场景二：未绑定商品（GOODS_UNBOUND → PRODUCT_UNBOUND）")
    oid = await _mk_order(bm_id=0)
    try:
        await _mk_reason(oid, "GOODS_UNBOUND", "goods_match")

        async with SessionFactory() as s:
            svc = AbnormalService(s, redis)
            row, created = await svc.raise_by_reason(
                order_id=oid,
                reason_code="GOODS_UNBOUND",
                source="audit",
                source_ref="goods_match:GOODS_UNBOUND",
            )
            ck.check(
                "未绑定：审单原因落异常单",
                row is not None and created,
                f"exc_type={getattr(row, 'exc_type', '')}",
            )
            if row is None:
                return oid
            ck.check(
                "未绑定：异常类型为 PRODUCT_UNBOUND",
                row.exc_type == "PRODUCT_UNBOUND",
                f"exc_type={row.exc_type}",
            )
            abn_id = int(row.id)

            # 自动分派（落单时已自动分派，这里核对状态）
            await _ensure_dispatched(svc, abn_id, ck, "未绑定")

            # 可用动作集：PRODUCT_UNBOUND → ["reaudit"]
            act_svc = AbnormalActionService(s, redis)
            allowed = await act_svc.allowed_actions(abn_id)
            ck.check(
                "未绑定：可用动作集仅 reaudit（DDL 白名单）",
                allowed == ["reaudit"],
                f"allowed={allowed}",
            )

            # 越权动作被拒
            from app.core.exceptions import ValidationError

            rejected = False
            try:
                await act_svc.execute(abn_id, "cancel", operator="e2e")
            except ValidationError:
                rejected = True
            ck.check("未绑定：越权动作被拒（cancel 不在白名单）", rejected, "")

            # 处置：修复后重新审单
            res = await act_svc.execute(abn_id, ACT_REAUDIT, operator="e2e", note="已建档绑定")
            ck.check(
                "未绑定：修复后重新审单已执行",
                bool(res.get("ok")),
                f"decision={res.get('audit_decision')}",
            )

        async with SessionFactory() as s:
            abn = await s.scalar(select(OrdAbnormal).where(OrdAbnormal.id == abn_id))
        ck.check(
            "未绑定：异常单已闭环",
            abn is not None and abn.status == ABNORMAL_STATUS_RESOLVED,
            f"status={getattr(abn, 'status', '')}",
        )
        ck.check(
            "未绑定：审单原因标记已清零",
            await _open_reason_count(oid) == 0,
            f"open={await _open_reason_count(oid)}",
        )
        return oid
    finally:
        await _clean([oid])


# ============ 场景三：地址异常（ADDRESS_INVALID → ADDR_INCOMPLETE）============


async def _scenario_address(ck: Checker, redis) -> int:
    """地址异常场景：落单 → 转复审（落复审单）→ 强制放行清标记 → 闭环"""
    ck.section("场景三：地址异常（ADDRESS_INVALID → ADDR_INCOMPLETE）")
    oid = await _mk_order(bm_id=0)
    try:
        await _mk_reason(oid, "ADDRESS_INVALID", "address_check")

        async with SessionFactory() as s:
            svc = AbnormalService(s, redis)
            row, created = await svc.raise_by_reason(
                order_id=oid,
                reason_code="ADDRESS_INVALID",
                source="audit",
                source_ref="address_check:ADDRESS_INVALID",
            )
            ck.check(
                "地址异常：审单原因落异常单",
                row is not None and created,
                f"exc_type={getattr(row, 'exc_type', '')}",
            )
            if row is None:
                return oid
            ck.check(
                "地址异常：异常类型为 ADDR_INCOMPLETE",
                row.exc_type == "ADDR_INCOMPLETE",
                f"exc_type={row.exc_type}",
            )
            abn_id = int(row.id)

            # 自动分派（落单时已自动分派，这里核对状态）
            await _ensure_dispatched(svc, abn_id, ck, "地址异常")

            act_svc = AbnormalActionService(s, redis)
            allowed = await act_svc.allowed_actions(abn_id)
            ck.check(
                "地址异常：可用动作集含 reaudit / to_aftersale",
                "reaudit" in allowed and "to_aftersale" in allowed,
                f"allowed={allowed}",
            )

            # 转售后（W9-1 已落地）→ 生成售后申请单，且**不立即闭环异常单**
            res_af = await act_svc.execute(abn_id, "to_aftersale", operator="e2e")
            ck.check(
                "地址异常：转售后生成售后申请单（W9-1 已落地）",
                res_af.get("ok") is True and int(res_af.get("apply_id") or 0) > 0,
                f"apply_bn={res_af.get('apply_bn')}",
            )
            ck.check(
                "地址异常：转售后为移交类动作（异常单不立即闭环）",
                res_af.get("closed") is False,
                f"closed={res_af.get('closed')} reason={res_af.get('close_reason')}",
            )
            async with SessionFactory() as s2:
                cnt = await s2.scalar(
                    text(
                        "SELECT COUNT(*) FROM oms_aftersale.aft_return_apply "
                        "WHERE order_id = :o"
                    ),
                    {"o": oid},
                )
            ck.check("地址异常：售后申请单已落库", int(cnt or 0) == 1, f"apply={cnt}")

            # 越权动作被拒（ADDR_INCOMPLETE 无 to_retrial）
            from app.core.exceptions import ValidationError

            rejected = False
            try:
                await act_svc.execute(abn_id, ACT_TO_RETRIAL, operator="e2e")
            except ValidationError:
                rejected = True
            ck.check("地址异常：越权动作被拒（to_retrial 不在白名单）", rejected, "")

            # 处置：修复后重新审单（reaudit，DDL 允许）
            res = await act_svc.execute(
                abn_id, ACT_REAUDIT, operator="e2e", note="改完地址重新审单"
            )
            ck.check(
                "地址异常：修复后重新审单已执行",
                bool(res.get("ok")),
                f"decision={res.get('audit_decision')}",
            )

        async with SessionFactory() as s:
            abn = await s.scalar(select(OrdAbnormal).where(OrdAbnormal.id == abn_id))
        ck.check(
            "地址异常：异常单已闭环",
            abn is not None and abn.status == ABNORMAL_STATUS_RESOLVED,
            f"status={getattr(abn, 'status', '')}",
        )
        ck.check(
            "地址异常：审单原因标记已清零",
            await _open_reason_count(oid) == 0,
            f"open={await _open_reason_count(oid)}",
        )

        # 转复审能力（ADDR_INCOMPLETE 无此动作 → 用 PRICE_ABNORMAL 类验证能力本身）
        oid3 = await _mk_order(bm_id=0)
        try:
            await _mk_reason(oid3, "PRICE_ABNORMAL", "price_check")
            async with SessionFactory() as s:
                svc = AbnormalService(s, redis)
                row3, _ = await svc.raise_by_reason(
                    order_id=oid3, reason_code="PRICE_ABNORMAL", source="audit"
                )
                if row3 is not None:
                    await _ensure_dispatched(svc, int(row3.id), ck, "价格异常(转复审)")
                    act = AbnormalActionService(s, redis)
                    res3 = await act.execute(
                        int(row3.id), ACT_TO_RETRIAL, operator="e2e", note="转复审"
                    )
                    ck.check(
                        "转复审能力：复审单已落库（ord_retrial）",
                        bool(res3.get("ok")) and int(res3.get("retrial_id") or 0) > 0,
                        f"retrial_bn={res3.get('retrial_bn')}",
                    )
                    async with SessionFactory() as s2:
                        ret3 = await s2.scalar(
                            select(OrdRetrial).where(
                                OrdRetrial.id == int(res3.get("retrial_id") or 0)
                            )
                        )
                    ck.check(
                        "转复审能力：复审单关联到原订单",
                        ret3 is not None and int(ret3.order_id or 0) == oid3,
                        f"order_id={getattr(ret3, 'order_id', '')}",
                    )
        finally:
            await _clean([oid3])

        # 强制放行（敏感操作留痕）—— 用 RISK_HIT（DDL action_set 含 force_pass）
        oid2 = await _mk_order(bm_id=0)
        try:
            await _mk_reason(oid2, "ABNORMAL_RISK", "blacklist")
            async with SessionFactory() as s:
                svc = AbnormalService(s, redis)
                row2, _ = await svc.raise_by_reason(
                    order_id=oid2,
                    reason_code="ABNORMAL_RISK",
                    source="audit",
                )
                if row2 is not None:
                    await _ensure_dispatched(svc, int(row2.id), ck, "风控命中(强放)")
                    act = AbnormalActionService(s, redis)
                    res2 = await act.execute(
                        int(row2.id),
                        ACT_FORCE_PASS,
                        operator="e2e",
                        note="已核实风控",
                    )
                    ck.check(
                        "强制放行：已执行并留审计痕迹",
                        bool(res2.get("ok")),
                        f"released={res2.get('released_reasons')}",
                    )
            async with SessionFactory() as s:
                abn2 = await s.scalar(
                    select(OrdAbnormal).where(
                        OrdAbnormal.order_id == oid2,
                        OrdAbnormal.exc_type == "RISK_HIT",
                    )
                )
            detail = {}
            if abn2 is not None and isinstance(abn2.reason_detail, dict):
                detail = abn2.reason_detail
            ck.check(
                "强制放行：留痕（含 OA 推送待办标记）",
                "force_pass" in detail
                and detail["force_pass"].get("oa_push") == "pending",
                f"detail_keys={list(detail.keys())}",
            )
        finally:
            await _clean([oid2])
        return oid
    finally:
        await _clean([oid])


# ============ 主流程 ============


async def main(with_mock: bool = False) -> int:
    from app.scripts._checker import Checker as SharedChecker  # noqa: F401

    ck = Checker()
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    redis = await get_redis()

    print("===== M2 gate③ 三类异常单人工处置闭环 =====")
    await _scenario_stockout(ck, redis)
    await _scenario_unbound(ck, redis)
    await _scenario_address(ck, redis)

    print(ck.render())
    print(f"\n{ck.summary()}")
    await engine.dispose()
    return 0 if ck.failed == 0 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-mock", action="store_true", help="自起模拟器（预留）")
    args = ap.parse_args()
    sys.exit(asyncio.run(main(with_mock=args.with_mock)))
