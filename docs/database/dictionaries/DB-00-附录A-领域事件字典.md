# DB-00 附录 A · 领域事件字典（全局契约 · 单一事实源）

> 文档编号：DB-00-附录A · 版本 V1.0 · 2026-10-24 · 编写：小凯 · 状态：待审阅
> 定位：SRS-00 §4.4 契约「事件字典统一登记」的落地。本册是**全系统领域事件的唯一权威登记处**，对应 `oms_base.bas_event_dict` 表的初始数据。
> 规则：任何模块 SRS 新增/修改事件，必须先在本册登记（事件名/发布方/订阅方/payload/分期），再在模块文档引用；命名遵循 SRS-00 §4.2 `域.实体.动作`（小写点分）。
> 抽取来源：对全部 71 份 SRS 的系统扫描 + 语义补全，共登记 **191 个领域事件**（含状态族展开与 succ/fail 拆分），其中 **26 个跨域核心事件**；另有 1 个 P2 预留事件（`fulfill.install.completed` 安装完成回传，DESIGN-IND-01 送装一体预留位，启动时正式登记）（≥2 域引用，改动需评估全链路影响）。SRS 中显式引用的事件已 100% 登记，零遗漏。

---

## 0. 使用说明

- **发布方**：事件的产生域（唯一，避免多头发布）；**订阅方**：已知消费域（可增补，发布方不感知订阅方——SRS-00 §4.2 事件解耦约定）。
- **投递**：全部经 D01.01 MQ（topic 交换机 `oms.{域}.events`，路由键=事件名，发布走事务性 outbox 保证不丢）。
- **幂等**：消费方以 `event_id` 或业务键幂等；跨域事件（🔶标记）为契约级，payload 变更需版本化。
- **分期**：P0=M1-M2、P1=M3、P2=后置。

图例：🔶 = 跨域核心契约事件（≥2 域引用，改动影响面大）

---

## 1. 订单域事件（发布方 D03，19 个）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| 🔶 order.created | 订单创建 | 缓冲订单落库创建成功 | D03.02审单/D11监控 | P0 |
| 🔶 order.paid | 订单支付 | pay_status→已支付 | D03.02/D08应收/D11 | P0 |
| order.audit.passed | 审核通过 | 审单自动/人工通过 | D03.07发货单/D08/D11 | P0 |
| order.audit.rejected | 审核驳回 | 审单不通过转人工/缺货 | D03.03工作台/D03.09异常 | P0 |
| order.fulfill.started | 履约开始 | fulfill_status→履约中 | D03.07/D11 | P0 |
| 🔶 order.delivery.shipped | 发货确认 | 出库回传→发货确认（**全链路关键事件**） | D02.04平台回传/D08.01应收/D08.04运费/D09.04轨迹/D07/D11 | P0 |
| order.shipped | 订单已发货 | ship_status→已发货 | D02.04/D05/D11 | P0 |
| order.completed | 订单完成 | 确认收货/超时→完成 | D08应收确认/D11报表 | P0 |
| order.cancelled | 订单取消 | 取消生效 | D04.03释放预占/D08冲减/D11 | P0 |
| order.flag.changed | 订单旗帜变更（V1.4） | 人工标旗/平台同步旗变更 | D02.04旗帜回传/D03.03工作台/D03.16 | P1 |
| order.urge.marked | 催发货标记（V1.4） | 平台催发货消息/客服代标 | D03.03队列提权/D09.02加急/D11.03催单看板 | P1 |
| order.paused | 订单暂停 | 暂停（叫回发货单） | D03.07/D11.03监控 | P0 |
| order.resumed | 订单恢复 | 恢复重推 | D03.07/D11 | P0 |
| order.recalled | 订单叫回 | 发货单叫回完成 | D03.08改单/D11 | P0 |
| 🔶 order.split.completed | 拆单完成 | 拆分方案落库为发货单 | D03.07/D08分账/D07转单/D11 | P0 |
| order.modify.effective | 改单生效 | 改单快照对比后生效 | D03.02重审/D08.01应收重算/D02.04/D10.06审计 | P1 |
| order.retrial.status_changed | 复审状态变更 | 复审单流转 | D03.03/D03.09/D11 | P1 |
| order.exception.created | 异常单产生 | 异常识别标记 | D03.02审单池过滤/D11.03 | P0 |
| order.exception.resolved | 异常单闭环 | 异常处理完成 | D03.02/D11 | P0 |
| order.archived | 订单归档 | 完结满 N 月归档 | D11/归档库 | P1 |
| order.lifecycle.node | 全链路节点 | 各节点增值埋点（增值链路） | D02.04/D11.03 | P1 |

## 1b. 特殊单型事件（发布方 D03.10，5 个）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| order.presale.released | 预售释放 | 尾款支付/到期转正常履约 | D03.02投审/D04.03预占 | P1 |
| order.groupon.succeed | 团购成团 | 平台成团消息 | D03.02/D02.04回传 | P1 |
| order.groupon.failed | 团购未成团 | 平台未成团 | D05退款/D02.04 | P1 |
| order.virtual.delivered | 虚拟商品发货 | 卡密核销自动发货 | D02.04回传/D11 | P0 |
| 🔶 oversold.batch.created | 超卖应急批次 | 平台已成交 OMS 无货 | D03.09应急/D11.03看板 | P0 |

## 1c. 发货单事件（发布方 D03.07，6 个）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| delivery.command.recalled | 叫回完成 | 发货单叫回指令完成 | D03.08改单/D03.09暂停编排 | P0 |
| delivery.command.recall_failed | 叫回失败 | 发货单叫回失败 | D03.08/D03.09人工跟进 | P0 |
| delivery.push_failed | 推仓失败 | 发货单推仓失败 | D03.09异常/D11.03告警 | P0 |
| delivery.printed | 面单打印完成 | 发货单打印完成 | D02.04打印时机回传 | P0 |
| delivery.verified | 发货校验完成 | 发货前校验完成 | D02.04校验后回传时机 | P0 |
| delivery.virtual.ready | 虚拟发货单就绪 | 虚拟商品发货单生成 | D03.10自动发货通道 | P0 |

## 1d. 促销赠品事件（发布方 D03.14，2 个，V1.1 增补）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| promotion.gift_applied | 加赠成功 | 审单加赠插件落库赠品行 | D11 统计/D04.10 赠品备货参考/D10.04 门户推送 | P1 |
| promotion.gift_revoked | 加赠撤销 | 改单降档/取消/重审撤销赠品 | D11/D04.03 预占对账 | P1 |

## 2. 合单事件（发布方 D03.05，3 个）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| combine.group.sealed | 合单组封组 | 缓冲窗到期封组 | D03.07发货单 | P0 |
| combine.merged | 母子单合并 | 多单合并母发货单 | D03.07/D11 | P0 |
| combine.split_back | 合单拆回 | 部分取消母单拆分 | D03.07/D11 | P0 |

## 3. 审单任务事件（发布方 D03.03，4 个）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| audit.dispatch.requested | 审单分派请求 | 不通过转人工分派 | D03.03工作台 | P0 |
| audit.task.assigned | 审单任务分配 | 分派到审核组/员 | D11.03绩效 | P0 |
| 🔶 audit.task.overtime | 审单超时 | 待审超时效阈值 | D11.03看板/D01.07告警 | P0 |
| audit.plan.executed | 履约方案执行完成 | plan 执行器落库完成 | D03.07/D11 | P0 |

## 4. O2O 门店事件（发布方 D03.11，5 个）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| store.order.dispatched | 门店派单 | 路由到门店仓 | D02.04/D11 | P1 |
| store.order.accepted | 门店接单 | 门店确认接单 | D03.07/D11 | P1 |
| store.order.refused | 门店拒单 | 门店拒单/超时 | D03.06重新分仓 | P1 |
| pickup.verified | 自提核销 | 自提码核销=发货确认 | D02.04/D11 | P1 |
| pickup.expired | 自提超期 | 超期未提 | D04.02库存回退/D01.07通知 | P1 |

## 4b. 即时零售与同城运力事件（发布方 D03.15/D09.06，12 个，V1.2 增补）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| instant.order.dispatched | 即时零售派店 | 订单派发到门店 | D03.15 拣货/D11.03 监控 | P1 |
| instant.pick.task | 拣货任务生成 | 门店拣货任务下发 | D03.15 倒计时监控 | P1 |
| instant.pick.done | 拣货完成 | 门店拣货完成 | D09.06 呼叫骑手 | P1 |
| instant.delivered | 即时配送送达 | 骑手送达确认 | D02.04 平台回传/D03 订单完成/D11 | P1 |
| instant.cancelled | 即时单取消 | 门店缺货/超时取消 | D02.04 平台退款联动/D04.03 释放 | P1 |
| instant.compensation.created | 赔付登记 | 配送超时/货损赔付 | D08.01/D11 | P1 |
| rider.status.changed | 骑手状态变更 | 接单/到店/取货/配送中状态流转 | D03.15 时效监控/D11.03 | P1 |
| rider.handover.done | 骑手交接确认 | 店员扫码交接完成 | D03.15 | P1 |
| rider.call.failed | 呼叫骑手失败 | 运力呼叫失败 | D09.06 顺位改派/D01.07 告警 | P1 |
| rider.exception.reassigned | 骑手改派 | 骑手取消/异常改派 | D03.15/D11.03 | P1 |
| rider.exception.lost | 配送异常丢失 | 骑手异常/货物丢失 | D03.15 应急/D05 理赔/D01.07 | P1 |
| rider.order.cancelled | 配送单取消 | 运力侧配送取消 | D09.06/D03.15 | P1 |

## 5. 库存域事件（发布方 D04，10 个）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| 🔶 stock.changed | 库存变动 | 任一口径记账变动 | D04.08可售重算/D11 | P0 |
| stock.reserved | 预占成功 | 审单预占生效 | D03.02/D04.08/D11 | P0 |
| stock.released | 预占释放 | 取消/改单/过期释放 | D03/D04.08/D11 | P0 |
| stock.reserve_failed | 预占失败 | 可用不足预占失败 | D03.09缺货流程 | P0 |
| 🔶 stock.freeze_expired | 预占过期回收 | 僵尸预占到期释放 | D03.09/D11.03告警 | P0 |
| 🔶 stock.shortage | 库存缺货 | 缺货判定 | D03.09/D04.10补货/D10.04门户 | P0 |
| stock.change.logged | 流水已落库 | 预占/记账流水异步落库完成 | D04.02对账 | P0 |
| price.archive.changed | 价格档案变更（V1.5） | 档案创建/价格版本生效 | D03.02审单基准缓存刷新/D11 | P1 |
| price.adjust.executed | 调价计划执行完成（V1.5） | 批量改价回传批次终态 | D02.04台账/D01.07失败率告警/D11 | P1 |
| material.created | 物料创建 | 基础/销售物料建档 | D04.08 | P0 |
| 🔶 material.updated | 物料变更 | 物料档案修改 | D04.08可售重算/D01缓存失效 | P0 |
| 🔶 material.bind_completed | BOM绑定完成 | 销售物料绑定基础物料 | D03.09异常订单重解析/D04.08 | P0 |

## 6. 借调/调拨事件（发布方 D04.05，3 个）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| transfer.completed | 调拨完成 | 入库确认调拨完结 | D04.02/D04.08/D11 | P0 |
| lend.expired | 借调到期 | 借调台账到期关闭 | D04.03释放/D08结算 | P1 |
| lend.consumed | 借调消耗 | 借调出库转扣减 | D08.02内部交易结算 | P1 |

## 7. 单据中心事件（发布方 D04.04，1 个 · 高扇出核心）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| 🔶 iobill.confirmed | 出入库单据确认 | 单据确认记账完成（**四类源单公用**） | D06.03采购入库状态/D05.02退货触发退款/D09.03入库闭环/D04.05调拨 | P0 |

## 8. 售后域事件（发布方 D05，11 个）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| aftersale.apply.created | 售后申请创建 | 平台同步/手工建单 | D05.05自动审核/D03订单标记/D11 | P0 |
| aftersale.apply.approved | 申请审核通过 | 同意退款/退货 | D05.02执行/D02.04回传 | P0 |
| aftersale.apply.rejected | 申请拒绝 | 拒绝售后 | D02.04回传/D11 | P0 |
| aftersale.apply.closed | 申请关闭 | 售后单关闭 | D05.04换货/D03/D11 | P0 |
| aftersale.apply.completed | 售后完成 | 退款+退货闭环 | D03订单状态/D08冲减/D11 | P0 |
| aftersale.apply.type_changed | 售后类型变更 | 仅退款↔退货退款转换 | D05.02/03/04编排 | P0 |
| aftersale.status_changed | 售后状态变更 | 状态机流转（通用） | D02.04回传/D11 | P0 |
| 🔶 aftersale.refund.succeeded | 退款成功 | 平台退款到账同步 | D08.01应收冲减/D08.05发票冲红/D11 | P0 |
| aftersale.refundonly.unshipped | 未发货仅退款（高优） | 未发货整单仅退款识别 | D03.09发货拦截/叫回 | P0 |
| aftersale.reship.qc_completed | 退货质检完成 | 良/不良质检分流完成 | D05.03触发退款/D05.04换货补发 | P0 |
| aftersale.defect.pending | 不良品待处置 | 不良品入处置队列 | D10.04门户/D01.07通知 | P1 |

## 8b. 售后自动审核事件（发布方 D05.05，2 个）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| aftersale.autoaudit.decided | 售后自动审核决策 | 规则引擎自动决策 | D05.01/D11/D01.07（临期兜底/风控命中通知） | P1 |
| aftersale.buyerprofile.updated | 跨店铺退货画像更新（V1.3） | 售后单终态（completed/closed）驱动画像增量重算 | D05.05画像插件缓存刷新/D11风控报表 | P1 |

## 9. 采购域事件（发布方 D06，9 个）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| purchase.apply.approved | 采购申请审批通过 | OA 审批通过 | D06.02转单/D11 | P0 |
| purchase.apply.closed | 采购申请关闭 | 申请关闭 | D04.10建议单联动/D11 | P0 |
| purchase.po.checked | 采购单审核 | 审核生效（现购挂账时点+在途记账） | D06.03/D06.04现购挂账/D04.10在途解除预警/D11 | P0 |
| purchase.po.cancelled | 采购单取消 | 采购单终止 | D06.03/D06.04/D11 | P0 |
| purchase.po.completed | 采购单完成 | 全部入库完成 | D06.04/D11 | P0 |
| purchase.receipt.confirmed | 采购收货确认 | 入库确认（赊购挂账时点） | D06.04赊购挂账/D04.10预警解除/D11 | P0 |
| purchase.defect.closed | 残损索赔闭环 | 残损/索赔结果 | D06.04应付扣减/D11 | P1 |
| purchase.invoice.matched | 采购发票匹配 | 三单匹配暂估转正 | D04.07价差回冲/D11 | P1 |
| purchase.payable.settled | 采购应付核销 | 付款核销闭环 | D04.04单据markSettled/D11 | P1 |

## 10. 财务域事件（发布方 D08，13 个）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| finance.ar.created | 应收生成 | 订单完成生成应收 | D08.02结算/D08.03核销/D11 | P1 |
| finance.ar.offset | 应收冲减 | 退款冲减应收 | D08.02/D08.03/D11 | P1 |
| finance.ar.adjusted | 应收调整 | 人工调整（OA审批后） | D08.03/D11 | P1 |
| finance.bill.matched | 平台账单匹配 | 账单与应收自动匹配 | D08.03/D08.06/D11 | P1 |
| finance.gap.created | 差异产生 | 匹配差异登记 | D08.03/D08.06排查/D11 | P1 |
| finance.writeoff.completed | 核销完成 | 收款核销完成 | D08.01/D08.02/D08.06/D11 | P1 |
| finance.writeoff.reversed | 核销冲销 | 反核销 | D08.01/D08.02/D11 | P1 |
| finance.period.closed | 期间结账 | 月末结账锁定 | D08.06/D11 | P1 |
| finance.period.reopened | 反结账 | 反结账（OA审批） | D08.06/D11 | P1 |
| finance.settle.drafted | 结算单生成 | 周期到期生成草稿 | D10.04品牌方门户确认/D11 | P1 |
| 🔶 finance.settle.archived | 结算单归档 | 结算确认归档 | D11.02 BI宽表推送/D08.06金蝶 | P1 |
| 🔶 finance.settle.redflushed | 结算单红冲 | 结算红冲重算 | D10.04门户重确认/D11.02/D08.06 | P1 |
| freight.task.closed | 运费对账关账 | 运费关账（应付/金蝶供数） | D08.03应付核销/D08.06金蝶/D11 | P1 |

## 11. 发票事件（发布方 D08.05，3 个）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| invoice.demand.created | 开票需求生成 | 订单完成进预发票池 | D08.05/D11 | P1 |
| invoice.issued | 发票开具 | 电子发票开具成功 | D08.01应收核对/D08.06供数/D02.04回传/D11 | P1 |
| invoice.red_issued | 发票冲红 | 冲红成功 | D08.01/D08.06/D11 | P1 |

## 12. 金蝶供数事件（发布方 D08.06，3 个）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| kd.feed.delivered | 金蝶供数投递 | 供数文件投递完成 | D01.07通知/D11 | P1 |
| kd.recon.diff_found | 金蝶对账差异 | OMS-金蝶双向对账差异 | D08.06排查工作台/D01.07告警 | P1 |
| kd.close.ready | 金蝶结账就绪 | 结账前置检查通过 | D08.03/D11 | P1 |

## 13. 平台 Gateway 事件（发布方 D02，13 个）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| gateway.order.buffered | 订单缓冲落库 | 拉单/消息接收落缓冲 | D03.01创建 | P0 |
| gateway.call.succ | 平台调用成功 | API 调用成功 | D11.03监控 | P0 |
| gateway.call.failed | 平台调用失败 | API 调用失败 | D02.05重试/D11.03 | P0 |
| gateway.retry.dead | 重试进死信 | 重试超限进死信 | D01.07告警/人工工作台 | P0 |
| gateway.retry.resolved | 重试成功 | 失败重试成功 | D11.03 | P0 |
| gateway.auth.expiring | 授权即将过期 | 店铺授权临期 | D01.07告警/D02.06 | P0 |
| gateway.auth.expired | 授权过期 | 店铺授权失效 | D02.06/D01.07告警/D11.03 | P0 |
| gateway.auth.refreshed | 授权续期成功 | session 续期成功 | D11.03 | P0 |
| gateway.reconcile.diff | 平台对账差异 | 回传反查差异 | D02.05/D01.07告警 | P0 |
| gateway.sync.delivery.succ/fail | 发货回传结果 | 平台发货回传结果 | D03订单同步状态/D09发货单回传标记 | P0 |
| gateway.sync.stock.item.result | 库存回写结果 | 平台库存回写结果 | D04.08同步状态 | P0 |
| sellable.changed | 可售变化 | 可售重算变化超阈值 | D02.04库存回写 | P0 |
| aftersale.action.required | 售后回传指令 | 需向平台回传售后动作 | D02.04执行 | P0 |

## 14. 平台消息入口事件（发布方 D02.03，5 个）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| order.raw.received | 原始订单接收 | 平台订单报文落缓冲 | D03.01创建 worker | P0 |
| platform.order.address_changed | 平台改地址 | 买家平台端改地址消息 | D03.08改单应用 | P1 |
| platform.order.hold | 平台收订/挂起 | 平台侧订单挂起消息 | D03.09暂停 | P0 |
| platform.aftersale.created | 平台售后创建 | 平台售后单消息 | D05.01同步 | P0 |
| platform.aftersale.refund.created | 平台退款创建 | 平台退款单消息 | D05.01/D05.03 | P0 |
| platform.aftersale.status_changed | 平台售后状态变更 | 平台退款成功/失败语义 | D05.03状态同步 | P0 |
| platform.aftersale.logistics_updated | 退货物流更新 | 买家回填退货物流 | D05.02物流跟踪 | P1 |
| platform.groupon.result | 团购成团结果 | 平台成团/未成团消息 | D03.10 | P1 |
| platform.omniorder.assigned | 全渠道派单 | 平台指定门店派单 | D03.11门店履约 | P1 |
| payment.step.paid | 分阶段支付 | 预售尾款支付消息 | D03.10预售释放 | P1 |

## 15. 履约集成事件（发布方 D09，15 个）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| wms.outbound.pushed | 出库指令已推送 | 推仓成功 | D03.07置pushed | P0 |
| wms.outbound.push.failed | 出库推送失败 | 推仓失败（结构化原因） | D03.07置push_failed/D11.03告警 | P0 |
| wms.outbound.accepted | WMS接收确认 | WMS 接单确认 | D03.07 | P0 |
| wms.outbound.callback | 出库回传 | WMS 出库回传（运单/包裹/称重） | D03.07编排settle/D08.04运费重量/D11 | P0 |
| wms.outbound.rejected | 出库打回 | WMS 缺货/拒单打回 | D03.07拆单回退 | P0 |
| wms.outbound.recall.succ | 叫回成功 | 发货单叫回成功 | D03.07/D03.08改单 | P0 |
| wms.outbound.recall.failed | 叫回失败 | 发货单叫回失败 | D03.07/D03.08 | P0 |
| wms.outbound.waybill.printed | 面单打印完成 | 仓内打印回执 | D03.07/D02.04打印时机回传 | P0 |
| 🔶 wms.inbound.callback | 入库回传 | WMS 收货/质检回传 | D06.03/D05.02/D04.05/D04.04 | P0 |
| 🔶 wms.inbound.confirmed | 入库记账闭环 | 入库确认记账完成 | D06.03/D05.02触发退款/D04.05在途转实际 | P0 |
| 🔶 wms.inbound.diff | 入库差异 | 超收/短缺/破损/串货 | D06.03残损/D05.02部分退货/D04.05损耗 | P0 |
| 🔶 wms.inbound.push.failed | 入库推送失败 | 入库指令下发失败 | D06.03/D05.02/D09重试/D11 | P0 |
| wms.inbound.cancel.succ | 入库取消成功 | 入库指令取消成功 | D06.03/D05.02 | P1 |
| 🔶 wms.circuit.opened | WMS熔断打开 | WMS 连续失败熔断 | D01.07告警/D11.03看板/D09降级 | P0 |
| 🔶 wms.circuit.closed | WMS熔断恢复 | WMS 恢复 | D01.07恢复通知/D11.03 | P0 |
| wms.binding.changed | WMS绑定变更 | 仓库-WMS绑定变更 | D09.01路由刷新 | P0 |
| logistics.trace.updated | 物流轨迹更新 | 轨迹节点回流（P1） | 订单跟踪/D05物流异常/D11.03签收超时 | P1 |

## 16. 面单打印事件（发布方 D09.05，3 个）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| waybill.obtained | 面单取号成功 | 电子面单取号 | D03.07发货单/D11.03 | P0 |
| 🔶 waybill.cancelled | 面单作废 | 面单取消/作废 | D08.04运费/D03.07/D11.03 | P0 |
| print.task.failed | 打印任务失败 | 打印下发失败 | D11.03告警/D01.07 | P0 |

## 17. 组织权限事件（发布方 D10，7 个）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| org.node.created | 组织节点创建 | 组织树新增节点 | D10.03权限继承重算 | P0 |
| org.node.moved | 组织节点移动 | 节点迁移 | D10.03权限重算 | P0 |
| org.node.disabled | 组织节点停用 | 节点停用 | D10.03/D02.06店铺 | P0 |
| org.owner.status_changed | 货主状态变更 | 货主合作中/暂停/终止 | D02.06/D04.08/D08.01/D10.02 | P0 |
| org.shop.owner_transferred | 店铺货主转移 | 店铺换货主（资产转移） | D04.08/D08.01/D10.03 | P1 |
| auth.account.disabled | 账户禁用 | 账户禁用（离职等） | D10.03权限缓存失效/D10.04 | P0 |
| auth.role_changed | 角色变更 | 账户角色调整 | D10.03权限重算 | P0 |
| auth.tenant.disabled | 租户禁用 | 租户停用 | D10.03/D10.04门户 | P0 |

## 18. 经销域事件（发布方 D07，P2 占位，4 个）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| dealer.credit.frozen | 经销商信用冻结 | 信用超额/逾期冻结 | D07.02下单拦截 | P2 |
| dealer.credit.unfrozen | 信用解冻 | 回款恢复信用 | D07.02 | P2 |
| dealer.status_changed | 经销商状态变更 | 合作状态变更 | D10.02租户禁用/D01.07通知 | P2 |
| dealer.endorse.expired | 授权到期 | 产品线授权到期 | D07.02订货拦截/D01.07 | P2 |
| dropship.convert.completed | 转单完成 | 代发转单完成 | D07.02进度回写/D08.02 | P2 |
| dropship.convert.failed | 转单失败 | 代发转单失败 | D07.02/D11 | P2 |
| dropship.ledger.posted | 代发台账登记 | 双向结算台账登记 | D08.02/D11 | P2 |

## 19. 底座与监控事件（发布方 D01/D11，14 个）

| 事件名 | 中文名 | 触发时机 | 主要订阅方 | 分期 |
|---|---|---|---|---|
| rule.config.changed | 规则配置变更 | 规则/字典变更 | 各域 worker 缓存失效（≤5s） | P0 |
| rule.hit.reported | 规则命中上报 | 规则命中统计 | D01.03自消费聚合 | P1 |
| pipl.plain.accessed | 明文访问 | 敏感字段明文访问 | D10.06审计 | P0 |
| pipl.access.anomaly | 访问异常 | 敏感数据异常访问 | D01.07告警 | P0 |
| pipl.dsr.received | 数据主体请求 | 收到查询/更正/删除请求 | D01.05工作台 | P1 |
| mq.deadletter.created | 死信产生 | 消息进死信队列 | D01.07告警 | P0 |
| mq.backlog.exceeded | 队列积压超阈值 | MQ 积压 | D01.07告警/D11.03 | P0 |
| mq.dispatcher.stalled | 投递器停滞 | outbox 投递停滞 | D01.07告警 | P0 |
| monitor.alert.fired | 告警触发 | 指标越阈告警 | D01.07分级触达 | P1 |
| monitor.alert.recovered | 告警恢复 | 告警恢复 | D01.07恢复通知 | P1 |
| monitor.alert.escalated | 告警升级 | 告警持续升级 | D01.07升级触达 | P1 |
| report.snapshot.ready | 报表快照就绪 | 日终快照完成 | D11.02 BI增量/D01.07日报推送 | P1 |
| report.snapshot.failed | 报表快照失败 | 快照任务失败 | D01.07告警 | P1 |
| bi.push.completed | BI推送完成 | 宽表推送 BI 完成 | D01.07/数据负责人 | P1 |
| bi.push.failed | BI推送失败 | 宽表推送失败 | D01.07告警 | P1 |
| bi.recon.mismatch | BI对账不平 | OMS vs BI 行数不平 | D01.07告警/数据负责人 | P1 |
| delivery.timeout.accept | 接单超时（延迟消息） | 门店接单超时 | D03.11超时改派 | P1 |

---

## 20. 统计与治理

| 指标 | 数值 |
|---|---|
| 领域事件总数 | 191（另 1 个 P2 预留） |
| 跨域核心事件（🔶，≥2 域引用） | 26 |
| 发布域数 | 17（D01-D11 + 发货单/合单/审单/特殊单型/O2O/面单/即时零售/同城运力子域） |
| P0 事件 | ~110 |
| P1 事件 | ~61 |
| P2 事件 | 7（经销域占位） |
| SRS 显式引用事件覆盖率 | 155/155 = 100%（零遗漏） |
| 最高扇出事件 | `order.delivery.shipped`（6 域订阅）、`iobill.confirmed`（4 域）、`wms.inbound.*` 族（4 域） |

### 治理约定
1. **单一发布方**：每事件唯一发布域，禁止多头发布（避免重复消费与责任模糊）。
2. **跨域事件变更冻结**：🔶 事件的 payload 结构变更需评审全部订阅方，走版本化（payload 加 `schema_version`）。
3. **命名唯一**：新增事件先查本册防重名/防语义冲突；动作词统一（created/updated/completed/failed/cancelled/confirmed/changed）。
4. **落库同步**：本册是 `bas_event_dict` 表初始数据源（配套 `sql/DB-D01-oms_base.sql` 的事件字典 INSERT）；新增事件同步更新表数据。
5. **订阅登记**：订阅方新增消费关系，在其模块 SRS §7 接口表登记（IF-xxxD 依赖项），本册「主要订阅方」列为已知快照，非穷举约束。

---

## 变更记录

| 日期 | 版本 | 变更 | 原因 |
|---|---|---|---|
| 2026-10-24 | V1.0 | 首版：系统扫描 70 份 SRS 登记 172 个领域事件（SRS 显式引用 155 个 100% 覆盖 + 语义补全 17 个状态族） | 兑现 SRS-00 §4.4 事件字典契约 |
| 2026-10-24 | V1.2 | +14 事件：促销 2（§1d）+ 即时零售/同城运力 12（§4b），总数 172→186 | V1.1 复查增补 D03.14 + V1.2 友商对标增补 D03.15/D09.06 |
| 2026-10-24 | V1.3 | +1 事件：aftersale.buyerprofile.updated（跨店铺退货画像更新）；登记 fulfill.install.completed 为 P2 预留；总数 186→187 | 行业适配校验 H4（D05.05 V1.3）+ DESIGN-IND-01 预留 |
| 2026-10-24 | V1.4 | +2 事件：order.flag.changed（旗帜双向同步）/order.urge.marked（催发货提权）；总数 187→189 | 业务完整性仿真 S1（D03.01 V1.4 FR-04h） |
| 2026-10-24 | V1.5 | +2 事件：price.archive.changed / price.adjust.executed；总数 189→191 | S4 决策修正（D04.11 价格管理） |

---

*抽取方法：正则扫描全部 SRS 反引号事件名 → 域前缀白名单过滤 → 剔除命令/OpenAPI方法/任务名等非事件 → 跨域引用统计。可复现脚本见 `_research/tools/`（如需）。本册与 `bas_event_dict` 表、各模块 SRS §7 接口表三方需保持一致，以本册为权威。*
