"""M1 基础主数据 —— **契约公开面（唯一对外接口）**

⚠ **跨模块 import 只能从本文件导入**（门禁 R2 强制）。
   `service/` 下的实现是内部细节，不对外承诺稳定性 ——
   需要跨模块用的能力，在此显式导出。

本文件由 `tools/gen_module_public_api.py` 生成，请勿手工编辑。
"""
from __future__ import annotations

from app.modules.m1_master.service.auth import (
    LOCK_MINUTES,
    MAX_FAIL,
    REFRESH_DAYS,
    SUPERUSER_ROLE_CODE,
    AuthService,
    fingerprint,
)
from app.modules.m1_master.service.branch_owner import (
    REL_TYPE_BRANCH_OWNER,
    BranchOwnerService,
)
from app.modules.m1_master.service.master import (
    CHILD_MATRIX,
    MAX_LEVEL,
    TAX_NO_RE,
    BranchService,
    OrgService,
    OwnerService,
    ShopService,
    get_redis,
)
from app.modules.m1_master.service.permission import (
    SCOPE_CACHE_PREFIX,
    SCOPE_CACHE_TTL,
    DataScope,
    PermissionService,
    build_auth_context,
)

__all__ = [
    "AuthService",
    "LOCK_MINUTES",
    "MAX_FAIL",
    "REFRESH_DAYS",
    "SUPERUSER_ROLE_CODE",
    "fingerprint",
    "BranchOwnerService",
    "REL_TYPE_BRANCH_OWNER",
    "BranchService",
    "CHILD_MATRIX",
    "MAX_LEVEL",
    "OrgService",
    "OwnerService",
    "ShopService",
    "TAX_NO_RE",
    "get_redis",
    "DataScope",
    "PermissionService",
    "SCOPE_CACHE_PREFIX",
    "SCOPE_CACHE_TTL",
    "build_auth_context",
]
