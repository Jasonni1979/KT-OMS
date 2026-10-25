"""物料域 Pydantic Schema（SRS-D04.01）

第一批：分类树（FR-05a）+ 品牌（FR-05b）+ 基础物料（FR-02）
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# ============ 枚举 ============

MATERIAL_TYPES = {1: "成品", 2: "半成品", 3: "普通", 4: "礼盒", 5: "虚拟"}
SALES_MATERIAL_TYPES = {1: "普通", 2: "组合", 3: "赠品", 4: "多选一", 5: "礼盒", 6: "福袋"}
BARCODE_TYPES = {1: "厂商码", 2: "店铺码", 3: "WMS码", 9: "其他"}


# ============ 分类树（FR-05a）============

class MaterialCatCreate(BaseModel):
    cat_name: str = Field(min_length=1, max_length=128)
    parent_id: int = Field(default=0, ge=0, description="0=根分类")
    sort_no: int = 0


class MaterialCatUpdate(BaseModel):
    cat_name: str | None = Field(default=None, max_length=128)
    sort_no: int | None = None
    status: int | None = Field(default=None, ge=1, le=2)
    version: int


class MaterialCatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    cat_name: str
    parent_id: int
    cat_path: str
    cat_level: int
    sort_no: int
    status: int
    version: int
    create_time: datetime


# ============ 品牌（FR-05b）============

class BrandCreate(BaseModel):
    brand_name: str = Field(min_length=1, max_length=128)
    brand_name_en: str = Field(default="", max_length=128)
    owner_id: int = Field(default=0, ge=0, description="0=公共品牌")
    org_node_id: int = Field(default=0, ge=0, description="组织树 brand 节点映射")


class BrandUpdate(BaseModel):
    brand_name: str | None = Field(default=None, max_length=128)
    brand_name_en: str | None = Field(default=None, max_length=128)
    status: int | None = Field(default=None, ge=1, le=2)
    version: int


class BrandOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    owner_id: int
    brand_name: str
    brand_name_en: str
    org_node_id: int
    status: int
    version: int
    create_time: datetime


# ============ 基础物料（FR-02）============

class MaterialCreate(BaseModel):
    material_bn: str = Field(min_length=1, max_length=64, description="货号,全局唯一")
    material_name: str = Field(min_length=1, max_length=128)
    owner_id: int = Field(gt=0, description="货主归属,必填,建档后不可改")
    material_spu: str = Field(default="", max_length=128)
    type: int = Field(default=3, ge=1, le=5, description="1成品,2半成品,3普通,4礼盒,5虚拟")
    cat_id: int = Field(default=0, ge=0)
    brand_id: int = Field(default=0, ge=0)
    color: str = Field(default="", max_length=64)
    size: str = Field(default="", max_length=64)
    same_code_group: str = Field(default="", max_length=64)
    kingdee_material_code: str = Field(default="", max_length=64, description="金蝶编码,买断货主建议必填")
    serial_number: int = Field(default=0, ge=0, le=1, description="SN码管理开关")
    storage_life_flag: int = Field(default=0, ge=0, le=1, description="效期管理开关")
    is_ctrl_store: int = Field(default=1, ge=0, le=1, description="库存管控开关:0不记账,1记账")
    omnichannel: int = Field(default=0, ge=0, le=1)
    is_o2o_sales: int = Field(default=0, ge=0, le=1)
    tax_rate: float = Field(default=0, ge=0, le=100)
    tax_name: str = Field(default="", max_length=64)
    tax_code: str = Field(default="", max_length=64)
    org_id: int = Field(default=0, ge=0, description="运营组织")
    remark: str = Field(default="", max_length=512)


class MaterialUpdate(BaseModel):
    """编辑契约：material_bn 与 owner_id 建档后不可改（改货主=资产转移，D04.05）"""

    material_name: str | None = Field(default=None, max_length=128)
    material_spu: str | None = Field(default=None, max_length=128)
    type: int | None = Field(default=None, ge=1, le=5)
    cat_id: int | None = Field(default=None, ge=0)
    brand_id: int | None = Field(default=None, ge=0)
    color: str | None = Field(default=None, max_length=64)
    size: str | None = Field(default=None, max_length=64)
    same_code_group: str | None = Field(default=None, max_length=64)
    kingdee_material_code: str | None = Field(default=None, max_length=64)
    serial_number: int | None = Field(default=None, ge=0, le=1)
    storage_life_flag: int | None = Field(default=None, ge=0, le=1)
    is_ctrl_store: int | None = Field(default=None, ge=0, le=1)
    omnichannel: int | None = Field(default=None, ge=0, le=1)
    is_o2o_sales: int | None = Field(default=None, ge=0, le=1)
    tax_rate: float = Field(default=0, ge=0, le=100)
    tax_name: str | None = Field(default=None, max_length=64)
    tax_code: str | None = Field(default=None, max_length=64)
    org_id: int | None = Field(default=None, ge=0)
    status: int | None = Field(default=None, ge=1, le=2)
    remark: str | None = Field(default=None, max_length=512)
    version: int


class MaterialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    owner_id: int
    material_bn: str
    material_bn_crc32: int
    material_name: str
    material_spu: str
    type: int
    cat_id: int
    cat_path: str
    brand_id: int
    color: str
    size: str
    same_code_group: str
    kingdee_material_code: str
    serial_number: int
    storage_life_flag: int
    is_ctrl_store: int
    omnichannel: int
    is_o2o_sales: int
    tax_rate: float
    tax_name: str
    tax_code: str
    org_id: int
    status: int
    source: str
    remark: str
    version: int
    create_time: datetime


# ============ 销售物料（FR-01）============

class SalesMaterialCreate(BaseModel):
    shop_id: int = Field(gt=0, description="所属店铺")
    sales_material_bn: str = Field(min_length=1, max_length=128, description="平台商品编码,店铺内唯一")
    sales_material_name: str = Field(min_length=1, max_length=255)
    spec_text: str = Field(default="", max_length=512, description="平台规格文本")
    sales_material_type: int = Field(
        default=1, ge=1, le=6, description="1普通,2组合,3赠品,4多选一,5礼盒,6福袋"
    )
    class_id: int = Field(default=0, ge=0, description="客户分类")
    tax_rate: float = Field(default=0, ge=0, le=100)
    tax_name: str = Field(default="", max_length=64)
    tax_code: str = Field(default="", max_length=64)
    org_id: int = Field(default=0, ge=0)
    visibled: int = Field(default=1, ge=0, le=1, description="上下架")
    source: str = Field(default="local", pattern="^(local|api|import|migration)$")


class SalesMaterialAutoCreate(BaseModel):
    """FR-01a 拉单自动建档入参（幂等：同店铺同编码只建一次）"""

    shop_id: int = Field(gt=0)
    sales_material_bn: str = Field(min_length=1, max_length=128)
    sales_material_name: str = Field(default="", max_length=255)
    spec_text: str = Field(default="", max_length=512)
    sales_material_type: int = Field(default=1, ge=1, le=6)


class SalesMaterialUpdate(BaseModel):
    sales_material_name: str | None = Field(default=None, max_length=255)
    spec_text: str | None = Field(default=None, max_length=512)
    sales_material_type: int | None = Field(default=None, ge=1, le=6)
    class_id: int | None = Field(default=None, ge=0)
    tax_rate: float | None = Field(default=None, ge=0, le=100)
    tax_name: str | None = Field(default=None, max_length=64)
    tax_code: str | None = Field(default=None, max_length=64)
    org_id: int | None = Field(default=None, ge=0)
    visibled: int | None = Field(default=None, ge=0, le=1)
    status: int | None = Field(default=None, ge=1, le=2)
    version: int


class SalesMaterialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    owner_id: int
    shop_id: int
    sales_material_bn: str
    sales_material_name: str
    spec_text: str
    sales_material_type: int
    bind_status: int
    class_id: int
    tax_rate: float
    tax_name: str
    tax_code: str
    org_id: int
    visibled: int
    status: int
    source: str
    version: int
    create_time: datetime


# ============ BOM 绑定（FR-03）============

class BomItemIn(BaseModel):
    bm_id: int = Field(gt=0, description="基础物料")
    bind_num: int = Field(default=1, ge=1, description="数量≥1")
    rate: float = Field(default=0, ge=0, le=100, description="价格贡献占比%,与fixed_price二选一")
    fixed_price: float = Field(default=0, ge=0, description="固定价,与rate二选一")


class BomBind(BaseModel):
    items: list[BomItemIn] = Field(min_length=1, description="绑定明细（1:N）")
    operator: str = Field(default="", max_length=64)


class BomItemOut(BaseModel):
    id: int
    bm_id: int
    material_bn: str
    material_name: str
    material_type: int
    bind_num: int
    rate: float
    fixed_price: float
    is_virtual: int


class BomVersionOut(BaseModel):
    id: int
    sm_id: int
    version_no: int
    status: int
    effective_time: datetime | None
    operator: str
    create_time: datetime
    items: list[BomItemOut] = Field(default_factory=list)


class BomCandidateOut(BaseModel):
    """FR-03d 自动绑定建议候选"""

    bm_id: int
    material_bn: str
    material_name: str
    owner_id: int
    score: float
    reason: str



# ============ 条码（FR-04：一品多码）============

class BarcodeCreate(BaseModel):
    barcode: str = Field(min_length=1, max_length=64, description="条码值,全局唯一")
    bm_id: int = Field(gt=0, description="归属基础物料")
    barcode_type: int = Field(default=1, ge=1, le=9, description="1厂商码,2店铺码,3WMS码,9其他")
    shop_id: int = Field(default=0, ge=0, description="店铺码时必填")


class BarcodeUpdate(BaseModel):
    barcode_type: int | None = Field(default=None, ge=1, le=9)
    shop_id: int | None = Field(default=None, ge=0)
    status: int | None = Field(default=None, ge=1, le=2)
    version: int


class BarcodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    owner_id: int
    barcode: str
    bm_id: int
    material_bn: str
    material_name: str
    barcode_type: int
    shop_id: int
    status: int
    version: int
    create_time: datetime
