"""OMS 订单号生成器（D03.01 FR-03a~03e）

规则：`前缀(1) + yyMMdd(6) + 店铺码(3) + 混淆序列(7)` = **17 位**

- 前缀：P=平台单 L=手工单 I=导入单 C=换货单 B=补发单 R=B2B单
- 店铺码：店铺档案分配的 3 位数字码（从 shop_bn 数字部分后 3 位派生，全局递增唯一）
- 序列：Redis `INCR order:seq:{yyMMdd}`（原子、跨进程安全），经**步进混淆**
  （× STEP 后取模 10^7，STEP 与 10^7 互质）后输出，防外部按号遍历推测单量
- 降级：Redis 故障时走 DB 号段表 `bas_seq`（CAS 发号，每次取 step_size 号段），不重号
"""

from datetime import date, datetime

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import BaseSeq

#: 步长（与 10^7 互质 → gcd(3, 10_000_000) = 1，混淆可逆且不重号）
STEP = 3
#: 序列空间 10^7
SEQ_SPACE = 10_000_000
#: 前缀枚举（FR-03a）
PREFIX_PLATFORM = "P"
PREFIX_LOCAL = "L"
PREFIX_IMPORT = "I"
PREFIX_EXCHANGE = "C"
PREFIX_RESHIP = "B"
PREFIX_B2B = "R"
#: DB 号段降级域码
SEQ_DOMAIN = "OD"


def shop_code_of(shop_bn: str) -> str:
    """店铺码（3 位数字）：从 shop_bn 的数字部分后 3 位派生

    shop_bn 由 Redis 全局发号递增生成 → 后 3 位在 1000 家店铺内不重复；
    超出 1000 家时存在理论冲突，由订单号唯一索引兜底（FR-03d）。
    """
    digits = "".join(ch for ch in (shop_bn or "") if ch.isdigit())
    if not digits:
        return "000"
    return f"{int(digits[-3:]) % 1000:03d}"


class OrderBnGenerator:
    """订单号生成器"""

    def __init__(self, session: AsyncSession, redis: Redis | None = None):
        self.s = session
        self.r = redis

    async def next(self, prefix: str, shop_bn: str, *, now: datetime | None = None) -> str:
        """生成下一个订单号"""
        now = now or datetime.now()
        yymmdd = now.strftime("%y%m%d")
        shop_code = shop_code_of(shop_bn)
        seq = await self._next_seq(yymmdd)
        mixed = (seq * STEP) % SEQ_SPACE
        return f"{prefix}{yymmdd}{shop_code}{mixed:07d}"

    async def _next_seq(self, yymmdd: str) -> int:
        """取序列号（Redis 主 / DB 号段降级）"""
        if self.r is not None:
            try:
                return int(await self.r.incr(f"order:seq:{yymmdd}"))
            except Exception:
                pass  # 降级到 DB
        return await self._next_seq_db(yymmdd)

    async def _next_seq_db(self, yymmdd: str) -> int:
        """DB 号段降级（CAS 发号，一次取 step_size 号段，号段内本地自增）"""
        parsed = datetime.strptime(yymmdd, "%y%m%d")
        seq_date = date(parsed.year + 2000, parsed.month, parsed.day)
        row = await self.s.scalar(
            select(BaseSeq).where(
                BaseSeq.seq_domain == SEQ_DOMAIN,
                BaseSeq.seq_date == seq_date,
            )
        )
        if row is None:
            row = BaseSeq(
                seq_domain=SEQ_DOMAIN,
                seq_date=seq_date,
                current_value=0,
                step_size=1000,
                max_value=SEQ_SPACE,
                remark="OMS订单号序列（Redis 故障降级号段）",
            )
            self.s.add(row)
            await self.s.commit()
            await self.s.refresh(row)
        # CAS 推进一个号段
        res = await self.s.execute(
            update(BaseSeq)
            .where(BaseSeq.id == row.id, BaseSeq.version == row.version)
            .values(
                current_value=BaseSeq.current_value + BaseSeq.step_size,
                version=BaseSeq.version + 1,
            )
        )
        await self.s.commit()
        if int(getattr(res, 'rowcount', 0) or 0) == 0:
            # CAS 失败（并发）→ 重读一次
            fresh = await self.s.scalar(
                select(BaseSeq).where(
                    BaseSeq.seq_domain == SEQ_DOMAIN, BaseSeq.seq_date == seq_date
                )
            )
            if fresh is None:
                return int(datetime.now().timestamp() % SEQ_SPACE)
            return int(fresh.current_value)
        # 号段起点 + 段内偏移（用毫秒尾数避免段内并发重号）
        offset = int(datetime.now().timestamp() * 1000) % int(row.step_size)
        return int(row.current_value) + offset
