"""ORM 声明式基类（对齐 DB-00 §3 公共字段约定：tenant_id/owner_id/version/软删/时间戳）"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, SmallInteger, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, comment="创建时间"
    )
    update_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False, comment="更新时间"
    )


class TenantMixin:
    tenant_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=1, index=True, comment="租户ID（D10.03 行级隔离维度）"
    )


class SoftDeleteMixin:
    is_deleted: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, comment="软删标记: 0=否,1=是"
    )


class VersionMixin:
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="乐观锁版本"
    )


class BaseEntity(Base, TimestampMixin, TenantMixin, SoftDeleteMixin, VersionMixin):
    """业务实体基类：id + 公共字段全套（流水/日志类实体不用软删，另行定义）"""

    __abstract__ = True

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
