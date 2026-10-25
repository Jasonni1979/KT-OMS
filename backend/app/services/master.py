"""档案域服务层：组织树（SRS-D10.01 FR-01/02）+ 货主（FR-03/06）+ 店铺/仓库最小版

层级约束矩阵与 cat_path 维护严格按 SRS-D10.01 §5.1/§5.2；
移动（FR-02d）与店铺换货主（FR-07b）依赖 OA 审批（D10.05，MVP OUT 清单），M1 最小版不实现，
组织树初始化以 seed 脚本 + 新建为主（树结构低频变更）。
"""
import asyncio
import re

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.branch import FulBranch
from app.models.org import OrgNode, OrgOwner
from app.models.shop import GwShop
from app.schemas import master as sc

# ---------- FR-01b/§5.1 层级约束矩阵（父类型 → 允许子类型） ----------
CHILD_MATRIX: dict[str, tuple[str, ...]] = {
    "": ("group",),                                   # 无父 → 唯一根
    "group": ("brand", "owner_co", "dept", "warehouse"),
    "brand": ("owner_co", "shop"),
    "owner_co": ("shop", "reserved_dealer"),
    "shop": (),
    "warehouse": (),
    "dept": ("dept",),
    "reserved_dealer": (),
}
MAX_LEVEL = 8
TAX_NO_RE = re.compile(r"^[0-9A-HJ-NPQRTUWXY]{18}$")  # 统一社会信用代码 18 位


class OrgService:
    """组织树服务（FR-01/02）"""

    def __init__(self, session: AsyncSession):
        self.s = session

    async def _get_node(self, node_id: int) -> OrgNode:
        node = await self.s.scalar(
            select(OrgNode).where(OrgNode.id == node_id, OrgNode.is_deleted == 0)
        )
        if not node:
            raise NotFoundError(f"组织节点不存在: {node_id}")
        return node

    async def create_node(self, data: sc.OrgNodeCreate, tenant_id: int = 1) -> OrgNode:
        # 编码唯一
        dup = await self.s.scalar(select(OrgNode.id).where(OrgNode.org_code == data.org_code))
        if dup:
            raise ConflictError(f"组织编码已存在: {data.org_code}")
        # 父节点与层级矩阵校验
        parent: OrgNode | None = None
        if data.parent_id:
            parent = await self._get_node(data.parent_id)
            if parent.status != 1:
                raise ValidationError("父节点已停用，禁止挂载子节点")
            if parent.node_level >= MAX_LEVEL:
                raise ValidationError(f"层级深度超限（≤{MAX_LEVEL}）")
        allowed = CHILD_MATRIX.get(parent.node_type if parent else "", ())
        if data.node_type not in allowed:
            p_type = parent.node_type if parent else "（根）"
            raise ValidationError(
                f"层级约束违例: {p_type} 下不允许 {data.node_type}（允许: {allowed or '无'}）"
            )
        # group 单根约束（FR-01e）
        if data.node_type == "group":
            exists = await self.s.scalar(
                select(OrgNode.id).where(OrgNode.node_type == "group", OrgNode.is_deleted == 0)
            )
            if exists:
                raise ConflictError("group 根节点全系统唯一，已存在")
        # shop/warehouse 节点必须携带 ref_id 联动档案（FR-02a）
        if data.node_type in ("shop", "warehouse") and not data.ref_id:
            raise ValidationError(f"{data.node_type} 节点必须关联业务档案 ref_id（请先建店铺/仓库档案）")

        node = OrgNode(
            tenant_id=tenant_id,
            org_code=data.org_code,
            org_name=data.org_name,
            node_type=data.node_type,
            parent_id=data.parent_id,
            cat_path="",  # 占位，拿到 id 后补全
            node_level=(parent.node_level + 1) if parent else 1,
            ref_id=data.ref_id,
            sort_no=data.sort_no,
            remark=data.remark,
        )
        # 同父下不重名（应用层校验，FR-01c）
        dup_name = await self.s.scalar(
            select(OrgNode.id).where(
                OrgNode.parent_id == data.parent_id,
                OrgNode.org_name == data.org_name,
                OrgNode.is_deleted == 0,
            )
        )
        if dup_name:
            raise ConflictError(f"同父节点下名称重复: {data.org_name}")
        self.s.add(node)
        await self.s.flush()
        # §5.2 cat_path 写时补全：parent.cat_path + node.id + ','
        prefix = parent.cat_path if parent else ","
        node.cat_path = f"{prefix}{node.id},"
        await self.s.commit()
        await self.s.refresh(node)
        return node

    async def update_node(self, node_id: int, data: sc.OrgNodeUpdate) -> OrgNode:
        node = await self._get_node(node_id)
        if node.version != data.version:
            raise ConflictError("数据已被他人修改，请刷新后重试", code="OPTIMISTIC_LOCK")
        if data.org_name is not None and data.org_name != node.org_name:
            dup = await self.s.scalar(
                select(OrgNode.id).where(
                    OrgNode.parent_id == node.parent_id,
                    OrgNode.org_name == data.org_name,
                    OrgNode.is_deleted == 0,
                    OrgNode.id != node_id,
                )
            )
            if dup:
                raise ConflictError(f"同父节点下名称重复: {data.org_name}")
            node.org_name = data.org_name
        if data.sort_no is not None:
            node.sort_no = data.sort_no
        if data.remark is not None:
            node.remark = data.remark
        if data.status is not None:
            if data.status == 2:
                await self._assert_deactivatable(node)
            node.status = data.status
        node.version += 1
        await self.s.commit()
        await self.s.refresh(node)
        return node

    async def _assert_deactivatable(self, node: OrgNode) -> None:
        """FR-02b：有子节点或生效关联时禁止停用，返回引用清单"""
        refs: list[str] = []
        children = await self.s.scalar(
            select(func.count(OrgNode.id)).where(OrgNode.parent_id == node.id, OrgNode.is_deleted == 0)
        )
        if children:
            refs.append(f"子节点×{children}")
        if node.node_type == "owner_co":
            owners = await self.s.scalar(
                select(func.count(OrgOwner.id))
                .where(OrgOwner.org_node_id == node.id, OrgOwner.is_deleted == 0)
            )
            if owners:
                refs.append(f"货主档案×{owners}")
        if refs:
            raise ConflictError(f"节点存在生效关联，禁止停用: {'; '.join(refs)}", data={"refs": refs})

    async def delete_node(self, node_id: int) -> None:
        """FR-02c：仅无关联无子节点的停用节点可软删；根节点永不可删"""
        node = await self._get_node(node_id)
        if node.node_type == "group":
            raise ValidationError("根节点永不可删除")
        if node.status != 2:
            raise ValidationError("仅停用节点可删除，请先停用")
        await self._assert_deactivatable(node)  # 复用引用校验
        node.is_deleted = 1
        await self.s.commit()

    async def children(self, parent_id: int, tenant_id: int = 1) -> list[OrgNode]:
        """FR-02e 懒加载子树（0=根层）"""
        rows = await self.s.scalars(
            select(OrgNode)
            .where(OrgNode.parent_id == parent_id, OrgNode.is_deleted == 0, OrgNode.tenant_id == tenant_id)
            .order_by(OrgNode.sort_no, OrgNode.id)
        )
        return list(rows)

    async def search(self, keyword: str, tenant_id: int = 1) -> list[OrgNode]:
        """FR-02e 按名称/编码搜索"""
        like = f"%{keyword}%"
        rows = await self.s.scalars(
            select(OrgNode)
            .where(
                OrgNode.is_deleted == 0,
                OrgNode.tenant_id == tenant_id,
                (OrgNode.org_name.like(like)) | (OrgNode.org_code.like(like)),
            )
            .limit(50)
        )
        return list(rows)


class OwnerService:
    """货主服务（FR-03/06 最小版；暂停/终止的 OA 审批联动为 M4+，此处仅状态机与前置校验骨架）"""

    def __init__(self, session: AsyncSession):
        self.s = session

    @staticmethod
    async def assert_valid(session: AsyncSession, owner_id: int) -> OrgOwner:
        """FR-03d 全域校验服务：存在+状态可用（供各域写单据前调用）"""
        owner = await session.scalar(
            select(OrgOwner).where(OrgOwner.id == owner_id, OrgOwner.is_deleted == 0)
        )
        if not owner:
            raise NotFoundError(f"货主不存在: {owner_id}")
        if owner.status != 1:
            raise ValidationError(f"货主不可用（status={owner.status}: 2=暂停/3=终止）: {owner.owner_name}")
        return owner

    @staticmethod
    async def is_buyout(session: AsyncSession, owner_id: int) -> bool:
        """FR-03e 类型判定：仅凯淳买断可采购/计存货成本"""
        owner = await session.scalar(select(OrgOwner).where(OrgOwner.id == owner_id))
        return bool(owner and owner.owner_type == "KC_BUYOUT")

    async def create(self, data: sc.OwnerCreate, tenant_id: int = 1) -> OrgOwner:
        dup = await self.s.scalar(select(OrgOwner.id).where(OrgOwner.owner_code == data.owner_code))
        if dup:
            raise ConflictError(f"货主编码已存在: {data.owner_code}")
        # 归属节点必须是 owner_co 类型
        node = await self.s.scalar(
            select(OrgNode).where(OrgNode.id == data.org_node_id, OrgNode.is_deleted == 0)
        )
        if not node or node.node_type != "owner_co":
            raise ValidationError("归属组织节点必须为 owner_co（货主公司）类型")
        if data.tax_no and not TAX_NO_RE.match(data.tax_no):
            raise ValidationError("统一社会信用代码格式错误（18位）")
        owner = OrgOwner(
            tenant_id=tenant_id,
            owner_code=data.owner_code,
            owner_name=data.owner_name,
            owner_type=data.owner_type,
            org_node_id=data.org_node_id,
            tax_no=data.tax_no,
            contact_name=data.contact_name,
            remark=data.remark,
        )
        self.s.add(owner)
        await self.s.commit()
        await self.s.refresh(owner)
        return owner

    async def update(self, owner_id: int, data: sc.OwnerUpdate) -> OrgOwner:
        owner = await self.s.scalar(
            select(OrgOwner).where(OrgOwner.id == owner_id, OrgOwner.is_deleted == 0)
        )
        if not owner:
            raise NotFoundError(f"货主不存在: {owner_id}")
        if owner.version != data.version:
            raise ConflictError("数据已被他人修改，请刷新后重试", code="OPTIMISTIC_LOCK")
        if owner.status == 3:
            raise ValidationError("终止货主数据只读（FR-06d）")
        for f in ("owner_name", "tax_no", "contact_name", "remark"):
            v = getattr(data, f)
            if v is not None:
                setattr(owner, f, v)
        if data.tax_no and not TAX_NO_RE.match(data.tax_no):
            raise ValidationError("统一社会信用代码格式错误（18位）")
        owner.version += 1
        await self.s.commit()
        await self.s.refresh(owner)
        return owner

    async def list(self, keyword: str | None = None, tenant_id: int = 1) -> list[OrgOwner]:
        q = select(OrgOwner).where(OrgOwner.is_deleted == 0, OrgOwner.tenant_id == tenant_id)
        if keyword:
            like = f"%{keyword}%"
            q = q.where((OrgOwner.owner_name.like(like)) | (OrgOwner.owner_code.like(like)))
        rows = await self.s.scalars(q.order_by(OrgOwner.id))
        return list(rows)


class ShopService:
    """店铺档案最小版（建档自动挂组织树 shop 节点，FR-02a 联动；平台授权归 W4 D02.06）"""

    def __init__(self, session: AsyncSession, redis: Redis):
        self.s = session
        self.r = redis

    async def _next_bn(self, prefix: str, seq_key: str) -> str:
        n = await self.r.incr(seq_key)
        return f"{prefix}{n:06d}"

    async def create(self, data: sc.ShopCreate, parent_node_id: int, tenant_id: int = 1) -> GwShop:
        await OwnerService.assert_valid(self.s, data.owner_id)
        # 父节点校验：shop 只能挂 brand / owner_co（§5.1）
        parent = await self.s.scalar(
            select(OrgNode).where(OrgNode.id == parent_node_id, OrgNode.is_deleted == 0)
        )
        if not parent or parent.node_type not in ("brand", "owner_co"):
            raise ValidationError("店铺必须挂在 brand 或 owner_co 节点下（§5.1 层级矩阵）")
        shop = GwShop(
            tenant_id=tenant_id,
            owner_id=data.owner_id,
            shop_bn=await self._next_bn("S", "seq:shop_bn"),
            shop_name=data.shop_name,
            platform=data.platform,
            platform_shop_id=data.platform_shop_id,
            shop_type=data.shop_type,
            business_type=data.business_type,
        )
        self.s.add(shop)
        await self.s.flush()
        # 联动建组织树 shop 节点（org_code=SHOP_{id} 保唯一）+ 回填 ref_id/org_node_id
        node = OrgNode(
            tenant_id=tenant_id,
            org_code=f"SHOP_{shop.id}",
            org_name=data.shop_name,
            node_type="shop",
            parent_id=parent_node_id,
            cat_path="",
            node_level=parent.node_level + 1,
            ref_id=shop.id,
        )
        self.s.add(node)
        await self.s.flush()
        node.cat_path = f"{parent.cat_path}{node.id},"
        shop.org_node_id = node.id
        await self.s.commit()
        await self.s.refresh(shop)
        return shop

    async def update(self, shop_id: int, data: sc.ShopUpdate) -> GwShop:
        shop = await self.s.scalar(select(GwShop).where(GwShop.id == shop_id, GwShop.is_deleted == 0))
        if not shop:
            raise NotFoundError(f"店铺不存在: {shop_id}")
        if shop.version != data.version:
            raise ConflictError("数据已被他人修改，请刷新后重试", code="OPTIMISTIC_LOCK")
        if data.shop_name is not None:
            shop.shop_name = data.shop_name
        if data.status is not None:
            shop.status = data.status
        shop.version += 1
        await self.s.commit()
        await self.s.refresh(shop)
        return shop

    async def list(self, keyword: str | None = None, tenant_id: int = 1) -> list[GwShop]:
        q = select(GwShop).where(GwShop.is_deleted == 0, GwShop.tenant_id == tenant_id)
        if keyword:
            like = f"%{keyword}%"
            q = q.where((GwShop.shop_name.like(like)) | (GwShop.shop_bn.like(like)))
        rows = await self.s.scalars(q.order_by(GwShop.id))
        return list(rows)


class BranchService:
    """仓库档案最小版（D09.01 的 WMS 绑定/路由属性后置；建档自动挂组织树 warehouse 节点）"""

    def __init__(self, session: AsyncSession, redis: Redis):
        self.s = session
        self.r = redis

    async def create(self, data: sc.BranchCreate, tenant_id: int = 1) -> FulBranch:
        if data.owner_id is not None:
            await OwnerService.assert_valid(self.s, data.owner_id)
        # 多货主仓（owner_id 空）必须管控库存
        if data.owner_id is None and data.is_ctrl != 1:
            raise ValidationError("多货主仓必须管控库存（is_ctrl=1，三元记账前提）")
        branch = FulBranch(
            tenant_id=tenant_id,
            owner_id=data.owner_id,
            branch_bn=f"B{await self.r.incr('seq:branch_bn'):06d}",
            branch_name=data.branch_name,
            branch_type=data.branch_type,
            region_code=data.region_code,
            province=data.province,
            city=data.city,
            district=data.district,
            address=data.address,
            contact_name=data.contact_name,
            is_ctrl=data.is_ctrl,
            countable_flag=data.countable_flag,
            cutoff_time=data.cutoff_time,
            memo=data.memo,
        )
        self.s.add(branch)
        await self.s.flush()
        # 仓节点直属 group 根（§5.1：物理仓多货主共用）
        root = await self.s.scalar(
            select(OrgNode).where(OrgNode.node_type == "group", OrgNode.is_deleted == 0)
        )
        if not root:
            raise ConflictError("组织树根节点未初始化（请先运行 seed 脚本，FR-08a）")
        node = OrgNode(
            tenant_id=tenant_id,
            org_code=f"WH_{branch.id}",
            org_name=data.branch_name,
            node_type="warehouse",
            parent_id=root.id,
            cat_path="",
            node_level=root.node_level + 1,
            ref_id=branch.id,
        )
        self.s.add(node)
        await self.s.flush()
        node.cat_path = f"{root.cat_path}{node.id},"
        branch.org_node_id = node.id
        await self.s.commit()
        await self.s.refresh(branch)
        return branch

    async def update(self, branch_id: int, data: sc.BranchUpdate) -> FulBranch:
        branch = await self.s.scalar(
            select(FulBranch).where(FulBranch.id == branch_id, FulBranch.is_deleted == 0)
        )
        if not branch:
            raise NotFoundError(f"仓库不存在: {branch_id}")
        if branch.version != data.version:
            raise ConflictError("数据已被他人修改，请刷新后重试", code="OPTIMISTIC_LOCK")
        for f in ("branch_name", "region_code", "province", "city", "district",
                  "address", "contact_name", "is_ctrl", "countable_flag", "cutoff_time", "status", "memo"):
            v = getattr(data, f)
            if v is not None:
                setattr(branch, f, v)
        branch.version += 1
        await self.s.commit()
        await self.s.refresh(branch)
        return branch

    async def list(self, keyword: str | None = None, tenant_id: int = 1) -> list[FulBranch]:
        q = select(FulBranch).where(FulBranch.is_deleted == 0, FulBranch.tenant_id == tenant_id)
        if keyword:
            like = f"%{keyword}%"
            q = q.where((FulBranch.branch_name.like(like)) | (FulBranch.branch_bn.like(like)))
        rows = await self.s.scalars(q.order_by(FulBranch.id))
        return list(rows)


_redis: Redis | None = None
_redis_loop: object = None


async def get_redis() -> Redis:
    """发号器 Redis 连接（lazy 单例；event loop 变更时重建，避免测试跨 loop 报错）"""
    global _redis, _redis_loop
    loop = asyncio.get_running_loop()
    if _redis is None or _redis_loop is not loop:
        if _redis is not None:
            await _redis.aclose()
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
        _redis_loop = loop
    return _redis
