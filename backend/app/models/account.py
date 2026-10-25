"""oms_org 账户/角色/权限模型（SRS-D10.02，MVP：staff 账密通道）"""
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OrgAccount(Base):
    __tablename__ = "org_account"
    __table_args__ = {"schema": "oms_org"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    account_type: Mapped[str] = mapped_column(String(16), nullable=False, default="staff",
                                              comment="staff/portal/machine(P2)")
    login_name: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", comment="staff唯一登录账号"
    )
    account_name: Mapped[str] = mapped_column(String(64), nullable=False)
    mobile_enc: Mapped[bytes | None] = mapped_column(nullable=True, comment="D01.05信封加密,M1b接入")
    mobile_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    email_enc: Mapped[bytes | None] = mapped_column(nullable=True)
    email_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    org_node_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    dept_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    position: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1,
                                        comment="1=待激活,2=正常,3=锁定,4=禁用")
    lock_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fail_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    disable_reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    last_login_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login_ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    roles_ver: Mapped[int] = mapped_column(Integer, nullable=False, default=1,
                                           comment="角色绑定版本,变更+1,JWT落后即强制刷新")
    create_op: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class OrgAccountCredential(Base):
    __tablename__ = "org_account_credential"
    __table_args__ = {"schema": "oms_org"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    account_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    credential_type: Mapped[str] = mapped_column(String(16), nullable=False, default="password",
                                                 comment="password/wecom/oidc/api_key(P2)")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False, default="",
                                               comment="argon2id,禁明文/可逆")
    password_history_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    password_updated_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    must_change_pwd: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    wecom_corp_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    wecom_openid: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    sso_subject: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    sso_idp_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    api_key_hash: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )


class OrgRole(Base):
    __tablename__ = "org_role"
    __table_args__ = {"schema": "oms_org"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    role_code: Mapped[str] = mapped_column(String(64), nullable=False, comment="租户内唯一")
    role_name: Mapped[str] = mapped_column(String(64), nullable=False)
    role_type: Mapped[str] = mapped_column(String(16), nullable=False, default="custom",
                                           comment="system=预置不可删/custom")
    data_scope_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="org_node",
                                                 comment="all/org_node/custom(D10.03 FR-02c)")
    custom_scope_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    portal_flag: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    remark: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class OrgAccountRole(Base):
    __tablename__ = "org_account_role"
    __table_args__ = {"schema": "oms_org"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    account_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    grant_op: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    expire_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="空=长期")
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class OrgPermPoint(Base):
    __tablename__ = "org_perm_point"
    __table_args__ = {"schema": "oms_org"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    perm_code: Mapped[str] = mapped_column(String(128), nullable=False, comment="域.模块.资源.动作")
    perm_name: Mapped[str] = mapped_column(String(128), nullable=False)
    perm_type: Mapped[str] = mapped_column(String(16), nullable=False, default="action",
                                           comment="menu/action/button/field")
    module_code: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    internal_only: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    portal_visible: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    register_version: Mapped[str] = mapped_column(String(32), nullable=False, default="V1.0")
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    remark: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class OrgRolePerm(Base):
    __tablename__ = "org_role_perm"
    __table_args__ = {"schema": "oms_org"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    role_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    perm_code: Mapped[str] = mapped_column(String(128), nullable=False)
    grant_op: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)


class OrgDataPermission(Base):
    """数据权限授权关系（D10.03 FR-02a/02b：节点授权源头 + 直接维度授权）"""

    __tablename__ = "org_data_permission"
    __table_args__ = {"schema": "oms_org"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    account_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    dim_type: Mapped[str] = mapped_column(
        String(16), nullable=False,
        comment="org_node/shop/brand/branch/owner",
    )
    dim_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    grant_scope: Mapped[str] = mapped_column(String(16), nullable=False, default="inherit",
                                              comment="inherit=展开子树/self_only=仅本节点")
    grant_source: Mapped[str] = mapped_column(String(16), nullable=False, default="direct")
    reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    grant_op: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    expire_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class OrgSession(Base):
    """refresh 会话落库（FR-05b：登出/禁用/踢出=删Redis+吊销双保险）"""

    __tablename__ = "org_session"
    __table_args__ = {"schema": "oms_org"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    account_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    device_type: Mapped[str] = mapped_column(String(16), nullable=False, default="pc")
    device_fp: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    login_ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    ip_region: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="password")
    refresh_token_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    expire_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1,
                                        comment="1=活跃,2=登出,3=被踢,4=被吊销")
    login_result: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    fail_reason: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
