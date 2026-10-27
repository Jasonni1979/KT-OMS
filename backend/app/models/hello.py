"""hello 演示域模型：映射真实表 oms_org.org_tenant（验证跨 schema + async 连通性）

注：这是 M0 骨架的连通性演示，非正式业务模型。
正式 org 域模型（OrgTenant/OrgOwner/...）在 M1 按 DB-D10 数据字典生成。
"""
from datetime import date, datetime

from sqlalchemy import JSON, BigInteger, Date, DateTime, Integer, SmallInteger, String
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
    #: 租户关联货主集（FR-01c：外部租户强制隔离的**唯一数据来源**）
    #: ⚠ DDL 有这列但 ORM 之前**漏映射** → 门户登录会话的 owner 范围读不到
    owner_scope_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # ⚠ 可空性按真实 DDL 对齐（contact_name / contact_phone_hash 是 NOT NULL）
    contact_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    contact_phone_enc: Mapped[bytes | None] = mapped_column(nullable=True)
    contact_phone_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[int] = mapped_column(SmallInteger, default=1)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    create_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    version: Mapped[int] = mapped_column(Integer, default=0)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, default=0)
