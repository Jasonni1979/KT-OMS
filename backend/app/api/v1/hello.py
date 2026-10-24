"""hello 演示路由：健康检查 + DB/Redis/MQ 连通性 + 跨 schema 查询演示"""
from fastapi import APIRouter, Depends
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.response import ok
from app.models.hello import OrgTenant

router = APIRouter(tags=["hello"])


@router.get("/healthz")
async def healthz() -> dict:
    """存活探针（K8s liveness）"""
    return ok({"status": "up"})


@router.get("/readyz")
async def readyz(session: AsyncSession = Depends(get_session)) -> dict:
    """就绪探针：DB 连通性检查"""
    await session.execute(text("SELECT 1"))
    return ok({"status": "ready", "db": "up"})


@router.get("/tenants")
async def list_tenants(session: AsyncSession = Depends(get_session)) -> dict:
    """跨 schema 查询演示：读 oms_org.org_tenant（M0 连通性验证用）"""
    result = await session.execute(
        select(OrgTenant).where(OrgTenant.is_deleted == 0).limit(20)
    )
    rows = result.scalars().all()
    return ok(
        {
            "total": len(rows),
            "items": [
                {
                    "id": r.id,
                    "tenant_code": r.tenant_code,
                    "tenant_name": r.tenant_name,
                    "tenant_type": r.tenant_type,
                    "status": r.status,
                }
                for r in rows
            ],
        }
    )
