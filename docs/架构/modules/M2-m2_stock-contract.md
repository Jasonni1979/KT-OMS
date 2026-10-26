# M2 商品与库存账本

**目录** `backend/app/modules/m2_stock/` · **代码行** 3,161 · **service** 7 个

**职责**：物料 / SKU 映射 / 可用量计算 / 库存台账 / 预占冻结 / 出入库单 / 盘点对账

**收编 service**：material, sku_mapping, stock_ledger, freeze, sellable, stock_recon, io_bill

---

## 可写表

| schema | 表数 | 表 |
|---|---|---|
| oms_stock | 55 | `inv_activity_lock_pool` `inv_alert_rule` `inv_barcode` `inv_batch` `inv_batch_assign` `inv_batch_stock` `inv_bom_item` `inv_bom_version` `inv_brand` `inv_consignment_value` `inv_cost_change_log` `inv_cost_config` `inv_cost_snapshot` `inv_estimate_batch` `inv_expire_disposal` `inv_expire_rule` `inv_freeze_log` `inv_fukubukuro_item` `inv_fukubukuro_plan` `inv_independent_quota` `inv_io_bill` `inv_io_bill_item` `inv_io_bill_type` `inv_io_callback_log` `inv_lend_ledger` `inv_lend_rule` `inv_manual_freeze` `inv_material` `inv_material_cat` `inv_ownership_transfer` `inv_ownership_transfer_item` `inv_pickone_candidate` `inv_price_adjust_item` `inv_price_adjust_plan` `inv_price_archive` `inv_price_sync_task` `inv_price_version` `inv_replenish_suggestion` `inv_sales_forecast` `inv_sales_material` `inv_sellable_snapshot` `inv_serial_no` `inv_stock_adjust` `inv_stock_change_log` `inv_stock_config` `inv_stock_ledger` `inv_stock_recon_diff` `inv_stock_snapshot` `inv_stocktake_item` `inv_stocktake_plan` `inv_stocktake_task` `inv_sync_log` `inv_sync_strategy` `inv_transfer_item` `inv_transfer_order` |
| oms_base | 2 | `bas_import_task` `bas_import_error` |

完整清单见同目录 `tables.yaml`。

## 对外只读接口（跨模块可自由调用）

| 接口 | 说明 |
|---|---|
| `stock_ledger.available_of` | 查可用量（扣冻结后） |
| `stock_ledger.get_balance` | 查台账余额 |
| `stock_ledger.get_row` | 按库存键查台账行 |
| `stock_ledger.query` | 台账流水查询 |
| `sku_mapping.find_sales_material` | 平台 SKU → 基础物料 |
| `sellable.calc` | 批量算可售 |
| `sellable.calc_single` | 单物料算可售 |
| `sellable.get_strategy` | 取可售策略 |
| `sellable.shop_branches` | 店铺可用仓 |
| `material.get` | 按 id 取物料 |
| `material.list_all` | 物料全量列表 |
| `material.children` | 物料分类子树 |
| `freeze.query_logs` | 冻结流水查询 |

## 对外写接口（跨模块调用须在本模块登记）

| 接口 | 说明 |
|---|---|
| `stock_ledger.apply_change` | 台账变更（唯一写入口） |
| `stock_ledger.adjust` | 库存调整 |
| `freeze.reserve` | 预占冻结 |
| `freeze.release` | 释放冻结 |
| `freeze.settle` | 冻结结算（发货核销） |
| `freeze.expire_reclaim` | 过期回收 |
| `io_bill.create` | 出入库单创建 |
| `io_bill.push_to_wms` | 出入库单推 WMS |
| `io_bill.confirm` | 出入库单确认 |
| `material.create` | 建物料 |
| `material.update` | 改物料 |

## 允许的跨模块调用

| 下游模块 | 类型 | 说明 |
|---|---|---|
| M1 | 读 | 查组织 / 货主 / 店铺（`material→master`） |

## 禁止

- 不得 import M3 / M4 / M5 / M6 / M7 的任何符号
- 不得写 oms_order.*
- 不得写 oms_fulfill.*
- 不得写 oms_aftersale.*
- 不得写 oms_gateway.*
- 不得直接 import 其它模块的 `service/` 内部实现 —— 只能从对方 `contract.py` 导入
- 不得 import `app.tools.simulation`（仿真造数工具，非业务代码）

## 已知待收口点

- **库存是全系统唯一的余额真相源** —— 其它模块不得直接写 `inv_stock_ledger` / `inv_freeze_log`。
- `freeze` 与 `stock_ledger` 的耦合方向必须保持 `freeze → stock_ledger`（冻结记流水，台账记余额）。
- Redis 可售缓存由 `sellable` 独占维护，失效只经 `sellable.invalidate*`。

## 测试入口

```bash
pytest backend/tests/modules/m2_stock/ -q
```
