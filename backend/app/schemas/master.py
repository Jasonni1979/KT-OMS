"""档案域 Pydantic Schema（组织树/货主/店铺/仓库，请求响应契约）"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ============ 组织树（SRS-D10.01 FR-01/02）============

NODE_TYPES = ("group", "brand", "owner_co", "shop", "warehouse", "dept", "reserved_dealer")


class OrgNodeCreate(BaseModel):
    org_code: str = Field(min_length=1, max_length=64, description="全局唯一,创建后不可改")
    org_name: str = Field(min_length=1, max_length=128)
    node_type: str = Field(pattern="^(group|brand|owner_co|shop|warehouse|dept|reserved_dealer)$")
    parent_id: int = Field(default=0, ge=0, description="0=根(仅group)")
    ref_id: int = Field(default=0, ge=0, description="shop/warehouse 联动业务档案ID")
    sort_no: int = 0
    remark: str = Field(default="", max_length=512)


class OrgNodeUpdate(BaseModel):
    org_name: str | None = Field(default=None, max_length=128)
    sort_no: int | None = None
    remark: str | None = Field(default=None, max_length=512)
    status: int | None = Field(default=None, ge=1, le=2)
    version: int = Field(description="乐观锁:提交当前读到的version")


class OrgNodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    org_code: str
    org_name: str
    node_type: str
    parent_id: int
    cat_path: str
    node_level: int
    ref_id: int
    sort_no: int
    status: int
    remark: str
    version: int
    create_time: datetime


# ============ 货主（FR-03/06）============

OWNER_TYPES = ("KC_BUYOUT", "BRAND_CONSIGN", "DEALER_TC")


class OwnerCreate(BaseModel):
    owner_code: str = Field(min_length=1, max_length=64)
    owner_name: str = Field(min_length=1, max_length=128)
    owner_type: str = Field(pattern="^(KC_BUYOUT|BRAND_CONSIGN)$", description="DEALER_TC为P2预留置灰")
    org_node_id: int = Field(gt=0, description="归属owner_co节点,必填")
    tax_no: str = Field(default="", max_length=64)
    contact_name: str = Field(default="", max_length=64)
    remark: str = Field(default="", max_length=512)


class OwnerUpdate(BaseModel):
    owner_name: str | None = Field(default=None, max_length=128)
    tax_no: str | None = Field(default=None, max_length=64)
    contact_name: str | None = Field(default=None, max_length=64)
    remark: str | None = Field(default=None, max_length=512)
    version: int


class OwnerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    owner_code: str
    owner_name: str
    owner_type: str
    org_node_id: int
    tax_no: str
    contact_name: str
    status: int
    remark: str
    version: int
    create_time: datetime


# ============ 店铺（最小版）============

PLATFORMS = ("taobao", "jd", "pdd", "xhs", "vop", "douyin", "wechat", "kuaishou")


class ShopCreate(BaseModel):
    shop_name: str = Field(min_length=1, max_length=128)
    owner_id: int = Field(gt=0)
    platform: str = Field(pattern="^(taobao|jd|pdd|xhs|vop|douyin|wechat|kuaishou)$")
    platform_shop_id: str = Field(default="", max_length=64)
    shop_type: str = Field(default="flagship", pattern="^(direct|flagship|franchise|store|dealer)$")
    business_type: str = Field(default="direct_sale", pattern="^(direct_sale|distribution|dealer)$")


class ShopUpdate(BaseModel):
    shop_name: str | None = Field(default=None, max_length=128)
    status: str | None = Field(default=None, pattern="^(enabled|disabled)$")
    version: int


class ShopOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    shop_bn: str
    shop_name: str
    owner_id: int
    platform: str
    platform_shop_id: str
    shop_type: str
    business_type: str
    auth_status: str
    org_node_id: int
    status: str
    version: int
    create_time: datetime


# ============ 仓库（最小版）============


class BranchCreate(BaseModel):
    branch_name: str = Field(min_length=1, max_length=128)
    owner_id: int | None = Field(default=None, description="单一归属仓必填;多货主仓为空")
    branch_type: str = Field(default="entity", pattern="^(entity|cloud|store|bonded|virtual|defective)$")
    region_code: str | None = Field(default=None, max_length=16)
    province: str | None = Field(default=None, max_length=32)
    city: str | None = Field(default=None, max_length=32)
    district: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=256)
    contact_name: str | None = Field(default=None, max_length=64)
    is_ctrl: int = Field(default=1, ge=0, le=1)
    countable_flag: int = Field(default=1, ge=0, le=1)
    cutoff_time: str | None = Field(default=None, pattern="^([01]\\d|2[0-3]):[0-5]\\d$")
    memo: str | None = Field(default=None, max_length=512)


class BranchUpdate(BaseModel):
    branch_name: str | None = Field(default=None, max_length=128)
    region_code: str | None = None
    province: str | None = None
    city: str | None = None
    district: str | None = None
    address: str | None = None
    contact_name: str | None = None
    is_ctrl: int | None = Field(default=None, ge=0, le=1)
    countable_flag: int | None = Field(default=None, ge=0, le=1)
    cutoff_time: str | None = Field(default=None, pattern="^([01]\\d|2[0-3]):[0-5]\\d$")
    status: str | None = Field(default=None, pattern="^(enabled|disabled)$")
    memo: str | None = None
    version: int


class BranchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    branch_bn: str
    branch_name: str
    owner_id: int | None
    branch_type: str
    region_code: str | None
    province: str | None
    city: str | None
    district: str | None
    address: str | None
    contact_name: str | None
    is_ctrl: int
    countable_flag: int
    cutoff_time: str | None
    org_node_id: int | None
    status: str
    version: int
    create_time: datetime
