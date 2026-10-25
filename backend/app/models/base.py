"""ORM 声明式基类（对齐 DB-00 §3 公共字段约定：tenant_id/owner_id/version/软删/时间戳）"""
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    Integer,
    SmallInteger,
    String,
    func,
)
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


class BaseImportTask(Base, TimestampMixin, TenantMixin, VersionMixin):
    """导入任务（D01.06 FR-03：导入任务编排 + 进度 + 结果 + 断点续跑）"""

    __tablename__ = "bas_import_task"
    __table_args__ = {"schema": "oms_base"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    task_bn: Mapped[str] = mapped_column(String(32), nullable=False, comment="任务号,唯一")
    template_code: Mapped[str] = mapped_column(String(64), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    entity_ref: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    source_file_ref: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    file_md5: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    row_count_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0,
        comment="0待执行,1执行中,2成功,3部分成功,4失败,5已取消",
    )
    progress_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    result_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    error_report_ref: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cancel_flag: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    fail_reason: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    creator: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    start_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cost_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")


class BaseImportError(Base, TenantMixin):
    """导入错误明细（D01.06 FR-03c：错误阶段/错误码/人读消息/原行快照）

    注：bas_import_error 为追加型日志表，DDL 只有 create_time（无 update_time/version）。
    """

    __tablename__ = "bas_import_error"
    __table_args__ = {"schema": "oms_base"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    row_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_stage: Mapped[str] = mapped_column(String(16), nullable=False, default="format")
    error_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    error_message: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    row_snapshot: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False, comment="创建时间"
    )


class BaseImportTemplate(Base, TimestampMixin, TenantMixin):
    """导入模板登记（SRS-D01.06 FR-01a/FR-01d：代码=权威定义，DB=登记供筛选）"""

    __tablename__ = "bas_ie_template"
    __table_args__ = {"schema": "oms_base"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    template_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    template_name: Mapped[str] = mapped_column(String(128), nullable=False)
    domain_code: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    entity_ref: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    importer_ref: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    columns_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    validate_rules_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    sensitive_columns_json: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    compat_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    header_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    perm_point: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    # 注：bas_ie_template 无 version 列（模板以 template_version 管理版本）
