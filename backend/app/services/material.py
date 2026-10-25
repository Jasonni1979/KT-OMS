"""物料域服务层（SRS-D04.01）

第一批：分类树（FR-05a）+ 品牌（FR-05b）+ 基础物料（FR-02）

唯一性策略（依 DDL 实际索引）：
  · inv_material.material_bn        —— uk_inv_material_bn 全局唯一
  · inv_brand(brand_name, owner_id)  —— uk_inv_brand_name 同货主内唯一
  · inv_material_cat                —— **无唯一键** → 同级同名由应用层校验
"""
import zlib

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.material import InvBrand, InvMaterial, InvMaterialCat
from app.models.org import OrgNode
from app.schemas import material as sc
from app.services.master import OwnerService

MAX_CAT_LEVEL = 5


def crc32_of(text: str) -> int:
    """货号 CRC32 辅助索引（商派惯例：大表查询加速）"""
    return zlib.crc32(text.encode("utf-8")) & 0xFFFFFFFF


class CategoryService:
    """基础物料分类树（FR-05a：增删改/移动节点/路径维护）"""

    def __init__(self, session: AsyncSession):
        self.s = session

    async def _get(self, cat_id: int) -> InvMaterialCat:
        cat = await self.s.scalar(
            select(InvMaterialCat).where(InvMaterialCat.id == cat_id, InvMaterialCat.is_deleted == 0)
        )
        if not cat:
            raise NotFoundError(f"分类不存在: {cat_id}")
        return cat

    async def create(self, data: sc.MaterialCatCreate, tenant_id: int = 1) -> InvMaterialCat:
        # 同级同名校验（表无唯一键，应用层保证）
        dup = await self.s.scalar(
            select(InvMaterialCat.id).where(
                InvMaterialCat.parent_id == data.parent_id,
                InvMaterialCat.cat_name == data.cat_name,
                InvMaterialCat.is_deleted == 0,
            )
        )
        if dup:
            raise ConflictError(f"同级下已存在同名分类: {data.cat_name}")

        parent_path = ""
        level = 1
        if data.parent_id:
            parent = await self._get(data.parent_id)
            if parent.status != 1:
                raise ValidationError("父分类已停用，不可新增子分类")
            parent_path = parent.cat_path
            level = parent.cat_level + 1
            if level > MAX_CAT_LEVEL:
                raise ValidationError(f"分类层级超限（最大 {MAX_CAT_LEVEL} 层）")

        cat = InvMaterialCat(
            tenant_id=tenant_id,
            cat_name=data.cat_name,
            parent_id=data.parent_id,
            cat_path="",
            cat_level=level,
            sort_no=data.sort_no,
        )
        self.s.add(cat)
        await self.s.flush()
        cat.cat_path = f"{parent_path or '/'}{cat.id}/"
        await self.s.commit()
        await self.s.refresh(cat)
        return cat

    async def update(self, cat_id: int, data: sc.MaterialCatUpdate) -> InvMaterialCat:
        cat = await self._get(cat_id)
        if cat.version != data.version:
            raise ConflictError("数据已被他人修改，请刷新后重试", code="OPTIMISTIC_LOCK")
        if data.cat_name and data.cat_name != cat.cat_name:
            dup = await self.s.scalar(
                select(InvMaterialCat.id).where(
                    InvMaterialCat.parent_id == cat.parent_id,
                    InvMaterialCat.cat_name == data.cat_name,
                    InvMaterialCat.id != cat_id,
                    InvMaterialCat.is_deleted == 0,
                )
            )
            if dup:
                raise ConflictError(f"同级下已存在同名分类: {data.cat_name}")
            cat.cat_name = data.cat_name
        if data.sort_no is not None:
            cat.sort_no = data.sort_no
        if data.status is not None:
            cat.status = data.status
        cat.version += 1
        await self.s.commit()
        await self.s.refresh(cat)
        return cat

    async def move(self, cat_id: int, new_parent_id: int) -> InvMaterialCat:
        """移动节点（FR-05a）：级联刷新子树 cat_path"""
        cat = await self._get(cat_id)
        if new_parent_id == cat_id:
            raise ValidationError("不能移动到自身")
        if new_parent_id:
            # 防环：目标不能是自身子树
            subtree = await self._subtree_ids(cat_id)
            if new_parent_id in subtree:
                raise ValidationError("不能移动到自己的子分类下")
            parent = await self._get(new_parent_id)
            if parent.status != 1:
                raise ValidationError("目标父分类已停用")
            if parent.cat_level + 1 > MAX_CAT_LEVEL:
                raise ValidationError(f"分类层级超限（最大 {MAX_CAT_LEVEL} 层）")
            new_path = parent.cat_path
            new_level = parent.cat_level + 1
        else:
            new_path = ""
            new_level = 1

        old_path = cat.cat_path
        # 子树集合必须在改写自身路径之前取：_subtree_ids 依赖 cat_path 前缀匹配，
        # 若先改 cat.cat_path 则新前缀匹配不到旧子树（静默漏刷）
        descendants = await self._subtree_ids(cat_id)

        cat.parent_id = new_parent_id
        cat.cat_path = f"{new_path or '/'}{cat.id}/"
        cat.cat_level = new_level
        cat.version += 1

        # 级联刷新子树
        for did in descendants:
            row = await self.s.scalar(
                select(InvMaterialCat).where(InvMaterialCat.id == did, InvMaterialCat.is_deleted == 0)
            )
            if row is None:
                continue
            if row.cat_path.startswith(old_path):
                row.cat_path = f"{cat.cat_path}{row.cat_path[len(old_path):]}"
            row.cat_level = row.cat_path.strip("/").count("/") + 1
        await self.s.commit()
        await self.s.refresh(cat)
        return cat

    async def delete(self, cat_id: int) -> None:
        """删除分类（有子分类或被物料引用则拒绝）"""
        cat = await self._get(cat_id)
        child = await self.s.scalar(
            select(InvMaterialCat.id).where(
                InvMaterialCat.parent_id == cat_id, InvMaterialCat.is_deleted == 0
            )
        )
        if child:
            raise ConflictError("该分类下仍有子分类，不可删除")
        used = await self.s.scalar(
            select(InvMaterial.id).where(InvMaterial.cat_id == cat_id, InvMaterial.is_deleted == 0)
        )
        if used:
            raise ConflictError("该分类已被基础物料引用，不可删除（可改为停用）")
        cat.is_deleted = 1
        cat.status = 2
        cat.version += 1
        await self.s.commit()

    async def _subtree_ids(self, cat_id: int) -> set[int]:
        """子树节点 ID 集合（按 cat_path 前缀匹配）"""
        cat = await self._get(cat_id)
        rows = await self.s.scalars(
            select(InvMaterialCat.id).where(
                InvMaterialCat.cat_path.startswith(cat.cat_path),
                InvMaterialCat.id != cat_id,
                InvMaterialCat.is_deleted == 0,
            )
        )
        return set(rows.all())

    async def children(self, parent_id: int, tenant_id: int = 1) -> list[InvMaterialCat]:
        rows = await self.s.scalars(
            select(InvMaterialCat)
            .where(
                InvMaterialCat.parent_id == parent_id,
                InvMaterialCat.is_deleted == 0,
                InvMaterialCat.tenant_id == tenant_id,
            )
            .order_by(InvMaterialCat.sort_no, InvMaterialCat.id)
        )
        return list(rows)

    async def list_all(self, tenant_id: int = 1) -> list[InvMaterialCat]:
        rows = await self.s.scalars(
            select(InvMaterialCat)
            .where(InvMaterialCat.is_deleted == 0, InvMaterialCat.tenant_id == tenant_id)
            .order_by(InvMaterialCat.cat_level, InvMaterialCat.sort_no, InvMaterialCat.id)
        )
        return list(rows)


class BrandService:
    """品牌档案（FR-05b：owner_id=0 公共品牌；映射组织树 brand 节点）"""

    def __init__(self, session: AsyncSession):
        self.s = session

    async def create(self, data: sc.BrandCreate, tenant_id: int = 1) -> InvBrand:
        dup = await self.s.scalar(
            select(InvBrand.id).where(
                InvBrand.brand_name == data.brand_name,
                InvBrand.owner_id == data.owner_id,
                InvBrand.is_deleted == 0,
            )
        )
        if dup:
            raise ConflictError(f"该货主下已存在同名品牌: {data.brand_name}")
        if data.owner_id:
            await OwnerService.assert_valid(self.s, data.owner_id)
        if data.org_node_id:
            node = await self.s.scalar(
                select(OrgNode).where(
                    OrgNode.id == data.org_node_id,
                    OrgNode.node_type == "brand",
                    OrgNode.is_deleted == 0,
                )
            )
            if not node:
                raise ValidationError("组织节点必须是 brand 类型（FR-05b）")
        brand = InvBrand(
            tenant_id=tenant_id,
            owner_id=data.owner_id,
            brand_name=data.brand_name,
            brand_name_en=data.brand_name_en,
            org_node_id=data.org_node_id,
        )
        self.s.add(brand)
        await self.s.commit()
        await self.s.refresh(brand)
        return brand

    async def update(self, brand_id: int, data: sc.BrandUpdate) -> InvBrand:
        brand = await self.s.scalar(
            select(InvBrand).where(InvBrand.id == brand_id, InvBrand.is_deleted == 0)
        )
        if not brand:
            raise NotFoundError(f"品牌不存在: {brand_id}")
        if brand.version != data.version:
            raise ConflictError("数据已被他人修改，请刷新后重试", code="OPTIMISTIC_LOCK")
        if data.brand_name and data.brand_name != brand.brand_name:
            dup = await self.s.scalar(
                select(InvBrand.id).where(
                    InvBrand.brand_name == data.brand_name,
                    InvBrand.owner_id == brand.owner_id,
                    InvBrand.id != brand_id,
                    InvBrand.is_deleted == 0,
                )
            )
            if dup:
                raise ConflictError(f"该货主下已存在同名品牌: {data.brand_name}")
            brand.brand_name = data.brand_name
        if data.brand_name_en is not None:
            brand.brand_name_en = data.brand_name_en
        if data.status is not None:
            brand.status = data.status
        brand.version += 1
        await self.s.commit()
        await self.s.refresh(brand)
        return brand

    async def list(self, keyword: str | None = None, tenant_id: int = 1) -> list[InvBrand]:
        q = select(InvBrand).where(InvBrand.is_deleted == 0, InvBrand.tenant_id == tenant_id)
        if keyword:
            like = f"%{keyword}%"
            q = q.where((InvBrand.brand_name.like(like)) | (InvBrand.brand_name_en.like(like)))
        rows = await self.s.scalars(q.order_by(InvBrand.id))
        return list(rows)


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

    async def list(
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
