"""物料域服务层（SRS-D04.01）

第一批：分类树（FR-05a）+ 品牌（FR-05b）+ 基础物料（FR-02）

唯一性策略（依 DDL 实际索引）：
  · inv_material.material_bn        —— uk_inv_material_bn 全局唯一
  · inv_brand(brand_name, owner_id)  —— uk_inv_brand_name 同货主内唯一
  · inv_material_cat                —— **无唯一键** → 同级同名由应用层校验

⚠ 本文件在 P3（上下文体积治理）中拆分为多个文件；
   此处保留 re-export，**原有 import 路径全部保持可用**。
"""

import zlib

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.material import (
    InvBrand,
    InvMaterial,
    InvMaterialCat,
    InvSalesMaterial,
)
from app.models.shop import GwShop
from app.modules.m1_master.contract import OwnerService
from app.modules.m2_stock.service.material_barcode import (
    BarcodeService,
)
from app.modules.m2_stock.service.material_bom import (
    BomExpandItem,
    BomService,
    bom_expand,
)
from app.modules.m2_stock.service.material_catalog import (
    _SPEC_NOISE,  # noqa: F401
    MAX_CAT_LEVEL,
    BrandService,
    CategoryService,
    _extract_keywords,  # noqa: F401
)
from app.schemas import material as sc

__all__ = [
    "MAX_CAT_LEVEL",
    "crc32_of",
    "CategoryService",
    "BrandService",
    "MaterialService",
    "SalesMaterialService",
    "BomService",
    "BarcodeService",
    "BomExpandItem",
    "bom_expand",
]


def crc32_of(text: str) -> int:
    """货号 CRC32 辅助索引（商派惯例：大表查询加速）"""
    return zlib.crc32(text.encode("utf-8")) & 0xFFFFFFFF

class MaterialService:
    """基础物料档案（FR-02：owner_id 必填且建档后不可改；type=5 虚拟不参与记账）"""

    def __init__(self, session: AsyncSession):
        self.s = session

    async def _get(self, material_id: int) -> InvMaterial:
        mat = await self.s.scalar(
            select(InvMaterial).where(InvMaterial.id == material_id, InvMaterial.is_deleted == 0)
        )
        if not mat:
            raise NotFoundError(f"基础物料不存在: {material_id}")
        return mat

    async def create(self, data: sc.MaterialCreate, tenant_id: int = 1) -> InvMaterial:
        # 货号全局唯一（uk_inv_material_bn）
        dup = await self.s.scalar(
            select(InvMaterial.id).where(
                InvMaterial.material_bn == data.material_bn, InvMaterial.is_deleted == 0
            )
        )
        if dup:
            raise ConflictError(f"货号已存在: {data.material_bn}")

        # 货主必填且有效
        await OwnerService.assert_valid(self.s, data.owner_id)

        # 分类/品牌引用校验
        cat_path = ""
        if data.cat_id:
            cat = await self.s.scalar(
                select(InvMaterialCat).where(
                    InvMaterialCat.id == data.cat_id, InvMaterialCat.is_deleted == 0
                )
            )
            if not cat:
                raise ValidationError(f"分类不存在: {data.cat_id}")
            if cat.status != 1:
                raise ValidationError("分类已停用，不可建档")
            cat_path = cat.cat_path
        if data.brand_id:
            brand = await self.s.scalar(
                select(InvBrand).where(InvBrand.id == data.brand_id, InvBrand.is_deleted == 0)
            )
            if not brand:
                raise ValidationError(f"品牌不存在: {data.brand_id}")

        mat = InvMaterial(
            tenant_id=tenant_id,
            owner_id=data.owner_id,
            material_bn=data.material_bn,
            material_bn_crc32=crc32_of(data.material_bn),
            material_name=data.material_name,
            material_spu=data.material_spu,
            type=data.type,
            cat_id=data.cat_id,
            cat_path=cat_path,
            brand_id=data.brand_id,
            color=data.color,
            size=data.size,
            same_code_group=data.same_code_group,
            kingdee_material_code=data.kingdee_material_code,
            serial_number=data.serial_number,
            storage_life_flag=data.storage_life_flag,
            is_ctrl_store=data.is_ctrl_store,
            omnichannel=data.omnichannel,
            is_o2o_sales=data.is_o2o_sales,
            tax_rate=data.tax_rate,
            tax_name=data.tax_name,
            tax_code=data.tax_code,
            org_id=data.org_id,
            remark=data.remark,
        )
        self.s.add(mat)
        await self.s.commit()
        await self.s.refresh(mat)
        return mat

    async def update(self, material_id: int, data: sc.MaterialUpdate) -> InvMaterial:
        mat = await self._get(material_id)
        if mat.version != data.version:
            raise ConflictError("数据已被他人修改，请刷新后重试", code="OPTIMISTIC_LOCK")

        # 分类变更需同步冗余 cat_path
        if data.cat_id is not None and data.cat_id != mat.cat_id:
            if data.cat_id == 0:
                mat.cat_path = ""
            else:
                cat = await self.s.scalar(
                    select(InvMaterialCat).where(
                        InvMaterialCat.id == data.cat_id, InvMaterialCat.is_deleted == 0
                    )
                )
                if not cat:
                    raise ValidationError(f"分类不存在: {data.cat_id}")
                mat.cat_path = cat.cat_path
            mat.cat_id = data.cat_id

        for f in (
            "material_name", "material_spu", "type", "brand_id", "color", "size",
            "same_code_group", "kingdee_material_code", "serial_number",
            "storage_life_flag", "is_ctrl_store", "omnichannel", "is_o2o_sales",
            "tax_rate", "tax_name", "tax_code", "org_id", "status", "remark",
        ):
            v = getattr(data, f)
            if v is not None:
                setattr(mat, f, v)
        mat.version += 1
        await self.s.commit()
        await self.s.refresh(mat)
        return mat

    async def list_all(
        self,
        keyword: str | None = None,
        owner_id: int | None = None,
        cat_id: int | None = None,
        brand_id: int | None = None,
        tenant_id: int = 1,
    ) -> list[InvMaterial]:
        q = select(InvMaterial).where(
            InvMaterial.is_deleted == 0, InvMaterial.tenant_id == tenant_id
        )
        if keyword:
            like = f"%{keyword}%"
            q = q.where(
                (InvMaterial.material_bn.like(like))
                | (InvMaterial.material_name.like(like))
                | (InvMaterial.material_spu.like(like))
            )
        if owner_id:
            q = q.where(InvMaterial.owner_id == owner_id)
        if cat_id:
            q = q.where(InvMaterial.cat_id == cat_id)
        if brand_id:
            q = q.where(InvMaterial.brand_id == brand_id)
        rows = await self.s.scalars(q.order_by(InvMaterial.id))
        return list(rows)

    async def count(self, tenant_id: int = 1) -> int:
        """物料总数（概览用）"""
        return int(
            await self.s.scalar(
                select(func.count(InvMaterial.id)).where(
                    InvMaterial.is_deleted == 0, InvMaterial.tenant_id == tenant_id
                )
            )
            or 0
        )

class SalesMaterialService:
    """销售物料档案（FR-01）

    · FR-01a 自动建档幂等：同店铺同平台商品编码只建一次（uk_inv_sales_material_shop_bn）
    · FR-01c 待绑定清单：bind_status=0 的独立查询视图
    · FR-02 销售物料 owner_id 由 BOM 明细回填（未绑定时为 0，尚未归属任何货主）
    """

    def __init__(self, session: AsyncSession):
        self.s = session

    async def _get(self, sm_id: int) -> InvSalesMaterial:
        sm = await self.s.scalar(
            select(InvSalesMaterial).where(
                InvSalesMaterial.id == sm_id, InvSalesMaterial.is_deleted == 0
            )
        )
        if not sm:
            raise NotFoundError(f"销售物料不存在: {sm_id}")
        return sm

    async def _assert_shop(self, shop_id: int) -> None:
        shop = await self.s.scalar(
            select(GwShop).where(GwShop.id == shop_id, GwShop.is_deleted == 0)
        )
        if not shop:
            raise ValidationError(f"店铺不存在: {shop_id}")

    async def create(self, data: sc.SalesMaterialCreate, tenant_id: int = 1) -> InvSalesMaterial:
        await self._assert_shop(data.shop_id)
        dup = await self.s.scalar(
            select(InvSalesMaterial.id).where(
                InvSalesMaterial.shop_id == data.shop_id,
                InvSalesMaterial.sales_material_bn == data.sales_material_bn,
                InvSalesMaterial.is_deleted == 0,
            )
        )
        if dup:
            raise ConflictError(
                f"该店铺下已存在平台商品编码: {data.sales_material_bn}",
                data={"sales_material_id": dup},
            )
        sm = InvSalesMaterial(
            tenant_id=tenant_id,
            owner_id=0,
            shop_id=data.shop_id,
            sales_material_bn=data.sales_material_bn,
            sales_material_bn_crc32=crc32_of(data.sales_material_bn),
            sales_material_name=data.sales_material_name,
            spec_text=data.spec_text,
            sales_material_type=data.sales_material_type,
            bind_status=0,
            class_id=data.class_id,
            tax_rate=data.tax_rate,
            tax_name=data.tax_name,
            tax_code=data.tax_code,
            org_id=data.org_id,
            visibled=data.visibled,
            source=data.source,
        )
        self.s.add(sm)
        await self.s.commit()
        await self.s.refresh(sm)
        return sm

    async def auto_create(
        self, data: sc.SalesMaterialAutoCreate, tenant_id: int = 1
    ) -> tuple[InvSalesMaterial, bool]:
        """FR-01a 拉单自动建档（幂等）：返回 (物料, 是否新建)"""
        await self._assert_shop(data.shop_id)
        existing = await self.s.scalar(
            select(InvSalesMaterial).where(
                InvSalesMaterial.shop_id == data.shop_id,
                InvSalesMaterial.sales_material_bn == data.sales_material_bn,
                InvSalesMaterial.is_deleted == 0,
            )
        )
        if existing:
            return existing, False
        sm = InvSalesMaterial(
            tenant_id=tenant_id,
            owner_id=0,
            shop_id=data.shop_id,
            sales_material_bn=data.sales_material_bn,
            sales_material_bn_crc32=crc32_of(data.sales_material_bn),
            sales_material_name=data.sales_material_name or data.sales_material_bn,
            spec_text=data.spec_text,
            sales_material_type=data.sales_material_type,
            bind_status=0,
            source="api",
        )
        self.s.add(sm)
        await self.s.commit()
        await self.s.refresh(sm)
        return sm, True

    async def update(self, sm_id: int, data: sc.SalesMaterialUpdate) -> InvSalesMaterial:
        sm = await self._get(sm_id)
        if sm.version != data.version:
            raise ConflictError("数据已被他人修改，请刷新后重试", code="OPTIMISTIC_LOCK")
        for f in (
            "sales_material_name", "spec_text", "sales_material_type", "class_id",
            "tax_rate", "tax_name", "tax_code", "org_id", "visibled", "status",
        ):
            v = getattr(data, f)
            if v is not None:
                setattr(sm, f, v)
        sm.version += 1
        await self.s.commit()
        await self.s.refresh(sm)
        return sm

    async def list_all(
        self,
        keyword: str | None = None,
        shop_id: int | None = None,
        bind_status: int | None = None,
        tenant_id: int = 1,
    ) -> list[InvSalesMaterial]:
        q = select(InvSalesMaterial).where(
            InvSalesMaterial.is_deleted == 0, InvSalesMaterial.tenant_id == tenant_id
        )
        if keyword:
            like = f"%{keyword}%"
            q = q.where(
                (InvSalesMaterial.sales_material_bn.like(like))
                | (InvSalesMaterial.sales_material_name.like(like))
            )
        if shop_id:
            q = q.where(InvSalesMaterial.shop_id == shop_id)
        if bind_status is not None:
            q = q.where(InvSalesMaterial.bind_status == bind_status)
        rows = await self.s.scalars(q.order_by(InvSalesMaterial.id))
        return list(rows)

    async def unbound_list(
        self, shop_id: int | None = None, tenant_id: int = 1
    ) -> list[InvSalesMaterial]:
        """FR-01c 待绑定清单（未绑定销售物料）"""
        return await self.list_all(shop_id=shop_id, bind_status=0, tenant_id=tenant_id)
