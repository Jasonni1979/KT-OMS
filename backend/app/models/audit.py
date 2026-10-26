"""审单域 ORM 模型（D03.02 审单引擎 + D03.03 人工审单工作台）

覆盖：
- ord_audit_rule          审单规则（条件层/插件层/动作层三层模型）
- ord_audit_reason        结构化审核原因（替代商派位标记）
- ord_fulfill_plan        履约方案（决策执行分离的载体）
- ord_audit_plugin_perf   插件级耗时日志
- ord_audit_batch_log     批次日志
- ord_audit_task          审单任务（人工队列）
- ord_audit_group         审核组
- ord_audit_work_log      审单作业日志（绩效统计源）
- ord_dispatch_rule       分派规则

按真实 DDL 映射；缺列不映射。
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


class OrdAuditRule(Base, TimestampMixin, TenantMixin, VersionMixin):
    """审单规则（D03.02 FR-03a 三层模型）

    条件层：conditions（18 维 DSL JSON，AND 组合）
    插件层：plugin_config（逐插件 enable/params 覆盖）
    动作层：auto_confirm / pass_action / fail_route / effective_window / exclude_window
    """

    __tablename__ = "ord_audit_rule"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    owner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    conditions: Mapped[Any] = mapped_column(JSON, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    plugin_config: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    auto_confirm: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    pass_action: Mapped[str] = mapped_column(String(32), nullable=False, default="exec_plan")
    fail_route: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    effective_window: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    exclude_window: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    default_audit_group: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    router_num_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="enabled")
    is_default: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class OrdAuditReason(Base, TenantMixin):
    """结构化审核原因（D03.02 FR-04a：替代商派 auto_status 位标记）

    每次审单写 0..N 条：插件名/原因码/级别(BLOCK|WARN)/描述(含数据快照)/
    建议动作/决策明细 JSON/路由结果。
    注：DDL 只有 create_time（无 update_time/version/is_deleted）→ 追加型表。
    """

    __tablename__ = "ord_audit_reason"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    batch_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    plugin_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    level: Mapped[str] = mapped_column(String(8), nullable=False, default="BLOCK")
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    detail: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    suggest_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    route_target: Mapped[str | None] = mapped_column(String(16), nullable=True)
    handle_status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    handle_way: Mapped[str | None] = mapped_column(String(64), nullable=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default="CURRENT_TIMESTAMP(3)", nullable=False
    )


class OrdFulfillPlan(Base, TimestampMixin, TenantMixin, VersionMixin):
    """履约方案 plan（D03.02 FR-05a：决策执行分离的载体）

    四要素：仓库分配 / 拆单方案 / 物流方案 / 合单组
    溯源：plan_version / rule_snapshot_id / plugin_trace / decision_by / decision_time
    状态：plan_status（draft/pending/executing/success/failed/discarded）
          exec_status（waiting/running/success/failed/compensated）
    """

    __tablename__ = "ord_fulfill_plan"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    plan_bn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    order_ids: Mapped[Any] = mapped_column(JSON, nullable=False)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    warehouse_alloc: Mapped[Any] = mapped_column(JSON, nullable=False)
    split_matrix: Mapped[Any] = mapped_column(JSON, nullable=False)
    logistics_alloc: Mapped[Any] = mapped_column(JSON, nullable=False)
    combine_group: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    rule_snapshot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plugin_trace: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    decision_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    decision_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    plan_status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    exec_status: Mapped[str] = mapped_column(String(16), nullable=False, default="waiting")
    delivery_ids: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    fail_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    brand_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class OrdAuditPluginPerf(Base, TenantMixin):
    """插件级耗时日志（D03.02 FR-01e：TOP 慢插件分析与 SLA 告警）

    注：追加型日志表，DDL 无 update_time/version/is_deleted。
    """

    __tablename__ = "ord_audit_plugin_perf"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    plugin_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    phase: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    cost_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    reason_codes: Mapped[str | None] = mapped_column(String(512), nullable=True)
    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default="CURRENT_TIMESTAMP(3)", nullable=False
    )


class OrdAuditBatchLog(Base, TenantMixin):
    """审单批次日志（D03.02 FR-06c：批次规模/结果分布/总耗时）

    注：追加型日志表，DDL 无 update_time/version/is_deleted。
    """

    __tablename__ = "ord_audit_batch_log"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    batch_no: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    group_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    order_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_dist: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    total_cost_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default="CURRENT_TIMESTAMP(3)", nullable=False
    )


class OrdAuditGroup(Base, TimestampMixin, TenantMixin, VersionMixin):
    """审核组（D03.03 FR-06a：组名/归属组织/成员/组长）

    注：DDL 无 owner_id 列 → 仅 tenant 维隔离。
    """

    __tablename__ = "ord_audit_group"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    group_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    org_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    leader_op_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    default_shop_scope: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    members: Mapped[Any] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="enabled")


class OrdAuditTask(Base, TimestampMixin, TenantMixin, VersionMixin):
    """审单任务（D03.03 §6.3：一单一活跃任务；驳回重提生成新任务，历史留档）"""

    __tablename__ = "ord_audit_task"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    batch_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    assign_group: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    assign_op: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    assign_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    assign_way: Mapped[str | None] = mapped_column(String(16), nullable=True)
    task_status: Mapped[str] = mapped_column(String(16), nullable=False, default="wait_assign")
    lock_op: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    lock_expire: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    overtime_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result: Mapped[str | None] = mapped_column(String(16), nullable=True)
    result_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plan_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    is_active: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)


class OrdAuditWorkLog(Base, TenantMixin):
    """审单作业日志（D03.03 FR-07b：绩效统计源；分派/通过/驳回/转派埋点）

    注：DDL 只有 create_time（无 update_time/version/is_deleted）→ 追加型表。
    """

    __tablename__ = "ord_audit_work_log"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    task_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    op_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    action: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    from_op: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    to_op: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    batch_flag: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    memo: Mapped[str | None] = mapped_column(String(256), nullable=True)
    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default="CURRENT_TIMESTAMP(3)", nullable=False
    )


class OrdDispatchRule(Base, TimestampMixin, TenantMixin, VersionMixin):
    """分派规则（D03.03 FR-02a：多维规则分派，weight DESC 首命中）

    注：DDL 无 owner_id 列 → 仅 tenant 维隔离。
    """

    __tablename__ = "ord_dispatch_rule"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    conditions: Mapped[Any] = mapped_column(JSON, nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    target_group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    target_op_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    strategy: Mapped[str] = mapped_column(String(16), nullable=False, default="round_robin")
    filter_on_duty: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="enabled")


class OrdRetrial(Base, TimestampMixin, TenantMixin, VersionMixin):
    """复审单（D03.08 改单复审 / D03.09 FR-02d 转复审动作的载体）

    本期由异常单动作 `to_retrial` 落单；D03.08 的改单执行链路在 W8-3 落地。
    """

    __tablename__ = "ord_retrial"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    #: 货主（DDL NOT NULL 无默认值 → 显式声明，INSERT 必填）
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    retrial_bn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: 复审单关联的改单单号（D03.08）
    modify_bn: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: abnormal（异常单转复审）/ modify（改单触发）…
    retrial_type: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    #: wait / processing / approved / rejected
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="wait")
    hit_detail: Mapped[Any] = mapped_column(JSON, nullable=True)
    snapshot_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    assign_group: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    assign_op: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    handle_opinion: Mapped[str | None] = mapped_column(String(512), nullable=True)
    handle_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    handle_op: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    brand_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
