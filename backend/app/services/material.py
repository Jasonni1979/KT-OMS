"""物料域服务层（SRS-D04.01）

第一批：分类树（FR-05a）+ 品牌（FR-05b）+ 基础物料（FR-02）

唯一性策略（依 DDL 实际索引）：
  · inv_material.material_bn        —— uk_inv_material_bn 全局唯一
  · inv_brand(brand_name, owner_id)  —— uk_inv_brand_name 同货主内唯一
  · inv_material_cat                —— **无唯一键** → 同级同名由应用层校验
"""
import zlib
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.material import (
    InvBarcode,
    InvBomItem,
    InvBomVersion,
    InvBrand,
    InvMaterial,
    InvMaterialCat,
    InvSalesMaterial,
)
from app.models.org import OrgNode
from app.models.shop import GwShop
from app.schemas import material as sc
from app.services.master import OwnerService

MAX_CAT_LEVEL = 5

# 规格/颜色/尺码等修饰词（用于 FR-03d 关键词提取）
_SPEC_NOISE = ("款", "色", "码", "号", "规格", "尺码", "颜色", "装", "件", "双", "条", "包", "盒")


def _extract_keywords(name: str) -> list[str]:
    """从平台商品标题提取匹配关键词（FR-03d）

    平台标题通常是「商品名 颜色 尺码」空格分隔结构 → 先按空白取最长词（最可能是商品名），
    再补充去规格修饰词后的片段与整体去噪名；多关键词可提升召回。
    """
    import re

    raw = (name or "").strip()
    out: list[str] = []
    # ① 空白分词：取最长的非纯数字词
    tokens = [t for t in re.split(r"\s+", raw) if len(t) >= 2 and not t.isdigit()]
    if tokens:
        out.append(max(tokens, key=len))
    # ② 去规格修饰词后的分词片段
    cleaned = re.sub(r"(颜色|尺码|规格|款号|型号)", " ", raw)
    for part in re.split(r"[\s]+", re.sub(r"[\d\-_/\\.,;:()（）\[\]【】]+", " ", cleaned)):
        if len(part) >= 2:
            out.append(part)
    # ③ 整体去噪名（无空格标题的兜底）
    flat = re.sub(r"[\d\s\-_/\\.,;:()（）\[\]【】]+", "", raw)
    if len(flat) >= 2:
        out.append(flat)
    return list(dict.fromkeys(out))


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

    async def list_all(self, keyword: str | None = None, tenant_id: int = 1) -> list[InvBrand]:
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


class BomService:
    """销售物料 ↔ 基础物料绑定（FR-03）

    规则：
    · FR-03a 1:N 绑定，数量 ≥1，价格贡献占比 rate 与固定价 fixed_price 二选一
    · FR-03b 变更留痕：新版本 version_no+1，旧生效版转历史（status=3）
    · §5.2 嵌套约束：BOM 只允许一层；组合装的基础物料不得再作为另一组合装成员
    · §6.1 同货主：一条销售物料的全部明细必须同货主（跨货主组合走拆单 D03.04）
    · §6.3 占比合计：比例模式下 rate 合计必须 = 100%
    """

    def __init__(self, session: AsyncSession):
        self.s = session

    async def _get_sm(self, sm_id: int) -> InvSalesMaterial:
        sm = await self.s.scalar(
            select(InvSalesMaterial).where(
                InvSalesMaterial.id == sm_id, InvSalesMaterial.is_deleted == 0
            )
        )
        if not sm:
            raise NotFoundError(f"销售物料不存在: {sm_id}")
        return sm

    async def current_version(self, sm_id: int) -> InvBomVersion | None:
        """当前生效版本"""
        return await self.s.scalar(
            select(InvBomVersion).where(
                InvBomVersion.sm_id == sm_id,
                InvBomVersion.status == 2,
                InvBomVersion.is_deleted == 0,
            ).order_by(InvBomVersion.version_no.desc())
        )

    async def _items_of(self, bom_version_id: int) -> list[InvBomItem]:
        rows = await self.s.scalars(
            select(InvBomItem).where(
                InvBomItem.bom_version_id == bom_version_id,
                InvBomItem.is_deleted == 0,
            ).order_by(InvBomItem.id)
        )
        return list(rows)

    async def _is_combo(self, items: list[InvBomItem], materials: dict[int, InvMaterial]) -> bool:
        """组合装判定（§5.2）：合计数量>1 或含礼盒类型"""
        if sum(i.bind_num for i in items) > 1:
            return True
        return any(materials.get(i.bm_id) and materials[i.bm_id].type == 4 for i in items)

    async def _combo_sm_ids_with_bm(
        self, bm_ids: set[int], exclude_sm_id: int
    ) -> set[int]:
        """找出「已把给定基础物料作为组合装成员」的销售物料集合（嵌套约束用）"""
        if not bm_ids:
            return set()
        rows = await self.s.execute(
            select(InvBomItem.bom_version_id, InvBomItem.sm_id)
            .where(
                InvBomItem.bm_id.in_(bm_ids),
                InvBomItem.is_deleted == 0,
                InvBomItem.sm_id != exclude_sm_id,
            )
        )
        pairs = rows.all()
        if not pairs:
            return set()
        version_ids = {vid for vid, _ in pairs}
        vers = await self.s.scalars(
            select(InvBomVersion).where(
                InvBomVersion.id.in_(version_ids),
                InvBomVersion.status == 2,
                InvBomVersion.is_deleted == 0,
            )
        )
        combo_sms: set[int] = set()
        for bv in list(vers):
            items = await self._items_of(bv.id)
            if not items:
                continue
            bm_ids_in = {i.bm_id for i in items}
            mats = await self._load_materials(bm_ids_in)
            if await self._is_combo(items, mats):
                combo_sms.add(bv.sm_id)
        return combo_sms

    async def _load_materials(self, bm_ids: set[int]) -> dict[int, InvMaterial]:
        if not bm_ids:
            return {}
        rows = await self.s.scalars(
            select(InvMaterial).where(
                InvMaterial.id.in_(bm_ids), InvMaterial.is_deleted == 0
            )
        )
        return {m.id: m for m in rows}

    async def bind(
        self, sm_id: int, data: sc.BomBind, tenant_id: int = 1
    ) -> sc.BomVersionOut:
        """执行绑定（生成新版本，旧版转历史）"""
        sm = await self._get_sm(sm_id)

        # ① 明细基础物料必须存在
        bm_ids = {i.bm_id for i in data.items}
        materials = await self._load_materials(bm_ids)
        missing = bm_ids - set(materials)
        if missing:
            raise ValidationError(f"基础物料不存在: {sorted(missing)}")

        # ② 同货主校验（§6.1）
        owner_ids = {materials[bm].owner_id for bm in bm_ids}
        if len(owner_ids) > 1:
            raise ValidationError(
                f"同一销售物料的 BOM 明细必须同货主（跨货主组合走拆单 D03.04）: {sorted(owner_ids)}"
            )
        owner_id = next(iter(owner_ids))

        # ③ 数量与占比校验
        total_num = sum(i.bind_num for i in data.items)
        pure_fixed = all(i.fixed_price > 0 for i in data.items)
        if not pure_fixed:
            rate_sum = sum(i.rate for i in data.items if i.fixed_price <= 0)
            if abs(rate_sum - 100) > 0.01:
                raise ValidationError(f"价格贡献占比合计必须为 100%，当前 {rate_sum}%")

        # ④ 嵌套约束：组合装成员不得再作为另一组合装成员（§5.2）
        is_combo = total_num > 1 or any(
            materials[i.bm_id].type == 4 for i in data.items
        )
        if is_combo:
            conflict = await self._combo_sm_ids_with_bm(bm_ids, sm_id)
            if conflict:
                raise ValidationError(
                    f"组合装的基础物料不得再作为另一组合装成员（§5.2 嵌套约束），"
                    f"冲突销售物料: {sorted(conflict)}"
                )

        # ⑤ 版本化：旧生效版转历史，新建生效版
        old = await self.current_version(sm_id)
        version_no = 1
        if old:
            old.status = 3  # 历史
            version_no = old.version_no + 1
        max_no = await self.s.scalar(
            select(func.max(InvBomVersion.version_no)).where(InvBomVersion.sm_id == sm_id)
        )
        version_no = max(int(max_no or 0), version_no)

        bv = InvBomVersion(
            tenant_id=tenant_id,
            owner_id=owner_id,
            sm_id=sm_id,
            version_no=version_no,
            status=2,
            effective_time=datetime.now(),
            operator=data.operator or "system",
        )
        self.s.add(bv)
        await self.s.flush()

        for item in data.items:
            mat = materials[item.bm_id]
            self.s.add(
                InvBomItem(
                    tenant_id=tenant_id,
                    owner_id=owner_id,
                    bom_version_id=bv.id,
                    sm_id=sm_id,
                    bm_id=item.bm_id,
                    bind_num=item.bind_num,
                    rate=item.rate if item.fixed_price <= 0 else 0,
                    fixed_price=item.fixed_price,
                    is_virtual=1 if mat.type == 5 else 0,
                )
            )

        # ⑥ 销售物料回填：绑定状态 + 货主 + 组合装类型
        sm.bind_status = 1
        sm.owner_id = owner_id
        if is_combo and sm.sales_material_type == 1:
            sm.sales_material_type = 2
        sm.version += 1
        await self.s.commit()
        await self.s.refresh(bv)
        return await self.get_version(bv.id)

    async def unbind(self, sm_id: int) -> None:
        """解绑（FR-03c：上层需先做影响面确认——未审单订单按新 BOM 解析）"""
        sm = await self._get_sm(sm_id)
        cur = await self.current_version(sm_id)
        if cur:
            cur.status = 3
        sm.bind_status = 0
        sm.owner_id = 0
        sm.version += 1
        await self.s.commit()

    async def get_version(self, bom_version_id: int) -> sc.BomVersionOut:
        bv = await self.s.scalar(
            select(InvBomVersion).where(InvBomVersion.id == bom_version_id)
        )
        if not bv:
            raise NotFoundError(f"BOM 版本不存在: {bom_version_id}")
        items = await self._items_of(bv.id)
        materials = await self._load_materials({i.bm_id for i in items})
        return sc.BomVersionOut(
            id=bv.id,
            sm_id=bv.sm_id,
            version_no=bv.version_no,
            status=bv.status,
            effective_time=bv.effective_time,
            operator=bv.operator,
            create_time=bv.create_time,
            items=[
                sc.BomItemOut(
                    id=i.id,
                    bm_id=i.bm_id,
                    material_bn=materials[i.bm_id].material_bn if i.bm_id in materials else "",
                    material_name=materials[i.bm_id].material_name if i.bm_id in materials else "",
                    material_type=materials[i.bm_id].type if i.bm_id in materials else 3,
                    bind_num=i.bind_num,
                    rate=float(i.rate),
                    fixed_price=float(i.fixed_price),
                    is_virtual=i.is_virtual,
                )
                for i in items
            ],
        )

    async def history(self, sm_id: int) -> list[sc.BomVersionOut]:
        """版本历史（FR-03b 变更留痕）"""
        rows = await self.s.scalars(
            select(InvBomVersion).where(
                InvBomVersion.sm_id == sm_id, InvBomVersion.is_deleted == 0
            ).order_by(InvBomVersion.version_no.desc())
        )
        return [await self.get_version(bv.id) for bv in list(rows)]

    async def suggest_candidates(self, sm_id: int, limit: int = 10) -> list[sc.BomCandidateOut]:
        """FR-03d 自动绑定建议：按名称/规格相似度给候选基础物料"""
        sm = await self._get_sm(sm_id)
        keywords = _extract_keywords(sm.sales_material_name)
        if not keywords:
            return []
        matched: dict[int, InvMaterial] = {}
        for kw in keywords:
            rows = await self.s.scalars(
                select(InvMaterial).where(
                    InvMaterial.is_deleted == 0,
                    InvMaterial.status == 1,
                    InvMaterial.material_name.like(f"%{kw}%"),
                ).limit(limit * 3)
            )
            for m in list(rows):
                matched.setdefault(m.id, m)
        out: list[sc.BomCandidateOut] = []
        for mat in matched.values():
            score = 0.0
            reason = ""
            hit = next((k for k in keywords if k in mat.material_name), "")
            if mat.material_name == sm.sales_material_name:
                score, reason = 1.0, "名称完全一致"
            elif hit:
                score, reason = 0.7, f"名称包含「{hit}」"
            else:
                score, reason = 0.3, "名称部分匹配"
            # 规格命中加成（颜色/尺码出现在平台规格文本中）
            if sm.spec_text:
                if mat.color and mat.color in sm.spec_text:
                    score += 0.15
                    reason += " + 颜色匹配"
                if mat.size and mat.size in sm.spec_text:
                    score += 0.15
                    reason += " + 尺码匹配"
            out.append(
                sc.BomCandidateOut(
                    bm_id=mat.id,
                    material_bn=mat.material_bn,
                    material_name=mat.material_name,
                    owner_id=mat.owner_id,
                    score=round(min(score, 1.0), 2),
                    reason=reason,
                )
            )
        out.sort(key=lambda x: -x.score)
        return out[:limit]


class BarcodeService:
    """条码登记与反查（FR-04：条码 ↔ 基础物料 N:1；条码全局唯一）

    · FR-04a 同一条码全局唯一（uk_inv_barcode），冲突时拒绝并提示归属物料
    · FR-04b 条码反查：供 WMS 回传解析 / 门店扫码 / 售后核销调用
    """

    def __init__(self, session: AsyncSession):
        self.s = session

    async def _load_material(self, bm_id: int) -> InvMaterial:
        mat = await self.s.scalar(
            select(InvMaterial).where(InvMaterial.id == bm_id, InvMaterial.is_deleted == 0)
        )
        if not mat:
            raise ValidationError(f"基础物料不存在: {bm_id}")
        return mat

    async def create(self, data: sc.BarcodeCreate, tenant_id: int = 1) -> sc.BarcodeOut:
        mat = await self._load_material(data.bm_id)
        # 店铺码必须关联店铺
        if data.barcode_type == 2 and not data.shop_id:
            raise ValidationError("店铺码必须关联店铺（shop_id 必填）")
        # 全局唯一（uk_inv_barcode）→ 冲突时提示归属物料
        dup = await self.s.scalar(
            select(InvBarcode).where(
                InvBarcode.barcode == data.barcode, InvBarcode.is_deleted == 0
            )
        )
        if dup:
            owner_mat = await self._load_material(dup.bm_id)
            raise ConflictError(
                f"条码已存在，归属物料：{owner_mat.material_bn} {owner_mat.material_name}",
                data={
                    "existing_id": dup.id,
                    "bm_id": dup.bm_id,
                    "material_bn": owner_mat.material_bn,
                    "material_name": owner_mat.material_name,
                },
            )
        bc = InvBarcode(
            tenant_id=tenant_id,
            owner_id=mat.owner_id,
            barcode=data.barcode,
            bm_id=data.bm_id,
            barcode_type=data.barcode_type,
            shop_id=data.shop_id,
        )
        self.s.add(bc)
        await self.s.commit()
        await self.s.refresh(bc)
        return await self._to_out(bc)

    async def _to_out(self, bc: InvBarcode) -> sc.BarcodeOut:
        mat = await self._load_material(bc.bm_id)
        return sc.BarcodeOut(
            id=bc.id,
            owner_id=bc.owner_id,
            barcode=bc.barcode,
            bm_id=bc.bm_id,
            material_bn=mat.material_bn,
            material_name=mat.material_name,
            barcode_type=bc.barcode_type,
            shop_id=bc.shop_id,
            status=bc.status,
            version=bc.version,
            create_time=bc.create_time,
        )

    async def update(self, barcode_id: int, data: sc.BarcodeUpdate) -> sc.BarcodeOut:
        bc = await self.s.scalar(
            select(InvBarcode).where(InvBarcode.id == barcode_id, InvBarcode.is_deleted == 0)
        )
        if not bc:
            raise NotFoundError(f"条码不存在: {barcode_id}")
        if bc.version != data.version:
            raise ConflictError("数据已被他人修改，请刷新后重试", code="OPTIMISTIC_LOCK")
        if data.barcode_type is not None:
            bc.barcode_type = data.barcode_type
        if data.shop_id is not None:
            bc.shop_id = data.shop_id
        if data.status is not None:
            bc.status = data.status
        bc.version += 1
        await self.s.commit()
        await self.s.refresh(bc)
        return await self._to_out(bc)

    async def list_all(
        self,
        keyword: str | None = None,
        bm_id: int | None = None,
        barcode_type: int | None = None,
        tenant_id: int = 1,
    ) -> list[sc.BarcodeOut]:
        q = select(InvBarcode).where(
            InvBarcode.is_deleted == 0, InvBarcode.tenant_id == tenant_id
        )
        if keyword:
            like = f"%{keyword}%"
            q = q.where(
                (InvBarcode.barcode.like(like))
                | (InvMaterial.material_bn.like(like))
                | (InvMaterial.material_name.like(like))
            )
        if bm_id:
            q = q.where(InvBarcode.bm_id == bm_id)
        if barcode_type:
            q = q.where(InvBarcode.barcode_type == barcode_type)
        rows = await self.s.scalars(
            q.join(InvMaterial, InvMaterial.id == InvBarcode.bm_id).order_by(InvBarcode.id)
        )
        return [await self._to_out(bc) for bc in list(rows)]

    async def lookup(self, barcode: str) -> sc.BarcodeOut:
        """FR-04b 条码反查（WMS 回传解析 / 门店扫码 / 售后核销）"""
        bc = await self.s.scalar(
            select(InvBarcode).where(
                InvBarcode.barcode == barcode, InvBarcode.is_deleted == 0
            )
        )
        if not bc:
            raise NotFoundError(f"条码未登记: {barcode}")
        return await self._to_out(bc)


class BomExpandItem:
    """BOM 展开结果行（D03.01 FR-04d 快照）"""

    __slots__ = (
        "bm_id", "bm_number", "bm_name", "owner_id", "qty",
        "rate", "fixed_price", "is_virtual", "is_combo_member",
    )

    def __init__(
        self,
        bm_id: int,
        bm_number: str,
        bm_name: str,
        owner_id: int,
        qty: int,
        rate: float,
        fixed_price: float,
        is_virtual: bool,
        is_combo_member: bool,
    ):
        self.bm_id = bm_id
        self.bm_number = bm_number
        self.bm_name = bm_name
        self.owner_id = owner_id
        self.qty = qty
        self.rate = rate
        self.fixed_price = fixed_price
        self.is_virtual = is_virtual
        self.is_combo_member = is_combo_member

    def as_dict(self) -> dict:
        return {
            "bm_id": self.bm_id,
            "bm_number": self.bm_number,
            "bm_name": self.bm_name,
            "owner_id": self.owner_id,
            "qty": self.qty,
            "rate": self.rate,
            "fixed_price": self.fixed_price,
            "is_virtual": self.is_virtual,
            "is_combo_member": self.is_combo_member,
        }


async def bom_expand(
    session: AsyncSession, sm_id: int, qty: int
) -> tuple[list[BomExpandItem], int]:
    """BOM 展开快照（D03.01 FR-04d）

    返回 (展开明细, BOM 版本号)。组合装展开为多行基础物料（子行数量 = bind_num × qty）；
    未绑定 BOM 返回空列表（调用方按 parse_status=pending 软失败处理）。

    **快照固化**：档案后续变更不回溯（D04.01 §5.3 审计要求）。
    """
    bom = BomService(session)
    cur = await bom.current_version(sm_id)
    if not cur:
        return [], 0
    items = await bom._items_of(cur.id)
    if not items:
        return [], cur.version_no
    materials = await bom._load_materials({i.bm_id for i in items})
    out: list[BomExpandItem] = []
    for i in items:
        mat = materials.get(i.bm_id)
        if not mat:
            continue
        out.append(
            BomExpandItem(
                bm_id=mat.id,
                bm_number=mat.material_bn,
                bm_name=mat.material_name,
                owner_id=mat.owner_id,
                qty=int(i.bind_num) * qty,
                rate=float(i.rate),
                fixed_price=float(i.fixed_price),
                is_virtual=bool(i.is_virtual),
                is_combo_member=bool(i.is_virtual) or int(i.bind_num) > 1,
            )
        )
    return out, cur.version_no
