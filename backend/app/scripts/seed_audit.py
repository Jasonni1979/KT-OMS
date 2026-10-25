"""审单域字典与规则预置（D01.03 FR-08 字典服务 + D03.02 FR-03 规则模型）

**代码 = 权威定义，DB = 登记副本**（与导入模板同一策略）。

预置内容：
1. 原因码字典（audit_reason_code）：码 → 名称/级别/默认路由/建议审核组/建议动作
2. 决策码字典（decision_code）
3. 审单规则（ord_audit_rule）：缺省规则 + 常用业务规则

用法：
    cd backend && .venv/bin/python -m app.scripts.seed_audit
"""
from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import select

from app.core.db import SessionFactory, engine, without_data_scope
from app.core.dicts import DICTS, DictItem
from app.models.audit import OrdAuditRule

# ============ 原因码字典（D03.02 §5.4 路由表）============

#: (code, 名称, 级别, 默认路由, 建议审核组, 建议动作)
REASON_CODES: list[tuple[str, str, str, str, str, str]] = [
    # 缺货类 → D03.09
    ("STOCK_SHORTAGE", "库存不足", "BLOCK", "shortage", "stock", "等补货"),
    ("STOCK_RACE", "预占竞态（决策到执行间库存被抢）", "BLOCK", "shortage", "stock", "重审重算"),
    # 决策类 → 人工
    ("NO_BRANCH", "无可用发货仓", "BLOCK", "manual", "fulfill", "人工指定仓库"),
    ("SPLIT_FAIL", "拆单失败", "BLOCK", "manual", "fulfill", "人工调整拆单"),
    ("NO_LOGISTICS", "无可用物流方案", "BLOCK", "manual", "fulfill", "人工指定物流"),
    ("LOGI_SUSPEND", "物流停运", "BLOCK", "manual", "fulfill", "人工指定物流"),
    ("LOGI_UNREACHED", "物流不可达", "BLOCK", "manual", "fulfill", "人工指定物流"),
    # 校验类 → 人工
    ("ABNORMAL_ORDER_STATUS", "订单状态异常", "BLOCK", "manual", "default", "人工审核"),
    ("ORDER_PAUSED", "订单已暂停", "BLOCK", "manual", "default", "人工审核"),
    ("ADDRESS_INVALID", "收货地址不合规", "BLOCK", "manual", "address", "改地址"),
    ("ADDRESS_FORBIDDEN", "收货地区属禁运区", "BLOCK", "manual", "address", "人工审核"),
    ("ADDRESS_FAKE", "疑似虚假地址", "BLOCK", "manual", "address", "人工审核"),
    ("MEMO_HOLD", "买家留言需确认", "BLOCK", "manual", "default", "联系买家"),
    ("GIFT_INVALID", "赠品方案无效", "BLOCK", "manual", "default", "人工审核"),
    ("INVOICE_INVALID", "开票要素缺失", "BLOCK", "manual", "finance", "人工审核"),
    ("GOODS_UNBOUND", "商品未绑定", "BLOCK", "manual", "product", "绑定商品"),
    ("COMBINE_CONFLICT", "合单前提冲突", "BLOCK", "manual", "default", "人工审核"),
    ("ROUTE_LIMIT", "路由次数超限", "BLOCK", "manual", "default", "强制人工"),
    ("DECISION_INCOMPLETE", "决策要素缺失", "BLOCK", "manual", "default", "人工审核"),
    ("PLUGIN_EXCEPTION", "插件执行异常", "BLOCK", "manual", "default", "人工审核"),
    # 复审类 → D03.08
    ("PRICE_ABNORMAL", "价格异常", "BLOCK", "retrial", "finance", "价格复审"),
    ("BIG_AMOUNT", "大额订单", "BLOCK", "retrial", "supervisor", "大额复审"),
    ("BLACKLIST_HIT", "命中黑名单", "BLOCK", "retrial", "risk", "黑名单复审"),
    # 等待类 → 回池
    ("PAY_UNPAID", "未支付", "BLOCK", "pool", "default", "等待支付"),
    ("COMBINE_WAIT", "等待同买家订单到齐", "BLOCK", "pool", "default", "等待合单"),
    ("HOLD_SPECIAL", "特殊单型待放行", "BLOCK", "pool", "default", "等待放行"),
    ("REFUND_PENDING", "退款处理中", "BLOCK", "hold", "after_sale", "等待退款终态"),
    # 提示类 → 不拦截
    ("ADDRESS_SENSITIVE", "地址含敏感词", "WARN", "manual", "address", "人工确认"),
    ("RURAL_AREA_TIP", "乡村件提示", "WARN", "manual", "default", "人工确认"),
    ("MULTI_ADDRESS_TIP", "多地址提示", "WARN", "manual", "default", "人工确认"),
    ("MEMO_TIP", "备注提示", "WARN", "manual", "default", "人工确认"),
]

#: 决策码
DECISION_CODES: list[tuple[str, str]] = [
    ("AUTO_PASS", "自动通过"),
    ("TO_MANUAL", "转人工"),
    ("HOLD", "挂起"),
    ("SHORTAGE", "转缺货流程"),
    ("RETRIAL", "转复审"),
    ("BACK_POOL", "回缓冲池"),
]

#: 建议动作字典
SUGGEST_ACTIONS: list[tuple[str, str]] = [
    ("等补货", "等待补货到仓后重审"),
    ("改地址", "联系买家确认收货地址"),
    ("联系买家", "联系买家确认订单信息"),
    ("人工指定仓库", "人工指定发货仓"),
    ("人工指定物流", "人工指定物流公司"),
    ("人工调整拆单", "人工调整拆单分配"),
    ("复审", "提交复审流程"),
    ("等待支付", "等待买家支付"),
    ("等待合单", "等待同买家订单到齐"),
    ("等待放行", "等待特殊单型放行事件"),
    ("等待退款终态", "等待退款流程终结"),
    ("人工审核", "转人工审核"),
    ("人工确认", "人工确认后放行"),
]


def build_dicts() -> None:
    """注册预置字典到内存"""
    DICTS.register_preset(
        "audit_reason_code",
        [
            DictItem(
                code=code,
                name=name,
                dict_type="audit_reason_code",
                level=level,
                ext={
                    "default_route": route,
                    "audit_group": group,
                    "suggest_action": action,
                },
                sort_no=i * 10,
            )
            for i, (code, name, level, route, group, action) in enumerate(REASON_CODES)
        ],
    )
    DICTS.register_preset(
        "decision_code",
        [
            DictItem(code=c, name=n, dict_type="decision_code", sort_no=i * 10)
            for i, (c, n) in enumerate(DECISION_CODES)
        ],
    )
    DICTS.register_preset(
        "suggest_action",
        [
            DictItem(code=c, name=n, dict_type="suggest_action", sort_no=i * 10)
            for i, (c, n) in enumerate(SUGGEST_ACTIONS)
        ],
    )


# ============ 审单规则预置 ============

#: 缺省规则（系统内置，is_default=1，不可删不可停；autoConfirm=关 → 全转人工）
DEFAULT_RULE = {
    "rule_name": "系统缺省规则（全部转人工）",
    "conditions": {},
    "weight": -9999,
    "plugin_config": {},
    "auto_confirm": 0,
    "pass_action": "manual_confirm",
    "fail_route": {},
    "effective_window": None,
    "exclude_window": None,
    "default_audit_group": None,
    "router_num_limit": 5,
    "status": "enabled",
    "is_default": 1,
}
#: 常用业务规则（weight 高 → 优先命中）
BUSINESS_RULES: list[dict] = [
    {
        "rule_name": "常规单自动审单（实付 < 1000 且无留言）",
        "conditions": {
            "logic": "AND",
            "items": [
                {"dim": "order.amount_paid", "op": "lt", "value": 1000},
                {"dim": "order.has_memo", "op": "is_false", "value": True},
            ],
        },
        "weight": 50,
        "plugin_config": {
            "price_check": {"enable": True, "params": {"max_cost_ratio": 3.0}},
            "address_check": {
                "enable": True,
                "params": {"min_address_len": 5, "sensitive_words": ["代收", "测试", "空号"]},
            },
        },
        "auto_confirm": 1,
        "pass_action": "exec_plan",
        "fail_route": {},
        "default_audit_group": None,
        "router_num_limit": 5,
        "status": "enabled",
        "is_default": 0,
    },
    {
        "rule_name": "大额订单转复审（实付 >= 1000）",
        "conditions": {
            "logic": "AND",
            "items": [
                {"dim": "order.amount_paid", "op": "gte", "value": 1000},
            ],
        },
        "weight": 80,
        "plugin_config": {},
        "auto_confirm": 0,
        "pass_action": "manual_confirm",
        "fail_route": {"BIG_AMOUNT": "retrial"},
        "default_audit_group": None,
        "router_num_limit": 5,
        "status": "enabled",
        "is_default": 0,
    },
    {
        "rule_name": "含买家留言转人工",
        "conditions": {
            "logic": "AND",
            "items": [
                {"dim": "order.has_memo", "op": "is_true", "value": True},
            ],
        },
        "weight": 70,
        "plugin_config": {},
        "auto_confirm": 0,
        "pass_action": "manual_confirm",
        "fail_route": {},
        "default_audit_group": None,
        "router_num_limit": 5,
        "status": "enabled",
        "is_default": 0,
    },
]


async def _seed_carrier_bindings() -> int:
    """仓 ↔ 物流绑定（ful_store_carrier_map）

    logi_match 插件的候选物流来源（D09.04 基础版）。
    P0 策略：给所有启用仓绑定默认承运商（顺丰/中通优先，其余兜底）。
    """
    from sqlalchemy import text

    async with SessionFactory() as s:
        rows = list(
            await s.execute(
                text(
                    "SELECT b.id FROM oms_fulfill.ful_branch b "
                    "WHERE b.is_deleted = 0 AND b.status = 'enabled'"
                )
            )
        )
        branch_ids = [int(r[0]) for r in rows]
        if not branch_ids:
            print("[seed] 无启用仓，跳过仓物流绑定")
            return 0
        carriers = list(
            await s.execute(
                text(
                    "SELECT carrier_code FROM oms_fulfill.ful_carrier "
                    "WHERE carrier_code IN ('SF_CITY','FENGNIAO','DADA','SELF') "
                    "ORDER BY carrier_code LIMIT 4"
                )
            )
        )
        carrier_codes = [r[0] for r in carriers] or ["SF_CITY"]
        n = 0
        for idx, bid in enumerate(branch_ids):
            code = carrier_codes[idx % len(carrier_codes)]
            exists = await s.scalar(
                text(
                    "SELECT id FROM oms_fulfill.ful_store_carrier_map "
                    "WHERE store_branch_id = :bid AND carrier_code = :code LIMIT 1"
                ),
                {"bid": bid, "code": code},
            )
            if exists:
                continue
            await s.execute(
                text(
                    "INSERT INTO oms_fulfill.ful_store_carrier_map "
                    "(tenant_id, owner_id, store_branch_id, carrier_code, "
                    " carrier_store_id, create_time, update_time, version, is_deleted) "
                    "VALUES (1, 0, :bid, :code, :cstore, NOW(3), NOW(3), 0, 0)"
                ),
                {"bid": bid, "code": code, "cstore": f"{code}_001"},
            )
            n += 1
        await s.commit()
        print(f"[seed] 仓物流绑定新增 {n} 条（仓数={len(branch_ids)}，承运商={carrier_codes}）")
        return n


async def _seed_audit_groups() -> int:
    """审核组 + 分派规则预置（D03.03 FR-02a/FR-06a）

    审核组是分派规则的落地载体；组内成员含在班状态与任务上限。
    """
    from app.models.audit import OrdAuditGroup, OrdDispatchRule

    groups: list[dict[str, Any]] = [
        {
            "group_name": "默认审核组",
            "members": [
                {"op_id": 1, "name": "审单员小王", "duty_status": "on", "task_limit": 50},
                {"op_id": 2, "name": "审单员小李", "duty_status": "on", "task_limit": 50},
                {"op_id": 3, "name": "审单员小张", "duty_status": "on", "task_limit": 30},
            ],
            "leader_op_id": 1,
        },
        {
            "group_name": "address",
            "members": [
                {"op_id": 4, "name": "地址处理员", "duty_status": "on", "task_limit": 40},
            ],
            "leader_op_id": 4,
        },
        {
            "group_name": "stock",
            "members": [
                {"op_id": 5, "name": "库存协调员", "duty_status": "on", "task_limit": 40},
            ],
            "leader_op_id": 5,
        },
        {
            "group_name": "risk",
            "members": [
                {"op_id": 6, "name": "风控专员", "duty_status": "on", "task_limit": 30},
            ],
            "leader_op_id": 6,
        },
        {
            "group_name": "supervisor",
            "members": [
                {"op_id": 7, "name": "主管", "duty_status": "on", "task_limit": 80},
            ],
            "leader_op_id": 7,
        },
    ]
    group_ids: dict[str, int] = {}
    n = 0
    async with SessionFactory() as s:
        for g in groups:
            row = await s.scalar(
                select(OrdAuditGroup).where(
                    OrdAuditGroup.group_name == g["group_name"],
                    OrdAuditGroup.is_deleted == 0,
                )
            )
            if row is None:
                row = OrdAuditGroup(**g, status="enabled")
                s.add(row)
                await s.flush()
                n += 1
                print(f"[seed] 新建审核组：{g['group_name']} id={row.id}")
            else:
                row.members = g["members"]
                row.leader_op_id = g["leader_op_id"]
            group_ids[g["group_name"]] = row.id

        # 分派规则（weight DESC 首命中）
        dispatch_rules = [
            {
                "rule_name": "地址类原因 → 地址处理组",
                "conditions": {
                    "logic": "AND",
                    "items": [{"dim": "reason_code", "op": "in",
                              "value": ["ADDRESS_INVALID", "ADDRESS_FORBIDDEN",
                                        "ADDRESS_FAKE"]}],
                },
                "weight": 80,
                "target_group_id": group_ids.get("address", 0),
                "target_op_id": None,
                "strategy": "least_task",
                "filter_on_duty": 1,
                "status": "enabled",
            },
            {
                "rule_name": "缺货类原因 → 库存协调组",
                "conditions": {
                    "logic": "AND",
                    "items": [{"dim": "reason_code", "op": "in", "value": ["STOCK_SHORTAGE", "STOCK_RACE"]}],
                },
                "weight": 75,
                "target_group_id": group_ids.get("stock", 0),
                "target_op_id": None,
                "strategy": "least_task",
                "filter_on_duty": 1,
                "status": "enabled",
            },
            {
                "rule_name": "黑名单/大额 → 主管组",
                "conditions": {
                    "logic": "AND",
                    "items": [{"dim": "reason_code", "op": "in",
                              "value": ["BLACKLIST_HIT", "BIG_AMOUNT",
                                        "PRICE_ABNORMAL"]}],
                },
                "weight": 70,
                "target_group_id": group_ids.get("supervisor", 0),
                "target_op_id": None,
                "strategy": "round_robin",
                "filter_on_duty": 1,
                "status": "enabled",
            },
            {
                "rule_name": "缺省分派 → 默认审核组",
                "conditions": {},
                "weight": -9999,
                "target_group_id": group_ids.get("默认审核组", 0),
                "target_op_id": None,
                "strategy": "least_task",
                "filter_on_duty": 1,
                "status": "enabled",
            },
        ]
        for spec in dispatch_rules:
            row = await s.scalar(
                select(OrdDispatchRule).where(
                    OrdDispatchRule.rule_name == spec["rule_name"],
                    OrdDispatchRule.is_deleted == 0,
                )
            )
            if row is None:
                s.add(OrdDispatchRule(**spec))
                print(f"[seed] 新建分派规则：{spec['rule_name']}")
            else:
                for k, v in spec.items():
                    setattr(row, k, v)
        await s.commit()
    return n


async def _seed_impl() -> None:
    build_dicts()
    async with SessionFactory() as s:
        # ① 字典登记到 DB
        n = await DICTS.sync_to_db(s)
        print(f"[seed] 原因码/决策码/建议动作字典登记：{n} 项")

        # ② 审单规则（幂等：按 rule_name 判重；缺省规则按 is_default 判重）
        for spec in [DEFAULT_RULE, *BUSINESS_RULES]:
            if spec.get("is_default"):
                row = await s.scalar(
                    select(OrdAuditRule).where(
                        OrdAuditRule.is_default == 1, OrdAuditRule.is_deleted == 0
                    )
                )
            else:
                row = await s.scalar(
                    select(OrdAuditRule).where(
                        OrdAuditRule.rule_name == spec["rule_name"],
                        OrdAuditRule.is_deleted == 0,
                    )
                )
            if row is None:
                s.add(OrdAuditRule(**spec))
                print(f"[seed] 新建审单规则：{spec['rule_name']}")
            else:
                # 唯一键 uk_ord_audit_rule_name：同名即冲突（历史遗留的重复缺省规则改名）
                if row.rule_name != spec["rule_name"] and spec.get("is_default"):
                    row.rule_name = f"{spec['rule_name']}（历史{row.id}）"
                for k, v in spec.items():
                    if k == "rule_name" and row.rule_name != v:
                        continue
                    setattr(row, k, v)
                print(f"[seed] 审单规则已存在（更新）：{row.rule_name}")
        # 清理历史遗留的重复缺省规则（is_default=1 只允许一条）
        dup = list(
            await s.scalars(
                select(OrdAuditRule).where(
                    OrdAuditRule.is_default == 1, OrdAuditRule.is_deleted == 0
                )
            )
        )
        if len(dup) > 1:
            for d in dup[1:]:
                print(f"[seed] 清理重复缺省规则 id={d.id}（{d.rule_name}）")
                await s.delete(d)
        await s.commit()
        print("[seed] 完成")

    # ③ 仓物流绑定（审单链 logi_match 的候选来源）
    await _seed_carrier_bindings()
    # ④ 审核组 + 分派规则
    await _seed_audit_groups()


async def seed() -> None:
    """豁免通道登记点⑧：系统级初始化脚本（无用户上下文，fail-closed 下需显式豁免）"""
    with without_data_scope():
        await _seed_impl()


if __name__ == "__main__":
    async def _main():
        await seed()
        await engine.dispose()

    asyncio.run(_main())
