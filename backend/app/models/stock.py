"""oms_stock 单据与记账模型（SRS-D04.04 单据流水 + D04.02 记账行/变动流水）

- inv_io_bill        出入库单据头（bill_type→inv_io_bill_type；状态机见 D04.04 §4.1）
- inv_io_bill_item   单据明细行
- inv_stock_ledger   五口径记账行（三元键：仓 + 物料 + 货主）
- inv_stock_change_log 库存变动流水（口径级 before/after 快照，幂等键防重复记账）
- inv_stock_snapshot 库存快照（D04.02 FR-06 对账快照）
"""
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    Integer,
    Numeric,
    SmallInteger,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class InvIoBill(Base):
    """出入库单据头（D04.04 FR-01/FR-02）"""

    __tablename__ = "inv_io_bill"
    __table_args__ = {"schema": "oms_stock"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    bill_bn: Mapped[str] = mapped_column(String(32), nullable=False, comment="单据号,全局唯一")
    bill_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True, comment="类型码")
    direction: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, comment="1入库,2出库")
    branch_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    source_bill_type: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    source_bill_bn: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    wms_bill_no: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    status: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1,
        comment="1草稿,2已下发WMS,3部分回传,4全部回传,5已确认,6已红冲,7已关闭",
    )
    red_flush_of: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    settle_status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    settle_bn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    settle_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    settle_money: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    approval_status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    operator: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    confirm_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    memo: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    attachment: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class InvIoBillItem(Base):
    """出入库单据明细行（D04.04 FR-06 追溯）"""

    __tablename__ = "inv_io_bill_item"
    __table_args__ = {"schema": "oms_stock"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    bill_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    bill_bn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    bm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    issued_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    returned_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confirmed_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    defect_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    batch_no: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    expire_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    serial_nos: Mapped[list | None] = mapped_column(JSON, nullable=True)
    unit_cost: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    source_item_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    remark: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class InvStockLedger(Base):
    """五口径记账行（D04.02 FR-02：三元键 = 仓 + 物料 + 货主）"""

    __tablename__ = "inv_stock_ledger"
    __table_args__ = {"schema": "oms_stock"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    branch_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    bm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    store: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="实际库存")
    freeze: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="锁定库存")
    arrive_store: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="在途库存")
    defective: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="次品库存")
    safe_store: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="安全库存")
    is_locked: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    unit_cost: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    inventory_cost: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    last_store_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class InvStockChangeLog(Base):
    """库存变动流水（D04.02 FR-03：口径级 before/after 快照 + 幂等键）"""

    __tablename__ = "inv_stock_change_log"
    __table_args__ = {"schema": "oms_stock"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    branch_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    bm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    change_field: Mapped[str] = mapped_column(String(16), nullable=False, default="store")
    change_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    before_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    after_balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bill_type: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    bill_bn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    bill_item_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    action: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    operator: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="oms")
    idempotent_key: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class InvStockSnapshot(Base):
    """库存快照（D04.02 FR-06 对账快照）"""

    __tablename__ = "inv_stock_snapshot"
    __table_args__ = {"schema": "oms_stock"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    branch_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    bm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    store: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    freeze: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    arrive_store: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    defective: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    safe_store: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit_cost: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    inventory_cost: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class InvStockConfig(Base):
    """库存配置（D04.02 FR-02c 负卖开关 / FR-04b 调整阈值 / FR-05 预占有效期）"""

    __tablename__ = "inv_stock_config"
    __table_args__ = {"schema": "oms_stock"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    config_type: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1,
        comment="1负卖开关,2调整审批阈值,3预占有效期,4超收容差,5调拨在途可售默认",
    )
    scope_type: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, comment="1全局,2货主,3店铺,4仓库,5仓库x货主,6调整类型"
    )
    scope_ref: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    config_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class InvStockReconDiff(Base):
    """库存对账差异（D04.02 FR-05c/FR-06b：Redis vs DB / WMS vs OMS / 批次账 vs 数量账）"""

    __tablename__ = "inv_stock_recon_diff"
    __table_args__ = {"schema": "oms_stock"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    recon_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    recon_type: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, comment="1 Redis vs DB,2 WMS vs OMS,3 批次账 vs 数量账"
    )
    branch_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    bm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    change_field: Mapped[str] = mapped_column(String(16), nullable=False, default="store")
    oms_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    peer_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    diff_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, comment="1待处理,2已自动修复,3已人工处理,4误报忽略"
    )
    handle_remark: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    handler: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    handle_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )


class InvFreezeLog(Base):
    """预占台账（SRS-D04.03：Redis 实时口径 + DB 业务追溯双写）"""

    __tablename__ = "inv_freeze_log"
    __table_args__ = {"schema": "oms_stock"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    obj_type: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, comment="1订单,2售后换货,3调拨,4人工,5借调"
    )
    obj_bn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    obj_item_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    branch_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    bm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    num: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="预占数量>0")
    settled_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="已核销数量")
    released_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="已释放数量")
    status: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, comment="1已生效,2部分核销,3已核销,4已释放"
    )
    expire_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    lend_owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    lend_ledger_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="audit")
    is_compensated: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, comment="Saga补偿标记:0正常,1已补偿回滚"
    )
    idempotent_key: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class InvIoBillType(Base):
    """出入库单据类型（D04.04 FR-01：口径影响模板驱动记账，扩展不改代码）"""

    __tablename__ = "inv_io_bill_type"
    __table_args__ = {"schema": "oms_stock"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    type_code: Mapped[str] = mapped_column(String(32), nullable=False, comment="类型码,唯一")
    type_name: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, comment="1入库,2出库")
    effect_template: Mapped[list | None] = mapped_column(
        JSON, nullable=True,
        comment="口径影响模板:[{field:store,sign:1}]；销售出库为[{action:settle}]",
    )
    need_wms: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    need_approval: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    settle_rel: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, comment="0无,1应付,2应收"
    )
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class InvSyncStrategy(Base):
    """可售同步策略（D04.08 FR-01：按店铺配置，可下探到分类/品牌/物料）"""

    __tablename__ = "inv_sync_strategy"
    __table_args__ = {"schema": "oms_stock"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    scope_type: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, comment="1全店,2分类,3品牌,4指定物料"
    )
    scope_ref: Mapped[list | None] = mapped_column(JSON, nullable=True)
    strategy_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="shared_safe",
        comment="independent独立/shared_ratio比例/shared_safe安全库存/activity_lock活动锁定",
    )
    safe_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    safe_ratio: Mapped[float] = mapped_column(Numeric(9, 4), nullable=False, default=0)
    alloc_ratio: Mapped[float] = mapped_column(Numeric(9, 4), nullable=False, default=0)
    oversell_mode: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, comment="1硬分配,2软超卖"
    )
    quota_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    water_level: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    water_level_type: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, comment="1绝对值,2销量天数"
    )
    min_sellable: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_sellable: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="0=不限")
    writeback_mode: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, comment="1实时,2准实时批量,3定时"
    )
    threshold_rate: Mapped[float] = mapped_column(
        Numeric(9, 4), nullable=False, default=0, comment="回写变化阈值率(防抖)"
    )
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class InvActivityLockPool(Base):
    """活动锁定库存池（D04.08 FR-01e：渠道级预留，与订单级预占不同）"""

    __tablename__ = "inv_activity_lock_pool"
    __table_args__ = {"schema": "oms_stock"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    activity_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    activity_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    branch_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    bm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    lock_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sold_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    remain_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    channel_scope: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    release_rule: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", comment="warmup/active/ended/released"
    )
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class InvSyncLog(Base):
    """可售回写日志（D04.08 FR-03d：可追溯）"""

    __tablename__ = "inv_sync_log"
    __table_args__ = {"schema": "oms_stock"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    sm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    platform_sku: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    calc_sellable: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    writeback_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trigger_type: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, comment="1事件,2水位,3定时,4手动,5对账强制"
    )
    sync_status: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, comment="1成功,2失败"
    )
    platform_response: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    error_code: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
