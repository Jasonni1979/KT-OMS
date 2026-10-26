"""契约中心 —— **全系统唯一的枚举 / 状态机 / 错误分级 / 单号规则来源**

为什么存在
----------
过去枚举值与中文标签散落在 39 个 service 里各抄一份，DDL 变更时必然漂移
（W9 实测两处：换货状态机缺「待审核→换货执行中」边、应急批次阶段表缺边）。
本包把「唯一一份」收敛到这里：

| 文件 | 内容 | 权威来源 | 维护方式 |
|---|---|---|---|
| `enums.py` | 全部枚举列（值 → 中文标签） | **DDL COMMENT** | **自动生成**，勿手改 |
| `transitions.py` | 状态机流转表 | SRS §5.1 流转表 | 手写（带来源标注） |
| `errors.py` | 两套错误分级（**不可混用**） | DDL + D09.02 §5.4 | 手写 |
| `ids.py` | 单号前缀规则 | D11 / 各域约定 | 手写 |

使用约定
--------
1. 代码里**不再手抄**枚举值 —— 一律从本包引用。
2. `enums.py` 由 `tools/gen_contracts.py` 生成，**不要手工编辑**。
3. `tools/check_contract_ddl.py` 校验三者与 DDL 一致（CI 门禁）。
"""
from __future__ import annotations

from app.contracts.enums import ENUM_BY_LABEL, ENUM_COLUMNS

__all__ = ["ENUM_COLUMNS", "ENUM_BY_LABEL"]
