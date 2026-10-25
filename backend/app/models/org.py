"""oms_org 域模型：组织树 + 货主档案（SRS-D10.01，映射真实 DDL）"""
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OrgNode(Base):
    """组织树节点（一棵树+类型枚举，FR-01；cat_path 冗余路径 FR-01d）"""

    __tablename__ = "org_node"
    __table_args__ = {"schema": "oms_org"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    org_code: Mapped[str] = mapped_column(String(64), nullable=False, comment="全局唯一,创建后不可改")
    org_name: Mapped[str] = mapped_column(String(128), nullable=False)
    node_type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="group/brand/owner_co/shop/warehouse/dept/reserved_dealer",
    )
    parent_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)
    cat_path: Mapped[str] = mapped_column(String(255), nullable=False, default=",")
    node_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    ref_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0,
        comment="shop->gw_shop.id; warehouse->ful_branch.id; 其余=0",
    )
    sort_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1, comment="1=启用,2=停用")
    remark: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class OrgNodeRelation(Base):
    """节点与业务对象关联（D10.01 FR-07a：仓↔可服务货主多对多 = 三元记账前提）"""

    __tablename__ = "org_node_relation"
    __table_args__ = {"schema": "oms_org"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    node_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    rel_type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="shop/branch/owner/branch_owner/tenant_owner",
    )
    rel_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    is_primary: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    create_op: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )


class OrgOwner(Base):
    """货主档案（三元记账 owner_id 权威源，FR-03；类型创建后不可改）"""

    __tablename__ = "org_owner"
    __table_args__ = {"schema": "oms_org"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    owner_code: Mapped[str] = mapped_column(String(64), nullable=False, comment="全局唯一,创建后不可改")
    owner_name: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_type: Mapped[str] = mapped_column(
        String(32), nullable=False,
        comment="KC_BUYOUT=凯淳买断/BRAND_CONSIGN=品牌代销/DEALER_TC=经销(P2预留)",
    )
    org_node_id: Mapped[int] = mapped_column(BigInteger, nullable=False, comment="归属货主公司节点(owner_co)")
    tax_no: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    contact_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # contact_phone_enc/_hash：D01.05 信封加密组件 M1b 接入前保持默认（NULL/空），
    # 档案最小版联系人电话不强制采集——接入加密组件后补迁移
    contact_phone_enc: Mapped[bytes | None] = mapped_column(nullable=True)
    contact_phone_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=1,
        comment="1=合作中,2=暂停,3=终止(不可逆)",
    )
    contract_id_cur: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    kingdee_subject_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    terminate_check_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    remark: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
