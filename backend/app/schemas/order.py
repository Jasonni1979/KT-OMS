"""订单接入域输出契约（D02 网关 / D03 订单）"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PullStatOut(BaseModel):
    """拉单统计"""

    ok: bool
    created: int = 0
    updated: int = 0
    skipped: int = 0
    closed: int = 0
    errors: int = 0
    window_start: str = ""
    window_end: str = ""
    reason: str = ""


class PullSingleOut(BaseModel):
    """单拉结果"""

    ok: bool
    outcome: str = ""
    reason: str = ""
    err_code: str = ""
    err_msg: str = ""


class WatermarkOut(BaseModel):
    """拉单水位"""

    model_config = ConfigDict(from_attributes=True)

    shop_id: int
    channel: str
    last_download_time: datetime | None = None
    overlap_sec: int
    safety_delay_sec: int
    poll_interval_sec: int
    lag_alert_threshold_sec: int
    version: int


class BufferItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    buffer_bn: str
    platform: str
    shop_id: int
    platform_order_bn: str
    platform_status: str
    canonical_status: str
    total_amount: float
    customer_paid: float
    platform_bear_total: float
    freight: float
    deliver_status: str
    deliver_times: int
    convert_warnings: list | None = None
    create_time: datetime


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_id: int
    owner_id: int
    platform_sku_code: str
    # ⚠ 以下 4 个字段在 DDL 里是**可空列**（is_nullable=YES，无默认值）
    #   声明为非空 → 遇到 NULL 的订单行时 pydantic 校验失败 → 订单详情接口 500
    platform_oid: str | None = None
    bm_id: int
    bm_number: str
    bm_name: str | None = None
    nums: int
    list_price: float
    list_amount: float
    shop_discount: float
    platform_subsidy: float
    paid_amount: float
    bom_version: int | None = None
    is_virtual: int
    is_gift: int
    parse_status: str
    platform_extra: dict | None = None


class ReceiverOut(BaseModel):
    """收货人（**默认脱敏**，明文查看需授权点 + 留痕）"""

    model_config = ConfigDict(from_attributes=True)
    id: int
    order_id: int
    name_masked: str = ""
    mobile_masked: str = ""
    mobile_tail4: str = ""
    province: str
    city: str
    district: str
    area_code: str | None = None
    address_masked: str = ""
    is_cipher: int
    key_version: str


class OrderPmtOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_id: int
    item_id: int | None
    pmt_type: str
    bearer: str
    amount: float
    platform_pmt_id: str


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    order_bn: str
    platform_order_bn: str
    shop_id: int
    owner_id: int
    createway: str
    order_type: str
    order_status: str
    audit_status: str
    fulfill_status: str
    pay_status: str
    ship_status: str
    list_amount: float
    shop_discount: float
    platform_subsidy: float
    paid_amount: float
    freight: float
    is_cod: int
    promotion_source: str
    # ⚠ DDL 里这三个字段是**可空列**（is_nullable=YES，无默认值）
    #   声明为非空 str → 遇到 NULL 的订单时 pydantic 校验失败 → 整个列表 500
    buyer_nick: str | None = None
    order_time: datetime | None = None
    pay_time: datetime | None = None
    combine_hash: str | None = None
    flag_color: int
    urge_flag: int
    warehouse_memo: str | None = None
    buyer_memo: str | None = None
    platform_extra: dict | None = None
    version: int
    create_time: datetime
    items: list[OrderItemOut] = Field(default_factory=list)


class OrderFailOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    fail_bn: str
    shop_id: int
    platform_order_bn: str
    createway: str
    fail_code: str
    fail_reason: str
    handle_status: str
    retry_count: int
    create_time: datetime


class ApiLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    log_bn: str
    method: str
    platform: str
    shop_id: int
    primary_bn: str
    err_code: str
    err_level: str
    spendtime_ms: int
    is_truncated: int
    source: str
    create_time: datetime
