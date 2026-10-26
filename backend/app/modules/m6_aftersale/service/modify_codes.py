"""M6 改单域常量与工具 —— 改单类型/状态机/快照二进制编解码"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.enums import ORD_ORDER_MODIFY_MODIFY_TYPE
from app.models.modify import OrdOrderModify

MODIFY_ADDRESS = "address"

MODIFY_STATUS_EDITING = "editing"

MODIFY_STATUS_RECALLING = "recalling"

MODIFY_STATUS_EFFECTIVE = "effective"

MODIFY_STATUS_SUSPENDED = "suspended"

MODIFY_STATUS_CANCELLED = "cancelled"

MODIFY_OPEN_STATUSES = (
    MODIFY_STATUS_EDITING,
    MODIFY_STATUS_RECALLING,
    MODIFY_STATUS_SUSPENDED,
)

MODIFY_TYPE_LABEL = ORD_ORDER_MODIFY_MODIFY_TYPE

def _hex(v: bytes | str | None) -> str:
    """blob → hex 字符串（JSON 可序列化）"""
    if v is None:
        return ""
    if isinstance(v, bytes):
        return v.hex()
    return str(v)

def _unhex(v: str | bytes | None) -> bytes:
    """hex 字符串 → blob（还原密文）"""
    if v is None:
        return b""
    if isinstance(v, bytes):
        return v
    try:
        return bytes.fromhex(str(v))
    except ValueError:
        return str(v).encode("utf-8")

async def s_rows(session: AsyncSession, q, limit: int):
    """执行带 limit 的 select"""
    return await session.scalars(q.order_by(OrdOrderModify.id.desc()).limit(limit))
