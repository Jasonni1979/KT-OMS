# M0 Spike 验证报告

> 版本 V1.0 · 2026-10-24 · 编写：小凯 · 对应《研发执行计划-M0至M3》M0 出口标准
> 结论先行：**三大技术风险点全部验证通过，M0 出口达成，可进入 M1**

---

## 1. 验证环境

| 项 | 值 |
|---|---|
| 机器 | macOS (Apple Silicon aarch64) 本地开发机 |
| 基建 | deploy/docker-compose.yml：MySQL 8.0(:3308) / Redis 7(:6380) / RabbitMQ 3.13(:5673) 全 healthy |
| 数据库 | **373 表全量建库成功**（init-db.sh，12 schema，与需求文档库 DDL 完全一致） |
| 后端 | Python 3.12 / FastAPI / SQLAlchemy 2.1 async / aiomysql / redis-py / uv 管理 |
| 前端 | Node 22 / Vue 3.5 / TypeScript 5.6 / Vite 5 / Element Plus 2.8 |

## 2. M0.1 数据库基建 ✅

- docker-compose 三容器一键起（坑：工作区路径含冒号「OMS:WMS」无法做卷挂载 → 改 init-db.sh stdin 导入，可重复执行）
- 11 份 DDL 按 D01→D11 顺序导入，`information_schema` 实测 **373 表 = 预期 373**，零错误
- 种子数据：开发租户（oms_org.org_tenant）

## 3. M0.2/M0.3 工程骨架 ✅

- **backend/**：分层骨架（api/core/domain/services/infra/models）；统一响应信封 `{code,message,data}`；结构化日志（structlog+trace_id）；统一异常体系（BizError 分级错误码）；AuthContext（contextvars）中间件链路贯通；hello 域跨 schema 查询演示；**pytest 冒烟 4/4 通过**；ruff/mypy 配置就位
- **frontend/**：登录页（品牌色 #185FA5）/主布局（侧边菜单+顶栏）/工作台/租户列表页；axios 统一封装（信封解析/trace_id 透传/401 跳转）；路由守卫；**vue-tsc 类型检查通过 + vite build 生产构建通过**；OpenAPI 类型生成脚本就位（`npm run gen:api`）

## 4. 风险点① M0.4 数据权限全局过滤（D10.03 契约）✅

**验证内容**（tests/poc_data_permission.py）：
| 用例 | 结果 |
|---|---|
| 租户隔离 + asyncio 并发不串扰（tenant1/tenant2 并发查询各见其数据） | ✅ PASS |
| 超管 bypass（is_superuser 见全部） | ✅ PASS |
| **fail-closed**（无 AuthContext 拒绝查询，防中间件漏配全量泄露） | ✅ PASS |

**技术结论**：`with_loader_criteria` + `do_orm_execute` 事件 + contextvars 方案成立——业务查询代码**零感知**自动注入 tenant 过滤，与 SRS-D10.03 设计一致。M1 扩展四维（owner/shop/branch）与字段级权限按同机制叠加。

## 5. 风险点② M0.5 Redis Lua 预占（D04.02/D04.03 契约）✅

**验证内容**（tests/bench_freeze.py + app/infra/lua/ 三脚本 + FreezeService）：
| 场景 | 结果 |
|---|---|
| **200 并发抢 100 件**：恰好 100 成功 / 100 拒绝 / freeze=100，**零超卖** | ✅ PASS（1.2s） |
| 同幂等键 50 次并发重复提交：仅预占 1 次，49 次幂等命中 | ✅ PASS |
| release/settle 重复调用幂等 + 数量守恒（store=90/freeze=0 精确） | ✅ PASS |

**技术结论**：三元键（仓×SKU×货主）hash + 三 Lua 脚本（reserve/release/settle）+ 幂等台账键方案成立，`available = store − freeze − defective − safe_locked` 契约在原子层保证。M1 补：预占台账落库（inv_freeze_log）、过期回收任务、Saga 批量补偿。

## 6. 风险点③ M0.6 审单插件链 + 吞吐（D03.02 契约）✅

**验证内容**（app/domain/audit.py + tests/bench_audit.py）：
- 9 插件注册表（五段：RISK 短路/INTERCEPT/CHECK 收集不短路/DECISION/VERDICT），`@register_plugin` 装饰器注册，新增插件零改链代码
- 决策与执行分离：链只产出 plan（selected_branch/split_plan/logistics/auto_passed），不落库
- 结构化 AuditReason（plugin/code/level/message）替代商派位标记 ✓

| 场景 | 结果 |
|---|---|
| 正确性：正常单 auto_pass / 黑名单短路 / 地址异常 HOLD+结构化原因 | ✅ PASS |
| 串行吞吐（纯规则计算）：10000 单/0.01s ≈ **4000 万单/分钟**（目标 ≥500） | ✅ PASS |
| 4 进程横向扩展线性度 | ✅ PASS |

**技术结论**：规则编排本身比目标高 4 个数量级，**吞吐瓶颈只可能在 IO（DB 预占/平台 API）**——而 IO 已分别被风险点②（Redis 原子操作）与异步框架（FastAPI+asyncio）覆盖。M2 接真实依赖后复测端到端吞吐。
**worker 选型建议**：spike 中 asyncio 并发与多进程均验证可用；建议 **arq**（asyncio 原生、轻、与 FastAPI 同栈；Celery 功能全但同步栈重）——M1 落 outbox 投递器时最终定，两者切换成本已隔离在 D01.01 封装层内。

## 7. M0.7 CI ✅

.github/workflows/ci.yml：backend（ruff+mypy+pytest）→ backend-with-db（MySQL/Redis services + 373 表 DDL 全量 + 集成测试）→ frontend（type-check+build）。推送即触发。

## 8. 遗留与已知问题（不阻塞 M1）

| # | 事项 | 处置 |
|---|---|---|
| 1 | 工作区路径含冒号导致 uv/部分工具报错（`path segment contains separator ':'`） | 开发命令统一走 `.venv/bin/python` 直调；**建议正式开发时仓库放无冒号路径**（如 ~/dev/KT-OMS），CI 在云端无此问题 |
| 2 | 本机直连 PyPI/npm/GitHub 慢且抖动 | uv 已配清华镜像验证可用；git push 需禁代理重试（已固化命令模板） |
| 3 | 前端主 chunk >500KB 警告 | M1 做路由级代码分割（Element Plus 按需引入已配 unplugin） |
| 4 | Alembic 迁移基线未生成 | M1 W3 补：以 373 表 DDL 为 baseline revision（`alembic stamp`），后续变更走迁移 |
| 5 | 冒烟测试依赖本机 Docker 容器 | CI 已用 services 容器解决；本地跑测试前先 `docker compose up -d` |

## 9. M0 出口标准核对

| 出口项 | 状态 |
|---|---|
| docker-compose 一键环境 + 373 表 | ✅ |
| backend/frontend 骨架可运行（测试/构建通过） | ✅ |
| 数据权限过滤验证报告 | ✅ §4 |
| Lua 预占防超卖验证报告 | ✅ §5 |
| 审单链吞吐验证报告 | ✅ §6 |
| worker 选型结论 | ✅ arq 建议（M1 终定） |
| CI 门禁 | ✅ |

**→ M0 完成，进入 M1（库存域 + 淘系拉单）。外部依赖提醒：淘系开放平台应用+测试店铺授权需 W4 前就位（Jason 跟进中，已设周二提醒）。**
