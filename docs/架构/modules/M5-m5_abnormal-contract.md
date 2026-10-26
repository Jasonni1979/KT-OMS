# M5 异常单域

**目录** `backend/app/modules/m5_abnormal/` · **代码行** 2,872 · **service** 12 个

**职责**：异常单 / 类型字典 / 分派引擎 / 动作执行器 / 缺货策略链 / 应急批次 / 名单服务 / 告警扫描

**收编 service**：abnormal, abnormal_action, abnormal_dispatch, abnormal_ext, stockout_strategy

---

## 可写表

| schema | 表数 | 表 |
|---|---|---|
| oms_order | 8 | `ord_abnormal` `ord_abnormal_type_dict` `ord_reason_code_dict` `ord_stockout` `ord_oversold_batch` `ord_risk_list` `ord_pause_command_log` `ord_retrial` |

完整清单见同目录 `tables.yaml`。

## 对外只读接口（跨模块可自由调用）

| 接口 | 说明 |
|---|---|
| `abnormal.types_all` | 全部异常类型 |
| `abnormal.reason_dict` | 原因码字典 |
| `abnormal.type_by_reason_code` | 原因码 → 类型 |
| `abnormal.get` | 取异常单详情 |
| `abnormal_ext.batch_sla_status` | 批次分级 SLA 状态 |
| `abnormal_ext.list_pause_logs` | 暂停命令日志 |

## 对外写接口（跨模块调用须在本模块登记）

| 接口 | 说明 |
|---|---|
| `abnormal.create` | 创建异常单（幂等） |
| `abnormal.raise_by_reason` | 由审单原因落异常单（**M3 需经此接口**） |
| `abnormal.transit` | 异常单状态流转 |
| `abnormal.dispatch` | 触发分派 |
| `abnormal_action.execute` | 执行动作（白名单校验） |
| `abnormal_action.clear_reasons` | 清审单原因（经 M3 接口） |
| `abnormal_ext.aggregate_oversold_batch` | 超卖聚合建批 |
| `abnormal_ext.advance_batch` | 批次阶段推进 |
| `abnormal_ext.pause_order` | 订单暂停编排 |
| `abnormal_ext.resume_order` | 订单恢复 |
| `abnormal_ext.add_to_list` | 加名单（须带 OA 审批单号） |
| `abnormal_ext.remove_from_list` | 移名单 |
| `stockout_strategy.calc_switch_branch` | 换仓测算 |
| `stockout_strategy.switch_branch` | 换仓重试 |
| `stockout_strategy.release_and_retry` | 解除重审 |

## 允许的跨模块调用

| 下游模块 | 类型 | 说明 |
|---|---|---|
| M1 | 读 | 组织 / 货主 / 店铺 / 审批场景 |
| M2 | 读 | 查库存可用量（`stockout_strategy→stock_ledger`） |
| M3 | 读写 | 读审单引擎与单号规则；清审单原因经 M3 接口 |
| M4 | 读写 | 换仓重试 / 解除重审需改履约（`abnormal_action/stockout_strategy→plan_executor/dispatch_service`） |
| M6 | 写 | 转售后（`abnormal_action→aftersale`） |

## 禁止

- 不得 import M7 / M8 的任何符号
- 不得写 oms_order.ord_order
- 不得写 oms_order.ord_order_item
- 不得写 oms_order.ord_audit_reason
- 不得写 oms_order.ord_delivery*
- 不得写 oms_fulfill.*
- 不得写 oms_aftersale.*
- 不得写 oms_gateway.*
- 不得直接 import 其它模块的 `service/` 内部实现 —— 只能从对方 `contract.py` 导入
- 不得 import `app.tools.simulation`（仿真造数工具，非业务代码）

## 已知待收口点

- **M5 ↔ M6 属「业务协作」**（异常单 → 转售后 / 改单 → 落异常单），双向已在设计文档登记。
- **动作白名单由 DDL 的 `action_set` 决定** —— 越权动作被拒是正确行为（FR-02d），不是缺陷。
- `ord_abnormal` 无 `batch_id` 列 —— 批次关联路径是 **异常单 → `ord_stockout.batch_id` → 批次**。
- 名单服务（`ord_risk_list`）两层库：私有优先（货主 > 租户 > 全局）。

## 测试入口

```bash
pytest backend/tests/modules/m5_abnormal/ -q
```
