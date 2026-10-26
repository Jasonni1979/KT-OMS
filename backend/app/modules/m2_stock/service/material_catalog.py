"""M2 商品目录 —— 类目与品牌（商品主数据的前置依赖）"""


from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.material import (
    InvBrand,
    InvMaterial,
    InvMaterialCat,
)
from app.models.org import OrgNode
from app.modules.m1_master.contract import OwnerService
from app.schemas import material as sc

MAX_CAT_LEVEL = 5

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
