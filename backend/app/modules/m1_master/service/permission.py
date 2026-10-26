"""权限范围解析服务（D10.03 FR-03 权限继承四步模型 + FR-08 缓存）

四步模型（商派 permission.php 逆向验证，卡淳重写）：
① 节点授权：org_data_permission(dim_type=org_node) 记录账户↔组织节点授权
② 子树展开：沿 org_path LIKE ',{node_id},%' 取子树，节点类型换算四维值
   shop节点→shop_ids / warehouse节点→branch_ids / owner_co节点→owner_ids / brand节点→brand_ids
③ 合并取并集：继承展开 ∪ 直接维度授权 ∪ 角色 custom 显式四维
④ 自动继承：新增子节点落在已授权子树内 → 事件驱动缓存失效重算（不物化冗余授权行）

缓存：Redis perm:scope:{account_id}，TTL 30min（FR-08a）；miss/故障降级实时计算（FR-08d）。
"""
import json
import logging
from dataclasses import dataclass, field

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AuthContext, system_scope
from app.models.account import (
    OrgAccountRole,
    OrgDataPermission,
    OrgRole,
)
from app.models.org import OrgNode, OrgNodeRelation
from app.models.shop import GwShop

logger = logging.getLogger("ktoms.permission.scope")

SCOPE_CACHE_TTL = 1800  # 30min（FR-08a）
SCOPE_CACHE_PREFIX = "perm:scope:"


@dataclass
class DataScope:
    """四维 scope 快照（FR-07c）"""

    tenant_id: int = 1
    all: bool = False
    owner_ids: list[int] = field(default_factory=list)
    shop_ids: list[int] = field(default_factory=list)
    branch_ids: list[int] = field(default_factory=list)
    brand_ids: list[int] = field(default_factory=list)
    source: str = ""  # 来源标记：inherit/direct/role_custom

    def to_json(self) -> str:
        return json.dumps({
            "tenant_id": self.tenant_id, "all": self.all,
            "owner_ids": self.owner_ids, "shop_ids": self.shop_ids,
            "branch_ids": self.branch_ids, "brand_ids": self.brand_ids,
            "source": self.source,
        }, ensure_ascii=False)

    @classmethod
    def from_json(cls, raw: str) -> "DataScope":
        d = json.loads(raw)
        return cls(
            tenant_id=d.get("tenant_id", 1), all=d.get("all", False),
            owner_ids=d.get("owner_ids", []), shop_ids=d.get("shop_ids", []),
            branch_ids=d.get("branch_ids", []), brand_ids=d.get("brand_ids", []),
            source=d.get("source", ""),
        )


class PermissionService:
    """权限范围解析（FR-07b getScope）"""

    def __init__(self, session: AsyncSession, redis: Redis | None = None):
        self.s = session
        self.r = redis

    @system_scope
    async def get_scope(self, account_id: int, tenant_id: int = 1) -> DataScope:
        """解析账户四维 scope（缓存优先，miss 实时计算并回填）"""
        if self.r is not None:
            cached = await self.r.get(f"{SCOPE_CACHE_PREFIX}{account_id}")
            if cached:
                raw = cached.decode() if isinstance(cached, bytes) else cached
                scope = DataScope.from_json(raw)
                scope.tenant_id = tenant_id
                return scope
        scope = await self._compute(account_id, tenant_id)
        if self.r is not None:
            try:
                await self.r.set(f"{SCOPE_CACHE_PREFIX}{account_id}", scope.to_json(), ex=SCOPE_CACHE_TTL)
            except Exception as e:  # Redis 故障降级：权限判定不失效（FR-08d）
                logger.warning("scope cache write failed, degrade to realtime: %s", e)
        return scope

    @system_scope
    async def _compute(self, account_id: int, tenant_id: int) -> DataScope:
        scope = DataScope(tenant_id=tenant_id)

        # 角色模式解析（FR-02c）：all / org_node / custom，账户 scope = 各角色并集
        roles = (await self.s.scalars(
            select(OrgRole)
            .join(OrgAccountRole, OrgAccountRole.role_id == OrgRole.id)
            .where(OrgAccountRole.account_id == account_id, OrgRole.is_deleted == 0)
        )).all()
        for role in roles:
            if role.data_scope_mode == "all":
                scope.all = True
                scope.source = "role_all"
                return scope
            if role.data_scope_mode == "custom" and role.custom_scope_json:
                for dim in ("owner_ids", "shop_ids", "branch_ids", "brand_ids"):
                    vals = role.custom_scope_json.get(dim) or []
                    target = getattr(scope, dim)
                    for v in vals:
                        if v not in target:
                            target.append(v)
                scope.source = "role_custom"

        # ① 节点授权（dim_type=org_node）
        grants = (await self.s.scalars(
            select(OrgDataPermission).where(
                OrgDataPermission.account_id == account_id,
                OrgDataPermission.status == 1,
                OrgDataPermission.is_deleted == 0,
            )
        )).all()

        node_ids = [g.dim_id for g in grants if g.dim_type == "org_node" and g.grant_scope != "self_only"]
        self_only_ids = [
            g.dim_id for g in grants
            if g.dim_type == "org_node" and g.grant_scope == "self_only"
        ]

        # ② 子树展开（沿 org_path 前缀索引，§5.1）
        if node_ids:
            await self._expand_nodes(scope, node_ids, inherit=True)
        if self_only_ids:
            await self._expand_nodes(scope, self_only_ids, inherit=False)

        # ③ 合并直接维度授权（点状授权，如单店临时支援）
        for g in grants:
            if g.dim_type == "shop" and g.dim_id not in scope.shop_ids:
                scope.shop_ids.append(g.dim_id)
            elif g.dim_type == "branch" and g.dim_id not in scope.branch_ids:
                scope.branch_ids.append(g.dim_id)
            elif g.dim_type == "owner" and g.dim_id not in scope.owner_ids:
                scope.owner_ids.append(g.dim_id)
            elif g.dim_type == "brand" and g.dim_id not in scope.brand_ids:
                scope.brand_ids.append(g.dim_id)
            if g.dim_type != "org_node":
                scope.source = scope.source or "direct"

        # 维度联动推导（只收窄语义的补全，§5.1 ②）
        await self._infer_dimensions(scope)
        return scope

    @system_scope
    async def _expand_nodes(self, scope: DataScope, node_ids: list[int], inherit: bool) -> None:
        """节点→四维换算（FR-03b）"""
        for nid in node_ids:
            node = await self.s.scalar(
                select(OrgNode).where(OrgNode.id == nid, OrgNode.is_deleted == 0)
            )
            if not node:
                continue
            # 取子树：自身 + (inherit 时) org_path 前缀匹配的后代
            if inherit:
                descendants = (await self.s.scalars(
                    select(OrgNode).where(
                        OrgNode.cat_path.like(f"%,{nid},%"),
                        OrgNode.is_deleted == 0,
                    )
                )).all()
            else:
                descendants = [node]
            for dn in descendants:
                if dn.node_type == "shop" and dn.ref_id and dn.ref_id not in scope.shop_ids:
                    scope.shop_ids.append(dn.ref_id)
                elif dn.node_type == "warehouse" and dn.ref_id and dn.ref_id not in scope.branch_ids:
                    scope.branch_ids.append(dn.ref_id)
                elif dn.node_type == "owner_co":
                    # 货主公司节点 → 归属该节点的货主（org_owner.org_node_id）
                    owner_ids = (await self.s.scalars(
                        select(_owner_id_col()).where(_owner_node_col() == dn.id)
                    )).all()
                    for oid in owner_ids:
                        if oid not in scope.owner_ids:
                            scope.owner_ids.append(oid)
                elif dn.node_type == "brand":
                    if dn.id not in scope.brand_ids:
                        scope.brand_ids.append(dn.id)
            if not scope.source:
                scope.source = "inherit"

    async def _infer_dimensions(self, scope: DataScope) -> None:
        """维度联动推导（§5.1 ② 末两行，只收窄语义的补全）

        - 店铺 → 其货主（订单 owner 过滤需要）
        - 货主 → 服务仓（org_node_relation rel_type=branch_owner，三元记账前提）
        """
        if scope.shop_ids:
            owners = (await self.s.scalars(
                select(GwShop.owner_id).where(GwShop.id.in_(scope.shop_ids))
            )).all()
            for oid in owners:
                if oid and oid not in scope.owner_ids:
                    scope.owner_ids.append(oid)
        if scope.owner_ids:
            # 仓节点 → 服务货主关系（rel_type=branch_owner：node_id=仓节点, rel_id=owner_id）
            rel_rows = (await self.s.execute(
                select(OrgNodeRelation.node_id, OrgNodeRelation.rel_id)
                .join(OrgNode, OrgNode.id == OrgNodeRelation.node_id)
                .where(
                    OrgNodeRelation.rel_type == "branch_owner",
                    OrgNodeRelation.rel_id.in_(scope.owner_ids),
                    OrgNodeRelation.status == 1,
                )
            )).all()
            for node_id, _rel_id in rel_rows:
                node = await self.s.scalar(
                    select(OrgNode).where(OrgNode.id == node_id, OrgNode.is_deleted == 0)
                )
                if node and node.ref_id and node.ref_id not in scope.branch_ids:
                    scope.branch_ids.append(node.ref_id)

    # ---------- 缓存失效（FR-08b） ----------

    async def invalidate_account(self, account_id: int) -> None:
        if self.r is not None:
            await self.r.delete(f"{SCOPE_CACHE_PREFIX}{account_id}")

    async def invalidate_all(self) -> None:
        """组织树/角色变更时全量失效（保守做法；M1 规模可接受，规模化后按受影响子树精准失效）"""
        if self.r is None:
            return
        keys = await self.r.keys(f"{SCOPE_CACHE_PREFIX}*")
        if keys:
            await self.r.delete(*keys)


def _owner_id_col():
    from app.models.org import OrgOwner
    return OrgOwner.id


def _owner_node_col():
    from app.models.org import OrgOwner
    return OrgOwner.org_node_id


async def build_auth_context(account_id: int, tenant_id: int, session: AsyncSession,
                             redis: Redis | None, is_superuser: bool) -> AuthContext:
    """解析 scope 并构造 AuthContext（供 deps 注入）"""
    scope = await PermissionService(session, redis).get_scope(account_id, tenant_id)
    return AuthContext(
        tenant_id=tenant_id,
        owner_ids=scope.owner_ids,
        shop_ids=scope.shop_ids,
        branch_ids=scope.branch_ids,
        brand_ids=scope.brand_ids,
        account_id=account_id,
        is_superuser=is_superuser,
        all_data=scope.all,
        scope_source=scope.source,
    )
