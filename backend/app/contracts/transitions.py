"""状态机流转表契约 —— 状态迁移的唯一权威

⚠ **手写文件**（DDL 里没有流转信息，权威源是 SRS §5.1 流转表）。
   每个键必须是一个 `schema.table.column`，且其下用**中文标签**表示状态；
   `tools/check_contract_ddl.py` 会校验标签确实存在于该列的 DDL 枚举里
   —— **DDL 加了状态而这里没加 → 立即失败**。

收录范围
--------
已收录：售后申请单 / 售后退款单 / 应急批次阶段（P0）
待抽取：发货单四指令状态机、异常单状态机
  —— 这两处当前是**内联实现**（`transit()` 里直接判 `INVALID_TRANSITION`），
  非表驱动，需在 P3 巨型 service 拆分时一并抽成表驱动
  （否则「非法流转」判定与契约无法互校）。
"""
from __future__ import annotations

from typing import Final

#: 售后申请单状态机（SRS-D05.01 §5.1 权威流转表）
AFT_RETURN_APPLY_TRANSITIONS: Final[dict[str, tuple[str, ...]]] = {
    "待关联": ("待审核", "关闭"),
    "待审核": ("待退货", "退款中", "换货执行中", "拒绝", "关闭"),
    "拒绝": ("待审核",),
    "待退货": ("待收货",),
    "待收货": ("待退款",),
    "待退款": ("完成", "关闭"),
    "退款中": ("完成", "关闭"),
    "换货执行中": ("完成", "关闭"),
    "完成": (),
    "关闭": (),
}

#: 售后退款单状态机（SRS-D05.03 §5.1）
AFT_REFUND_TRANSITIONS: Final[dict[str, tuple[str, ...]]] = {
    "待退款": ("退款中", "已取消"),
    "退款中": ("已退款", "退款失败", "已退款-线下"),
    "退款失败": ("退款中",),
    "已退款": (),      # 吸收态，不回退
    "已退款-线下": (),  # 吸收态，不回退
    "已取消": (),
}

#: 应急批次阶段推进（SRS-D03.09 FR-05c：不可跳、不可回退）
ORD_OVERSOLD_BATCH_STAGE_FLOW: Final[tuple[str, ...]] = (
    "alarm",
    "alloc_calc",
    "negotiate",
    "refund",
    "compensate",
    "review",
)

#: 流转表索引：`schema.table.column` → {状态标签: 允许迁移到的标签}
TRANSITIONS: Final[dict[str, dict[str, tuple[str, ...]]]] = {
    "oms_aftersale.aft_return_apply.status": AFT_RETURN_APPLY_TRANSITIONS,
    "oms_aftersale.aft_refund.status": AFT_REFUND_TRANSITIONS,
}
