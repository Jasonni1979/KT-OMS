"""W6 履约域种子数据（分仓规则 + 拆单规则 + 审核组）

幂等：按规则名判重，重复执行不产生重复数据。

用法：
    cd backend && .venv/bin/python -m app.scripts.seed_fulfill
"""
from __future__ import annotations

import asyncio
import sys
from typing import Any

from sqlalchemy import select

from app.core.db import AuthContext, SessionFactory, engine, set_auth_context
from app.models.fulfill import OrdBranchDispatchRule, OrdSplitRule
from app.modules.m1_master.service.master import get_redis
from app.modules.m4_fulfill.service.split_service import SplitRuleService

#: 分仓规则（ord_branch_dispatch_rule）
DISPATCH_RULES: list[dict[str, Any]] = [
    {
        "rule_name": "缺省兜底（店铺绑定仓优先级）",
        "conditions": {"logic": "AND", "items": []},
        "strategy_type": "binding_priority",
        "branch_seq": None,
        "weight": -9999,
        "default_flag": 1,
        "status": "enabled",
    },
    {
        "rule_name": "华东仓优先（区域路由）",
        "conditions": {
            "logic": "AND",
            "items": [{"dim": "receiver_province", "op": "eq", "value": "上海市"}],
        },
        "strategy_type": "region_route",
        "branch_seq": None,
        "weight": 80,
        "default_flag": 0,
        "status": "enabled",
    },
    {
        "rule_name": "华南订单走品牌代销仓（货主指定仓）",
        "conditions": {
            "logic": "AND",
            "items": [{"dim": "receiver_city", "op": "eq", "value": "深圳市"}],
        },
        "strategy_type": "owner_assign",
        "branch_seq": None,
        "weight": 70,
        "default_flag": 0,
        "status": "enabled",
    },
    {
        "rule_name": "大促期库存深度优先",
        "conditions": {
            "logic": "AND",
            "items": [{"dim": "order_type", "op": "eq", "value": "promotion"}],
        },
        "strategy_type": "stock_depth",
        "branch_seq": None,
        "weight": 90,
        "effective_period": {"start": "00:00", "end": "23:59"},
        "default_flag": 0,
        "status": "enabled",
    },
]


async def _seed_dispatch_rules(s) -> int:
    """分仓规则种子"""
    n = 0
    for spec in DISPATCH_RULES:
        row = await s.scalar(
            select(OrdBranchDispatchRule).where(
                OrdBranchDispatchRule.rule_name == spec["rule_name"],
                OrdBranchDispatchRule.is_deleted == 0,
            )
        )
        if row is None:
            s.add(OrdBranchDispatchRule(**spec))
            print(f"[seed] 新建分仓规则：{spec['rule_name']}")
            n += 1
        else:
            for k, v in spec.items():
                setattr(row, k, v)
            print(f"[seed] 分仓规则已存在（更新）：{spec['rule_name']}")
    await s.commit()
    return n


async def _seed_split_rules(s) -> int:
    """拆单规则种子（走 SplitRuleService.save → 保存期校验生效）"""
    svc = SplitRuleService(s)
    specs = [
        {
            "owner_id": 0,
            "rule_name": "W6按货主拆单（凯淳核心）",
            "split_type": "owner",
            "split_config": {},
            "scope_type": "global",
            "confirm_source": "all",
            "status": "enabled",
        },
        {
            "owner_id": 0,
            "rule_name": "W6按仓库拆单",
            "split_type": "branch",
            "split_config": {},
            "scope_type": "global",
            "confirm_source": "all",
            "status": "enabled",
        },
        {
            "owner_id": 0,
            "rule_name": "W6按货主+按仓级联",
            "split_type": "owner",
            "split_config": {},
            "split_type_2": "branch",
            "split_config_2": {},
            "scope_type": "global",
            "confirm_source": "all",
            "status": "enabled",
        },
        {
            "owner_id": 0,
            "rule_name": "W6按库存深度拆单",
            "split_type": "stock_depth",
            "split_config": {"allow_partial": True},
            "scope_type": "global",
            "confirm_source": "all",
            "status": "enabled",
        },
    ]
    n = 0
    for spec in specs:
        exists = await s.scalar(
            select(OrdSplitRule).where(
                OrdSplitRule.rule_name == spec["rule_name"],
                OrdSplitRule.is_deleted == 0,
            )
        )
        if exists is not None:
            print(f"[seed] 拆单规则已存在：{spec['rule_name']}")
            continue
        try:
            await svc.save(spec)
            print(f"[seed] 新建拆单规则：{spec['rule_name']}")
            n += 1
        except Exception as e:
            print(f"[seed] 拆单规则保存失败 {spec['rule_name']}：{e}")
    return n


async def main() -> int:
    set_auth_context(AuthContext(tenant_id=1, is_superuser=True))
    redis = await get_redis()
    del redis
    async with SessionFactory() as s:
        n1 = await _seed_dispatch_rules(s)
        n2 = await _seed_split_rules(s)
    print(f"[seed] 完成：分仓规则 {n1} 条，拆单规则 {n2} 条")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
