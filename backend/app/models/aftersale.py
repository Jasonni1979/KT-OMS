"""售后服务域 ORM（D05 售后申请 / 退货退款执行 / 仅退款 / 换货补发 · W9-1）

覆盖（本期最小闭环的 4 张核心表）：
- aft_return_apply       售后申请单（三链路合一：仅退款/退货退款/换货/补发）
- aft_return_apply_item  申请行（行级部分售后：数量 + 双口径金额）
- aft_return_apply_log   状态变迁操作日志（谁/何时/从什么到什么）
- aft_refund             退款单（仅退款/退货退款收口；含线下登记例外）

⚠ **枚举以 DDL COMMENT 为权威**（tinyint 语义）：
- `aftersale_type`：1=仅退款 / 2=退货退款 / 3=换货 / 4=补发
- 申请单 `status`：0=待关联 / 1=待审核 / 2=待退货 / 3=待收货 / 4=待退款 /
  5=退款中 / 6=换货执行中 / 7=完成 / 8=拒绝 / 9=关闭
  （类型裁剪：仅退款无 2/3，换货无 4/5）
- `goods_status`：0=未发货 / 1=已发货未收 / 2=已收货
- 退款单 `status`：1=待退款 / 2=退款中 / 3=已退款 / 4=退款失败 / 5=已退款-线下 / 6=已取消
- 退款单 `channel`：1=platform / 2=offline
- `sync_status`：0=未回传 / 1=回传中 / 2=成功 / 3=失败待重试 / 4=转人工
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Integer,
    Numeric,
    SmallInteger,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin, VersionMixin


class AftReturnApply(Base, TimestampMixin, TenantMixin, VersionMixin):
    """售后申请单（D05.01 FR-02a/02b/02c/03a）

    ⚠ DDL 该表**无 is_deleted 列**（软删由其他字段表达）→ 不继承 SoftDeleteMixin。
    `source` 默认 platform，手工单为 manual（FR-03a）。
    """

    __tablename__ = "aft_return_apply"
    __table_args__ = {"schema": "oms_aftersale"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: 申请单号（平台单 RA 前缀 / 手工单 MA 前缀，FR-02a）
    apply_bn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    #: platform（平台同步）/ manual（手工建单）
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="platform")
    platform: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    platform_aftersale_bn: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: 1=仅退款 2=退货退款 3=换货 4=补发
    aftersale_type: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    #: 仅补发不换货标记
    reship_only: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    #: 0=待关联 1=待审核 2=待退货 3=待收货 4=待退款 5=退款中 6=换货执行中 7=完成 8=拒绝 9=关闭
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    #: 0=未发货 1=已发货未收 2=已收货
    goods_status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    order_bn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    #: 订单已归档（FR-01e 自动回捞）
    is_archived_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    apply_amount_customer: Mapped[Any] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    apply_amount_platform_bear: Mapped[Any] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    approved_amount_customer: Mapped[Any] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    approved_amount_platform_bear: Mapped[Any] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    reason_code: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    reason_raw: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    buyer_claim: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    evidence_urls: Mapped[Any] = mapped_column(JSON, nullable=True)
    buyer_id_enc: Mapped[bytes | None] = mapped_column(nullable=True)
    buyer_id_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    buyer_nick: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    buyer_phone_enc: Mapped[bytes | None] = mapped_column(nullable=True)
    buyer_phone_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    #: 处理时限（FR-06a 落单即算）
    deadline: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    #: 预警分级 0=无 1=黄 2=红（FR-06b）
    warn_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    platform_status_raw: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    platform_modified_version: Mapped[str] = mapped_column(
        String(64), nullable=False, default=""
    )
    #: 0=未回传 1=回传中 2=成功 3=失败待重试 4=转人工
    sync_status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    #: 平台超时自动同意（FR-06b 被动收敛）
    auto_agreed_by_platform: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0
    )
    #: 审核通道 1=人工 2=自动 3=OA审批
    audit_channel: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    operator: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    auditor: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    audit_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    platform_extra: Mapped[Any] = mapped_column(JSON, nullable=True)
    # ⚠ 以下 3 列是 **VIRTUAL GENERATED**（从 platform_extra 派生，FR-04b
    #   高频查询索引）→ **不能 INSERT，也不能映射为可写列**
    #   （映射后 INSERT 会报 "The value specified for generated column ... is not allowed"）
    #   platform_refund_id / cs_intervene_flag / platform_aftersale_type_raw


class AftReturnApplyItem(Base, TimestampMixin, TenantMixin, VersionMixin, SoftDeleteMixin):
    """售后申请行（D05.01 FR-02f：行级部分售后）

    数量校验：`Σ(本单 + 历史处理中 + 历史完成) ≤ 行购买数量`。
    """

    __tablename__ = "aft_return_apply_item"
    __table_args__ = {"schema": "oms_aftersale"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    apply_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    order_item_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: 平台子单号（oid）
    oid: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    bm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sku_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    sku_spec: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    apply_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    approved_num: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    apply_amount_customer_line: Mapped[Any] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    apply_amount_platform_bear_line: Mapped[Any] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    approved_amount_customer_line: Mapped[Any] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    gift_flag: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    #: 福袋/组合装按 BOM 展开校验（D04.01）
    combo_ref: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    platform_extra: Mapped[Any] = mapped_column(JSON, nullable=True)


class AftReturnApplyLog(Base, TenantMixin):
    """售后申请状态变迁日志（D05.01 FR-02c：每次变迁写操作日志）"""

    __tablename__ = "aft_return_apply_log"
    __table_args__ = {"schema": "oms_aftersale"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    apply_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: 同一申请单的递增序号
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    action: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    from_status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    to_status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    #: 操作者类型 1=人工 2=系统 3=平台
    operator_type: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    operator: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    detail_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default="CURRENT_TIMESTAMP(3)", nullable=False
    )


class AftRefund(Base, TimestampMixin, TenantMixin, VersionMixin):
    """退款单（D05.03 仅退款与退款单）

    `status`：1=待退款 2=退款中 3=已退款 4=退款失败 5=已退款-线下 6=已取消
    `channel`：1=platform（原路退回）2=offline（线下登记例外）
    """

    __tablename__ = "aft_refund"
    __table_args__ = {"schema": "oms_aftersale"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    refund_bn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    apply_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reship_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    order_bn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    #: apply_audit / inbound_trigger / platform_supplement / manual_offline / exchange_diff
    source: Mapped[str] = mapped_column(String(24), nullable=False, default="apply_audit")
    #: 1=待退款 2=退款中 3=已退款 4=退款失败 5=已退款-线下 6=已取消
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    #: 1=platform 2=offline
    channel: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    refund_customer: Mapped[Any] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    refund_platform_bear: Mapped[Any] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    platform_executed_amount: Mapped[Any] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    platform_refund_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    platform: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    refund_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    arrive_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    fail_reason_code: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    fail_reason_raw: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    platform_intervened: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    #: 资损类型 0=无 1=少件 2=破损
    loss_type: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    loss_amount: Mapped[Any] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    #: 审核通道 1=人工 2=自动 3=OA审批
    audit_channel: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    auditor: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    approval_ref: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    risk_flag: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    #: 台账回冲状态 0=未入账 1=已推 D08 2=差异
    ledger_status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    red_flush_of: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    platform_extra: Mapped[Any] = mapped_column(JSON, nullable=True)
