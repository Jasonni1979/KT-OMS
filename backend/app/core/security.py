"""安全核心：argon2id 密码哈希（FR §5.4 禁明文/可逆）+ JWT 签发验签（FR-05b）"""
import hashlib
import time
import uuid
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import settings
from app.core.exceptions import PermissionDeniedError

# argon2id 默认参数即满足 OWASP 推荐（time_cost=3/memory=64MiB/parallelism=4）
_hasher = PasswordHasher()

ALGORITHM = "HS256"


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(password_hash: str, plain: str) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, plain)
    except (VerifyMismatchError, InvalidHashError, Exception):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    """参数升级后透明重哈希（登录成功时触发）"""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except Exception:
        return False


def new_session_id() -> str:
    return uuid.uuid4().hex


def create_access_token(*, account_id: int, tenant_id: int, roles_ver: int,
                        is_superuser: bool = False) -> str:
    """access JWT 短期（默认 2h，FR-05b），不落库；每请求验签+Redis会话存在性校验"""
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": str(account_id),
        "tid": tenant_id,
        "roles_ver": roles_ver,
        "su": is_superuser,
        "typ": "access",
        "iat": now,
        "exp": now + settings.access_token_expire_minutes * 60,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def create_refresh_token() -> str:
    """refresh token 长期（7d，落库可吊销）；返回明文，库存 sha256"""
    return uuid.uuid4().hex + uuid.uuid4().hex


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as e:
        raise PermissionDeniedError("登录已过期，请重新登录", code="TOKEN_EXPIRED", http_status=401) from e
    except jwt.InvalidTokenError as e:
        raise PermissionDeniedError("无效的身份凭证", code="TOKEN_INVALID", http_status=401) from e
    if payload.get("typ") != "access":
        raise PermissionDeniedError("凭证类型错误", code="TOKEN_INVALID", http_status=401)
    return payload


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
