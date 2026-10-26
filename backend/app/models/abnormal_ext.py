"""异常单扩展域 ORM（W9-2 · SRS-D03.09 FR-05b/FR-06a/FR-07）

覆盖：
- ord_oversold_batch      超卖应急批次（FR-05b：同店铺同 SKU 聚合 + 统一决策）
- ord_pause_command_log   暂停编排命令日志（FR-06b：逐发货单分布式动作留痕）
- ord_risk_list           名单服务（FR-07：黑/灰/白名单，两层库 scope）

⚠ **枚举以 DDL COMMENT 为权威**：
- 批次 `stage`：alarm 告警 / alloc_calc 调拨测算 / negotiate 协商 /
  refund 退款 / compensate 赔付 / review 复盘关闭
- 名单 `list_type`：black 黑 / gray 灰 / white 白
- 名单 `dimension`：mobile 手机 / address 地址 / account 账号 / name 姓名
- 名单 `value_type`：plain 明文 / hash 盲索引
- 名单 `scope`：global 全局 / tenant 租户 / owner 货主
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Integer,
    SmallInteger,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TenantMixin, TimestampMixin, VersionMixin


class OrdOversoldBatch(Base, TimestampMixin, TenantMixin, VersionMixin, SoftDeleteMixin):
    """超卖应急批次（D03.09 FR-05b：同店铺同 SKU 的超卖单自动聚合）

    聚合键 = 店铺 × 基础物料 × 货主；批次级统一决策，批次内订单继承决策结果。
    SLA 以 `stage_timeline` 记录各阶段到达时间为计时依据
    （T+0 告警 / T+4h 调拨测算 / T+24h 协商 / 超时赔付）。
    """

    __tablename__ = "ord_oversold_batch"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: 批次号（OS+日期+序列，唯一）
    batch_bn: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    shop_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: 基础物料（聚合键）
    bm_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resolved_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    refund_orders: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: alarm/alloc_calc/negotiate/refund/compensate/review
    stage: Mapped[str] = mapped_column(String(16), nullable=False, default="alarm")
    #: 各阶段到达时间（SLA 计时依据）
    stage_timeline: Mapped[Any] = mapped_column(JSON, nullable=True)
    #: 大促模式（1=SLA 收紧：T+4h→T+2h）
    promo_mode: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    #: 赔付登记 [{order_id,type,amount,liability,oa_approval_id}]
    compensation: Mapped[Any] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class OrdPauseCommandLog(Base, TenantMixin):
    """暂停编排命令日志（D03.09 FR-06b：逐发货单分布式动作留痕）"""

    __tablename__ = "ord_pause_command_log"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    order_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    delivery_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    #: pause / resume / cancel_fail 等命令
    command: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    #: ok / fail
    result: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    fail_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fail_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)
    abnormal_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    operator: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    create_time: Mapped[datetime] = mapped_column(
        DateTime, server_default="CURRENT_TIMESTAMP(3)", nullable=False
    )


class OrdRiskList(Base, TimestampMixin, TenantMixin, SoftDeleteMixin):
    """名单服务（D03.09 FR-07：黑/灰/白名单，两层库）

    - `list_type`：black 黑名单（禁止履约）/ gray 灰名单（强制人工审核）/
      white 白名单（跳过风控校验）
    - `dimension`：mobile 手机 / address 地址 / account 账号 / name 姓名
    - `match_value`：归一化后的匹配值（mobile/name/address 存 **HMAC 盲索引**，
      account 存明文）
    - `scope`：global 全局基础库 / tenant 租户私有库 / owner 货主私有库
      （**命中判定私有优先**，FR-07d）
    - `oa_approval_id`：加入/移出黑名单的 OA 审批单号（FR-07b 审批留痕）
    """

    __tablename__ = "ord_risk_list"
    __table_args__ = {"schema": "oms_order"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: black / gray / white
    list_type: Mapped[str] = mapped_column(String(8), nullable=False, default="black")
    #: mobile / address / account / name
    dimension: Mapped[str] = mapped_column(String(16), nullable=False, default="mobile")
    match_value: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    #: plain 明文 / hash 盲索引
    value_type: Mapped[str] = mapped_column(String(8), nullable=False, default="plain")
    #: global / tenant / owner
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="tenant")
    effective_start: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    effective_end: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    #: manual / risk_rule / platform（FR-07b 来源）
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    oa_approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    disabled: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    # ⚠ DDL 该表**无 version 列** → 不继承 VersionMixin
    is_deleted: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
