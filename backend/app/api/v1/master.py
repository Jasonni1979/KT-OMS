"""档案域 API（D10.01 组织树/货主 + 店铺/仓库最小版）

路由前缀 /api/v1/master；写操作经统一响应封装；
数据权限：M1a-3 中间件全局接入后自动行级过滤（当前 tenant_id 固定=1 开发租户）。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.response import ok
from app.modules.m1_master.contract import (
    BranchOwnerService,
    BranchService,
    OrgService,
    OwnerService,
    ShopService,
    get_redis,
)
from app.schemas import master as sc

router = APIRouter(tags=["master-档案"])


# ============ 组织树 ============

@router.get("/org-nodes", summary="子节点懒加载（parent_id=0 取根层）")
async def list_org_nodes(
    parent_id: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    nodes = await OrgService(session).children(parent_id)
    return ok([sc.OrgNodeOut.model_validate(n) for n in nodes])


@router.get("/org-nodes/search", summary="按名称/编码搜索节点")
async def search_org_nodes(
    keyword: str = Query(min_length=1, max_length=64),
    session: AsyncSession = Depends(get_session),
):
    nodes = await OrgService(session).search(keyword)
    return ok([sc.OrgNodeOut.model_validate(n) for n in nodes])


@router.post("/org-nodes", summary="新增组织节点（层级矩阵校验）")
async def create_org_node(
    data: sc.OrgNodeCreate,
    session: AsyncSession = Depends(get_session),
):
    node = await OrgService(session).create_node(data)
    return ok(sc.OrgNodeOut.model_validate(node))


@router.put("/org-nodes/{node_id}", summary="修改节点（名称/排序/备注/停用，乐观锁）")
async def update_org_node(
    node_id: int,
    data: sc.OrgNodeUpdate,
    session: AsyncSession = Depends(get_session),
):
    node = await OrgService(session).update_node(node_id, data)
    return ok(sc.OrgNodeOut.model_validate(node))


@router.delete("/org-nodes/{node_id}", summary="软删节点（仅无关联停用节点）")
async def delete_org_node(node_id: int, session: AsyncSession = Depends(get_session)):
    await OrgService(session).delete_node(node_id)
    return ok(None)


# ============ 货主 ============

@router.get("/owners", summary="货主列表")
async def list_owners(
    keyword: str | None = Query(default=None, max_length=64),
    session: AsyncSession = Depends(get_session),
):
    owners = await OwnerService(session).list(keyword)
    return ok([sc.OwnerOut.model_validate(o) for o in owners])


@router.post("/owners", summary="新建货主（类型创建后不可改）")
async def create_owner(data: sc.OwnerCreate, session: AsyncSession = Depends(get_session)):
    owner = await OwnerService(session).create(data)
    return ok(sc.OwnerOut.model_validate(owner))


@router.put("/owners/{owner_id}", summary="修改货主（终止态只读拒绝）")
async def update_owner(
    owner_id: int,
    data: sc.OwnerUpdate,
    session: AsyncSession = Depends(get_session),
):
    owner = await OwnerService(session).update(owner_id, data)
    return ok(sc.OwnerOut.model_validate(owner))


# ============ 店铺（最小版） ============

@router.get("/shops", summary="店铺列表")
async def list_shops(
    keyword: str | None = Query(default=None, max_length=64),
    session: AsyncSession = Depends(get_session),
):
    redis = await get_redis()
    shops = await ShopService(session, redis).list(keyword)
    return ok([sc.ShopOut.model_validate(s) for s in shops])


@router.post("/shops", summary="新建店铺（联动挂组织树 shop 节点）")
async def create_shop(
    data: sc.ShopCreate,
    parent_node_id: int = Query(gt=0, description="挂载的 brand/owner_co 组织节点"),
    session: AsyncSession = Depends(get_session),
):
    redis = await get_redis()
    shop = await ShopService(session, redis).create(data, parent_node_id)
    return ok(sc.ShopOut.model_validate(shop))


@router.put("/shops/{shop_id}", summary="修改店铺")
async def update_shop(
    shop_id: int,
    data: sc.ShopUpdate,
    session: AsyncSession = Depends(get_session),
):
    redis = await get_redis()
    shop = await ShopService(session, redis).update(shop_id, data)
    return ok(sc.ShopOut.model_validate(shop))


# ============ 仓库（最小版） ============

@router.get("/branches", summary="仓库列表")
async def list_branches(
    keyword: str | None = Query(default=None, max_length=64),
    session: AsyncSession = Depends(get_session),
):
    redis = await get_redis()
    branches = await BranchService(session, redis).list(keyword)
    return ok([sc.BranchOut.model_validate(b) for b in branches])


@router.post("/branches", summary="新建仓库（联动挂组织树 warehouse 节点，直属根）")
async def create_branch(data: sc.BranchCreate, session: AsyncSession = Depends(get_session)):
    redis = await get_redis()
    branch = await BranchService(session, redis).create(data)
    return ok(sc.BranchOut.model_validate(branch))


@router.put("/branches/{branch_id}", summary="修改仓库")
async def update_branch(
    branch_id: int,
    data: sc.BranchUpdate,
    session: AsyncSession = Depends(get_session),
):
    redis = await get_redis()
    branch = await BranchService(session, redis).update(branch_id, data)
    return ok(sc.BranchOut.model_validate(branch))


# ============ 仓 ↔ 可服务货主（D10.01 FR-07a）============

@router.get("/branches/{branch_id}/owners", summary="某仓的可服务货主")
async def list_branch_owners(
    branch_id: int,
    session: AsyncSession = Depends(get_session),
):
    rels = await BranchOwnerService(session).list_by_branch(branch_id)
    return ok(rels)


@router.post("/branches/{branch_id}/owners", summary="绑定可服务货主（批量幂等）")
async def bind_branch_owners(
    branch_id: int,
    data: sc.BranchOwnerBind,
    session: AsyncSession = Depends(get_session),
):
    rels = await BranchOwnerService(session).bind(branch_id, data)
    return ok(rels)


@router.get("/owners/{owner_id}/branches", summary="某货主可服务的仓")
async def list_owner_branches(
    owner_id: int,
    session: AsyncSession = Depends(get_session),
):
    rels = await BranchOwnerService(session).list_by_owner(owner_id)
    return ok(rels)


@router.delete("/branch-owner-rels/{rel_id}", summary="解绑可服务货主（关系置停用）")
async def unbind_branch_owner(rel_id: int, session: AsyncSession = Depends(get_session)):
    await BranchOwnerService(session).unbind(rel_id)
    return ok(None)
