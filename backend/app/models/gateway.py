"""Gateway 域 ORM 模型（D02 平台接入）

覆盖：订单缓冲池（canonical 落地）+ 拉单水位 + 店铺授权 + api_log。
全部按真实 DDL 映射（缺列不映射——照抄基类 Mixin 会直接 1054 报错）。
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
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TenantMixin, TimestampMixin, VersionMixin


def mysql_blob():
    """varbinary 列类型（DDL 为 varbinary(N)，非 Text）"""
    from sqlalchemy.dialects.mysql import VARBINARY

    return VARBINARY(1024)


class GwOrderBuffer(Base, TimestampMixin, TenantMixin, VersionMixin):
    """订单缓冲池（D02.03 §6.1：canonical 模型的落地载体）"""

    __tablename__ = "gw_order_buffer"
    __table_args__ = {"schema": "oms_gateway"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    buffer_bn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    platform_order_bn: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    order_type: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")
    platform_status: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    canonical_status: Mapped[str] = mapped_column(String(16), nullable=False, default="unshipped")
    platform_modified: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    pay_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    platform_create_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    customer_paid: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    platform_bear_total: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    freight: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    buyer_message: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    seller_memo: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    receiver_name_enc: Mapped[bytes | None] = mapped_column(mysql_blob(), nullable=True)
    receiver_mobile_enc: Mapped[bytes | None] = mapped_column(mysql_blob(), nullable=True)
    receiver_mobile_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    receiver_province: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    receiver_city: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    receiver_district: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    receiver_address_enc: Mapped[bytes | None] = mapped_column(mysql_blob(), nullable=True)
    receiver_zip: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    oaid_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    receiver_encrypted_channel: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    warehouse_hint: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    logistics_hint: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    platform_extra: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    convert_warnings: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    adapter_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    mapping_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    deliver_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    deliver_times: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_deliver_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="api")


class GwOrderBufferItem(Base, TimestampMixin, TenantMixin):
    """订单缓冲行（D02.03 §6.1）"""

    __tablename__ = "gw_order_buffer_item"
    __table_args__ = {"schema": "oms_gateway"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    buffer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    oid: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    platform_sku_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    platform_item_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    goods_name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    sku_spec: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    local_sku_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sale_price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    customer_paid_line: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    platform_bear_line: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    merchant_bear_line: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    refund_status: Mapped[str] = mapped_column(String(16), nullable=False, default="none")
    gift_flag: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    platform_extra: Mapped[Any | None] = mapped_column(JSON, nullable=True)


class GwOrderBufferPromotion(Base, TimestampMixin, TenantMixin):
    """缓冲单优惠分摊明细（D02.03 §6.1）"""

    __tablename__ = "gw_order_buffer_promotion"
    __table_args__ = {"schema": "oms_gateway"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    buffer_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    promotion_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    promotion_type: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    bear_by: Mapped[str] = mapped_column(String(16), nullable=False, default="platform")
    line_allocations: Mapped[Any | None] = mapped_column(JSON, nullable=True)


class GwPullWatermark(Base, TimestampMixin, TenantMixin, VersionMixin):
    """店铺拉单水位（D02.03 §6.3：只进不退 + CAS 推进）"""

    __tablename__ = "gw_pull_watermark"
    __table_args__ = {"schema": "oms_gateway"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="order")
    last_download_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    overlap_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    safety_delay_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    poll_interval_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    lag_alert_threshold_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=1800)


class GwShopAuth(Base, TimestampMixin, TenantMixin, VersionMixin):
    """店铺授权凭证（D02.06；密文存储，禁止明文）"""

    __tablename__ = "gw_shop_auth"
    __table_args__ = {"schema": "oms_gateway"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    access_token_enc: Mapped[bytes | None] = mapped_column(mysql_blob(), nullable=True)
    refresh_token_enc: Mapped[bytes | None] = mapped_column(mysql_blob(), nullable=True)
    session_enc: Mapped[bytes | None] = mapped_column(mysql_blob(), nullable=True)
    key_version: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    refresh_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_refresh_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    refresh_fail_times: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")


class GwApiLog(Base, TenantMixin):
    """api_log 报文日志（D02.01 FR-07：调用留痕，超阈值截断）"""

    __tablename__ = "gw_api_log"
    __table_args__ = {"schema": "oms_gateway"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    log_bn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    direction: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    method: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    native_method: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    primary_bn: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    request_params: Mapped[str] = mapped_column(Text, nullable=False, default="")
    response_body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_truncated: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    oss_ref: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    http_status: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    err_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    err_level: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    spendtime_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    msg_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="pull")
    retry_of: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    operator: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    create_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now()
    )

