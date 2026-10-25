

# 导入即注册业务域可过滤实体 + 安装行级过滤注入（D10.03 FR-04a/04b）
from app.core.db import install_scope_injection as _install_scope  # noqa: E402
from app.models import registry  # noqa: E402,F401

_install_scope()
