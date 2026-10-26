# M6 售后与改单

**目录** `backend/app/modules/m6_aftersale/` · **代码行** 1,804 · **service** 9 个

**职责**：售后申请 / 审核 / 退款单 / 改地址（快照 + 差异对比 + 叫回联动）

**收编 service**：aftersale, modify

---

## 可写表

| schema | 表数 | 表 |
|---|---|---|
| oms_aftersale | 23 | `aft_audit_task` `aft_auto_audit_log` `aft_auto_audit_rule` `aft_buyer_profile` `aft_defect_disposal` `aft_exchange` `aft_exchange_item` `aft_exchange_log` `aft_reason_dict` `aft_refund` `aft_refund_alloc` `aft_refund_log` `aft_reship` `aft_reship_item` `aft_reship_package` `aft_reship_sn` `aft_return_address` `aft_return_apply` `aft_return_apply_item` `aft_return_apply_log` `aft_return_logistics` `aft_risk_flag` `aft_timeout_monitor` |
| oms_order | 3 | `ord_order_modify` `ord_order_snapshot` `ord_modify_log` |

完整清单见同目录 `tables.yaml`。

## 对外只读接口（跨模块可自由调用）

| 接口 | 说明 |
|---|---|
| `aftersale.list_applies` | 列售后申请 |
| `aftersale.get_apply` | 取售后申请详情 |
| `modify.list_modifies` | 列改单 |
| `modify.get_modify` | 取改单详情（含快照与差异） |

## 对外写接口（跨模块调用须在本模块登记）

| 接口 | 说明 |
|---|---|
| `aftersale.create_apply` | 建售后申请（幂等） |
| `aftersale.transit` | 售后单状态流转（§5.1 权威流转表） |
| `aftersale.audit` | 审核（同意 / 拒绝） |
| `aftersale.create_refund` | 生成退款单 |
| `aftersale.refund_transit` | 退款单状态推进 |
| `modify.create_address_modify` | 发起改地址改单 |
| `modify.complete_recall_and_effective` | 叫回成功后生效 |
| `modify.cancel_recall_modify` | 撤销改单恢复现场 |

## 允许的跨模块调用

| 下游模块 | 类型 | 说明 |
|---|---|---|
| M1 | 读 | 组织 / 货主 / 店铺 |
| M4 | 写 | 叫回发货单（`modify→wms_channel` 经 M7，此处为业务协作） |
| M5 | 读写 | 查异常单；改单失败落异常单（`modify→abnormal`） |
| M7 | 写 | 叫回指令（`modify→wms_channel`） |

## 禁止

- 不得 import M2 / M3 / M8 的任何符号
- 不得写 oms_order.ord_order
- 不得写 oms_order.ord_order_item
- 不得写 oms_order.ord_abnormal*
- 不得写 oms_order.ord_audit_reason
- 不得写 oms_stock.*
- 不得写 oms_fulfill.*
- 不得写 oms_gateway.*
- 不得直接 import 其它模块的 `service/` 内部实现 —— 只能从对方 `contract.py` 导入
- 不得 import `app.tools.simulation`（仿真造数工具，非业务代码）

## 已知待收口点

- **收货人密文不落明文**：`ord_receiver.name_enc/mobile_enc/address_enc` 是 blob，快照与差异对比一律用 hex（PIPL 合规）。
- 售后状态是 **tinyint**（0=待关联 … 7=完成 / 8=拒绝 / 9=关闭），枚举以 **DDL COMMENT 为权威**。
- `aft_return_apply` 有 3 个 **VIRTUAL 生成列**（`platform_refund_id` / `cs_intervene_flag` / `platform_aftersale_type_raw`）→ **不得 INSERT、不得映射为 ORM 可写列**。
- 改单表 `ord_order_modify` / `ord_order_snapshot` 此前**无 ORM 模型**，W9 已补。

## 测试入口

```bash
pytest backend/tests/modules/m6_aftersale/ -q
```
