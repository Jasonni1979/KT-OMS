# M2 gate③ 交付说明 —— 三类异常单人工处置闭环

> 交付日期：2026-10-26　|　里程碑：**M2 gate③（异常单三类人工处置演示）**
> 关联 SRS：SRS-D03.09（异常单与缺货处理）· SRS-D03.02（审单引擎）
> 提交：`m2_gate3_e2e.py` + `goods_match` 插件 + 三个真实缺陷修复

---

## 一、交付结论

**M2 gate③ 验收通过。** 三类异常单各跑通一条**完整真实链路**（不 mock 数据库，
全部走真实服务），端到端断言 **36/36 通过**，并已接入 CI 门禁（含断言数下限校验）。

```
审单投审 → 审单插件产出原因码 → 按原因码字典落异常单 → 自动分派
        → 人工处置动作 → 异常单闭环 → 订单审单原因标记清零
```

---

## 二、三类场景的验收明细

| 场景 | 原因码 | 异常类型 | 处置动作 | 关键断言 |
|---|---|---|---|---|
| 缺货 | `STOCK_SHORTAGE` | `STOCK_SHORT` | 解除重审 `reaudit` | 缺货明细（三元键+缺口量 4）+ 库存快照 + 换仓测算 + 借调扩展位 + 闭环 + 原因清零 |
| 未绑定商品 | `GOODS_UNBOUND` | `PRODUCT_UNBOUND` | 修复后重新审单 `reaudit` | 自动落单 + 分派 + **越权动作被拒**（`cancel` 不在白名单）+ 闭环 + 原因清零 |
| 地址异常 | `ADDRESS_INVALID` | `ADDR_INCOMPLETE` | 重新审单 `reaudit` | 自动落单 + 分派 + **越权动作被拒**（`to_retrial` 不在白名单）+ 转售后扩展位 + 未落假售后单 + 闭环 |

补充验证（动作能力的其他类型分支）：

| 能力 | 类型 | 原因码 | 验收点 |
|---|---|---|---|
| 转复审 `to_retrial` | `PRICE_ABNORMAL` | `PRICE_ABNORMAL` | 复审单落 `ord_retrial` 且关联原订单 |
| 强制放行 `force_pass` | `RISK_HIT` | `ABNORMAL_RISK` | 清审单原因标记 + 留审计痕迹（含 OA 推送待办标记 `pending`） |

---

## 三、为什么动作集是这样分的（DDL 是权威）

DDL 预置的 `ord_abnormal_type_dict.action_set` 决定了每个类型能做什么：

| 类型 | action_set（DDL 预置） |
|---|---|
| `PRODUCT_UNBOUND` | `["reaudit"]` |
| `ADDR_INCOMPLETE` | `["reaudit", "to_aftersale"]` |
| `STOCK_SHORT` | `["reaudit", "suspend", "to_aftersale", "refund"]` |
| `PRICE_ABNORMAL` | `["to_retrial", "cancel"]` |
| `RISK_HIT` | `["suspend", "cancel", "force_pass"]` |

因此：
- 地址异常**不能**转复审、**不能**强制放行 → E2E 断言「越权动作被拒」
- 强制放行只对 `RISK_HIT` 类开放 → 单独用 `ABNORMAL_RISK` 原因码验证
- 转复审只对 `PRICE_ABNORMAL` 类开放 → 单独验证复审单落库

**越权动作被拒绝是正确行为**，不是缺陷——这正是 FR-02d「按类型配置可用动作集」的
落地证据。

---

## 四、本轮修掉的 3 个真实缺陷

### 缺陷 1（严重）审单链路在生产上完全不可用 —— 插件链从未注册

| 项 | 内容 |
|---|---|
| 现象 | 跑审单立刻抛 `KeyError: 链未注册: order.audit` |
| 根因 | `register_audit_chain()` / `register_audit_plugins()` **只有 `seed_audit_demo` 与 `audit_e2e` 两个脚本手动调用**，API 服务与其它脚本都没注册 → 审单一跑就崩 |
| 为何没被发现 | `audit_e2e` 自己注册了链，**恰好把问题盖住**；异常单落单链路此前也没被独立 E2E 走到 |
| 修法 | `audit_engine` 模块导入期调用 `_ensure_audit_chain_registered()`（幂等：链已注册则跳过） |
| 验证 | 导入即注册，10 个插件全部就位（含新增 `goods_match`） |

### 缺陷 2（严重）可空列让审单直接 500

| 项 | 内容 |
|---|---|
| 现象 | `TypeError: float() argument must be a string or a real number, not 'NoneType'` |
| 根因 | `ord_order_item.weight` 是**可空列**（`is_nullable=YES`），`load_context` 里 `float(it.weight)` 遇 NULL 抛异常 → 整个审单链路 500 |
| 修法 | 新增 `_num()` 兜底（None → 0.0），`paid_amount` / `list_price` / `weight` / `order.weight` 汇总全部改用 |
| 影响面 | 任何没填重量的订单行都会触发——生产上这是必现故障 |

### 缺陷 3（中）`GOODS_UNBOUND` 无产出路径 → 未绑定商品永远不落异常单

| 项 | 内容 |
|---|---|
| 现象 | `PRODUCT_UNBOUND` 类型与 `GOODS_UNBOUND` 原因码在字典里都已配置，但**审单插件链里没有任何插件产出该原因码** |
| 后果 | FR-03a 的「审单原因落单」映射形同虚设，未绑定商品永远不会进异常池 |
| 修法 | 新增 `GoodsMatchPlugin`（`goods_match`，CHECK 段）：判定口径 = 订单行未绑定基础物料（`bm_id = 0`），赠品/虚拟品不参与判定 |
| 生效方式 | `plugin_config` 只用于**关闭**插件（`enable: false`），未配置 = 默认启用 → 无需改规则数据 |

---

## 五、新增文件与接口

### 新增
| 文件 | 内容 |
|---|---|
| `backend/app/scripts/m2_gate3_e2e.py` | M2 gate③ 演示 E2E（36 项断言） |
| `backend/app/scripts/_checker.py` | E2E 断言收集器（公共模块，消除各脚本重复的 `Checker`） |
| `backend/app/services/abnormal_dispatch.py` | 异常单分派规则引擎（FR-02c） |
| `backend/app/services/abnormal_action.py` | 异常单动作执行器（FR-02d） |
| `backend/app/models/abnormal.py` 内的 `OrdReasonCodeDict` | 原因码字典 ORM（FR-01c 权威映射源） |
| `backend/app/models/audit.py` 内的 `OrdRetrial` | 复审单 ORM（`ord_retrial` 表此前无模型） |

### 新增接口
| 端点 | 说明 |
|---|---|
| `GET  /api/v1/abnormal/{id}/actions` | 该异常单的可用动作集（未实现动作带 `enabled:false` + 原因，前端据此置灰） |
| `POST /api/v1/abnormal/{id}/auto-dispatch` | 规则引擎自动分派（FR-02c） |
| `POST /api/v1/abnormal/{id}/action` | 执行处理动作（FR-02d） |
| `GET  /api/v1/abnormal/{id}/strategy` | 换仓测算（FR-04b） |
| `POST /api/v1/abnormal/{id}/switch-branch` | 换仓重试（FR-04b） |
| `POST /api/v1/abnormal/{id}/release-retry` | 解除重审（FR-04c） |

---

## 六、关键设计取舍

### 6.1 不重复造轮子
- 换仓直接复用 D03.06 已有的 `DispatchService.dispatch(exclude_branches=...)`
  （它本来就标注了「FR-04b-1 换仓重试」）+ `PlanExecutor.execute`
- 可用量用 `StockLedgerService.get_balance`（与审单 `stock_check` 同源的 D04.02 唯一公式）
- 分派规则复用 D03.03 的 `ord_dispatch_rule` 表（不另建表），只扩展维度
- 条件求值语义与 `DispatchService._conditions_hit` **完全一致**（AND 组合、维度缺失不命中）

### 6.2 扩展位不伪造数据
| 能力 | 状态 | 返回 |
|---|---|---|
| 借调建议（D04.05 额度服务） | W8 不做 | `borrow_stock: {enabled: false, reason: "D04.05 额度服务未实现（P1）"}` |
| 转售后（D05 售后服务） | W9 | `enabled: false` + 原因，**不落任何 `aft_refund` 记录** |
| 平台退款 | W9 | `enabled: false` + 原因 |
| OA 推送（强制放行） | W8-3 | 落库留痕 + `oa_push: "pending"` 待办标记 |

E2E 与单元测试**专门断言了这些扩展位不产生假单据**（如 `aft_refund` 表零新增）。

### 6.3 动作前置状态校验
动作只能在「已分派 / 处理中」执行。待分派的异常单若能直接执行动作，会**绕过状态机**
直接改订单、释放预占，而异常单还挂在待分派池里无人负责 → 已加前置校验。

---

## 七、门禁

| 项 | 结果 |
|---|---|
| pytest | **339 passed**（W8 开始时 276 → +63） |
| M2 gate③ E2E | **36/36**（CI 门禁 + 断言数下限 36） |
| CI 本地复演 | **29/29 全绿**（新增 M2 gate③ 门禁 + 断言数下限校验） |
| GitHub CI | 8 job ↔ 本地 13 项门禁一一对应（新增 M2 gate③ 步骤） |
| ruff / mypy | 全过（118 文件零错误） |
| 模型 ↔ DDL | **67/67 一致** |
| 测试文档 | 353 函数 / 354 用例 / 27 模块 |

---

## 八、尚未完成项（归属明确）

| 项 | 归属 | 说明 |
|---|---|---|
| OA 推送（强制放行/挂起到期提醒） | W8-3 | 已落库留痕 + `pending` 标记，待接企微/OA |
| 改地址执行链路（D03.08） | W8-3 | `to_retrial` 复审单已落库，改单执行待做 |
| 异常单分派通知处理人（企微） | W8-3 | FR-02c「分派即企微通知处理人」待接 D01.07 |
| 转售后（D05）/ 平台退款 | W9 | 扩展位，返回明确未实现 |
| 借调建议（D04.05 额度服务） | W9+ | 扩展位，返回明确未实现 |
| 超卖应急批次（FR-05b~05e） | W8-3 | 类型与 SLA 已配，批次聚合未做 |
| 缺货看板聚合（FR-04d） | W8-3 | 缺货明细已落库，聚合 API 未做 |
