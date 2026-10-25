"""PIPL 个人信息加密组件（D01.05 的最小可用实现，M1c 接入订单收货人所需）

设计要点：
1. **信封加密**：数据密钥（`pipl_data_key`）与盲索引密钥（`pipl_index_key`）分离——
   盲索引用于等值检索（合单指纹、订单检索），泄露索引不应能反解明文。
2. **AES-GCM**（带认证标签）：密文自带完整性校验，密文格式
   `nonce(12) + tag(16) + ciphertext`，落库为 varbinary。
3. **盲索引** HMAC-SHA256：同一明文恒定输出，支持等值检索与合单指纹计算
   （D03.01 FR-07a 指纹只用盲索引，不含明文）。
4. **脱敏展示**：姓名保留姓、手机保留后 4 位（界面默认展示脱敏，明文查看需授权点）。

生产环境：主密钥由 KMS 注入（`KTOMS_PIPL_DATA_KEY` / `KTOMS_PIPL_INDEX_KEY`），
本模块的密钥派生仅用于 dev/test。
"""

import base64
import hashlib
import hmac

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

_NONCE_LEN = 12
_TAG_LEN = 16


def _data_key() -> bytes:
    """数据密钥（32 字节）：dev 环境由配置串 SHA-256 派生，生产由 KMS 注入原始密钥"""
    raw = settings.pipl_data_key.encode()
    if len(raw) == 32:
        return raw
    return hashlib.sha256(raw).digest()


def _index_key() -> bytes:
    """盲索引密钥（32 字节）"""
    raw = settings.pipl_index_key.encode()
    if len(raw) == 32:
        return raw
    return hashlib.sha256(raw).digest()


def encrypt(plaintext: str | None) -> bytes | None:
    """加密个人信息 → varbinary（nonce + tag + ciphertext）"""
    if plaintext is None or plaintext == "":
        return None
    nonce = _random_nonce()
    aead = AESGCM(_data_key())
    ct = aead.encrypt(nonce, plaintext.encode(), None)
    return nonce + ct[-_TAG_LEN:] + ct[:-_TAG_LEN]


def decrypt(cipher: bytes | None) -> str:
    """解密个人信息（密文为空返回空串）"""
    if not cipher:
        return ""
    nonce = cipher[:_NONCE_LEN]
    tag = cipher[_NONCE_LEN : _NONCE_LEN + _TAG_LEN]
    body = cipher[_NONCE_LEN + _TAG_LEN :]
    aead = AESGCM(_data_key())
    try:
        return aead.decrypt(nonce, body + tag, None).decode()
    except Exception:
        # 密钥轮换后旧密文无法解密 → 返回空串（不抛异常打断业务）
        return ""


def blind_index(plaintext: str | None) -> str:
    """盲索引（HMAC-SHA256 hex64）：等值检索用，同一明文恒定"""
    if not plaintext:
        return ""
    return hmac.new(
        _index_key(), plaintext.strip().encode(), hashlib.sha256
    ).hexdigest()


def mask_name(name: str | None) -> str:
    """姓名脱敏：张* / 欧阳**"""
    if not name:
        return ""
    s = name.strip()
    if len(s) == 1:
        return s
    return s[0] + "*" * (len(s) - 1)


def mask_mobile(mobile: str | None) -> str:
    """手机脱敏：138****0000"""
    if not mobile:
        return ""
    s = mobile.strip()
    if len(s) < 7:
        return s[0] + "*" * (len(s) - 1) if s else ""
    return f"{s[:3]}****{s[-4:]}"


def tail4(mobile: str | None) -> str:
    """手机末四位（脱敏检索辅助，非敏感）"""
    if not mobile:
        return ""
    return mobile.strip()[-4:]


def _random_nonce() -> bytes:
    import os

    return os.urandom(_NONCE_LEN)


def encode_key_version() -> str:
    """当前密钥版本（密文落库时记录，支持轮换）"""
    return settings.pipl_key_version


def fingerprint_seed(parts: list[str]) -> str:
    """合单指纹种子拼接（D03.01 FR-07a）

    只接受盲索引/密文标识等**不可逆**成分，禁止传明文。
    """
    return "|".join(p for p in parts if p)


def hash_fingerprint(parts: list[str]) -> str:
    """合单指纹 = md5(盲索引成分拼接)（32 位 hex）"""
    return hashlib.md5(fingerprint_seed(parts).encode()).hexdigest()


def b64_key_preview() -> str:
    """密钥指纹（仅前 8 位 base64，便于运维核对是哪把密钥，不泄露密钥本身）"""
    return base64.b64encode(hashlib.sha256(_data_key()).digest()).decode()[:8]
