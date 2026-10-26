"""M8 报表与监控 —— **契约公开面（唯一对外接口）**

⚠ **跨模块 import 只能从本文件导入**（门禁 R2 强制）。
   `service/` 下的实现是内部细节，不对外承诺稳定性 ——
   需要跨模块用的能力，在此显式导出。

本文件由 `tools/gen_module_public_api.py` 生成，请勿手工编辑。
"""
from __future__ import annotations

from app.modules.m8_insight.service.monitor import (
    AGE_BUCKETS,
    MonitorService,
)

__all__ = [
    "AGE_BUCKETS",
    "MonitorService",
]
