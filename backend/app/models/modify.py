"""订单修改与快照 ORM（D03.08 订单修改与复审 · W8-3）

覆盖：
- ord_order_modify   改单主表（改单类型/状态机/叫回标记/差异摘要/Saga 日志）
- ord_order_snapshot 改单快照（不可变副本：订单主档/行/收货人，密文原样存）

按真实 DDL 映射；缺列不映射。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    SmallInteger,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin, VersionMixin


class OrdOrderModify(Base, TimestampMixin, TenantMixin, VersionMixin, SoftDeleteMixin):
    """订单改单（D03.08 FR-01a 改单入口 / FR-02a 快照 / FR-06a 叫回）

    ⚠ DDL：`owner_id` / `order_id` / `snapshot_id` / `operator` / `shop_id` 等
    均为 NOT NULL 且**无默认值** → INSERT 必须显式给值。
    """

    __tablename__ = "ord_order_modify"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    modify_bn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    order_bn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    #: address（改地址）/ item（改商品）/ price（改价格）/ invoice / memo
    modify_type: Mapped[str] = mapped_column(String(16), nullable=False, default="address")
    #: manual（人工）/ platform（平台消息 FR-01d）/ abnormal（异常单联动）
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    snapshot_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: editing / recalling / effective / suspended / cancelled
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="editing")
    need_recall: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    recall_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    #: 参与叫回的发货单 id 列表
    recall_refs: Mapped[Any] = mapped_column(JSON, nullable=True)
    approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 字段级差异（旧值 / 新值 / 变更字段）
    diff_summary: Mapped[Any] = mapped_column(JSON, nullable=True)
    #: Saga 编排日志（每步 {at, stage, ok, detail}）
    saga_log: Mapped[Any] = mapped_column(JSON, nullable=True)
    operator: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    effective_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    brand_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class OrdOrderSnapshot(Base, TenantMixin):
    """订单快照（D03.08 FR-02a：不可变副本，一次改单一份）

    ⚠ 收货人快照**保持密文**（PIPL）：`name_enc` / `mobile_enc` / `address_enc`
    原样存，`mobile_hash` / `address_hash` 存哈希，不落明文。
    """

    __tablename__ = "ord_order_snapshot"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    snapshot_bn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    modify_bn: Mapped[str | None] = mapped_column(String(32), nullable=True)
    snap_order: Mapped[Any] = mapped_column(JSON, nullable=False)
    snap_items: Mapped[Any] = mapped_column(JSON, nullable=False)
    snap_receiver: Mapped[Any] = mapped_column(JSON, nullable=False)
    snap_extend: Mapped[Any] = mapped_column(JSON, nullable=True)
    #: 快照时的预占流水号集合（FR-02b，回滚时按此恢复）
    freeze_ids: Mapped[Any] = mapped_column(JSON, nullable=True)
    status_snap: Mapped[Any] = mapped_column(JSON, nullable=False)
    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default="CURRENT_TIMESTAMP(3)", nullable=False
    )
