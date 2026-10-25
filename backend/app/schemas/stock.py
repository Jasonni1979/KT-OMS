"""库存域 Pydantic Schema（SRS-D04.02 记账 + D04.04 调整单 + 对账）"""
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

# ============ 口径 ============

STOCK_FIELDS = ("store", "freeze", "arrive_store", "defective")

# ============ 记账 ============


class StockChangeItem(BaseModel):
    """单口径变动（一个记账动作可含多个口径）"""

    field: str = Field(pattern="^(store|freeze|arrive_store|defective)$")
    delta: int = Field(description="变动数量（±整数）")


class StockChangeRequest(BaseModel):
    """记账请求（FR-03a：三元键 + 口径变动 + 业务单据 + 幂等键）"""

    branch_id: int = Field(gt=0)
    bm_id: int = Field(gt=0)
    owner_id: int = Field(gt=0)
    changes: list[StockChangeItem] = Field(min_length=1)
    bill_type: str = Field(default="", max_length=32, description="业务单据类型")
    bill_bn: str = Field(default="", max_length=32, description="业务单据号")
    bill_item_id: int = Field(default=0)
    action: str = Field(default="", max_length=32, description="动作: inbound/outbound/adjust/...")
    operator: str = Field(default="", max_length=64)
    source: str = Field(default="oms", max_length=32, description="manual/oms/wms/migration")
    remark: str = Field(default="", max_length=255)
    redis_synced: bool = Field(
        default=False,
        description="Redis 已由调用方原子更新（预占/核销走 Lua 先行），跳过 Redis 同步避免重复累加",
    )


class StockLedgerOut(BaseModel):
    """五口径余额（available 为派生计算值，不落库）"""

    branch_id: int
    bm_id: int
    owner_id: int
    store: int
    freeze: int
    arrive_store: int
    defective: int
    safe_store: int
    is_locked: int
    available: int
    unit_cost: float
    inventory_cost: float
    status: int
    material_bn: str = ""
    material_name: str = ""
    branch_name: str = ""


class StockChangeResult(BaseModel):
    """记账结果"""

    idempotent: bool = Field(description="True=幂等命中，本次未重复记账")
    balances: dict[str, int] = Field(description="各口径变更后余额")
    available: int
    change_log_ids: list[int] = Field(default_factory=list)


# ============ 人工调整（FR-04）============

ADJUST_TYPES = ("盘盈", "盘亏", "报损", "退货修正", "系统纠错", "其他")


class StockAdjustRequest(BaseModel):
    """人工库存调整单（FR-04b：三元键 + 数量 + 类型 + 原因）"""

    branch_id: int = Field(gt=0)
    bm_id: int = Field(gt=0)
    owner_id: int = Field(gt=0)
    field: str = Field(pattern="^(store|freeze|arrive_store|defective)$", default="store")
    adjust_num: int = Field(description="调整数量（±整数；盘盈为正）")
    adjust_type: str = Field(default="其他", max_length=32)
    reason: str = Field(min_length=1, max_length=512, description="原因必填")
    operator: str = Field(default="", max_length=64)
    attachment: dict | None = None


# ============ 对账（FR-05/FR-06）============

class ReconDiffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    owner_id: int
    recon_date: date
    recon_type: int
    branch_id: int
    bm_id: int
    change_field: str
    oms_num: int
    peer_num: int
    diff_num: int
    status: int
    handle_remark: str
    handler: str
    handle_time: datetime | None


class ReconReportOut(BaseModel):
    """对账报告"""

    recon_type: int
    checked: int = Field(description="比对的三元键数量")
    diff_count: int = Field(description="差异条数")
    fixed: int = Field(description="自动修复条数")
    diffs: list[ReconDiffOut] = Field(default_factory=list)


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    owner_id: int
    snapshot_date: date
    branch_id: int
    bm_id: int
    store: int
    freeze: int
    arrive_store: int
    defective: int
    safe_store: int
    available_num: int
    unit_cost: float
    inventory_cost: float


# ============ 预占（FR-D04.03）============

FREEZE_OBJ_TYPES = {1: "订单", 2: "售后换货", 3: "调拨", 4: "人工", 5: "借调"}
FREEZE_STATUS_LABEL = {1: "已生效", 2: "部分核销", 3: "已核销", 4: "已释放"}


class FreezeReserveItem(BaseModel):
    """单行预占请求"""

    branch_id: int = Field(gt=0)
    bm_id: int = Field(gt=0)
    owner_id: int = Field(gt=0)
    num: int = Field(gt=0, description="预占数量>0")
    shop_id: int = Field(default=0, ge=0)
    obj_item_id: int = Field(default=0, ge=0, description="对象行ID（幂等键成分）")


class FreezeReserveRequest(BaseModel):
    """统一预占入口（FR-01a：对象类型 + 单据引用 + 三元键 + 数量）"""

    obj_type: int = Field(default=1, ge=1, le=5, description="1订单,2售后换货,3调拨,4人工,5借调")
    obj_bn: str = Field(min_length=1, max_length=32, description="对象单号")
    items: list[FreezeReserveItem] = Field(min_length=1, description="逐行预占（Saga）")
    source: str = Field(default="audit", max_length=32, description="audit/manual/compensate/wms")
    lend_owner_id: int = Field(default=0, ge=0, description="借出货主（借调预占必填）")
    ttl_hours: int | None = Field(default=None, ge=1, le=720, description="覆盖默认有效期（小时）")


class FreezeReleaseRequest(BaseModel):
    """释放请求（FR-02a：按单据引用定位未核销流水）"""

    obj_type: int = Field(default=1, ge=1, le=5)
    obj_bn: str = Field(min_length=1, max_length=32)
    obj_item_id: int | None = Field(default=None, ge=0, description="为空=释放该单全部未核销行")
    num: int | None = Field(default=None, gt=0, description="为空=全额释放")
    operator: str = Field(default="", max_length=64)


class FreezeSettleRequest(BaseModel):
    """转扣减请求（FR-03a：出库回传触发 freeze-N & store-N）"""

    obj_type: int = Field(default=1, ge=1, le=5)
    obj_bn: str = Field(min_length=1, max_length=32)
    obj_item_id: int = Field(default=0, ge=0)
    num: int = Field(gt=0, description="本次核销数量（支持部分核销）")
    bill_type: str = Field(default="sale_out", max_length=32)
    bill_bn: str = Field(default="", max_length=32)
    bill_item_id: int = Field(default=0, ge=0)
    operator: str = Field(default="", max_length=64)


class FreezeLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    owner_id: int
    obj_type: int
    obj_bn: str
    obj_item_id: int
    branch_id: int
    bm_id: int
    shop_id: int
    num: int
    settled_num: int
    released_num: int
    status: int
    expire_time: datetime | None
    source: str
    is_compensated: int
    idempotent_key: str
    create_time: datetime


class FreezeResult(BaseModel):
    """预占结果"""

    idempotent: bool
    obj_type: int
    obj_bn: str
    reserved_num: int = 0
    available_after: int = 0
    logs: list[FreezeLogOut] = Field(default_factory=list)
    compensated: bool = Field(description="True=Saga 补偿回滚了部分行")


class FreezeAgeOut(BaseModel):
    """账龄分析（FR-04a：在途预占按时长分级）"""

    total: int
    age_24h: int
    age_48h: int
    age_72h: int
    expired_pending: int


# ============ 出入库单据（D04.04）============

BILL_STATUS_LABEL = {
    1: "草稿", 2: "已下发WMS", 3: "部分回传", 4: "全部回传",
    5: "已确认", 6: "已红冲", 7: "已关闭",
}
SETTLE_STATUS_LABEL = {0: "无需结算", 1: "未结算", 2: "部分结算", 3: "已结算", 4: "结算锁定"}


class IoBillItemIn(BaseModel):
    """单据明细行"""

    bm_id: int = Field(gt=0, description="基础物料")
    source_item_id: int = Field(
        default=0,
        ge=0,
        description="来源订单行ID（D03.07 追溯链；销售出库核销预占时按此定位预占台账）",
    )
    issued_num: int = Field(default=0, ge=0, description="下发数量")
    confirmed_num: int = Field(default=0, ge=0, description="确认记账数量")
    defect_num: int = Field(default=0, ge=0, description="不良数量")
    batch_no: str = Field(default="", max_length=64)
    unit_cost: float = Field(default=0, ge=0)
    remark: str = Field(default="", max_length=255)


class IoBillCreate(BaseModel):
    """创建出入库单据（FR-03a 源单自动生成 / FR-03b 人工创建）"""

    bill_type: str = Field(min_length=1, max_length=32, description="单据类型码")
    branch_id: int = Field(gt=0)
    owner_id: int = Field(default=0, ge=0, description="行级货主（默认继承）")
    shop_id: int = Field(default=0, ge=0)
    source_bill_type: str = Field(default="", max_length=32)
    source_bill_bn: str = Field(default="", max_length=64)
    items: list[IoBillItemIn] = Field(min_length=1)
    operator: str = Field(default="", max_length=64)
    memo: str = Field(default="", max_length=512)


class IoBillItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    bill_id: int
    bill_bn: str
    owner_id: int
    bm_id: int
    issued_num: int
    returned_num: int
    confirmed_num: int
    defect_num: int
    batch_no: str
    unit_cost: float
    amount: float


class IoBillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    owner_id: int
    bill_bn: str
    bill_type: str
    direction: int
    branch_id: int
    source_bill_type: str
    source_bill_bn: str
    wms_bill_no: str
    shop_id: int
    status: int
    red_flush_of: str
    settle_status: int
    settle_bn: str
    settle_num: int
    settle_money: float
    operator: str
    confirm_time: datetime | None
    memo: str
    source: str
    version: int
    create_time: datetime
    items: list[IoBillItemOut] = Field(default_factory=list)


class IoBillCallback(BaseModel):
    """WMS 回传（FR-02c：分批回传累计）"""

    wms_bill_no: str = Field(default="", max_length=64)
    items: list[IoBillItemIn] = Field(min_length=1)
    operator: str = Field(default="", max_length=64)


class RedFlushRequest(BaseModel):
    """红冲（FR-04a：原因必填，已结算禁止）"""

    reason: str = Field(min_length=1, max_length=512)
    operator: str = Field(default="", max_length=64)


class SettleUpdateRequest(BaseModel):
    """结算状态回写（FR-05a：由财务/采购对账流程回写）"""

    settle_status: int = Field(ge=1, le=4)
    settle_bn: str = Field(default="", max_length=32)
    settle_num: int = Field(default=0, ge=0)
    settle_money: float = Field(default=0, ge=0)
    operator: str = Field(default="", max_length=64)


class IoBillTraceOut(BaseModel):
    """追溯链（FR-06a：单据 → 行 → 流水 → 记账行余额）"""

    bill: IoBillOut
    change_logs: list[dict] = Field(default_factory=list)
    ledger: dict[str, int] = Field(default_factory=dict)


# ============ 可售计算与平台同步（D04.08）============

STRATEGY_TYPE_LABEL = {
    "independent": "分平台独立库存",
    "shared_ratio": "共享池按比例分配",
    "shared_safe": "全量共享-安全库存预留",
    "activity_lock": "活动锁定",
}
SYNC_TRIGGER_LABEL = {1: "事件驱动", 2: "水位触发", 3: "定时全量", 4: "手动", 5: "对账强制"}


class SyncStrategyIn(BaseModel):
    """可售同步策略配置（D04.08 FR-01）"""

    shop_id: int = Field(gt=0)
    scope_type: int = Field(default=1, ge=1, le=4, description="1全店,2分类,3品牌,4指定物料")
    scope_ref: list[int] = Field(default_factory=list, description="范围引用（分类/品牌/物料ID）")
    strategy_type: str = Field(default="shared_safe", description="independent/shared_ratio/shared_safe")
    safe_num: int = Field(default=0, ge=0, description="安全库存量")
    safe_ratio: float = Field(default=0, ge=0, le=100, description="安全库存比例%")
    alloc_ratio: float = Field(default=0, ge=0, description="分配比例%")
    oversell_mode: int = Field(default=1, ge=1, le=2, description="1硬分配,2软超卖")
    quota_num: int = Field(default=0, ge=0, description="独立配额")
    water_level: int = Field(default=0, ge=0, description="水位线")
    min_sellable: int = Field(default=0, ge=0, description="可售下限")
    max_sellable: int = Field(default=0, ge=0, description="可售上限（0=不限）")
    writeback_mode: int = Field(default=1, ge=1, le=3, description="1实时,2准实时批量,3定时")
    threshold_rate: float = Field(default=0, ge=0, description="回写变化阈值率（防抖）")
    status: int = Field(default=1, ge=1, le=2)


class SyncStrategyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    shop_id: int
    scope_type: int
    scope_ref: list | None = None
    strategy_type: str
    safe_num: int
    safe_ratio: float
    alloc_ratio: float
    oversell_mode: int
    quota_num: int
    water_level: int
    min_sellable: int
    max_sellable: int
    writeback_mode: int
    threshold_rate: float
    status: int
    version: int


class SellableOut(BaseModel):
    """可售计算结果（IF-D04.08-01）"""

    shop_id: int
    sm_id: int
    platform_sku: str
    base_available: int
    sellable: int
    strategy_type: str
    is_combo: bool
    member_details: list[dict] = Field(default_factory=list)
    branch_ids: list[int] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class WritebackResultOut(BaseModel):
    """回写结果（FR-03）"""

    shop_id: int
    sm_id: int
    platform_sku: str
    calc_sellable: int
    written: bool
    reason: str = ""
    error_code: str = ""


class SellableReconOut(BaseModel):
    """可售同步对账报告（FR-05b）"""

    shop_id: int
    checked: int
    diff_count: int
    diffs: list[dict] = Field(default_factory=list)
