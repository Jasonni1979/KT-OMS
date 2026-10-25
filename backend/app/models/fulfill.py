"""履约域 ORM 模型（W6：D03.06 配货分仓 + D03.04 拆单 + D03.07 发货单）

覆盖：
- ord_dispatch_plan            分仓方案（不可变决策记录，按轮次追加）
- ord_branch_dispatch_rule     选仓分仓规则（条件→仓序）
- ord_branch_change_log        手工改仓记录（敏感操作审计）
- ord_routing_decision_log     路由决策日志（DOM 埋点，训练数据地基）
- ord_split_rule               拆单策略规则（含级联配置）
- ord_split_trace              拆分追溯轨迹（只增）
- ord_delivery                 发货单头（指令状态机载体）
- ord_delivery_item            发货单行（行内货主唯一）
- ord_delivery_item_detail     发货单行↔订单行明细溯源
- ord_delivery_package         发货单包裹（出库回传落库）
- ord_delivery_log             发货单状态流转日志（只增）
- ord_delivery_diff            发货单实发差异登记

按真实 DDL 映射；缺列不映射。日志/轨迹类表为追加型（无 update_time/version/is_deleted）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Integer,
    Numeric,
    SmallInteger,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, VersionMixin
from app.models.gateway import mysql_blob

# ==================== D03.06 配货分仓 ====================


class OrdDispatchPlan(Base, TenantMixin):
    """分仓方案（D03.06 FR-05a：不可变决策记录）

    决策与执行分离：plan 只表达「行→仓→分配量」，不做任何库存承诺。
    消费方：审单引擎（挂入履约方案）、拆单 branch/stock_depth 策略、
    预占（仓维度）、发货单（branch_id 溯源）。

    注：追加型表，DDL 无 update_time/version/is_deleted（只增不改）。
    """

    __tablename__ = "ord_dispatch_plan"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    round_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    #: 行级分配 JSON：{order_item_id: {branch_id: qty}}
    alloc: Mapped[Any] = mapped_column(JSON, nullable=False)
    #: single 整仓 / multi 多仓 / lack 缺货 / appointed 指定仓
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="single")
    split_required: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    #: 满足度快照（各候选仓满足率/可用量明细）
    fulfill_snapshot: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    #: 缺货明细（行/SKU/缺口/候选分布）
    lack_detail: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    #: 规则命中记录（规则ID/策略类型/仓序）
    rule_hit: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    #: auto / retry / manual / platform
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")
    #: effective / superseded
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="effective")
    lack_route: Mapped[str | None] = mapped_column(String(16), nullable=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default="CURRENT_TIMESTAMP(3)", nullable=False
    )


class OrdBranchDispatchRule(Base, TimestampMixin, TenantMixin, VersionMixin):
    """选仓分仓规则（D03.06 FR-02a：条件→仓序）

    条件维度：店铺/平台/收货区域/订单类型/货主/物料分类/重量体积/标签
    输出：候选仓优先级序列（branch_seq）+ 选仓策略类型（strategy_type）
    """

    __tablename__ = "ord_branch_dispatch_rule"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    owner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    conditions: Mapped[Any] = mapped_column(JSON, nullable=False)
    #: binding_priority/region_route/stock_depth/owner_assign/store_o2o/round_robin
    strategy_type: Mapped[str] = mapped_column(String(32), nullable=False, default="binding_priority")
    #: 候选仓优先级序列 JSON：[branch_id, ...]
    branch_seq: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    effective_period: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    exclude_period: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    default_flag: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="enabled")


class OrdBranchChangeLog(Base, TenantMixin):
    """手工改仓记录（D03.06 FR-06c：敏感操作审计）

    注：追加型表，DDL 无 update_time/version/is_deleted。
    """

    __tablename__ = "ord_branch_change_log"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    plan_round: Mapped[int | None] = mapped_column(Integer, nullable=True)
    old_branch: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    new_branch: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    old_fulfill: Mapped[Any | None] = mapped_column(Numeric(9, 4), nullable=True)
    new_fulfill: Mapped[Any | None] = mapped_column(Numeric(9, 4), nullable=True)
    reason: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    forced: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recall_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operator: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default="CURRENT_TIMESTAMP(3)", nullable=False
    )


class OrdRoutingDecisionLog(Base, TenantMixin):
    """路由决策日志（D03.06 FR-08a：DOM 埋点，算法寻源数据地基）

    每次分仓决策记录完整特征快照：候选仓集合/各仓特征/命中规则/最终选仓/耗时。
    注：只增表，DDL 无 update_time/version/is_deleted。
    """

    __tablename__ = "ord_routing_decision_log"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    round_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    candidate_branches: Mapped[Any] = mapped_column(JSON, nullable=False)
    branch_features: Mapped[Any] = mapped_column(JSON, nullable=False)
    rule_hit: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    chosen_branch: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: 拆单 vs 等货 vs 调拨成本对比（FR-08b）
    cost_compare: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    #: rule（规则式）/ algo（算法式，P2 预留）
    decision_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="rule")
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default="CURRENT_TIMESTAMP(3)", nullable=False
    )


# ==================== D03.04 拆单 ====================


class OrdSplitRule(Base, TimestampMixin, TenantMixin, VersionMixin):
    """拆单策略规则（D03.04 FR-01c）

    一级策略 split_type + split_config；二三级级联 split_type_2/3（FR-04a）。
    配置在保存期经策略 validateConfig 预校验（配置错误暴露在保存期而非运行期）。
    """

    __tablename__ = "ord_split_rule"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    rule_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    split_type: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    split_config: Mapped[Any] = mapped_column(JSON, nullable=False)
    split_type_2: Mapped[str | None] = mapped_column(String(32), nullable=True)
    split_config_2: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    split_type_3: Mapped[str | None] = mapped_column(String(32), nullable=True)
    split_config_3: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    #: global / shop / order_group
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, default="global")
    scope_ref: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    #: auto / manual / all
    confirm_source: Mapped[str] = mapped_column(String(16), nullable=False, default="all")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="enabled")


class OrdSplitTrace(Base, TenantMixin):
    """拆分追溯轨迹（D03.04 FR-08a：每轮拆单一条，不可变只追加）

    含规则快照（策略链+各级 config）/输入明细快照/输出分组结果/耗时/来源。
    注：追加型表，DDL 无 update_time/version/is_deleted。
    """

    __tablename__ = "ord_split_trace"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    round_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    split_rule_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    rule_snapshot: Mapped[Any] = mapped_column(JSON, nullable=False)
    input_snapshot: Mapped[Any] = mapped_column(JSON, nullable=False)
    group_result: Mapped[Any] = mapped_column(JSON, nullable=False)
    #: auto / manual
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")
    result_status: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    delivery_ids: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    err_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    err_detail: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    cost_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    operator: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default="CURRENT_TIMESTAMP(3)", nullable=False
    )


# ==================== D03.07 发货单 ====================


class OrdDelivery(Base, TimestampMixin, TenantMixin, VersionMixin):
    """发货单头（D03.07 FR-01a/FR-02a：指令状态机载体）

    状态枚举（§4.1 权威）：
    draft → pushed → processing → outbound → shipped → finished
    分支：push_failed / recalling / recalled / rejected / cancelled / partial_outbound
    """

    __tablename__ = "ord_delivery"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    delivery_bn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    #: 合单场景：一发货单多订单（多对多关联的轻量表达）
    order_ids: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    combine_group_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    #: init / running / succ / fail / none（无需推仓）
    sync_status: Mapped[str] = mapped_column(String(16), nullable=False, default="init")
    sync_msg: Mapped[str | None] = mapped_column(String(512), nullable=True)
    branch_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    wms_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    wms_bill_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    logi_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    logi_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 母子单：母单 is_bind=1，子单 parent_id=母单
    is_bind: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    parent_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: 虚拟发货单（免推仓直发）
    is_virtual: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    #: 暂缓推仓（预售）
    hold_flag: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    hold_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    receiver_name_enc: Mapped[bytes | None] = mapped_column(mysql_blob(), nullable=True)
    receiver_mobile_enc: Mapped[bytes | None] = mapped_column(mysql_blob(), nullable=True)
    receiver_address_enc: Mapped[bytes | None] = mapped_column(mysql_blob(), nullable=True)
    receiver_cipher: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    weight: Mapped[Any | None] = mapped_column(Numeric(18, 4), nullable=True)
    volume: Mapped[Any | None] = mapped_column(Numeric(18, 4), nullable=True)
    est_freight: Mapped[Any | None] = mapped_column(Numeric(18, 2), nullable=True)
    #: 溯源：分仓方案 ID / 拆单轨迹 ID
    plan_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    split_trace_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")
    delivery_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finish_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    memo: Mapped[str | None] = mapped_column(String(512), nullable=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    brand_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class OrdDeliveryItem(Base, TimestampMixin, TenantMixin, VersionMixin):
    """发货单行（D03.07 FR-01a/FR-05b）

    行内货主唯一（FR-01b 落库强约束）；settled_num=已核销量（出库累计）。
    """

    __tablename__ = "ord_delivery_item"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    delivery_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    bm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bm_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sm_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    settled_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    lend_flag: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    lend_ledger_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    price: Mapped[Any | None] = mapped_column(Numeric(18, 4), nullable=True)
    memo: Mapped[str | None] = mapped_column(String(256), nullable=True)


class OrdDeliveryItemDetail(Base, TenantMixin):
    """发货单行↔订单行明细溯源（D03.07 FR-01a）

    行内拆时同一订单行出现在多组，本表承载多对一映射；
    Σsplit_qty = item.num（守恒）。
    注：追加型表，DDL 无 update_time/version/is_deleted。
    """

    __tablename__ = "ord_delivery_item_detail"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    delivery_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    delivery_item_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    order_item_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    split_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    freeze_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default="CURRENT_TIMESTAMP(3)", nullable=False
    )


class OrdDeliveryPackage(Base, TimestampMixin, TenantMixin):
    """发货单包裹（D03.07 FR-01a：出库回传落库）

    重量/体积/运单号供 D08.04 运费对账与 D09.05 面单关联。
    """

    __tablename__ = "ord_delivery_package"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    owner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    delivery_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    package_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    waybill_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    logi_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    weight: Mapped[Any | None] = mapped_column(Numeric(18, 4), nullable=True)
    volume: Mapped[Any | None] = mapped_column(Numeric(18, 4), nullable=True)
    pack_items: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    #: 回传批次号（幂等键=delivery_id+batch_no）
    batch_no: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    callback_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sign_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class OrdDeliveryLog(Base, TenantMixin):
    """发货单状态流转日志（D03.07 FR-02d：全留痕）

    注：追加型表，DDL 无 update_time/version/is_deleted。
    """

    __tablename__ = "ord_delivery_log"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    delivery_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    command: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    from_status: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    to_status: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    operator: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
    reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    ref_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default="CURRENT_TIMESTAMP(3)", nullable=False
    )


class OrdDeliveryDiff(Base, TimestampMixin, TenantMixin):
    """发货单实发差异登记（D03.07 SC-03：少发/多发/破损）

    少发→差额预占释放+差异登记；多发→差额直扣实际库存+差异流水。
    """

    __tablename__ = "ord_delivery_diff"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    delivery_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    delivery_item_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: short（少发）/ over（多发）/ damage（破损）
    diff_type: Mapped[str] = mapped_column(String(16), nullable=False, default="short")
    diff_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: wms / logistics / brand（责任方）
    liability: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: reship（补发）/ refund（退款）/ recon（对账）
    handle_way: Mapped[str | None] = mapped_column(String(16), nullable=True)
    handle_status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    rel_aftersale_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    memo: Mapped[str | None] = mapped_column(String(512), nullable=True)
    operator: Mapped[str] = mapped_column(String(64), nullable=False, default="system")
