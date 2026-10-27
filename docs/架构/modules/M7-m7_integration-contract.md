# M7 外部集成

**目录** `backend/app/modules/m7_integration/` · **代码行** 3,093 · **service** 11 个

**职责**：平台拉单 / 平台回传 / WMS 指令通道 / 导入中心

**收编 service**：gateway, pull, sync, wms_channel, wms_events, writeback, import_center

---

## 可写表

| schema | 表数 | 表 |
|---|---|---|
| oms_gateway | 24 | `gw_adapter_config` `gw_api_fail` `gw_api_log` `gw_credential_audit` `gw_enum_mapping` `gw_errcode_dict` `gw_msg_notify` `gw_openapi_app` `gw_openapi_log` `gw_openapi_register` `gw_order_buffer` `gw_order_buffer_item` `gw_order_buffer_promotion` `gw_platform_config` `gw_pull_watermark` `gw_ratelimit_config` `gw_recon_diff` `gw_rpc_pending` `gw_shop` `gw_shop_auth` `gw_shop_config` `gw_stock_sync_batch` `gw_stock_sync_item` `gw_writeback_task` |
| oms_fulfill | 5 | `ful_outbound_cmd` `ful_outbound_callback` `ful_outbound_buffer` `ful_cmd_fail` `ful_channel_log` |

完整清单见同目录 `tables.yaml`。

## 对外只读接口（跨模块可自由调用）

| 接口 | 说明 |
|---|---|
| `gateway.call` | 调平台 OpenAPI（统一入口） |
| `gateway.refund_list_get` | 拉平台售后报文（D05.01 FR-01a） |
| `pull.get_watermark` | 拉单水位 |
| `sync.sync_status` | 库存同步状态 |
| `wms_channel.query_order` | 查 WMS 侧订单状态 |
| `writeback.list_tasks` | 列回传任务 |

## 对外写接口（跨模块调用须在本模块登记）

| 接口 | 说明 |
|---|---|
| `pull.poll_shop` | 按店铺轮询拉单 |
| `pull.pull_single` | 单店拉单 |
| `sync.writeback` | 库存回传 |
| `sync.writeback_shop` | 单店库存回传 |
| `sync.recon_shop` | 库存对账 |
| `wms_channel.push` | 推 WMS 出库指令 |
| `wms_channel.recall` | 叫回 |
| `wms_channel.resume` | 恢复（重推） |
| `wms_channel.receive_callback` | 接收 WMS 回传（落回调 + 触发编排） |
| `writeback.send_delivery` | 发货回传平台 |
| `writeback.on_order_shipped` | 订单已发货回传 |
| `writeback.retry_pending` | 重试待发回传 |
| `import_center.create_task` | 建导入任务 |
| `import_center.run_task` | 跑导入任务 |

## 允许的跨模块调用

| 下游模块 | 类型 | 说明 |
|---|---|---|
| M1 | 读 | 店铺 / 货主 / 组织 |
| M2 | 读 | SKU 映射 / 可售（`pull→sku_mapping`、`sync→sellable`） |
| M3 | 写 | 拉单建单（`pull→order_create`） |
| M4 | 写 | 回传推进发货单（`wms_events→delivery_service`） |
| M5 | 写 | 回传异常落单（`wms_events→abnormal`） |

## 禁止

- 不得 import M6 / M8 的任何符号
- 不得写 oms_order.*
- 不得写 oms_fulfill.*
- 不得写 oms_stock.*
- 不得写 oms_aftersale.*
- 不得写 oms_base.bas_event_outbox（白名单除外）
- 不得直接 import 其它模块的 `service/` 内部实现 —— 只能从对方 `contract.py` 导入
- 不得 import `app.tools.simulation`（仿真造数工具，非业务代码）

## 已知待收口点

- **本模块是未来的首个拆分候选**（IO 密集 / 故障域独立），契约已为此预留。
- **两套错误分级不可混用**：通道侧 `ful_cmd_fail.err_class` = RETRYABLE/FATAL/BIZ_REJECT；平台侧 `gw_api_fail.err_level` = RETRYABLE/RATE_LIMITED/AUTH/MANUAL/FATAL。
- **回传幂等键 = 发货单号 + 批次号 + 类型** —— 造演示数据时单号必须唯一。
- **待收口**：`wms_channel ⇄ wms_events` 模块内循环 → P3 消除。

## 测试入口

```bash
pytest backend/tests/modules/m7_integration/ -q
```
