"""oms_gateway.gw_shop 店铺档案（最小版：D02.06 授权字段留待 W4 Gateway 模块消费）"""
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Integer, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GwShop(Base):
    __tablename__ = "gw_shop"
    __table_args__ = {"schema": "oms_gateway"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, index=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, index=True, comment="LFK->oms_org.org_owner"
    )
    shop_bn: Mapped[str] = mapped_column(String(32), nullable=False, comment="店铺编码(Redis发号)")
    shop_name: Mapped[str] = mapped_column(String(128), nullable=False)
    platform: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="taobao/jd/pdd/xhs/vop/douyin/wechat/kuaishou"
    )
    platform_shop_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    app_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    org_node_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, comment="组织树店铺节点")
    shop_type: Mapped[str] = mapped_column(String(16), nullable=False, default="flagship")
    business_type: Mapped[str] = mapped_column(String(16), nullable=False, default="direct_sale")
    auth_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    seller_info_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    auth_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    auth_url_track: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="enabled")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    create_time: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.now)
    update_time: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.now, onupdate=datetime.now
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
