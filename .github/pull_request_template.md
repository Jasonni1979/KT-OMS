## 变更摘要

<!-- 一句话说清「改了什么、为什么」。关联 SRS/交付说明编号。 -->

## 关联需求

<!-- 例：SRS-D03.07 FR-02a；W7-履约通道-交付说明.md §2.3 -->

- [ ] 本 PR 有对应的 SRS 条目或交付说明章节

## 变更类型

- [ ] 新功能（feat）
- [ ] 缺陷修复（fix）
- [ ] 重构（refactor，不改行为）
- [ ] 文档 / 测试（docs / test）
- [ ] 构建 / CI（ci）

## 自检清单（提交前本地跑一遍）

```bash
cd KT-OMS && ./deploy/ci-local-rehearsal.sh    # 本地等价 CI（12 项门禁）
```

- [ ] 本地复演全绿（**不要只跑 pytest** —— 端到端与 DDL 一致性门禁必须一起过）
- [ ] 新增/修改的测试用例已登记到 `tools/test_case_map.py`（否则 `gen_test_doc.py --check` 会失败）
- [ ] 若动了 ORM 模型：已确认 `python backend/tools/check_model_ddl.py` 通过
- [ ] 若动了前端：`npm run type-check` 通过

## 数据库变更

- [ ] 无 DDL 变更
- [ ] 有 DDL 变更 → 已同步 `docs/database/sql/` 与 `docs/database/dictionaries/`，且 CI 的「模型 ↔ DDL 列一致性」通过

## 风险与影响面

<!--
· 是否影响已有数据（需数据迁移 / 兼容处理）
· 是否影响跨域契约（事件、错误分级、幂等键、编码映射）
· 是否需要同步更新 SRS / 交付文档
-->

## 测试证据

<!--
贴关键断言输出（本地复演的汇总行，或关键用例的 PASS 行）。
❗ 断言「静默不跑」比失败更危险 —— 复盘实测过 CI 库比开发库少 2 条断言却显示通过，
   所以请贴**条数**，不只是「通过」。
-->

```
合计：__/__ 项通过
```
