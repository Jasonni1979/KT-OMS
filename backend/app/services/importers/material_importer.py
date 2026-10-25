"""基础物料导入器（SRS-D04.01 FR-02d 批量导入 + D01.06 FR-03a ImporterInterface）

行级幂等：货号唯一约束冲突转行错误而非批失败（FR-03d）；
性能：prefetch 一次 IN 查询批量取已存在货号/货主/分类/品牌，杜绝 N+1。
"""
from typing import Any

from sqlalchemy import select

from app.core.importer import ColumnSpec, ImporterInterface, RowResult, TemplateSpec
from app.models.material import InvBrand, InvMaterial, InvMaterialCat
from app.models.org import OrgOwner
from app.services.import_center import ImportContext, register_importer, register_template

MATERIAL_TEMPLATE = TemplateSpec(
    template_code="material_import",
    template_name="基础物料导入模板",
    domain_code="D04",
    entity_ref="inv_material",
    importer_ref="material_importer",
    perm_point="material:import",
    columns=[
        ColumnSpec("货号", "material_bn", required=True, example="KC-MUG-001",
                   desc="全局唯一；建档后不可改。建议：品牌缩写+品类+规格"),
        ColumnSpec("物料名称", "material_name", required=True, example="陶瓷马克杯"),
        ColumnSpec("货主编码", "owner_code", required=True, example="owner_KC",
                   desc="货主归属，建档后不可改（改货主=资产转移 D04.05）"),
        ColumnSpec("物料属性", "material_type", value_type="enum",
                   enum_dict={"1": "成品", "2": "半成品", "3": "普通", "4": "礼盒", "5": "虚拟"},
                   example="3", desc="虚拟物料不参与实物库存记账"),
        ColumnSpec("分类名称", "cat_name", example="杯具", desc="基础物料分类（可选）"),
        ColumnSpec("品牌名称", "brand_name", example="凯淳", desc="品牌档案（可选）"),
        ColumnSpec("SPU款号", "material_spu", example="SPU-2026-001"),
        ColumnSpec("颜色", "color", example="米白"),
        ColumnSpec("尺码", "size", example="标准"),
        ColumnSpec("开票税率", "tax_rate", value_type="decimal", example="13",
                   desc="百分数值，如 13 表示 13%"),
        ColumnSpec("金蝶编码", "kingdee_material_code", example="KD-0001",
                   desc="买断货主建议必填（D08.06 推送金蝶）"),
        ColumnSpec("备注", "remark", example="首批导入"),
    ],
)

ERROR_OWNER_NOT_FOUND = "BIZ_OWNER_NOT_FOUND"
ERROR_OWNER_INACTIVE = "BIZ_OWNER_INACTIVE"
ERROR_BN_DUPLICATE = "BIZ_MATERIAL_BN_DUPLICATE"
ERROR_BN_DUPLICATE_IN_FILE = "BIZ_MATERIAL_BN_DUPLICATE_IN_FILE"
ERROR_CAT_NOT_FOUND = "BIZ_CATEGORY_NOT_FOUND"
ERROR_BRAND_NOT_FOUND = "BIZ_BRAND_NOT_FOUND"


class MaterialImporter(ImporterInterface):
    """基础物料导入"""

    template_code = "material_import"

    def support_mode(self) -> str:
        return "两者"

    async def prefetch(self, rows: list[dict[str, Any]], ctx: ImportContext) -> None:
        """批量预取：一次 IN 查询取已存在货号/货主/分类/品牌"""
        bns = {str(r.get("material_bn") or "").strip() for r in rows}
        bns.discard("")
        owner_codes = {str(r.get("owner_code") or "").strip() for r in rows}
        owner_codes.discard("")
        cat_names = {str(r.get("cat_name") or "").strip() for r in rows}
        cat_names.discard("")
        brand_names = {str(r.get("brand_name") or "").strip() for r in rows}
        brand_names.discard("")

        s = ctx.session
        existing_bns = set()
        if bns:
            existing_bns = set(
                (await s.scalars(
                    select(InvMaterial.material_bn).where(InvMaterial.material_bn.in_(bns))
                )).all()
            )
        owners: dict[str, OrgOwner] = {}
        if owner_codes:
            owners = {
                o.owner_code: o
                for o in (await s.scalars(
                    select(OrgOwner).where(OrgOwner.owner_code.in_(owner_codes))
                )).all()
            }
        cats: dict[str, InvMaterialCat] = {}
        if cat_names:
            cats = {
                c.cat_name: c
                for c in (await s.scalars(
                    select(InvMaterialCat).where(InvMaterialCat.cat_name.in_(cat_names))
                )).all()
            }
        brands: dict[str, InvBrand] = {}
        if brand_names:
            brands = {
                b.brand_name: b
                for b in (await s.scalars(
                    select(InvBrand).where(InvBrand.brand_name.in_(brand_names))
                )).all()
            }
        ctx.cache = {
            "existing_bns": existing_bns,
            "owners": owners,
            "cats": cats,
            "brands": brands,
            "file_bns": set(),
        }

    def row_validate(self, row: dict[str, Any], ctx: ImportContext) -> RowResult:
        cache = ctx.cache
        row_no = row.get("_row_no", 0)
        bn = str(row.get("material_bn") or "").strip()
        owner_code = str(row.get("owner_code") or "").strip()

        # 货号：库内已存在
        if bn in cache.get("existing_bns", set()):
            return RowResult(
                False, ERROR_BN_DUPLICATE, f"第{row_no}行 货号 {bn} 已存在"
            )
        # 货号：文件内重复
        file_bns = cache.setdefault("file_bns", set())
        if bn in file_bns:
            return RowResult(
                False, ERROR_BN_DUPLICATE_IN_FILE, f"第{row_no}行 货号 {bn} 在本文件内重复"
            )
        file_bns.add(bn)

        # 货主必须存在且合作中
        owner = cache.get("owners", {}).get(owner_code)
        if not owner:
            return RowResult(
                False, ERROR_OWNER_NOT_FOUND, f"第{row_no}行 货主编码 {owner_code} 不存在"
            )
        if owner.status != 1:
            return RowResult(
                False, ERROR_OWNER_INACTIVE,
                f"第{row_no}行 货主 {owner_code} 非合作中状态，不可建档",
            )

        # 分类/品牌（填了就必须存在）
        cat_name = str(row.get("cat_name") or "").strip()
        if cat_name and cat_name not in cache.get("cats", {}):
            return RowResult(
                False, ERROR_CAT_NOT_FOUND, f"第{row_no}行 分类 {cat_name} 不存在"
            )
        brand_name = str(row.get("brand_name") or "").strip()
        if brand_name and brand_name not in cache.get("brands", {}):
            return RowResult(
                False, ERROR_BRAND_NOT_FOUND, f"第{row_no}行 品牌 {brand_name} 不存在"
            )
        return RowResult(ok=True)

    async def commit_batch(self, rows: list[dict[str, Any]], ctx: ImportContext) -> None:
        """批次提交（事务边界内批量落库）"""
        from app.services.material import crc32_of

        cache = ctx.cache
        for row in rows:
            bn = str(row.get("material_bn") or "").strip()
            owner = cache["owners"][str(row.get("owner_code") or "").strip()]
            cat = cache.get("cats", {}).get(str(row.get("cat_name") or "").strip())
            brand = cache.get("brands", {}).get(str(row.get("brand_name") or "").strip())
            tax_rate = str(row.get("tax_rate") or "").strip()
            ctx.session.add(
                InvMaterial(
                    tenant_id=1,
                    owner_id=owner.id,
                    material_bn=bn,
                    material_bn_crc32=crc32_of(bn),
                    material_name=str(row.get("material_name") or "").strip(),
                    material_spu=str(row.get("material_spu") or "").strip(),
                    type=int(str(row.get("material_type") or "3").strip() or 3),
                    cat_id=cat.id if cat else 0,
                    cat_path=cat.cat_path if cat else "",
                    brand_id=brand.id if brand else 0,
                    color=str(row.get("color") or "").strip(),
                    size=str(row.get("size") or "").strip(),
                    kingdee_material_code=str(row.get("kingdee_material_code") or "").strip(),
                    tax_rate=float(tax_rate) if tax_rate else 0,
                    remark=str(row.get("remark") or "").strip(),
                    source="import",
                )
            )


register_template(MATERIAL_TEMPLATE)
register_importer(MaterialImporter())
