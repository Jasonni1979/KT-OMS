"""hello 演示域模型：映射真实表 oms_org.org_tenant（验证跨 schema + async 连通性）

注：这是 M0 骨架的连通性演示，非正式业务模型。
正式 org 域模型（OrgTenant/OrgOwner/...）在 M1 按 DB-D10 数据字典生成。
"""
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OrgTenant(Base):
    """租户表（映射 oms_org.org_tenant，只读演示）"""

    __tablename__ = "org_tenant"
    __table_args__ = {"schema": "oms_org"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_code: Mapped[str] = mapped_column(String(64))
    tenant_name: Mapped[str] = mapped_column(String(128))
    tenant_type: Mapped[str] = mapped_column(String(16))
    status: Mapped[int] = mapped_column(SmallInteger, default=1)
    source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    create_time: Mapped[datetime] = mapped_column(DateTime)
    update_time: Mapped[datetime] = mapped_column(DateTime)
    version: Mapped[int] = mapped_column(Integer, default=0)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, default=0)
