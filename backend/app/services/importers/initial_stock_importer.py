"""期初库存导入器 + 期初建账（SRS-D04.04 §5.4 + D01.06）

期初建账语义（§5.4）：
- 按「仓 × 物料 × 货主」导入期初余额（含五口径拆分：实际/锁定/在途/次品）
- 生成单据（inv_io_bill，bill_type=opening_in，source=import）+ 单据明细 + 记账行
  （inv_stock_ledger，五口径余额起点快照 = D04.02 §5.3 的 S0）
- 期初单据不参与结算（inv_io_bill_type.opening_in 的 settle_rel=0）

M1b 阶段说明：日常增减记账与对账由 M1b-3（D04.02）承担；期初因是「起点快照」，
在本模块直接落记账行，保证期初建账后余额立即可见。
"""
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from app.core.importer import ColumnSpec, ImporterInterface, RowResult, TemplateSpec
from app.models.branch import FulBranch
from app.models.material import InvMaterial
from app.models.org import OrgNodeRelation, OrgOwner
from app.models.stock import (
    InvIoBill,
    InvIoBillItem,
    InvStockChangeLog,
    InvStockLedger,
)
from app.services.import_center import ImportContext, register_importer, register_template

INITIAL_TEMPLATE = TemplateSpec(
    template_code="initial_stock_import",
    template_name="期初库存导入模板",
    domain_code="D04",
    entity_ref="inv_stock_ledger",
    importer_ref="initial_stock_importer",
    perm_point="stock:initial_import",
    columns=[
        ColumnSpec("仓库编码", "branch_bn", required=True, example="B000001",
                   desc="仓库档案编码（ful_branch.branch_bn）"),
        ColumnSpec("货号", "material_bn", required=True, example="KC-MUG-001",
                   desc="基础物料货号（必须已建档）"),
        ColumnSpec("货主编码", "owner_code", required=True, example="owner_KC",
                   desc="该仓必须可服务此货主（M1b-0 仓货主关系）"),
        ColumnSpec("实际库存", "store", required=True, value_type="int", example="100",
                   desc="实际库存（含锁定与次品）"),
        ColumnSpec("锁定库存", "freeze", value_type="int", example="0",
                   desc="已预占未出库；恒 ≤ 实际库存"),
        ColumnSpec("在途库存", "arrive_store", value_type="int", example="0"),
        ColumnSpec("次品库存", "defective", value_type="int", example="0",
                   desc="不良品实物，不参与可售"),
        ColumnSpec("安全库存", "safe_store", value_type="int", example="0"),
        ColumnSpec("单位成本", "unit_cost", value_type="decimal", example="19.90"),
        ColumnSpec("批次号", "batch_no", example="B20261001"),
        ColumnSpec("效期", "expire_date", value_type="date", example="2028-10-01"),
    ],
)

ERROR_BRANCH_NOT_FOUND = "BIZ_BRANCH_NOT_FOUND"
ERROR_MATERIAL_NOT_FOUND = "BIZ_MATERIAL_NOT_FOUND"
ERROR_OWNER_NOT_FOUND = "BIZ_OWNER_NOT_FOUND"
ERROR_BRANCH_OWNER_NOT_ALLOWED = "BIZ_BRANCH_OWNER_NOT_ALLOWED"
ERROR_FREEZE_GT_STORE = "BIZ_FREEZE_GT_STORE"
ERROR_NEGATIVE_QTY = "BIZ_NEGATIVE_QTY"
ERROR_DUPLICATE_KEY = "BIZ_DUPLICATE_TERNARY_KEY"
ERROR_LEDGER_EXISTS = "BIZ_LEDGER_ALREADY_EXISTS"


class InitialStockImporter(ImporterInterface):
    """期初库存导入 + 期初建账"""

    template_code = "initial_stock_import"

    def support_mode(self) -> str:
        return "整任务重跑"

    async def prefetch(self, rows: list[dict[str, Any]], ctx: ImportContext) -> None:
        s = ctx.session
        branch_bns = {str(r.get("branch_bn") or "").strip() for r in rows}
        branch_bns.discard("")
        mat_bns = {str(r.get("material_bn") or "").strip() for r in rows}
        mat_bns.discard("")
        owner_codes = {str(r.get("owner_code") or "").strip() for r in rows}
        owner_codes.discard("")

        branches = {
            b.branch_bn: b
            for b in (await s.scalars(
                select(FulBranch).where(FulBranch.branch_bn.in_(branch_bns))
            )).all()
        } if branch_bns else {}
        materials = {
            m.material_bn: m
            for m in (await s.scalars(
                select(InvMaterial).where(InvMaterial.material_bn.in_(mat_bns))
            )).all()
        } if mat_bns else {}
        owners = {
            o.owner_code: o
            for o in (await s.scalars(
                select(OrgOwner).where(OrgOwner.owner_code.in_(owner_codes))
            )).all()
        } if owner_codes else {}

        # 仓 ↔ 可服务货主关系（M1b-0 关系表：node_id=仓节点, rel_type=branch_owner）
        branch_ids = [b.id for b in branches.values()]
        allowed: dict[tuple[int, int], bool] = {}
        if branch_ids:
            rels = (await s.execute(
                select(OrgNodeRelation.node_id, OrgNodeRelation.rel_id)
                .where(
                    OrgNodeRelation.rel_type == "branch_owner",
                    OrgNodeRelation.status == 1,
                    OrgNodeRelation.node_id.in_(
                        select(FulBranch.org_node_id).where(FulBranch.id.in_(branch_ids))
                    ),
                )
            )).all()
            for node_id, owner_id in rels:
                branch = next((b for b in branches.values() if b.org_node_id == node_id), None)
                if branch:
                    allowed[(branch.id, owner_id)] = True

        ctx.cache = {
            "branches": branches,
            "materials": materials,
            "owners": owners,
            "allowed": allowed,
            "seen_keys": set(),
        }

    def row_validate(self, row: dict[str, Any], ctx: ImportContext) -> RowResult:
        cache = ctx.cache
        row_no = row.get("_row_no", 0)
        branch = cache["branches"].get(str(row.get("branch_bn") or "").strip())
        if not branch:
            return RowResult(
                False, ERROR_BRANCH_NOT_FOUND,
                f"第{row_no}行 仓库 {row.get('branch_bn')} 不存在",
            )
        mat = cache["materials"].get(str(row.get("material_bn") or "").strip())
        if not mat:
            return RowResult(
                False, ERROR_MATERIAL_NOT_FOUND,
                f"第{row_no}行 货号 {row.get('material_bn')} 不存在（需先建基础物料档案）",
            )
        owner = cache["owners"].get(str(row.get("owner_code") or "").strip())
        if not owner:
            return RowResult(
                False, ERROR_OWNER_NOT_FOUND,
                f"第{row_no}行 货主编码 {row.get('owner_code')} 不存在",
            )
        # 三元记账前提：该仓必须可服务此货主
        if not cache["allowed"].get((branch.id, owner.id)):
            return RowResult(
                False, ERROR_BRANCH_OWNER_NOT_ALLOWED,
                f"第{row_no}行 仓库 {branch.branch_bn} 未配置可服务货主 {owner.owner_code}",
            )
        # 数量校验
        store = _to_int(row.get("store"))
        freeze = _to_int(row.get("freeze"))
        arrive = _to_int(row.get("arrive_store"))
        defective = _to_int(row.get("defective"))
        if min(store, freeze, arrive, defective) < 0:
            return RowResult(
                False, ERROR_NEGATIVE_QTY, f"第{row_no}行 库存数量不可为负"
            )
        if freeze > store:
            return RowResult(
                False, ERROR_FREEZE_GT_STORE,
                f"第{row_no}行 锁定库存 {freeze} 不得大于实际库存 {store}",
            )
        # 文件内三元键重复
        key = (branch.id, mat.id, owner.id)
        seen = cache.setdefault("seen_keys", set())
        if key in seen:
            return RowResult(
                False, ERROR_DUPLICATE_KEY,
                f"第{row_no}行 仓×物料×货主 三元键重复（同一组合只能出现一次）",
            )
        seen.add(key)
        return RowResult(ok=True)

    async def commit_batch(self, rows: list[dict[str, Any]], ctx: ImportContext) -> None:
        """生成期初单据 + 明细 + 记账行（起点快照）"""
        cache = ctx.cache
        s = ctx.session
        # 按 (仓, 货主) 分组 → 每组一张期初单据（单据头 owner_id/branch_id 为单值）
        groups: dict[tuple[int, int], list[dict]] = {}
        for row in rows:
            branch = cache["branches"][str(row.get("branch_bn") or "").strip()]
            owner = cache["owners"][str(row.get("owner_code") or "").strip()]
            groups.setdefault((branch.id, owner.id), []).append(row)

        now = datetime.now()
        date_str = now.strftime("%Y%m%d")
        for (branch_id, owner_id), group in groups.items():
            branch = next(b for b in cache["branches"].values() if b.id == branch_id)
            owner = cache["owners"][next(
                k for k, v in cache["owners"].items() if v.id == owner_id
            )]
            seq = await ctx.session.scalar(
                select(func.max(InvIoBill.id)).where(InvIoBill.bill_type == "opening_in")
            ) or 0
            bill_bn = f"opening_in{date_str}{(int(seq) + 1) % 1000000:06d}"

            bill = InvIoBill(
                tenant_id=1,
                owner_id=owner.id,
                bill_bn=bill_bn,
                bill_type="opening_in",
                direction=1,
                branch_id=branch.id,
                source_bill_type="",
                source_bill_bn="",
                status=5,          # 已确认（期初是起点快照，直接生效）
                settle_status=0,   # 不参与结算（§5.4）
                approval_status=0,
                operator="import",
                confirm_time=now,
                source="import",
                memo="期初建账导入",
            )
            s.add(bill)
            await s.flush()

            for row in group:
                mat = cache["materials"][str(row.get("material_bn") or "").strip()]
                store = _to_int(row.get("store"))
                freeze = _to_int(row.get("freeze"))
                arrive = _to_int(row.get("arrive_store"))
                defective = _to_int(row.get("defective"))
                safe = _to_int(row.get("safe_store"))
                unit_cost = _to_float(row.get("unit_cost"))
                s.add(
                    InvIoBillItem(
                        tenant_id=1,
                        owner_id=owner.id,
                        bill_id=bill.id,
                        bill_bn=bill_bn,
                        bm_id=mat.id,
                        issued_num=store,
                        returned_num=0,
                        confirmed_num=store,
                        defect_num=defective,
                        batch_no=str(row.get("batch_no") or "").strip(),
                        unit_cost=unit_cost,
                        amount=round(unit_cost * store, 2),
                        remark="期初",
                    )
                )
                # 记账行（起点快照）：三元键 = 仓 + 物料 + 货主
                s.add(
                    InvStockLedger(
                        tenant_id=1,
                        owner_id=owner.id,
                        branch_id=branch.id,
                        bm_id=mat.id,
                        store=store,
                        freeze=freeze,
                        arrive_store=arrive,
                        defective=defective,
                        safe_store=safe,
                        unit_cost=unit_cost,
                        inventory_cost=round(unit_cost * store, 2),
                        status=1,
                        last_store_time=now,
                    )
                )
                # 变动流水（口径级 before/after：期初从 0 起算）
                for field_name, num in (
                    ("store", store), ("freeze", freeze),
                    ("arrive", arrive), ("defective", defective),
                ):
                    if num == 0:
                        continue
                    s.add(
                        InvStockChangeLog(
                            tenant_id=1,
                            owner_id=owner.id,
                            branch_id=branch.id,
                            bm_id=mat.id,
                            change_field=field_name,
                            change_num=num,
                            before_balance=0,
                            after_balance=num,
                            bill_type="opening_in",
                            bill_bn=bill_bn,
                            bill_item_id=0,
                            action="inbound",
                            operator="import",
                            source="migration",
                            idempotent_key=f"opening_in:{bill_bn}:{mat.id}:{field_name}",
                        )
                    )


def _to_int(value: Any) -> int:
    text = str(value if value is not None else "").strip()
    if not text:
        return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def _to_float(value: Any) -> float:
    text = str(value if value is not None else "").strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


register_template(INITIAL_TEMPLATE)
register_importer(InitialStockImporter())
