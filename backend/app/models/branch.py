"""oms_fulfill.ful_branch 仓库档案（branch_id 三元键事实源；WMS 绑定属性归 D09.01 后置）"""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FulBranch(Base):
    __tablename__ = "ful_branch"
    __table_args__ = {"schema": "oms_fulfill"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    owner_id: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="单一归属仓必填；多货主仓为空"
    )
    branch_bn: Mapped[str] = mapped_column(String(32), nullable=False, comment="仓库编码,全局唯一不可变更")
    branch_name: Mapped[str] = mapped_column(String(128), nullable=False)
    branch_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="entity",
        comment="entity/cloud/store/bonded/virtual/defective",
    )
    region_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    province: Mapped[str | None] = mapped_column(String(32), nullable=True)
    city: Mapped[str | None] = mapped_column(String(32), nullable=True)
    district: Mapped[str | None] = mapped_column(String(32), nullable=True)
    address: Mapped[str | None] = mapped_column(String(256), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    contact_mobile_enc: Mapped[bytes | None] = mapped_column(nullable=True)
    is_ctrl: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, comment="管控库存")
    countable_flag: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, comment="计可售")
    is_declare: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, comment="跨境申报仓")
    cutoff_time: Mapped[str | None] = mapped_column(String(5), nullable=True, comment="截单时间 HH:mm")
    org_node_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="enabled")
    memo: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
