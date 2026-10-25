"""oms_stock 物料域模型（SRS-D04.01，映射真实 DDL，schema=oms_stock）

七张表：
- inv_material_cat  基础物料分类树（FR-05a，cat_path 冗余）
- inv_brand        品牌档案（FR-05b，owner_id=0 为公共品牌）
- inv_material     基础物料档案（FR-02，owner_id 必填且建档后不可改）
- inv_sales_material 销售物料档案（FR-01，店铺内平台商品编码唯一）
- inv_bom_version  BOM 版本（同销售物料仅一个生效版，变更 version+1 旧版转历史）
- inv_bom_item     BOM 明细（销售物料 → 基础物料 N 条，仅一层不递归）
- inv_barcode      条码（一品多码，条码全局唯一）
"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, Numeric, SmallInteger, String
from sqlalchemy.dialects.mysql import INTEGER as MySQLInteger
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class InvMaterialCat(Base):
    """基础物料分类树（FR-05a）"""

    __tablename__ = "inv_material_cat"
    __table_args__ = {"schema": "oms_stock"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    cat_name: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    cat_path: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    cat_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    sort_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, comment="1=启用,2=停用")
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class InvBrand(Base):
    """品牌档案（FR-05b：归属货主可空=公共品牌；映射组织树 brand 节点）"""

    __tablename__ = "inv_brand"
    __table_args__ = {"schema": "oms_stock"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="0=公共品牌;否则归属货主"
    )
    brand_name: Mapped[str] = mapped_column(String(128), nullable=False)
    brand_name_en: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    org_node_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="组织树 brand 节点映射"
    )
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class InvMaterial(Base):
    """基础物料档案（FR-02：owner_id 必填且建档后不可改；type=5 虚拟不参与记账）"""

    __tablename__ = "inv_material"
    __table_args__ = {"schema": "oms_stock"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="货主,必填")
    material_bn: Mapped[str] = mapped_column(String(64), nullable=False, comment="货号,全局唯一")
    material_bn_crc32: Mapped[int] = mapped_column(
        MySQLInteger(unsigned=True), nullable=False, default=0
    )
    material_name: Mapped[str] = mapped_column(String(128), nullable=False)
    material_spu: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    type: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=3, comment="1成品,2半成品,3普通,4礼盒,5虚拟"
    )
    cat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    cat_path: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    brand_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    color: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    size: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    same_code_group: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    kingdee_material_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    serial_number: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, comment="SN码管理开关:0=关,1=开"
    )
    storage_life_flag: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, comment="效期管理开关:0=关,1=开"
    )
    is_ctrl_store: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, comment="库存管控开关:0=不记账,1=记账"
    )
    omnichannel: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    is_o2o_sales: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    tax_rate: Mapped[float] = mapped_column(Numeric(9, 4), nullable=False, default=0)
    tax_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    tax_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    cos_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, comment="组织架构节点")
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, comment="运营组织")
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, comment="1=启用,2=停用")
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="local", comment="local/api/import/migration"
    )
    remark: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class InvSalesMaterial(Base):
    """销售物料档案（FR-01：平台商品编码店铺内唯一；bind_status 0未绑定/1已绑定）"""

    __tablename__ = "inv_sales_material"
    __table_args__ = {"schema": "oms_stock"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, index=True, comment="绑定后自基础物料回填"
    )
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="所属店铺")
    sales_material_bn: Mapped[str] = mapped_column(String(128), nullable=False, comment="平台商品编码")
    sales_material_bn_crc32: Mapped[int] = mapped_column(
        MySQLInteger(unsigned=True),
        nullable=False,
        default=0,
    )
    sales_material_name: Mapped[str] = mapped_column(String(255), nullable=False)
    spec_text: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    sales_material_type: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=1,
        comment="1普通,2组合,3赠品,4多选一,5礼盒,6福袋",
    )
    bind_status: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, comment="0未绑定,1已绑定"
    )
    class_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, comment="客户分类")
    tax_rate: Mapped[float] = mapped_column(Numeric(9, 4), nullable=False, default=0)
    tax_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    tax_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    org_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    visibled: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, comment="上下架")
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, comment="1正常,2已停用")
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="local", comment="local/api/import/migration"
    )
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class InvBomVersion(Base):
    """BOM 版本（FR-03b：同一销售物料仅一个生效版；变更 version_no+1，旧版转历史）"""

    __tablename__ = "inv_bom_version"
    __table_args__ = {"schema": "oms_stock"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, comment="冗余自销售物料")
    sm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="销售物料")
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, comment="1草稿,2生效,3历史"
    )
    effective_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    operator: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class InvBomItem(Base):
    """BOM 明细（FR-03a：1 销售物料 → N 基础物料；仅一层不递归；同货主）"""

    __tablename__ = "inv_bom_item"
    __table_args__ = {"schema": "oms_stock"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    bom_version_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    sm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="冗余加速")
    bm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="基础物料")
    bind_num: Mapped[int] = mapped_column(Integer, nullable=False, default=1, comment="数量≥1")
    rate: Mapped[float] = mapped_column(
        Numeric(9, 4), nullable=False, default=0, comment="价格贡献占比%,与fixed_price二选一(0=未用)"
    )
    fixed_price: Mapped[float] = mapped_column(
        Numeric(18, 4), nullable=False, default=0, comment="固定价,与rate二选一(0=未用)"
    )
    is_virtual: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class InvBarcode(Base):
    """条码（一品多码 FR-04：条码全局唯一，冲突拒绝并提示归属物料）"""

    __tablename__ = "inv_barcode"
    __table_args__ = {"schema": "oms_stock"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    barcode: Mapped[str] = mapped_column(String(64), nullable=False, comment="全局唯一")
    bm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True, comment="归属基础物料")
    barcode_type: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1, comment="1厂商码,2店铺码,3WMS码,9其他"
    )
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, comment="店铺码时填")
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
