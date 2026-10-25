# canonical 订单字段映射表

> **契约地位**：本表是 D02（平台接入）→ D03（订单域）的唯一字段契约。
> D03 及下游**不得感知平台差异**，平台特有信息一律进 `platform_extra`。
>
> - 契约定义源：`backend/app/schemas/canonical.py`（CanonicalOrder / CanonicalOrderItem /
>   CanonicalReceiver / CanonicalPromotion）
> - 缓冲表落地：`oms_gateway.gw_order_buffer` + `gw_order_buffer_item` + `gw_order_buffer_promotion`
> - 订单域落地：`oms_order.ord_order` + `ord_order_item` + `ord_receiver` + `ord_order_pmt`
> - 依据：SRS-D02.03 §6.1、FR-04a~04c；SRS-D03.01 FR-01b、FR-04b、FR-06a
>
> **改动规则**：本表任一字段口径变更，必须同步 ①canonical schema ②适配器映射 ③本表
> ④`tools/test_case_map.py` 的需求追溯列。CI 有文档同步门禁兜底。

## 1. 订单头字段映射

| canonical 字段 | 含义 | 淘系（模拟器）来源 | ord_order 落点 | 校验规则 |
|---|---|---|---|---|
| `platform` | 平台标识 | 固定 `taobao` | `ord_order`（经 createway 区分来源） | 非空 |
| `shop_id` | 店铺 ID | 拉单上下文（店铺配置） | `ord_order.shop_id` | 店铺须存在且授权未过期 |
| `platform_order_bn` | 平台单号 | `tid` | `ord_order.platform_order_bn` | 非空；幂等键成分 |
| `order_type` | 订单类型 | 固定 `normal` | `ord_order.order_type` | 枚举 |
| `platform_status` | 平台原始状态 | `status`（淘系 WAIT_SELLER_SEND_GOODS 等） | `ord_order.platform_extra.platform_status` | 原样保留 |
| `canonical_status` | 标准状态 | 由 `status` 映射（见 §4） | `ord_order.platform_extra` + 状态初始化 | 枚举 |
| `platform_modified` | 平台最后修改时间 | `modified` | `ord_order.platform_extra` | **版本收敛唯一依据** |
| `platform_create_time` | 平台下单时间 | `created` | `ord_order.order_time` | 非空 |
| `pay_time` | 平台付款时间 | `pay_time` | `ord_order.pay_time` | COD 可空 |
| `is_cod` | 货到付款 | 报文无货到付款 → `false` | `ord_order.is_cod` | 默认 false |
| `total_amount` | 商品总额 | `total_fee`（商品总价） | `ord_order.list_amount` | ≥0 |
| `customer_paid` | 客户实付 | `buyer_pay_amount` | `ord_order.paid_amount` | **双口径必填** |
| `platform_bear_total` | 平台承担合计 | `platform_bear_amount` | `ord_order.platform_subsidy` | 缺失时由比例分摊补算 + 告警 |
| `merchant_bear_total` | 商家承担合计 | `total_fee − customer_paid + freight − platform_bear` | `ord_order.shop_discount` | 恒等式校验 |
| `freight` | 运费 | `post_fee` | `ord_order.freight` | 不参与优惠分摊 |
| `buyer_message` | 买家留言 | `buyer_msg` | `ord_order.buyer_memo` | 展示脱敏 |
| `seller_memo` | 卖家备注 | `seller_memo` | `ord_order.warehouse_memo` | 可空 |
| `promotion_source` | 推广来源 | 报文 `promotion` 解析 | `ord_order.promotion_source` | 缺省 `organic` |
| `promotion_pid` | 推广位 ID | 报文 `promotion.pid` | `ord_order.promotion_pid` | 可空 |
| `promotion_id` | 推广活动 ID | 报文 `promotion.id` | `ord_order.promotion_id` | 可空 |
| `flag_color` | 旗帜颜色 | `seller_flag`（1-5，模拟器暂不产出） | `ord_order.flag_color` | 默认映射见 §4 |
| `urge_flag` | 催发货标记 | 催单消息 → 1 | `ord_order.urge_flag` | 默认 0 |
| `warehouse_hint` | 平台指定仓 | `warehouse_type` | `ord_order.platform_extra` | 可空 |
| `logistics_hint` | 物流提示 | 报文物流字段 | `ord_order.platform_extra` | 可空 |
| `platform_extra` | 平台特有字段 | 原始报文关键属性留档 | `ord_order.platform_extra` | JSON |
| `convert_warnings` | 转换告警 | 映射过程产生 | `ord_order.platform_extra.convert_warnings` | JSON 数组 |

## 2. 订单行字段映射

| canonical 字段 | 含义 | 淘系来源 | ord_order_item 落点 | 校验规则 |
|---|---|---|---|---|
| `line_no` | 行号 | 序号生成 | `ord_order_item` 行序（无独立列） | 从 1 连续 |
| `oid` | 平台子单号 | `oid` | `ord_order_item.platform_oid` | 售后对账键 |
| `platform_sku_id` | 平台 SKU 编码 | `sku_id` | `ord_order_item.platform_sku_code` | **非空**；映射查询键 |
| `platform_item_id` | 平台商品 ID | `item_id` | `ord_order_item.platform_extra` | 可空 |
| `goods_name` | 商品名 | `goods_name` | `ord_order_item.platform_extra` | 可空 |
| `sku_spec` | 规格 | `sku_properties_name` | `ord_order_item.platform_extra` | 可空 |
| `num` | 数量 | `num`（子单数量） | `ord_order_item.nums` | **>0**，硬校验 |
| `sale_price` | 成交单价 | `price` | `ord_order_item.list_price` | ≥0 |
| `list_amount` | 行原价金额 | `price × num` | `ord_order_item.list_amount` | = sale_price × num |
| `customer_paid_line` | 行客户实付 | 分摊后 | `ord_order_item.paid_amount` | Σ行 = 单实付（不含运费）±0.01 |
| `platform_bear_line` | 行平台承担 | `divide_order_fee`（平台行级优惠分摊） | `ord_order_item.platform_subsidy` | Σ行 = 单平台承担；与单级不符时回退比例分摊 |
| `merchant_bear_line` | 行商家承担 | 分摊后 | `ord_order_item.shop_discount` | Σ行 = 单商家承担 |
| `refund_status` | 行级退款标识 | 售后报文 | `ord_order_item.platform_extra` | 枚举 |
| `gift_flag` | 赠品标记 | 报文 `is_gift` | `ord_order_item.is_gift` | 0/1 |
| `platform_extra` | 行级平台字段 | `divide_order_fee` 等 | `ord_order_item.platform_extra` | JSON |

### 2.1 平台 SKU → 本地物料的映射链（D03.01 FR-04b 第四项）

```
platform_sku_id
  → oms_stock.inv_sales_material（shop_id + sales_material_bn 匹配）
  → inv_bom_version（生效版）→ inv_bom_item → 基础物料 inv_material
  → ord_order_item.sm_id / bm_id / owner_id / bom_version（**快照固化，不回溯**）
```

- 未命中销售物料 → 触发未知商品自动建档（D02.03 FR-05，见 §5）
- 销售物料存在但 BOM 未绑定 → `parse_status=pending`（软失败，不拒单）

## 3. 收货人字段映射

| canonical 字段 | 含义 | 淘系来源 | ord_receiver 落点 | 安全要求 |
|---|---|---|---|---|
| `receiver.name` | 姓名 | `receiver_name` | `name_enc` + `name_hash` | PIPL 加密 + 盲索引 |
| `receiver.mobile` | 手机 | `receiver_mobile` | `mobile_enc` + `mobile_hash` + `mobile_tail4` | PIPL 加密 + 盲索引 |
| `receiver.province` | 省 | `receiver_state` | `province` | 明文（非敏感） |
| `receiver.city` | 市 | `receiver_city` | `city` | 明文 |
| `receiver.district` | 区 | `receiver_district` | `district` | 明文 |
| `receiver.address` | 详址 | `receiver_address` | `address_enc` + `address_hash` | PIPL 加密 + 盲索引 |
| `receiver.zip` | 邮编 | `receiver_zip` | `zip` | 明文 |
| `receiver.buyer_id` | 买家标识 | `buyer_open_id` | `ord_order.buyer_id_enc` | PIPL 加密 |
| `receiver.buyer_nick` | 买家昵称 | 报文昵称 | `ord_order.buyer_nick` | 展示脱敏 |
| `receiver.encrypted_channel` | 加密通道 | 固定 `none`（淘系走 oaid 密文体系时置 `oaid`） | `ord_receiver.is_cipher` / 通道标识 | 密文单原样保存 |
| `receiver.cipher_blob` | 平台密文包 | 平台密文字段 | `ord_receiver.cipher_blob` | 原样保存，不解密 |

**合单指纹**（D03.01 FR-07a）：`md5(name_hash + mobile_hash + area_code + address_hash + COD标记 + 店铺参数)`
—— 只用**密文标识/盲索引**参与计算，平台密文单用平台稳定串，不依赖解密。

## 4. 枚举映射

### 4.1 平台状态 → canonical 状态

| 淘系 status | canonical_status | 说明 |
|---|---|---|
| `WAIT_BUYER_PAY` | `unpaid` | 待付款 |
| `WAIT_SELLER_SEND_GOODS` | `unshipped` | 待发货 |
| `WAIT_BUYER_CONFIRM_GOODS` | `shipped` | 已发货（待收货） |
| `TRADE_CLOSED` / `TRADE_CLOSED_BY_TAOBAO` | `closed` | 已关闭 |
| `TRADE_FINISHED` | `finished` | 已完成 |

未识别状态 → `unshipped` + `convert_warnings` 追加「未知平台状态」。

### 4.2 平台旗帜 → OMS 旗帜颜色（D03.01 FR-04h）

| 平台 seller_flag | OMS flag_color | 默认语义 |
|---|---|---|
| 1 | 1 红 | 停发暂缓 |
| 2 | 2 黄 | 待确认 |
| 3 | 3 绿 | 优先放行 |
| 4 | 4 蓝 | 已联系买家 |
| 5 | 5 紫 | VIP 关注 |

语义为**店铺级可配**，此表是默认映射；变更走店铺配置，不改代码。

## 5. 未知商品自动建档联动（D02.03 FR-05）

| 环节 | 动作 | 失败处理 |
|---|---|---|
| ① 映射检查 | `platform_sku_id` 查 `inv_sales_material` | 未命中继续 ② |
| ② 拉平台资料 | 调适配器 `itemGet`（模拟器 `taobao.item.get`） | 拉取失败 → 该行 `parse_status=pending`，订单挂 `waiting` |
| ③ 自动建档 | 复用 `SalesMaterialService.auto_create`（幂等，FR-01a） | 建档失败 → 同上 |
| ④ 回写继续 | 建档成功 → 重新走 §2.1 映射链 | — |

**并发防护**：同一 `platform_sku_id` 建档加 Redis 锁去重（`lock:autocreate:{sku}`）。
**时效**：单商品建档 ≤5s；不阻塞整批（挂起的订单进 `waiting` 状态，建档完成事件驱动恢复投递）。

## 5.1 平台报文金额口径（模拟器对齐）

模拟器（mocks/platform）按下列口径造单，保证平台侧数据自洽：

```
行原价   sub.total_fee = price × num
平台承担 divide_order_fee = 平台承担总额 × (行原价 / 订单原价)     # 行级分摊
订单原价 trade.total_fee = Σ 行原价
实付     trade.buyer_pay_amount = 订单原价 − 平台承担 + 运费
运费     trade.post_fee
```

OMS 侧校验：`Σ(行原价 − 平台承担分摊 − 商家承担分摊) == 实付 − 运费`（容差 0.01）。
平台承担总额由 `platform_bear_amount` 提供；缺失或与行级分摊不符时 → 比例分摊 + 告警。

## 6. 金额勾稽恒等式（D03.01 FR-06a）

```
订单头：paid_amount = list_amount − shop_discount − platform_subsidy + freight
行级：  paid_i       = list_i     − shop_discount_i − platform_subsidy_i
校验：  Σ paid_i     = paid_amount − freight        （容差 0.01 元，超差拒单转人工）
```

行级分摊算法见 SRS-D03.01 §5.2（比例分摊 + 尾差归最大金额行 + 双口径二次拆分）。
平台报文自带行级分摊时**优先采用平台值**，OMS 只做勾稽校验；超差回退比例分摊并记日志。

## 7. 已知边界与处理策略

| 场景 | 处理 | 依据 |
|---|---|---|
| 平台金额字段缺失 | 按比例分摊补算 + `convert_warnings` 记录 | FR-04c |
| 平台状态未识别 | 归 `unshipped` + 告警 | §4.1 |
| 收货人省市区无法解析 | **不拒单**，打「地址待清洗」标 + 带标投审 | D03.01 FR-04c 软失败 |
| 商品未绑定 | `parse_status=pending` + 暂缓投审 | D03.01 FR-04c 软失败 |
| 金额勾稽超差（>0.01） | **拒单** → `is_fail=1` + 落 `ord_order_fail` | D03.01 FR-04c 硬失败 |
| 店铺无效/授权过期 | **拒单** → `is_fail=1` | D03.01 FR-04c 硬失败 |
| 订单行数量 ≤0 | **拒单** → `is_fail=1` | D03.01 FR-04c 硬失败 |
| 平台密文单 | 密文原样保存，`encrypted_channel=oaid`，不解密 | D02.03 §5.4 |
