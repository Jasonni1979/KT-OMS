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
