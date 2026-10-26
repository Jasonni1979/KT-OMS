"""M2 BOM 展开 —— 组合品结构与递归展开"""

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.models.material import (
    InvBomItem,
    InvBomVersion,
    InvMaterial,
    InvSalesMaterial,
)
from app.modules.m2_stock.service.material_catalog import (
    _extract_keywords,
)
from app.schemas import material as sc


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