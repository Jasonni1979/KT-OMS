"""物料域 API（SRS-D04.01 分类/品牌/基础物料）

路由前缀 /api/v1/material；数据权限由 M1a-3 中间件行级过滤自动生效
（inv_material 已注册 owner 维过滤）。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.response import ok
from app.schemas import material as sc
from app.services import material as svc

router = APIRouter(tags=["material-物料"])


# ============ 分类树（FR-05a）============

@router.get("/categories", summary="子分类懒加载（parent_id=0 取根层）")
async def list_categories(
    parent_id: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    cats = await svc.CategoryService(session).children(parent_id)
    return ok([sc.MaterialCatOut.model_validate(c) for c in cats])


@router.get("/categories/all", summary="全部分类（树选择器用）")
async def list_all_categories(session: AsyncSession = Depends(get_session)):
    cats = await svc.CategoryService(session).list_all()
    return ok([sc.MaterialCatOut.model_validate(c) for c in cats])


@router.post("/categories", summary="新增分类")
async def create_category(
    data: sc.MaterialCatCreate, session: AsyncSession = Depends(get_session)
):
    cat = await svc.CategoryService(session).create(data)
    return ok(sc.MaterialCatOut.model_validate(cat))


@router.put("/categories/{cat_id}", summary="修改分类")
async def update_category(
    cat_id: int, data: sc.MaterialCatUpdate, session: AsyncSession = Depends(get_session)
):
    cat = await svc.CategoryService(session).update(cat_id, data)
    return ok(sc.MaterialCatOut.model_validate(cat))


@router.post("/categories/{cat_id}/move", summary="移动分类（级联刷新子树路径）")
async def move_category(
    cat_id: int,
    new_parent_id: int = Query(ge=0, description="0=移到根层"),
    session: AsyncSession = Depends(get_session),
):
    cat = await svc.CategoryService(session).move(cat_id, new_parent_id)
    return ok(sc.MaterialCatOut.model_validate(cat))


@router.delete("/categories/{cat_id}", summary="删除分类（有子分类/被引用则拒绝）")
async def delete_category(cat_id: int, session: AsyncSession = Depends(get_session)):
    await svc.CategoryService(session).delete(cat_id)
    return ok(None)


# ============ 品牌（FR-05b）============

@router.get("/brands", summary="品牌列表")
async def list_brands(
    keyword: str | None = Query(default=None, max_length=64),
    session: AsyncSession = Depends(get_session),
):
    brands = await svc.BrandService(session).list(keyword)
    return ok([sc.BrandOut.model_validate(b) for b in brands])


@router.post("/brands", summary="新增品牌")
async def create_brand(data: sc.BrandCreate, session: AsyncSession = Depends(get_session)):
    brand = await svc.BrandService(session).create(data)
    return ok(sc.BrandOut.model_validate(brand))


@router.put("/brands/{brand_id}", summary="修改品牌")
async def update_brand(
    brand_id: int, data: sc.BrandUpdate, session: AsyncSession = Depends(get_session)
):
    brand = await svc.BrandService(session).update(brand_id, data)
    return ok(sc.BrandOut.model_validate(brand))


# ============ 基础物料（FR-02）============

@router.get("/materials", summary="基础物料列表")
async def list_materials(
    keyword: str | None = Query(default=None, max_length=64),
    owner_id: int | None = Query(default=None, ge=1),
    cat_id: int | None = Query(default=None, ge=0),
    brand_id: int | None = Query(default=None, ge=0),
    session: AsyncSession = Depends(get_session),
):
    mats = await svc.MaterialService(session).list(keyword, owner_id, cat_id, brand_id)
    return ok([sc.MaterialOut.model_validate(m) for m in mats])


@router.post("/materials", summary="新建基础物料（货号唯一/货主必填）")
async def create_material(
    data: sc.MaterialCreate, session: AsyncSession = Depends(get_session)
):
    mat = await svc.MaterialService(session).create(data)
    return ok(sc.MaterialOut.model_validate(mat))


@router.put("/materials/{material_id}", summary="修改基础物料（货号与货主不可改）")
async def update_material(
    material_id: int, data: sc.MaterialUpdate, session: AsyncSession = Depends(get_session)
):
    mat = await svc.MaterialService(session).update(material_id, data)
    return ok(sc.MaterialOut.model_validate(mat))
