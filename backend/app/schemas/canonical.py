"""canonical 标准订单模型（SRS-D02.03 FR-04 / SRS-D03.01 FR-01b）

**这是 D02（平台接入）→ D03（订单域）的唯一投递契约**（D02.03 §6.1）。

设计约束（契约级，改动需同步 docs/canonical订单字段映射.md 与下游实现）：
1. **平台无关**：D03 及下游不得感知平台差异；平台特有信息一律进 `platform_extra`。
2. **双口径金额必备**：`customer_paid`（客户实付）与 `platform_bear_total`（平台承担）
   为必填校验项；缺失时由适配器按分摊规则补算并写入 `convert_warnings`。
3. **版本收敛依据**：`platform_modified` 是幂等路由（create/update/skip/close）的唯一依据。
4. **收货人敏感字段**：明文仅存在于 canonical 层（内存），落库前必须经 PIPL 加密
   （D02.03 FR-04b）；平台密文单走 `encrypted_channel` 分支，明文留空。
"""

from datetime import datetime

from pydantic import BaseModel, Field

# ============ 枚举字典（平台无关的标准值）============

#: 标准订单状态（D02.03 §6.1 canonical_status）
CANONICAL_STATUS = {
    "unpaid": "待付款",
    "unshipped": "待发货",
    "shipped": "已发货",
    "closed": "已关闭",
    "finished": "已完成",
}

#: 收件人加密通道（决定面单与解密路径）
ENCRYPTED_CHANNEL = {
    "none": "明文",
    "oaid": "平台密文(淘系oaid)",
    "virtual": "平台虚拟号",
}

#: 订单类型（平台无关）
ORDER_TYPE = {
    "normal": "普通",
    "presale": "预售",
    "group": "团购",
    "jit": "JIT采购",
    "virtual": "虚拟",
    "exchange": "换货0元单",
}

#: 推广来源（D03.01 FR-04g 佣金归因）
PROMOTION_SOURCE = {
    "organic": "自然流量",
    "taoke": "淘客联盟",
    "live": "直播带货",
    "private": "私域",
    "other": "其他",
}

#: 行级退款标识
REFUND_STATUS = {
    "none": "无",
    "refunding": "退款中",
    "refunded": "已退款",
}

#: 优惠承担方（D03.01 FR-06a 双口径核心维度）
BEAR_BY = {
    "platform": "平台",
    "shop": "商家",
    "mixed": "混合",
}

#: 平台旗帜 → OMS 旗帜颜色（D03.01 FR-04h，语义店铺级可配，此处为默认映射）
PLATFORM_FLAG_COLOR_MAP = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5}


class CanonicalReceiver(BaseModel):
    """收货人（D02.03 FR-04b：落库前必须 PIPL 加密）"""

    name: str = Field(default="", description="收货人姓名")
    mobile: str = Field(default="", description="收货人手机")
    province: str = Field(default="", description="省")
    city: str = Field(default="", description="市")
    district: str = Field(default="", description="区/县")
    address: str = Field(default="", description="详细地址")
    zip: str = Field(default="", description="邮编")
    buyer_id: str = Field(default="", description="平台买家标识（open_id/nick，可空）")
    buyer_nick: str = Field(default="", description="买家昵称")
    encrypted_channel: str = Field(
        default="none", description="收件人加密通道：none/oaid/virtual"
    )
    cipher_blob: dict | None = Field(
        default=None, description="平台密文原文包（密文单原样保存，不解密）"
    )


class CanonicalOrderItem(BaseModel):
    """订单行（D02.03 §6.1 order_buffer_item）"""

    line_no: int = Field(ge=1, description="行号（从 1 开始）")
    oid: str = Field(default="", description="平台子单号（售后对账键）")
    platform_sku_id: str = Field(min_length=1, description="平台 SKU 编码（outer_id）")
    platform_item_id: str = Field(default="", description="平台商品 ID")
    goods_name: str = Field(default="", description="平台侧商品名")
    sku_spec: str = Field(default="", description="平台侧规格")
    num: int = Field(gt=0, description="购买数量")
    sale_price: float = Field(default=0, ge=0, description="成交单价")
    list_amount: float = Field(default=0, ge=0, description="行原价金额（未优惠前）")
    customer_paid_line: float = Field(default=0, description="行客户实付（分摊后）")
    platform_bear_line: float = Field(default=0, description="行平台承担")
    merchant_bear_line: float = Field(default=0, description="行商家承担")
    refund_status: str = Field(default="none", description="行级退款标识")
    gift_flag: int = Field(default=0, description="赠品标记 0否/1是")
    platform_extra: dict = Field(default_factory=dict)


class CanonicalPromotion(BaseModel):
    """优惠分摊明细（D02.03 §6.1 order_buffer_promotion）"""

    promotion_id: str = Field(default="", description="平台优惠流水号")
    pmt_type: str = Field(default="other", description="优惠类型")
    amount: float = Field(default=0, ge=0, description="优惠金额")
    bear_by: str = Field(default="platform", description="承担方：platform/shop/mixed")
    line_allocations: dict[str, float] = Field(
        default_factory=dict,
        description="行分摊 JSON（键=行号，值=分摊额）",
    )


class CanonicalOrder(BaseModel):
    """canonical 标准订单（D02→D03 唯一投递契约）"""

    # --- 幂等三元键（D03.01 FR-02a：DB 唯一索引兜底）---
    platform: str = Field(min_length=1, description="平台标识")
    shop_id: int = Field(gt=0, description="店铺 ID")
    platform_order_bn: str = Field(min_length=1, description="平台订单号")

    # --- 订单属性 ---
    order_type: str = Field(default="normal", description="订单类型")
    platform_status: str = Field(default="", description="平台原始状态（原样保留）")
    canonical_status: str = Field(default="unshipped", description="标准状态")
    platform_modified: datetime = Field(description="平台最后修改时间（版本收敛依据）")
    platform_create_time: datetime = Field(description="平台下单时间")
    pay_time: datetime | None = Field(default=None, description="平台付款时间")
    is_cod: bool = Field(default=False, description="货到付款")

    # --- 双口径金额（FR-04c 必填校验项）---
    total_amount: float = Field(default=0, ge=0, description="商品总额（行原价合计）")
    customer_paid: float = Field(default=0, ge=0, description="客户实付")
    platform_bear_total: float = Field(default=0, ge=0, description="平台承担合计")
    merchant_bear_total: float = Field(default=0, ge=0, description="商家承担合计")
    freight: float = Field(default=0, ge=0, description="运费（客户实付口径，不参与分摊）")

    # --- 备注与推广 ---
    buyer_message: str = Field(default="", description="买家留言")
    seller_memo: str = Field(default="", description="卖家备注")
    promotion_source: str = Field(default="organic", description="推广来源")
    promotion_pid: str = Field(default="", description="推广位 ID")
    promotion_id: str = Field(default="", description="推广活动 ID")

    # --- 客服协同标记（D03.01 FR-04h）---
    flag_color: int = Field(default=0, ge=0, le=5, description="旗帜颜色 0无旗~5紫")
    urge_flag: int = Field(default=0, ge=0, le=1, description="催发货标记")
    urge_cnt: int = Field(default=0, ge=0, description="催单次数累计")

    # --- 路由提示 ---
    warehouse_hint: str = Field(default="", description="平台指定仓提示")
    logistics_hint: str = Field(default="", description="平台物流提示")

    # --- 载荷 ---
    receiver: CanonicalReceiver = Field(description="收货人")
    items: list[CanonicalOrderItem] = Field(
        default_factory=list,
        description="商品行（允许为空：行空属服务端硬失败分级，不在契约层拦截）",
    )
    promotions: list[CanonicalPromotion] = Field(
        default_factory=list, description="优惠分摊明细"
    )
    platform_extra: dict = Field(
        default_factory=dict, description="平台特有字段 {platform:{...}}"
    )
    convert_warnings: list[str] = Field(
        default_factory=list, description="转换告警（未知状态/比例分摊/字段缺失降级）"
    )

    @property
    def idem_key(self) -> str:
        """平台单幂等键（FR-02a）"""
        return f"{self.platform}:{self.shop_id}:{self.platform_order_bn}"

    def add_warning(self, msg: str) -> None:
        """记录转换告警（去重）"""
        if msg not in self.convert_warnings:
            self.convert_warnings.append(msg)
