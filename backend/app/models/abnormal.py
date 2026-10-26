"""异常单域 ORM 模型（SRS-D03.09 异常单与缺货处理）

三张表：
- `ord_abnormal_type_dict` 异常类型字典（FR-01a/FR-01b：分类/默认处理组/默认SLA/
  是否需异常单化/是否阻断履约/可用动作集/原因码映射）
- `ord_abnormal` 异常单主表（FR-02b 状态机 + FR-02c 分派 + FR-02d 动作 + 时间线）
- `ord_stockout` 缺货明细（FR-04a：三元键 branch×bm×owner + 缺口量 + 库存快照；
  FR-04b 策略链执行状态与结果；FR-05a 超卖标记）

状态机（FR-02b）：wait_dispatch → assigned → processing → resolved / cancelled / suspended
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Integer,
    SmallInteger,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, VersionMixin

# ============ 异常单状态机（FR-02b）============

ABNORMAL_STATUS_WAIT_DISPATCH = "wait_dispatch"  # 待分派
ABNORMAL_STATUS_ASSIGNED = "assigned"            # 已分派
ABNORMAL_STATUS_PROCESSING = "processing"        # 处理中
ABNORMAL_STATUS_RESOLVED = "resolved"            # 已解决
ABNORMAL_STATUS_CANCELLED = "cancelled"          # 已取消
ABNORMAL_STATUS_SUSPENDED = "suspended"          # 已挂起（等外部条件）

#: 状态机允许的流转（FR-02b）
ABNORMAL_TRANSITIONS: dict[str, tuple[str, ...]] = {
    ABNORMAL_STATUS_WAIT_DISPATCH: (ABNORMAL_STATUS_ASSIGNED, ABNORMAL_STATUS_CANCELLED),
    ABNORMAL_STATUS_ASSIGNED: (
        ABNORMAL_STATUS_PROCESSING,
        ABNORMAL_STATUS_SUSPENDED,
        ABNORMAL_STATUS_CANCELLED,
        ABNORMAL_STATUS_RESOLVED,
    ),
    ABNORMAL_STATUS_PROCESSING: (
        ABNORMAL_STATUS_RESOLVED,
        ABNORMAL_STATUS_SUSPENDED,
        ABNORMAL_STATUS_CANCELLED,
    ),
    ABNORMAL_STATUS_SUSPENDED: (
        ABNORMAL_STATUS_PROCESSING,
        ABNORMAL_STATUS_ASSIGNED,
        ABNORMAL_STATUS_RESOLVED,
        ABNORMAL_STATUS_CANCELLED,
    ),
    ABNORMAL_STATUS_RESOLVED: (),
    ABNORMAL_STATUS_CANCELLED: (),
}

#: 异常分类（FR-01a）
ABNORMAL_CATEGORY_DATA = "data"        # 数据类
ABNORMAL_CATEGORY_RISK = "risk"        # 风控类
ABNORMAL_CATEGORY_STOCK = "stock"      # 库存类
ABNORMAL_CATEGORY_FULFILL = "fulfill"  # 履约类
ABNORMAL_CATEGORY_PLATFORM = "platform"  # 平台类
ABNORMAL_CATEGORY_OTHER = "other"      # 其他（未映射原因码兜底，FR-01c）


class OrdReasonCodeDict(Base, TimestampMixin, TenantMixin):
    """审单原因码字典（D03.02 产出 · FR-01c 映射的**权威来源**）

    `exc_type` 列 = 该原因码映射到的异常类型（LFK → ord_abnormal_type_dict.type_code）；
    `need_abnormal_bill=1` 的类型才自动落异常单（FR-03a）。
    """

    __tablename__ = "ord_reason_code_dict"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # ⚠ 该表**无 is_deleted 列**（DDL 只有 disabled 启停）——写多一列必报错
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    reason_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    #: 产出插件（与 ord_audit_reason.plugin_name 同域）
    plugin_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    #: BLOCK 拦截 / WARN 提示
    level: Mapped[str] = mapped_column(String(8), nullable=False, default="BLOCK")
    #: manual 人工 / shortage 缺货 / retrial 复审 / requeue 回池 / suspend 挂起
    default_route: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    #: change_branch 换仓 / modify_address 改地址 / contact_buyer 联系买家 …
    default_suggest: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: 映射的异常类型（NULL = 不落异常单）
    exc_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    is_system: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    disabled: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class OrdAbnormalTypeDict(Base, TimestampMixin, TenantMixin):
    """异常类型字典（FR-01a/FR-01b/FR-01c）"""

    __tablename__ = "ord_abnormal_type_dict"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    type_code: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    type_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    default_group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    default_sla_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=24)
    #: 是否需异常单化（FR-03a：仅「是」的原因码才落异常单，避免异常池泛滥）
    need_abnormal_bill: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    #: 是否阻断履约（FR-01a）
    block_fulfill: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    #: 可用动作集（FR-02d：JSON 数组）
    action_set: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    #: 原因码 → 异常类型映射（FR-01c：JSON 字典，键=原因码，值=type_code）
    reason_code_map: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    #: 系统内置类型不可删（FR-01a）
    is_system: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    disabled: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class OrdAbnormal(Base, TimestampMixin, TenantMixin, VersionMixin):
    """异常单（FR-02a 创建来源 / FR-02b 状态机 / FR-02c 分派 / FR-02d 动作）"""

    __tablename__ = "ord_abnormal"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    abnormal_bn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    order_bn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    #: 异常类型编码（关联 ord_abnormal_type_dict.type_code）
    exc_type: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    exc_category: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    #: 创建来源（FR-02a）：audit / freeze / push / writeback / manual / relink
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    #: 来源引用（如审单原因码、失败单号、事件 ID）
    source_ref: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    #: 原因明细（JSON）
    reason_detail: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ABNORMAL_STATUS_WAIT_DISPATCH, index=True
    )
    #: 处理组（分派目标，FR-02c）
    group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: 处理人（FR-02c）
    op_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    dispatch_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: SLA 截止（FR-01a 默认 SLA 小时数推导）
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    escalate_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    #: 解决动作（FR-02d：re_audit / cancel / suspend / to_aftersale / force_pass）
    resolve_action: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    rel_retrial_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    rel_refund_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    rel_delivery_ids: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    #: 挂起到期（FR-02d：挂起须填预计恢复时间）
    suspend_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: 时间线（FR-02b：操作人/动作/备注/前后状态）
    timeline: Mapped[Any | None] = mapped_column(JSON, nullable=True)


class OrdStockout(Base, TimestampMixin, TenantMixin, VersionMixin):
    """缺货明细（FR-04a 缺货标记 / FR-04b 策略链 / FR-05a 超卖识别）"""

    __tablename__ = "ord_stockout"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: 关联异常单（FR-04a：缺货明细挂在缺货异常单下）
    abnormal_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    #: 三元键：仓 × 基础物料 × 货主
    branch_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: 缺口量
    lack_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: 缺货时点库存快照（JSON）
    stock_snapshot: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    #: 策略链状态（wait_calc → running → done / skipped）
    strategy_status: Mapped[str] = mapped_column(String(16), nullable=False, default="wait_calc")
    #: 策略链结果（JSON：换仓候选/借调建议/拆单建议…）
    strategy_result: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    #: 承诺到货时间（FR-04b 借调/采购建议）
    promise_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: 超卖标记（FR-05a：平台已成交但 OMS 无货 → SLA 更短、告警级别更高）
    oversold_flag: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    batch_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    negotiate_record: Mapped[Any | None] = mapped_column(JSON, nullable=True)
