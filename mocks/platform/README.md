# mock-platform（淘系平台模拟器）

V1.1 计划 §2.1/§2.2 的仿真基座：让 M1-M3 全程在仿真环境开发与内测，**不依赖淘系测试环境到位**。

## 启动

```bash
# 方式1：docker compose（与后端同栈）
cd KT-OMS/deploy && docker compose up -d mock-platform

# 方式2：本地
cd KT-OMS/mocks/platform && pip install -r requirements.txt
uvicorn app.main:app --port 9000
```

## 关键设计（保真要点）

| 项 | 实现 |
|---|---|
| 入口 | `POST /api/taobao/router`，`method` 参数路由（淘系 TOP 统一网关形态） |
| 签名 | md5(secret + 排序拼接 + secret) 大写，支持 hmac-sha256；`MOCK_TAOBAO_VERIFY_SIGN=0` 可关 |
| 响应包裹 | `error_response` / `{method}_response` + `total_results` |
| 错误码 | isv.invalid-signature / isv.invalid-session-key / isv.trade-not-exist / flow-limit / isv.trade-service-error… |
| 错误注入 | 请求带 `_inject_error=<code>` → 返回该错误码（**让适配器重试/降级逻辑在仿真期被真实锻炼**） |
| 增量语义 | `start_modified`/`end_modified` 时间窗 + `page_no`/`page_size` 分页（淘系语义） |

## 已实现的平台方法

| method | 用途 | 消费方 |
|---|---|---|
| taobao.trade.sold.get | 订单增量拉取 | D02.03 轮询通道 |
| taobao.trade.detail.get | 订单详情（收货人全量） | D02.03 单拉补偿 |
| taobao.item.get | 商品查询 | D04.01 未知商品自动建档 |
| taobao.logistics.online.send | **OMS 发货回传接收**（留档供断言） | D02.04 回传中心 |
| taobao.refund.get / refund.list.get | 售后单查询/增量 | D05.01 售后 |

## 造单引擎

```bash
# 造 10 笔正常单
curl -X POST localhost:9000/sim/orders -H 'Content-Type: application/json' \
  -d '{"scenario":"normal","count":10}'

# 场景库（V1.1 §2.2）：normal/multi_item/out_of_stock/address_abnormal/
#                    unbound_item/buyer_message/big_amount/
#                    refund_only/return_refund/defective_return
```

## 切换真实环境

适配器配置开关：`platform.driver = simulator | taobao`——真实环境就绪后改配置即可，
业务模块零改动（差异只收敛在适配器层）。
