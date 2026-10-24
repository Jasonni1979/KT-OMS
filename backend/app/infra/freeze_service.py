"""库存预占服务原型（M0.5 spike / SRS-D04.03 FreezeService）

三元记账键：仓×SKU×货主 → Redis hash key inv:{branch_id}:{bm_id}:{owner_id}
预占台账：inv:freeze:{idempotent_key}（TTL=预占有效期，过期回收任务兜底）
三个 Lua 脚本保证原子性：reserve / release / settle（app/infra/lua/）
"""
from pathlib import Path

from redis.asyncio import Redis

LUA_DIR = Path(__file__).parent / "lua"


class FreezeService:
    """预占/释放/转扣减（对齐 SRS-D04.03 接口契约：reserve/release/settle）"""

    def __init__(self, redis: Redis):
        self._redis = redis
        self._reserve = redis.register_script((LUA_DIR / "freeze_reserve.lua").read_text())
        self._release = redis.register_script((LUA_DIR / "freeze_release.lua").read_text())
        self._settle = redis.register_script((LUA_DIR / "freeze_settle.lua").read_text())

    @staticmethod
    def stock_key(branch_id: int, bm_id: int, owner_id: int) -> str:
        return f"inv:{branch_id}:{bm_id}:{owner_id}"

    @staticmethod
    def freeze_key(idempotent_key: str) -> str:
        return f"inv:freeze:{idempotent_key}"

    async def init_stock(self, branch_id: int, bm_id: int, owner_id: int,
                         store: int, defective: int = 0, safe_locked: int = 0) -> None:
        """期初/测试初始化库存行（生产走 D04.04 期初建账 + 记账流水同步 Redis）"""
        await self._redis.hset(self.stock_key(branch_id, bm_id, owner_id), mapping={
            "store": store, "freeze": 0, "defective": defective, "safe_locked": safe_locked,
        })

    async def reserve(self, branch_id: int, bm_id: int, owner_id: int,
                      num: int, idempotent_key: str, ttl_seconds: int = 72 * 3600) -> tuple[int, int]:
        """预占。返回 (code, available_after)：code 1=成功 0=幂等命中 -1=可用不足"""
        res = await self._reserve(
            keys=[self.stock_key(branch_id, bm_id, owner_id)],
            args=[num, idempotent_key, self.freeze_key(idempotent_key), ttl_seconds],
        )
        return int(res[0]), int(res[1])

    async def release(self, branch_id: int, bm_id: int, owner_id: int,
                      num: int, idempotent_key: str) -> tuple[int, int]:
        """释放（订单取消/审单驳回）。返回 (code, freeze_after)"""
        res = await self._release(
            keys=[self.stock_key(branch_id, bm_id, owner_id)],
            args=[num, self.freeze_key(idempotent_key)],
        )
        return int(res[0]), int(res[1])

    async def settle(self, branch_id: int, bm_id: int, owner_id: int,
                     num: int, idempotent_key: str) -> tuple[int, int, int]:
        """预占转实扣（出库回传 D09.02 触发）。返回 (code, store_after, freeze_after)"""
        res = await self._settle(
            keys=[self.stock_key(branch_id, bm_id, owner_id)],
            args=[num, self.freeze_key(idempotent_key)],
        )
        return int(res[0]), int(res[1]), int(res[2])

    async def get_stock(self, branch_id: int, bm_id: int, owner_id: int) -> dict:
        raw = await self._redis.hgetall(self.stock_key(branch_id, bm_id, owner_id))
        return {k.decode() if isinstance(k, bytes) else k: int(v) for k, v in raw.items()}
