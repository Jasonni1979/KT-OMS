# KT-OMS 界面演示（2026-10-25）

## 录屏

| 文件 | 时长 | 内容 |
|---|---|---|
| `KT-OMS界面巡检-全页面.mp4` | 59s | 登录 → 工作台 → 14 个菜单页逐页巡检 → 切 Tab / 触发对账 / 单据详情 / 树展开 → 退出登录 |
| `KT-OMS界面巡检-深交互.mp4` | 33s | BOM 抽屉 / 库存人工调整（填表提交）/ 对账 / 单据追溯链 / 导入中心 / 条码查询 |

录制方式：Playwright（Chromium）真实浏览器操作 + `recordVideo`，1600×950，locale=zh-CN。
**控制台错误 0 条**（两轮巡检全程无 JS 异常）。

## 截图

`screenshots/` 共 30 张，覆盖：

| 编号 | 页面 | 编号 | 页面 |
|---|---|---|---|
| 00 | 登录页 | 09 | 销售物料与BOM |
| 01 | 登录（已填表） | 10 | 条码管理 |
| 02 | 工作台 | 11 | 导入中心 |
| 03 | 货主档案 | 12 | 库存余额与对账 |
| 04 | 店铺档案 | 13 | 出入库单据 |
| 05 | 仓库档案 | 14 | 租户列表 |
| 06 | 基础物料 | 15 | 库存-对账差异 Tab |
| 07 | 物料分类 | 16 | 库存-对账执行结果 |
| 08 | 品牌档案 | 17 | 单据详情 |

## 本地复现

```bash
# ① 基建（MySQL8 + Redis7 + RabbitMQ + 淘系平台模拟器）
cd deploy && docker compose up -d

# ② 后端（FastAPI :8000）
cd backend && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# ③ 前端（静态服务 + API 反代 :5173，免 Vite dev server）
cd .. && node tools/serve_frontend.mjs 5173
#    或开发模式：cd frontend && node node_modules/vite/bin/vite.js

# ④ 演示数据（走 HTTP API，幂等可重跑）
cd backend && .venv/bin/python -m app.scripts.seed_demo

# ⑤ 业务场景端到端（14 项断言）
.venv/bin/python -m app.scripts.scenario_e2e --gateway http://127.0.0.1:9000
```

登录：`admin` / `Ktoms@2026`

## 本轮修复的三个真实缺陷

1. **模拟器容器时区错位** → 拉单永远取不到数据
   - 现象：`scenario_e2e` 拉单步骤 FAIL（`total_results: 0`）
   - 根因：`mock-platform` 容器默认 UTC，后端按北京时间算水位窗口，差 8 小时
   - 修复：`deploy/docker-compose.yml` 给 mock-platform 加 `TZ: Asia/Shanghai`
   - 验证：场景 4/7 → **14/14 通过**

2. **DDL 导入全库中文乱码（443 行 / 51 列）**
   - 现象：单据类型列显示 `é”€å”®å‡ºåº“`，货主名 `å‡¯æ·³è‡ª…`
   - 根因：`deploy/init-db.sh` 用 mysql CLI 管道导入，容器 locale=POSIX → 客户端字符集 cp1252，
     把 SQL 文件里的 UTF-8 字节误解码后按 UTF-8 重编码写入
   - 修复：
     - 源头：`init-db.sh` 显式 `--default-character-set=utf8mb4` + 导入后编码自检
     - 存量：新增 `tools/scan_mojibake.py`（pymysql 直连 + 逐字符 cp1252/latin-1 逆映射）
   - 验证：全库扫描 **0 列命中 / 0 行**

3. **测试造数残留污染开发库（33 条孤儿）**
   - 现象：销售物料「所属店铺」列显示 `#369` 而非店铺名
   - 根因：pytest 造数（`SIMSKU001` 等）只断言不回收，店铺删了物料还在
   - 修复：`tests/conftest.py` 加 session 级自动清理（按编码前缀 + 孤儿清扫）
   - 验证：149/149 通过，孤儿数 **0**

## 回归门禁

| 项 | 结果 |
|---|---|
| backend pytest | 149 / 149 通过 |
| 业务场景端到端 | 14 / 14 通过 |
| ruff | All checks passed |
| mypy | 77 文件零错误 |
| 全库乱码扫描 | 0 行 |
| 界面巡检控制台错误 | 0 |
