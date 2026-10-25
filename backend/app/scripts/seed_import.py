"""导入模板登记 seed（SRS-D01.06 FR-01d：各域模板统一登记）

代码里的 TEMPLATE_REGISTRY 是权威定义（与数据权限注册表同策略：代码=权威，DB=登记）。
本脚本把模板登记到 oms_base.bas_ie_template，供任务中心按模板类型筛选。幂等可重跑。
"""
import asyncio
import json

from sqlalchemy import select

from app.core.db import SessionFactory, engine, without_data_scope
from app.models.base import BaseImportTemplate
from app.services import importers  # noqa: F401  # 导入即注册模板
from app.services.import_center import TEMPLATE_REGISTRY


async def seed() -> None:
    # 豁免通道登记点⑦：系统级初始化脚本（无用户上下文，fail-closed 下需显式豁免）
    with without_data_scope():
        await _seed_impl()


async def _seed_impl() -> None:
    async with SessionFactory() as s:
        for code, spec in TEMPLATE_REGISTRY.items():
            existing = await s.scalar(
                select(BaseImportTemplate).where(BaseImportTemplate.template_code == code)
            )
            headers = spec.headers
            fingerprint = _fingerprint(headers)
            if existing:
                existing.template_name = spec.template_name
                existing.domain_code = spec.domain_code
                existing.entity_ref = spec.entity_ref
                existing.importer_ref = spec.importer_ref
                existing.columns_json = json.dumps(spec.to_columns_json(), ensure_ascii=False)
                existing.header_fingerprint = fingerprint
                existing.perm_point = spec.perm_point
                existing.template_version = spec.version
                existing.status = 1
                continue
            s.add(
                BaseImportTemplate(
                    tenant_id=1,
                    template_code=spec.template_code,
                    template_name=spec.template_name,
                    domain_code=spec.domain_code,
                    entity_ref=spec.entity_ref,
                    importer_ref=spec.importer_ref,
                    columns_json=json.dumps(spec.to_columns_json(), ensure_ascii=False),
                    validate_rules_json=json.dumps(
                        {"framework": "必填/类型/长度/枚举", "business": "importer.rowValidate"},
                        ensure_ascii=False,
                    ),
                    sensitive_columns_json=json.dumps([], ensure_ascii=False),
                    template_version=spec.version,
                    header_fingerprint=fingerprint,
                    perm_point=spec.perm_point,
                    status=1,
                )
            )
        await s.commit()
        print(f"已登记导入模板 {len(TEMPLATE_REGISTRY)} 个: {list(TEMPLATE_REGISTRY)}")


def _fingerprint(headers: list[str]) -> str:
    import hashlib

    return hashlib.sha256("|".join(headers).encode()).hexdigest()


if __name__ == "__main__":
    async def _main() -> None:
        await seed()
        await engine.dispose()

    asyncio.run(_main())
