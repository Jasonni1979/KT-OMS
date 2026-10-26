"""M2 条码服务 —— 条码生成与扫码查询"""


from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.models.material import (
    InvBarcode,
    InvMaterial,
)
from app.schemas import material as sc


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
