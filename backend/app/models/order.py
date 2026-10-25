"""订单域 ORM 模型（D03 订单接入与创建）

覆盖：订单头（ord_order）+ 订单行 + 收货人（加密）+ 优惠分摊 + 状态日志 + 接入失败单。
按真实 DDL 映射；缺列（如 ord_order_pmt 无 version）不映射。
"""

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


class OrdOrder(Base, TimestampMixin, TenantMixin, VersionMixin):
    """订单头（D03.01 FR-04a：订单聚合根）"""

    __tablename__ = "ord_order"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    order_bn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    platform_order_bn: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    external_bn: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    platform_msg_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    brand_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    createway: Mapped[str] = mapped_column(String(16), nullable=False, default="platform")
    order_type: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    special_tags: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    # 四套状态（D03.01 FR-05a 初始化 + §5.1 合法流转表）
    order_status: Mapped[str] = mapped_column(String(16), nullable=False, default="processing")
    audit_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    fulfill_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    pay_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unpaid")
    ship_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unshipped")
    # 双口径金额（D03.01 FR-06a）
    list_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    shop_discount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    platform_subsidy: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    paid_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    freight: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    is_cod: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    # 推广来源（D03.01 FR-04g）
    promotion_source: Mapped[str] = mapped_column(String(16), nullable=False, default="organic")
    promotion_pid: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    promotion_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    buyer_id_enc: Mapped[bytes | None] = mapped_column(mysql_blob(), nullable=True)
    buyer_nick: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    order_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pay_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 合单指纹（D03.01 FR-07a）
    combine_hash: Mapped[str | None] = mapped_column(String(32), nullable=True)
    combine_idx: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    combine_group_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    # 拆单轮次计数（D03.04 FR-06b：每轮落库成功 +1；发货单取消不回退）
    splited_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 发货联动字段（D03.07 FR-06a：发货确认时回写）
    logi_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    logi_no: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    delivery_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finish_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    batch_no: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    is_fail: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    fail_code: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    is_pause: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    cancel_reason_code: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    cancel_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 客服协同标记（D03.01 FR-04h）
    flag_color: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    urge_flag: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    urge_cnt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_urge_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # ---------- 以下为 DDL 有列但此前模型未映射的字段（tools/check_model_ddl.py 检出）----------
    # 时效承诺（D03.10 预售/承诺）
    promise_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    promise_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 收货坐标（O2O 门店路由 D03.11）
    receiver_lat: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    receiver_lng: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    # 运费与承担方（发货单/面单 D09.05）
    delivery_fee: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    fee_bearer: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 即时零售平台（D03.15）
    instant_platform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 跨境申报类型（D03.12）
    cross_border_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    declare_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    declare_status: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    # 归档（D03.13）
    archive_flag: Mapped[str] = mapped_column(String(16), nullable=False, default="online")
    archive_locator: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    archive_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 叫回标记（D03.07 FR-08b）
    recall_flag: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    recall_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 审单路由人数（D03.03 分派）
    router_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warehouse_memo: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    buyer_memo: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    self_delivery: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    fulfill_channel: Mapped[str] = mapped_column(String(16), nullable=False, default="express")
    platform_extra: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="api")


class OrdOrderItem(Base, TimestampMixin, TenantMixin, VersionMixin):
    """订单行（D03.01 FR-04a/FR-04d：BOM 展开快照固化，档案变更不回溯）"""

    __tablename__ = "ord_order_item"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    sm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    platform_sku_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    platform_oid: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    bm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    bm_number: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    bm_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    parent_item_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    nums: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    split_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sendnum: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    refund_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    list_price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    list_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    shop_discount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    platform_subsidy: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    paid_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    bom_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bom_candidates: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    is_virtual: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    is_gift: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    # 预售预计发货日（D03.10 预售/现货拆单）
    estimate_con_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 行税额（金额分摊 D03.01 FR-06）
    tax_amount: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    parse_status: Mapped[str] = mapped_column(String(16), nullable=False, default="parsed")
    weight: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    platform_extra: Mapped[Any | None] = mapped_column(JSON, nullable=True)


class OrdReceiver(Base, TimestampMixin, TenantMixin, VersionMixin):
    """收货人（D03.01 FR-04f：PIPL 加密 + 盲索引；密文单原样保存）"""

    __tablename__ = "ord_receiver"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    name_enc: Mapped[bytes | None] = mapped_column(mysql_blob(), nullable=True)
    name_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    mobile_enc: Mapped[bytes | None] = mapped_column(mysql_blob(), nullable=True)
    mobile_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    mobile_tail4: Mapped[str] = mapped_column(String(4), nullable=False, default="")
    phone_enc: Mapped[bytes | None] = mapped_column(mysql_blob(), nullable=True)
    province: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    city: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    district: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    town: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    area_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    address_enc: Mapped[bytes | None] = mapped_column(mysql_blob(), nullable=True)
    address_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    zip: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    is_cipher: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    cipher_blob: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    key_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")


class OrdOrderPmt(Base, TimestampMixin, TenantMixin):
    """优惠分摊（D03.01 FR-06c：单级 + 行级两层，双口径取数源）"""

    __tablename__ = "ord_order_pmt"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    item_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    pmt_type: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    bearer: Mapped[str] = mapped_column(String(16), nullable=False, default="platform")
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    platform_pmt_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    pmt_memo: Mapped[str] = mapped_column(String(256), nullable=False, default="")


class OrdStatusLog(Base, TenantMixin):
    """状态变迁日志（D03.01 FR-05b：前值/后值/触发源/操作者）"""

    __tablename__ = "ord_status_log"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    order_bn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    status_domain: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    from_value: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    to_value: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    trigger_source: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    trigger_ref: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    operator: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    memo: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    create_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now()
    )


class OrdOrderFail(Base, TimestampMixin, TenantMixin):
    """接入失败单（D03.01 FR-04c 硬失败：落独立列表人工处理，不进缓冲池）"""

    __tablename__ = "ord_order_fail"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    fail_bn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    platform_order_bn: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    platform_msg_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    createway: Mapped[str] = mapped_column(String(16), nullable=False, default="platform")
    fail_code: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    fail_reason: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    raw_payload: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    handle_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    operator: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    handle_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
