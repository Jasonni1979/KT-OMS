"""仓 ↔ 可服务货主关系服务（SRS-D10.01 FR-07a / D09.01 消费 / D04.02 三元记账前提）

一个物理仓可存多货主货物；该关系启用后，该仓才能为对应货主开立三元记账行
（仓 + 货主 + 物料）。数据落 oms_org.org_node_relation：
    rel_type='branch_owner'、node_id=仓组织节点ID(oms_org.org_node.id)、rel_id=货主ID
唯一键 uk_org_node_relation(node_id, rel_type, rel_id) 天然防重复绑定。

规则（对齐 M1a-1 建仓校验 + D10.01 §5.1）：
  · 单一归属仓（ful_branch.owner_id 非空）只能服务该货主，绑定其他货主直接拒绝
  · 多货主仓（ful_branch.owner_id 为空）必须管控库存（is_ctrl=1），否则拒绝
  · 货主须处于「合作中」（status=1）方可绑定
  · 解绑走 status=2（停用）保留审计痕迹，不物理删除
"""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.branch import FulBranch
from app.models.org import OrgNode, OrgNodeRelation, OrgOwner
from app.schemas import master as sc

REL_TYPE_BRANCH_OWNER = "branch_owner"


class BranchOwnerService:
    """仓可服务货主关系（FR-07a）"""

    def __init__(self, session: AsyncSession):
        self.s = session

    # ---------- 内部校验 ----------

    async def _get_branch(self, branch_id: int) -> FulBranch:
        branch = await self.s.scalar(
            select(FulBranch).where(FulBranch.id == branch_id, FulBranch.is_deleted == 0)
        )
        if not branch:
            raise NotFoundError(f"仓库不存在: {branch_id}")
        if not branch.org_node_id:
            raise ConflictError("该仓未挂接组织树节点，无法配置可服务货主（数据异常）")
        return branch

    async def _get_owner(self, owner_id: int) -> OrgOwner:
        owner = await self.s.scalar(
            select(OrgOwner).where(OrgOwner.id == owner_id, OrgOwner.is_deleted == 0)
        )
        if not owner:
            raise NotFoundError(f"货主不存在: {owner_id}")
        return owner

    # ---------- 建仓联动 ----------

    async def bind_for_new_branch(self, branch: FulBranch, tenant_id: int = 1) -> None:
        """建仓时自动绑定：单一归属仓 → 其归属货主（多货主仓留待人工配置）"""
        if not branch.owner_id or not branch.org_node_id:
            return
        owner = await self._get_owner(branch.owner_id)
        self.s.add(
            OrgNodeRelation(
                tenant_id=tenant_id,
                node_id=branch.org_node_id,
                rel_type=REL_TYPE_BRANCH_OWNER,
                rel_id=owner.id,
                is_primary=1,
                status=1,
                create_op="system:branch_create",
            )
        )

    # ---------- 查询 ----------

    async def list_by_branch(self, branch_id: int) -> list[sc.BranchOwnerRelOut]:
        """查某仓的可服务货主（含停用关系，便于前端展示历史）"""
        branch = await self._get_branch(branch_id)
        rows = await self.s.execute(
            select(OrgNodeRelation, OrgOwner)
            .join(OrgOwner, OrgOwner.id == OrgNodeRelation.rel_id)
            .where(
                OrgNodeRelation.node_id == branch.org_node_id,
                OrgNodeRelation.rel_type == REL_TYPE_BRANCH_OWNER,
            )
            .order_by(OrgNodeRelation.status, OrgNodeRelation.id)
        )
        return [
            sc.BranchOwnerRelOut(
                id=rel.id,
                node_id=rel.node_id,
                branch_id=branch.id,
                branch_name=branch.branch_name,
                owner_id=owner.id,
                owner_code=owner.owner_code,
                owner_name=owner.owner_name,
                owner_type=owner.owner_type,
                owner_status=owner.status,
                is_primary=rel.is_primary,
                status=rel.status,
                create_time=rel.create_time,
            )
            for rel, owner in rows.all()
        ]

    async def list_by_owner(self, owner_id: int) -> list[sc.BranchOwnerRelOut]:
        """查某货主可服务的仓（D04.02 按货主隔离记账时用）"""
        owner = await self._get_owner(owner_id)
        rows = await self.s.execute(
            select(OrgNodeRelation, OrgNode, FulBranch)
            .join(OrgNode, OrgNode.id == OrgNodeRelation.node_id)
            .join(FulBranch, FulBranch.org_node_id == OrgNode.id)
            .where(
                OrgNodeRelation.rel_type == REL_TYPE_BRANCH_OWNER,
                OrgNodeRelation.rel_id == owner.id,
                OrgNodeRelation.status == 1,
                FulBranch.is_deleted == 0,
            )
            .order_by(OrgNodeRelation.id)
        )
        return [
            sc.BranchOwnerRelOut(
                id=rel.id,
                node_id=rel.node_id,
                branch_id=branch.id,
                branch_name=branch.branch_name,
                owner_id=owner.id,
                owner_code=owner.owner_code,
                owner_name=owner.owner_name,
                owner_type=owner.owner_type,
                owner_status=owner.status,
                is_primary=rel.is_primary,
                status=rel.status,
                create_time=rel.create_time,
            )
            for rel, _node, branch in rows.all()
        ]

    # ---------- 写入 ----------

    async def bind(
        self, branch_id: int, data: sc.BranchOwnerBind, tenant_id: int = 1
    ) -> list[sc.BranchOwnerRelOut]:
        """批量绑定可服务货主（幂等）"""
        branch = await self._get_branch(branch_id)
        # 单一归属仓：只能服务其归属货主
        if branch.owner_id:
            illegal = [oid for oid in data.owner_ids if oid != branch.owner_id]
            if illegal:
                raise ValidationError(
                    f"单一归属仓（归属货主 {branch.owner_id}）不可绑定其他货主: {illegal}"
                )
        else:
            # 多货主仓必须管控库存（三元记账前提）
            if branch.is_ctrl != 1:
                raise ValidationError("多货主仓必须管控库存（is_ctrl=1）后才可配置可服务货主")

        # 去重
        owner_ids = list(dict.fromkeys(data.owner_ids))
        # 校验货主存在且合作中
        owners: dict[int, OrgOwner] = {}
        for oid in owner_ids:
            owner = await self._get_owner(oid)
            if owner.status != 1:
                raise ValidationError(f"货主非合作中状态，不可绑定: {owner.owner_name}({owner.status})")
            owners[oid] = owner

        existing = (
            await self.s.scalars(
                select(OrgNodeRelation).where(
                    OrgNodeRelation.node_id == branch.org_node_id,
                    OrgNodeRelation.rel_type == REL_TYPE_BRANCH_OWNER,
                    OrgNodeRelation.rel_id.in_(owner_ids),
                )
            )
        ).all()
        existing_map = {rel.rel_id: rel for rel in existing}

        for oid in owner_ids:
            rel = existing_map.get(oid)
            if rel:
                # 幂等：已停用的关系重新启用
                if rel.status != 1:
                    rel.status = 1
                    rel.update_time = datetime.now()
                continue
            self.s.add(
                OrgNodeRelation(
                    tenant_id=tenant_id,
                    node_id=branch.org_node_id,
                    rel_type=REL_TYPE_BRANCH_OWNER,
                    rel_id=oid,
                    is_primary=1 if branch.owner_id == oid else 0,
                    status=1,
                    create_op=data.operator or "system",
                )
            )
        await self.s.commit()
        return await self.list_by_branch(branch_id)

    async def unbind(self, rel_id: int) -> None:
        """解绑（关系置停用，保留审计痕迹）"""
        rel = await self.s.scalar(
            select(OrgNodeRelation).where(
                OrgNodeRelation.id == rel_id,
                OrgNodeRelation.rel_type == REL_TYPE_BRANCH_OWNER,
            )
        )
        if not rel:
            raise NotFoundError(f"仓货主关系不存在: {rel_id}")
        if rel.status != 2:
            rel.status = 2
            rel.update_time = datetime.now()
            await self.s.commit()
