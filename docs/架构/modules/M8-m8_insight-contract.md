# M8 报表与监控

**目录** `backend/app/modules/m8_insight/` · **代码行** 298 · **service** 1 个

**职责**：履约监控看板 / 指标 / 数据体检（只读全部模块）

**收编 service**：monitor

---

## 可写表

| schema | 表数 | 表 |
|---|---|---|
| oms_report | 24 | `rpt_aftersale` `rpt_alert_claim` `rpt_audit_perf` `rpt_bi_push_log` `rpt_fulfill_sla` `rpt_indicator_dict` `rpt_monitor_metric` `rpt_near_expire` `rpt_order_wide` `rpt_platform_compare` `rpt_product_sale_rank` `rpt_profit` `rpt_sales_daily` `rpt_sales_monthly` `rpt_service_fee` `rpt_settlement_wide` `rpt_slow_moving` `rpt_snapshot_task` `rpt_stock_age` `rpt_stock_snapshot` `rpt_stock_turnover` `rpt_stock_wide` `rpt_stockout` `rpt_timeout_alert` |

完整清单见同目录 `tables.yaml`。

## 对外只读接口（跨模块可自由调用）

| 接口 | 说明 |
|---|---|
| `monitor.overview` | 看板总览（指标卡 + 分域明细） |
| `monitor.pull_watermark` | 拉单水位 |
| `monitor.audit_backlog` | 审单积压 + SLA 分级 |
| `monitor.writeback_failures` | 回传失败台账 |
| `monitor.abnormal_realtime` | 异常单实时分布 |

## 对外写接口（跨模块调用须在本模块登记）

（无 —— 本模块不向外暴露写接口）

## 允许的跨模块调用

（无 —— 本模块不依赖其它模块）

## 禁止

- 不得 import M1 / M2 / M3 / M4 / M5 / M6 / M7 的内部符号
- 不得写 除 oms_report.* 外的任何表
- 不得直接 import 其它模块的 `service/` 内部实现 —— 只能从对方 `contract.py` 导入
- 不得 import `app.tools.simulation`（仿真造数工具，非业务代码）

## 已知待收口点

- **只读全部模块，但不被任何模块依赖**（最顶层）。
- 看板当前是**实时快照口径**（直查业务表），非 D11.01 报表口径 —— 差异须在 `caliber_note` 明示。
- 拉单水位尚未含 Redis 分钟埋点 → W10 统一接入。

## 测试入口

```bash
pytest backend/tests/modules/m8_insight/ -q
```
