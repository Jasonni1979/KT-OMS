# KT-OMS 贡献指南

> 给新加入的团队成员。本文件假设你第一次接触本项目。
> 文档全貌见 [`docs/README.md`](docs/README.md)。

---

## 1. 环境准备

### 依赖

| 组件 | 版本 | 说明 |
|---|---|---|
| Python | 3.12 | 后端（`backend/`） |
| Node.js | 22 | 前端（`frontend/`） |
| MySQL | 8.0 | 12 个 schema / 373 张表 |
| Redis | 7.x | 限流令牌桶、预占、会话、outbox 锁 |

### 拉代码

```bash
git clone git@github.com:<你的账号>/KT-OMS.git
cd KT-OMS
```

> 仓库为 **Private**，需先被邀请为 Collaborator（见 §2）。SSH 推送需先配好 Key：
> `ssh-keygen -t ed25519 -C "you@company.com"` → 把公钥贴到 GitHub → `ssh -T git@github.com` 验证。

### 起数据库

```bash
docker compose -f deploy/docker-compose.dev.yml up -d   # MySQL(3308) + Redis(6380)
```

> ⚠ 本机 **3308/6380** 是宿主机映射端口（容器内是 3306/6379）。
> `backend/app/core/config.py` 默认已按宿主机端口配置。

### 起后端 / 前端

```bash
# 后端（8000）
cd backend && uv sync --all-extras && uv run uvicorn app.main:app --port 8000

# 前端（5173，静态服务 + API 反代；勿用 vite dev server）
cd frontend && npm ci && npm run build
node tools/serve_frontend.mjs 5173
```

### 初始化数据

```bash
cd backend
uv run python -m app.scripts.seed_org      # 组织树 / 货主
uv run python -m app.scripts.seed_auth     # 超管账号（admin / Ktoms@2026）
uv run python -m app.scripts.seed_import
uv run python -m app.scripts.seed_fulfill
uv run python -m app.scripts.seed_wms       # WMS 档案 + 仓↔WMS 绑定
```

模拟器（拉单/回传的真实对端，**必须起**）：

```bash
# 平台模拟器（9000）
cd mocks/platform && uv run uvicorn app.main:app --port 9000
# WMS 模拟器（9001）
cd mocks/wms     && uv run uvicorn app.main:app --port 9001
```

---

## 2. Git 协作约定

### 分支策略

| 分支 | 用途 | 谁可以推 |
|---|---|---|
| `main` | 唯一主干，**受保护** | 不可直推，只能走 PR |
| `feature/<模块>-<简述>` | 功能开发 | 你自己 |
| `fix/<模块>-<简述>` | 缺陷修复 | 你自己 |

```
main ← PR（CI 必须全绿 + 至少 1 人 review） ← feature/xxx
```

### 提交信息（沿用仓库既有风格）

```
<type>(<范围>): <简述>

<正文：为什么改、改了什么、影响什么>
```

| type | 用法 |
|---|---|
| `feat` | 新功能 |
| `fix` | 缺陷修复 |
| `refactor` | 重构（行为不变） |
| `test` | 测试 |
| `docs` | 文档 |
| `ci` | 构建 / CI |

范围用领域缩写：`WMS` / `FUL` / `AUD` / `GW` / `AUTH` / `ORG` / `STOCK` / `PLT`。
例：`feat(WMS): 出库指令支持批量下发` · `fix(auth): 同端互踢后旧 token 应立即失效`

### 提交前必跑

```bash
cd KT-OMS && ./deploy/ci-local-rehearsal.sh
```

**这是本地等价 CI（12 项门禁）**，与 GitHub Actions 的 8 个 job 一一对应。
只有本地全绿再提 PR，能省掉一轮 CI 往返。

---

## 3. 门禁清单（本地 = CI）

| # | 门禁 | 本地命令 |
|---|---|---|
| 1 | ruff | `cd backend && uv run ruff check app tests` |
| 2 | mypy | `cd backend && uv run mypy app --ignore-missing-imports` |
| 3 | pytest | `cd backend && uv run pytest tests/ -q` |
| 4 | 模型 ↔ DDL 一致性 | `cd backend && uv run python ../tools/check_model_ddl.py` |
| 5 | mock-platform pytest | `cd mocks/platform && uv run pytest tests/ -q` |
| 6 | mock-wms pytest | `cd mocks/wms && uv run pytest tests/ -q` |
| 7 | 测试用例清单同步 | `python3 tools/gen_test_doc.py --check` |
| 8 | 业务场景端到端 | `cd backend && uv run python -m app.scripts.scenario_e2e --with-mock` |
| 9 | 履约链路端到端 | `cd backend && uv run python -m app.scripts.fulfill_e2e` |
| 10 | 造单场景矩阵 | `cd backend && uv run python -m app.scripts.scenario_matrix_e2e --with-mock` |
| 11 | W7 通道端到端 | `cd backend && uv run python -m app.scripts.wms_channel_e2e --with-mock` |
| 12 | W7 平台回传端到端 | `cd backend && uv run python -m app.scripts.writeback_e2e --with-mock` |
| 13 | 前端类型 + 构建 | `cd frontend && npm run type-check && npm run build` |

---

## 4. 写代码前必知的项目规矩

这些是本项目**踩过坑总结出来的**，违反会直接导致 CI 失败或线上事故。

### 4.1 新增/修改 ORM 模型 → 必须跑 DDL 一致性校验

```bash
cd backend && uv run python ../tools/check_model_ddl.py
```

**DDL 列名偏差已连续五轮踩坑**（W5 三次 + W6 一次 + W7 一次）。根因是照抄其他域基类，
但每张表的 `version` / `is_deleted` / `update_time` 存在性都不同。

新增表/字段还要同步：`docs/database/sql/`（DDL）+ `docs/database/dictionaries/`（数据字典）。

### 4.2 金额一律按「分」整数比较

```python
# ❌ 错：33435.54 - 33435.53 = 0.010000000002037268 > 0.01 → 误判超差
if abs(sum_paid - expect) > 0.01:

# ✅ 对：用 helper（app/services/allocation.py::_diff_cents）
if _diff_cents(sum_paid, expect) > _TOLERANCE_CENTS:
```

复盘实测：这条曾导致金额完全正确的大额单被硬失败拒单。

### 4.3 DATETIME 无时区 → 时间比较统一用 UTC

`lock_until` / `expire_time` 等是 MySQL `DATETIME`（**不带时区**）。
若写入用本地时区、比较用另一个时区，会出现「锁定中的账户被判为已过期 → 自动放行」。
认证链路用 `app/services/auth.py::_utcnow()`。

### 4.4 E2E 脚本：开头 + 结尾双清，且按 FK 顺序

```python
# ① 开头清（幂等重跑）② 结尾清（最后一次运行的残留不能留在库里）
# ③ 删除顺序：先子表后父表
#    gw_api_fail → gw_writeback_task
#    ord_order_item / ord_receiver → ord_delivery → ord_order
# 顺序反了整段 rollback，**静默不删**（看起来清干净了，其实没有）
```

复盘实测：W6 E2E 残留的 owner_co 根节点让 `test_master` 取错「第一条根节点」，
**层级矩阵校验被绕过**（应 422 得 200）。

### 4.5 测试断言不要取「第一条」

```python
# ❌ 错：库里可能有残留的同类记录
row = (await s.execute(text("SELECT ... LIMIT 1"))).first()

# ✅ 对：按业务字段精确定位
root = next(n for n in nodes if n["node_type"] == "group")
```

### 4.6 断言可能「静默不跑」

数据前置条件不满足时，`if` 分支被跳过 → 门禁显示通过但**实际少覆盖**。
复盘实测：开发库 23 条断言 / CI 库 21 条，门禁却都是绿的。

因此本地复演脚本对每个 E2E 都带**断言条数下限**校验。新增 E2E 时请同步在
`deploy/ci-local-rehearsal.sh` 里加 `assert_min`。

### 4.7 新增测试用例必须登记到追溯表

```python
# tools/test_case_map.py 的 CASES 里加一条（函数名为主键）
"test_xxx": ("D03.07 FR-02a", "场景/输入", "预期结果与验证点"),
```

然后 `python3 tools/gen_test_doc.py` 重新生成《测试用例清单.md》。
漏登记 → CI 的「测试用例清单与代码同步」门禁失败。

---

## 5. 跨域契约（改代码前确认没踩）

| 契约 | 说明 |
|---|---|
| **错误分级有两套** | 通道侧 `ful_cmd_fail.err_class` = RETRYABLE/FATAL/BIZ_REJECT；平台侧 `gw_api_fail.err_level` = RETRYABLE/RATE_LIMITED/AUTH/MANUAL/FATAL。**别混用** |
| **编码映射** | WMS 回传用**物料编码**，OMS 发货单行用 **bm_id** → 通道层 `_standardize_lines()` 做映射，编排层只认 bm_id |
| **通道侧状态投影** | 出库回传按「累计回传量 ≥ 指令量」判定：齐套 = `completed`，不齐套 = `partial`（等尾批） |
| **回传幂等键** | 发货单号 + 批次号 + 类型 → 造演示数据时单号必须唯一，否则被幂等挡掉 |
| **事件必须带 delivery_id** | 否则编排时 `transit(0, …)` 抛错；无主事件应跳过并告警 |
| **状态机** | 发货单状态机以 `SRS-D03.07 §4.1` 为唯一权威，不新增不修改状态与流转 |

---

## 6. 需要帮忙时

| 情况 | 找谁 / 怎么办 |
|---|---|
| 需求有歧义、SRS 没覆盖 | 问 Jason（**不要自己猜业务规则**） |
| DDL 列名对不上 | 跑 `check_model_ddl.py` 看它报什么，别人肉 desc 硬猜 |
| 门禁挂了但本地是绿的 | 对比「本地复演的断言条数」与「CI 的断言条数」—— 可能是环境差异（时区/数据残留） |
| 想加新域 / 改状态机 | 先问 Jason（属范围变更） |
| 环境起不来 | 看 `docs/README.md` 的演示物料里有没有相关录屏 |

---

## 7. 常见问题

**Q：`git push` 提示 permission denied？**
A：仓库是 Private，你还没被邀请为 Collaborator，或 SSH Key 没配到 GitHub。见 §1 / §2。

**Q：CI 报 MySQL 连不上？**
A：CI 用 runner 自带的 MySQL/Redis（不用容器）。本地是容器（端口 3308/6380）。别把两者的端口搞混。

**Q：本地复演某个 E2E 说「模拟器未启动」？**
A：起对应模拟器（9000 平台 / 9001 WMS），或加 `--with-mock` 让脚本自起
（端口被占用时会复用已有实例）。

**Q：提交了但 CI 门禁说「测试用例清单与代码同步」失败？**
A：忘了在 `tools/test_case_map.py` 登记用例，或没跑 `python3 tools/gen_test_doc.py` 重新生成文档。
