# M3 订单与审单

**目录** `backend/app/modules/m3_trade/` · **代码行** 2,461 · **service** 6 个

**职责**：订单建单 / 单号生成 / 金额分摊 / 审单插件链 / 审单原因落库

**收编 service**：order_create, order_bn, allocation, audit_engine, audit_plugins, audit_rule

---

## 可写表

| schema | 表数 | 表 |
|---|---|---|
| oms_order | 15 | `ord_order` `ord_order_item` `ord_receiver` `ord_order_pmt` `ord_order_fail` `ord_status_log` `ord_audit_reason` `ord_audit_plugin_perf` `ord_audit_work_log` `ord_audit_task` `ord_audit_batch_log` `ord_audit_group` `ord_audit_rule` `ord_combine_blacklist` `ord_combine_group` |
| oms_audit | 6 | `aud_data_access_log` `aud_destroy_log` `aud_entity_registry` `aud_hash_anchor` `aud_operation_log` `aud_retention_policy` |

完整清单见同目录 `tables.yaml`。

## 对外只读接口（跨模块可自由调用）

| 接口 | 说明 |
|---|---|
| `audit_engine.blocked` | 订单是否被审单拦截 |
| `audit_engine.reason_codes` | 该单的审单原因码集合 |
| `audit_engine.load_context` | 审单上下文（插件链共享） |
| `audit_rule.matches` | 规则命中判定 |
| `audit_rule.explain` | 规则命中解释 |
| `audit_rule.in_effective_window` | 规则是否在生效窗口 |
| `order_create.get_order` | 取订单快照（**需新增**） |

## 对外写接口（跨模块调用须在本模块登记）

| 接口 | 说明 |
|---|---|
| `order_create.create` | 建单（幂等） |
| `audit_engine.submit` | 提交审单（跑插件链） |
| `audit_engine.write_reasons` | 落审单原因 |
| `audit_engine.save_plan` | 落分派计划 |
| `audit_engine.clear_reasons` | 清审单原因（闭环联动，**M4 需经此接口**） |

## 允许的跨模块调用

| 下游模块 | 类型 | 说明 |
|---|---|---|
| M1 | 读 | 组织 / 货主 / 店铺 |
| M2 | 读 | 查库存可用量（`audit_plugins→stock_ledger`）、SKU 映射（`order_create→sku_mapping`） |
| M4 | 读 | 审单插件做**预演拆单**（`audit_plugins→split_service/dispatch_service`） |
| M5 | 写 | 审单落异常单（`audit_engine→abnormal`） |

## 禁止

- 不得 import M6 / M7 / M8 的任何符号
- 不得写 oms_fulfill.*
- 不得写 oms_aftersale.*
- 不得写 oms_gateway.*
- 不得写 oms_order.ord_abnormal*
- 不得写 oms_order.ord_delivery*
- 不得直接 import 其它模块的 `service/` 内部实现 —— 只能从对方 `contract.py` 导入
- 不得 import `app.tools.simulation`（仿真造数工具，非业务代码）

## 已知待收口点

- **M3 → M4 属「相邻层协作·读」**：审单阶段预演拆单（选仓 / 拆单测算）是业务必需，登记为白名单边。
- **M3 → M5 属「相邻层协作·写」**：审单落异常单。M5 必须暴露公开写接口 `abnormal.raise_by_reason`。
- `ord_audit_reason` 的写权**独归 M3** —— M4 的 `plan_executor` 当前直接写该表，**待收口**：改调 M3 的 `audit_engine.clear_reasons`。

## 测试入口

```bash
pytest backend/tests/modules/m3_trade/ -q
```
