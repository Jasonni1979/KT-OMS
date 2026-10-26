# M1 基础主数据

**目录** `backend/app/modules/m1_master/` · **代码行** 1,197 · **service** 4 个

**职责**：组织树 / 货主 / 店铺 / 账号 / 角色 / 数据权限范围 / 字典与规则 / 事件字典

**收编 service**：master, branch_owner, auth, permission

---

## 可写表

| schema | 表数 | 表 |
|---|---|---|
| oms_base | 26 | `bas_alert_record` `bas_consume_idempotent` `bas_dead_letter` `bas_entity_meta` `bas_event_dict` `bas_export_task` `bas_field_meta` `bas_ie_template` `bas_message_trace` `bas_migration_mapping` `bas_notify_log` `bas_notify_route` `bas_notify_template` `bas_pipl_consent` `bas_pipl_ds_request` `bas_pipl_policy` `bas_plugin_registry` `bas_rule` `bas_rule_condition` `bas_rule_dict` `bas_rule_test_log` `bas_rule_version` `bas_schedule_log` `bas_schedule_task` `bas_seq` `bas_task_dependency` |
| oms_org | 28 | `org_account` `org_account_credential` `org_account_role` `org_approval_instance` `org_approval_scene` `org_approval_threshold` `org_data_permission` `org_field_perm` `org_filterable_entity` `org_idp_config` `org_node` `org_node_relation` `org_oa_callback_log` `org_owner` `org_owner_contract` `org_owner_settle_config` `org_perm_point` `org_perm_violation` `org_portal_account` `org_portal_export_log` `org_portal_message` `org_portal_notify_pref` `org_portal_read_log` `org_role` `org_role_perm` `org_session` `org_shop_owner_transfer` `org_tenant` |

完整清单见同目录 `tables.yaml`。

## 对外只读接口（跨模块可自由调用）

| 接口 | 说明 |
|---|---|
| `master.get_node` | 按 id 取组织节点 |
| `master.list_nodes` | 按父节点列子节点 |
| `master.children` | 递归子树 |
| `master.search` | 按关键字搜节点 |
| `master.is_buyout` | 是否买断型货主 |
| `branch_owner.list_by_owner` | 货主 → 关联组织 |
| `branch_owner.list_by_branch` | 组织 → 关联货主 |
| `permission.get_scope` | 账户的数据权限范围（owner/shop/branch/brand） |
| `auth.permissions_of` | 账户权限点集合 |

## 对外写接口（跨模块调用须在本模块登记）

| 接口 | 说明 |
|---|---|
| `master.create_node` | 建组织节点 |
| `master.update_node` | 改组织节点 |
| `master.delete_node` | 删组织节点（软删） |
| `branch_owner.bind` | 绑定货主与组织 |
| `branch_owner.unbind` | 解绑 |

## 允许的跨模块调用

（无 —— 本模块不依赖其它模块）

## 禁止

- 不得直接 import 其它模块的 `service/` 内部实现 —— 只能从对方 `contract.py` 导入
- 不得 import `app.tools.simulation`（仿真造数工具，非业务代码）

## 已知待收口点

- **最底层模块**：不得依赖任何其它模块（门禁 R1 强约束）。
- `bas_event_outbox` 是**多写者白名单表**（M4 / M7 共同写），不计入本模块独占写权。
- 权限与数据范围（`org_data_permission` / `org_field_perm`）由本模块独家维护 —— 改权限规则只应动 M1，不应从其它模块绕过。

## 测试入口

```bash
pytest backend/tests/modules/m1_master/ -q
```
