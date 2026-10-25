"""认证服务（SRS-D10.02 FR-05：MVP=内部 staff 账密通道；企微扫码/短信验证码留扩展位）

- 密码连败 5 次锁定 15 分钟（FR-02d）
- JWT access 2h + refresh 7d 落库可吊销（FR-05b）
- 多端策略：内部 PC+移动各 1 会话并存，同端互踢（FR-05c）
- 登录成功/失败均落 org_session 审计（FR-05d，D10.06 投递 M4+ 补）
"""
import hashlib
from datetime import datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security as sec
from app.core.config import settings
from app.core.exceptions import PermissionDeniedError
from app.models.account import (
    OrgAccount,
    OrgAccountCredential,
    OrgAccountRole,
    OrgRole,
    OrgRolePerm,
    OrgSession,
)

MAX_FAIL = 5
LOCK_MINUTES = 15
REFRESH_DAYS = 7
# 超管角色编码（seed 预置，data_scope_mode=all）
SUPERUSER_ROLE_CODE = "R_SUPER"


class AuthService:
    def __init__(self, session: AsyncSession, redis: Redis):
        self.s = session
        self.r = redis

    # ---------- 登录 ----------

    async def login_password(self, login_name: str, password: str,
                             device_type: str = "pc", login_ip: str = "",
                             device_fp: str = "") -> dict:
        """账密登录（channel=password）。失败原因结构化：pwd_error/locked/disabled"""
        account = await self.s.scalar(
            select(OrgAccount).where(
                OrgAccount.login_name == login_name,
                OrgAccount.account_type == "staff",
                OrgAccount.is_deleted == 0,
            )
        )
        if not account:
            # 用户不存在与密码错统一话术（防账号枚举）
            raise PermissionDeniedError("账号或密码错误", code="AUTH_FAILED", http_status=401)
        if account.status == 4:
            await self._audit_fail(account, device_type, login_ip, "disabled")
            raise PermissionDeniedError("账户已禁用", code="ACCOUNT_DISABLED", http_status=403)
        now = datetime.now()
        if account.status == 3:
            if account.lock_until and account.lock_until > now:
                await self._audit_fail(account, device_type, login_ip, "locked")
                raise PermissionDeniedError(
                    f"账户锁定中，{account.lock_until:%H:%M} 后自动解锁",
                    code="ACCOUNT_LOCKED", http_status=423,
                )
            # 锁定已到期，自动解锁
            account.status = 2
            account.fail_count = 0
            account.lock_until = None

        cred = await self.s.scalar(
            select(OrgAccountCredential).where(
                OrgAccountCredential.account_id == account.id,
                OrgAccountCredential.credential_type == "password",
                OrgAccountCredential.status == 1,
            )
        )
        if not cred or not sec.verify_password(cred.password_hash, password):
            account.fail_count += 1
            if account.fail_count >= MAX_FAIL:
                account.status = 3
                account.lock_until = now + timedelta(minutes=LOCK_MINUTES)
                account.fail_count = 0
            await self.s.commit()
            await self._audit_fail(account, device_type, login_ip, "pwd_error")
            raise PermissionDeniedError("账号或密码错误", code="AUTH_FAILED", http_status=401)

        # 成功：清零失败计数、透明重哈希（参数升级）
        account.fail_count = 0
        account.status = 2 if account.status == 1 else account.status
        account.last_login_time = now
        account.last_login_ip = login_ip
        if sec.password_needs_rehash(cred.password_hash):
            cred.password_hash = sec.hash_password(password)
            cred.password_updated_time = now

        must_change = bool(cred.must_change_pwd)
        tokens = await self._issue_session(account, device_type, login_ip, device_fp, "password")
        await self.s.commit()
        return {**tokens, "must_change_pwd": must_change, "account_id": account.id,
                "account_name": account.account_name}

    async def _issue_session(self, account: OrgAccount, device_type: str,
                             login_ip: str, device_fp: str, channel: str) -> dict:
        """签发 JWT + refresh 落库 + Redis 会话；同端互踢（FR-05c）"""
        is_super = await self._is_superuser(account.id)
        access = sec.create_access_token(
            account_id=account.id, tenant_id=account.tenant_id,
            roles_ver=account.roles_ver, is_superuser=is_super,
        )
        refresh = sec.create_refresh_token()
        session_id = sec.new_session_id()
        expire = datetime.now() + timedelta(days=REFRESH_DAYS)

        # 同端互踢：旧会话标记被踢 + 删 Redis
        old_rows = (await self.s.scalars(
            select(OrgSession).where(
                OrgSession.account_id == account.id,
                OrgSession.device_type == device_type,
                OrgSession.status == 1,
            )
        )).all()
        for old in old_rows:
            old.status = 3
            await self.r.delete(f"session:{account.id}:{device_type}")

        row = OrgSession(
            tenant_id=account.tenant_id, session_id=session_id, account_id=account.id,
            device_type=device_type, device_fp=device_fp, login_ip=login_ip,
            channel=channel, refresh_token_hash=sec.hash_refresh_token(refresh),
            expire_time=expire, status=1, login_result=1,
        )
        self.s.add(row)
        await self.s.flush()
        # Redis 会话索引（存在性校验支持即时吊销，FR-05b）
        await self.r.set(
            f"session:{account.id}:{device_type}", session_id,
            ex=REFRESH_DAYS * 86400,
        )
        return {"access_token": access, "refresh_token": refresh, "session_id": session_id,
                "expires_in": settings.access_token_expire_minutes * 60}

    async def _is_superuser(self, account_id: int) -> bool:
        role_ids = (await self.s.scalars(
            select(OrgAccountRole.role_id).where(OrgAccountRole.account_id == account_id)
        )).all()
        if not role_ids:
            return False
        cnt = await self.s.scalar(
            select(OrgRole.id).where(OrgRole.id.in_(role_ids), OrgRole.role_code == SUPERUSER_ROLE_CODE)
        )
        return cnt is not None

    async def _audit_fail(self, account: OrgAccount, device_type: str, ip: str, reason: str) -> None:
        self.s.add(OrgSession(
            tenant_id=account.tenant_id, session_id=sec.new_session_id(), account_id=account.id,
            device_type=device_type, login_ip=ip, channel="password",
            expire_time=datetime.now(), status=2, login_result=2, fail_reason=reason,
        ))
        await self.s.commit()

    # ---------- 每请求校验 ----------

    async def validate_access(self, token: str) -> dict:
        """JWT 验签 → roles_ver 一致性 → Redis 会话存在性（即时吊销，FR-05b §5.2）"""
        payload = sec.decode_access_token(token)
        account_id = int(payload["sub"])
        account = await self.s.scalar(
            select(OrgAccount).where(OrgAccount.id == account_id, OrgAccount.is_deleted == 0)
        )
        if not account or account.status in (3, 4):
            raise PermissionDeniedError("账户状态异常", code="ACCOUNT_DISABLED", http_status=401)
        if account.roles_ver != payload.get("roles_ver"):
            # 角色已变更，强制前端刷新（拿新 token）
            raise PermissionDeniedError("权限已变更，请重新登录", code="ROLES_CHANGED", http_status=401)
        # Redis 任一端会话存在即放行（access 2h 内不区分端）
        keys = await self.r.keys(f"session:{account_id}:*")
        if not keys:
            raise PermissionDeniedError("会话已失效", code="SESSION_REVOKED", http_status=401)
        return {**payload, "account": account}

    # ---------- 刷新 / 登出 ----------

    async def refresh(self, refresh_token: str, device_type: str = "pc") -> dict:
        rt_hash = sec.hash_refresh_token(refresh_token)
        row = await self.s.scalar(
            select(OrgSession).where(
                OrgSession.refresh_token_hash == rt_hash,
                OrgSession.status == 1,
                OrgSession.expire_time > datetime.now(),
            )
        )
        if not row:
            raise PermissionDeniedError("刷新令牌无效或已过期", code="REFRESH_INVALID", http_status=401)
        account = await self.s.scalar(select(OrgAccount).where(OrgAccount.id == row.account_id))
        if not account or account.status in (3, 4):
            raise PermissionDeniedError("账户状态异常", code="ACCOUNT_DISABLED", http_status=401)
        # 旋转：旧 refresh 作废
        row.status = 2
        tokens = await self._issue_session(account, device_type, row.login_ip, row.device_fp, row.channel)
        await self.s.commit()
        return tokens

    async def logout(self, account_id: int, device_type: str = "pc") -> None:
        """登出=删 Redis + refresh 吊销双保险（FR-05b）"""
        sid = await self.r.get(f"session:{account_id}:{device_type}")
        if sid:
            await self.s.execute(
                update(OrgSession)
                .where(OrgSession.session_id == sid, OrgSession.status == 1)
                .values(status=2)
            )
        await self.r.delete(f"session:{account_id}:{device_type}")
        await self.s.commit()

    # ---------- 权限点（供菜单/按钮控制） ----------

    async def permissions_of(self, account_id: int) -> list[str]:
        role_ids = (await self.s.scalars(
            select(OrgAccountRole.role_id).where(OrgAccountRole.account_id == account_id)
        )).all()
        if not role_ids:
            return []
        # 超管=全量生效权限点
        is_super = await self._is_superuser(account_id)
        if is_super:
            from app.models.account import OrgPermPoint
            return list((await self.s.scalars(
                select(OrgPermPoint.perm_code).where(OrgPermPoint.status == 1, OrgPermPoint.is_deleted == 0)
            )).all())
        codes = (await self.s.scalars(
            select(OrgRolePerm.perm_code).where(OrgRolePerm.role_id.in_(role_ids)).distinct()
        )).all()
        return list(codes)


def fingerprint(ip: str, ua: str) -> str:
    """设备指纹极简版（IP+UA 哈希；正式指纹方案 M4+ 安全加固）"""
    return hashlib.md5(f"{ip}|{ua}".encode()).hexdigest()[:32]
