"""错误分级契约 —— **两套并存，绝不可混用**

这是 W9 沉淀的硬规则：通道侧与平台侧用了**不同的**分级体系，
混用会导致「本该重试的被判死信」或「本该停重试的被反复重试」。

| 体系 | 字段 | 取值 | 来源 |
|---|---|---|---|
| **通道侧** | `ful_cmd_fail.err_class` | RETRYABLE / FATAL / BIZ_REJECT | D09.02 §5.4 |
| **平台侧** | `gw_api_fail.err_level` | RETRYABLE / RATE_LIMITED / AUTH / MANUAL / FATAL | D02.04 |

对照表
------
| 语义 | 通道侧 err_class | 平台侧 err_level |
|---|---|---|
| 可重试 | RETRYABLE | RETRYABLE |
| 限流退避 | —（通道无此概念） | RATE_LIMITED |
| 授权失效 | —（通道无此概念） | AUTH |
| 转人工 | —（用 status=manual 表达） | MANUAL |
| 停止重试 | FATAL | FATAL |
| 业务拒绝 | BIZ_REJECT | —（平台侧无此概念） |

⚠ 状态字段两套相同：`waiting / retrying / succ / manual / dead`
（平台侧多 `suspended` 店铺挂起、`deleted` 终态清理）
"""
from __future__ import annotations

from typing import Final

#: 通道侧错误分类（WMS 指令失败）
CHANNEL_ERR_CLASS: Final[dict[str, str]] = {
    "RETRYABLE": "可重试",
    "FATAL": "停重试",
    "BIZ_REJECT": "业务拒绝",
}

#: 平台侧错误分级（平台 API 调用失败）
PLATFORM_ERR_LEVEL: Final[dict[str, str]] = {
    "RETRYABLE": "可重试",
    "RATE_LIMITED": "退避限流",
    "AUTH": "需重新授权",
    "MANUAL": "需人工",
    "FATAL": "停止重试",
}

#: 失败台账状态（两套相同）
FAIL_STATUS: Final[dict[str, str]] = {
    "waiting": "等待",
    "retrying": "重试中",
    "succ": "成功",
    "manual": "转人工",
    "dead": "死信",
}
