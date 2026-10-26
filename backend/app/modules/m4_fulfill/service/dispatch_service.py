"""配货分仓引擎（D03.06）

**定位**：分仓**决策器**——回答「这张订单的货从哪个（些）仓发」。
决策与执行分离：输出不可变 plan（行→仓→分配量），不做任何库存承诺，
由审单链路（D03.02）拿 plan 去预占（D04.03）、拆单（D03.04）、出发货单（D03.07）。

**核心流程**（§4.1 决策树）：
```
① 平台指定仓 store_code？→ 锁定唯一候选（校验存在且营业），不换仓
② 候选仓生成（按序合并去重 + 硬过滤）：
   货主仓属限定（行级硬过滤）> 店铺绑定仓（优先级）> 区域路由命中仓 > 全局兜底仓
③ 一次批量预取三元可用量（SKU × 候选仓 × 行货主）
④ 规则引擎命中（weight DESC 首个全命中）→ 候选仓按策略排序
⑤ 满足度计算：首个满足率=100% → 整仓 plan
   否则贪心多仓组合 → 多仓 plan（split_required=true）
   否则缺货判定 → lack plan（缺口明细 + 缺货路径编排）
⑥ plan 落库（轮次追加，旧轮次 superseded）+ 路由决策埋点
```

**关键契约**：
- 三元口径（仓×SKU×货主）——FR-03a，行货主的可用量，不是货主总量
- 硬过滤不可被手工绕过（货主仓属）——FR-06b
- 满足度快照是时点值，预占才是最终裁决——FR-03c
- plan 不可变、按轮次追加——FR-05a

⚠ 本文件在 P3（上下文体积治理）中拆分为多个文件；
   此处保留 re-export，**原有 import 路径全部保持可用**。
"""

from __future__ import annotations

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.modules.m4_fulfill.service.dispatch_candidate import DispatchCandidateMixin
from app.modules.m4_fulfill.service.dispatch_decide import DispatchDecideMixin
from app.modules.m4_fulfill.service.dispatch_models import (
    FAIL_FULL_LACK,
    FAIL_NO_CANDIDATE_BRANCH,
    FAIL_PARTIAL_LACK,
    MODE_APPOINTED,
    MODE_LACK,
    MODE_MULTI,
    MODE_SINGLE,
    STRATEGY_BINDING_PRIORITY,
    STRATEGY_OWNER_ASSIGN,
    STRATEGY_REGION_ROUTE,
    STRATEGY_ROUND_ROBIN,
    STRATEGY_STOCK_DEPTH,
    BranchCandidate,
    DispatchResult,
    _in_window,  # noqa: F401
    period_match,
)
from app.modules.m4_fulfill.service.dispatch_rule import DispatchRuleMixin

__all__ = [
    "MODE_SINGLE",
    "MODE_MULTI",
    "MODE_LACK",
    "MODE_APPOINTED",
    "STRATEGY_BINDING_PRIORITY",
    "STRATEGY_REGION_ROUTE",
    "STRATEGY_STOCK_DEPTH",
    "STRATEGY_OWNER_ASSIGN",
    "STRATEGY_STORE_O2O",
    "STRATEGY_ROUND_ROBIN",
    "FAIL_NO_CANDIDATE_BRANCH",
    "FAIL_PARTIAL_LACK",
    "FAIL_FULL_LACK",
    "BranchCandidate",
    "DispatchResult",
    "DispatchService",
    "period_match",
]


logger = get_logger("dispatch")

STRATEGY_STORE_O2O = "store_o2o"      # P1（M3 交付）

class DispatchService(DispatchCandidateMixin, DispatchRuleMixin, DispatchDecideMixin):
    """分仓服务（D03.06 FR-02/03/04/05/06）"""

    def __init__(self, session: AsyncSession, redis: Redis):
        self.s = session
        self.r = redis
