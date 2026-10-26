# M4 履约与发货

**目录** `backend/app/modules/m4_fulfill/` · **代码行** 4,402 · **service** 5 个

**职责**：拆单 / 发货单 / 四指令状态机 / 分派计划执行 / 换仓重试

**收编 service**：split_service, plan_executor, delivery_service, dispatch, dispatch_service

---

## 可写表

| schema | 表数 | 表 |
|---|---|---|
| oms_fulfill | 36 | `ful_addr_keyword` `ful_area_router` `ful_branch` `ful_branch_dly` `ful_call_decision` `ful_carrier` `ful_carrier_metric` `ful_city_freight` `ful_dly_corp` `ful_dly_product` `ful_freight_region_price` `ful_freight_template` `ful_handover` `ful_inbound_callback` `ful_inbound_cmd` `ful_inbound_diff` `ful_print_log` `ful_print_task` `ful_print_template` `ful_print_tmpl_binding` `ful_rider_call` `ful_rider_track` `ful_route_log` `ful_shop_carrier` `ful_shop_dly` `ful_store_carrier_map` `ful_suspend` `ful_trace_node` `ful_trace_sub` `ful_unreach_area` `ful_waybill` `ful_waybill_account` `ful_waybill_segment` `ful_wms` `ful_wms_binding` `ful_wms_health` |
| oms_order | 14 | `ord_delivery` `ord_delivery_item` `ord_delivery_item_detail` `ord_delivery_log` `ord_delivery_diff` `ord_delivery_package` `ord_dispatch_plan` `ord_dispatch_rule` `ord_branch_dispatch_rule` `ord_routing_decision_log` `ord_branch_change_log` `ord_split_rule` `ord_split_trace` `ord_fulfill_plan` |

完整清单见同目录 `tables.yaml`。

## 对外只读接口（跨模块可自由调用）

| 接口 | 说明 |
|---|---|
| `delivery_service.get` | 取发货单快照 |
| `delivery_service.query_order` | 按订单查发货单 |
| `dispatch_service.get_fulfill_view` | 订单的履约视图 |
| `plan_executor.get_plan` | 取分派计划 |
| `plan_executor.list_plans` | 列分派计划 |
| `split_service.get` | 取拆单结果 |
| `dispatch.match_rule` | 分派规则匹配 |

## 对外写接口（跨模块调用须在本模块登记）

| 接口 | 说明 |
|---|---|
| `delivery_service.create_from_plan` | 由计划生成发货单 |
| `delivery_service.transit` | 发货单状态机推进（唯一入口） |
| `delivery_service.push` | 推 WMS |
| `delivery_service.recall` | 叫回 |
| `delivery_service.recall_result` | 叫回结果回写 |
| `delivery_service.resume` | 恢复（重推） |
| `delivery_service.confirm` | 发货确认 |
| `delivery_service.finish` | 完结 |
| `plan_executor.execute` | 执行计划 |
| `plan_executor.execute_manual_plan` | 执行人工计划 |
| `plan_executor.discard_plan` | 废弃计划 |
| `dispatch_service.dispatch` | 分派 |
| `dispatch_service.change_branch` | 换仓 |
| `dispatch_service.retry_with_gap` | 错峰重试 |

## 允许的跨模块调用

| 下游模块 | 类型 | 说明 |
|---|---|---|
| M1 | 读 | 组织 / 货主 / 店铺 |
| M2 | 读写 | 占用与释放库存（`dispatch_service/split_service→stock_ledger`、`plan_executor→freeze`） |
| M7 | 写 | 推 WMS 指令 / 叫回（`delivery_service→wms_channel`） |

## 禁止

- 不得 import M5 / M6 / M8 的任何符号
- 不得写 oms_order.ord_order
- 不得写 oms_order.ord_order_item
- 不得写 oms_order.ord_abnormal*
- 不得写 oms_order.ord_audit_reason
- 不得写 oms_stock.*
- 不得写 oms_aftersale.*
- 不得直接 import 其它模块的 `service/` 内部实现 —— 只能从对方 `contract.py` 导入
- 不得 import `app.tools.simulation`（仿真造数工具，非业务代码）

## 已知待收口点

- **M4 → M7 属「适配器调用」**：发货推 WMS 指令是主链路，方向合理。
- **M4 ↔ M7 的反向边（M7 → M4，回传推进发货单）属「回调关系」**，不是逻辑环 —— 已在设计文档 §5.2 登记为白名单。
- **待收口**：`plan_executor` 直接写 `ord_audit_reason`（M3 的表）→ 改调 M3 的 `clear_reasons`。
- **待收口**：`wms_channel ⇄ wms_events` 模块内循环依赖 → P3 拆分时消除。
- 本模块是**最大的一个**（4.4k 行 / 5 service）→ P3 必须把 `delivery_service`（1403 行）拆开。

## 测试入口

```bash
pytest backend/tests/modules/m4_fulfill/ -q
```
