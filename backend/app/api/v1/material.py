"""物料域 API（SRS-D04.01 分类/品牌/基础物料）

路由前缀 /api/v1/material；数据权限由 M1a-3 中间件行级过滤自动生效
（inv_material 已注册 owner 维过滤）。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.response import ok
from app.modules.m2_stock.contract import (
    BarcodeService,
    BomService,
    BrandService,
    CategoryService,
    MaterialService,
    SalesMaterialService,
)
from app.schemas import material as sc

router = APIRouter(tags=["material-物料"])


# ============ 分类树（FR-05a）============

@router.get("/categories", summary="子分类懒加载（parent_id=0 取根层）")
async def list_categories(
    parent_id: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    cats = await CategoryService(session).children(parent_id)
    return ok([sc.MaterialCatOut.model_validate(c) for c in cats])


@router.get("/categories/all", summary="全部分类（树选择器用）")
async def list_all_categories(session: AsyncSession = Depends(get_session)):
    cats = await CategoryService(session).list_all()
    return ok([sc.MaterialCatOut.model_validate(c) for c in cats])


@router.post("/categories", summary="新增分类")
async def create_category(
    data: sc.MaterialCatCreate, session: AsyncSession = Depends(get_session)
):
    cat = await CategoryService(session).create(data)
    return ok(sc.MaterialCatOut.model_validate(cat))


@router.put("/categories/{cat_id}", summary="修改分类")
async def update_category(
    cat_id: int, data: sc.MaterialCatUpdate, session: AsyncSession = Depends(get_session)
):
    cat = await CategoryService(session).update(cat_id, data)
    return ok(sc.MaterialCatOut.model_validate(cat))


@router.post("/categories/{cat_id}/move", summary="移动分类（级联刷新子树路径）")
async def move_category(
    cat_id: int,
    new_parent_id: int = Query(ge=0, description="0=移到根层"),
    session: AsyncSession = Depends(get_session),
):
    cat = await CategoryService(session).move(cat_id, new_parent_id)
    return ok(sc.MaterialCatOut.model_validate(cat))


@router.delete("/categories/{cat_id}", summary="删除分类（有子分类/被引用则拒绝）")
async def delete_category(cat_id: int, session: AsyncSession = Depends(get_session)):
    await CategoryService(session).delete(cat_id)
    return ok(None)


# ============ 品牌（FR-05b）============

@router.get("/brands", summary="品牌列表")
async def list_brands(
    keyword: str | None = Query(default=None, max_length=64),
    session: AsyncSession = Depends(get_session),
):
    brands = await BrandService(session).list_all(keyword)
    return ok([sc.BrandOut.model_validate(b) for b in brands])


@router.post("/brands", summary="新增品牌")
async def create_brand(data: sc.BrandCreate, session: AsyncSession = Depends(get_session)):
    brand = await BrandService(session).create(data)
    return ok(sc.BrandOut.model_validate(brand))


@router.put("/brands/{brand_id}", summary="修改品牌")
async def update_brand(
    brand_id: int, data: sc.BrandUpdate, session: AsyncSession = Depends(get_session)
):
    brand = await BrandService(session).update(brand_id, data)
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
    mats = await MaterialService(session).list_all(keyword, owner_id, cat_id, brand_id)
    return ok([sc.MaterialOut.model_validate(m) for m in mats])


@router.post("/materials", summary="新建基础物料（货号唯一/货主必填）")
async def create_material(
    data: sc.MaterialCreate, session: AsyncSession = Depends(get_session)
):
    mat = await MaterialService(session).create(data)
    return ok(sc.MaterialOut.model_validate(mat))


@router.put("/materials/{material_id}", summary="修改基础物料（货号与货主不可改）")
async def update_material(
    material_id: int, data: sc.MaterialUpdate, session: AsyncSession = Depends(get_session)
):
    mat = await MaterialService(session).update(material_id, data)
    return ok(sc.MaterialOut.model_validate(mat))


# ============ 销售物料（FR-01）============

@router.get("/sales-materials", summary="销售物料列表")
async def list_sales_materials(
    keyword: str | None = Query(default=None, max_length=128),
    shop_id: int | None = Query(default=None, ge=1),
    bind_status: int | None = Query(default=None, ge=0, le=1),
    session: AsyncSession = Depends(get_session),
):
    sms = await SalesMaterialService(session).list_all(keyword, shop_id, bind_status)
    return ok([sc.SalesMaterialOut.model_validate(s) for s in sms])


@router.get("/sales-materials/unbound", summary="待绑定清单（FR-01c）")
async def list_unbound_sales_materials(
    shop_id: int | None = Query(default=None, ge=1),
    session: AsyncSession = Depends(get_session),
):
    sms = await SalesMaterialService(session).unbound_list(shop_id)
    return ok([sc.SalesMaterialOut.model_validate(s) for s in sms])


@router.post("/sales-materials", summary="手工建档销售物料（店铺内编码唯一）")
async def create_sales_material(
    data: sc.SalesMaterialCreate, session: AsyncSession = Depends(get_session)
):
    sm = await SalesMaterialService(session).create(data)
    return ok(sc.SalesMaterialOut.model_validate(sm))


@router.post("/sales-materials/auto", summary="拉单自动建档（幂等，FR-01a）")
async def auto_create_sales_material(
    data: sc.SalesMaterialAutoCreate, session: AsyncSession = Depends(get_session)
):
    sm, created = await SalesMaterialService(session).auto_create(data)
    return ok({"material": sc.SalesMaterialOut.model_validate(sm), "created": created})


@router.put("/sales-materials/{sm_id}", summary="修改销售物料")
async def update_sales_material(
    sm_id: int, data: sc.SalesMaterialUpdate, session: AsyncSession = Depends(get_session)
):
    sm = await SalesMaterialService(session).update(sm_id, data)
    return ok(sc.SalesMaterialOut.model_validate(sm))


# ============ BOM 绑定（FR-03）============

@router.get("/sales-materials/{sm_id}/bom", summary="当前生效 BOM")
async def get_current_bom(sm_id: int, session: AsyncSession = Depends(get_session)):
    bom_svc = BomService(session)
    cur = await bom_svc.current_version(sm_id)
    if not cur:
        return ok(None)
    return ok(await bom_svc.get_version(cur.id))


@router.get("/sales-materials/{sm_id}/bom/history", summary="BOM 版本历史（变更留痕）")
async def get_bom_history(sm_id: int, session: AsyncSession = Depends(get_session)):
    versions = await BomService(session).history(sm_id)
    return ok(versions)


@router.post("/sales-materials/{sm_id}/bom", summary="绑定基础物料（生成新版本）")
async def bind_bom(
    sm_id: int, data: sc.BomBind, session: AsyncSession = Depends(get_session)
):
    return ok(await BomService(session).bind(sm_id, data))


@router.delete("/sales-materials/{sm_id}/bom", summary="解绑（影响面确认由上层做）")
async def unbind_bom(sm_id: int, session: AsyncSession = Depends(get_session)):
    await BomService(session).unbind(sm_id)
    return ok(None)


@router.get("/sales-materials/{sm_id}/bom/candidates", summary="自动绑定建议（FR-03d）")
async def bom_candidates(
    sm_id: int,
    limit: int = Query(default=10, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
):
    cands = await BomService(session).suggest_candidates(sm_id, limit)
    return ok(cands)


# ============ 条码（FR-04：一品多码）============

@router.get("/barcodes", summary="条码列表")
async def list_barcodes(
    keyword: str | None = Query(default=None, max_length=64),
    bm_id: int | None = Query(default=None, ge=1),
    barcode_type: int | None = Query(default=None, ge=1, le=9),
    session: AsyncSession = Depends(get_session),
):
    bcs = await BarcodeService(session).list_all(keyword, bm_id, barcode_type)
    return ok(bcs)


@router.post("/barcodes", summary="登记条码（全局唯一，冲突提示归属物料）")
async def create_barcode(data: sc.BarcodeCreate, session: AsyncSession = Depends(get_session)):
    return ok(await BarcodeService(session).create(data))


@router.put("/barcodes/{barcode_id}", summary="修改条码（类型/店铺/状态）")
async def update_barcode(
    barcode_id: int, data: sc.BarcodeUpdate, session: AsyncSession = Depends(get_session)
):
    return ok(await BarcodeService(session).update(barcode_id, data))


@router.get("/barcodes/lookup", summary="条码反查（FR-04b：WMS回传/门店扫码/售后核销）")
async def lookup_barcode(
    barcode: str = Query(min_length=1, max_length=64),
    session: AsyncSession = Depends(get_session),
):
    return ok(await BarcodeService(session).lookup(barcode))
