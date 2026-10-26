# ruff: noqa: E501
"""枚举契约 —— **自动生成，请勿手工编辑**

生成源：`information_schema.columns.column_comment`（**DDL 是权威源**）
生成器：`tools/gen_contracts.py`
重新生成：`python3 tools/gen_contracts.py`
校验同步：`python3 tools/check_contract_ddl.py`

**为什么存在**：枚举值与中文标签过去散落在 39 个 service 里各抄一份，
DDL 变更时必然漂移（W9 已实测：换货状态机缺边、批次阶段表缺边）。
本文件把「唯一一份」放在 DDL 里，代码侧只允许引用本文件。

⚠ 生成列（VIRTUAL/STORED GENERATED）不参与枚举 —— 派生值，非业务写入。
"""
from __future__ import annotations

from typing import Any, Final


# ==================== oms_base ====================

BAS_EVENT_DICT_PARTITIONED: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
BAS_EVENT_DICT_PARTITIONED_VALUES: Final[frozenset[int]] = frozenset(BAS_EVENT_DICT_PARTITIONED)

BAS_EVENT_DICT_BLOCKING_FLAG: Final[dict[int, str]] = {
    0: '旁路重试',
    1: '阻塞后续',
}
BAS_EVENT_DICT_BLOCKING_FLAG_VALUES: Final[frozenset[int]] = frozenset(BAS_EVENT_DICT_BLOCKING_FLAG)

BAS_EVENT_DICT_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '废弃',
}
BAS_EVENT_DICT_STATUS_VALUES: Final[frozenset[int]] = frozenset(BAS_EVENT_DICT_STATUS)

BAS_EVENT_OUTBOX_STATUS: Final[dict[int, str]] = {
    0: '待投递',
    1: '已投递',
    2: '投递失败',
}
BAS_EVENT_OUTBOX_STATUS_VALUES: Final[frozenset[int]] = frozenset(BAS_EVENT_OUTBOX_STATUS)

BAS_CONSUME_IDEMPOTENT_STATUS: Final[dict[int, str]] = {
    1: 'PROCESSING',
    2: 'SUCCESS',
}
BAS_CONSUME_IDEMPOTENT_STATUS_VALUES: Final[frozenset[int]] = frozenset(BAS_CONSUME_IDEMPOTENT_STATUS)

BAS_DEAD_LETTER_HANDLE_STATUS: Final[dict[int, str]] = {
    0: '未处理',
    1: '已重放',
    2: '已作废',
    3: '已修复关闭',
}
BAS_DEAD_LETTER_HANDLE_STATUS_VALUES: Final[frozenset[int]] = frozenset(BAS_DEAD_LETTER_HANDLE_STATUS)

BAS_SCHEDULE_TASK_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
BAS_SCHEDULE_TASK_STATUS_VALUES: Final[frozenset[int]] = frozenset(BAS_SCHEDULE_TASK_STATUS)

BAS_SCHEDULE_LOG_SAMPLED: Final[dict[int, str]] = {
    0: '全量',
    1: '成功抽样',
}
BAS_SCHEDULE_LOG_SAMPLED_VALUES: Final[frozenset[int]] = frozenset(BAS_SCHEDULE_LOG_SAMPLED)

BAS_TASK_DEPENDENCY_PLAN_DATE_ALIGN: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
BAS_TASK_DEPENDENCY_PLAN_DATE_ALIGN_VALUES: Final[frozenset[int]] = frozenset(BAS_TASK_DEPENDENCY_PLAN_DATE_ALIGN)

BAS_TASK_DEPENDENCY_AUTO_TRIGGER: Final[dict[int, str]] = {
    0: '手动补触发',
    1: '自动补触发',
}
BAS_TASK_DEPENDENCY_AUTO_TRIGGER_VALUES: Final[frozenset[int]] = frozenset(BAS_TASK_DEPENDENCY_AUTO_TRIGGER)

BAS_TASK_DEPENDENCY_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '停用',
}
BAS_TASK_DEPENDENCY_STATUS_VALUES: Final[frozenset[int]] = frozenset(BAS_TASK_DEPENDENCY_STATUS)

BAS_RULE_DICT_PRESET_FLAG: Final[dict[int, str]] = {
    0: '租户扩展',
    1: '预置',
}
BAS_RULE_DICT_PRESET_FLAG_VALUES: Final[frozenset[int]] = frozenset(BAS_RULE_DICT_PRESET_FLAG)

BAS_RULE_DICT_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '停用',
}
BAS_RULE_DICT_STATUS_VALUES: Final[frozenset[int]] = frozenset(BAS_RULE_DICT_STATUS)

BAS_RULE_DEFAULTED: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
BAS_RULE_DEFAULTED_VALUES: Final[frozenset[int]] = frozenset(BAS_RULE_DEFAULTED)

BAS_RULE_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
BAS_RULE_STATUS_VALUES: Final[frozenset[int]] = frozenset(BAS_RULE_STATUS)

BAS_RULE_VERSION_STATUS: Final[dict[int, str]] = {
    1: '草稿',
    2: '待发布',
    3: '灰度中',
    4: '已生效',
    5: '已废弃',
    6: '已回滚',
}
BAS_RULE_VERSION_STATUS_VALUES: Final[frozenset[int]] = frozenset(BAS_RULE_VERSION_STATUS)

BAS_RULE_VERSION_AGENT_DRAFT: Final[dict[int, str]] = {
    0: '人工',
    1: 'K-AIDE生成',
}
BAS_RULE_VERSION_AGENT_DRAFT_VALUES: Final[frozenset[int]] = frozenset(BAS_RULE_VERSION_AGENT_DRAFT)

BAS_RULE_TEST_LOG_RUN_MODE: Final[dict[int, str]] = {
    1: '单跑',
    2: '对比',
}
BAS_RULE_TEST_LOG_RUN_MODE_VALUES: Final[frozenset[int]] = frozenset(BAS_RULE_TEST_LOG_RUN_MODE)

BAS_RULE_TEST_LOG_EXEC_MODE: Final[dict[int, str]] = {
    1: '同步',
    2: '异步',
}
BAS_RULE_TEST_LOG_EXEC_MODE_VALUES: Final[frozenset[int]] = frozenset(BAS_RULE_TEST_LOG_EXEC_MODE)

BAS_RULE_TEST_LOG_RUN_STATUS: Final[dict[int, str]] = {
    1: '运行中',
    2: '完成',
    3: '失败',
}
BAS_RULE_TEST_LOG_RUN_STATUS_VALUES: Final[frozenset[int]] = frozenset(BAS_RULE_TEST_LOG_RUN_STATUS)

BAS_PLUGIN_REGISTRY_SHORT_CIRCUIT: Final[dict[int, str]] = {
    0: '不短路全收集',
    1: '短路终止',
}
BAS_PLUGIN_REGISTRY_SHORT_CIRCUIT_VALUES: Final[frozenset[int]] = frozenset(BAS_PLUGIN_REGISTRY_SHORT_CIRCUIT)

BAS_PLUGIN_REGISTRY_ENABLED: Final[dict[int, str]] = {
    0: '停用',
    1: '启用',
}
BAS_PLUGIN_REGISTRY_ENABLED_VALUES: Final[frozenset[int]] = frozenset(BAS_PLUGIN_REGISTRY_ENABLED)

BAS_ENTITY_META_SOFT_DELETE: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
BAS_ENTITY_META_SOFT_DELETE_VALUES: Final[frozenset[int]] = frozenset(BAS_ENTITY_META_SOFT_DELETE)

BAS_ENTITY_META_CRUD_ENABLED: Final[dict[int, str]] = {
    0: '定制页面仅局部复用元数据',
    1: '走通用骨架',
}
BAS_ENTITY_META_CRUD_ENABLED_VALUES: Final[frozenset[int]] = frozenset(BAS_ENTITY_META_CRUD_ENABLED)

BAS_ENTITY_META_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '停用',
}
BAS_ENTITY_META_STATUS_VALUES: Final[frozenset[int]] = frozenset(BAS_ENTITY_META_STATUS)

BAS_FIELD_META_REQUIRED_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
BAS_FIELD_META_REQUIRED_FLAG_VALUES: Final[frozenset[int]] = frozenset(BAS_FIELD_META_REQUIRED_FLAG)

BAS_FIELD_META_SENSITIVE_LEVEL: Final[dict[int, str]] = {
    0: '公开',
    1: '内部',
    2: '敏感',
    3: '高敏',
}
BAS_FIELD_META_SENSITIVE_LEVEL_VALUES: Final[frozenset[int]] = frozenset(BAS_FIELD_META_SENSITIVE_LEVEL)

BAS_FIELD_META_UNIQUE_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
BAS_FIELD_META_UNIQUE_FLAG_VALUES: Final[frozenset[int]] = frozenset(BAS_FIELD_META_UNIQUE_FLAG)

BAS_FIELD_META_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '废弃',
}
BAS_FIELD_META_STATUS_VALUES: Final[frozenset[int]] = frozenset(BAS_FIELD_META_STATUS)

BAS_PIPL_POLICY_LEVEL: Final[dict[int, str]] = {
    0: '公开',
    1: '内部',
    2: '敏感',
    3: '高敏',
}
BAS_PIPL_POLICY_LEVEL_VALUES: Final[frozenset[int]] = frozenset(BAS_PIPL_POLICY_LEVEL)

BAS_PIPL_POLICY_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '历史/停用',
}
BAS_PIPL_POLICY_STATUS_VALUES: Final[frozenset[int]] = frozenset(BAS_PIPL_POLICY_STATUS)

BAS_PIPL_DS_REQUEST_RESTRICTED_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
BAS_PIPL_DS_REQUEST_RESTRICTED_FLAG_VALUES: Final[frozenset[int]] = frozenset(BAS_PIPL_DS_REQUEST_RESTRICTED_FLAG)

BAS_PIPL_DS_REQUEST_HANDLE_STATUS: Final[dict[int, str]] = {
    0: '待受理',
    1: '扫描中',
    2: '处置中',
    3: '已办结',
    4: '已拒绝',
    5: '超期升级',
}
BAS_PIPL_DS_REQUEST_HANDLE_STATUS_VALUES: Final[frozenset[int]] = frozenset(BAS_PIPL_DS_REQUEST_HANDLE_STATUS)

BAS_IE_TEMPLATE_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '停用',
}
BAS_IE_TEMPLATE_STATUS_VALUES: Final[frozenset[int]] = frozenset(BAS_IE_TEMPLATE_STATUS)

BAS_IMPORT_TASK_STATUS: Final[dict[int, str]] = {
    0: '待执行',
    1: '执行中',
    2: '成功',
    3: '部分成功',
    4: '失败',
    5: '已取消',
}
BAS_IMPORT_TASK_STATUS_VALUES: Final[frozenset[int]] = frozenset(BAS_IMPORT_TASK_STATUS)

BAS_EXPORT_TASK_SENSITIVE_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
BAS_EXPORT_TASK_SENSITIVE_FLAG_VALUES: Final[frozenset[int]] = frozenset(BAS_EXPORT_TASK_SENSITIVE_FLAG)

BAS_EXPORT_TASK_PLAIN_APPLY: Final[dict[int, str]] = {
    0: '脱敏直通',
    1: '申请明文',
}
BAS_EXPORT_TASK_PLAIN_APPLY_VALUES: Final[frozenset[int]] = frozenset(BAS_EXPORT_TASK_PLAIN_APPLY)

BAS_EXPORT_TASK_STATUS: Final[dict[int, str]] = {
    0: '待审批',
    1: '待执行',
    2: '执行中',
    3: '成功',
    4: '失败',
    5: '已取消',
    6: '审批拒绝终止',
}
BAS_EXPORT_TASK_STATUS_VALUES: Final[frozenset[int]] = frozenset(BAS_EXPORT_TASK_STATUS)

BAS_NOTIFY_TEMPLATE_COMPLIANCE_CONFIRMED: Final[dict[int, str]] = {
    0: '未确认',
    1: '已确认',
}
BAS_NOTIFY_TEMPLATE_COMPLIANCE_CONFIRMED_VALUES: Final[frozenset[int]] = frozenset(BAS_NOTIFY_TEMPLATE_COMPLIANCE_CONFIRMED)

BAS_NOTIFY_TEMPLATE_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
BAS_NOTIFY_TEMPLATE_STATUS_VALUES: Final[frozenset[int]] = frozenset(BAS_NOTIFY_TEMPLATE_STATUS)

BAS_NOTIFY_ROUTE_DENOISE_FLAG: Final[dict[int, str]] = {
    0: '正常',
    1: '仅计数进日报/阈值触发即时发',
}
BAS_NOTIFY_ROUTE_DENOISE_FLAG_VALUES: Final[frozenset[int]] = frozenset(BAS_NOTIFY_ROUTE_DENOISE_FLAG)

BAS_NOTIFY_ROUTE_DEFAULT_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
BAS_NOTIFY_ROUTE_DEFAULT_FLAG_VALUES: Final[frozenset[int]] = frozenset(BAS_NOTIFY_ROUTE_DEFAULT_FLAG)

BAS_NOTIFY_ROUTE_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
BAS_NOTIFY_ROUTE_STATUS_VALUES: Final[frozenset[int]] = frozenset(BAS_NOTIFY_ROUTE_STATUS)

BAS_NOTIFY_LOG_SEND_STATUS: Final[dict[int, str]] = {
    0: '受理',
    1: '已提交服务商',
    2: '送达',
    3: '失败',
}
BAS_NOTIFY_LOG_SEND_STATUS_VALUES: Final[frozenset[int]] = frozenset(BAS_NOTIFY_LOG_SEND_STATUS)

BAS_ALERT_RECORD_ALERT_LEVEL: Final[dict[int, str]] = {
    0: '电话+企微穿透免打扰',
    1: '企微',
    2: '日报池',
}
BAS_ALERT_RECORD_ALERT_LEVEL_VALUES: Final[frozenset[int]] = frozenset(BAS_ALERT_RECORD_ALERT_LEVEL)

BAS_ALERT_RECORD_RECOVERED: Final[dict[int, str]] = {
    0: '活跃',
    1: '已恢复',
}
BAS_ALERT_RECORD_RECOVERED_VALUES: Final[frozenset[int]] = frozenset(BAS_ALERT_RECORD_RECOVERED)

BAS_MIGRATION_MAPPING_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '废弃',
}
BAS_MIGRATION_MAPPING_STATUS_VALUES: Final[frozenset[int]] = frozenset(BAS_MIGRATION_MAPPING_STATUS)


# ==================== oms_order ====================

ORD_FLAG_CHANGE_LOG_CHANGE_SOURCE: Final[dict[int, str]] = {
    1: '平台同步',
    2: '人工标旗',
    3: '系统规则',
}
ORD_FLAG_CHANGE_LOG_CHANGE_SOURCE_VALUES: Final[frozenset[int]] = frozenset(ORD_FLAG_CHANGE_LOG_CHANGE_SOURCE)

ORD_FLAG_CHANGE_LOG_SYNC_STATUS: Final[dict[int, str]] = {
    0: '无需回传',
    1: '待回传',
    2: '回传成功',
    3: '回传失败',
}
ORD_FLAG_CHANGE_LOG_SYNC_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORD_FLAG_CHANGE_LOG_SYNC_STATUS)


# ==================== oms_stock ====================

INV_IO_BILL_TYPE_DIRECTION: Final[dict[int, str]] = {
    1: '入库',
    2: '出库',
}
INV_IO_BILL_TYPE_DIRECTION_VALUES: Final[frozenset[int]] = frozenset(INV_IO_BILL_TYPE_DIRECTION)

INV_IO_BILL_TYPE_NEED_WMS: Final[dict[int, str]] = {
    0: '本地记账类',
    1: '仓执行类',
}
INV_IO_BILL_TYPE_NEED_WMS_VALUES: Final[frozenset[int]] = frozenset(INV_IO_BILL_TYPE_NEED_WMS)

INV_IO_BILL_TYPE_NEED_APPROVAL: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
INV_IO_BILL_TYPE_NEED_APPROVAL_VALUES: Final[frozenset[int]] = frozenset(INV_IO_BILL_TYPE_NEED_APPROVAL)

INV_IO_BILL_TYPE_SETTLE_REL: Final[dict[int, str]] = {
    0: '无',
    1: '应付',
    2: '应收',
}
INV_IO_BILL_TYPE_SETTLE_REL_VALUES: Final[frozenset[int]] = frozenset(INV_IO_BILL_TYPE_SETTLE_REL)

INV_IO_BILL_TYPE_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
INV_IO_BILL_TYPE_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_IO_BILL_TYPE_STATUS)

INV_MATERIAL_CAT_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
INV_MATERIAL_CAT_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_MATERIAL_CAT_STATUS)

INV_BRAND_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
INV_BRAND_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_BRAND_STATUS)

INV_STOCK_CONFIG_CONFIG_TYPE: Final[dict[int, str]] = {
    1: '负卖开关',
    2: '调整审批阈值',
    3: '预占有效期',
    4: '超收容差',
    5: '调拨在途可售默认',
}
INV_STOCK_CONFIG_CONFIG_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_STOCK_CONFIG_CONFIG_TYPE)

INV_STOCK_CONFIG_SCOPE_TYPE: Final[dict[int, str]] = {
    1: '全局',
    2: '货主',
    3: '店铺',
    4: '仓库',
    5: '仓库x货主',
    6: '调整类型',
}
INV_STOCK_CONFIG_SCOPE_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_STOCK_CONFIG_SCOPE_TYPE)

INV_STOCK_CONFIG_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
INV_STOCK_CONFIG_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_STOCK_CONFIG_STATUS)

INV_COST_CONFIG_TAX_CALIBER: Final[dict[int, str]] = {
    1: '含税',
    2: '不含税',
}
INV_COST_CONFIG_TAX_CALIBER_VALUES: Final[frozenset[int]] = frozenset(INV_COST_CONFIG_TAX_CALIBER)

INV_COST_CONFIG_BRANCH_COST_MODE: Final[dict[int, str]] = {
    1: '分仓均价',
    2: '全局均价',
}
INV_COST_CONFIG_BRANCH_COST_MODE_VALUES: Final[frozenset[int]] = frozenset(INV_COST_CONFIG_BRANCH_COST_MODE)

INV_COST_CONFIG_RETURN_COST_MODE: Final[dict[int, str]] = {
    1: '原单成本快照',
    2: '当前均价',
}
INV_COST_CONFIG_RETURN_COST_MODE_VALUES: Final[frozenset[int]] = frozenset(INV_COST_CONFIG_RETURN_COST_MODE)

INV_COST_CONFIG_FREIGHT_IN_COST: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
INV_COST_CONFIG_FREIGHT_IN_COST_VALUES: Final[frozenset[int]] = frozenset(INV_COST_CONFIG_FREIGHT_IN_COST)

INV_COST_CONFIG_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '历史',
}
INV_COST_CONFIG_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_COST_CONFIG_STATUS)

INV_EXPIRE_RULE_SCOPE_TYPE: Final[dict[int, str]] = {
    1: '全局',
    2: '货主',
    3: '品牌',
    4: '分类',
    5: '物料',
}
INV_EXPIRE_RULE_SCOPE_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_EXPIRE_RULE_SCOPE_TYPE)

INV_EXPIRE_RULE_THRESHOLD_TYPE: Final[dict[int, str]] = {
    1: '到期前天数',
    2: '剩余效期比例%',
}
INV_EXPIRE_RULE_THRESHOLD_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_EXPIRE_RULE_THRESHOLD_TYPE)

INV_EXPIRE_RULE_AUTO_FREEZE: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
INV_EXPIRE_RULE_AUTO_FREEZE_VALUES: Final[frozenset[int]] = frozenset(INV_EXPIRE_RULE_AUTO_FREEZE)

INV_EXPIRE_RULE_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
INV_EXPIRE_RULE_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_EXPIRE_RULE_STATUS)

INV_ALERT_RULE_RULE_TYPE: Final[dict[int, str]] = {
    1: '低库存',
    2: '断货风险',
    3: '滞销',
    4: '仓间不均衡',
    5: '超储',
}
INV_ALERT_RULE_RULE_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_ALERT_RULE_RULE_TYPE)

INV_ALERT_RULE_SCOPE_TYPE: Final[dict[int, str]] = {
    1: '全局',
    2: '货主',
    3: '品牌',
    4: '分类',
    5: '物料',
}
INV_ALERT_RULE_SCOPE_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_ALERT_RULE_SCOPE_TYPE)

INV_ALERT_RULE_SALES_CALIBER: Final[dict[int, str]] = {
    1: '近7天',
    2: '近14天',
    3: '近30天',
}
INV_ALERT_RULE_SALES_CALIBER_VALUES: Final[frozenset[int]] = frozenset(INV_ALERT_RULE_SALES_CALIBER)

INV_ALERT_RULE_PROMO_EXCLUDE: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
INV_ALERT_RULE_PROMO_EXCLUDE_VALUES: Final[frozenset[int]] = frozenset(INV_ALERT_RULE_PROMO_EXCLUDE)

INV_ALERT_RULE_SCAN_FREQ: Final[dict[int, str]] = {
    1: '日批',
    2: '实时',
    3: '日批+实时',
}
INV_ALERT_RULE_SCAN_FREQ_VALUES: Final[frozenset[int]] = frozenset(INV_ALERT_RULE_SCAN_FREQ)

INV_ALERT_RULE_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
INV_ALERT_RULE_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_ALERT_RULE_STATUS)

INV_STOCKTAKE_PLAN_CYCLE_TYPE: Final[dict[int, str]] = {
    1: '月盘',
    2: '周盘',
    3: '日盘',
    4: '动碰抽盘',
}
INV_STOCKTAKE_PLAN_CYCLE_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_STOCKTAKE_PLAN_CYCLE_TYPE)

INV_STOCKTAKE_PLAN_SCOPE_TYPE: Final[dict[int, str]] = {
    1: '仓x货主全量',
    2: '分类',
    3: '物料清单',
    4: '动碰规则',
}
INV_STOCKTAKE_PLAN_SCOPE_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_STOCKTAKE_PLAN_SCOPE_TYPE)

INV_STOCKTAKE_PLAN_MODE: Final[dict[int, str]] = {
    1: '明盘',
    2: '盲盘',
}
INV_STOCKTAKE_PLAN_MODE_VALUES: Final[frozenset[int]] = frozenset(INV_STOCKTAKE_PLAN_MODE)

INV_STOCKTAKE_PLAN_EXECUTOR: Final[dict[int, str]] = {
    1: 'WMS',
    2: '人工',
}
INV_STOCKTAKE_PLAN_EXECUTOR_VALUES: Final[frozenset[int]] = frozenset(INV_STOCKTAKE_PLAN_EXECUTOR)

INV_STOCKTAKE_PLAN_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
INV_STOCKTAKE_PLAN_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_STOCKTAKE_PLAN_STATUS)

INV_SYNC_STRATEGY_SCOPE_TYPE: Final[dict[int, str]] = {
    1: '全店',
    2: '分类',
    3: '品牌',
    4: '指定物料',
}
INV_SYNC_STRATEGY_SCOPE_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_SYNC_STRATEGY_SCOPE_TYPE)

INV_SYNC_STRATEGY_OVERSELL_MODE: Final[dict[int, str]] = {
    1: '硬分配',
    2: '软超卖',
}
INV_SYNC_STRATEGY_OVERSELL_MODE_VALUES: Final[frozenset[int]] = frozenset(INV_SYNC_STRATEGY_OVERSELL_MODE)

INV_SYNC_STRATEGY_WATER_LEVEL_TYPE: Final[dict[int, str]] = {
    1: '绝对值',
    2: '销量天数',
}
INV_SYNC_STRATEGY_WATER_LEVEL_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_SYNC_STRATEGY_WATER_LEVEL_TYPE)

INV_SYNC_STRATEGY_WRITEBACK_MODE: Final[dict[int, str]] = {
    1: '实时',
    2: '准实时批量',
    3: '定时',
}
INV_SYNC_STRATEGY_WRITEBACK_MODE_VALUES: Final[frozenset[int]] = frozenset(INV_SYNC_STRATEGY_WRITEBACK_MODE)

INV_SYNC_STRATEGY_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
INV_SYNC_STRATEGY_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_SYNC_STRATEGY_STATUS)

INV_MATERIAL_TYPE: Final[dict[int, str]] = {
    1: '成品',
    2: '半成品',
    3: '普通',
    4: '礼盒',
    5: '虚拟',
}
INV_MATERIAL_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_MATERIAL_TYPE)

INV_MATERIAL_SERIAL_NUMBER: Final[dict[int, str]] = {
    0: '关',
    1: '开',
}
INV_MATERIAL_SERIAL_NUMBER_VALUES: Final[frozenset[int]] = frozenset(INV_MATERIAL_SERIAL_NUMBER)

INV_MATERIAL_STORAGE_LIFE_FLAG: Final[dict[int, str]] = {
    0: '关',
    1: '开',
}
INV_MATERIAL_STORAGE_LIFE_FLAG_VALUES: Final[frozenset[int]] = frozenset(INV_MATERIAL_STORAGE_LIFE_FLAG)

INV_MATERIAL_IS_CTRL_STORE: Final[dict[int, str]] = {
    0: '不记账',
    1: '记账',
}
INV_MATERIAL_IS_CTRL_STORE_VALUES: Final[frozenset[int]] = frozenset(INV_MATERIAL_IS_CTRL_STORE)

INV_MATERIAL_OMNICHANNEL: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
INV_MATERIAL_OMNICHANNEL_VALUES: Final[frozenset[int]] = frozenset(INV_MATERIAL_OMNICHANNEL)

INV_MATERIAL_IS_O2O_SALES: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
INV_MATERIAL_IS_O2O_SALES_VALUES: Final[frozenset[int]] = frozenset(INV_MATERIAL_IS_O2O_SALES)

INV_MATERIAL_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
INV_MATERIAL_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_MATERIAL_STATUS)

INV_SALES_MATERIAL_SALES_MATERIAL_TYPE: Final[dict[int, str]] = {
    1: '普通',
    2: '组合',
    3: '赠品',
    4: '多选一',
    5: '礼盒',
    6: '福袋',
}
INV_SALES_MATERIAL_SALES_MATERIAL_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_SALES_MATERIAL_SALES_MATERIAL_TYPE)

INV_SALES_MATERIAL_BIND_STATUS: Final[dict[int, str]] = {
    0: '未绑定',
    1: '已绑定',
}
INV_SALES_MATERIAL_BIND_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_SALES_MATERIAL_BIND_STATUS)

INV_SALES_MATERIAL_VISIBLED: Final[dict[int, str]] = {
    0: '下架',
    1: '上架',
}
INV_SALES_MATERIAL_VISIBLED_VALUES: Final[frozenset[int]] = frozenset(INV_SALES_MATERIAL_VISIBLED)

INV_SALES_MATERIAL_STATUS: Final[dict[int, str]] = {
    1: '正常',
    2: '已停用',
}
INV_SALES_MATERIAL_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_SALES_MATERIAL_STATUS)

INV_BOM_VERSION_STATUS: Final[dict[int, str]] = {
    1: '草稿',
    2: '生效',
    3: '历史',
}
INV_BOM_VERSION_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_BOM_VERSION_STATUS)

INV_BARCODE_BARCODE_TYPE: Final[dict[int, str]] = {
    1: '厂商码',
    2: '店铺码',
    3: 'WMS码',
    9: '其他',
}
INV_BARCODE_BARCODE_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_BARCODE_BARCODE_TYPE)

INV_BARCODE_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
INV_BARCODE_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_BARCODE_STATUS)

INV_FUKUBUKURO_PLAN_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
INV_FUKUBUKURO_PLAN_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_FUKUBUKURO_PLAN_STATUS)

INV_PICKONE_CANDIDATE_SELECT_TYPE: Final[dict[int, str]] = {
    1: '库存深度优先',
    2: '成本优先',
    3: '指定顺序',
}
INV_PICKONE_CANDIDATE_SELECT_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_PICKONE_CANDIDATE_SELECT_TYPE)

INV_STOCK_LEDGER_IS_LOCKED: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
INV_STOCK_LEDGER_IS_LOCKED_VALUES: Final[frozenset[int]] = frozenset(INV_STOCK_LEDGER_IS_LOCKED)

INV_STOCK_LEDGER_STATUS: Final[dict[int, str]] = {
    1: '活跃',
    2: '停用',
}
INV_STOCK_LEDGER_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_STOCK_LEDGER_STATUS)

INV_STOCK_ADJUST_ADJUST_TYPE: Final[dict[int, str]] = {
    1: '盘盈',
    2: '盘亏',
    3: '报损',
    4: '退货修正',
    5: '系统纠错',
    9: '其他',
}
INV_STOCK_ADJUST_ADJUST_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_STOCK_ADJUST_ADJUST_TYPE)

INV_STOCK_ADJUST_APPROVAL_STATUS: Final[dict[int, str]] = {
    0: '免审',
    1: '待审',
    2: '通过',
    3: '驳回',
}
INV_STOCK_ADJUST_APPROVAL_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_STOCK_ADJUST_APPROVAL_STATUS)

INV_STOCK_ADJUST_STATUS: Final[dict[int, str]] = {
    1: '草稿',
    2: '生效',
    3: '关闭',
}
INV_STOCK_ADJUST_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_STOCK_ADJUST_STATUS)

INV_STOCK_RECON_DIFF_RECON_TYPE: Final[dict[int, str]] = {
    1: 'Redis vs DB',
    2: 'WMS vs OMS',
    3: '批次账 vs 数量账',
}
INV_STOCK_RECON_DIFF_RECON_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_STOCK_RECON_DIFF_RECON_TYPE)

INV_STOCK_RECON_DIFF_STATUS: Final[dict[int, str]] = {
    1: '待处理',
    2: '已自动修复',
    3: '已人工处理',
    4: '误报忽略',
}
INV_STOCK_RECON_DIFF_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_STOCK_RECON_DIFF_STATUS)

INV_FREEZE_LOG_OBJ_TYPE: Final[dict[int, str]] = {
    1: '订单',
    2: '售后换货',
    3: '调拨',
    4: '人工',
    5: '借调',
}
INV_FREEZE_LOG_OBJ_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_FREEZE_LOG_OBJ_TYPE)

INV_FREEZE_LOG_STATUS: Final[dict[int, str]] = {
    1: '已生效',
    2: '部分核销',
    3: '已核销',
    4: '已释放',
}
INV_FREEZE_LOG_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_FREEZE_LOG_STATUS)

INV_FREEZE_LOG_IS_COMPENSATED: Final[dict[int, str]] = {
    0: '正常',
    1: '已补偿回滚',
}
INV_FREEZE_LOG_IS_COMPENSATED_VALUES: Final[frozenset[int]] = frozenset(INV_FREEZE_LOG_IS_COMPENSATED)

INV_MANUAL_FREEZE_APPROVAL_STATUS: Final[dict[int, str]] = {
    0: '免审',
    1: '待审',
    2: '通过',
    3: '驳回',
}
INV_MANUAL_FREEZE_APPROVAL_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_MANUAL_FREEZE_APPROVAL_STATUS)

INV_MANUAL_FREEZE_STATUS: Final[dict[int, str]] = {
    1: '草稿',
    2: '生效',
    3: '部分消耗',
    4: '已释放',
    5: '已过期',
}
INV_MANUAL_FREEZE_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_MANUAL_FREEZE_STATUS)

INV_IO_BILL_DIRECTION: Final[dict[int, str]] = {
    1: '入库',
    2: '出库',
}
INV_IO_BILL_DIRECTION_VALUES: Final[frozenset[int]] = frozenset(INV_IO_BILL_DIRECTION)

INV_IO_BILL_STATUS: Final[dict[int, str]] = {
    1: '草稿',
    2: '已下发WMS',
    3: '部分回传',
    4: '全部回传',
    5: '已确认',
    6: '已红冲',
    7: '已关闭',
}
INV_IO_BILL_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_IO_BILL_STATUS)

INV_IO_BILL_SETTLE_STATUS: Final[dict[int, str]] = {
    0: '无需结算',
    1: '未结算',
    2: '部分结算',
    3: '已结算',
    4: '结算锁定',
}
INV_IO_BILL_SETTLE_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_IO_BILL_SETTLE_STATUS)

INV_IO_BILL_APPROVAL_STATUS: Final[dict[int, str]] = {
    0: '免审',
    1: '待审',
    2: '通过',
    3: '驳回',
}
INV_IO_BILL_APPROVAL_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_IO_BILL_APPROVAL_STATUS)

INV_IO_CALLBACK_LOG_CALLBACK_TYPE: Final[dict[int, str]] = {
    1: '入库回传',
    2: '出库回传',
    3: '质检结果',
}
INV_IO_CALLBACK_LOG_CALLBACK_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_IO_CALLBACK_LOG_CALLBACK_TYPE)

INV_IO_CALLBACK_LOG_STATUS: Final[dict[int, str]] = {
    1: '成功',
    2: '失败待重试',
    3: '丢弃',
}
INV_IO_CALLBACK_LOG_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_IO_CALLBACK_LOG_STATUS)

INV_TRANSFER_ORDER_REASON: Final[dict[int, str]] = {
    1: '平衡',
    2: '归集',
    3: '退仓前置',
    4: '借调移位',
    9: '其他',
}
INV_TRANSFER_ORDER_REASON_VALUES: Final[frozenset[int]] = frozenset(INV_TRANSFER_ORDER_REASON)

INV_TRANSFER_ORDER_STATUS: Final[dict[int, str]] = {
    1: '草稿',
    2: '已确认',
    3: '出库中',
    4: '在途',
    5: '入库中',
    6: '已完结',
    7: '差异完结',
    8: '已关闭',
}
INV_TRANSFER_ORDER_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_TRANSFER_ORDER_STATUS)

INV_TRANSFER_ORDER_ARRIVAL_SELLABLE: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
INV_TRANSFER_ORDER_ARRIVAL_SELLABLE_VALUES: Final[frozenset[int]] = frozenset(INV_TRANSFER_ORDER_ARRIVAL_SELLABLE)

INV_TRANSFER_ORDER_DIFF_TYPE: Final[dict[int, str]] = {
    0: '无',
    1: '运输损耗',
    2: '短少',
    3: '溢余',
    9: '其他',
}
INV_TRANSFER_ORDER_DIFF_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_TRANSFER_ORDER_DIFF_TYPE)

INV_TRANSFER_ORDER_APPROVAL_STATUS: Final[dict[int, str]] = {
    0: '免审',
    1: '待审',
    2: '通过',
    3: '驳回',
}
INV_TRANSFER_ORDER_APPROVAL_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_TRANSFER_ORDER_APPROVAL_STATUS)

INV_LEND_RULE_SCOPE_TYPE: Final[dict[int, str]] = {
    1: '指定清单',
    2: '分类',
    3: '品牌',
}
INV_LEND_RULE_SCOPE_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_LEND_RULE_SCOPE_TYPE)

INV_LEND_RULE_SETTLE_PRICE_TYPE: Final[dict[int, str]] = {
    1: '内部购销价',
    2: '成本价',
    3: '免费额度',
}
INV_LEND_RULE_SETTLE_PRICE_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_LEND_RULE_SETTLE_PRICE_TYPE)

INV_LEND_RULE_MOVE_TYPE: Final[dict[int, str]] = {
    1: '货不动',
    2: '货动',
}
INV_LEND_RULE_MOVE_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_LEND_RULE_MOVE_TYPE)

INV_LEND_RULE_STATUS: Final[dict[int, str]] = {
    1: '待审批',
    2: '生效',
    3: '暂停',
    4: '已到期',
    5: '已关闭',
}
INV_LEND_RULE_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_LEND_RULE_STATUS)

INV_LEND_RULE_APPROVAL_STATUS: Final[dict[int, str]] = {
    1: '待审',
    2: '通过',
    3: '驳回',
}
INV_LEND_RULE_APPROVAL_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_LEND_RULE_APPROVAL_STATUS)

INV_LEND_LEDGER_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '耗尽',
    3: '到期',
    4: '关闭',
}
INV_LEND_LEDGER_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_LEND_LEDGER_STATUS)

INV_LEND_LEDGER_SETTLE_STATUS: Final[dict[int, str]] = {
    0: '未结算',
    1: '已结算',
}
INV_LEND_LEDGER_SETTLE_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_LEND_LEDGER_SETTLE_STATUS)

INV_OWNERSHIP_TRANSFER_STATUS: Final[dict[int, str]] = {
    1: '草稿',
    2: '待审批',
    3: '待双方确认',
    4: '执行中',
    5: '已完成',
    6: '已驳回',
    7: '已关闭',
}
INV_OWNERSHIP_TRANSFER_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_OWNERSHIP_TRANSFER_STATUS)

INV_OWNERSHIP_TRANSFER_APPROVAL_STATUS: Final[dict[int, str]] = {
    1: '待审',
    2: '通过',
    3: '驳回',
}
INV_OWNERSHIP_TRANSFER_APPROVAL_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_OWNERSHIP_TRANSFER_APPROVAL_STATUS)

INV_STOCKTAKE_TASK_MODE: Final[dict[int, str]] = {
    1: '明盘',
    2: '盲盘',
}
INV_STOCKTAKE_TASK_MODE_VALUES: Final[frozenset[int]] = frozenset(INV_STOCKTAKE_TASK_MODE)

INV_STOCKTAKE_TASK_EXECUTOR: Final[dict[int, str]] = {
    1: 'WMS',
    2: '人工',
}
INV_STOCKTAKE_TASK_EXECUTOR_VALUES: Final[frozenset[int]] = frozenset(INV_STOCKTAKE_TASK_EXECUTOR)

INV_STOCKTAKE_TASK_TRIGGER_TYPE: Final[dict[int, str]] = {
    1: '手动',
    2: '计划调度',
    3: '对账差异',
}
INV_STOCKTAKE_TASK_TRIGGER_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_STOCKTAKE_TASK_TRIGGER_TYPE)

INV_STOCKTAKE_TASK_STATUS: Final[dict[int, str]] = {
    1: '待下发',
    2: '执行中',
    3: '已回传',
    4: '差异核查',
    5: '审批中',
    6: '已完结',
    7: '已关闭',
}
INV_STOCKTAKE_TASK_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_STOCKTAKE_TASK_STATUS)

INV_STOCKTAKE_TASK_APPROVAL_STATUS: Final[dict[int, str]] = {
    0: '免审',
    1: '待审',
    2: '通过',
    3: '驳回',
}
INV_STOCKTAKE_TASK_APPROVAL_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_STOCKTAKE_TASK_APPROVAL_STATUS)

INV_STOCKTAKE_ITEM_RECOUNT_FLAG: Final[dict[int, str]] = {
    0: '无',
    1: '已复盘',
}
INV_STOCKTAKE_ITEM_RECOUNT_FLAG_VALUES: Final[frozenset[int]] = frozenset(INV_STOCKTAKE_ITEM_RECOUNT_FLAG)

INV_STOCKTAKE_ITEM_DIFF_REASON: Final[dict[int, str]] = {
    0: '无差异',
    1: '货损',
    2: '货差',
    3: '单据未闭环',
    4: '回传丢失',
    5: '串货',
    9: '其他',
}
INV_STOCKTAKE_ITEM_DIFF_REASON_VALUES: Final[frozenset[int]] = frozenset(INV_STOCKTAKE_ITEM_DIFF_REASON)

INV_STOCKTAKE_ITEM_SUSPECT_MIXUP: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
INV_STOCKTAKE_ITEM_SUSPECT_MIXUP_VALUES: Final[frozenset[int]] = frozenset(INV_STOCKTAKE_ITEM_SUSPECT_MIXUP)

INV_COST_CHANGE_LOG_CHANGE_TYPE: Final[dict[int, str]] = {
    1: '入库计价',
    2: '出库结转',
    3: '退货冲回',
    4: '暂估回冲',
    5: '调整',
    6: '期初',
    7: '代管入',
    8: '代管出',
}
INV_COST_CHANGE_LOG_CHANGE_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_COST_CHANGE_LOG_CHANGE_TYPE)

INV_COST_CHANGE_LOG_ESTIMATE_FLAG: Final[dict[int, str]] = {
    0: '正式价',
    1: '暂估价',
}
INV_COST_CHANGE_LOG_ESTIMATE_FLAG_VALUES: Final[frozenset[int]] = frozenset(INV_COST_CHANGE_LOG_ESTIMATE_FLAG)

INV_COST_CHANGE_LOG_COST_ESTIMATED: Final[dict[int, str]] = {
    0: '原单快照',
    1: '均价替代+人工确认',
}
INV_COST_CHANGE_LOG_COST_ESTIMATED_VALUES: Final[frozenset[int]] = frozenset(INV_COST_CHANGE_LOG_COST_ESTIMATED)

INV_ESTIMATE_BATCH_STATUS: Final[dict[int, str]] = {
    1: '暂估中',
    2: '部分转正',
    3: '已转正',
}
INV_ESTIMATE_BATCH_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_ESTIMATE_BATCH_STATUS)

INV_SELLABLE_SNAPSHOT_SYNC_STATUS: Final[dict[int, str]] = {
    0: '未同步',
    1: '已同步',
    2: '同步失败',
    3: '熔断暂停',
}
INV_SELLABLE_SNAPSHOT_SYNC_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_SELLABLE_SNAPSHOT_SYNC_STATUS)

INV_SYNC_LOG_TRIGGER_TYPE: Final[dict[int, str]] = {
    1: '事件驱动',
    2: '水位触发',
    3: '定时全量',
    4: '手动',
    5: '对账强制',
}
INV_SYNC_LOG_TRIGGER_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_SYNC_LOG_TRIGGER_TYPE)

INV_SYNC_LOG_SYNC_STATUS: Final[dict[int, str]] = {
    1: '成功',
    2: '失败',
}
INV_SYNC_LOG_SYNC_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_SYNC_LOG_SYNC_STATUS)

INV_BATCH_STATUS: Final[dict[int, str]] = {
    1: '正常',
    2: '冻结',
    3: '清空',
}
INV_BATCH_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_BATCH_STATUS)

INV_BATCH_STOCK_NEAR_EXPIRE_LEVEL: Final[dict[int, str]] = {
    0: '无',
    1: '黄',
    2: '橙',
    3: '红',
}
INV_BATCH_STOCK_NEAR_EXPIRE_LEVEL_VALUES: Final[frozenset[int]] = frozenset(INV_BATCH_STOCK_NEAR_EXPIRE_LEVEL)

INV_BATCH_ASSIGN_STRATEGY: Final[dict[int, str]] = {
    1: 'FEFO',
    2: 'FIFO',
    3: '指定批次',
}
INV_BATCH_ASSIGN_STRATEGY_VALUES: Final[frozenset[int]] = frozenset(INV_BATCH_ASSIGN_STRATEGY)

INV_BATCH_ASSIGN_IS_MATCH: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
INV_BATCH_ASSIGN_IS_MATCH_VALUES: Final[frozenset[int]] = frozenset(INV_BATCH_ASSIGN_IS_MATCH)

INV_SERIAL_NO_STATUS: Final[dict[int, str]] = {
    1: '在库',
    2: '已出库',
    3: '售后中',
    4: '已核销',
    5: '换出',
    6: '终止',
}
INV_SERIAL_NO_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_SERIAL_NO_STATUS)

INV_EXPIRE_DISPOSAL_DISPOSAL_TYPE: Final[dict[int, str]] = {
    1: '促销出清',
    2: '退仓',
    3: '报废',
}
INV_EXPIRE_DISPOSAL_DISPOSAL_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_EXPIRE_DISPOSAL_DISPOSAL_TYPE)

INV_EXPIRE_DISPOSAL_APPROVAL_STATUS: Final[dict[int, str]] = {
    0: '免审',
    1: '待审',
    2: '通过',
    3: '驳回',
}
INV_EXPIRE_DISPOSAL_APPROVAL_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_EXPIRE_DISPOSAL_APPROVAL_STATUS)

INV_EXPIRE_DISPOSAL_STATUS: Final[dict[int, str]] = {
    1: '草稿',
    2: '执行中',
    3: '已完成',
    4: '已关闭',
}
INV_EXPIRE_DISPOSAL_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_EXPIRE_DISPOSAL_STATUS)

INV_REPLENISH_SUGGESTION_SUGGEST_TYPE: Final[dict[int, str]] = {
    1: '采购',
    2: '调拨',
    3: '借调',
    4: '处置',
}
INV_REPLENISH_SUGGESTION_SUGGEST_TYPE_VALUES: Final[frozenset[int]] = frozenset(INV_REPLENISH_SUGGESTION_SUGGEST_TYPE)

INV_REPLENISH_SUGGESTION_ALERT_LEVEL: Final[dict[int, str]] = {
    1: '黄',
    2: '橙',
    3: '红',
}
INV_REPLENISH_SUGGESTION_ALERT_LEVEL_VALUES: Final[frozenset[int]] = frozenset(INV_REPLENISH_SUGGESTION_ALERT_LEVEL)

INV_REPLENISH_SUGGESTION_STATUS: Final[dict[int, str]] = {
    1: '待处理',
    2: '已采纳',
    3: '已忽略',
    4: '已转单',
    5: '已解除',
    6: '已过期',
}
INV_REPLENISH_SUGGESTION_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_REPLENISH_SUGGESTION_STATUS)

INV_REPLENISH_SUGGESTION_IGNORE_REASON: Final[dict[int, str]] = {
    0: '无',
    1: '品牌方不补',
    2: '清仓中',
    3: '数据存疑',
    9: '其他',
}
INV_REPLENISH_SUGGESTION_IGNORE_REASON_VALUES: Final[frozenset[int]] = frozenset(INV_REPLENISH_SUGGESTION_IGNORE_REASON)

INV_SALES_FORECAST_DEGRADE_FLAG: Final[dict[int, str]] = {
    0: 'ML预测',
    1: '算法服务不可用自动降级统计式',
}
INV_SALES_FORECAST_DEGRADE_FLAG_VALUES: Final[frozenset[int]] = frozenset(INV_SALES_FORECAST_DEGRADE_FLAG)

INV_PRICE_ARCHIVE_BELOW_FLOOR_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
INV_PRICE_ARCHIVE_BELOW_FLOOR_FLAG_VALUES: Final[frozenset[int]] = frozenset(INV_PRICE_ARCHIVE_BELOW_FLOOR_FLAG)

INV_PRICE_ARCHIVE_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
INV_PRICE_ARCHIVE_STATUS_VALUES: Final[frozenset[int]] = frozenset(INV_PRICE_ARCHIVE_STATUS)

INV_PRICE_VERSION_SYNC_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
INV_PRICE_VERSION_SYNC_FLAG_VALUES: Final[frozenset[int]] = frozenset(INV_PRICE_VERSION_SYNC_FLAG)

INV_PRICE_ADJUST_PLAN_EXPIRE_WRITEBACK: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
INV_PRICE_ADJUST_PLAN_EXPIRE_WRITEBACK_VALUES: Final[frozenset[int]] = frozenset(INV_PRICE_ADJUST_PLAN_EXPIRE_WRITEBACK)

INV_PRICE_ADJUST_ITEM_BELOW_FLOOR: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
INV_PRICE_ADJUST_ITEM_BELOW_FLOOR_VALUES: Final[frozenset[int]] = frozenset(INV_PRICE_ADJUST_ITEM_BELOW_FLOOR)

INV_PRICE_SYNC_TASK_ALERT_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '已触发',
}
INV_PRICE_SYNC_TASK_ALERT_FLAG_VALUES: Final[frozenset[int]] = frozenset(INV_PRICE_SYNC_TASK_ALERT_FLAG)


# ==================== oms_aftersale ====================

AFT_REASON_DICT_DUTY_PARTY: Final[dict[int, str]] = {
    0: '无',
    1: '买家责任',
    2: '物流责任',
    3: '卖家/质量责任',
    4: '平台责任',
}
AFT_REASON_DICT_DUTY_PARTY_VALUES: Final[frozenset[int]] = frozenset(AFT_REASON_DICT_DUTY_PARTY)

AFT_REASON_DICT_AUDIT_WHITE: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
AFT_REASON_DICT_AUDIT_WHITE_VALUES: Final[frozenset[int]] = frozenset(AFT_REASON_DICT_AUDIT_WHITE)

AFT_REASON_DICT_REJECT_SUGGEST: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
AFT_REASON_DICT_REJECT_SUGGEST_VALUES: Final[frozenset[int]] = frozenset(AFT_REASON_DICT_REJECT_SUGGEST)

AFT_REASON_DICT_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
AFT_REASON_DICT_STATUS_VALUES: Final[frozenset[int]] = frozenset(AFT_REASON_DICT_STATUS)

AFT_RETURN_ADDRESS_ADDRESS_TYPE: Final[dict[int, str]] = {
    1: '凯淳仓',
    2: '品牌方指定仓',
    3: '凯淳代收仓',
}
AFT_RETURN_ADDRESS_ADDRESS_TYPE_VALUES: Final[frozenset[int]] = frozenset(AFT_RETURN_ADDRESS_ADDRESS_TYPE)

AFT_RETURN_ADDRESS_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
AFT_RETURN_ADDRESS_STATUS_VALUES: Final[frozenset[int]] = frozenset(AFT_RETURN_ADDRESS_STATUS)

AFT_AUTO_AUDIT_RULE_ACTION_TYPE: Final[dict[int, str]] = {
    1: '自动同意退款',
    2: '自动同意退货',
    3: '自动拒绝建议',
    4: '转人工',
}
AFT_AUTO_AUDIT_RULE_ACTION_TYPE_VALUES: Final[frozenset[int]] = frozenset(AFT_AUTO_AUDIT_RULE_ACTION_TYPE)

AFT_AUTO_AUDIT_RULE_RESCUE_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
AFT_AUTO_AUDIT_RULE_RESCUE_FLAG_VALUES: Final[frozenset[int]] = frozenset(AFT_AUTO_AUDIT_RULE_RESCUE_FLAG)

AFT_AUTO_AUDIT_RULE_DEFAULTED: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
AFT_AUTO_AUDIT_RULE_DEFAULTED_VALUES: Final[frozenset[int]] = frozenset(AFT_AUTO_AUDIT_RULE_DEFAULTED)

AFT_AUTO_AUDIT_RULE_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
AFT_AUTO_AUDIT_RULE_STATUS_VALUES: Final[frozenset[int]] = frozenset(AFT_AUTO_AUDIT_RULE_STATUS)

AFT_RETURN_APPLY_AFTERSALE_TYPE: Final[dict[int, str]] = {
    1: '仅退款',
    2: '退货退款',
    3: '换货',
    4: '补发',
}
AFT_RETURN_APPLY_AFTERSALE_TYPE_VALUES: Final[frozenset[int]] = frozenset(AFT_RETURN_APPLY_AFTERSALE_TYPE)

AFT_RETURN_APPLY_RESHIP_ONLY: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
AFT_RETURN_APPLY_RESHIP_ONLY_VALUES: Final[frozenset[int]] = frozenset(AFT_RETURN_APPLY_RESHIP_ONLY)

AFT_RETURN_APPLY_STATUS: Final[dict[int, str]] = {
    0: '待关联',
    1: '待审核',
    2: '待退货',
    3: '待收货',
    4: '待退款',
    5: '退款中',
    6: '换货执行中',
    7: '完成',
    8: '拒绝',
    9: '关闭',
}
AFT_RETURN_APPLY_STATUS_VALUES: Final[frozenset[int]] = frozenset(AFT_RETURN_APPLY_STATUS)

AFT_RETURN_APPLY_GOODS_STATUS: Final[dict[int, str]] = {
    0: '未发货',
    1: '已发货未收',
    2: '已收货',
}
AFT_RETURN_APPLY_GOODS_STATUS_VALUES: Final[frozenset[int]] = frozenset(AFT_RETURN_APPLY_GOODS_STATUS)

AFT_RETURN_APPLY_IS_ARCHIVED_ORDER: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
AFT_RETURN_APPLY_IS_ARCHIVED_ORDER_VALUES: Final[frozenset[int]] = frozenset(AFT_RETURN_APPLY_IS_ARCHIVED_ORDER)

AFT_RETURN_APPLY_WARN_LEVEL: Final[dict[int, str]] = {
    0: '无',
    1: '黄色',
    2: '红色',
    3: '已超时',
}
AFT_RETURN_APPLY_WARN_LEVEL_VALUES: Final[frozenset[int]] = frozenset(AFT_RETURN_APPLY_WARN_LEVEL)

AFT_RETURN_APPLY_SYNC_STATUS: Final[dict[int, str]] = {
    0: '未回传',
    1: '回传中',
    2: '成功',
    3: '失败待重试',
    4: '转人工',
}
AFT_RETURN_APPLY_SYNC_STATUS_VALUES: Final[frozenset[int]] = frozenset(AFT_RETURN_APPLY_SYNC_STATUS)

AFT_RETURN_APPLY_AUTO_AGREED_BY_PLATFORM: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
AFT_RETURN_APPLY_AUTO_AGREED_BY_PLATFORM_VALUES: Final[frozenset[int]] = frozenset(AFT_RETURN_APPLY_AUTO_AGREED_BY_PLATFORM)

AFT_RETURN_APPLY_AUDIT_CHANNEL: Final[dict[int, str]] = {
    0: '未审核',
    1: '人工',
    2: '自动规则',
    3: '临期兜底',
    4: 'OA审批',
}
AFT_RETURN_APPLY_AUDIT_CHANNEL_VALUES: Final[frozenset[int]] = frozenset(AFT_RETURN_APPLY_AUDIT_CHANNEL)

AFT_RETURN_APPLY_ITEM_GIFT_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
AFT_RETURN_APPLY_ITEM_GIFT_FLAG_VALUES: Final[frozenset[int]] = frozenset(AFT_RETURN_APPLY_ITEM_GIFT_FLAG)

AFT_RETURN_APPLY_LOG_OPERATOR_TYPE: Final[dict[int, str]] = {
    1: '系统',
    2: '人工',
}
AFT_RETURN_APPLY_LOG_OPERATOR_TYPE_VALUES: Final[frozenset[int]] = frozenset(AFT_RETURN_APPLY_LOG_OPERATOR_TYPE)

AFT_RESHIP_RESHIP_TYPE: Final[dict[int, str]] = {
    1: '退货入库',
    2: '换货',
}
AFT_RESHIP_RESHIP_TYPE_VALUES: Final[frozenset[int]] = frozenset(AFT_RESHIP_RESHIP_TYPE)

AFT_RESHIP_STATUS: Final[dict[int, str]] = {
    1: '已创建',
    2: '已预报',
    3: '下发失败',
    4: '运送中',
    5: '收货中',
    6: '质检完成',
    7: '已闭环',
    8: '已取消',
    9: '质检异常挂起',
    10: '差异处理中',
}
AFT_RESHIP_STATUS_VALUES: Final[frozenset[int]] = frozenset(AFT_RESHIP_STATUS)

AFT_RESHIP_SN_CHECK_STATUS: Final[dict[int, str]] = {
    0: '无SN物料',
    1: '全部通过',
    2: '部分失败挂起',
    3: '失败疑似调包',
}
AFT_RESHIP_SN_CHECK_STATUS_VALUES: Final[frozenset[int]] = frozenset(AFT_RESHIP_SN_CHECK_STATUS)

AFT_RESHIP_DIFF_STATUS: Final[dict[int, str]] = {
    0: '无差异',
    1: '等待补寄',
    2: '期满按实收闭环',
    3: '多退容差内',
    4: '暂挂待认领',
    5: '人工强制闭环',
}
AFT_RESHIP_DIFF_STATUS_VALUES: Final[frozenset[int]] = frozenset(AFT_RESHIP_DIFF_STATUS)

AFT_RESHIP_CLOSE_TYPE: Final[dict[int, str]] = {
    0: '未闭环',
    1: '正常',
    2: '差异闭环',
    3: '强制闭环',
    4: '取消',
}
AFT_RESHIP_CLOSE_TYPE_VALUES: Final[frozenset[int]] = frozenset(AFT_RESHIP_CLOSE_TYPE)

AFT_RESHIP_ITEM_REFUND_TRIGGER_STATUS: Final[dict[int, str]] = {
    0: '未触发',
    1: '已触发',
    2: '人工确认中',
}
AFT_RESHIP_ITEM_REFUND_TRIGGER_STATUS_VALUES: Final[frozenset[int]] = frozenset(AFT_RESHIP_ITEM_REFUND_TRIGGER_STATUS)

AFT_RESHIP_ITEM_DIFF_FLAG: Final[dict[int, str]] = {
    0: '无',
    1: '有',
}
AFT_RESHIP_ITEM_DIFF_FLAG_VALUES: Final[frozenset[int]] = frozenset(AFT_RESHIP_ITEM_DIFF_FLAG)

AFT_RESHIP_SN_CHECK_STAGE: Final[dict[int, str]] = {
    1: '预报登记',
    2: '质检扫码',
}
AFT_RESHIP_SN_CHECK_STAGE_VALUES: Final[frozenset[int]] = frozenset(AFT_RESHIP_SN_CHECK_STAGE)

AFT_RESHIP_SN_CHECK_RESULT: Final[dict[int, str]] = {
    0: '待校验',
    1: '通过',
    2: '失败-非本订单出库SN',
    3: '失败-SN状态异常',
    4: '降级跳过',
}
AFT_RESHIP_SN_CHECK_RESULT_VALUES: Final[frozenset[int]] = frozenset(AFT_RESHIP_SN_CHECK_RESULT)

AFT_RESHIP_SN_SWAP_SUSPECT_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
AFT_RESHIP_SN_SWAP_SUSPECT_FLAG_VALUES: Final[frozenset[int]] = frozenset(AFT_RESHIP_SN_SWAP_SUSPECT_FLAG)

AFT_RESHIP_SN_BEFORE_SN_STATUS: Final[dict[int, str]] = {
    1: '在库',
    2: '已出库',
    3: '售后中',
    4: '已核销',
    5: '换出',
    6: '终止',
}
AFT_RESHIP_SN_BEFORE_SN_STATUS_VALUES: Final[frozenset[int]] = frozenset(AFT_RESHIP_SN_BEFORE_SN_STATUS)

AFT_RESHIP_SN_HANDLE_RESULT: Final[dict[int, str]] = {
    0: '无需处理',
    1: '确认调包-拒收该件',
    2: '登记错误-D04.09修正后重检',
    3: '确认正常放行',
}
AFT_RESHIP_SN_HANDLE_RESULT_VALUES: Final[frozenset[int]] = frozenset(AFT_RESHIP_SN_HANDLE_RESULT)

AFT_DEFECT_DISPOSAL_DISPOSAL_TYPE: Final[dict[int, str]] = {
    1: '退仓还品牌方',
    2: '报废',
    3: '促销出清',
    4: '退供应商',
}
AFT_DEFECT_DISPOSAL_DISPOSAL_TYPE_VALUES: Final[frozenset[int]] = frozenset(AFT_DEFECT_DISPOSAL_DISPOSAL_TYPE)

AFT_DEFECT_DISPOSAL_APPROVAL_STATUS: Final[dict[int, str]] = {
    0: '免审',
    1: '待OA审批',
    2: '通过',
    3: '驳回',
    4: '待品牌方门户确认',
}
AFT_DEFECT_DISPOSAL_APPROVAL_STATUS_VALUES: Final[frozenset[int]] = frozenset(AFT_DEFECT_DISPOSAL_APPROVAL_STATUS)

AFT_DEFECT_DISPOSAL_STATUS: Final[dict[int, str]] = {
    1: '待处置',
    2: '处置中',
    3: '已闭环',
    4: '超期预警',
}
AFT_DEFECT_DISPOSAL_STATUS_VALUES: Final[frozenset[int]] = frozenset(AFT_DEFECT_DISPOSAL_STATUS)

AFT_RETURN_LOGISTICS_TRACE_STATUS: Final[dict[int, str]] = {
    1: '已揽收',
    2: '运输中',
    3: '已签收',
    4: '拒收',
    5: '退回买家',
    6: '无轨迹',
}
AFT_RETURN_LOGISTICS_TRACE_STATUS_VALUES: Final[frozenset[int]] = frozenset(AFT_RETURN_LOGISTICS_TRACE_STATUS)

AFT_RETURN_LOGISTICS_WARN_FLAG: Final[dict[int, str]] = {
    0: '无',
    1: '签收后超时未质检',
    2: '拒收/退回异常',
    3: '预报后15天无轨迹',
}
AFT_RETURN_LOGISTICS_WARN_FLAG_VALUES: Final[frozenset[int]] = frozenset(AFT_RETURN_LOGISTICS_WARN_FLAG)

AFT_REFUND_STATUS: Final[dict[int, str]] = {
    1: '待退款',
    2: '退款中',
    3: '已退款',
    4: '退款失败',
    5: '已退款-线下',
    6: '已取消',
}
AFT_REFUND_STATUS_VALUES: Final[frozenset[int]] = frozenset(AFT_REFUND_STATUS)

AFT_REFUND_CHANNEL: Final[dict[int, str]] = {
    1: 'platform',
    2: 'offline',
}
AFT_REFUND_CHANNEL_VALUES: Final[frozenset[int]] = frozenset(AFT_REFUND_CHANNEL)

AFT_REFUND_PLATFORM_INTERVENED: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
AFT_REFUND_PLATFORM_INTERVENED_VALUES: Final[frozenset[int]] = frozenset(AFT_REFUND_PLATFORM_INTERVENED)

AFT_REFUND_LOSS_TYPE: Final[dict[int, str]] = {
    0: '无',
    1: '弃货退款',
    2: '平台介入资损',
    3: '超时自动同意资损',
}
AFT_REFUND_LOSS_TYPE_VALUES: Final[frozenset[int]] = frozenset(AFT_REFUND_LOSS_TYPE)

AFT_REFUND_AUDIT_CHANNEL: Final[dict[int, str]] = {
    1: '人工',
    2: '自动',
    3: 'OA审批',
}
AFT_REFUND_AUDIT_CHANNEL_VALUES: Final[frozenset[int]] = frozenset(AFT_REFUND_AUDIT_CHANNEL)

AFT_REFUND_RISK_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
AFT_REFUND_RISK_FLAG_VALUES: Final[frozenset[int]] = frozenset(AFT_REFUND_RISK_FLAG)

AFT_REFUND_LEDGER_STATUS: Final[dict[int, str]] = {
    0: '未入账',
    1: '已推D08',
    2: '差异',
}
AFT_REFUND_LEDGER_STATUS_VALUES: Final[frozenset[int]] = frozenset(AFT_REFUND_LEDGER_STATUS)

AFT_REFUND_ALLOC_IS_LAST_LINE: Final[dict[int, str]] = {
    0: '否',
    1: '是[辅助]',
}
AFT_REFUND_ALLOC_IS_LAST_LINE_VALUES: Final[frozenset[int]] = frozenset(AFT_REFUND_ALLOC_IS_LAST_LINE)

AFT_REFUND_LOG_OPERATOR_TYPE: Final[dict[int, str]] = {
    1: '系统',
    2: '人工',
}
AFT_REFUND_LOG_OPERATOR_TYPE_VALUES: Final[frozenset[int]] = frozenset(AFT_REFUND_LOG_OPERATOR_TYPE)

AFT_EXCHANGE_EXCHANGE_TYPE: Final[dict[int, str]] = {
    1: '同款',
    2: '异款',
}
AFT_EXCHANGE_EXCHANGE_TYPE_VALUES: Final[frozenset[int]] = frozenset(AFT_EXCHANGE_EXCHANGE_TYPE)

AFT_EXCHANGE_RESHIP_ONLY: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
AFT_EXCHANGE_RESHIP_ONLY_VALUES: Final[frozenset[int]] = frozenset(AFT_EXCHANGE_RESHIP_ONLY)

AFT_EXCHANGE_STATUS: Final[dict[int, str]] = {
    1: '已创建',
    2: '退货链路中',
    3: '双链路并行中',
    4: '待补差确认',
    5: '补发链路中',
    6: '补发挂起',
    7: '退货超时挂起',
    8: '人工决策中',
    9: '完成',
    10: '已取消',
}
AFT_EXCHANGE_STATUS_VALUES: Final[frozenset[int]] = frozenset(AFT_EXCHANGE_STATUS)

AFT_EXCHANGE_DIFF_TYPE: Final[dict[int, str]] = {
    0: '无差价',
    1: '退差',
    2: '补差',
}
AFT_EXCHANGE_DIFF_TYPE_VALUES: Final[frozenset[int]] = frozenset(AFT_EXCHANGE_DIFF_TYPE)

AFT_EXCHANGE_DIFF_STATUS: Final[dict[int, str]] = {
    0: '无差价',
    1: '处理中',
    2: '已结清',
    3: '已冲销',
}
AFT_EXCHANGE_DIFF_STATUS_VALUES: Final[frozenset[int]] = frozenset(AFT_EXCHANGE_DIFF_STATUS)

AFT_EXCHANGE_SN_REENTRY_POLICY: Final[dict[int, str]] = {
    1: '可再售',
    2: '换出终止',
}
AFT_EXCHANGE_SN_REENTRY_POLICY_VALUES: Final[frozenset[int]] = frozenset(AFT_EXCHANGE_SN_REENTRY_POLICY)

AFT_EXCHANGE_LOG_OPERATOR_TYPE: Final[dict[int, str]] = {
    1: '系统',
    2: '人工',
}
AFT_EXCHANGE_LOG_OPERATOR_TYPE_VALUES: Final[frozenset[int]] = frozenset(AFT_EXCHANGE_LOG_OPERATOR_TYPE)

AFT_AUTO_AUDIT_LOG_DECISION: Final[dict[int, str]] = {
    1: '自动同意',
    2: '拒绝建议',
    3: '转人工',
    4: '灰度未开转人工',
    5: '竞态放弃',
    6: '临期兜底自动同意',
}
AFT_AUTO_AUDIT_LOG_DECISION_VALUES: Final[frozenset[int]] = frozenset(AFT_AUTO_AUDIT_LOG_DECISION)

AFT_AUTO_AUDIT_LOG_RISK_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
AFT_AUTO_AUDIT_LOG_RISK_FLAG_VALUES: Final[frozenset[int]] = frozenset(AFT_AUTO_AUDIT_LOG_RISK_FLAG)

AFT_AUTO_AUDIT_LOG_DEADLINE_RESCUE: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
AFT_AUTO_AUDIT_LOG_DEADLINE_RESCUE_VALUES: Final[frozenset[int]] = frozenset(AFT_AUTO_AUDIT_LOG_DEADLINE_RESCUE)

AFT_AUTO_AUDIT_LOG_MANUAL_FINAL_DECISION: Final[dict[int, str]] = {
    0: '未回填',
    1: '同意',
    2: '拒绝',
    3: '转OA',
}
AFT_AUTO_AUDIT_LOG_MANUAL_FINAL_DECISION_VALUES: Final[frozenset[int]] = frozenset(AFT_AUTO_AUDIT_LOG_MANUAL_FINAL_DECISION)

AFT_AUTO_AUDIT_LOG_OVERTURN_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
AFT_AUTO_AUDIT_LOG_OVERTURN_FLAG_VALUES: Final[frozenset[int]] = frozenset(AFT_AUTO_AUDIT_LOG_OVERTURN_FLAG)

AFT_AUDIT_TASK_TASK_TYPE: Final[dict[int, str]] = {
    1: '常规人工审核',
    2: '自动审核转人工',
    3: '拒绝建议确认',
    4: '抽检任务',
    5: '风控复核',
    6: '质检争议复核',
}
AFT_AUDIT_TASK_TASK_TYPE_VALUES: Final[frozenset[int]] = frozenset(AFT_AUDIT_TASK_TASK_TYPE)

AFT_AUDIT_TASK_PRIORITY: Final[dict[int, str]] = {
    1: '普通',
    2: '重要',
    3: '置顶',
}
AFT_AUDIT_TASK_PRIORITY_VALUES: Final[frozenset[int]] = frozenset(AFT_AUDIT_TASK_PRIORITY)

AFT_AUDIT_TASK_STATUS: Final[dict[int, str]] = {
    1: '待处理',
    2: '已认领',
    3: '已完成',
    4: '已取消',
}
AFT_AUDIT_TASK_STATUS_VALUES: Final[frozenset[int]] = frozenset(AFT_AUDIT_TASK_STATUS)

AFT_AUDIT_TASK_RESULT: Final[dict[int, str]] = {
    0: '未决',
    1: '同意',
    2: '拒绝',
    3: '转OA审批',
    4: '改判同意',
}
AFT_AUDIT_TASK_RESULT_VALUES: Final[frozenset[int]] = frozenset(AFT_AUDIT_TASK_RESULT)

AFT_RISK_FLAG_DIM_TYPE: Final[dict[int, str]] = {
    1: '买家',
    2: '店铺',
    3: '收货地址',
}
AFT_RISK_FLAG_DIM_TYPE_VALUES: Final[frozenset[int]] = frozenset(AFT_RISK_FLAG_DIM_TYPE)

AFT_RISK_FLAG_BLACKLIST_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
AFT_RISK_FLAG_BLACKLIST_FLAG_VALUES: Final[frozenset[int]] = frozenset(AFT_RISK_FLAG_BLACKLIST_FLAG)

AFT_RISK_FLAG_HIGH_FREQ_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
AFT_RISK_FLAG_HIGH_FREQ_FLAG_VALUES: Final[frozenset[int]] = frozenset(AFT_RISK_FLAG_HIGH_FREQ_FLAG)

AFT_RISK_FLAG_CALIBRATE_STATUS: Final[dict[int, str]] = {
    0: '待校准',
    1: '已日终校准',
}
AFT_RISK_FLAG_CALIBRATE_STATUS_VALUES: Final[frozenset[int]] = frozenset(AFT_RISK_FLAG_CALIBRATE_STATUS)

AFT_TIMEOUT_MONITOR_AFTERSALE_TYPE: Final[dict[int, str]] = {
    1: '仅退款',
    2: '退货退款',
    3: '换货',
}
AFT_TIMEOUT_MONITOR_AFTERSALE_TYPE_VALUES: Final[frozenset[int]] = frozenset(AFT_TIMEOUT_MONITOR_AFTERSALE_TYPE)

AFT_TIMEOUT_MONITOR_WARN_LEVEL: Final[dict[int, str]] = {
    0: '正常',
    1: '黄色',
    2: '红色',
    3: '已超时',
}
AFT_TIMEOUT_MONITOR_WARN_LEVEL_VALUES: Final[frozenset[int]] = frozenset(AFT_TIMEOUT_MONITOR_WARN_LEVEL)

AFT_TIMEOUT_MONITOR_ESCALATE_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '已升级主管',
}
AFT_TIMEOUT_MONITOR_ESCALATE_FLAG_VALUES: Final[frozenset[int]] = frozenset(AFT_TIMEOUT_MONITOR_ESCALATE_FLAG)

AFT_TIMEOUT_MONITOR_AUTO_AGREED_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
AFT_TIMEOUT_MONITOR_AUTO_AGREED_FLAG_VALUES: Final[frozenset[int]] = frozenset(AFT_TIMEOUT_MONITOR_AUTO_AGREED_FLAG)

AFT_TIMEOUT_MONITOR_LOSS_REVIEW_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '已入复盘清单',
}
AFT_TIMEOUT_MONITOR_LOSS_REVIEW_FLAG_VALUES: Final[frozenset[int]] = frozenset(AFT_TIMEOUT_MONITOR_LOSS_REVIEW_FLAG)

AFT_TIMEOUT_MONITOR_STATUS: Final[dict[int, str]] = {
    1: '监控中',
    2: '已处理按时闭环',
    3: '已超时',
    4: '平台自动同意已收敛',
    5: '已取消',
}
AFT_TIMEOUT_MONITOR_STATUS_VALUES: Final[frozenset[int]] = frozenset(AFT_TIMEOUT_MONITOR_STATUS)

AFT_BUYER_PROFILE_APPEAL_STATUS: Final[dict[int, str]] = {
    0: '无',
    1: '申诉中',
    2: '申诉通过',
    3: '申诉驳回',
}
AFT_BUYER_PROFILE_APPEAL_STATUS_VALUES: Final[frozenset[int]] = frozenset(AFT_BUYER_PROFILE_APPEAL_STATUS)


# ==================== oms_purchase ====================

PUR_DICT_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
PUR_DICT_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_DICT_STATUS)

PUR_SUPPLIER_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
    3: '冻结',
}
PUR_SUPPLIER_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_SUPPLIER_STATUS)

PUR_SUPPLIER_PAY_TYPE: Final[dict[int, str]] = {
    1: '现购cash',
    2: '赊购credit',
}
PUR_SUPPLIER_PAY_TYPE_VALUES: Final[frozenset[int]] = frozenset(PUR_SUPPLIER_PAY_TYPE)

PUR_SUPPLIER_SETTLE_TYPE: Final[dict[int, str]] = {
    1: '票到付款',
    2: '货到付款',
    3: '月结',
}
PUR_SUPPLIER_SETTLE_TYPE_VALUES: Final[frozenset[int]] = frozenset(PUR_SUPPLIER_SETTLE_TYPE)

PUR_SUPPLY_RELATION_TAX_FLAG: Final[dict[int, str]] = {
    1: '含税',
    2: '不含税',
}
PUR_SUPPLY_RELATION_TAX_FLAG_VALUES: Final[frozenset[int]] = frozenset(PUR_SUPPLY_RELATION_TAX_FLAG)

PUR_SUPPLY_RELATION_IS_DEFAULT: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
PUR_SUPPLY_RELATION_IS_DEFAULT_VALUES: Final[frozenset[int]] = frozenset(PUR_SUPPLY_RELATION_IS_DEFAULT)

PUR_SUPPLY_RELATION_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
PUR_SUPPLY_RELATION_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_SUPPLY_RELATION_STATUS)

PUR_SUPPLY_PRICE_LOG_TAX_FLAG: Final[dict[int, str]] = {
    1: '含税',
    2: '不含税',
}
PUR_SUPPLY_PRICE_LOG_TAX_FLAG_VALUES: Final[frozenset[int]] = frozenset(PUR_SUPPLY_PRICE_LOG_TAX_FLAG)

PUR_REQUEST_REQUEST_TYPE: Final[dict[int, str]] = {
    1: '手工',
    2: '补货建议转单',
    3: '批量导入',
}
PUR_REQUEST_REQUEST_TYPE_VALUES: Final[frozenset[int]] = frozenset(PUR_REQUEST_REQUEST_TYPE)

PUR_REQUEST_STATUS: Final[dict[int, str]] = {
    1: '草稿',
    2: '审批中',
    3: '已通过',
    4: '已驳回',
    5: '部分转单',
    6: '已转单',
    7: '已关闭',
    8: '已作废',
}
PUR_REQUEST_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_REQUEST_STATUS)

PUR_REQUEST_APPROVAL_RESULT: Final[dict[int, str]] = {
    0: '无',
    1: '通过',
    2: '驳回',
    3: '撤回确认',
}
PUR_REQUEST_APPROVAL_RESULT_VALUES: Final[frozenset[int]] = frozenset(PUR_REQUEST_APPROVAL_RESULT)

PUR_REQUEST_CLOSE_REASON: Final[dict[int, str]] = {
    0: '无',
    1: '需求取消',
    2: '供应商断供',
    3: '价格谈崩',
    4: '转由调拨解决',
    9: '其他',
}
PUR_REQUEST_CLOSE_REASON_VALUES: Final[frozenset[int]] = frozenset(PUR_REQUEST_CLOSE_REASON)

PUR_REQUEST_ITEM_SOURCE_TYPE: Final[dict[int, str]] = {
    1: '手工',
    2: '补货建议转单',
    3: '导入',
}
PUR_REQUEST_ITEM_SOURCE_TYPE_VALUES: Final[frozenset[int]] = frozenset(PUR_REQUEST_ITEM_SOURCE_TYPE)

PUR_REQUEST_ITEM_ITEM_STATUS: Final[dict[int, str]] = {
    1: '待转单',
    2: '部分转单',
    3: '已转单',
    4: '已关闭',
}
PUR_REQUEST_ITEM_ITEM_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_REQUEST_ITEM_ITEM_STATUS)

PUR_ORDER_SOURCE_TYPE: Final[dict[int, str]] = {
    1: '申请转单',
    2: '直接创建',
    3: '复制创建',
}
PUR_ORDER_SOURCE_TYPE_VALUES: Final[frozenset[int]] = frozenset(PUR_ORDER_SOURCE_TYPE)

PUR_ORDER_PO_TYPE: Final[dict[int, str]] = {
    1: '现购cash',
    2: '赊购credit',
}
PUR_ORDER_PO_TYPE_VALUES: Final[frozenset[int]] = frozenset(PUR_ORDER_PO_TYPE)

PUR_ORDER_AUDIT_STATUS: Final[dict[int, str]] = {
    1: '未审核',
    2: '审批中',
    3: '已审核',
    4: '已驳回',
    5: '已作废',
}
PUR_ORDER_AUDIT_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_ORDER_AUDIT_STATUS)

PUR_ORDER_INBOUND_STATUS: Final[dict[int, str]] = {
    0: '不适用',
    1: '待入库',
    2: '部分入库',
    3: '已入库',
    4: '未入库终止',
}
PUR_ORDER_INBOUND_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_ORDER_INBOUND_STATUS)

PUR_ORDER_PURCHASE_STATUS: Final[dict[int, str]] = {
    1: '执行中',
    2: '采购完成',
    3: '已终止',
    4: '部分终止',
    5: '采购退货',
}
PUR_ORDER_PURCHASE_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_ORDER_PURCHASE_STATUS)

PUR_ORDER_SETTLE_STATUS: Final[dict[int, str]] = {
    1: '未结算',
    2: '部分结算',
    3: '已结算',
    4: '拒绝结算',
}
PUR_ORDER_SETTLE_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_ORDER_SETTLE_STATUS)

PUR_ORDER_DAMAGE_STATUS: Final[dict[int, str]] = {
    0: '无需确认',
    1: '待确认',
    2: '已确认',
}
PUR_ORDER_DAMAGE_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_ORDER_DAMAGE_STATUS)

PUR_ORDER_WMS_SYNC_STATUS: Final[dict[int, str]] = {
    1: '无需同步',
    2: '已下发',
    3: '推送失败',
    4: '已取消同步',
}
PUR_ORDER_WMS_SYNC_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_ORDER_WMS_SYNC_STATUS)

PUR_ORDER_TERMINATE_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
PUR_ORDER_TERMINATE_FLAG_VALUES: Final[frozenset[int]] = frozenset(PUR_ORDER_TERMINATE_FLAG)

PUR_ORDER_EMERGENCY: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
PUR_ORDER_EMERGENCY_VALUES: Final[frozenset[int]] = frozenset(PUR_ORDER_EMERGENCY)

PUR_ORDER_SUPPLIER_CONFIRM_FLAG: Final[dict[int, str]] = {
    0: '未确认',
    1: '已确认',
}
PUR_ORDER_SUPPLIER_CONFIRM_FLAG_VALUES: Final[frozenset[int]] = frozenset(PUR_ORDER_SUPPLIER_CONFIRM_FLAG)

PUR_ORDER_ITEM_ITEM_STATUS: Final[dict[int, str]] = {
    1: '待入库',
    2: '部分入库',
    3: '完成入库',
    4: '已关闭',
}
PUR_ORDER_ITEM_ITEM_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_ORDER_ITEM_ITEM_STATUS)

PUR_ORDER_FEE_FEE_TYPE: Final[dict[int, str]] = {
    1: '运费',
    2: '装卸费',
    3: '保险费',
    4: '关税',
    9: '其他',
}
PUR_ORDER_FEE_FEE_TYPE_VALUES: Final[frozenset[int]] = frozenset(PUR_ORDER_FEE_FEE_TYPE)

PUR_ORDER_FEE_ALLOC_TYPE: Final[dict[int, str]] = {
    1: '按金额占比',
    2: '按数量占比',
}
PUR_ORDER_FEE_ALLOC_TYPE_VALUES: Final[frozenset[int]] = frozenset(PUR_ORDER_FEE_ALLOC_TYPE)

PUR_ARRIVAL_PLAN_DEVIATION_FLAG: Final[dict[int, str]] = {
    0: '无',
    1: '日期偏离',
    2: '量差偏离',
    3: '双偏离',
}
PUR_ARRIVAL_PLAN_DEVIATION_FLAG_VALUES: Final[frozenset[int]] = frozenset(PUR_ARRIVAL_PLAN_DEVIATION_FLAG)

PUR_ARRIVAL_PLAN_STATUS: Final[dict[int, str]] = {
    1: '待到货',
    2: '部分核销',
    3: '已核销',
    4: '已关闭',
}
PUR_ARRIVAL_PLAN_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_ARRIVAL_PLAN_STATUS)

PUR_ORDER_CHANGE_CHANGE_TYPE: Final[dict[int, str]] = {
    1: '加量',
    2: '减量',
    3: '价格调整',
    4: '价外费用',
    5: '到货计划',
    6: '头信息',
    7: '整单取消',
    8: '部分终止',
    9: '反审核',
}
PUR_ORDER_CHANGE_CHANGE_TYPE_VALUES: Final[frozenset[int]] = frozenset(PUR_ORDER_CHANGE_CHANGE_TYPE)

PUR_ORDER_CHANGE_REAUDIT_FLAG: Final[dict[int, str]] = {
    0: '免审生效',
    1: '跨阈值上移需OA重审',
}
PUR_ORDER_CHANGE_REAUDIT_FLAG_VALUES: Final[frozenset[int]] = frozenset(PUR_ORDER_CHANGE_REAUDIT_FLAG)

PUR_ORDER_CHANGE_STATUS: Final[dict[int, str]] = {
    1: '挂起',
    2: '已生效',
    3: '已驳回',
    4: '已撤销',
}
PUR_ORDER_CHANGE_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_ORDER_CHANGE_STATUS)

PUR_ARRIVAL_OUT_OF_PLAN_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
PUR_ARRIVAL_OUT_OF_PLAN_FLAG_VALUES: Final[frozenset[int]] = frozenset(PUR_ARRIVAL_OUT_OF_PLAN_FLAG)

PUR_ARRIVAL_STATUS: Final[dict[int, str]] = {
    1: '已登记',
    2: '已生成入库单据',
    3: '已下发',
    4: '收货中',
    5: '已回传',
    6: '已确认',
    7: '已取消',
    8: '异常',
}
PUR_ARRIVAL_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_ARRIVAL_STATUS)

PUR_ARRIVAL_SOURCE_TYPE: Final[dict[int, str]] = {
    1: '手工',
    2: '供应商通知代录',
    3: '导入',
    4: '无单认领',
}
PUR_ARRIVAL_SOURCE_TYPE_VALUES: Final[frozenset[int]] = frozenset(PUR_ARRIVAL_SOURCE_TYPE)

PUR_RECEIPT_ESTIMATE_FLAG: Final[dict[int, str]] = {
    0: '正式价',
    1: '暂估价',
}
PUR_RECEIPT_ESTIMATE_FLAG_VALUES: Final[frozenset[int]] = frozenset(PUR_RECEIPT_ESTIMATE_FLAG)

PUR_RECEIPT_BILL_STATUS: Final[dict[int, str]] = {
    1: '草稿',
    2: '已下发WMS',
    3: '部分回传',
    4: '全部回传',
    5: '已确认',
    6: '已红冲',
    7: '已关闭',
}
PUR_RECEIPT_BILL_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_RECEIPT_BILL_STATUS)

PUR_RECEIPT_SETTLE_STATUS: Final[dict[int, str]] = {
    0: '无需结算',
    1: '未结算',
    2: '部分结算',
    3: '已结算',
    4: '结算锁定',
}
PUR_RECEIPT_SETTLE_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_RECEIPT_SETTLE_STATUS)

PUR_RECEIPT_ITEM_QUALITY_RESULT: Final[dict[int, str]] = {
    0: '免检',
    1: '合格',
    2: '部分不良',
    3: '整批不良',
}
PUR_RECEIPT_ITEM_QUALITY_RESULT_VALUES: Final[frozenset[int]] = frozenset(PUR_RECEIPT_ITEM_QUALITY_RESULT)

PUR_RECEIPT_ITEM_ESTIMATE_FLAG: Final[dict[int, str]] = {
    0: '正式价',
    1: '暂估价',
}
PUR_RECEIPT_ITEM_ESTIMATE_FLAG_VALUES: Final[frozenset[int]] = frozenset(PUR_RECEIPT_ITEM_ESTIMATE_FLAG)

PUR_DAMAGE_DAMAGE_REASON: Final[dict[int, str]] = {
    1: '运输破损',
    2: '生产不良',
    3: '包装破损',
    4: '效期异常',
    5: '货差短少',
    9: '其他',
}
PUR_DAMAGE_DAMAGE_REASON_VALUES: Final[frozenset[int]] = frozenset(PUR_DAMAGE_DAMAGE_REASON)

PUR_DAMAGE_CLAIM_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
PUR_DAMAGE_CLAIM_FLAG_VALUES: Final[frozenset[int]] = frozenset(PUR_DAMAGE_CLAIM_FLAG)

PUR_DAMAGE_CLAIM_OBJECT_TYPE: Final[dict[int, str]] = {
    0: '无',
    1: '供应商',
    2: '物流承运商',
}
PUR_DAMAGE_CLAIM_OBJECT_TYPE_VALUES: Final[frozenset[int]] = frozenset(PUR_DAMAGE_CLAIM_OBJECT_TYPE)

PUR_DAMAGE_CLAIM_RESULT: Final[dict[int, str]] = {
    0: '处理中',
    1: '认赔',
    2: '部分认赔',
    3: '放弃',
}
PUR_DAMAGE_CLAIM_RESULT_VALUES: Final[frozenset[int]] = frozenset(PUR_DAMAGE_CLAIM_RESULT)

PUR_DAMAGE_STATUS: Final[dict[int, str]] = {
    1: '待决策',
    2: '审批中',
    3: '已决策',
    4: '已闭环',
}
PUR_DAMAGE_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_DAMAGE_STATUS)

PUR_DIFF_DECISION_DIFF_TYPE: Final[dict[int, str]] = {
    1: '短缺',
    2: '超收',
    3: '超收',
    4: '拒收差异',
}
PUR_DIFF_DECISION_DIFF_TYPE_VALUES: Final[frozenset[int]] = frozenset(PUR_DIFF_DECISION_DIFF_TYPE)

PUR_DIFF_DECISION_DECISION: Final[dict[int, str]] = {
    0: '待决策',
    1: '供应商补发',
    2: '短缺核销',
    3: '索赔',
    4: '追认',
    5: '拒收超出',
}
PUR_DIFF_DECISION_DECISION_VALUES: Final[frozenset[int]] = frozenset(PUR_DIFF_DECISION_DECISION)

PUR_DIFF_DECISION_STATUS: Final[dict[int, str]] = {
    1: '待决策',
    2: '已决策',
    3: '已闭环',
}
PUR_DIFF_DECISION_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_DIFF_DECISION_STATUS)

PUR_PAYABLE_ACCRUAL_STRATEGY: Final[dict[int, str]] = {
    1: '现购按单挂账',
    2: '赊购按入库挂账',
}
PUR_PAYABLE_ACCRUAL_STRATEGY_VALUES: Final[frozenset[int]] = frozenset(PUR_PAYABLE_ACCRUAL_STRATEGY)

PUR_PAYABLE_ESTIMATE_FLAG: Final[dict[int, str]] = {
    0: '正式',
    1: '暂估',
}
PUR_PAYABLE_ESTIMATE_FLAG_VALUES: Final[frozenset[int]] = frozenset(PUR_PAYABLE_ESTIMATE_FLAG)

PUR_PAYABLE_SETTLE_STATUS: Final[dict[int, str]] = {
    1: '未结算',
    2: '部分结算',
    3: '已结算',
    4: '拒绝结算',
}
PUR_PAYABLE_SETTLE_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_PAYABLE_SETTLE_STATUS)

PUR_PAYABLE_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '差异挂起',
    3: '已关闭',
}
PUR_PAYABLE_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_PAYABLE_STATUS)

PUR_STATEMENT_CHECK_RESULT: Final[dict[int, str]] = {
    0: '未校验',
    1: '通过',
    2: '不通过',
}
PUR_STATEMENT_CHECK_RESULT_VALUES: Final[frozenset[int]] = frozenset(PUR_STATEMENT_CHECK_RESULT)

PUR_STATEMENT_CLOSE_STATUS: Final[dict[int, str]] = {
    1: '未关账',
    2: '关账中',
    3: '已关账',
}
PUR_STATEMENT_CLOSE_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_STATEMENT_CLOSE_STATUS)

PUR_STATEMENT_RECON_CONFIRM_STATUS: Final[dict[int, str]] = {
    0: '未生成',
    1: '待发送',
    2: '已发送',
    3: '已确认',
    4: '有异议',
}
PUR_STATEMENT_RECON_CONFIRM_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_STATEMENT_RECON_CONFIRM_STATUS)

PUR_STATEMENT_ITEM_OBJECT_TYPE: Final[dict[int, str]] = {
    1: '赊购入库挂账',
    2: '现购按单挂账',
    3: '付款核销',
    4: '退货退款',
    5: '调整扣减',
    6: '预付款抵扣',
    7: '暂估转正调整',
    9: '其他',
}
PUR_STATEMENT_ITEM_OBJECT_TYPE_VALUES: Final[frozenset[int]] = frozenset(PUR_STATEMENT_ITEM_OBJECT_TYPE)

PUR_STATEMENT_ITEM_DIRECTION: Final[dict[int, str]] = {
    1: '应付方向',
    2: '应收方向',
}
PUR_STATEMENT_ITEM_DIRECTION_VALUES: Final[frozenset[int]] = frozenset(PUR_STATEMENT_ITEM_DIRECTION)

PUR_INVOICE_MATCH_STATUS: Final[dict[int, str]] = {
    0: '未匹配',
    1: '部分匹配',
    2: '已匹配',
    3: '差异挂起',
}
PUR_INVOICE_MATCH_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_INVOICE_MATCH_STATUS)

PUR_INVOICE_ESTIMATE_REVERSED: Final[dict[int, str]] = {
    0: '未触发',
    1: '已触发',
}
PUR_INVOICE_ESTIMATE_REVERSED_VALUES: Final[frozenset[int]] = frozenset(PUR_INVOICE_ESTIMATE_REVERSED)

PUR_INVOICE_STATUS: Final[dict[int, str]] = {
    1: '正常',
    2: '作废',
    3: '红冲',
}
PUR_INVOICE_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_INVOICE_STATUS)

PUR_INVOICE_MATCH_MATCH_RESULT: Final[dict[int, str]] = {
    0: '待匹配',
    1: '通过',
    2: '价格差异',
    3: '数量差异',
    4: '金额尾差',
}
PUR_INVOICE_MATCH_MATCH_RESULT_VALUES: Final[frozenset[int]] = frozenset(PUR_INVOICE_MATCH_MATCH_RESULT)

PUR_PAYMENT_PAY_TYPE: Final[dict[int, str]] = {
    1: '预付款',
    2: '货款',
    3: '退款收回抵扣',
}
PUR_PAYMENT_PAY_TYPE_VALUES: Final[frozenset[int]] = frozenset(PUR_PAYMENT_PAY_TYPE)

PUR_PAYMENT_STATUS: Final[dict[int, str]] = {
    1: '申请草稿',
    2: '审批中',
    3: '审批通过待付款',
    4: '已付款',
    5: '已核销',
    6: '已驳回',
    7: '已取消',
}
PUR_PAYMENT_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_PAYMENT_STATUS)

PUR_PAYMENT_KD_PUSH_STATUS: Final[dict[int, str]] = {
    0: '未推送',
    1: '已推送',
    2: '推送失败',
    3: '已冲销同步',
}
PUR_PAYMENT_KD_PUSH_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_PAYMENT_KD_PUSH_STATUS)

PUR_PAYMENT_VERIFY_DIRECTION: Final[dict[int, str]] = {
    1: '正向核销',
    2: '反向撤销',
}
PUR_PAYMENT_VERIFY_DIRECTION_VALUES: Final[frozenset[int]] = frozenset(PUR_PAYMENT_VERIFY_DIRECTION)

PUR_PAYMENT_VERIFY_FIFO_FLAG: Final[dict[int, str]] = {
    0: '人工指定',
    1: '到期日FIFO自动',
}
PUR_PAYMENT_VERIFY_FIFO_FLAG_VALUES: Final[frozenset[int]] = frozenset(PUR_PAYMENT_VERIFY_FIFO_FLAG)

PUR_PAYMENT_VERIFY_KD_REVERSE_FLAG: Final[dict[int, str]] = {
    0: '无需',
    1: '已推金蝶需冲销供数',
}
PUR_PAYMENT_VERIFY_KD_REVERSE_FLAG_VALUES: Final[frozenset[int]] = frozenset(PUR_PAYMENT_VERIFY_KD_REVERSE_FLAG)

PUR_RECON_DIFF_DIFF_TYPE: Final[dict[int, str]] = {
    1: '价格差异',
    2: '数量差异',
    3: '金额尾差',
    4: '对账异议',
    5: '暂估超期',
    6: '台账差额校验不平',
    7: '索赔争议',
}
PUR_RECON_DIFF_DIFF_TYPE_VALUES: Final[frozenset[int]] = frozenset(PUR_RECON_DIFF_DIFF_TYPE)

PUR_RECON_DIFF_HANDLE_PATH: Final[dict[int, str]] = {
    0: '待定',
    1: '拒付差额',
    2: '追认调价',
    3: '补决策',
    4: '重开发票',
    5: '强制核销',
    9: '其他',
}
PUR_RECON_DIFF_HANDLE_PATH_VALUES: Final[frozenset[int]] = frozenset(PUR_RECON_DIFF_HANDLE_PATH)

PUR_RECON_DIFF_FORCE_VERIFY_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
PUR_RECON_DIFF_FORCE_VERIFY_FLAG_VALUES: Final[frozenset[int]] = frozenset(PUR_RECON_DIFF_FORCE_VERIFY_FLAG)

PUR_RECON_DIFF_STATUS: Final[dict[int, str]] = {
    1: '待处理',
    2: '处理中',
    3: '已闭环',
    4: '已升级',
}
PUR_RECON_DIFF_STATUS_VALUES: Final[frozenset[int]] = frozenset(PUR_RECON_DIFF_STATUS)


# ==================== oms_dealer ====================

DLR_PRICE_TYPE_TAX_MODE: Final[dict[int, str]] = {
    1: '含税价',
    2: '不含税价',
}
DLR_PRICE_TYPE_TAX_MODE_VALUES: Final[frozenset[int]] = frozenset(DLR_PRICE_TYPE_TAX_MODE)

DLR_PRICE_TYPE_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
DLR_PRICE_TYPE_STATUS_VALUES: Final[frozenset[int]] = frozenset(DLR_PRICE_TYPE_STATUS)

DLR_DEALER_DEALER_LEVEL: Final[dict[int, str]] = {
    1: '战略',
    2: 'A级',
    3: 'B级',
    4: 'C级',
}
DLR_DEALER_DEALER_LEVEL_VALUES: Final[frozenset[int]] = frozenset(DLR_DEALER_DEALER_LEVEL)

DLR_DEALER_COOP_MODE: Final[dict[int, str]] = {
    1: '买断转售',
    2: '代发',
    3: '混合',
}
DLR_DEALER_COOP_MODE_VALUES: Final[frozenset[int]] = frozenset(DLR_DEALER_COOP_MODE)

DLR_DEALER_STATUS: Final[dict[int, str]] = {
    1: '合作中',
    2: '暂停',
    3: '终止',
}
DLR_DEALER_STATUS_VALUES: Final[frozenset[int]] = frozenset(DLR_DEALER_STATUS)

DLR_DEALER_SHOP_SHOP_TYPE: Final[dict[int, str]] = {
    1: '线上店',
    2: '线下门店',
}
DLR_DEALER_SHOP_SHOP_TYPE_VALUES: Final[frozenset[int]] = frozenset(DLR_DEALER_SHOP_SHOP_TYPE)

DLR_DEALER_SHOP_IS_DROPSHIP: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
DLR_DEALER_SHOP_IS_DROPSHIP_VALUES: Final[frozenset[int]] = frozenset(DLR_DEALER_SHOP_IS_DROPSHIP)

DLR_DEALER_SHOP_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
DLR_DEALER_SHOP_STATUS_VALUES: Final[frozenset[int]] = frozenset(DLR_DEALER_SHOP_STATUS)

DLR_CREDIT_ACCOUNT_OVER_POLICY: Final[dict[int, str]] = {
    1: '拦截',
    2: 'OA审批放行',
}
DLR_CREDIT_ACCOUNT_OVER_POLICY_VALUES: Final[frozenset[int]] = frozenset(DLR_CREDIT_ACCOUNT_OVER_POLICY)

DLR_CREDIT_ACCOUNT_STATUS: Final[dict[int, str]] = {
    1: '正常',
    2: '冻结',
}
DLR_CREDIT_ACCOUNT_STATUS_VALUES: Final[frozenset[int]] = frozenset(DLR_CREDIT_ACCOUNT_STATUS)

DLR_CREDIT_TXN_TXN_TYPE: Final[dict[int, str]] = {
    1: '下单预占',
    2: '释放',
    3: '审核扣减',
    4: '转应收',
    5: '回款恢复',
    6: '逾期登记',
}
DLR_CREDIT_TXN_TXN_TYPE_VALUES: Final[frozenset[int]] = frozenset(DLR_CREDIT_TXN_TXN_TYPE)

DLR_CREDIT_TXN_DIRECTION: Final[dict[int, str]] = {
    1: '占用增加',
    2: '占用减少',
    3: '性质转换',
    4: '逾期登记',
}
DLR_CREDIT_TXN_DIRECTION_VALUES: Final[frozenset[int]] = frozenset(DLR_CREDIT_TXN_DIRECTION)

DLR_CREDIT_PERIOD_START_ANCHOR: Final[dict[int, str]] = {
    1: '发货日',
    2: '结算单归档日',
}
DLR_CREDIT_PERIOD_START_ANCHOR_VALUES: Final[frozenset[int]] = frozenset(DLR_CREDIT_PERIOD_START_ANCHOR)

DLR_CREDIT_PERIOD_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '历史',
}
DLR_CREDIT_PERIOD_STATUS_VALUES: Final[frozenset[int]] = frozenset(DLR_CREDIT_PERIOD_STATUS)

DLR_PRODUCT_AUTH_AUTH_LEVEL: Final[dict[int, str]] = {
    1: '品牌级',
    2: '分类级',
    3: 'SKU级',
}
DLR_PRODUCT_AUTH_AUTH_LEVEL_VALUES: Final[frozenset[int]] = frozenset(DLR_PRODUCT_AUTH_AUTH_LEVEL)

DLR_PRODUCT_AUTH_DELIVERY_MODE: Final[dict[int, str]] = {
    1: '自发',
    2: '代发',
}
DLR_PRODUCT_AUTH_DELIVERY_MODE_VALUES: Final[frozenset[int]] = frozenset(DLR_PRODUCT_AUTH_DELIVERY_MODE)

DLR_PRODUCT_AUTH_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '已失效',
    3: '已终止',
}
DLR_PRODUCT_AUTH_STATUS_VALUES: Final[frozenset[int]] = frozenset(DLR_PRODUCT_AUTH_STATUS)

DLR_SALES_ORDER_CHANNEL: Final[dict[int, str]] = {
    1: '门户自助',
    2: '业务员代下单',
    3: '批量导入',
    4: 'EDI直连',
}
DLR_SALES_ORDER_CHANNEL_VALUES: Final[frozenset[int]] = frozenset(DLR_SALES_ORDER_CHANNEL)

DLR_SALES_ORDER_PAY_MODE: Final[dict[int, str]] = {
    1: '账期赊销',
    2: '先款后货',
    3: '预存款抵扣',
}
DLR_SALES_ORDER_PAY_MODE_VALUES: Final[frozenset[int]] = frozenset(DLR_SALES_ORDER_PAY_MODE)

DLR_SALES_ORDER_AMOUNT_CALIBER: Final[dict[int, str]] = {
    1: '批发价口径',
    2: '0元内部口径——系统级配置选定后全局一致',
}
DLR_SALES_ORDER_AMOUNT_CALIBER_VALUES: Final[frozenset[int]] = frozenset(DLR_SALES_ORDER_AMOUNT_CALIBER)

DLR_SALES_ORDER_ALLOW_SPLIT: Final[dict[int, str]] = {
    0: '整单一次转',
    1: '允许分批转履约',
}
DLR_SALES_ORDER_ALLOW_SPLIT_VALUES: Final[frozenset[int]] = frozenset(DLR_SALES_ORDER_ALLOW_SPLIT)

DLR_SALES_ORDER_STATUS: Final[dict[int, str]] = {
    1: '草稿',
    2: '待审核',
    3: '超额审批中',
    4: '已审核',
    5: '部分转单',
    6: '全部转单',
    7: '部分发货',
    8: '已完成',
    9: '已关闭',
}
DLR_SALES_ORDER_STATUS_VALUES: Final[frozenset[int]] = frozenset(DLR_SALES_ORDER_STATUS)

DLR_SALES_ORDER_CLOSE_REASON: Final[dict[int, str]] = {
    0: '无',
    1: '经销商取消',
    2: '凯淳拒绝',
    3: '超时未审核自动关闭',
    4: 'OA驳回',
}
DLR_SALES_ORDER_CLOSE_REASON_VALUES: Final[frozenset[int]] = frozenset(DLR_SALES_ORDER_CLOSE_REASON)

DLR_SALES_ORDER_CONVERT_STATUS: Final[dict[int, str]] = {
    1: 'unconvert未转',
    2: 'splitting分批中',
    3: 'converted已转',
    4: 'fail转失败',
    5: 'needless无需转',
}
DLR_SALES_ORDER_CONVERT_STATUS_VALUES: Final[frozenset[int]] = frozenset(DLR_SALES_ORDER_CONVERT_STATUS)

DLR_SALES_ORDER_ITEM_MOQ_CHECK: Final[dict[int, str]] = {
    1: '通过',
    2: '低于起订量拦截',
    3: '非整箱倍数拦截',
}
DLR_SALES_ORDER_ITEM_MOQ_CHECK_VALUES: Final[frozenset[int]] = frozenset(DLR_SALES_ORDER_ITEM_MOQ_CHECK)

DLR_SALES_ORDER_ITEM_STATUS: Final[dict[int, str]] = {
    1: '正常',
    2: '已关闭',
    3: '已转完',
}
DLR_SALES_ORDER_ITEM_STATUS_VALUES: Final[frozenset[int]] = frozenset(DLR_SALES_ORDER_ITEM_STATUS)

DLR_PRICE_LIST_STATUS: Final[dict[int, str]] = {
    1: '草稿',
    2: '审批中',
    3: '待生效',
    4: '生效中',
    5: '已失效',
}
DLR_PRICE_LIST_STATUS_VALUES: Final[frozenset[int]] = frozenset(DLR_PRICE_LIST_STATUS)

DLR_PRICE_CHANGE_ACTION: Final[dict[int, str]] = {
    1: '发布',
    2: '变更',
    3: '提前失效',
    4: '版本切换',
    5: '特批价申请',
    6: '合同价录入',
}
DLR_PRICE_CHANGE_ACTION_VALUES: Final[frozenset[int]] = frozenset(DLR_PRICE_CHANGE_ACTION)

DLR_PRICE_CHANGE_APPROVAL_LEVEL: Final[dict[int, str]] = {
    1: '销售总监',
    2: '财务总监加签',
    3: '总经理',
}
DLR_PRICE_CHANGE_APPROVAL_LEVEL_VALUES: Final[frozenset[int]] = frozenset(DLR_PRICE_CHANGE_APPROVAL_LEVEL)

DLR_PRICE_CHANGE_APPROVAL_STATUS: Final[dict[int, str]] = {
    1: '待审',
    2: '通过',
    3: '驳回',
}
DLR_PRICE_CHANGE_APPROVAL_STATUS_VALUES: Final[frozenset[int]] = frozenset(DLR_PRICE_CHANGE_APPROVAL_STATUS)

DLR_TRANSFER_ORDER_SOURCE_TYPE: Final[dict[int, str]] = {
    1: 'B2B销售单',
    2: '平台单',
}
DLR_TRANSFER_ORDER_SOURCE_TYPE_VALUES: Final[frozenset[int]] = frozenset(DLR_TRANSFER_ORDER_SOURCE_TYPE)

DLR_TRANSFER_ORDER_TRANSFER_STATUS: Final[dict[int, str]] = {
    1: 'unconvert未转',
    2: 'splitting拆分中',
    3: 'converted已转',
    4: 'fail转失败',
    5: 'needless无需转',
}
DLR_TRANSFER_ORDER_TRANSFER_STATUS_VALUES: Final[frozenset[int]] = frozenset(DLR_TRANSFER_ORDER_TRANSFER_STATUS)

DLR_TRANSFER_ORDER_CHANNEL_TYPE: Final[dict[int, str]] = {
    1: '凯淳仓代发',
    2: '货权方仓',
    3: '供应商直发',
}
DLR_TRANSFER_ORDER_CHANNEL_TYPE_VALUES: Final[frozenset[int]] = frozenset(DLR_TRANSFER_ORDER_CHANNEL_TYPE)

DLR_TRANSFER_ORDER_ITEM_DROPSHIP_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
DLR_TRANSFER_ORDER_ITEM_DROPSHIP_FLAG_VALUES: Final[frozenset[int]] = frozenset(DLR_TRANSFER_ORDER_ITEM_DROPSHIP_FLAG)

DLR_TRANSFER_ORDER_ITEM_STATUS: Final[dict[int, str]] = {
    1: '待转',
    2: '已转',
    3: '挂起',
    4: '失败',
    5: '已取消',
}
DLR_TRANSFER_ORDER_ITEM_STATUS_VALUES: Final[frozenset[int]] = frozenset(DLR_TRANSFER_ORDER_ITEM_STATUS)

DLR_DROPSHIP_LEDGER_OBJECT_TYPE: Final[dict[int, str]] = {
    1: '代发出库',
    2: '代发服务费',
    3: '经销商侧代发应收',
    4: '调整',
}
DLR_DROPSHIP_LEDGER_OBJECT_TYPE_VALUES: Final[frozenset[int]] = frozenset(DLR_DROPSHIP_LEDGER_OBJECT_TYPE)

DLR_DROPSHIP_LEDGER_DIRECTION: Final[dict[int, str]] = {
    1: '凯淳应付',
    2: '凯淳应收',
}
DLR_DROPSHIP_LEDGER_DIRECTION_VALUES: Final[frozenset[int]] = frozenset(DLR_DROPSHIP_LEDGER_DIRECTION)

DLR_DROPSHIP_LEDGER_SETTLE_PRICE_TYPE: Final[dict[int, str]] = {
    1: '内部购销价',
    2: '成本价',
    3: '免费',
}
DLR_DROPSHIP_LEDGER_SETTLE_PRICE_TYPE_VALUES: Final[frozenset[int]] = frozenset(DLR_DROPSHIP_LEDGER_SETTLE_PRICE_TYPE)

DLR_DROPSHIP_LEDGER_SETTLE_STATUS: Final[dict[int, str]] = {
    0: '未结算',
    1: '已入结算单',
    2: '已归档',
}
DLR_DROPSHIP_LEDGER_SETTLE_STATUS_VALUES: Final[frozenset[int]] = frozenset(DLR_DROPSHIP_LEDGER_SETTLE_STATUS)


# ==================== oms_finance ====================

FIN_DICT_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
FIN_DICT_STATUS_VALUES: Final[frozenset[int]] = frozenset(FIN_DICT_STATUS)

FIN_GAP_ACCOUNT_NEED_HANDLE: Final[dict[int, str]] = {
    0: '口径差无需处理',
    1: '需处理',
}
FIN_GAP_ACCOUNT_NEED_HANDLE_VALUES: Final[frozenset[int]] = frozenset(FIN_GAP_ACCOUNT_NEED_HANDLE)

FIN_GAP_ACCOUNT_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
FIN_GAP_ACCOUNT_STATUS_VALUES: Final[frozenset[int]] = frozenset(FIN_GAP_ACCOUNT_STATUS)

FIN_CREDIT_PERIOD_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '历史',
}
FIN_CREDIT_PERIOD_STATUS_VALUES: Final[frozenset[int]] = frozenset(FIN_CREDIT_PERIOD_STATUS)

FIN_SETTLE_CONFIG_PLATFORM_IN_SETTLE: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
FIN_SETTLE_CONFIG_PLATFORM_IN_SETTLE_VALUES: Final[frozenset[int]] = frozenset(FIN_SETTLE_CONFIG_PLATFORM_IN_SETTLE)

FIN_SETTLE_CONFIG_ZERO_PERIOD_SKIP: Final[dict[int, str]] = {
    0: '生成空结算单保持连续性',
    1: '跳过',
}
FIN_SETTLE_CONFIG_ZERO_PERIOD_SKIP_VALUES: Final[frozenset[int]] = frozenset(FIN_SETTLE_CONFIG_ZERO_PERIOD_SKIP)

FIN_SETTLE_CONFIG_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '历史',
}
FIN_SETTLE_CONFIG_STATUS_VALUES: Final[frozenset[int]] = frozenset(FIN_SETTLE_CONFIG_STATUS)

FIN_SERVICE_FEE_RULE_WITH_REFUND: Final[dict[int, str]] = {
    0: '毛销售额',
    1: '净销售额',
}
FIN_SERVICE_FEE_RULE_WITH_REFUND_VALUES: Final[frozenset[int]] = frozenset(FIN_SERVICE_FEE_RULE_WITH_REFUND)

FIN_SERVICE_FEE_RULE_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '停用',
    3: '历史',
}
FIN_SERVICE_FEE_RULE_STATUS_VALUES: Final[frozenset[int]] = frozenset(FIN_SERVICE_FEE_RULE_STATUS)

FIN_INVOICE_CHANNEL_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
FIN_INVOICE_CHANNEL_STATUS_VALUES: Final[frozenset[int]] = frozenset(FIN_INVOICE_CHANNEL_STATUS)

FIN_CODE_MAPPING_DIRECTION: Final[dict[int, str]] = {
    0: '不适用',
    1: '借',
    2: '贷',
}
FIN_CODE_MAPPING_DIRECTION_VALUES: Final[frozenset[int]] = frozenset(FIN_CODE_MAPPING_DIRECTION)

FIN_CODE_MAPPING_GAP_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
FIN_CODE_MAPPING_GAP_FLAG_VALUES: Final[frozenset[int]] = frozenset(FIN_CODE_MAPPING_GAP_FLAG)

FIN_CODE_MAPPING_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
FIN_CODE_MAPPING_STATUS_VALUES: Final[frozenset[int]] = frozenset(FIN_CODE_MAPPING_STATUS)

FIN_KINGDEE_ADAPTER_STATUS: Final[dict[int, str]] = {
    0: '占位',
    1: '启用',
    2: '停用',
}
FIN_KINGDEE_ADAPTER_STATUS_VALUES: Final[frozenset[int]] = frozenset(FIN_KINGDEE_ADAPTER_STATUS)

FIN_RECEIVABLE_SETTLE_STATUS: Final[dict[int, str]] = {
    0: '未结算',
    1: '已进结算单锁定',
    2: '结算差异处理中',
}
FIN_RECEIVABLE_SETTLE_STATUS_VALUES: Final[frozenset[int]] = frozenset(FIN_RECEIVABLE_SETTLE_STATUS)

FIN_RECEIVABLE_SETTLE_CARRY_NEXT: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
FIN_RECEIVABLE_SETTLE_CARRY_NEXT_VALUES: Final[frozenset[int]] = frozenset(FIN_RECEIVABLE_SETTLE_CARRY_NEXT)

FIN_RECEIVABLE_LEND_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
FIN_RECEIVABLE_LEND_FLAG_VALUES: Final[frozenset[int]] = frozenset(FIN_RECEIVABLE_LEND_FLAG)

FIN_RECEIVABLE_PLATFORM_INTERVENED: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
FIN_RECEIVABLE_PLATFORM_INTERVENED_VALUES: Final[frozenset[int]] = frozenset(FIN_RECEIVABLE_PLATFORM_INTERVENED)

FIN_RECEIVABLE_WAIT_LINK_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
FIN_RECEIVABLE_WAIT_LINK_FLAG_VALUES: Final[frozenset[int]] = frozenset(FIN_RECEIVABLE_WAIT_LINK_FLAG)

FIN_PLATFORM_BILL_ITEM_DIRECTION: Final[dict[int, str]] = {
    1: '收入',
    2: '支出',
}
FIN_PLATFORM_BILL_ITEM_DIRECTION_VALUES: Final[frozenset[int]] = frozenset(FIN_PLATFORM_BILL_ITEM_DIRECTION)

FIN_PLATFORM_BILL_ITEM_SPLIT_STATUS: Final[dict[int, str]] = {
    0: '未拆分',
    1: '已双口径拆分',
    2: '不可拆',
    3: '一流水拆多订单/多费用项',
}
FIN_PLATFORM_BILL_ITEM_SPLIT_STATUS_VALUES: Final[frozenset[int]] = frozenset(FIN_PLATFORM_BILL_ITEM_SPLIT_STATUS)

FIN_BILL_DIFF_AUTO_JUDGE: Final[dict[int, str]] = {
    0: '人工判定',
    1: '自动初判',
}
FIN_BILL_DIFF_AUTO_JUDGE_VALUES: Final[frozenset[int]] = frozenset(FIN_BILL_DIFF_AUTO_JUDGE)

FIN_PLATFORM_FEE_SETTLE_STATUS: Final[dict[int, str]] = {
    0: '未结算',
    1: '已进结算单',
}
FIN_PLATFORM_FEE_SETTLE_STATUS_VALUES: Final[frozenset[int]] = frozenset(FIN_PLATFORM_FEE_SETTLE_STATUS)

FIN_PLATFORM_FEE_REVERSE_FLAG: Final[dict[int, str]] = {
    0: '正常',
    1: '红冲行',
}
FIN_PLATFORM_FEE_REVERSE_FLAG_VALUES: Final[frozenset[int]] = frozenset(FIN_PLATFORM_FEE_REVERSE_FLAG)

FIN_AR_LEDGER_CHECK_STATUS: Final[dict[int, str]] = {
    0: '未校验',
    1: '一致',
    2: '不一致已按明细重算',
}
FIN_AR_LEDGER_CHECK_STATUS_VALUES: Final[frozenset[int]] = frozenset(FIN_AR_LEDGER_CHECK_STATUS)

FIN_SETTLEMENT_OWNER_TYPE: Final[dict[int, str]] = {
    1: '代销',
    2: '买断',
}
FIN_SETTLEMENT_OWNER_TYPE_VALUES: Final[frozenset[int]] = frozenset(FIN_SETTLEMENT_OWNER_TYPE)

FIN_SETTLEMENT_NET_DIRECTION: Final[dict[int, str]] = {
    0: '零交易',
    1: '净额>0凯淳应付品牌方',
    2: '净额<0品牌方应付凯淳',
}
FIN_SETTLEMENT_NET_DIRECTION_VALUES: Final[frozenset[int]] = frozenset(FIN_SETTLEMENT_NET_DIRECTION)

FIN_SETTLEMENT_KD_PUSH_STATUS: Final[dict[int, str]] = {
    0: '待推',
    1: '已推',
    2: '失败重试',
}
FIN_SETTLEMENT_KD_PUSH_STATUS_VALUES: Final[frozenset[int]] = frozenset(FIN_SETTLEMENT_KD_PUSH_STATUS)

FIN_SETTLEMENT_PERIOD_LOCK: Final[dict[int, str]] = {
    0: '未锁',
    1: '已锁',
}
FIN_SETTLEMENT_PERIOD_LOCK_VALUES: Final[frozenset[int]] = frozenset(FIN_SETTLEMENT_PERIOD_LOCK)

FIN_SETTLEMENT_ITEM_LEND_DIRECTION: Final[dict[int, str]] = {
    0: '非借调',
    1: '本货主为借入方应付凯淳',
    2: '本货主为借出方应收',
}
FIN_SETTLEMENT_ITEM_LEND_DIRECTION_VALUES: Final[frozenset[int]] = frozenset(FIN_SETTLEMENT_ITEM_LEND_DIRECTION)

FIN_RECEIPT_DIRECTION: Final[dict[int, str]] = {
    1: '收款',
    2: '付款',
}
FIN_RECEIPT_DIRECTION_VALUES: Final[frozenset[int]] = frozenset(FIN_RECEIPT_DIRECTION)

FIN_WRITE_OFF_WRITEOFF_TYPE: Final[dict[int, str]] = {
    0: '应收应退互冲',
    1: '收款核销',
    2: '付款核销',
}
FIN_WRITE_OFF_WRITEOFF_TYPE_VALUES: Final[frozenset[int]] = frozenset(FIN_WRITE_OFF_WRITEOFF_TYPE)

FIN_WRITE_OFF_AUTO_FLAG: Final[dict[int, str]] = {
    0: '人工',
    1: '自动',
}
FIN_WRITE_OFF_AUTO_FLAG_VALUES: Final[frozenset[int]] = frozenset(FIN_WRITE_OFF_AUTO_FLAG)

FIN_WRITE_OFF_REVERSE_FLAG: Final[dict[int, str]] = {
    0: '正常',
    1: '反核销负向记录',
}
FIN_WRITE_OFF_REVERSE_FLAG_VALUES: Final[frozenset[int]] = frozenset(FIN_WRITE_OFF_REVERSE_FLAG)

FIN_ERROR_TABLE_DIFF_DIRECTION: Final[dict[int, str]] = {
    1: '借方',
    2: '贷方',
}
FIN_ERROR_TABLE_DIFF_DIRECTION_VALUES: Final[frozenset[int]] = frozenset(FIN_ERROR_TABLE_DIFF_DIRECTION)

FIN_FREIGHT_BILL_ITEM_TOLERANCE_RESULT: Final[dict[int, str]] = {
    0: '未判定',
    1: '容差内自动通过',
    2: '超容差进差异池',
}
FIN_FREIGHT_BILL_ITEM_TOLERANCE_RESULT_VALUES: Final[frozenset[int]] = frozenset(FIN_FREIGHT_BILL_ITEM_TOLERANCE_RESULT)

FIN_INVOICE_APPLY_BUYER_TYPE: Final[dict[int, str]] = {
    1: '个人',
    2: '企业',
}
FIN_INVOICE_APPLY_BUYER_TYPE_VALUES: Final[frozenset[int]] = frozenset(FIN_INVOICE_APPLY_BUYER_TYPE)

FIN_INVOICE_POOL_CONDITION_TYPE: Final[dict[int, str]] = {
    1: '已发货',
    2: '已付款',
    3: '已完成',
}
FIN_INVOICE_POOL_CONDITION_TYPE_VALUES: Final[frozenset[int]] = frozenset(FIN_INVOICE_POOL_CONDITION_TYPE)

FIN_INVOICE_COLOR: Final[dict[int, str]] = {
    1: '蓝票',
    2: '红票',
}
FIN_INVOICE_COLOR_VALUES: Final[frozenset[int]] = frozenset(FIN_INVOICE_COLOR)

FIN_INVOICE_ISSUER_TYPE: Final[dict[int, str]] = {
    1: '凯淳',
    2: '品牌方',
}
FIN_INVOICE_ISSUER_TYPE_VALUES: Final[frozenset[int]] = frozenset(FIN_INVOICE_ISSUER_TYPE)

FIN_KINGDEE_SUPPLY_FEED_TYPE: Final[dict[int, str]] = {
    1: '销售明细/',
    2: '退款明细/',
    3: '结算单/',
    4: '采购入库与应付/',
    5: '运费实际/',
    6: '发票台账/',
    7: '存货余额与出入库成本',
}
FIN_KINGDEE_SUPPLY_FEED_TYPE_VALUES: Final[frozenset[int]] = frozenset(FIN_KINGDEE_SUPPLY_FEED_TYPE)

FIN_KINGDEE_SUPPLY_FILE_ENCRYPT_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
FIN_KINGDEE_SUPPLY_FILE_ENCRYPT_FLAG_VALUES: Final[frozenset[int]] = frozenset(FIN_KINGDEE_SUPPLY_FILE_ENCRYPT_FLAG)

FIN_KINGDEE_SUPPLY_FILE_NOTIFY_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
FIN_KINGDEE_SUPPLY_FILE_NOTIFY_FLAG_VALUES: Final[frozenset[int]] = frozenset(FIN_KINGDEE_SUPPLY_FILE_NOTIFY_FLAG)

FIN_KINGDEE_RECEIPT_CHECK_RESULT: Final[dict[int, str]] = {
    0: '待勾稽',
    1: '勾稽通过',
    2: '勾稽不平',
}
FIN_KINGDEE_RECEIPT_CHECK_RESULT_VALUES: Final[frozenset[int]] = frozenset(FIN_KINGDEE_RECEIPT_CHECK_RESULT)

FIN_KINGDEE_RECEIPT_TIMEOUT_ALERT: Final[dict[int, str]] = {
    0: '未催',
    1: '已催办',
}
FIN_KINGDEE_RECEIPT_TIMEOUT_ALERT_VALUES: Final[frozenset[int]] = frozenset(FIN_KINGDEE_RECEIPT_TIMEOUT_ALERT)


# ==================== oms_org ====================

ORG_NODE_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
ORG_NODE_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_NODE_STATUS)

ORG_NODE_RELATION_IS_PRIMARY: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
ORG_NODE_RELATION_IS_PRIMARY_VALUES: Final[frozenset[int]] = frozenset(ORG_NODE_RELATION_IS_PRIMARY)

ORG_NODE_RELATION_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
ORG_NODE_RELATION_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_NODE_RELATION_STATUS)

ORG_OWNER_STATUS: Final[dict[int, str]] = {
    1: '合作中',
    2: '暂停',
    3: '终止',
}
ORG_OWNER_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_OWNER_STATUS)

ORG_OWNER_CONTRACT_STATUS: Final[dict[int, str]] = {
    1: '草稿',
    2: '生效中',
    3: '已到期',
    4: '已作废',
}
ORG_OWNER_CONTRACT_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_OWNER_CONTRACT_STATUS)

ORG_OWNER_SETTLE_CONFIG_SETTLE_PERIOD_TYPE: Final[dict[int, str]] = {
    1: '月结',
    2: '半月结',
    3: '周结',
}
ORG_OWNER_SETTLE_CONFIG_SETTLE_PERIOD_TYPE_VALUES: Final[frozenset[int]] = frozenset(ORG_OWNER_SETTLE_CONFIG_SETTLE_PERIOD_TYPE)

ORG_OWNER_SETTLE_CONFIG_PAYMENT_START_BASIS: Final[dict[int, str]] = {
    1: '结算单归档日',
    2: '品牌方确认日',
}
ORG_OWNER_SETTLE_CONFIG_PAYMENT_START_BASIS_VALUES: Final[frozenset[int]] = frozenset(ORG_OWNER_SETTLE_CONFIG_PAYMENT_START_BASIS)

ORG_OWNER_SETTLE_CONFIG_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '历史',
}
ORG_OWNER_SETTLE_CONFIG_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_OWNER_SETTLE_CONFIG_STATUS)

ORG_SHOP_OWNER_TRANSFER_APPROVAL_STATUS: Final[dict[int, str]] = {
    0: '待发起',
    1: '审批中',
    2: '通过',
    3: '驳回',
}
ORG_SHOP_OWNER_TRANSFER_APPROVAL_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_SHOP_OWNER_TRANSFER_APPROVAL_STATUS)

ORG_SHOP_OWNER_TRANSFER_STATUS: Final[dict[int, str]] = {
    1: '草稿',
    2: '审批中',
    3: '执行中',
    4: '完成',
    5: '关闭',
}
ORG_SHOP_OWNER_TRANSFER_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_SHOP_OWNER_TRANSFER_STATUS)

ORG_TENANT_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '禁用',
}
ORG_TENANT_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_TENANT_STATUS)

ORG_ACCOUNT_STATUS: Final[dict[int, str]] = {
    1: '待激活',
    2: '正常',
    3: '锁定',
    4: '禁用',
}
ORG_ACCOUNT_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_ACCOUNT_STATUS)

ORG_ACCOUNT_CREDENTIAL_MUST_CHANGE_PWD: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
ORG_ACCOUNT_CREDENTIAL_MUST_CHANGE_PWD_VALUES: Final[frozenset[int]] = frozenset(ORG_ACCOUNT_CREDENTIAL_MUST_CHANGE_PWD)

ORG_ACCOUNT_CREDENTIAL_STATUS: Final[dict[int, str]] = {
    1: '有效',
    2: '失效',
}
ORG_ACCOUNT_CREDENTIAL_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_ACCOUNT_CREDENTIAL_STATUS)

ORG_SESSION_STATUS: Final[dict[int, str]] = {
    1: '活跃',
    2: '登出',
    3: '被踢',
    4: '被吊销',
}
ORG_SESSION_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_SESSION_STATUS)

ORG_SESSION_LOGIN_RESULT: Final[dict[int, str]] = {
    1: '成功',
    2: '失败',
}
ORG_SESSION_LOGIN_RESULT_VALUES: Final[frozenset[int]] = frozenset(ORG_SESSION_LOGIN_RESULT)

ORG_ROLE_PORTAL_FLAG: Final[dict[int, str]] = {
    0: '内部',
    1: '外部',
}
ORG_ROLE_PORTAL_FLAG_VALUES: Final[frozenset[int]] = frozenset(ORG_ROLE_PORTAL_FLAG)

ORG_ROLE_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
ORG_ROLE_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_ROLE_STATUS)

ORG_IDP_CONFIG_ENABLED: Final[dict[int, str]] = {
    0: '关',
    1: '开',
}
ORG_IDP_CONFIG_ENABLED_VALUES: Final[frozenset[int]] = frozenset(ORG_IDP_CONFIG_ENABLED)

ORG_PERM_POINT_INTERNAL_ONLY: Final[dict[int, str]] = {
    0: '外部可绑定',
    1: '仅内部',
}
ORG_PERM_POINT_INTERNAL_ONLY_VALUES: Final[frozenset[int]] = frozenset(ORG_PERM_POINT_INTERNAL_ONLY)

ORG_PERM_POINT_PORTAL_VISIBLE: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
ORG_PERM_POINT_PORTAL_VISIBLE_VALUES: Final[frozenset[int]] = frozenset(ORG_PERM_POINT_PORTAL_VISIBLE)

ORG_PERM_POINT_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '废弃',
}
ORG_PERM_POINT_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_PERM_POINT_STATUS)

ORG_DATA_PERMISSION_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '已失效',
}
ORG_DATA_PERMISSION_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_DATA_PERMISSION_STATUS)

ORG_FILTERABLE_ENTITY_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '停用',
}
ORG_FILTERABLE_ENTITY_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_FILTERABLE_ENTITY_STATUS)

ORG_FIELD_PERM_PORTAL_FORBIDDEN: Final[dict[int, str]] = {
    0: '按权限点',
    1: '品牌方永不展示',
}
ORG_FIELD_PERM_PORTAL_FORBIDDEN_VALUES: Final[frozenset[int]] = frozenset(ORG_FIELD_PERM_PORTAL_FORBIDDEN)

ORG_FIELD_PERM_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '停用',
}
ORG_FIELD_PERM_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_FIELD_PERM_STATUS)

ORG_PERM_VIOLATION_AUDIT_PUSHED: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
ORG_PERM_VIOLATION_AUDIT_PUSHED_VALUES: Final[frozenset[int]] = frozenset(ORG_PERM_VIOLATION_AUDIT_PUSHED)

ORG_PORTAL_ACCOUNT_AUDIT_STATUS: Final[dict[int, str]] = {
    0: '待审核',
    1: '通过',
    2: '驳回',
    3: '无需审核',
}
ORG_PORTAL_ACCOUNT_AUDIT_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_PORTAL_ACCOUNT_AUDIT_STATUS)

ORG_PORTAL_MESSAGE_READ_STATUS: Final[dict[int, str]] = {
    0: '未读',
    1: '已读',
}
ORG_PORTAL_MESSAGE_READ_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_PORTAL_MESSAGE_READ_STATUS)

ORG_PORTAL_READ_LOG_SAMPLED: Final[dict[int, str]] = {
    0: '全量',
    1: '采样命中',
}
ORG_PORTAL_READ_LOG_SAMPLED_VALUES: Final[frozenset[int]] = frozenset(ORG_PORTAL_READ_LOG_SAMPLED)

ORG_APPROVAL_SCENE_DEFAULT_NEED: Final[dict[int, str]] = {
    0: '免审',
    1: '需审',
}
ORG_APPROVAL_SCENE_DEFAULT_NEED_VALUES: Final[frozenset[int]] = frozenset(ORG_APPROVAL_SCENE_DEFAULT_NEED)

ORG_APPROVAL_SCENE_FIXED_MUST: Final[dict[int, str]] = {
    0: '有阈值配置',
    1: '全量必审无阈值豁免',
}
ORG_APPROVAL_SCENE_FIXED_MUST_VALUES: Final[frozenset[int]] = frozenset(ORG_APPROVAL_SCENE_FIXED_MUST)

ORG_APPROVAL_SCENE_STUB_MODE: Final[dict[int, str]] = {
    0: '正式OA',
    1: '桩',
}
ORG_APPROVAL_SCENE_STUB_MODE_VALUES: Final[frozenset[int]] = frozenset(ORG_APPROVAL_SCENE_STUB_MODE)

ORG_APPROVAL_SCENE_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '废弃',
}
ORG_APPROVAL_SCENE_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_APPROVAL_SCENE_STATUS)

ORG_APPROVAL_THRESHOLD_NEED_APPROVAL: Final[dict[int, str]] = {
    0: '免审',
    1: '需审',
}
ORG_APPROVAL_THRESHOLD_NEED_APPROVAL_VALUES: Final[frozenset[int]] = frozenset(ORG_APPROVAL_THRESHOLD_NEED_APPROVAL)

ORG_APPROVAL_THRESHOLD_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '停用',
}
ORG_APPROVAL_THRESHOLD_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_APPROVAL_THRESHOLD_STATUS)

ORG_APPROVAL_INSTANCE_URGENT_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
ORG_APPROVAL_INSTANCE_URGENT_FLAG_VALUES: Final[frozenset[int]] = frozenset(ORG_APPROVAL_INSTANCE_URGENT_FLAG)

ORG_APPROVAL_INSTANCE_AUTO_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
ORG_APPROVAL_INSTANCE_AUTO_FLAG_VALUES: Final[frozenset[int]] = frozenset(ORG_APPROVAL_INSTANCE_AUTO_FLAG)

ORG_APPROVAL_INSTANCE_STATUS: Final[dict[int, str]] = {
    1: '发起中',
    2: '审批中',
    3: '通过',
    4: '驳回',
    5: '撤回',
    6: '发起失败',
    7: '撤回中',
    8: '通过未执行',
}
ORG_APPROVAL_INSTANCE_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_APPROVAL_INSTANCE_STATUS)

ORG_APPROVAL_INSTANCE_EXECUTE_CHECK_STATUS: Final[dict[int, str]] = {
    0: '未执行',
    1: '通过',
    2: '失败',
}
ORG_APPROVAL_INSTANCE_EXECUTE_CHECK_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_APPROVAL_INSTANCE_EXECUTE_CHECK_STATUS)

ORG_OA_CALLBACK_LOG_DIRECTION: Final[dict[int, str]] = {
    1: '入',
    2: '出',
}
ORG_OA_CALLBACK_LOG_DIRECTION_VALUES: Final[frozenset[int]] = frozenset(ORG_OA_CALLBACK_LOG_DIRECTION)

ORG_OA_CALLBACK_LOG_SIGN_VERIFIED: Final[dict[int, str]] = {
    0: '失败',
    1: '通过',
}
ORG_OA_CALLBACK_LOG_SIGN_VERIFIED_VALUES: Final[frozenset[int]] = frozenset(ORG_OA_CALLBACK_LOG_SIGN_VERIFIED)

ORG_OA_CALLBACK_LOG_PROCESS_STATUS: Final[dict[int, str]] = {
    0: '待处理',
    1: '已处理',
    2: '重复忽略',
    3: '乱序忽略',
    4: '处理失败',
}
ORG_OA_CALLBACK_LOG_PROCESS_STATUS_VALUES: Final[frozenset[int]] = frozenset(ORG_OA_CALLBACK_LOG_PROCESS_STATUS)

AUD_OPERATION_LOG_SENSITIVE_LEVEL: Final[dict[int, str]] = {
    1: '普通',
    2: '一般变更决策',
    3: '资金/PII明文/权限变更',
}
AUD_OPERATION_LOG_SENSITIVE_LEVEL_VALUES: Final[frozenset[int]] = frozenset(AUD_OPERATION_LOG_SENSITIVE_LEVEL)

AUD_DATA_ACCESS_LOG_RISK_FLAG: Final[dict[int, str]] = {
    0: '正常',
    1: '高频',
    2: '非工作时段批量',
    3: '爬取模式',
    4: '服务账号解密量突增',
}
AUD_DATA_ACCESS_LOG_RISK_FLAG_VALUES: Final[frozenset[int]] = frozenset(AUD_DATA_ACCESS_LOG_RISK_FLAG)

AUD_DATA_ACCESS_LOG_ANONYMIZED: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
AUD_DATA_ACCESS_LOG_ANONYMIZED_VALUES: Final[frozenset[int]] = frozenset(AUD_DATA_ACCESS_LOG_ANONYMIZED)

AUD_ENTITY_REGISTRY_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '停用',
}
AUD_ENTITY_REGISTRY_STATUS_VALUES: Final[frozenset[int]] = frozenset(AUD_ENTITY_REGISTRY_STATUS)

AUD_HASH_ANCHOR_VERIFY_STATUS: Final[dict[int, str]] = {
    0: '待校验',
    1: '通过',
    2: '断链',
}
AUD_HASH_ANCHOR_VERIFY_STATUS_VALUES: Final[frozenset[int]] = frozenset(AUD_HASH_ANCHOR_VERIFY_STATUS)

AUD_RETENTION_POLICY_POLICY_LEVEL: Final[dict[int, str]] = {
    1: '普通',
    2: '一般变更决策',
    3: '资金/PII明文/权限变更',
}
AUD_RETENTION_POLICY_POLICY_LEVEL_VALUES: Final[frozenset[int]] = frozenset(AUD_RETENTION_POLICY_POLICY_LEVEL)

AUD_RETENTION_POLICY_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '历史',
}
AUD_RETENTION_POLICY_STATUS_VALUES: Final[frozenset[int]] = frozenset(AUD_RETENTION_POLICY_STATUS)


# ==================== oms_report ====================

RPT_INDICATOR_DICT_STATUS: Final[dict[int, str]] = {
    1: '生效',
    2: '历史',
    3: '废止',
}
RPT_INDICATOR_DICT_STATUS_VALUES: Final[frozenset[int]] = frozenset(RPT_INDICATOR_DICT_STATUS)

RPT_SNAPSHOT_TASK_STATUS: Final[dict[int, str]] = {
    1: '待执行',
    2: '生成中',
    3: '就绪',
    4: '失败',
    5: '待人工复核',
    6: '已重跑替代',
}
RPT_SNAPSHOT_TASK_STATUS_VALUES: Final[frozenset[int]] = frozenset(RPT_SNAPSHOT_TASK_STATUS)

RPT_SNAPSHOT_TASK_RERUN_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
RPT_SNAPSHOT_TASK_RERUN_FLAG_VALUES: Final[frozenset[int]] = frozenset(RPT_SNAPSHOT_TASK_RERUN_FLAG)

RPT_PRODUCT_SALE_RANK_WINDOW_TYPE: Final[dict[int, str]] = {
    1: '当日',
    2: '近7天滚动',
    3: '近30天滚动',
    4: '近90天滚动',
}
RPT_PRODUCT_SALE_RANK_WINDOW_TYPE_VALUES: Final[frozenset[int]] = frozenset(RPT_PRODUCT_SALE_RANK_WINDOW_TYPE)

RPT_PRODUCT_SALE_RANK_RANK_TYPE: Final[dict[int, str]] = {
    1: '按GMV',
    2: '按销量',
    3: '按实付',
    4: '按退款率',
}
RPT_PRODUCT_SALE_RANK_RANK_TYPE_VALUES: Final[frozenset[int]] = frozenset(RPT_PRODUCT_SALE_RANK_RANK_TYPE)

RPT_STOCK_SNAPSHOT_OWNER_TYPE: Final[dict[int, str]] = {
    1: '买断',
    2: '代销',
    3: '经销商DEALER_TC',
}
RPT_STOCK_SNAPSHOT_OWNER_TYPE_VALUES: Final[frozenset[int]] = frozenset(RPT_STOCK_SNAPSHOT_OWNER_TYPE)

RPT_STOCK_AGE_AGE_BUCKET: Final[dict[int, str]] = {
    30: '0-30天',
    60: '31-60天',
    90: '61-90天',
    180: '91-180天',
}
RPT_STOCK_AGE_AGE_BUCKET_VALUES: Final[frozenset[int]] = frozenset(RPT_STOCK_AGE_AGE_BUCKET)

RPT_NEAR_EXPIRE_EXPIRE_LEVEL: Final[dict[int, str]] = {
    1: '黄',
    2: '橙',
    3: '红',
}
RPT_NEAR_EXPIRE_EXPIRE_LEVEL_VALUES: Final[frozenset[int]] = frozenset(RPT_NEAR_EXPIRE_EXPIRE_LEVEL)

RPT_NEAR_EXPIRE_DISPOSAL_STATUS: Final[dict[int, str]] = {
    0: '未处置',
    1: '处置中',
    2: '已处置',
    3: '已过期',
}
RPT_NEAR_EXPIRE_DISPOSAL_STATUS_VALUES: Final[frozenset[int]] = frozenset(RPT_NEAR_EXPIRE_DISPOSAL_STATUS)

RPT_STOCKOUT_AGE_LEVEL: Final[dict[int, str]] = {
    1: '>24h',
    2: '>48h',
    3: '>72h',
}
RPT_STOCKOUT_AGE_LEVEL_VALUES: Final[frozenset[int]] = frozenset(RPT_STOCKOUT_AGE_LEVEL)

RPT_STOCKOUT_SUGGEST_STATUS: Final[dict[int, str]] = {
    0: '无',
    1: '已生成',
    2: '已采纳',
}
RPT_STOCKOUT_SUGGEST_STATUS_VALUES: Final[frozenset[int]] = frozenset(RPT_STOCKOUT_SUGGEST_STATUS)

RPT_TIMEOUT_ALERT_STATUS: Final[dict[int, str]] = {
    1: '预警中',
    2: '已解除',
    3: '已升级',
}
RPT_TIMEOUT_ALERT_STATUS_VALUES: Final[frozenset[int]] = frozenset(RPT_TIMEOUT_ALERT_STATUS)

RPT_AFTERSALE_APPLY_TYPE: Final[dict[int, str]] = {
    0: '全部',
    1: '仅退款',
    2: '退货退款',
    3: '换货',
    4: '补发',
}
RPT_AFTERSALE_APPLY_TYPE_VALUES: Final[frozenset[int]] = frozenset(RPT_AFTERSALE_APPLY_TYPE)

RPT_AFTERSALE_DENOMINATOR_TYPE: Final[dict[int, str]] = {
    1: '付款订单量',
    2: '发货订单量',
}
RPT_AFTERSALE_DENOMINATOR_TYPE_VALUES: Final[frozenset[int]] = frozenset(RPT_AFTERSALE_DENOMINATOR_TYPE)

RPT_PROFIT_CATEGORY_LEVEL: Final[dict[int, str]] = {
    1: '货主总',
    2: '店铺级',
    3: '分类级',
    4: '单品级',
}
RPT_PROFIT_CATEGORY_LEVEL_VALUES: Final[frozenset[int]] = frozenset(RPT_PROFIT_CATEGORY_LEVEL)

RPT_PROFIT_FREIGHT_CALIBER: Final[dict[int, str]] = {
    1: '实际',
    2: '预估',
}
RPT_PROFIT_FREIGHT_CALIBER_VALUES: Final[frozenset[int]] = frozenset(RPT_PROFIT_FREIGHT_CALIBER)

RPT_PROFIT_PERIOD_LOCKED: Final[dict[int, str]] = {
    0: '未关账',
    1: '已关账只读固化',
}
RPT_PROFIT_PERIOD_LOCKED_VALUES: Final[frozenset[int]] = frozenset(RPT_PROFIT_PERIOD_LOCKED)

RPT_SERVICE_FEE_NET_DIRECTION: Final[dict[int, str]] = {
    1: '凯淳应收',
    2: '凯淳应付',
}
RPT_SERVICE_FEE_NET_DIRECTION_VALUES: Final[frozenset[int]] = frozenset(RPT_SERVICE_FEE_NET_DIRECTION)

RPT_ORDER_WIDE_ORDER_TYPE: Final[dict[int, str]] = {
    1: '普通',
    2: '换货',
    3: '补发',
    4: 'B2B等',
}
RPT_ORDER_WIDE_ORDER_TYPE_VALUES: Final[frozenset[int]] = frozenset(RPT_ORDER_WIDE_ORDER_TYPE)

RPT_ORDER_WIDE_AUDIT_MODE: Final[dict[int, str]] = {
    0: '未审',
    1: '自动',
    2: '人工',
}
RPT_ORDER_WIDE_AUDIT_MODE_VALUES: Final[frozenset[int]] = frozenset(RPT_ORDER_WIDE_AUDIT_MODE)

RPT_ORDER_WIDE_HAS_AFTERSALE: Final[dict[int, str]] = {
    0: '无',
    1: '申请中',
    2: '已完成',
}
RPT_ORDER_WIDE_HAS_AFTERSALE_VALUES: Final[frozenset[int]] = frozenset(RPT_ORDER_WIDE_HAS_AFTERSALE)

RPT_ORDER_WIDE_AFTERSALE_TYPE: Final[dict[int, str]] = {
    0: '无',
    1: '仅退款',
    2: '退货退款',
    3: '换货',
    4: '补发',
}
RPT_ORDER_WIDE_AFTERSALE_TYPE_VALUES: Final[frozenset[int]] = frozenset(RPT_ORDER_WIDE_AFTERSALE_TYPE)

RPT_ORDER_WIDE_REFUND_STATUS: Final[dict[int, str]] = {
    0: '无',
    1: '退款中',
    2: '退款成功',
    3: '退款关闭',
}
RPT_ORDER_WIDE_REFUND_STATUS_VALUES: Final[frozenset[int]] = frozenset(RPT_ORDER_WIDE_REFUND_STATUS)

RPT_ORDER_WIDE_QC_GOOD_FLAG: Final[dict[int, str]] = {
    0: '未质检',
    1: '良品',
    2: '不良品',
}
RPT_ORDER_WIDE_QC_GOOD_FLAG_VALUES: Final[frozenset[int]] = frozenset(RPT_ORDER_WIDE_QC_GOOD_FLAG)

RPT_ORDER_WIDE_PLATFORM_INTERVENED: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
RPT_ORDER_WIDE_PLATFORM_INTERVENED_VALUES: Final[frozenset[int]] = frozenset(RPT_ORDER_WIDE_PLATFORM_INTERVENED)

RPT_STOCK_WIDE_OWNER_TYPE: Final[dict[int, str]] = {
    1: '买断',
    2: '代销',
    3: '经销商',
}
RPT_STOCK_WIDE_OWNER_TYPE_VALUES: Final[frozenset[int]] = frozenset(RPT_STOCK_WIDE_OWNER_TYPE)

RPT_STOCK_WIDE_SLOW_MOVING_FLAG: Final[dict[int, str]] = {
    0: '否',
    1: '是',
}
RPT_STOCK_WIDE_SLOW_MOVING_FLAG_VALUES: Final[frozenset[int]] = frozenset(RPT_STOCK_WIDE_SLOW_MOVING_FLAG)

RPT_SETTLEMENT_WIDE_OWNER_TYPE: Final[dict[int, str]] = {
    1: '买断',
    2: '代销',
    3: '经销商',
}
RPT_SETTLEMENT_WIDE_OWNER_TYPE_VALUES: Final[frozenset[int]] = frozenset(RPT_SETTLEMENT_WIDE_OWNER_TYPE)

RPT_SETTLEMENT_WIDE_REDFLUSH_FLAG: Final[dict[int, str]] = {
    0: '正常',
    1: '红冲单',
    2: '被红冲原单',
}
RPT_SETTLEMENT_WIDE_REDFLUSH_FLAG_VALUES: Final[frozenset[int]] = frozenset(RPT_SETTLEMENT_WIDE_REDFLUSH_FLAG)

RPT_SETTLEMENT_WIDE_NET_DIRECTION: Final[dict[int, str]] = {
    1: '凯淳应付货主',
    2: '凯淳应收货主',
}
RPT_SETTLEMENT_WIDE_NET_DIRECTION_VALUES: Final[frozenset[int]] = frozenset(RPT_SETTLEMENT_WIDE_NET_DIRECTION)

RPT_SETTLEMENT_WIDE_STATUS: Final[dict[int, str]] = {
    1: '已归档',
    2: '已红冲',
}
RPT_SETTLEMENT_WIDE_STATUS_VALUES: Final[frozenset[int]] = frozenset(RPT_SETTLEMENT_WIDE_STATUS)

RPT_BI_PUSH_LOG_BATCH_TYPE: Final[dict[int, str]] = {
    1: '全量',
    2: '增量',
    3: '补推',
    4: '重建',
}
RPT_BI_PUSH_LOG_BATCH_TYPE_VALUES: Final[frozenset[int]] = frozenset(RPT_BI_PUSH_LOG_BATCH_TYPE)

RPT_BI_PUSH_LOG_CHANNEL: Final[dict[int, str]] = {
    1: '文件OSS',
    2: '中间表',
}
RPT_BI_PUSH_LOG_CHANNEL_VALUES: Final[frozenset[int]] = frozenset(RPT_BI_PUSH_LOG_CHANNEL)

RPT_BI_PUSH_LOG_STATUS: Final[dict[int, str]] = {
    1: '加工中',
    2: '已推送',
    3: '对账平',
    4: '对账不平',
    5: '失败',
    6: '已补推替代',
}
RPT_BI_PUSH_LOG_STATUS_VALUES: Final[frozenset[int]] = frozenset(RPT_BI_PUSH_LOG_STATUS)

RPT_BI_PUSH_LOG_RECON_STATUS: Final[dict[int, str]] = {
    0: '未对账',
    1: '平',
    2: '不平',
    3: '无回执超时',
}
RPT_BI_PUSH_LOG_RECON_STATUS_VALUES: Final[frozenset[int]] = frozenset(RPT_BI_PUSH_LOG_RECON_STATUS)

RPT_MONITOR_METRIC_ALERT_MARK: Final[dict[int, str]] = {
    0: '无',
    1: '告警触发点',
    2: '恢复点',
}
RPT_MONITOR_METRIC_ALERT_MARK_VALUES: Final[frozenset[int]] = frozenset(RPT_MONITOR_METRIC_ALERT_MARK)

RPT_MONITOR_METRIC_REG_STATUS: Final[dict[int, str]] = {
    1: '启用',
    2: '停用',
}
RPT_MONITOR_METRIC_REG_STATUS_VALUES: Final[frozenset[int]] = frozenset(RPT_MONITOR_METRIC_REG_STATUS)

RPT_ALERT_CLAIM_ALERT_LEVEL: Final[dict[int, str]] = {
    1: 'P0',
    2: 'P1',
    3: 'P2',
}
RPT_ALERT_CLAIM_ALERT_LEVEL_VALUES: Final[frozenset[int]] = frozenset(RPT_ALERT_CLAIM_ALERT_LEVEL)

RPT_ALERT_CLAIM_STATUS: Final[dict[int, str]] = {
    1: '触发',
    2: '已通知',
    3: '已认领',
    4: '处置中',
    5: '已闭环',
    6: '已自动恢复',
    7: '已归并',
    8: '已静默',
    9: '已升级',
}
RPT_ALERT_CLAIM_STATUS_VALUES: Final[frozenset[int]] = frozenset(RPT_ALERT_CLAIM_STATUS)

RPT_ALERT_CLAIM_ESCALATE_LEVEL: Final[dict[int, str]] = {
    0: '未升级',
    1: 'P1→P0',
    2: 'P0→运营负责人',
}
RPT_ALERT_CLAIM_ESCALATE_LEVEL_VALUES: Final[frozenset[int]] = frozenset(RPT_ALERT_CLAIM_ESCALATE_LEVEL)


# ==================== 字符串枚举（varchar 取值清单） ====================

# ---- oms_base ----

BAS_RULE_CONDITION_OP_CODE: Final[dict[str, str]] = {
    'after': 'after',
    'all_in': 'all_in',
    'any_in': 'any_in',
    'before': 'before',
    'between': 'between',
    'contains': 'contains',
    'eq': 'eq',
    'gt': 'gt',
    'gte': 'gte',
    'in': 'in',
    'in_window': 'in_window',
    'is_false': 'is_false',
    'is_null': 'is_null',
    'is_true': 'is_true',
    'lt': 'lt',
    'lte': 'lte',
    'neq': 'neq',
    'not_in': 'not_in',
    'not_null': 'not_null',
    'regex': 'regex',
    'starts_with': 'starts_with',
}
BAS_RULE_CONDITION_OP_CODE_VALUES: Final[frozenset[str]] = frozenset(BAS_RULE_CONDITION_OP_CODE)

BAS_FIELD_META_VALUE_TYPE: Final[dict[str, str]] = {
    'bool': 'bool',
    'date': 'date',
    'datetime': 'datetime',
    'decimal': 'decimal',
    'enum': 'enum',
    'int': 'int',
    'json': 'json',
    'ref': 'ref',
    'string': 'string',
}
BAS_FIELD_META_VALUE_TYPE_VALUES: Final[frozenset[str]] = frozenset(BAS_FIELD_META_VALUE_TYPE)

BAS_IE_TEMPLATE_DOMAIN_CODE: Final[dict[str, str]] = {
    'D03': 'D03',
    'D04': 'D04',
    'D06': 'D06',
    'D08': 'D08',
    'D09': '等',
}
BAS_IE_TEMPLATE_DOMAIN_CODE_VALUES: Final[frozenset[str]] = frozenset(BAS_IE_TEMPLATE_DOMAIN_CODE)

BAS_NOTIFY_LOG_MSG_CLASS: Final[dict[str, str]] = {
    'alert': 'alert',
    'consumer': 'consumer',
    'external': 'external',
    'notify': 'notify',
}
BAS_NOTIFY_LOG_MSG_CLASS_VALUES: Final[frozenset[str]] = frozenset(BAS_NOTIFY_LOG_MSG_CLASS)

# ---- oms_gateway ----

GW_PLATFORM_CONFIG_PLATFORM: Final[dict[str, str]] = {
    'douyin': 'douyin',
    'jd': 'jd',
    'kuaishou': 'kuaishou',
    'pdd': 'pdd',
    'taobao': 'taobao',
    'vop': 'vop',
    'wechat': 'wechat',
    'xhs': 'xhs',
}
GW_PLATFORM_CONFIG_PLATFORM_VALUES: Final[frozenset[str]] = frozenset(GW_PLATFORM_CONFIG_PLATFORM)

GW_PLATFORM_CONFIG_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
    'sandbox': '沙箱',
}
GW_PLATFORM_CONFIG_STATUS_VALUES: Final[frozenset[str]] = frozenset(GW_PLATFORM_CONFIG_STATUS)

GW_PLATFORM_CONFIG_SOURCE: Final[dict[str, str]] = {
    'api': 'api',
    'import': 'import',
    'local': 'local',
    'migration': 'migration',
}
GW_PLATFORM_CONFIG_SOURCE_VALUES: Final[frozenset[str]] = frozenset(GW_PLATFORM_CONFIG_SOURCE)

GW_ADAPTER_CONFIG_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
    'gray': '灰度',
}
GW_ADAPTER_CONFIG_STATUS_VALUES: Final[frozenset[str]] = frozenset(GW_ADAPTER_CONFIG_STATUS)

GW_ENUM_MAPPING_MAP_TYPE: Final[dict[str, str]] = {
    'aftersale_reason': 'aftersale_reason',
    'aftersale_status': 'aftersale_status',
    'logistics_code': 'logistics_code',
    'order_status': 'order_status',
}
GW_ENUM_MAPPING_MAP_TYPE_VALUES: Final[frozenset[str]] = frozenset(GW_ENUM_MAPPING_MAP_TYPE)

GW_ENUM_MAPPING_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
GW_ENUM_MAPPING_STATUS_VALUES: Final[frozenset[str]] = frozenset(GW_ENUM_MAPPING_STATUS)

GW_RATELIMIT_CONFIG_SCOPE_TYPE: Final[dict[str, str]] = {
    'app': 'app',
    'method': 'method',
    'platform': 'platform',
    'shop': 'shop',
}
GW_RATELIMIT_CONFIG_SCOPE_TYPE_VALUES: Final[frozenset[str]] = frozenset(GW_RATELIMIT_CONFIG_SCOPE_TYPE)

GW_RATELIMIT_CONFIG_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
GW_RATELIMIT_CONFIG_STATUS_VALUES: Final[frozenset[str]] = frozenset(GW_RATELIMIT_CONFIG_STATUS)

GW_SHOP_PLATFORM: Final[dict[str, str]] = {
    'douyin': 'douyin',
    'jd': 'jd',
    'kuaishou': 'kuaishou',
    'pdd': 'pdd',
    'taobao': 'taobao',
    'vop': 'vop',
    'wechat': 'wechat',
    'xhs': 'xhs',
}
GW_SHOP_PLATFORM_VALUES: Final[frozenset[str]] = frozenset(GW_SHOP_PLATFORM)

GW_SHOP_SHOP_TYPE: Final[dict[str, str]] = {
    'dealer': '经销',
    'direct': '直营',
    'flagship': '旗舰店',
    'franchise': '加盟',
    'store': '门店O2O',
}
GW_SHOP_SHOP_TYPE_VALUES: Final[frozenset[str]] = frozenset(GW_SHOP_SHOP_TYPE)

GW_SHOP_BUSINESS_TYPE: Final[dict[str, str]] = {
    'dealer': '经销',
    'direct_sale': '直销',
    'distribution': '分销',
}
GW_SHOP_BUSINESS_TYPE_VALUES: Final[frozenset[str]] = frozenset(GW_SHOP_BUSINESS_TYPE)

GW_SHOP_AUTH_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'expired': '过期',
    'normal': '正常',
    'pending': '待授权',
}
GW_SHOP_AUTH_STATUS_VALUES: Final[frozenset[str]] = frozenset(GW_SHOP_AUTH_STATUS)

GW_SHOP_AUTH_MODE: Final[dict[str, str]] = {
    'agent': '代授权',
    'self': '自助',
}
GW_SHOP_AUTH_MODE_VALUES: Final[frozenset[str]] = frozenset(GW_SHOP_AUTH_MODE)

GW_SHOP_AUTH_URL_TRACK: Final[dict[str, str]] = {
    'clicked': '已点击',
    'done': '已完成',
    'sent': '已发送',
}
GW_SHOP_AUTH_URL_TRACK_VALUES: Final[frozenset[str]] = frozenset(GW_SHOP_AUTH_URL_TRACK)

GW_SHOP_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
GW_SHOP_STATUS_VALUES: Final[frozenset[str]] = frozenset(GW_SHOP_STATUS)

GW_SHOP_SOURCE: Final[dict[str, str]] = {
    'api': 'api',
    'import': 'import',
    'local': 'local',
    'migration': 'migration',
}
GW_SHOP_SOURCE_VALUES: Final[frozenset[str]] = frozenset(GW_SHOP_SOURCE)

GW_SHOP_AUTH_SESSION_ENC: Final[dict[str, str]] = {
    'cookie': '凭证密文',
    'session': 'session',
}
GW_SHOP_AUTH_SESSION_ENC_VALUES: Final[frozenset[str]] = frozenset(GW_SHOP_AUTH_SESSION_ENC)

oms_gateway_GW_SHOP_AUTH_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'expired': '过期',
    'normal': '正常',
    'pending': '待授权',
}
oms_gateway_GW_SHOP_AUTH_STATUS_VALUES: Final[frozenset[str]] = frozenset(oms_gateway_GW_SHOP_AUTH_STATUS)

GW_SHOP_CONFIG_BACK_NODE: Final[dict[str, str]] = {
    'print': '打印时',
    'shipped': '发货时',
    'verify': '验货时',
}
GW_SHOP_CONFIG_BACK_NODE_VALUES: Final[frozenset[str]] = frozenset(GW_SHOP_CONFIG_BACK_NODE)

GW_CREDENTIAL_AUDIT_ACTION: Final[dict[str, str]] = {
    'reauth': '重授权',
    'refresh': '续期',
    'revoke': '吊销',
    'use': '取用',
}
GW_CREDENTIAL_AUDIT_ACTION_VALUES: Final[frozenset[str]] = frozenset(GW_CREDENTIAL_AUDIT_ACTION)

GW_CREDENTIAL_AUDIT_RESULT: Final[dict[str, str]] = {
    'denied': '拒绝',
    'fail': '失败',
    'succ': '成功',
}
GW_CREDENTIAL_AUDIT_RESULT_VALUES: Final[frozenset[str]] = frozenset(GW_CREDENTIAL_AUDIT_RESULT)

GW_API_LOG_ERR_LEVEL: Final[dict[str, str]] = {
    'AUTH': '需授权',
    'FATAL': '停重试',
    'MANUAL': '需人工',
    'RATE_LIMITED': '退避限流',
    'RETRYABLE': '可重试',
}
GW_API_LOG_ERR_LEVEL_VALUES: Final[frozenset[str]] = frozenset(GW_API_LOG_ERR_LEVEL)

GW_API_LOG_SOURCE: Final[dict[str, str]] = {
    'passthrough': '透传',
    'pull': '拉单',
    'reconcile': '对账',
    'retry': '重试',
    'writeback': '回传',
}
GW_API_LOG_SOURCE_VALUES: Final[frozenset[str]] = frozenset(GW_API_LOG_SOURCE)

GW_RPC_PENDING_STATUS: Final[dict[str, str]] = {
    'pending': '在途',
    'to_fail': '已转失败',
    'verified': '已核实',
}
GW_RPC_PENDING_STATUS_VALUES: Final[frozenset[str]] = frozenset(GW_RPC_PENDING_STATUS)

GW_API_FAIL_OBJ_TYPE: Final[dict[str, str]] = {
    'aftersale': 'aftersale',
    'delivery': 'delivery',
    'order_buffer': 'order_buffer',
    'order_pull': 'order_pull',
    'stock_batch': 'stock_batch',
    'writeback': '等',
}
GW_API_FAIL_OBJ_TYPE_VALUES: Final[frozenset[str]] = frozenset(GW_API_FAIL_OBJ_TYPE)

GW_API_FAIL_ERR_LEVEL: Final[dict[str, str]] = {
    'AUTH': 'AUTH',
    'FATAL': 'FATAL',
    'MANUAL': 'MANUAL',
    'RATE_LIMITED': 'RATE_LIMITED',
    'RETRYABLE': 'RETRYABLE',
}
GW_API_FAIL_ERR_LEVEL_VALUES: Final[frozenset[str]] = frozenset(GW_API_FAIL_ERR_LEVEL)

GW_API_FAIL_STATUS: Final[dict[str, str]] = {
    'dead': '死信',
    'deleted': '终态清理',
    'manual': '转人工',
    'retrying': '重试中',
    'succ': '成功',
    'suspended': '店铺挂起',
    'waiting': '等待',
}
GW_API_FAIL_STATUS_VALUES: Final[frozenset[str]] = frozenset(GW_API_FAIL_STATUS)

GW_API_FAIL_RESOLVED_BY: Final[dict[str, str]] = {
    'biz_closed': '业务关闭',
    'manual': '人工',
    'reconcile': '反查已生效',
    'retry': '重试成功',
}
GW_API_FAIL_RESOLVED_BY_VALUES: Final[frozenset[str]] = frozenset(GW_API_FAIL_RESOLVED_BY)

GW_ERRCODE_DICT_ERR_LEVEL: Final[dict[str, str]] = {
    'AUTH': '需重新授权',
    'FATAL': '停止重试',
    'MANUAL': '需人工',
    'RATE_LIMITED': '退避限流',
    'RETRYABLE': '可重试',
}
GW_ERRCODE_DICT_ERR_LEVEL_VALUES: Final[frozenset[str]] = frozenset(GW_ERRCODE_DICT_ERR_LEVEL)

GW_ERRCODE_DICT_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
GW_ERRCODE_DICT_STATUS_VALUES: Final[frozenset[str]] = frozenset(GW_ERRCODE_DICT_STATUS)

GW_ORDER_BUFFER_CANONICAL_STATUS: Final[dict[str, str]] = {
    'closed': '已关闭',
    'finished': '已完成',
    'shipped': '已发货',
    'unpaid': '待付款',
    'unshipped': '待发货',
}
GW_ORDER_BUFFER_CANONICAL_STATUS_VALUES: Final[frozenset[str]] = frozenset(GW_ORDER_BUFFER_CANONICAL_STATUS)

GW_ORDER_BUFFER_RECEIVER_ENCRYPTED_CHANNEL: Final[dict[str, str]] = {
    'none': '明文',
    'oaid': '平台密文',
    'virtual': '虚拟号',
}
GW_ORDER_BUFFER_RECEIVER_ENCRYPTED_CHANNEL_VALUES: Final[frozenset[str]] = frozenset(GW_ORDER_BUFFER_RECEIVER_ENCRYPTED_CHANNEL)

GW_ORDER_BUFFER_DELIVER_STATUS: Final[dict[str, str]] = {
    'accepted': '已接收',
    'closed': '已关闭',
    'delivered': '已投递',
    'fail': '投递失败',
    'manual': '人工处理',
    'pending': '待投递',
    'waiting': '建档等待',
}
GW_ORDER_BUFFER_DELIVER_STATUS_VALUES: Final[frozenset[str]] = frozenset(GW_ORDER_BUFFER_DELIVER_STATUS)

GW_ORDER_BUFFER_SOURCE: Final[dict[str, str]] = {
    'api': 'api',
    'import': 'import',
    'local': 'local',
    'migration': 'migration',
}
GW_ORDER_BUFFER_SOURCE_VALUES: Final[frozenset[str]] = frozenset(GW_ORDER_BUFFER_SOURCE)

GW_ORDER_BUFFER_ITEM_REFUND_STATUS: Final[dict[str, str]] = {
    'none': '无',
    'refunded': '已退款',
    'refunding': '退款中',
}
GW_ORDER_BUFFER_ITEM_REFUND_STATUS_VALUES: Final[frozenset[str]] = frozenset(GW_ORDER_BUFFER_ITEM_REFUND_STATUS)

GW_ORDER_BUFFER_PROMOTION_PROMOTION_TYPE: Final[dict[str, str]] = {
    'full_reduce': '满减',
    'platform_coupon': '平台券',
    'shop_coupon': '店铺券',
    'subsidy': '补贴',
}
GW_ORDER_BUFFER_PROMOTION_PROMOTION_TYPE_VALUES: Final[frozenset[str]] = frozenset(GW_ORDER_BUFFER_PROMOTION_PROMOTION_TYPE)

GW_ORDER_BUFFER_PROMOTION_BEAR_BY: Final[dict[str, str]] = {
    'merchant': '商家',
    'mixed': '混合',
    'platform': '平台',
}
GW_ORDER_BUFFER_PROMOTION_BEAR_BY_VALUES: Final[frozenset[str]] = frozenset(GW_ORDER_BUFFER_PROMOTION_BEAR_BY)

GW_MSG_NOTIFY_MSG_TYPE: Final[dict[str, str]] = {
    'aftersale': '售后',
    'other': '其他',
    'product': '商品',
    'trade': '订单',
    'trade_close': 'trade_close',
}
GW_MSG_NOTIFY_MSG_TYPE_VALUES: Final[frozenset[str]] = frozenset(GW_MSG_NOTIFY_MSG_TYPE)

GW_MSG_NOTIFY_ROUTE_TARGET: Final[dict[str, str]] = {
    'aftersale': '售后域',
    'order': '订单域',
    'product': '商品域',
    'unknown': '未知',
}
GW_MSG_NOTIFY_ROUTE_TARGET_VALUES: Final[frozenset[str]] = frozenset(GW_MSG_NOTIFY_ROUTE_TARGET)

GW_MSG_NOTIFY_STATUS: Final[dict[str, str]] = {
    'dead': '死信',
    'fail': '失败',
    'pending': '待消费',
    'processing': '消费中',
    'succ': '成功',
}
GW_MSG_NOTIFY_STATUS_VALUES: Final[frozenset[str]] = frozenset(GW_MSG_NOTIFY_STATUS)

GW_PULL_WATERMARK_CHANNEL: Final[dict[str, str]] = {
    'aftersale': '售后',
    'order': '订单',
    'refund': '退款',
}
GW_PULL_WATERMARK_CHANNEL_VALUES: Final[frozenset[str]] = frozenset(GW_PULL_WATERMARK_CHANNEL)

GW_WRITEBACK_TASK_SYNC_TYPE: Final[dict[str, str]] = {
    'aftersale': '售后',
    'delivery': '发货',
    'lifecycle': '生命周期',
    'stock': '库存',
}
GW_WRITEBACK_TASK_SYNC_TYPE_VALUES: Final[frozenset[str]] = frozenset(GW_WRITEBACK_TASK_SYNC_TYPE)

GW_WRITEBACK_TASK_ACTION: Final[dict[str, str]] = {
    'agree_refund': 'agree_refund',
    'cancel': '等',
    'confirm_receive': 'confirm_receive',
    'resend': 'resend',
    'send': 'send',
}
GW_WRITEBACK_TASK_ACTION_VALUES: Final[frozenset[str]] = frozenset(GW_WRITEBACK_TASK_ACTION)

GW_WRITEBACK_TASK_BACK_NODE: Final[dict[str, str]] = {
    'print': '打印',
    'shipped': '发货',
    'verify': '验货',
}
GW_WRITEBACK_TASK_BACK_NODE_VALUES: Final[frozenset[str]] = frozenset(GW_WRITEBACK_TASK_BACK_NODE)

GW_WRITEBACK_TASK_STATUS: Final[dict[str, str]] = {
    'fail_pending': '失败待重试',
    'manual': '转人工',
    'pending': '待处理',
    'processing': '处理中',
    'retrying': '重试中',
    'skipped': '跳过',
    'succ': '成功',
}
GW_WRITEBACK_TASK_STATUS_VALUES: Final[frozenset[str]] = frozenset(GW_WRITEBACK_TASK_STATUS)

GW_WRITEBACK_TASK_ERR_LEVEL: Final[dict[str, str]] = {
    'AUTH': 'AUTH',
    'FATAL': 'FATAL',
    'MANUAL': 'MANUAL',
    'RATE_LIMITED': 'RATE_LIMITED',
    'RETRYABLE': 'RETRYABLE',
}
GW_WRITEBACK_TASK_ERR_LEVEL_VALUES: Final[frozenset[str]] = frozenset(GW_WRITEBACK_TASK_ERR_LEVEL)

GW_STOCK_SYNC_BATCH_STATUS: Final[dict[str, str]] = {
    'done': '完成',
    'partial': '部分失败',
    'running': '进行中',
}
GW_STOCK_SYNC_BATCH_STATUS_VALUES: Final[frozenset[str]] = frozenset(GW_STOCK_SYNC_BATCH_STATUS)

GW_STOCK_SYNC_ITEM_STATUS: Final[dict[str, str]] = {
    'fail': '失败',
    'pending': '待同步',
    'skipped': '跳过',
    'succ': '成功',
}
GW_STOCK_SYNC_ITEM_STATUS_VALUES: Final[frozenset[str]] = frozenset(GW_STOCK_SYNC_ITEM_STATUS)

GW_RECON_DIFF_RECONCILE_TYPE: Final[dict[str, str]] = {
    'aftersale': '售后',
    'delivery': '发货',
    'order_missing': '漏单',
    'stock': '库存',
}
GW_RECON_DIFF_RECONCILE_TYPE_VALUES: Final[frozenset[str]] = frozenset(GW_RECON_DIFF_RECONCILE_TYPE)

GW_RECON_DIFF_RESULT: Final[dict[str, str]] = {
    'consistent': '一致',
    'fixed': '差异已修正',
    'repull': '漏单补拉',
    'to_manual': '差异转人工',
}
GW_RECON_DIFF_RESULT_VALUES: Final[frozenset[str]] = frozenset(GW_RECON_DIFF_RESULT)

GW_OPENAPI_APP_QUOTA_LEVEL: Final[dict[str, str]] = {
    'basic': 'basic',
    'premium': 'premium',
    'standard': 'standard',
}
GW_OPENAPI_APP_QUOTA_LEVEL_VALUES: Final[frozenset[str]] = frozenset(GW_OPENAPI_APP_QUOTA_LEVEL)

GW_OPENAPI_APP_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
GW_OPENAPI_APP_STATUS_VALUES: Final[frozenset[str]] = frozenset(GW_OPENAPI_APP_STATUS)

GW_OPENAPI_APP_AUDIT_STATUS: Final[dict[str, str]] = {
    'approved': '通过',
    'pending': '待审',
    'rejected': '驳回',
}
GW_OPENAPI_APP_AUDIT_STATUS_VALUES: Final[frozenset[str]] = frozenset(GW_OPENAPI_APP_AUDIT_STATUS)

GW_OPENAPI_REGISTER_DOMAIN: Final[dict[str, str]] = {
    'aftersale': 'aftersale',
    'order': 'order',
    'shop': 'shop',
    'stock': 'stock',
}
GW_OPENAPI_REGISTER_DOMAIN_VALUES: Final[frozenset[str]] = frozenset(GW_OPENAPI_REGISTER_DOMAIN)

GW_OPENAPI_REGISTER_RW_TYPE: Final[dict[str, str]] = {
    'read': 'read',
    'write': 'write',
}
GW_OPENAPI_REGISTER_RW_TYPE_VALUES: Final[frozenset[str]] = frozenset(GW_OPENAPI_REGISTER_RW_TYPE)

GW_OPENAPI_REGISTER_QUOTA_LEVEL: Final[dict[str, str]] = {
    'basic': 'basic',
    'premium': 'premium',
    'standard': 'standard',
}
GW_OPENAPI_REGISTER_QUOTA_LEVEL_VALUES: Final[frozenset[str]] = frozenset(GW_OPENAPI_REGISTER_QUOTA_LEVEL)

GW_OPENAPI_REGISTER_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
GW_OPENAPI_REGISTER_STATUS_VALUES: Final[frozenset[str]] = frozenset(GW_OPENAPI_REGISTER_STATUS)

GW_OPENAPI_LOG_RESULT: Final[dict[str, str]] = {
    'denied': '拒绝',
    'fail': '失败',
    'succ': '成功',
}
GW_OPENAPI_LOG_RESULT_VALUES: Final[frozenset[str]] = frozenset(GW_OPENAPI_LOG_RESULT)

# ---- oms_order ----

ORD_ORDER_CREATEWAY: Final[dict[str, str]] = {
    'after': '补发',
    'b2b': '经销',
    'exchange': '换货',
    'import': '导入',
    'local': '手工',
    'platform': '平台',
}
ORD_ORDER_CREATEWAY_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_CREATEWAY)

ORD_ORDER_ORDER_TYPE: Final[dict[str, str]] = {
    'exchange': '换货',
    'groupon': '团购',
    'luckybag': '福袋',
    'normal': '普通',
    'presale': '预售',
    'reship': '补发',
    'virtual': '虚拟',
}
ORD_ORDER_ORDER_TYPE_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_ORDER_TYPE)

ORD_ORDER_ORDER_STATUS: Final[dict[str, str]] = {
    'cancelled': '已取消',
    'finished': '已完成',
    'processing': '进行中',
}
ORD_ORDER_ORDER_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_ORDER_STATUS)

ORD_ORDER_AUDIT_STATUS: Final[dict[str, str]] = {
    'passed': '已审核',
    'pending': '待审核',
    'rejected': '驳回',
    'retrial': '复审中',
}
ORD_ORDER_AUDIT_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_AUDIT_STATUS)

ORD_ORDER_FULFILL_STATUS: Final[dict[str, str]] = {
    'finished': '完成',
    'fulfilling': '履约中',
    'partial_shipped': '部分发货',
    'pending': '待履约',
    'shipped': '已发货',
}
ORD_ORDER_FULFILL_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_FULFILL_STATUS)

ORD_ORDER_PAY_STATUS: Final[dict[str, str]] = {
    'full_refund': '全额退款',
    'paid': '已支付',
    'partial': '部分支付',
    'partial_refund': '部分退款',
    'refunding': '退款中',
    'unpaid': '未支付',
}
ORD_ORDER_PAY_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_PAY_STATUS)

ORD_ORDER_SHIP_STATUS: Final[dict[str, str]] = {
    'partial': '部分发货',
    'partial_return': '部分退货',
    'returned': '已退货',
    'shipped': '已发货',
    'unshipped': '未发货',
}
ORD_ORDER_SHIP_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_SHIP_STATUS)

ORD_ORDER_PROMOTION_SOURCE: Final[dict[str, str]] = {
    'live': '直播带货',
    'organic': '自然流量',
    'other': '其他',
    'private': '私域',
    'taoke': '淘客联盟',
}
ORD_ORDER_PROMOTION_SOURCE_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_PROMOTION_SOURCE)

ORD_ORDER_CROSS_BORDER_TYPE: Final[dict[str, str]] = {
    'NULL': '无',
    'bonded': '保税',
    'direct': '直邮',
}
ORD_ORDER_CROSS_BORDER_TYPE_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_CROSS_BORDER_TYPE)

ORD_ORDER_DECLARE_STATUS: Final[dict[str, str]] = {
    'declaring': '申报中',
    'exported': '已出区',
    'failed': '申报失败',
    'none': '无需申报',
    'refund_declare': '退单申报',
    'released': '放行',
    'returned': '已退单',
    'wait': '待申报',
}
ORD_ORDER_DECLARE_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_DECLARE_STATUS)

ORD_ORDER_ARCHIVE_FLAG: Final[dict[str, str]] = {
    'archived': '已归档',
    'online': '在线',
    'recalled': '已回捞',
}
ORD_ORDER_ARCHIVE_FLAG_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_ARCHIVE_FLAG)

ORD_ORDER_SOURCE: Final[dict[str, str]] = {
    'api': 'api',
    'import': 'import',
    'local': 'local',
    'migration': 'migration',
}
ORD_ORDER_SOURCE_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_SOURCE)

ORD_ORDER_ITEM_PARSE_STATUS: Final[dict[str, str]] = {
    'failed': '解析失败',
    'parsed': '已解析',
    'pending': '待解析',
}
ORD_ORDER_ITEM_PARSE_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_ITEM_PARSE_STATUS)

ORD_ORDER_PMT_PMT_TYPE: Final[dict[str, str]] = {
    'freight_coupon': '运费券',
    'item_discount': '单品直降',
    'other': '其他',
    'platform_coupon': '平台券',
    'shop_full_reduce': '店铺满减',
}
ORD_ORDER_PMT_PMT_TYPE_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_PMT_PMT_TYPE)

ORD_ORDER_PMT_BEARER: Final[dict[str, str]] = {
    'platform': '平台',
    'shop': '商家',
}
ORD_ORDER_PMT_BEARER_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_PMT_BEARER)

ORD_ORDER_INVOICE_INVOICE_TYPE: Final[dict[str, str]] = {
    'e_normal': '电子普票',
    'paper': '纸质普票',
    'special': '专票',
}
ORD_ORDER_INVOICE_INVOICE_TYPE_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_INVOICE_INVOICE_TYPE)

ORD_ORDER_INVOICE_TITLE_TYPE: Final[dict[str, str]] = {
    'company': '企业',
    'personal': '个人',
}
ORD_ORDER_INVOICE_TITLE_TYPE_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_INVOICE_TITLE_TYPE)

ORD_ORDER_INVOICE_INVOICE_STATUS: Final[dict[str, str]] = {
    'applied': '已申请',
    'failed': '开票失败',
    'issued': '已开票',
    'issuing': '开票中',
}
ORD_ORDER_INVOICE_INVOICE_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_INVOICE_INVOICE_STATUS)

ORD_STATUS_LOG_STATUS_DOMAIN: Final[dict[str, str]] = {
    'audit': '审核',
    'fulfill': '履约',
    'order': '总开关',
    'pay': '支付',
    'ship': '发货',
}
ORD_STATUS_LOG_STATUS_DOMAIN_VALUES: Final[frozenset[str]] = frozenset(ORD_STATUS_LOG_STATUS_DOMAIN)

ORD_ORDER_FAIL_FAIL_CODE: Final[dict[str, str]] = {
    'AMOUNT_MISMATCH': '金额勾稽超差',
    'AUTH_EXPIRED': '授权过期',
    'ITEM_EMPTY': '商品行空',
    'REQUIRED_MISSING': '必填缺失',
    'SHOP_INVALID': '店铺无效',
}
ORD_ORDER_FAIL_FAIL_CODE_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_FAIL_FAIL_CODE)

ORD_ORDER_FAIL_HANDLE_STATUS: Final[dict[str, str]] = {
    'ignored': '已忽略',
    'pending': '待处理',
    'repushed': '已修复重推',
}
ORD_ORDER_FAIL_HANDLE_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_FAIL_HANDLE_STATUS)

ORD_AUDIT_RULE_PASS_ACTION: Final[dict[str, str]] = {
    'draft_confirm': '仅决策转人工确认',
    'exec_plan': '生成plan执行',
}
ORD_AUDIT_RULE_PASS_ACTION_VALUES: Final[frozenset[str]] = frozenset(ORD_AUDIT_RULE_PASS_ACTION)

ORD_AUDIT_RULE_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
ORD_AUDIT_RULE_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_AUDIT_RULE_STATUS)

ORD_FULFILL_PLAN_PLAN_STATUS: Final[dict[str, str]] = {
    'discarded': '已废弃',
    'draft': '草稿',
    'pending': '待执行',
}
ORD_FULFILL_PLAN_PLAN_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_FULFILL_PLAN_PLAN_STATUS)

ORD_FULFILL_PLAN_EXEC_STATUS: Final[dict[str, str]] = {
    'executing': '执行中',
    'failed_compensated': '失败已补偿',
    'partial': '部分成功',
    'success': '成功',
    'waiting': '待执行',
}
ORD_FULFILL_PLAN_EXEC_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_FULFILL_PLAN_EXEC_STATUS)

ORD_FULFILL_PLAN_FAIL_CODE: Final[dict[str, str]] = {
    'DELIVERY_CREATE_FAIL': 'DELIVERY_CREATE_FAIL',
    'RESERVE_FAIL': 'RESERVE_FAIL',
    'STOCK_RACE': '库存竞态',
}
ORD_FULFILL_PLAN_FAIL_CODE_VALUES: Final[frozenset[str]] = frozenset(ORD_FULFILL_PLAN_FAIL_CODE)

ORD_AUDIT_REASON_PLUGIN_NAME: Final[dict[str, str]] = {
    'address_check': 'address_check',
    'admit_pay': 'admit_pay',
    'admit_special': 'admit_special',
    'admit_status': 'admit_status',
    'amount_check': 'amount_check',
    'auto_pass': 'auto_pass',
    'blacklist': 'blacklist',
    'branch_select': 'branch_select',
    'combine_check': 'combine_check',
    'gift_check': 'gift_check',
    'goods_match': 'goods_match',
    'invoice_check': 'invoice_check',
    'label_mark': 'label_mark',
    'logi_match': 'logi_match',
    'memo_flag': 'memo_flag',
    'price_check': 'price_check',
    'routernum': 'routernum',
    'split': 'split',
    'stock_check': 'stock_check',
}
ORD_AUDIT_REASON_PLUGIN_NAME_VALUES: Final[frozenset[str]] = frozenset(ORD_AUDIT_REASON_PLUGIN_NAME)

ORD_AUDIT_REASON_LEVEL: Final[dict[str, str]] = {
    'BLOCK': '拦截',
    'WARN': '提示',
}
ORD_AUDIT_REASON_LEVEL_VALUES: Final[frozenset[str]] = frozenset(ORD_AUDIT_REASON_LEVEL)

ORD_AUDIT_REASON_SUGGEST_ACTION: Final[dict[str, str]] = {
    'change_branch': '换仓',
    'contact_buyer': '联系买家',
    'modify_address': '改地址',
    'reship': '补发',
    'to_retrial': '转复审',
    'wait_restock': '等补货',
}
ORD_AUDIT_REASON_SUGGEST_ACTION_VALUES: Final[frozenset[str]] = frozenset(ORD_AUDIT_REASON_SUGGEST_ACTION)

ORD_AUDIT_REASON_ROUTE_TARGET: Final[dict[str, str]] = {
    'manual': '人工',
    'requeue': '回池',
    'retrial': '复审',
    'shortage': '缺货',
    'suspend': '挂起',
}
ORD_AUDIT_REASON_ROUTE_TARGET_VALUES: Final[frozenset[str]] = frozenset(ORD_AUDIT_REASON_ROUTE_TARGET)

ORD_AUDIT_REASON_HANDLE_STATUS: Final[dict[str, str]] = {
    'handled': '已处理',
    'open': '未处理',
}
ORD_AUDIT_REASON_HANDLE_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_AUDIT_REASON_HANDLE_STATUS)

ORD_AUDIT_PLUGIN_PERF_PHASE: Final[dict[str, str]] = {
    'ADMIT': '准入',
    'CHECK': '校验',
    'LOGISTICS': '物流',
    'STOCK': '库存',
    'WAREHOUSE': '仓',
}
ORD_AUDIT_PLUGIN_PERF_PHASE_VALUES: Final[frozenset[str]] = frozenset(ORD_AUDIT_PLUGIN_PERF_PHASE)

ORD_AUDIT_PLUGIN_PERF_RESULT: Final[dict[str, str]] = {
    'ERROR': '异常',
    'HOLD': '挂起',
    'MUTATE': '数据变更',
    'PASS': '通过',
    'SHORT_CIRCUIT': '短路',
}
ORD_AUDIT_PLUGIN_PERF_RESULT_VALUES: Final[frozenset[str]] = frozenset(ORD_AUDIT_PLUGIN_PERF_RESULT)

ORD_DISPATCH_RULE_STRATEGY: Final[dict[str, str]] = {
    'least_task': '最少任务',
    'round_robin': '轮询',
}
ORD_DISPATCH_RULE_STRATEGY_VALUES: Final[frozenset[str]] = frozenset(ORD_DISPATCH_RULE_STRATEGY)

ORD_DISPATCH_RULE_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
ORD_DISPATCH_RULE_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_DISPATCH_RULE_STATUS)

ORD_AUDIT_GROUP_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
ORD_AUDIT_GROUP_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_AUDIT_GROUP_STATUS)

ORD_AUDIT_TASK_ASSIGN_WAY: Final[dict[str, str]] = {
    'manual': '手动指派',
    'recycle': '回收重分',
    'rule': '规则',
    'transfer': '转派',
}
ORD_AUDIT_TASK_ASSIGN_WAY_VALUES: Final[frozenset[str]] = frozenset(ORD_AUDIT_TASK_ASSIGN_WAY)

ORD_AUDIT_TASK_TASK_STATUS: Final[dict[str, str]] = {
    'assigned': '已分派',
    'executing': '执行中',
    'finished': '已完结',
    'processing': '处理中',
    'rejected': '已驳回',
    'skip_approving': '跳过审批中',
    'transferred': '转出',
    'wait_assign': '待分派',
}
ORD_AUDIT_TASK_TASK_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_AUDIT_TASK_TASK_STATUS)

ORD_AUDIT_TASK_RESULT: Final[dict[str, str]] = {
    'passed': '通过',
    'rejected': '驳回',
    'skipped': '跳过',
    'transferred': '转出',
}
ORD_AUDIT_TASK_RESULT_VALUES: Final[frozenset[str]] = frozenset(ORD_AUDIT_TASK_RESULT)

ORD_AUDIT_WORK_LOG_ACTION: Final[dict[str, str]] = {
    'assign': '分派',
    'batch_item': '批量项',
    'batch_pass': '批量通过',
    'dispatch': '指派',
    'open': '打开',
    'pass': '通过',
    'recycle': '回收',
    'reject': '驳回',
    'skip': '跳过',
    'transfer': '转派',
}
ORD_AUDIT_WORK_LOG_ACTION_VALUES: Final[frozenset[str]] = frozenset(ORD_AUDIT_WORK_LOG_ACTION)

ORD_SPLIT_RULE_SPLIT_TYPE: Final[dict[str, str]] = {
    'branch': '按仓',
    'cascade': '级联编排器',
    'channel': '渠道',
    'customer_classify': '客户分类',
    'gift_separate': '赠品分离',
    'goods_type': '实物虚拟',
    'order_host': '平台子单',
    'owner': '按货主',
    'presale': '预售现货',
    'sku': '按SKU',
    'sku_category': '商品分类',
    'stock_depth': '库存深度',
    'store': '门店',
    'virtual_sku': '虚拟SKU',
    'volume': '体积',
    'weight': '重量',
}
ORD_SPLIT_RULE_SPLIT_TYPE_VALUES: Final[frozenset[str]] = frozenset(ORD_SPLIT_RULE_SPLIT_TYPE)

ORD_SPLIT_RULE_SCOPE_TYPE: Final[dict[str, str]] = {
    'global': '全局',
    'order_group': '订单分组',
    'shop': '店铺',
}
ORD_SPLIT_RULE_SCOPE_TYPE_VALUES: Final[frozenset[str]] = frozenset(ORD_SPLIT_RULE_SCOPE_TYPE)

ORD_SPLIT_RULE_CONFIRM_SOURCE: Final[dict[str, str]] = {
    'all': '全部',
    'auto': '自动',
    'manual': '手工',
}
ORD_SPLIT_RULE_CONFIRM_SOURCE_VALUES: Final[frozenset[str]] = frozenset(ORD_SPLIT_RULE_CONFIRM_SOURCE)

ORD_SPLIT_RULE_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
ORD_SPLIT_RULE_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_SPLIT_RULE_STATUS)

ORD_SPLIT_TRACE_SOURCE: Final[dict[str, str]] = {
    'auto': '自动',
    'manual': '手工',
}
ORD_SPLIT_TRACE_SOURCE_VALUES: Final[frozenset[str]] = frozenset(ORD_SPLIT_TRACE_SOURCE)

ORD_SPLIT_TRACE_RESULT_STATUS: Final[dict[str, str]] = {
    'fail': '失败',
    'success': '成功',
}
ORD_SPLIT_TRACE_RESULT_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_SPLIT_TRACE_RESULT_STATUS)

ORD_SPLIT_TRACE_ERR_CODE: Final[dict[str, str]] = {
    'CONFIG_INVALID': 'CONFIG_INVALID',
    'CONSERVATION_VIOLATION': 'CONSERVATION_VIOLATION',
    'NO_STOCK': 'NO_STOCK',
    'PRECONDITION_UNMET': 'PRECONDITION_UNMET',
}
ORD_SPLIT_TRACE_ERR_CODE_VALUES: Final[frozenset[str]] = frozenset(ORD_SPLIT_TRACE_ERR_CODE)

ORD_COMBINE_GROUP_STATUS: Final[dict[str, str]] = {
    'grouping': '聚组中',
    'hold': '等待',
    'merged': '已merge',
    'sealed': '已封窗',
    'split_back': '已拆回',
    'voided': '已作废',
}
ORD_COMBINE_GROUP_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_COMBINE_GROUP_STATUS)

ORD_COMBINE_GROUP_SOURCE: Final[dict[str, str]] = {
    'auto': '自动',
    'manual': '手工',
}
ORD_COMBINE_GROUP_SOURCE_VALUES: Final[frozenset[str]] = frozenset(ORD_COMBINE_GROUP_SOURCE)

ORD_COMBINE_BLACKLIST_LEVEL: Final[dict[str, str]] = {
    'platform': '平台',
    'shop_type': '店铺类型',
    'tag': '标签',
}
ORD_COMBINE_BLACKLIST_LEVEL_VALUES: Final[frozenset[str]] = frozenset(ORD_COMBINE_BLACKLIST_LEVEL)

ORD_COMBINE_BLACKLIST_RULE: Final[dict[str, str]] = {
    'forbid': '禁合',
    'same_tag_only': '仅同标签合',
}
ORD_COMBINE_BLACKLIST_RULE_VALUES: Final[frozenset[str]] = frozenset(ORD_COMBINE_BLACKLIST_RULE)

ORD_DISPATCH_PLAN_MODE: Final[dict[str, str]] = {
    'appointed': '指定仓',
    'lack': '缺货',
    'multi': '多仓',
    'single': '整仓',
}
ORD_DISPATCH_PLAN_MODE_VALUES: Final[frozenset[str]] = frozenset(ORD_DISPATCH_PLAN_MODE)

ORD_DISPATCH_PLAN_SOURCE: Final[dict[str, str]] = {
    'auto': '自动',
    'manual': '改仓',
    'platform': '平台指定仓',
    'retry': '换仓重试',
}
ORD_DISPATCH_PLAN_SOURCE_VALUES: Final[frozenset[str]] = frozenset(ORD_DISPATCH_PLAN_SOURCE)

ORD_DISPATCH_PLAN_STATUS: Final[dict[str, str]] = {
    'effective': '生效',
    'superseded': '已被替代',
}
ORD_DISPATCH_PLAN_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_DISPATCH_PLAN_STATUS)

ORD_DISPATCH_PLAN_LACK_ROUTE: Final[dict[str, str]] = {
    'lend_suggest': '借调建议',
    'retry_branch': '换仓重试中',
    'to_shortage': '转缺货',
}
ORD_DISPATCH_PLAN_LACK_ROUTE_VALUES: Final[frozenset[str]] = frozenset(ORD_DISPATCH_PLAN_LACK_ROUTE)

ORD_BRANCH_DISPATCH_RULE_STRATEGY_TYPE: Final[dict[str, str]] = {
    'binding_priority': '店铺绑定优先',
    'owner_assign': '货主指定',
    'region_route': '区域路由',
    'round_robin': '轮询',
    'stock_depth': '库存深度',
    'store_o2o': '门店分单',
}
ORD_BRANCH_DISPATCH_RULE_STRATEGY_TYPE_VALUES: Final[frozenset[str]] = frozenset(ORD_BRANCH_DISPATCH_RULE_STRATEGY_TYPE)

ORD_BRANCH_DISPATCH_RULE_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
ORD_BRANCH_DISPATCH_RULE_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_BRANCH_DISPATCH_RULE_STATUS)

ORD_DELIVERY_STATUS: Final[dict[str, str]] = {
    'cancelled': '已取消',
    'draft': '草稿',
    'finished': '已完结',
    'outbound': '已出库',
    'partial_outbound': '部分出库',
    'processing': '作业中',
    'push_failed': '推送失败',
    'pushed': '已推送',
    'recalled': '已叫回',
    'recalling': '叫回中',
    'rejected': '已打回',
    'shipped': '已发货确认',
}
ORD_DELIVERY_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_DELIVERY_STATUS)

ORD_DELIVERY_SYNC_STATUS: Final[dict[str, str]] = {
    'fail': '失败',
    'init': '未推',
    'no_need': '无需推仓',
    'success': '成功',
}
ORD_DELIVERY_SYNC_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_DELIVERY_SYNC_STATUS)

ORD_DELIVERY_SOURCE: Final[dict[str, str]] = {
    'auto': '自动',
    'manual': '人工',
    'store': '门店',
    'virtual': '虚拟',
}
ORD_DELIVERY_SOURCE_VALUES: Final[frozenset[str]] = frozenset(ORD_DELIVERY_SOURCE)

ORD_DELIVERY_LOG_COMMAND: Final[dict[str, str]] = {
    'cancel': '取消',
    'confirm': '发货确认',
    'finish': '完结',
    'outbound_callback': '出库回传',
    'push': '推送',
    'recall': '叫回',
    'reject': '打回',
    'resume': '恢复',
}
ORD_DELIVERY_LOG_COMMAND_VALUES: Final[frozenset[str]] = frozenset(ORD_DELIVERY_LOG_COMMAND)

ORD_DELIVERY_DIFF_DIFF_TYPE: Final[dict[str, str]] = {
    'damage': '破损',
    'lack': '少发',
    'mismatch': '行不匹配',
    'over': '多发',
}
ORD_DELIVERY_DIFF_DIFF_TYPE_VALUES: Final[frozenset[str]] = frozenset(ORD_DELIVERY_DIFF_DIFF_TYPE)

ORD_DELIVERY_DIFF_LIABILITY: Final[dict[str, str]] = {
    'brand': '品牌方',
    'logistics': '物流',
    'unknown': '待判',
    'wms': 'wms',
}
ORD_DELIVERY_DIFF_LIABILITY_VALUES: Final[frozenset[str]] = frozenset(ORD_DELIVERY_DIFF_LIABILITY)

ORD_DELIVERY_DIFF_HANDLE_WAY: Final[dict[str, str]] = {
    'pending': '待定',
    'reconcile': '对账挂账',
    'refund': '退款',
    'reship': '补发',
}
ORD_DELIVERY_DIFF_HANDLE_WAY_VALUES: Final[frozenset[str]] = frozenset(ORD_DELIVERY_DIFF_HANDLE_WAY)

ORD_DELIVERY_DIFF_HANDLE_STATUS: Final[dict[str, str]] = {
    'closed': '已闭环',
    'handled': '已处理',
    'open': '待处理',
}
ORD_DELIVERY_DIFF_HANDLE_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_DELIVERY_DIFF_HANDLE_STATUS)

ORD_ORDER_MODIFY_MODIFY_TYPE: Final[dict[str, str]] = {
    'address': '地址',
    'invoice': '发票',
    'item_add': '加商品',
    'item_sub': '减商品',
    'item_swap': '换商品',
    'price': '价格',
    'remark': '备注',
}
ORD_ORDER_MODIFY_MODIFY_TYPE_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_MODIFY_MODIFY_TYPE)

ORD_ORDER_MODIFY_SOURCE: Final[dict[str, str]] = {
    'manual': '人工',
    'platform': '平台消息',
    'system': '系统',
}
ORD_ORDER_MODIFY_SOURCE_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_MODIFY_SOURCE)

ORD_ORDER_MODIFY_STATUS: Final[dict[str, str]] = {
    'closed': '已关闭',
    'editing': '编辑中',
    'effective': '已生效',
    'freezing': '冻结中',
    'recalling': '叫回中',
    'rolled_back': '已回滚',
    'suspended': '挂起',
    'wait_approval': '待审批',
    'wait_confirm': '待确认',
}
ORD_ORDER_MODIFY_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_MODIFY_STATUS)

ORD_ORDER_MODIFY_RECALL_STATUS: Final[dict[str, str]] = {
    'fail': '失败',
    'recalling': '叫回中',
    'success': '成功',
    'timeout': '超时',
}
ORD_ORDER_MODIFY_RECALL_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_MODIFY_RECALL_STATUS)

ORD_MODIFY_LOG_ACTION: Final[dict[str, str]] = {
    'approval_pass': '审批通过',
    'approval_reject': '审批驳回',
    'approval_submit': '提审',
    'cancel': '撤销',
    'confirm': '确认',
    'create': '发起',
    'effect': '生效',
    'freeze': '冻结',
    'recall': '叫回',
    'rollback': '回滚',
    'suspend': '挂起',
}
ORD_MODIFY_LOG_ACTION_VALUES: Final[frozenset[str]] = frozenset(ORD_MODIFY_LOG_ACTION)

ORD_MODIFY_LOG_SOURCE: Final[dict[str, str]] = {
    'manual': '人工',
    'platform': '平台消息',
    'system': '系统',
}
ORD_MODIFY_LOG_SOURCE_VALUES: Final[frozenset[str]] = frozenset(ORD_MODIFY_LOG_SOURCE)

ORD_RETRIAL_RETRIAL_TYPE: Final[dict[str, str]] = {
    'amount': '大额',
    'audit': '价格',
    'blacklist': '黑名单',
    'normal': '人工发起',
}
ORD_RETRIAL_RETRIAL_TYPE_VALUES: Final[frozenset[str]] = frozenset(ORD_RETRIAL_RETRIAL_TYPE)

ORD_RETRIAL_STATUS: Final[dict[str, str]] = {
    'closed_by_cancel': '已取消收口',
    'passed': '复审通过',
    'rejected_cancel': '驳回-取消',
    'rejected_rollback': '驳回-回滚',
    'wait': '待复审',
}
ORD_RETRIAL_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_RETRIAL_STATUS)

ORD_ABNORMAL_EXC_CATEGORY: Final[dict[str, str]] = {
    'data': '数据',
    'fulfill': '履约',
    'platform': '平台',
    'risk': '风控',
    'stock': '库存',
}
ORD_ABNORMAL_EXC_CATEGORY_VALUES: Final[frozenset[str]] = frozenset(ORD_ABNORMAL_EXC_CATEGORY)

ORD_ABNORMAL_SOURCE: Final[dict[str, str]] = {
    'event': '事件',
    'linkage': '联动',
    'manual': '人工',
    'plugin': '审单插件',
    'scan': '定时扫描',
}
ORD_ABNORMAL_SOURCE_VALUES: Final[frozenset[str]] = frozenset(ORD_ABNORMAL_SOURCE)

ORD_ABNORMAL_STATUS: Final[dict[str, str]] = {
    'cancelled': '已取消',
    'dispatched': '已分派',
    'processing': '处理中',
    'resolved': '已解决',
    'suspended': '已挂起',
    'wait_dispatch': '待分派',
}
ORD_ABNORMAL_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_ABNORMAL_STATUS)

ORD_ABNORMAL_RESOLVE_ACTION: Final[dict[str, str]] = {
    'cancel': '取消',
    'force_pass': '强制放行',
    'reaudit': '重新审单',
    'refund': '退款',
    'suspend': '挂起',
    'to_aftersale': '转售后',
    'to_retrial': '转复审',
}
ORD_ABNORMAL_RESOLVE_ACTION_VALUES: Final[frozenset[str]] = frozenset(ORD_ABNORMAL_RESOLVE_ACTION)

ORD_ABNORMAL_TYPE_DICT_CATEGORY: Final[dict[str, str]] = {
    'data': '数据',
    'fulfill': '履约',
    'platform': '平台',
    'risk': '风控',
    'stock': '库存',
}
ORD_ABNORMAL_TYPE_DICT_CATEGORY_VALUES: Final[frozenset[str]] = frozenset(ORD_ABNORMAL_TYPE_DICT_CATEGORY)

ORD_STOCKOUT_STRATEGY_STATUS: Final[dict[str, str]] = {
    'change_branch': '换仓中',
    'lending': '借调中',
    'negotiating': '协商中',
    'purchase_urgent': '采购加急',
    'refunding': '退款中',
    'resolved': '已解除',
    'wait_calc': '待测算',
}
ORD_STOCKOUT_STRATEGY_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_STOCKOUT_STRATEGY_STATUS)

ORD_OVERSOLD_BATCH_STAGE: Final[dict[str, str]] = {
    'alarm': '告警',
    'alloc_calc': '调拨测算',
    'compensate': '赔付',
    'negotiate': '协商',
    'refund': '退款',
    'review': '复盘关闭',
}
ORD_OVERSOLD_BATCH_STAGE_VALUES: Final[frozenset[str]] = frozenset(ORD_OVERSOLD_BATCH_STAGE)

ORD_PAUSE_COMMAND_LOG_COMMAND: Final[dict[str, str]] = {
    'recall': '叫回',
    'resume': '恢复重推',
}
ORD_PAUSE_COMMAND_LOG_COMMAND_VALUES: Final[frozenset[str]] = frozenset(ORD_PAUSE_COMMAND_LOG_COMMAND)

ORD_PAUSE_COMMAND_LOG_RESULT: Final[dict[str, str]] = {
    'fail': '失败',
    'success': '成功',
    'timeout': '超时',
}
ORD_PAUSE_COMMAND_LOG_RESULT_VALUES: Final[frozenset[str]] = frozenset(ORD_PAUSE_COMMAND_LOG_RESULT)

ORD_RISK_LIST_LIST_TYPE: Final[dict[str, str]] = {
    'black': '黑名单',
    'gray': '灰名单',
    'white': '白名单',
}
ORD_RISK_LIST_LIST_TYPE_VALUES: Final[frozenset[str]] = frozenset(ORD_RISK_LIST_LIST_TYPE)

ORD_RISK_LIST_DIMENSION: Final[dict[str, str]] = {
    'account': '账号',
    'address': '地址',
    'mobile': '手机',
    'name': '姓名',
}
ORD_RISK_LIST_DIMENSION_VALUES: Final[frozenset[str]] = frozenset(ORD_RISK_LIST_DIMENSION)

ORD_RISK_LIST_VALUE_TYPE: Final[dict[str, str]] = {
    'hash': '盲索引',
    'plain': '明文',
}
ORD_RISK_LIST_VALUE_TYPE_VALUES: Final[frozenset[str]] = frozenset(ORD_RISK_LIST_VALUE_TYPE)

ORD_RISK_LIST_SCOPE: Final[dict[str, str]] = {
    'global': '全局',
    'owner': '货主',
    'tenant': '租户',
}
ORD_RISK_LIST_SCOPE_VALUES: Final[frozenset[str]] = frozenset(ORD_RISK_LIST_SCOPE)

ORD_PRESALE_PRESALE_STATUS: Final[dict[str, str]] = {
    'balance_paid': '尾款已付',
    'closed': '已关闭',
    'deposit_paid': '定金已付',
    'finished': '已完成',
    'fulfilling': '履约中',
    'wait_audit': '待审单',
}
ORD_PRESALE_PRESALE_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_PRESALE_PRESALE_STATUS)

ORD_PRESALE_RESERVE_MODE: Final[dict[str, str]] = {
    'immediate': '定金后立即预占',
    'none': '不预占',
}
ORD_PRESALE_RESERVE_MODE_VALUES: Final[frozenset[str]] = frozenset(ORD_PRESALE_RESERVE_MODE)

ORD_GROUPON_GROUPON_STATUS: Final[dict[str, str]] = {
    'closed': '关闭',
    'failed_cancel': '未成团取消',
    'finished': '完成',
    'fulfilling': '履约中',
    'refunding': '退款中',
    'succeed': '已成团',
    'wait_group': '待成团',
}
ORD_GROUPON_GROUPON_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_GROUPON_GROUPON_STATUS)

ORD_LUCKYBAG_ALLOC_DISPATCH_MODE: Final[dict[str, str]] = {
    'manual': '人工指定',
    'random': '随机',
    'rule': '规则',
}
ORD_LUCKYBAG_ALLOC_DISPATCH_MODE_VALUES: Final[frozenset[str]] = frozenset(ORD_LUCKYBAG_ALLOC_DISPATCH_MODE)

ORD_LUCKYBAG_ALLOC_DISPATCH_RESULT: Final[dict[str, str]] = {
    'fail_final': '全部失败转人工',
    'fail_preempt': '预占失败改派',
    'success': '成功',
}
ORD_LUCKYBAG_ALLOC_DISPATCH_RESULT_VALUES: Final[frozenset[str]] = frozenset(ORD_LUCKYBAG_ALLOC_DISPATCH_RESULT)

ORD_CARD_SECRET_STATUS: Final[dict[str, str]] = {
    'bound': '已绑定',
    'settled': '已核销',
    'unused': '未核销',
    'voided': '已作废',
}
ORD_CARD_SECRET_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_CARD_SECRET_STATUS)

ORD_VIRTUAL_DELIVERY_SYNC_CHANNEL: Final[dict[str, str]] = {
    'card_api': '接口带卡密',
    'status_only': '仅记状态',
    'virtual_waybill': '虚拟运单号',
}
ORD_VIRTUAL_DELIVERY_SYNC_CHANNEL_VALUES: Final[frozenset[str]] = frozenset(ORD_VIRTUAL_DELIVERY_SYNC_CHANNEL)

ORD_VIRTUAL_DELIVERY_SYNC_STATUS: Final[dict[str, str]] = {
    'fail': '失败',
    'manual': '人工补发',
    'success': '成功',
    'syncing': '发送中',
    'wait': '待发',
}
ORD_VIRTUAL_DELIVERY_SYNC_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_VIRTUAL_DELIVERY_SYNC_STATUS)

ORD_STORE_PROFILE_BIZ_STATUS: Final[dict[str, str]] = {
    'closed': '停业',
    'open': '营业中',
    'pause_accept': '暂停接单',
}
ORD_STORE_PROFILE_BIZ_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_STORE_PROFILE_BIZ_STATUS)

ORD_STORE_ORDER_FULFILL_MODE: Final[dict[str, str]] = {
    'city_delivery': '同城配送',
    'store_pickup': '门店自提',
    'store_ship': '门店发货',
}
ORD_STORE_ORDER_FULFILL_MODE_VALUES: Final[frozenset[str]] = frozenset(ORD_STORE_ORDER_FULFILL_MODE)

ORD_STORE_ORDER_ACCEPT_STATUS: Final[dict[str, str]] = {
    'accepted': '已接单',
    'refused': '已拒单',
    'timeout_redispatch': '超时转派',
    'wait': '待接单',
}
ORD_STORE_ORDER_ACCEPT_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_STORE_ORDER_ACCEPT_STATUS)

ORD_PICKUP_STATUS: Final[dict[str, str]] = {
    'cancelled': '已取消',
    'overdue_handling': '超期处理中',
    'verified': '已核销',
    'wait_verify': '待核销',
}
ORD_PICKUP_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_PICKUP_STATUS)

ORD_PICKUP_OVERDUE_ACTION: Final[dict[str, str]] = {
    'return_stock': '退回库存',
    'to_delivery': '转配送',
}
ORD_PICKUP_OVERDUE_ACTION_VALUES: Final[frozenset[str]] = frozenset(ORD_PICKUP_OVERDUE_ACTION)

ORD_DECLARE_DECLARE_MODE: Final[dict[str, str]] = {
    'bonded': '保税',
    'direct': '直邮',
}
ORD_DECLARE_DECLARE_MODE_VALUES: Final[frozenset[str]] = frozenset(ORD_DECLARE_DECLARE_MODE)

ORD_DECLARE_DECLARE_STATUS: Final[dict[str, str]] = {
    'declaring': '申报中',
    'exported': '已出区',
    'failed': '申报失败',
    'refund_declare': '退单申报',
    'released': '放行',
    'returned': '已退单',
    'wait': '待申报',
}
ORD_DECLARE_DECLARE_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_DECLARE_DECLARE_STATUS)

ORD_DECLARE_FAIL_REASON_CODE: Final[dict[str, str]] = {
    'AMOUNT_MISMATCH': '对碰不一致',
    'ID_INVALID': '身份证',
    'OTHER': 'OTHER',
    'QUOTA_OVER': '额度',
    'RECORD': '备案问题',
}
ORD_DECLARE_FAIL_REASON_CODE_VALUES: Final[frozenset[str]] = frozenset(ORD_DECLARE_FAIL_REASON_CODE)

ORD_ORDER_ARCHIVE_ARCHIVE_STATUS: Final[dict[str, str]] = {
    'done': '完成',
    'recalled': '已回捞待清理',
}
ORD_ORDER_ARCHIVE_ARCHIVE_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_ARCHIVE_ARCHIVE_STATUS)

ORD_ORDER_ARCHIVE_ARCHIVE_SOURCE: Final[dict[str, str]] = {
    'migration': '迁移导入',
    'task': '归档任务',
}
ORD_ORDER_ARCHIVE_ARCHIVE_SOURCE_VALUES: Final[frozenset[str]] = frozenset(ORD_ORDER_ARCHIVE_ARCHIVE_SOURCE)

ORD_ARCHIVE_LOG_LOG_TYPE: Final[dict[str, str]] = {
    'archive': '归档',
    'batch_rollback': '批次回滚',
    'cold_offload': '冷备卸载',
    'import': '迁移导入',
    'recall': '回捞',
}
ORD_ARCHIVE_LOG_LOG_TYPE_VALUES: Final[frozenset[str]] = frozenset(ORD_ARCHIVE_LOG_LOG_TYPE)

ORD_ARCHIVE_LOG_TRIGGER_SOURCE: Final[dict[str, str]] = {
    'aftersale': '售后建单',
    'finance': '财务',
    'manual': '客服人工',
    'migration': '迁移工具',
    'schedule': '调度任务',
}
ORD_ARCHIVE_LOG_TRIGGER_SOURCE_VALUES: Final[frozenset[str]] = frozenset(ORD_ARCHIVE_LOG_TRIGGER_SOURCE)

ORD_ARCHIVE_LOG_RESULT: Final[dict[str, str]] = {
    'fail': '失败',
    'success': '成功',
}
ORD_ARCHIVE_LOG_RESULT_VALUES: Final[frozenset[str]] = frozenset(ORD_ARCHIVE_LOG_RESULT)

ORD_ARCHIVE_CONFIG_SCOPE_LEVEL: Final[dict[str, str]] = {
    'brand': '品牌',
    'global': '全局',
    'owner': '货主',
}
ORD_ARCHIVE_CONFIG_SCOPE_LEVEL_VALUES: Final[frozenset[str]] = frozenset(ORD_ARCHIVE_CONFIG_SCOPE_LEVEL)

ORD_SHOP_FULFILL_CONFIG_LACK_FULFILL_MODE: Final[dict[str, str]] = {
    'manual': '人工',
    'ship_first': '先发后缺',
    'wait_all': '整单等货',
}
ORD_SHOP_FULFILL_CONFIG_LACK_FULFILL_MODE_VALUES: Final[frozenset[str]] = frozenset(ORD_SHOP_FULFILL_CONFIG_LACK_FULFILL_MODE)

ORD_SHOP_FULFILL_CONFIG_LEND_AUTO_MODE: Final[dict[str, str]] = {
    'auto': '自动借调',
    'manual': '人工确认',
}
ORD_SHOP_FULFILL_CONFIG_LEND_AUTO_MODE_VALUES: Final[frozenset[str]] = frozenset(ORD_SHOP_FULFILL_CONFIG_LEND_AUTO_MODE)

ORD_SHOP_FULFILL_CONFIG_MONITOR_MODE: Final[dict[str, str]] = {
    'item': '行级',
    'order': '整单',
}
ORD_SHOP_FULFILL_CONFIG_MONITOR_MODE_VALUES: Final[frozenset[str]] = frozenset(ORD_SHOP_FULFILL_CONFIG_MONITOR_MODE)

ORD_SHOP_FULFILL_CONFIG_PRESALE_RESERVE_MODE: Final[dict[str, str]] = {
    'immediate': '定金后立即预占',
    'none': '不预占',
}
ORD_SHOP_FULFILL_CONFIG_PRESALE_RESERVE_MODE_VALUES: Final[frozenset[str]] = frozenset(ORD_SHOP_FULFILL_CONFIG_PRESALE_RESERVE_MODE)

ORD_SHOP_FULFILL_CONFIG_LUCKYBAG_AFTERSALE_MODE: Final[dict[str, str]] = {
    'part': '部分退',
    'whole': '整套退',
}
ORD_SHOP_FULFILL_CONFIG_LUCKYBAG_AFTERSALE_MODE_VALUES: Final[frozenset[str]] = frozenset(ORD_SHOP_FULFILL_CONFIG_LUCKYBAG_AFTERSALE_MODE)

ORD_SHOP_FULFILL_CONFIG_PICKUP_OVERDUE_ACTION: Final[dict[str, str]] = {
    'return_stock': '退回库存',
    'to_delivery': '转配送',
}
ORD_SHOP_FULFILL_CONFIG_PICKUP_OVERDUE_ACTION_VALUES: Final[frozenset[str]] = frozenset(ORD_SHOP_FULFILL_CONFIG_PICKUP_OVERDUE_ACTION)

ORD_SHOP_FULFILL_CONFIG_O2O_FALLBACK: Final[dict[str, str]] = {
    'manual': '挂起人工',
    'to_warehouse': '转电商仓',
}
ORD_SHOP_FULFILL_CONFIG_O2O_FALLBACK_VALUES: Final[frozenset[str]] = frozenset(ORD_SHOP_FULFILL_CONFIG_O2O_FALLBACK)

ORD_REASON_CODE_DICT_LEVEL: Final[dict[str, str]] = {
    'BLOCK': '拦截',
    'WARN': '提示',
}
ORD_REASON_CODE_DICT_LEVEL_VALUES: Final[frozenset[str]] = frozenset(ORD_REASON_CODE_DICT_LEVEL)

ORD_REASON_CODE_DICT_DEFAULT_ROUTE: Final[dict[str, str]] = {
    'manual': '人工',
    'requeue': '回池',
    'retrial': '复审',
    'shortage': '缺货',
    'suspend': '挂起',
}
ORD_REASON_CODE_DICT_DEFAULT_ROUTE_VALUES: Final[frozenset[str]] = frozenset(ORD_REASON_CODE_DICT_DEFAULT_ROUTE)

ORD_REASON_CODE_DICT_DEFAULT_SUGGEST: Final[dict[str, str]] = {
    'change_branch': '换仓',
    'contact_buyer': '联系买家',
    'modify_address': '改地址',
    'reship': '补发',
    'to_retrial': '转复审',
    'wait_restock': '等补货',
}
ORD_REASON_CODE_DICT_DEFAULT_SUGGEST_VALUES: Final[frozenset[str]] = frozenset(ORD_REASON_CODE_DICT_DEFAULT_SUGGEST)

ORD_PROMOTION_ACTIVITY_ACTIVITY_TYPE: Final[dict[str, str]] = {
    'amount_reduce': '满减',
    'buy_gift': '买赠',
    'full_gift': '满赠',
    'ladder_gift': '阶梯满赠',
    'qty_discount': '满件折',
}
ORD_PROMOTION_ACTIVITY_ACTIVITY_TYPE_VALUES: Final[frozenset[str]] = frozenset(ORD_PROMOTION_ACTIVITY_ACTIVITY_TYPE)

ORD_PROMOTION_ACTIVITY_GIFT_LACK_POLICY: Final[dict[str, str]] = {
    'hold_order': '整单挂起',
    'manual': '人工',
    'replace': '换等价赠品',
    'skip_gift': '放弃赠品',
}
ORD_PROMOTION_ACTIVITY_GIFT_LACK_POLICY_VALUES: Final[frozenset[str]] = frozenset(ORD_PROMOTION_ACTIVITY_GIFT_LACK_POLICY)

ORD_PROMOTION_ACTIVITY_STATUS: Final[dict[str, str]] = {
    'active': '生效中',
    'draft': '草稿',
    'ended': '已结束',
    'paused': '已暂停',
    'pending': '待生效',
    'voided': '已作废',
}
ORD_PROMOTION_ACTIVITY_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_PROMOTION_ACTIVITY_STATUS)

ORD_PROMOTION_RULE_THRESHOLD_TYPE: Final[dict[str, str]] = {
    'amount': '实付金额',
    'qty': '件数',
}
ORD_PROMOTION_RULE_THRESHOLD_TYPE_VALUES: Final[frozenset[str]] = frozenset(ORD_PROMOTION_RULE_THRESHOLD_TYPE)

ORD_PROMOTION_RULE_DISCOUNT_TYPE: Final[dict[str, str]] = {
    'discount': '折扣',
    'reduce': '立减',
}
ORD_PROMOTION_RULE_DISCOUNT_TYPE_VALUES: Final[frozenset[str]] = frozenset(ORD_PROMOTION_RULE_DISCOUNT_TYPE)

ORD_PROMOTION_SCOPE_DIRECTION: Final[dict[str, str]] = {
    'exclude': '排除',
    'include': '参与',
}
ORD_PROMOTION_SCOPE_DIRECTION_VALUES: Final[frozenset[str]] = frozenset(ORD_PROMOTION_SCOPE_DIRECTION)

ORD_PROMOTION_SCOPE_SCOPE_TYPE: Final[dict[str, str]] = {
    'all': '全部',
    'brand': '品牌',
    'category': '分类树节点',
    'sku': 'sku',
}
ORD_PROMOTION_SCOPE_SCOPE_TYPE_VALUES: Final[frozenset[str]] = frozenset(ORD_PROMOTION_SCOPE_SCOPE_TYPE)

ORD_PROMOTION_SCOPE_ROLE: Final[dict[str, str]] = {
    'base': '满赠基数商品',
    'main': '买赠主品',
}
ORD_PROMOTION_SCOPE_ROLE_VALUES: Final[frozenset[str]] = frozenset(ORD_PROMOTION_SCOPE_ROLE)

ORD_GIFT_LOG_LOG_TYPE: Final[dict[str, str]] = {
    'applied': '加赠',
    'revoke': '撤销',
    'skipped': '缺货放弃或落选备查',
}
ORD_GIFT_LOG_LOG_TYPE_VALUES: Final[frozenset[str]] = frozenset(ORD_GIFT_LOG_LOG_TYPE)

ORD_GIFT_LOG_REVOKE_REASON: Final[dict[str, str]] = {
    'manual': '人工撤销',
    'modify_downgrade': '改单降档',
    'order_cancel': '订单取消',
    'race_give_up': '竞态放弃',
    'reaudit': '重审重算',
}
ORD_GIFT_LOG_REVOKE_REASON_VALUES: Final[frozenset[str]] = frozenset(ORD_GIFT_LOG_REVOKE_REASON)

ORD_GIFT_LOG_ADD: Final[dict[str, str]] = {
    'express': '常规快递',
    'instant': '即时零售',
    'store': '门店履约',
}
ORD_GIFT_LOG_ADD_VALUES: Final[frozenset[str]] = frozenset(ORD_GIFT_LOG_ADD)

ORD_INSTANT_DELIVERY_ORCHESTRATE_STATUS: Final[dict[str, str]] = {
    'accepted': '已接单',
    'aftersale': '售后中',
    'cancelled': '已取消',
    'delivered': '已送达',
    'delivering': '配送中',
    'exception_handling': '异常处理中',
    'finished': '完成',
    'lack_handling': '缺货处理中',
    'picking': '拣货中',
    'redispatching': '改派中',
    'refused': '已拒单',
    'self_delivering': '自配送中',
    'wait_pickup': '待取货',
}
ORD_INSTANT_DELIVERY_ORCHESTRATE_STATUS_VALUES: Final[frozenset[str]] = frozenset(ORD_INSTANT_DELIVERY_ORCHESTRATE_STATUS)

ORD_INSTANT_TRACK_LIABILITY: Final[dict[str, str]] = {
    'carrier': '运力方',
    'merchant': '商家承担',
    'store': '门店',
    'system': '系统',
}
ORD_INSTANT_TRACK_LIABILITY_VALUES: Final[frozenset[str]] = frozenset(ORD_INSTANT_TRACK_LIABILITY)

ORD_INSTANT_TRACK_BEARER: Final[dict[str, str]] = {
    'carrier': '运力方',
    'merchant': '商家',
    'platform': '平台',
}
ORD_INSTANT_TRACK_BEARER_VALUES: Final[frozenset[str]] = frozenset(ORD_INSTANT_TRACK_BEARER)

ORD_ROUTING_DECISION_LOG_DECISION_MODE: Final[dict[str, str]] = {
    'algorithm': '算法寻源',
    'rule': '规则式',
}
ORD_ROUTING_DECISION_LOG_DECISION_MODE_VALUES: Final[frozenset[str]] = frozenset(ORD_ROUTING_DECISION_LOG_DECISION_MODE)

ORD_ROUTING_DECISION_LOG_MODIFY: Final[dict[str, str]] = {
    'black': '黑名单',
    'gray': '灰名单',
    'white': '白名单',
}
ORD_ROUTING_DECISION_LOG_MODIFY_VALUES: Final[frozenset[str]] = frozenset(ORD_ROUTING_DECISION_LOG_MODIFY)

# ---- oms_stock ----

INV_STOCK_RECON_DIFF_CHANGE_FIELD: Final[dict[str, str]] = {
    'arrive': 'arrive',
    'defective': 'defective',
    'freeze': 'freeze',
    'store': 'store',
}
INV_STOCK_RECON_DIFF_CHANGE_FIELD_VALUES: Final[frozenset[str]] = frozenset(INV_STOCK_RECON_DIFF_CHANGE_FIELD)

INV_ACTIVITY_LOCK_POOL_STATUS: Final[dict[str, str]] = {
    'active': '生效中',
    'ended': '已结束',
    'released': '已释放',
    'warmup': '预热中',
}
INV_ACTIVITY_LOCK_POOL_STATUS_VALUES: Final[frozenset[str]] = frozenset(INV_ACTIVITY_LOCK_POOL_STATUS)

INV_SALES_FORECAST_ADOPT_STRATEGY: Final[dict[str, str]] = {
    'blended': '加权融合',
    'pure_forecast': '纯预测',
    'pure_history': '纯历史',
}
INV_SALES_FORECAST_ADOPT_STRATEGY_VALUES: Final[frozenset[str]] = frozenset(INV_SALES_FORECAST_ADOPT_STRATEGY)

INV_SALES_FORECAST_CALL_STATUS: Final[dict[str, str]] = {
    'degraded': '降级',
    'fail': '失败',
    'success': '成功',
    'timeout': '超时',
}
INV_SALES_FORECAST_CALL_STATUS_VALUES: Final[frozenset[str]] = frozenset(INV_SALES_FORECAST_CALL_STATUS)

INV_PRICE_SYNC_TASK_PLATFORM: Final[dict[str, str]] = {
    'douyin': 'douyin',
    'jd': 'jd',
    'kuaishou': 'kuaishou',
    'pdd': 'pdd',
    'taobao': 'taobao',
    'vop': 'vop',
    'wechat': 'wechat',
    'xhs': 'xhs',
}
INV_PRICE_SYNC_TASK_PLATFORM_VALUES: Final[frozenset[str]] = frozenset(INV_PRICE_SYNC_TASK_PLATFORM)

# ---- oms_finance ----

FIN_KINGDEE_ADAPTER_AUTH_TYPE: Final[dict[str, str]] = {
    'basic': 'basic',
    'kd_token': 'kd_token',
    'none': 'none',
    'oauth2': 'oauth2',
}
FIN_KINGDEE_ADAPTER_AUTH_TYPE_VALUES: Final[frozenset[str]] = frozenset(FIN_KINGDEE_ADAPTER_AUTH_TYPE)

FIN_INVOICE_POOL_SOURCE: Final[dict[str, str]] = {
    'manual': 'manual',
    'order': 'order',
    'platform': 'platform',
}
FIN_INVOICE_POOL_SOURCE_VALUES: Final[frozenset[str]] = frozenset(FIN_INVOICE_POOL_SOURCE)

# ---- oms_fulfill ----

FUL_BRANCH_BRANCH_TYPE: Final[dict[str, str]] = {
    'bonded': '保税仓',
    'cloud': '云仓',
    'defective': '次品仓',
    'entity': '实体仓',
    'store': '门店仓',
    'virtual': '虚拟仓',
}
FUL_BRANCH_BRANCH_TYPE_VALUES: Final[frozenset[str]] = frozenset(FUL_BRANCH_BRANCH_TYPE)

FUL_BRANCH_STATUS: Final[dict[str, str]] = {
    'archived': '归档',
    'disabled': '停用',
    'enabled': '启用',
    'migrating': '迁移中',
}
FUL_BRANCH_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_BRANCH_STATUS)

FUL_BRANCH_SOURCE: Final[dict[str, str]] = {
    'api': 'api',
    'import': 'import',
    'local': 'local',
    'migration': 'migration',
}
FUL_BRANCH_SOURCE_VALUES: Final[frozenset[str]] = frozenset(FUL_BRANCH_SOURCE)

FUL_WMS_WMS_CODE: Final[dict[str, str]] = {
    'flux': '富勒',
    'qimen': '奇门通用',
    'self': '自研仓内',
    'ttx': '通天晓',
    'wln': '万里牛',
}
FUL_WMS_WMS_CODE_VALUES: Final[frozenset[str]] = frozenset(FUL_WMS_WMS_CODE)

FUL_WMS_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
FUL_WMS_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_WMS_STATUS)

FUL_WMS_BINDING_PROTOCOL: Final[dict[str, str]] = {
    'qimen': 'qimen',
    'restful': 'restful',
    'ttx_rest': 'ttx_rest',
}
FUL_WMS_BINDING_PROTOCOL_VALUES: Final[frozenset[str]] = frozenset(FUL_WMS_BINDING_PROTOCOL)

FUL_WMS_BINDING_ENV: Final[dict[str, str]] = {
    'prod': '生产',
    'sandbox': '沙箱',
}
FUL_WMS_BINDING_ENV_VALUES: Final[frozenset[str]] = frozenset(FUL_WMS_BINDING_ENV)

FUL_WMS_BINDING_STATUS: Final[dict[str, str]] = {
    'active': '生效',
    'archived': '失效归档',
    'pending': '待生效',
    'receive_only': '只收不发',
}
FUL_WMS_BINDING_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_WMS_BINDING_STATUS)

FUL_WMS_HEALTH_CIRCUIT_STATUS: Final[dict[str, str]] = {
    'closed': '正常',
    'half_open': '半开探测',
    'open': '熔断中',
}
FUL_WMS_HEALTH_CIRCUIT_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_WMS_HEALTH_CIRCUIT_STATUS)

FUL_ROUTE_LOG_RESULT: Final[dict[str, str]] = {
    'degraded': '降级',
    'fail': '失败',
    'succ': '成功',
}
FUL_ROUTE_LOG_RESULT_VALUES: Final[frozenset[str]] = frozenset(FUL_ROUTE_LOG_RESULT)

FUL_CMD_FAIL_CMD_TYPE: Final[dict[str, str]] = {
    'cancel': '取消',
    'inbound': '入库',
    'outbound': '出库',
    'recall': '叫回',
}
FUL_CMD_FAIL_CMD_TYPE_VALUES: Final[frozenset[str]] = frozenset(FUL_CMD_FAIL_CMD_TYPE)

FUL_CMD_FAIL_ERR_CLASS: Final[dict[str, str]] = {
    'BIZ_REJECT': '业务拒绝',
    'FATAL': '停重试',
    'RETRYABLE': '可重试',
}
FUL_CMD_FAIL_ERR_CLASS_VALUES: Final[frozenset[str]] = frozenset(FUL_CMD_FAIL_ERR_CLASS)

FUL_CMD_FAIL_CIRCUIT_SNAPSHOT: Final[dict[str, str]] = {
    'closed': 'closed',
    'half_open': 'half_open',
    'open': 'open',
}
FUL_CMD_FAIL_CIRCUIT_SNAPSHOT_VALUES: Final[frozenset[str]] = frozenset(FUL_CMD_FAIL_CIRCUIT_SNAPSHOT)

FUL_CMD_FAIL_STATUS: Final[dict[str, str]] = {
    'dead': '死信',
    'manual': '转人工',
    'retrying': '重试中',
    'succ': '成功',
    'waiting': '等待',
}
FUL_CMD_FAIL_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_CMD_FAIL_STATUS)

FUL_CMD_FAIL_RESOLVED_BY: Final[dict[str, str]] = {
    'biz_closed': '业务关闭',
    'manual': '人工',
    'retry': '重试',
}
FUL_CMD_FAIL_RESOLVED_BY_VALUES: Final[frozenset[str]] = frozenset(FUL_CMD_FAIL_RESOLVED_BY)

FUL_OUTBOUND_CMD_CMD_TYPE: Final[dict[str, str]] = {
    'push': '推送',
    'recall': '叫回',
    'resume': '恢复',
}
FUL_OUTBOUND_CMD_CMD_TYPE_VALUES: Final[frozenset[str]] = frozenset(FUL_OUTBOUND_CMD_CMD_TYPE)

FUL_OUTBOUND_CMD_SOURCE: Final[dict[str, str]] = {
    'api': 'api',
    'import': 'import',
    'local': 'local',
    'migration': 'migration',
}
FUL_OUTBOUND_CMD_SOURCE_VALUES: Final[frozenset[str]] = frozenset(FUL_OUTBOUND_CMD_SOURCE)

FUL_OUTBOUND_CALLBACK_CALLBACK_TYPE: Final[dict[str, str]] = {
    'accept': '接收确认',
    'cancel_result': '取消结果',
    'node': '节点',
    'outbound': '出库',
    'reject': '打回',
}
FUL_OUTBOUND_CALLBACK_CALLBACK_TYPE_VALUES: Final[frozenset[str]] = frozenset(FUL_OUTBOUND_CALLBACK_CALLBACK_TYPE)

FUL_OUTBOUND_CALLBACK_REJECT_REASON: Final[dict[str, str]] = {
    'address_unreachable': '地址不可达',
    'oos': '缺货',
    'wh_error': '仓内异常',
}
FUL_OUTBOUND_CALLBACK_REJECT_REASON_VALUES: Final[frozenset[str]] = frozenset(FUL_OUTBOUND_CALLBACK_REJECT_REASON)

FUL_OUTBOUND_CALLBACK_PROCESS_STATUS: Final[dict[str, str]] = {
    'event_sent': '已发事件',
    'exception': '异常缓冲',
    'orchestrated': '编排闭环',
    'registered': '已登记',
}
FUL_OUTBOUND_CALLBACK_PROCESS_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_OUTBOUND_CALLBACK_PROCESS_STATUS)

FUL_OUTBOUND_BUFFER_STATUS: Final[dict[str, str]] = {
    'buffered': '缓冲中',
    'resent': '已补发',
    'voided': '已作废',
}
FUL_OUTBOUND_BUFFER_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_OUTBOUND_BUFFER_STATUS)

FUL_CHANNEL_LOG_ACTION: Final[dict[str, str]] = {
    'callback_accept': 'callback_accept',
    'callback_outbound': '等',
    'cancel': 'cancel',
    'push': 'push',
    'query': 'query',
    'recall': 'recall',
}
FUL_CHANNEL_LOG_ACTION_VALUES: Final[frozenset[str]] = frozenset(FUL_CHANNEL_LOG_ACTION)

FUL_CHANNEL_LOG_ERR_CLASS: Final[dict[str, str]] = {
    'BIZ_REJECT': 'BIZ_REJECT',
    'FATAL': 'FATAL',
    'RETRYABLE': 'RETRYABLE',
}
FUL_CHANNEL_LOG_ERR_CLASS_VALUES: Final[frozenset[str]] = frozenset(FUL_CHANNEL_LOG_ERR_CLASS)

FUL_INBOUND_CMD_BILL_TYPE: Final[dict[str, str]] = {
    'other': '其他',
    'purchase': '采购',
    'transfer': '调拨',
}
FUL_INBOUND_CMD_BILL_TYPE_VALUES: Final[frozenset[str]] = frozenset(FUL_INBOUND_CMD_BILL_TYPE)

FUL_INBOUND_CMD_SOURCE_TYPE: Final[dict[str, str]] = {
    'purchase': '采购PO',
    'return': '退货RA',
    'transfer': '调拨TR',
}
FUL_INBOUND_CMD_SOURCE_TYPE_VALUES: Final[frozenset[str]] = frozenset(FUL_INBOUND_CMD_SOURCE_TYPE)

FUL_INBOUND_CMD_STATUS: Final[dict[str, str]] = {
    'accepted': 'accepted',
    'buffering': 'buffering',
    'callback_done': 'callback_done',
    'orchestrated': 'orchestrated',
    'partial_callback': 'partial_callback',
    'processing': 'processing',
    'recall_failed': 'recall_failed',
    'recall_succ': 'recall_succ',
    'recalling': 'recalling',
    'rejected': 'rejected',
    'retrying': 'retrying',
    'send_failed': 'send_failed',
    'sending': 'sending',
    'sent': 'sent',
    'voided': 'voided',
}
FUL_INBOUND_CMD_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_INBOUND_CMD_STATUS)

FUL_INBOUND_CALLBACK_CALLBACK_TYPE: Final[dict[str, str]] = {
    'accept': '接收确认',
    'cancel_result': '取消结果',
    'diff_report': '差异上报',
    'qc': '质检',
    'receive': '收货',
}
FUL_INBOUND_CALLBACK_CALLBACK_TYPE_VALUES: Final[frozenset[str]] = frozenset(FUL_INBOUND_CALLBACK_CALLBACK_TYPE)

FUL_INBOUND_CALLBACK_PROCESS_STATUS: Final[dict[str, str]] = {
    'confirmed': '已确认',
    'diff_hold': '差异挂起',
    'exception': '异常缓冲',
    'received': '已收',
    'registered': '已登记',
}
FUL_INBOUND_CALLBACK_PROCESS_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_INBOUND_CALLBACK_PROCESS_STATUS)

FUL_INBOUND_DIFF_DIFF_TYPE: Final[dict[str, str]] = {
    'damage': '破损',
    'mismatch': '预报不符',
    'over': '超收',
    'qc_dispute': '质检争议',
    'short': '短缺',
    'wrong_goods': '串货',
}
FUL_INBOUND_DIFF_DIFF_TYPE_VALUES: Final[frozenset[str]] = frozenset(FUL_INBOUND_DIFF_DIFF_TYPE)

FUL_INBOUND_DIFF_HANDLE_STATUS: Final[dict[str, str]] = {
    'closed': '已闭环',
    'handling': '处理中',
    'open': '待处理',
}
FUL_INBOUND_DIFF_HANDLE_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_INBOUND_DIFF_HANDLE_STATUS)

FUL_INBOUND_DIFF_SOURCE_NOTIFY_STATUS: Final[dict[str, str]] = {
    'acked': '已确认',
    'pending': '待送达',
    'sent': '事件已送达',
}
FUL_INBOUND_DIFF_SOURCE_NOTIFY_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_INBOUND_DIFF_SOURCE_NOTIFY_STATUS)

FUL_DLY_CORP_CORP_CODE: Final[dict[str, str]] = {
    'ems': '邮政等',
    'jd': '京东物流',
    'sf': '顺丰',
    'sto': '申通',
    'yto': '圆通',
    'yunda': '韵达',
    'zto': '中通',
}
FUL_DLY_CORP_CORP_CODE_VALUES: Final[frozenset[str]] = frozenset(FUL_DLY_CORP_CORP_CODE)

FUL_DLY_CORP_CORP_TYPE: Final[dict[str, str]] = {
    'express': '快递',
    'freight': '快运',
    'lastmile': '落地配',
    'platform': '平台物流',
    'postal': '邮政',
    'samecity': '同城',
    'special': '特殊',
}
FUL_DLY_CORP_CORP_TYPE_VALUES: Final[frozenset[str]] = frozenset(FUL_DLY_CORP_CORP_TYPE)

FUL_DLY_CORP_WAYBILL_ACCOUNT_TYPE: Final[dict[str, str]] = {
    'cainiao': '菜鸟系',
    'direct': '快递直客',
    'none': '无需面单',
    'platform': '平台系',
}
FUL_DLY_CORP_WAYBILL_ACCOUNT_TYPE_VALUES: Final[frozenset[str]] = frozenset(FUL_DLY_CORP_WAYBILL_ACCOUNT_TYPE)

FUL_DLY_CORP_PICKUP_MODE: Final[dict[str, str]] = {
    'door': '上门',
    'self': '自送',
    'station': '驿站',
}
FUL_DLY_CORP_PICKUP_MODE_VALUES: Final[frozenset[str]] = frozenset(FUL_DLY_CORP_PICKUP_MODE)

FUL_DLY_CORP_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
FUL_DLY_CORP_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_DLY_CORP_STATUS)

FUL_DLY_PRODUCT_PRODUCT_TYPE: Final[dict[str, str]] = {
    'bulky': '大件',
    'cold': '冷链',
    'economy': '经济',
    'express': '特快',
    'intl': '国际',
    'samecity': '同城',
    'standard': '标快',
}
FUL_DLY_PRODUCT_PRODUCT_TYPE_VALUES: Final[frozenset[str]] = frozenset(FUL_DLY_PRODUCT_PRODUCT_TYPE)

FUL_DLY_PRODUCT_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
FUL_DLY_PRODUCT_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_DLY_PRODUCT_STATUS)

FUL_AREA_ROUTER_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
FUL_AREA_ROUTER_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_AREA_ROUTER_STATUS)

FUL_UNREACH_AREA_STATUS: Final[dict[str, str]] = {
    'disabled': '失效',
    'enabled': '生效',
}
FUL_UNREACH_AREA_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_UNREACH_AREA_STATUS)

FUL_SUSPEND_STATUS: Final[dict[str, str]] = {
    'disabled': '撤销停运',
    'enabled': '生效',
}
FUL_SUSPEND_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_SUSPEND_STATUS)

FUL_ADDR_KEYWORD_LEVEL: Final[dict[str, str]] = {
    'BLOCK': '拦截',
    'WARN': '提示',
}
FUL_ADDR_KEYWORD_LEVEL_VALUES: Final[frozenset[str]] = frozenset(FUL_ADDR_KEYWORD_LEVEL)

FUL_ADDR_KEYWORD_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
FUL_ADDR_KEYWORD_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_ADDR_KEYWORD_STATUS)

FUL_SHOP_DLY_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
FUL_SHOP_DLY_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_SHOP_DLY_STATUS)

FUL_BRANCH_DLY_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
FUL_BRANCH_DLY_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_BRANCH_DLY_STATUS)

FUL_FREIGHT_TEMPLATE_CHARGE_MODE: Final[dict[str, str]] = {
    'piece': '按件',
    'volume_max': '体积重取大',
    'weight': '首重续重',
}
FUL_FREIGHT_TEMPLATE_CHARGE_MODE_VALUES: Final[frozenset[str]] = frozenset(FUL_FREIGHT_TEMPLATE_CHARGE_MODE)

FUL_FREIGHT_TEMPLATE_STATUS: Final[dict[str, str]] = {
    'archived': '归档',
    'disabled': '停用',
    'enabled': '启用',
}
FUL_FREIGHT_TEMPLATE_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_FREIGHT_TEMPLATE_STATUS)

FUL_TRACE_SUB_PROVIDER: Final[dict[str, str]] = {
    'cainiao': '菜鸟',
    'kuaidi100': '快递100',
}
FUL_TRACE_SUB_PROVIDER_VALUES: Final[frozenset[str]] = frozenset(FUL_TRACE_SUB_PROVIDER)

FUL_TRACE_SUB_SUB_STATUS: Final[dict[str, str]] = {
    'closed': '已关闭',
    'failed': '订阅失败',
    'subscribed': '已订阅',
}
FUL_TRACE_SUB_SUB_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_TRACE_SUB_SUB_STATUS)

FUL_TRACE_NODE_NODE_STATUS: Final[dict[str, str]] = {
    'collected': '揽收',
    'delivering': '派送',
    'exception': '异常',
    'returned': '退签',
    'signed': '签收',
    'transit': '运输',
}
FUL_TRACE_NODE_NODE_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_TRACE_NODE_NODE_STATUS)

FUL_TRACE_NODE_SOURCE: Final[dict[str, str]] = {
    'manual': '人工登记',
    'provider': '订阅推送',
}
FUL_TRACE_NODE_SOURCE_VALUES: Final[frozenset[str]] = frozenset(FUL_TRACE_NODE_SOURCE)

FUL_WAYBILL_ACCOUNT_ACCOUNT_TYPE: Final[dict[str, str]] = {
    'cainiao': '菜鸟',
    'direct': '快递直客',
    'none': '无需面单',
    'platform': '平台系',
}
FUL_WAYBILL_ACCOUNT_ACCOUNT_TYPE_VALUES: Final[frozenset[str]] = frozenset(FUL_WAYBILL_ACCOUNT_ACCOUNT_TYPE)

FUL_WAYBILL_ACCOUNT_CIRCUIT_STATUS: Final[dict[str, str]] = {
    'closed': '正常',
    'half_open': '半开探测',
    'open': '熔断中',
}
FUL_WAYBILL_ACCOUNT_CIRCUIT_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_WAYBILL_ACCOUNT_CIRCUIT_STATUS)

FUL_WAYBILL_ACCOUNT_TEST_RESULT: Final[dict[str, str]] = {
    'fail': '失败',
    'succ': '成功',
}
FUL_WAYBILL_ACCOUNT_TEST_RESULT_VALUES: Final[frozenset[str]] = frozenset(FUL_WAYBILL_ACCOUNT_TEST_RESULT)

FUL_WAYBILL_ACCOUNT_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
FUL_WAYBILL_ACCOUNT_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_WAYBILL_ACCOUNT_STATUS)

FUL_WAYBILL_SEGMENT_STATUS: Final[dict[str, str]] = {
    'exhausted': '已耗尽',
    'in_pool': '在池',
    'partial': '部分分配',
    'returned': '已归还',
}
FUL_WAYBILL_SEGMENT_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_WAYBILL_SEGMENT_STATUS)

FUL_WAYBILL_SOURCE: Final[dict[str, str]] = {
    'manual': '人工登记',
    'oms': '默认',
    'wms': '例外仓回传登记',
}
FUL_WAYBILL_SOURCE_VALUES: Final[frozenset[str]] = frozenset(FUL_WAYBILL_SOURCE)

FUL_WAYBILL_STATUS: Final[dict[str, str]] = {
    'cancelled': '已作废',
    'expired': '已过期',
    'getting': '取号中',
    'obtained': '已取号',
    'printed': '已打印',
    'returning': '退回中',
    'used': '已使用',
}
FUL_WAYBILL_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_WAYBILL_STATUS)

FUL_PRINT_TEMPLATE_TMPL_TYPE: Final[dict[str, str]] = {
    'cloud': '云打印',
    'custom': '自定义',
    'local': '本地渲染',
    'standard': '标准',
}
FUL_PRINT_TEMPLATE_TMPL_TYPE_VALUES: Final[frozenset[str]] = frozenset(FUL_PRINT_TEMPLATE_TMPL_TYPE)

FUL_PRINT_TEMPLATE_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
FUL_PRINT_TEMPLATE_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_PRINT_TEMPLATE_STATUS)

FUL_PRINT_TMPL_BINDING_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
FUL_PRINT_TMPL_BINDING_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_PRINT_TMPL_BINDING_STATUS)

FUL_PRINT_TASK_CHANNEL: Final[dict[str, str]] = {
    'central': '集中打印',
    'store': '门店',
    'wh_client': '仓内客户端',
}
FUL_PRINT_TASK_CHANNEL_VALUES: Final[frozenset[str]] = frozenset(FUL_PRINT_TASK_CHANNEL)

FUL_PRINT_TASK_TASK_STATUS: Final[dict[str, str]] = {
    'failed': '失败',
    'pending': '待下发',
    'printed': '已打印',
    'reprinted': '已补打',
    'sent': '已下发',
}
FUL_PRINT_TASK_TASK_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_PRINT_TASK_TASK_STATUS)

FUL_PRINT_LOG_ACTION: Final[dict[str, str]] = {
    'receipt': '回执',
    'reprint': '补打',
    'resend': '重发',
    'send': '下发',
}
FUL_PRINT_LOG_ACTION_VALUES: Final[frozenset[str]] = frozenset(FUL_PRINT_LOG_ACTION)

FUL_PRINT_LOG_CHANNEL: Final[dict[str, str]] = {
    'central': '集中',
    'store': '门店',
    'wh_client': '仓内客户端',
}
FUL_PRINT_LOG_CHANNEL_VALUES: Final[frozenset[str]] = frozenset(FUL_PRINT_LOG_CHANNEL)

FUL_CARRIER_CARRIER_CODE: Final[dict[str, str]] = {
    'DADA': '达达快送',
    'FENGNIAO': '蜂鸟即配',
    'MEITUAN_PAOTUI': '美团跑腿',
    'SELF': '品牌自配送',
    'SF_CITY': '顺丰同城',
    'SHANSONG': '闪送',
}
FUL_CARRIER_CARRIER_CODE_VALUES: Final[frozenset[str]] = frozenset(FUL_CARRIER_CARRIER_CODE)

FUL_CARRIER_CARRIER_TYPE: Final[dict[str, str]] = {
    'brand_self': '品牌自配送',
    'crowdsource': '第三方众包',
    'express_city': '快递同城',
    'platform_self': '平台自营',
}
FUL_CARRIER_CARRIER_TYPE_VALUES: Final[frozenset[str]] = frozenset(FUL_CARRIER_CARRIER_TYPE)

FUL_CARRIER_CIRCUIT_STATUS: Final[dict[str, str]] = {
    'closed': '闭合',
    'half_open': '半开探测',
    'open': '开启',
}
FUL_CARRIER_CIRCUIT_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_CARRIER_CIRCUIT_STATUS)

FUL_CARRIER_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
FUL_CARRIER_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_CARRIER_STATUS)

FUL_RIDER_CALL_STATUS: Final[dict[str, str]] = {
    'accepted': '已受理',
    'call_failed': '呼叫失败',
    'called': '已呼叫',
    'cancelled': '已取消',
    'delivered': '已送达',
    'delivering': '配送中',
    'delivery_exception': '配送异常',
    'picked_up': '已取货',
    'rider_arrived': '骑手到店',
    'rider_assigned': '骑手已接单',
    'rider_cancelled': '骑手取消',
}
FUL_RIDER_CALL_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_RIDER_CALL_STATUS)

FUL_RIDER_CALL_FEE_LIABILITY: Final[dict[str, str]] = {
    'carrier': '运力方',
    'store': '门店',
    'system': '系统',
}
FUL_RIDER_CALL_FEE_LIABILITY_VALUES: Final[frozenset[str]] = frozenset(FUL_RIDER_CALL_FEE_LIABILITY)

FUL_RIDER_CALL_ASSIGN_MODE: Final[dict[str, str]] = {
    'assign': '店长指派',
    'grab': '抢单',
}
FUL_RIDER_CALL_ASSIGN_MODE_VALUES: Final[frozenset[str]] = frozenset(FUL_RIDER_CALL_ASSIGN_MODE)

FUL_RIDER_TRACK_SOURCE: Final[dict[str, str]] = {
    'callback': '回调',
    'query': '反查',
    'supplement': '补录',
}
FUL_RIDER_TRACK_SOURCE_VALUES: Final[frozenset[str]] = frozenset(FUL_RIDER_TRACK_SOURCE)

FUL_HANDOVER_VERIFY_MODE: Final[dict[str, str]] = {
    'scan': '扫码核验',
    'supplement': '补录',
}
FUL_HANDOVER_VERIFY_MODE_VALUES: Final[frozenset[str]] = frozenset(FUL_HANDOVER_VERIFY_MODE)

FUL_CITY_FREIGHT_SETTLE_STATUS: Final[dict[str, str]] = {
    'audited': '审核',
    'closed': '关账',
    'recorded': '记账',
}
FUL_CITY_FREIGHT_SETTLE_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_CITY_FREIGHT_SETTLE_STATUS)

FUL_SHOP_CARRIER_SELF_MODE: Final[dict[str, str]] = {
    'always': '始终参与比价',
    'fallback_only': '仅兜底',
}
FUL_SHOP_CARRIER_SELF_MODE_VALUES: Final[frozenset[str]] = frozenset(FUL_SHOP_CARRIER_SELF_MODE)

FUL_SHOP_CARRIER_STATUS: Final[dict[str, str]] = {
    'disabled': '停用',
    'enabled': '启用',
}
FUL_SHOP_CARRIER_STATUS_VALUES: Final[frozenset[str]] = frozenset(FUL_SHOP_CARRIER_STATUS)

# ---- oms_org ----

ORG_OWNER_CONTRACT_MODE_SNAPSHOT: Final[dict[str, str]] = {
    'BRAND_CONSIGN': 'BRAND_CONSIGN',
    'DEALER_TC': 'DEALER_TC',
    'KC_BUYOUT': 'KC_BUYOUT',
}
ORG_OWNER_CONTRACT_MODE_SNAPSHOT_VALUES: Final[frozenset[str]] = frozenset(ORG_OWNER_CONTRACT_MODE_SNAPSHOT)

ORG_PORTAL_MESSAGE_REF_TYPE: Final[dict[str, str]] = {
    'account': '等',
    'order': 'order',
    'settle': 'settle',
    'suggestion': 'suggestion',
}
ORG_PORTAL_MESSAGE_REF_TYPE_VALUES: Final[frozenset[str]] = frozenset(ORG_PORTAL_MESSAGE_REF_TYPE)

ORG_PORTAL_READ_LOG_PAGE_CODE: Final[dict[str, str]] = {
    'account': 'account',
    'aftersale': 'aftersale',
    'home': 'home',
    'msg': 'msg',
    'order': 'order',
    'settle': 'settle',
    'stock': 'stock',
    'warn': 'warn',
}
ORG_PORTAL_READ_LOG_PAGE_CODE_VALUES: Final[frozenset[str]] = frozenset(ORG_PORTAL_READ_LOG_PAGE_CODE)

AUD_OPERATION_LOG_ACTION: Final[dict[str, str]] = {
    'approve': 'approve',
    'business_event': 'business_event',
    'config_change': 'config_change',
    'create': 'create',
    'delete': 'delete',
    'export': 'export',
    'grant': 'grant',
    'login': 'login',
    'logout': 'logout',
    'revoke': 'revoke',
    'simulate': 'simulate',
    'update': 'update',
    'view_pii': 'view_pii',
}
AUD_OPERATION_LOG_ACTION_VALUES: Final[frozenset[str]] = frozenset(AUD_OPERATION_LOG_ACTION)

AUD_OPERATION_LOG_CHANNEL: Final[dict[str, str]] = {
    'api': 'api',
    'h5': 'h5',
    'mq': 'mq',
    'oa_callback': 'oa_callback',
    'scheduler': 'scheduler',
    'web': 'web',
}
AUD_OPERATION_LOG_CHANNEL_VALUES: Final[frozenset[str]] = frozenset(AUD_OPERATION_LOG_CHANNEL)

#: 全部枚举列索引：`schema.table.column` → 值标签字典
ENUM_COLUMNS: Final[dict[str, dict[Any, str]]] = {
    "oms_base.bas_event_dict.partitioned": BAS_EVENT_DICT_PARTITIONED,
    "oms_base.bas_event_dict.blocking_flag": BAS_EVENT_DICT_BLOCKING_FLAG,
    "oms_base.bas_event_dict.status": BAS_EVENT_DICT_STATUS,
    "oms_base.bas_event_outbox.status": BAS_EVENT_OUTBOX_STATUS,
    "oms_base.bas_consume_idempotent.status": BAS_CONSUME_IDEMPOTENT_STATUS,
    "oms_base.bas_dead_letter.handle_status": BAS_DEAD_LETTER_HANDLE_STATUS,
    "oms_base.bas_schedule_task.status": BAS_SCHEDULE_TASK_STATUS,
    "oms_base.bas_schedule_log.sampled": BAS_SCHEDULE_LOG_SAMPLED,
    "oms_base.bas_task_dependency.plan_date_align": BAS_TASK_DEPENDENCY_PLAN_DATE_ALIGN,
    "oms_base.bas_task_dependency.auto_trigger": BAS_TASK_DEPENDENCY_AUTO_TRIGGER,
    "oms_base.bas_task_dependency.status": BAS_TASK_DEPENDENCY_STATUS,
    "oms_base.bas_rule_dict.preset_flag": BAS_RULE_DICT_PRESET_FLAG,
    "oms_base.bas_rule_dict.status": BAS_RULE_DICT_STATUS,
    "oms_base.bas_rule.defaulted": BAS_RULE_DEFAULTED,
    "oms_base.bas_rule.status": BAS_RULE_STATUS,
    "oms_base.bas_rule_version.status": BAS_RULE_VERSION_STATUS,
    "oms_base.bas_rule_version.agent_draft": BAS_RULE_VERSION_AGENT_DRAFT,
    "oms_base.bas_rule_test_log.run_mode": BAS_RULE_TEST_LOG_RUN_MODE,
    "oms_base.bas_rule_test_log.exec_mode": BAS_RULE_TEST_LOG_EXEC_MODE,
    "oms_base.bas_rule_test_log.run_status": BAS_RULE_TEST_LOG_RUN_STATUS,
    "oms_base.bas_plugin_registry.short_circuit": BAS_PLUGIN_REGISTRY_SHORT_CIRCUIT,
    "oms_base.bas_plugin_registry.enabled": BAS_PLUGIN_REGISTRY_ENABLED,
    "oms_base.bas_entity_meta.soft_delete": BAS_ENTITY_META_SOFT_DELETE,
    "oms_base.bas_entity_meta.crud_enabled": BAS_ENTITY_META_CRUD_ENABLED,
    "oms_base.bas_entity_meta.status": BAS_ENTITY_META_STATUS,
    "oms_base.bas_field_meta.required_flag": BAS_FIELD_META_REQUIRED_FLAG,
    "oms_base.bas_field_meta.sensitive_level": BAS_FIELD_META_SENSITIVE_LEVEL,
    "oms_base.bas_field_meta.unique_flag": BAS_FIELD_META_UNIQUE_FLAG,
    "oms_base.bas_field_meta.status": BAS_FIELD_META_STATUS,
    "oms_base.bas_pipl_policy.level": BAS_PIPL_POLICY_LEVEL,
    "oms_base.bas_pipl_policy.status": BAS_PIPL_POLICY_STATUS,
    "oms_base.bas_pipl_ds_request.restricted_flag": BAS_PIPL_DS_REQUEST_RESTRICTED_FLAG,
    "oms_base.bas_pipl_ds_request.handle_status": BAS_PIPL_DS_REQUEST_HANDLE_STATUS,
    "oms_base.bas_ie_template.status": BAS_IE_TEMPLATE_STATUS,
    "oms_base.bas_import_task.status": BAS_IMPORT_TASK_STATUS,
    "oms_base.bas_export_task.sensitive_flag": BAS_EXPORT_TASK_SENSITIVE_FLAG,
    "oms_base.bas_export_task.plain_apply": BAS_EXPORT_TASK_PLAIN_APPLY,
    "oms_base.bas_export_task.status": BAS_EXPORT_TASK_STATUS,
    "oms_base.bas_notify_template.compliance_confirmed": BAS_NOTIFY_TEMPLATE_COMPLIANCE_CONFIRMED,
    "oms_base.bas_notify_template.status": BAS_NOTIFY_TEMPLATE_STATUS,
    "oms_base.bas_notify_route.denoise_flag": BAS_NOTIFY_ROUTE_DENOISE_FLAG,
    "oms_base.bas_notify_route.default_flag": BAS_NOTIFY_ROUTE_DEFAULT_FLAG,
    "oms_base.bas_notify_route.status": BAS_NOTIFY_ROUTE_STATUS,
    "oms_base.bas_notify_log.send_status": BAS_NOTIFY_LOG_SEND_STATUS,
    "oms_base.bas_alert_record.alert_level": BAS_ALERT_RECORD_ALERT_LEVEL,
    "oms_base.bas_alert_record.recovered": BAS_ALERT_RECORD_RECOVERED,
    "oms_base.bas_migration_mapping.status": BAS_MIGRATION_MAPPING_STATUS,
    "oms_order.ord_flag_change_log.change_source": ORD_FLAG_CHANGE_LOG_CHANGE_SOURCE,
    "oms_order.ord_flag_change_log.sync_status": ORD_FLAG_CHANGE_LOG_SYNC_STATUS,
    "oms_stock.inv_io_bill_type.direction": INV_IO_BILL_TYPE_DIRECTION,
    "oms_stock.inv_io_bill_type.need_wms": INV_IO_BILL_TYPE_NEED_WMS,
    "oms_stock.inv_io_bill_type.need_approval": INV_IO_BILL_TYPE_NEED_APPROVAL,
    "oms_stock.inv_io_bill_type.settle_rel": INV_IO_BILL_TYPE_SETTLE_REL,
    "oms_stock.inv_io_bill_type.status": INV_IO_BILL_TYPE_STATUS,
    "oms_stock.inv_material_cat.status": INV_MATERIAL_CAT_STATUS,
    "oms_stock.inv_brand.status": INV_BRAND_STATUS,
    "oms_stock.inv_stock_config.config_type": INV_STOCK_CONFIG_CONFIG_TYPE,
    "oms_stock.inv_stock_config.scope_type": INV_STOCK_CONFIG_SCOPE_TYPE,
    "oms_stock.inv_stock_config.status": INV_STOCK_CONFIG_STATUS,
    "oms_stock.inv_cost_config.tax_caliber": INV_COST_CONFIG_TAX_CALIBER,
    "oms_stock.inv_cost_config.branch_cost_mode": INV_COST_CONFIG_BRANCH_COST_MODE,
    "oms_stock.inv_cost_config.return_cost_mode": INV_COST_CONFIG_RETURN_COST_MODE,
    "oms_stock.inv_cost_config.freight_in_cost": INV_COST_CONFIG_FREIGHT_IN_COST,
    "oms_stock.inv_cost_config.status": INV_COST_CONFIG_STATUS,
    "oms_stock.inv_expire_rule.scope_type": INV_EXPIRE_RULE_SCOPE_TYPE,
    "oms_stock.inv_expire_rule.threshold_type": INV_EXPIRE_RULE_THRESHOLD_TYPE,
    "oms_stock.inv_expire_rule.auto_freeze": INV_EXPIRE_RULE_AUTO_FREEZE,
    "oms_stock.inv_expire_rule.status": INV_EXPIRE_RULE_STATUS,
    "oms_stock.inv_alert_rule.rule_type": INV_ALERT_RULE_RULE_TYPE,
    "oms_stock.inv_alert_rule.scope_type": INV_ALERT_RULE_SCOPE_TYPE,
    "oms_stock.inv_alert_rule.sales_caliber": INV_ALERT_RULE_SALES_CALIBER,
    "oms_stock.inv_alert_rule.promo_exclude": INV_ALERT_RULE_PROMO_EXCLUDE,
    "oms_stock.inv_alert_rule.scan_freq": INV_ALERT_RULE_SCAN_FREQ,
    "oms_stock.inv_alert_rule.status": INV_ALERT_RULE_STATUS,
    "oms_stock.inv_stocktake_plan.cycle_type": INV_STOCKTAKE_PLAN_CYCLE_TYPE,
    "oms_stock.inv_stocktake_plan.scope_type": INV_STOCKTAKE_PLAN_SCOPE_TYPE,
    "oms_stock.inv_stocktake_plan.mode": INV_STOCKTAKE_PLAN_MODE,
    "oms_stock.inv_stocktake_plan.executor": INV_STOCKTAKE_PLAN_EXECUTOR,
    "oms_stock.inv_stocktake_plan.status": INV_STOCKTAKE_PLAN_STATUS,
    "oms_stock.inv_sync_strategy.scope_type": INV_SYNC_STRATEGY_SCOPE_TYPE,
    "oms_stock.inv_sync_strategy.oversell_mode": INV_SYNC_STRATEGY_OVERSELL_MODE,
    "oms_stock.inv_sync_strategy.water_level_type": INV_SYNC_STRATEGY_WATER_LEVEL_TYPE,
    "oms_stock.inv_sync_strategy.writeback_mode": INV_SYNC_STRATEGY_WRITEBACK_MODE,
    "oms_stock.inv_sync_strategy.status": INV_SYNC_STRATEGY_STATUS,
    "oms_stock.inv_material.type": INV_MATERIAL_TYPE,
    "oms_stock.inv_material.serial_number": INV_MATERIAL_SERIAL_NUMBER,
    "oms_stock.inv_material.storage_life_flag": INV_MATERIAL_STORAGE_LIFE_FLAG,
    "oms_stock.inv_material.is_ctrl_store": INV_MATERIAL_IS_CTRL_STORE,
    "oms_stock.inv_material.omnichannel": INV_MATERIAL_OMNICHANNEL,
    "oms_stock.inv_material.is_o2o_sales": INV_MATERIAL_IS_O2O_SALES,
    "oms_stock.inv_material.status": INV_MATERIAL_STATUS,
    "oms_stock.inv_sales_material.sales_material_type": INV_SALES_MATERIAL_SALES_MATERIAL_TYPE,
    "oms_stock.inv_sales_material.bind_status": INV_SALES_MATERIAL_BIND_STATUS,
    "oms_stock.inv_sales_material.visibled": INV_SALES_MATERIAL_VISIBLED,
    "oms_stock.inv_sales_material.status": INV_SALES_MATERIAL_STATUS,
    "oms_stock.inv_bom_version.status": INV_BOM_VERSION_STATUS,
    "oms_stock.inv_barcode.barcode_type": INV_BARCODE_BARCODE_TYPE,
    "oms_stock.inv_barcode.status": INV_BARCODE_STATUS,
    "oms_stock.inv_fukubukuro_plan.status": INV_FUKUBUKURO_PLAN_STATUS,
    "oms_stock.inv_pickone_candidate.select_type": INV_PICKONE_CANDIDATE_SELECT_TYPE,
    "oms_stock.inv_stock_ledger.is_locked": INV_STOCK_LEDGER_IS_LOCKED,
    "oms_stock.inv_stock_ledger.status": INV_STOCK_LEDGER_STATUS,
    "oms_stock.inv_stock_adjust.adjust_type": INV_STOCK_ADJUST_ADJUST_TYPE,
    "oms_stock.inv_stock_adjust.approval_status": INV_STOCK_ADJUST_APPROVAL_STATUS,
    "oms_stock.inv_stock_adjust.status": INV_STOCK_ADJUST_STATUS,
    "oms_stock.inv_stock_recon_diff.recon_type": INV_STOCK_RECON_DIFF_RECON_TYPE,
    "oms_stock.inv_stock_recon_diff.status": INV_STOCK_RECON_DIFF_STATUS,
    "oms_stock.inv_freeze_log.obj_type": INV_FREEZE_LOG_OBJ_TYPE,
    "oms_stock.inv_freeze_log.status": INV_FREEZE_LOG_STATUS,
    "oms_stock.inv_freeze_log.is_compensated": INV_FREEZE_LOG_IS_COMPENSATED,
    "oms_stock.inv_manual_freeze.approval_status": INV_MANUAL_FREEZE_APPROVAL_STATUS,
    "oms_stock.inv_manual_freeze.status": INV_MANUAL_FREEZE_STATUS,
    "oms_stock.inv_io_bill.direction": INV_IO_BILL_DIRECTION,
    "oms_stock.inv_io_bill.status": INV_IO_BILL_STATUS,
    "oms_stock.inv_io_bill.settle_status": INV_IO_BILL_SETTLE_STATUS,
    "oms_stock.inv_io_bill.approval_status": INV_IO_BILL_APPROVAL_STATUS,
    "oms_stock.inv_io_callback_log.callback_type": INV_IO_CALLBACK_LOG_CALLBACK_TYPE,
    "oms_stock.inv_io_callback_log.status": INV_IO_CALLBACK_LOG_STATUS,
    "oms_stock.inv_transfer_order.reason": INV_TRANSFER_ORDER_REASON,
    "oms_stock.inv_transfer_order.status": INV_TRANSFER_ORDER_STATUS,
    "oms_stock.inv_transfer_order.arrival_sellable": INV_TRANSFER_ORDER_ARRIVAL_SELLABLE,
    "oms_stock.inv_transfer_order.diff_type": INV_TRANSFER_ORDER_DIFF_TYPE,
    "oms_stock.inv_transfer_order.approval_status": INV_TRANSFER_ORDER_APPROVAL_STATUS,
    "oms_stock.inv_lend_rule.scope_type": INV_LEND_RULE_SCOPE_TYPE,
    "oms_stock.inv_lend_rule.settle_price_type": INV_LEND_RULE_SETTLE_PRICE_TYPE,
    "oms_stock.inv_lend_rule.move_type": INV_LEND_RULE_MOVE_TYPE,
    "oms_stock.inv_lend_rule.status": INV_LEND_RULE_STATUS,
    "oms_stock.inv_lend_rule.approval_status": INV_LEND_RULE_APPROVAL_STATUS,
    "oms_stock.inv_lend_ledger.status": INV_LEND_LEDGER_STATUS,
    "oms_stock.inv_lend_ledger.settle_status": INV_LEND_LEDGER_SETTLE_STATUS,
    "oms_stock.inv_ownership_transfer.status": INV_OWNERSHIP_TRANSFER_STATUS,
    "oms_stock.inv_ownership_transfer.approval_status": INV_OWNERSHIP_TRANSFER_APPROVAL_STATUS,
    "oms_stock.inv_stocktake_task.mode": INV_STOCKTAKE_TASK_MODE,
    "oms_stock.inv_stocktake_task.executor": INV_STOCKTAKE_TASK_EXECUTOR,
    "oms_stock.inv_stocktake_task.trigger_type": INV_STOCKTAKE_TASK_TRIGGER_TYPE,
    "oms_stock.inv_stocktake_task.status": INV_STOCKTAKE_TASK_STATUS,
    "oms_stock.inv_stocktake_task.approval_status": INV_STOCKTAKE_TASK_APPROVAL_STATUS,
    "oms_stock.inv_stocktake_item.recount_flag": INV_STOCKTAKE_ITEM_RECOUNT_FLAG,
    "oms_stock.inv_stocktake_item.diff_reason": INV_STOCKTAKE_ITEM_DIFF_REASON,
    "oms_stock.inv_stocktake_item.suspect_mixup": INV_STOCKTAKE_ITEM_SUSPECT_MIXUP,
    "oms_stock.inv_cost_change_log.change_type": INV_COST_CHANGE_LOG_CHANGE_TYPE,
    "oms_stock.inv_cost_change_log.estimate_flag": INV_COST_CHANGE_LOG_ESTIMATE_FLAG,
    "oms_stock.inv_cost_change_log.cost_estimated": INV_COST_CHANGE_LOG_COST_ESTIMATED,
    "oms_stock.inv_estimate_batch.status": INV_ESTIMATE_BATCH_STATUS,
    "oms_stock.inv_sellable_snapshot.sync_status": INV_SELLABLE_SNAPSHOT_SYNC_STATUS,
    "oms_stock.inv_sync_log.trigger_type": INV_SYNC_LOG_TRIGGER_TYPE,
    "oms_stock.inv_sync_log.sync_status": INV_SYNC_LOG_SYNC_STATUS,
    "oms_stock.inv_batch.status": INV_BATCH_STATUS,
    "oms_stock.inv_batch_stock.near_expire_level": INV_BATCH_STOCK_NEAR_EXPIRE_LEVEL,
    "oms_stock.inv_batch_assign.strategy": INV_BATCH_ASSIGN_STRATEGY,
    "oms_stock.inv_batch_assign.is_match": INV_BATCH_ASSIGN_IS_MATCH,
    "oms_stock.inv_serial_no.status": INV_SERIAL_NO_STATUS,
    "oms_stock.inv_expire_disposal.disposal_type": INV_EXPIRE_DISPOSAL_DISPOSAL_TYPE,
    "oms_stock.inv_expire_disposal.approval_status": INV_EXPIRE_DISPOSAL_APPROVAL_STATUS,
    "oms_stock.inv_expire_disposal.status": INV_EXPIRE_DISPOSAL_STATUS,
    "oms_stock.inv_replenish_suggestion.suggest_type": INV_REPLENISH_SUGGESTION_SUGGEST_TYPE,
    "oms_stock.inv_replenish_suggestion.alert_level": INV_REPLENISH_SUGGESTION_ALERT_LEVEL,
    "oms_stock.inv_replenish_suggestion.status": INV_REPLENISH_SUGGESTION_STATUS,
    "oms_stock.inv_replenish_suggestion.ignore_reason": INV_REPLENISH_SUGGESTION_IGNORE_REASON,
    "oms_stock.inv_sales_forecast.degrade_flag": INV_SALES_FORECAST_DEGRADE_FLAG,
    "oms_stock.inv_price_archive.below_floor_flag": INV_PRICE_ARCHIVE_BELOW_FLOOR_FLAG,
    "oms_stock.inv_price_archive.status": INV_PRICE_ARCHIVE_STATUS,
    "oms_stock.inv_price_version.sync_flag": INV_PRICE_VERSION_SYNC_FLAG,
    "oms_stock.inv_price_adjust_plan.expire_writeback": INV_PRICE_ADJUST_PLAN_EXPIRE_WRITEBACK,
    "oms_stock.inv_price_adjust_item.below_floor": INV_PRICE_ADJUST_ITEM_BELOW_FLOOR,
    "oms_stock.inv_price_sync_task.alert_flag": INV_PRICE_SYNC_TASK_ALERT_FLAG,
    "oms_aftersale.aft_reason_dict.duty_party": AFT_REASON_DICT_DUTY_PARTY,
    "oms_aftersale.aft_reason_dict.audit_white": AFT_REASON_DICT_AUDIT_WHITE,
    "oms_aftersale.aft_reason_dict.reject_suggest": AFT_REASON_DICT_REJECT_SUGGEST,
    "oms_aftersale.aft_reason_dict.status": AFT_REASON_DICT_STATUS,
    "oms_aftersale.aft_return_address.address_type": AFT_RETURN_ADDRESS_ADDRESS_TYPE,
    "oms_aftersale.aft_return_address.status": AFT_RETURN_ADDRESS_STATUS,
    "oms_aftersale.aft_auto_audit_rule.action_type": AFT_AUTO_AUDIT_RULE_ACTION_TYPE,
    "oms_aftersale.aft_auto_audit_rule.rescue_flag": AFT_AUTO_AUDIT_RULE_RESCUE_FLAG,
    "oms_aftersale.aft_auto_audit_rule.defaulted": AFT_AUTO_AUDIT_RULE_DEFAULTED,
    "oms_aftersale.aft_auto_audit_rule.status": AFT_AUTO_AUDIT_RULE_STATUS,
    "oms_aftersale.aft_return_apply.aftersale_type": AFT_RETURN_APPLY_AFTERSALE_TYPE,
    "oms_aftersale.aft_return_apply.reship_only": AFT_RETURN_APPLY_RESHIP_ONLY,
    "oms_aftersale.aft_return_apply.status": AFT_RETURN_APPLY_STATUS,
    "oms_aftersale.aft_return_apply.goods_status": AFT_RETURN_APPLY_GOODS_STATUS,
    "oms_aftersale.aft_return_apply.is_archived_order": AFT_RETURN_APPLY_IS_ARCHIVED_ORDER,
    "oms_aftersale.aft_return_apply.warn_level": AFT_RETURN_APPLY_WARN_LEVEL,
    "oms_aftersale.aft_return_apply.sync_status": AFT_RETURN_APPLY_SYNC_STATUS,
    "oms_aftersale.aft_return_apply.auto_agreed_by_platform": AFT_RETURN_APPLY_AUTO_AGREED_BY_PLATFORM,
    "oms_aftersale.aft_return_apply.audit_channel": AFT_RETURN_APPLY_AUDIT_CHANNEL,
    "oms_aftersale.aft_return_apply_item.gift_flag": AFT_RETURN_APPLY_ITEM_GIFT_FLAG,
    "oms_aftersale.aft_return_apply_log.operator_type": AFT_RETURN_APPLY_LOG_OPERATOR_TYPE,
    "oms_aftersale.aft_reship.reship_type": AFT_RESHIP_RESHIP_TYPE,
    "oms_aftersale.aft_reship.status": AFT_RESHIP_STATUS,
    "oms_aftersale.aft_reship.sn_check_status": AFT_RESHIP_SN_CHECK_STATUS,
    "oms_aftersale.aft_reship.diff_status": AFT_RESHIP_DIFF_STATUS,
    "oms_aftersale.aft_reship.close_type": AFT_RESHIP_CLOSE_TYPE,
    "oms_aftersale.aft_reship_item.refund_trigger_status": AFT_RESHIP_ITEM_REFUND_TRIGGER_STATUS,
    "oms_aftersale.aft_reship_item.diff_flag": AFT_RESHIP_ITEM_DIFF_FLAG,
    "oms_aftersale.aft_reship_sn.check_stage": AFT_RESHIP_SN_CHECK_STAGE,
    "oms_aftersale.aft_reship_sn.check_result": AFT_RESHIP_SN_CHECK_RESULT,
    "oms_aftersale.aft_reship_sn.swap_suspect_flag": AFT_RESHIP_SN_SWAP_SUSPECT_FLAG,
    "oms_aftersale.aft_reship_sn.before_sn_status": AFT_RESHIP_SN_BEFORE_SN_STATUS,
    "oms_aftersale.aft_reship_sn.handle_result": AFT_RESHIP_SN_HANDLE_RESULT,
    "oms_aftersale.aft_defect_disposal.disposal_type": AFT_DEFECT_DISPOSAL_DISPOSAL_TYPE,
    "oms_aftersale.aft_defect_disposal.approval_status": AFT_DEFECT_DISPOSAL_APPROVAL_STATUS,
    "oms_aftersale.aft_defect_disposal.status": AFT_DEFECT_DISPOSAL_STATUS,
    "oms_aftersale.aft_return_logistics.trace_status": AFT_RETURN_LOGISTICS_TRACE_STATUS,
    "oms_aftersale.aft_return_logistics.warn_flag": AFT_RETURN_LOGISTICS_WARN_FLAG,
    "oms_aftersale.aft_refund.status": AFT_REFUND_STATUS,
    "oms_aftersale.aft_refund.channel": AFT_REFUND_CHANNEL,
    "oms_aftersale.aft_refund.platform_intervened": AFT_REFUND_PLATFORM_INTERVENED,
    "oms_aftersale.aft_refund.loss_type": AFT_REFUND_LOSS_TYPE,
    "oms_aftersale.aft_refund.audit_channel": AFT_REFUND_AUDIT_CHANNEL,
    "oms_aftersale.aft_refund.risk_flag": AFT_REFUND_RISK_FLAG,
    "oms_aftersale.aft_refund.ledger_status": AFT_REFUND_LEDGER_STATUS,
    "oms_aftersale.aft_refund_alloc.is_last_line": AFT_REFUND_ALLOC_IS_LAST_LINE,
    "oms_aftersale.aft_refund_log.operator_type": AFT_REFUND_LOG_OPERATOR_TYPE,
    "oms_aftersale.aft_exchange.exchange_type": AFT_EXCHANGE_EXCHANGE_TYPE,
    "oms_aftersale.aft_exchange.reship_only": AFT_EXCHANGE_RESHIP_ONLY,
    "oms_aftersale.aft_exchange.status": AFT_EXCHANGE_STATUS,
    "oms_aftersale.aft_exchange.diff_type": AFT_EXCHANGE_DIFF_TYPE,
    "oms_aftersale.aft_exchange.diff_status": AFT_EXCHANGE_DIFF_STATUS,
    "oms_aftersale.aft_exchange.sn_reentry_policy": AFT_EXCHANGE_SN_REENTRY_POLICY,
    "oms_aftersale.aft_exchange_log.operator_type": AFT_EXCHANGE_LOG_OPERATOR_TYPE,
    "oms_aftersale.aft_auto_audit_log.decision": AFT_AUTO_AUDIT_LOG_DECISION,
    "oms_aftersale.aft_auto_audit_log.risk_flag": AFT_AUTO_AUDIT_LOG_RISK_FLAG,
    "oms_aftersale.aft_auto_audit_log.deadline_rescue": AFT_AUTO_AUDIT_LOG_DEADLINE_RESCUE,
    "oms_aftersale.aft_auto_audit_log.manual_final_decision": AFT_AUTO_AUDIT_LOG_MANUAL_FINAL_DECISION,
    "oms_aftersale.aft_auto_audit_log.overturn_flag": AFT_AUTO_AUDIT_LOG_OVERTURN_FLAG,
    "oms_aftersale.aft_audit_task.task_type": AFT_AUDIT_TASK_TASK_TYPE,
    "oms_aftersale.aft_audit_task.priority": AFT_AUDIT_TASK_PRIORITY,
    "oms_aftersale.aft_audit_task.status": AFT_AUDIT_TASK_STATUS,
    "oms_aftersale.aft_audit_task.result": AFT_AUDIT_TASK_RESULT,
    "oms_aftersale.aft_risk_flag.dim_type": AFT_RISK_FLAG_DIM_TYPE,
    "oms_aftersale.aft_risk_flag.blacklist_flag": AFT_RISK_FLAG_BLACKLIST_FLAG,
    "oms_aftersale.aft_risk_flag.high_freq_flag": AFT_RISK_FLAG_HIGH_FREQ_FLAG,
    "oms_aftersale.aft_risk_flag.calibrate_status": AFT_RISK_FLAG_CALIBRATE_STATUS,
    "oms_aftersale.aft_timeout_monitor.aftersale_type": AFT_TIMEOUT_MONITOR_AFTERSALE_TYPE,
    "oms_aftersale.aft_timeout_monitor.warn_level": AFT_TIMEOUT_MONITOR_WARN_LEVEL,
    "oms_aftersale.aft_timeout_monitor.escalate_flag": AFT_TIMEOUT_MONITOR_ESCALATE_FLAG,
    "oms_aftersale.aft_timeout_monitor.auto_agreed_flag": AFT_TIMEOUT_MONITOR_AUTO_AGREED_FLAG,
    "oms_aftersale.aft_timeout_monitor.loss_review_flag": AFT_TIMEOUT_MONITOR_LOSS_REVIEW_FLAG,
    "oms_aftersale.aft_timeout_monitor.status": AFT_TIMEOUT_MONITOR_STATUS,
    "oms_aftersale.aft_buyer_profile.appeal_status": AFT_BUYER_PROFILE_APPEAL_STATUS,
    "oms_purchase.pur_dict.status": PUR_DICT_STATUS,
    "oms_purchase.pur_supplier.status": PUR_SUPPLIER_STATUS,
    "oms_purchase.pur_supplier.pay_type": PUR_SUPPLIER_PAY_TYPE,
    "oms_purchase.pur_supplier.settle_type": PUR_SUPPLIER_SETTLE_TYPE,
    "oms_purchase.pur_supply_relation.tax_flag": PUR_SUPPLY_RELATION_TAX_FLAG,
    "oms_purchase.pur_supply_relation.is_default": PUR_SUPPLY_RELATION_IS_DEFAULT,
    "oms_purchase.pur_supply_relation.status": PUR_SUPPLY_RELATION_STATUS,
    "oms_purchase.pur_supply_price_log.tax_flag": PUR_SUPPLY_PRICE_LOG_TAX_FLAG,
    "oms_purchase.pur_request.request_type": PUR_REQUEST_REQUEST_TYPE,
    "oms_purchase.pur_request.status": PUR_REQUEST_STATUS,
    "oms_purchase.pur_request.approval_result": PUR_REQUEST_APPROVAL_RESULT,
    "oms_purchase.pur_request.close_reason": PUR_REQUEST_CLOSE_REASON,
    "oms_purchase.pur_request_item.source_type": PUR_REQUEST_ITEM_SOURCE_TYPE,
    "oms_purchase.pur_request_item.item_status": PUR_REQUEST_ITEM_ITEM_STATUS,
    "oms_purchase.pur_order.source_type": PUR_ORDER_SOURCE_TYPE,
    "oms_purchase.pur_order.po_type": PUR_ORDER_PO_TYPE,
    "oms_purchase.pur_order.audit_status": PUR_ORDER_AUDIT_STATUS,
    "oms_purchase.pur_order.inbound_status": PUR_ORDER_INBOUND_STATUS,
    "oms_purchase.pur_order.purchase_status": PUR_ORDER_PURCHASE_STATUS,
    "oms_purchase.pur_order.settle_status": PUR_ORDER_SETTLE_STATUS,
    "oms_purchase.pur_order.damage_status": PUR_ORDER_DAMAGE_STATUS,
    "oms_purchase.pur_order.wms_sync_status": PUR_ORDER_WMS_SYNC_STATUS,
    "oms_purchase.pur_order.terminate_flag": PUR_ORDER_TERMINATE_FLAG,
    "oms_purchase.pur_order.emergency": PUR_ORDER_EMERGENCY,
    "oms_purchase.pur_order.supplier_confirm_flag": PUR_ORDER_SUPPLIER_CONFIRM_FLAG,
    "oms_purchase.pur_order_item.item_status": PUR_ORDER_ITEM_ITEM_STATUS,
    "oms_purchase.pur_order_fee.fee_type": PUR_ORDER_FEE_FEE_TYPE,
    "oms_purchase.pur_order_fee.alloc_type": PUR_ORDER_FEE_ALLOC_TYPE,
    "oms_purchase.pur_arrival_plan.deviation_flag": PUR_ARRIVAL_PLAN_DEVIATION_FLAG,
    "oms_purchase.pur_arrival_plan.status": PUR_ARRIVAL_PLAN_STATUS,
    "oms_purchase.pur_order_change.change_type": PUR_ORDER_CHANGE_CHANGE_TYPE,
    "oms_purchase.pur_order_change.reaudit_flag": PUR_ORDER_CHANGE_REAUDIT_FLAG,
    "oms_purchase.pur_order_change.status": PUR_ORDER_CHANGE_STATUS,
    "oms_purchase.pur_arrival.out_of_plan_flag": PUR_ARRIVAL_OUT_OF_PLAN_FLAG,
    "oms_purchase.pur_arrival.status": PUR_ARRIVAL_STATUS,
    "oms_purchase.pur_arrival.source_type": PUR_ARRIVAL_SOURCE_TYPE,
    "oms_purchase.pur_receipt.estimate_flag": PUR_RECEIPT_ESTIMATE_FLAG,
    "oms_purchase.pur_receipt.bill_status": PUR_RECEIPT_BILL_STATUS,
    "oms_purchase.pur_receipt.settle_status": PUR_RECEIPT_SETTLE_STATUS,
    "oms_purchase.pur_receipt_item.quality_result": PUR_RECEIPT_ITEM_QUALITY_RESULT,
    "oms_purchase.pur_receipt_item.estimate_flag": PUR_RECEIPT_ITEM_ESTIMATE_FLAG,
    "oms_purchase.pur_damage.damage_reason": PUR_DAMAGE_DAMAGE_REASON,
    "oms_purchase.pur_damage.claim_flag": PUR_DAMAGE_CLAIM_FLAG,
    "oms_purchase.pur_damage.claim_object_type": PUR_DAMAGE_CLAIM_OBJECT_TYPE,
    "oms_purchase.pur_damage.claim_result": PUR_DAMAGE_CLAIM_RESULT,
    "oms_purchase.pur_damage.status": PUR_DAMAGE_STATUS,
    "oms_purchase.pur_diff_decision.diff_type": PUR_DIFF_DECISION_DIFF_TYPE,
    "oms_purchase.pur_diff_decision.decision": PUR_DIFF_DECISION_DECISION,
    "oms_purchase.pur_diff_decision.status": PUR_DIFF_DECISION_STATUS,
    "oms_purchase.pur_payable.accrual_strategy": PUR_PAYABLE_ACCRUAL_STRATEGY,
    "oms_purchase.pur_payable.estimate_flag": PUR_PAYABLE_ESTIMATE_FLAG,
    "oms_purchase.pur_payable.settle_status": PUR_PAYABLE_SETTLE_STATUS,
    "oms_purchase.pur_payable.status": PUR_PAYABLE_STATUS,
    "oms_purchase.pur_statement.check_result": PUR_STATEMENT_CHECK_RESULT,
    "oms_purchase.pur_statement.close_status": PUR_STATEMENT_CLOSE_STATUS,
    "oms_purchase.pur_statement.recon_confirm_status": PUR_STATEMENT_RECON_CONFIRM_STATUS,
    "oms_purchase.pur_statement_item.object_type": PUR_STATEMENT_ITEM_OBJECT_TYPE,
    "oms_purchase.pur_statement_item.direction": PUR_STATEMENT_ITEM_DIRECTION,
    "oms_purchase.pur_invoice.match_status": PUR_INVOICE_MATCH_STATUS,
    "oms_purchase.pur_invoice.estimate_reversed": PUR_INVOICE_ESTIMATE_REVERSED,
    "oms_purchase.pur_invoice.status": PUR_INVOICE_STATUS,
    "oms_purchase.pur_invoice_match.match_result": PUR_INVOICE_MATCH_MATCH_RESULT,
    "oms_purchase.pur_payment.pay_type": PUR_PAYMENT_PAY_TYPE,
    "oms_purchase.pur_payment.status": PUR_PAYMENT_STATUS,
    "oms_purchase.pur_payment.kd_push_status": PUR_PAYMENT_KD_PUSH_STATUS,
    "oms_purchase.pur_payment_verify.direction": PUR_PAYMENT_VERIFY_DIRECTION,
    "oms_purchase.pur_payment_verify.fifo_flag": PUR_PAYMENT_VERIFY_FIFO_FLAG,
    "oms_purchase.pur_payment_verify.kd_reverse_flag": PUR_PAYMENT_VERIFY_KD_REVERSE_FLAG,
    "oms_purchase.pur_recon_diff.diff_type": PUR_RECON_DIFF_DIFF_TYPE,
    "oms_purchase.pur_recon_diff.handle_path": PUR_RECON_DIFF_HANDLE_PATH,
    "oms_purchase.pur_recon_diff.force_verify_flag": PUR_RECON_DIFF_FORCE_VERIFY_FLAG,
    "oms_purchase.pur_recon_diff.status": PUR_RECON_DIFF_STATUS,
    "oms_dealer.dlr_price_type.tax_mode": DLR_PRICE_TYPE_TAX_MODE,
    "oms_dealer.dlr_price_type.status": DLR_PRICE_TYPE_STATUS,
    "oms_dealer.dlr_dealer.dealer_level": DLR_DEALER_DEALER_LEVEL,
    "oms_dealer.dlr_dealer.coop_mode": DLR_DEALER_COOP_MODE,
    "oms_dealer.dlr_dealer.status": DLR_DEALER_STATUS,
    "oms_dealer.dlr_dealer_shop.shop_type": DLR_DEALER_SHOP_SHOP_TYPE,
    "oms_dealer.dlr_dealer_shop.is_dropship": DLR_DEALER_SHOP_IS_DROPSHIP,
    "oms_dealer.dlr_dealer_shop.status": DLR_DEALER_SHOP_STATUS,
    "oms_dealer.dlr_credit_account.over_policy": DLR_CREDIT_ACCOUNT_OVER_POLICY,
    "oms_dealer.dlr_credit_account.status": DLR_CREDIT_ACCOUNT_STATUS,
    "oms_dealer.dlr_credit_txn.txn_type": DLR_CREDIT_TXN_TXN_TYPE,
    "oms_dealer.dlr_credit_txn.direction": DLR_CREDIT_TXN_DIRECTION,
    "oms_dealer.dlr_credit_period.start_anchor": DLR_CREDIT_PERIOD_START_ANCHOR,
    "oms_dealer.dlr_credit_period.status": DLR_CREDIT_PERIOD_STATUS,
    "oms_dealer.dlr_product_auth.auth_level": DLR_PRODUCT_AUTH_AUTH_LEVEL,
    "oms_dealer.dlr_product_auth.delivery_mode": DLR_PRODUCT_AUTH_DELIVERY_MODE,
    "oms_dealer.dlr_product_auth.status": DLR_PRODUCT_AUTH_STATUS,
    "oms_dealer.dlr_sales_order.channel": DLR_SALES_ORDER_CHANNEL,
    "oms_dealer.dlr_sales_order.pay_mode": DLR_SALES_ORDER_PAY_MODE,
    "oms_dealer.dlr_sales_order.amount_caliber": DLR_SALES_ORDER_AMOUNT_CALIBER,
    "oms_dealer.dlr_sales_order.allow_split": DLR_SALES_ORDER_ALLOW_SPLIT,
    "oms_dealer.dlr_sales_order.status": DLR_SALES_ORDER_STATUS,
    "oms_dealer.dlr_sales_order.close_reason": DLR_SALES_ORDER_CLOSE_REASON,
    "oms_dealer.dlr_sales_order.convert_status": DLR_SALES_ORDER_CONVERT_STATUS,
    "oms_dealer.dlr_sales_order_item.moq_check": DLR_SALES_ORDER_ITEM_MOQ_CHECK,
    "oms_dealer.dlr_sales_order_item.status": DLR_SALES_ORDER_ITEM_STATUS,
    "oms_dealer.dlr_price_list.status": DLR_PRICE_LIST_STATUS,
    "oms_dealer.dlr_price_change.action": DLR_PRICE_CHANGE_ACTION,
    "oms_dealer.dlr_price_change.approval_level": DLR_PRICE_CHANGE_APPROVAL_LEVEL,
    "oms_dealer.dlr_price_change.approval_status": DLR_PRICE_CHANGE_APPROVAL_STATUS,
    "oms_dealer.dlr_transfer_order.source_type": DLR_TRANSFER_ORDER_SOURCE_TYPE,
    "oms_dealer.dlr_transfer_order.transfer_status": DLR_TRANSFER_ORDER_TRANSFER_STATUS,
    "oms_dealer.dlr_transfer_order.channel_type": DLR_TRANSFER_ORDER_CHANNEL_TYPE,
    "oms_dealer.dlr_transfer_order_item.dropship_flag": DLR_TRANSFER_ORDER_ITEM_DROPSHIP_FLAG,
    "oms_dealer.dlr_transfer_order_item.status": DLR_TRANSFER_ORDER_ITEM_STATUS,
    "oms_dealer.dlr_dropship_ledger.object_type": DLR_DROPSHIP_LEDGER_OBJECT_TYPE,
    "oms_dealer.dlr_dropship_ledger.direction": DLR_DROPSHIP_LEDGER_DIRECTION,
    "oms_dealer.dlr_dropship_ledger.settle_price_type": DLR_DROPSHIP_LEDGER_SETTLE_PRICE_TYPE,
    "oms_dealer.dlr_dropship_ledger.settle_status": DLR_DROPSHIP_LEDGER_SETTLE_STATUS,
    "oms_finance.fin_dict.status": FIN_DICT_STATUS,
    "oms_finance.fin_gap_account.need_handle": FIN_GAP_ACCOUNT_NEED_HANDLE,
    "oms_finance.fin_gap_account.status": FIN_GAP_ACCOUNT_STATUS,
    "oms_finance.fin_credit_period.status": FIN_CREDIT_PERIOD_STATUS,
    "oms_finance.fin_settle_config.platform_in_settle": FIN_SETTLE_CONFIG_PLATFORM_IN_SETTLE,
    "oms_finance.fin_settle_config.zero_period_skip": FIN_SETTLE_CONFIG_ZERO_PERIOD_SKIP,
    "oms_finance.fin_settle_config.status": FIN_SETTLE_CONFIG_STATUS,
    "oms_finance.fin_service_fee_rule.with_refund": FIN_SERVICE_FEE_RULE_WITH_REFUND,
    "oms_finance.fin_service_fee_rule.status": FIN_SERVICE_FEE_RULE_STATUS,
    "oms_finance.fin_invoice_channel.status": FIN_INVOICE_CHANNEL_STATUS,
    "oms_finance.fin_code_mapping.direction": FIN_CODE_MAPPING_DIRECTION,
    "oms_finance.fin_code_mapping.gap_flag": FIN_CODE_MAPPING_GAP_FLAG,
    "oms_finance.fin_code_mapping.status": FIN_CODE_MAPPING_STATUS,
    "oms_finance.fin_kingdee_adapter.status": FIN_KINGDEE_ADAPTER_STATUS,
    "oms_finance.fin_receivable.settle_status": FIN_RECEIVABLE_SETTLE_STATUS,
    "oms_finance.fin_receivable.settle_carry_next": FIN_RECEIVABLE_SETTLE_CARRY_NEXT,
    "oms_finance.fin_receivable.lend_flag": FIN_RECEIVABLE_LEND_FLAG,
    "oms_finance.fin_receivable.platform_intervened": FIN_RECEIVABLE_PLATFORM_INTERVENED,
    "oms_finance.fin_receivable.wait_link_flag": FIN_RECEIVABLE_WAIT_LINK_FLAG,
    "oms_finance.fin_platform_bill_item.direction": FIN_PLATFORM_BILL_ITEM_DIRECTION,
    "oms_finance.fin_platform_bill_item.split_status": FIN_PLATFORM_BILL_ITEM_SPLIT_STATUS,
    "oms_finance.fin_bill_diff.auto_judge": FIN_BILL_DIFF_AUTO_JUDGE,
    "oms_finance.fin_platform_fee.settle_status": FIN_PLATFORM_FEE_SETTLE_STATUS,
    "oms_finance.fin_platform_fee.reverse_flag": FIN_PLATFORM_FEE_REVERSE_FLAG,
    "oms_finance.fin_ar_ledger.check_status": FIN_AR_LEDGER_CHECK_STATUS,
    "oms_finance.fin_settlement.owner_type": FIN_SETTLEMENT_OWNER_TYPE,
    "oms_finance.fin_settlement.net_direction": FIN_SETTLEMENT_NET_DIRECTION,
    "oms_finance.fin_settlement.kd_push_status": FIN_SETTLEMENT_KD_PUSH_STATUS,
    "oms_finance.fin_settlement.period_lock": FIN_SETTLEMENT_PERIOD_LOCK,
    "oms_finance.fin_settlement_item.lend_direction": FIN_SETTLEMENT_ITEM_LEND_DIRECTION,
    "oms_finance.fin_receipt.direction": FIN_RECEIPT_DIRECTION,
    "oms_finance.fin_write_off.writeoff_type": FIN_WRITE_OFF_WRITEOFF_TYPE,
    "oms_finance.fin_write_off.auto_flag": FIN_WRITE_OFF_AUTO_FLAG,
    "oms_finance.fin_write_off.reverse_flag": FIN_WRITE_OFF_REVERSE_FLAG,
    "oms_finance.fin_error_table.diff_direction": FIN_ERROR_TABLE_DIFF_DIRECTION,
    "oms_finance.fin_freight_bill_item.tolerance_result": FIN_FREIGHT_BILL_ITEM_TOLERANCE_RESULT,
    "oms_finance.fin_invoice_apply.buyer_type": FIN_INVOICE_APPLY_BUYER_TYPE,
    "oms_finance.fin_invoice_pool.condition_type": FIN_INVOICE_POOL_CONDITION_TYPE,
    "oms_finance.fin_invoice.color": FIN_INVOICE_COLOR,
    "oms_finance.fin_invoice.issuer_type": FIN_INVOICE_ISSUER_TYPE,
    "oms_finance.fin_kingdee_supply.feed_type": FIN_KINGDEE_SUPPLY_FEED_TYPE,
    "oms_finance.fin_kingdee_supply_file.encrypt_flag": FIN_KINGDEE_SUPPLY_FILE_ENCRYPT_FLAG,
    "oms_finance.fin_kingdee_supply_file.notify_flag": FIN_KINGDEE_SUPPLY_FILE_NOTIFY_FLAG,
    "oms_finance.fin_kingdee_receipt.check_result": FIN_KINGDEE_RECEIPT_CHECK_RESULT,
    "oms_finance.fin_kingdee_receipt.timeout_alert": FIN_KINGDEE_RECEIPT_TIMEOUT_ALERT,
    "oms_org.org_node.status": ORG_NODE_STATUS,
    "oms_org.org_node_relation.is_primary": ORG_NODE_RELATION_IS_PRIMARY,
    "oms_org.org_node_relation.status": ORG_NODE_RELATION_STATUS,
    "oms_org.org_owner.status": ORG_OWNER_STATUS,
    "oms_org.org_owner_contract.status": ORG_OWNER_CONTRACT_STATUS,
    "oms_org.org_owner_settle_config.settle_period_type": ORG_OWNER_SETTLE_CONFIG_SETTLE_PERIOD_TYPE,
    "oms_org.org_owner_settle_config.payment_start_basis": ORG_OWNER_SETTLE_CONFIG_PAYMENT_START_BASIS,
    "oms_org.org_owner_settle_config.status": ORG_OWNER_SETTLE_CONFIG_STATUS,
    "oms_org.org_shop_owner_transfer.approval_status": ORG_SHOP_OWNER_TRANSFER_APPROVAL_STATUS,
    "oms_org.org_shop_owner_transfer.status": ORG_SHOP_OWNER_TRANSFER_STATUS,
    "oms_org.org_tenant.status": ORG_TENANT_STATUS,
    "oms_org.org_account.status": ORG_ACCOUNT_STATUS,
    "oms_org.org_account_credential.must_change_pwd": ORG_ACCOUNT_CREDENTIAL_MUST_CHANGE_PWD,
    "oms_org.org_account_credential.status": ORG_ACCOUNT_CREDENTIAL_STATUS,
    "oms_org.org_session.status": ORG_SESSION_STATUS,
    "oms_org.org_session.login_result": ORG_SESSION_LOGIN_RESULT,
    "oms_org.org_role.portal_flag": ORG_ROLE_PORTAL_FLAG,
    "oms_org.org_role.status": ORG_ROLE_STATUS,
    "oms_org.org_idp_config.enabled": ORG_IDP_CONFIG_ENABLED,
    "oms_org.org_perm_point.internal_only": ORG_PERM_POINT_INTERNAL_ONLY,
    "oms_org.org_perm_point.portal_visible": ORG_PERM_POINT_PORTAL_VISIBLE,
    "oms_org.org_perm_point.status": ORG_PERM_POINT_STATUS,
    "oms_org.org_data_permission.status": ORG_DATA_PERMISSION_STATUS,
    "oms_org.org_filterable_entity.status": ORG_FILTERABLE_ENTITY_STATUS,
    "oms_org.org_field_perm.portal_forbidden": ORG_FIELD_PERM_PORTAL_FORBIDDEN,
    "oms_org.org_field_perm.status": ORG_FIELD_PERM_STATUS,
    "oms_org.org_perm_violation.audit_pushed": ORG_PERM_VIOLATION_AUDIT_PUSHED,
    "oms_org.org_portal_account.audit_status": ORG_PORTAL_ACCOUNT_AUDIT_STATUS,
    "oms_org.org_portal_message.read_status": ORG_PORTAL_MESSAGE_READ_STATUS,
    "oms_org.org_portal_read_log.sampled": ORG_PORTAL_READ_LOG_SAMPLED,
    "oms_org.org_approval_scene.default_need": ORG_APPROVAL_SCENE_DEFAULT_NEED,
    "oms_org.org_approval_scene.fixed_must": ORG_APPROVAL_SCENE_FIXED_MUST,
    "oms_org.org_approval_scene.stub_mode": ORG_APPROVAL_SCENE_STUB_MODE,
    "oms_org.org_approval_scene.status": ORG_APPROVAL_SCENE_STATUS,
    "oms_org.org_approval_threshold.need_approval": ORG_APPROVAL_THRESHOLD_NEED_APPROVAL,
    "oms_org.org_approval_threshold.status": ORG_APPROVAL_THRESHOLD_STATUS,
    "oms_org.org_approval_instance.urgent_flag": ORG_APPROVAL_INSTANCE_URGENT_FLAG,
    "oms_org.org_approval_instance.auto_flag": ORG_APPROVAL_INSTANCE_AUTO_FLAG,
    "oms_org.org_approval_instance.status": ORG_APPROVAL_INSTANCE_STATUS,
    "oms_org.org_approval_instance.execute_check_status": ORG_APPROVAL_INSTANCE_EXECUTE_CHECK_STATUS,
    "oms_org.org_oa_callback_log.direction": ORG_OA_CALLBACK_LOG_DIRECTION,
    "oms_org.org_oa_callback_log.sign_verified": ORG_OA_CALLBACK_LOG_SIGN_VERIFIED,
    "oms_org.org_oa_callback_log.process_status": ORG_OA_CALLBACK_LOG_PROCESS_STATUS,
    "oms_org.aud_operation_log.sensitive_level": AUD_OPERATION_LOG_SENSITIVE_LEVEL,
    "oms_org.aud_data_access_log.risk_flag": AUD_DATA_ACCESS_LOG_RISK_FLAG,
    "oms_org.aud_data_access_log.anonymized": AUD_DATA_ACCESS_LOG_ANONYMIZED,
    "oms_org.aud_entity_registry.status": AUD_ENTITY_REGISTRY_STATUS,
    "oms_org.aud_hash_anchor.verify_status": AUD_HASH_ANCHOR_VERIFY_STATUS,
    "oms_org.aud_retention_policy.policy_level": AUD_RETENTION_POLICY_POLICY_LEVEL,
    "oms_org.aud_retention_policy.status": AUD_RETENTION_POLICY_STATUS,
    "oms_report.rpt_indicator_dict.status": RPT_INDICATOR_DICT_STATUS,
    "oms_report.rpt_snapshot_task.status": RPT_SNAPSHOT_TASK_STATUS,
    "oms_report.rpt_snapshot_task.rerun_flag": RPT_SNAPSHOT_TASK_RERUN_FLAG,
    "oms_report.rpt_product_sale_rank.window_type": RPT_PRODUCT_SALE_RANK_WINDOW_TYPE,
    "oms_report.rpt_product_sale_rank.rank_type": RPT_PRODUCT_SALE_RANK_RANK_TYPE,
    "oms_report.rpt_stock_snapshot.owner_type": RPT_STOCK_SNAPSHOT_OWNER_TYPE,
    "oms_report.rpt_stock_age.age_bucket": RPT_STOCK_AGE_AGE_BUCKET,
    "oms_report.rpt_near_expire.expire_level": RPT_NEAR_EXPIRE_EXPIRE_LEVEL,
    "oms_report.rpt_near_expire.disposal_status": RPT_NEAR_EXPIRE_DISPOSAL_STATUS,
    "oms_report.rpt_stockout.age_level": RPT_STOCKOUT_AGE_LEVEL,
    "oms_report.rpt_stockout.suggest_status": RPT_STOCKOUT_SUGGEST_STATUS,
    "oms_report.rpt_timeout_alert.status": RPT_TIMEOUT_ALERT_STATUS,
    "oms_report.rpt_aftersale.apply_type": RPT_AFTERSALE_APPLY_TYPE,
    "oms_report.rpt_aftersale.denominator_type": RPT_AFTERSALE_DENOMINATOR_TYPE,
    "oms_report.rpt_profit.category_level": RPT_PROFIT_CATEGORY_LEVEL,
    "oms_report.rpt_profit.freight_caliber": RPT_PROFIT_FREIGHT_CALIBER,
    "oms_report.rpt_profit.period_locked": RPT_PROFIT_PERIOD_LOCKED,
    "oms_report.rpt_service_fee.net_direction": RPT_SERVICE_FEE_NET_DIRECTION,
    "oms_report.rpt_order_wide.order_type": RPT_ORDER_WIDE_ORDER_TYPE,
    "oms_report.rpt_order_wide.audit_mode": RPT_ORDER_WIDE_AUDIT_MODE,
    "oms_report.rpt_order_wide.has_aftersale": RPT_ORDER_WIDE_HAS_AFTERSALE,
    "oms_report.rpt_order_wide.aftersale_type": RPT_ORDER_WIDE_AFTERSALE_TYPE,
    "oms_report.rpt_order_wide.refund_status": RPT_ORDER_WIDE_REFUND_STATUS,
    "oms_report.rpt_order_wide.qc_good_flag": RPT_ORDER_WIDE_QC_GOOD_FLAG,
    "oms_report.rpt_order_wide.platform_intervened": RPT_ORDER_WIDE_PLATFORM_INTERVENED,
    "oms_report.rpt_stock_wide.owner_type": RPT_STOCK_WIDE_OWNER_TYPE,
    "oms_report.rpt_stock_wide.slow_moving_flag": RPT_STOCK_WIDE_SLOW_MOVING_FLAG,
    "oms_report.rpt_settlement_wide.owner_type": RPT_SETTLEMENT_WIDE_OWNER_TYPE,
    "oms_report.rpt_settlement_wide.redflush_flag": RPT_SETTLEMENT_WIDE_REDFLUSH_FLAG,
    "oms_report.rpt_settlement_wide.net_direction": RPT_SETTLEMENT_WIDE_NET_DIRECTION,
    "oms_report.rpt_settlement_wide.status": RPT_SETTLEMENT_WIDE_STATUS,
    "oms_report.rpt_bi_push_log.batch_type": RPT_BI_PUSH_LOG_BATCH_TYPE,
    "oms_report.rpt_bi_push_log.channel": RPT_BI_PUSH_LOG_CHANNEL,
    "oms_report.rpt_bi_push_log.status": RPT_BI_PUSH_LOG_STATUS,
    "oms_report.rpt_bi_push_log.recon_status": RPT_BI_PUSH_LOG_RECON_STATUS,
    "oms_report.rpt_monitor_metric.alert_mark": RPT_MONITOR_METRIC_ALERT_MARK,
    "oms_report.rpt_monitor_metric.reg_status": RPT_MONITOR_METRIC_REG_STATUS,
    "oms_report.rpt_alert_claim.alert_level": RPT_ALERT_CLAIM_ALERT_LEVEL,
    "oms_report.rpt_alert_claim.status": RPT_ALERT_CLAIM_STATUS,
    "oms_report.rpt_alert_claim.escalate_level": RPT_ALERT_CLAIM_ESCALATE_LEVEL,
    "oms_base.bas_rule_condition.op_code": BAS_RULE_CONDITION_OP_CODE,
    "oms_base.bas_field_meta.value_type": BAS_FIELD_META_VALUE_TYPE,
    "oms_base.bas_ie_template.domain_code": BAS_IE_TEMPLATE_DOMAIN_CODE,
    "oms_base.bas_notify_log.msg_class": BAS_NOTIFY_LOG_MSG_CLASS,
    "oms_gateway.gw_platform_config.platform": GW_PLATFORM_CONFIG_PLATFORM,
    "oms_gateway.gw_platform_config.status": GW_PLATFORM_CONFIG_STATUS,
    "oms_gateway.gw_platform_config.source": GW_PLATFORM_CONFIG_SOURCE,
    "oms_gateway.gw_adapter_config.status": GW_ADAPTER_CONFIG_STATUS,
    "oms_gateway.gw_enum_mapping.map_type": GW_ENUM_MAPPING_MAP_TYPE,
    "oms_gateway.gw_enum_mapping.status": GW_ENUM_MAPPING_STATUS,
    "oms_gateway.gw_ratelimit_config.scope_type": GW_RATELIMIT_CONFIG_SCOPE_TYPE,
    "oms_gateway.gw_ratelimit_config.status": GW_RATELIMIT_CONFIG_STATUS,
    "oms_gateway.gw_shop.platform": GW_SHOP_PLATFORM,
    "oms_gateway.gw_shop.shop_type": GW_SHOP_SHOP_TYPE,
    "oms_gateway.gw_shop.business_type": GW_SHOP_BUSINESS_TYPE,
    "oms_gateway.gw_shop.auth_status": GW_SHOP_AUTH_STATUS,
    "oms_gateway.gw_shop.auth_mode": GW_SHOP_AUTH_MODE,
    "oms_gateway.gw_shop.auth_url_track": GW_SHOP_AUTH_URL_TRACK,
    "oms_gateway.gw_shop.status": GW_SHOP_STATUS,
    "oms_gateway.gw_shop.source": GW_SHOP_SOURCE,
    "oms_gateway.gw_shop_auth.session_enc": GW_SHOP_AUTH_SESSION_ENC,
    "oms_gateway.gw_shop_auth.status": oms_gateway_GW_SHOP_AUTH_STATUS,
    "oms_gateway.gw_shop_config.back_node": GW_SHOP_CONFIG_BACK_NODE,
    "oms_gateway.gw_credential_audit.action": GW_CREDENTIAL_AUDIT_ACTION,
    "oms_gateway.gw_credential_audit.result": GW_CREDENTIAL_AUDIT_RESULT,
    "oms_gateway.gw_api_log.err_level": GW_API_LOG_ERR_LEVEL,
    "oms_gateway.gw_api_log.source": GW_API_LOG_SOURCE,
    "oms_gateway.gw_rpc_pending.status": GW_RPC_PENDING_STATUS,
    "oms_gateway.gw_api_fail.obj_type": GW_API_FAIL_OBJ_TYPE,
    "oms_gateway.gw_api_fail.err_level": GW_API_FAIL_ERR_LEVEL,
    "oms_gateway.gw_api_fail.status": GW_API_FAIL_STATUS,
    "oms_gateway.gw_api_fail.resolved_by": GW_API_FAIL_RESOLVED_BY,
    "oms_gateway.gw_errcode_dict.err_level": GW_ERRCODE_DICT_ERR_LEVEL,
    "oms_gateway.gw_errcode_dict.status": GW_ERRCODE_DICT_STATUS,
    "oms_gateway.gw_order_buffer.canonical_status": GW_ORDER_BUFFER_CANONICAL_STATUS,
    "oms_gateway.gw_order_buffer.receiver_encrypted_channel": GW_ORDER_BUFFER_RECEIVER_ENCRYPTED_CHANNEL,
    "oms_gateway.gw_order_buffer.deliver_status": GW_ORDER_BUFFER_DELIVER_STATUS,
    "oms_gateway.gw_order_buffer.source": GW_ORDER_BUFFER_SOURCE,
    "oms_gateway.gw_order_buffer_item.refund_status": GW_ORDER_BUFFER_ITEM_REFUND_STATUS,
    "oms_gateway.gw_order_buffer_promotion.promotion_type": GW_ORDER_BUFFER_PROMOTION_PROMOTION_TYPE,
    "oms_gateway.gw_order_buffer_promotion.bear_by": GW_ORDER_BUFFER_PROMOTION_BEAR_BY,
    "oms_gateway.gw_msg_notify.msg_type": GW_MSG_NOTIFY_MSG_TYPE,
    "oms_gateway.gw_msg_notify.route_target": GW_MSG_NOTIFY_ROUTE_TARGET,
    "oms_gateway.gw_msg_notify.status": GW_MSG_NOTIFY_STATUS,
    "oms_gateway.gw_pull_watermark.channel": GW_PULL_WATERMARK_CHANNEL,
    "oms_gateway.gw_writeback_task.sync_type": GW_WRITEBACK_TASK_SYNC_TYPE,
    "oms_gateway.gw_writeback_task.action": GW_WRITEBACK_TASK_ACTION,
    "oms_gateway.gw_writeback_task.back_node": GW_WRITEBACK_TASK_BACK_NODE,
    "oms_gateway.gw_writeback_task.status": GW_WRITEBACK_TASK_STATUS,
    "oms_gateway.gw_writeback_task.err_level": GW_WRITEBACK_TASK_ERR_LEVEL,
    "oms_gateway.gw_stock_sync_batch.status": GW_STOCK_SYNC_BATCH_STATUS,
    "oms_gateway.gw_stock_sync_item.status": GW_STOCK_SYNC_ITEM_STATUS,
    "oms_gateway.gw_recon_diff.reconcile_type": GW_RECON_DIFF_RECONCILE_TYPE,
    "oms_gateway.gw_recon_diff.result": GW_RECON_DIFF_RESULT,
    "oms_gateway.gw_openapi_app.quota_level": GW_OPENAPI_APP_QUOTA_LEVEL,
    "oms_gateway.gw_openapi_app.status": GW_OPENAPI_APP_STATUS,
    "oms_gateway.gw_openapi_app.audit_status": GW_OPENAPI_APP_AUDIT_STATUS,
    "oms_gateway.gw_openapi_register.domain": GW_OPENAPI_REGISTER_DOMAIN,
    "oms_gateway.gw_openapi_register.rw_type": GW_OPENAPI_REGISTER_RW_TYPE,
    "oms_gateway.gw_openapi_register.quota_level": GW_OPENAPI_REGISTER_QUOTA_LEVEL,
    "oms_gateway.gw_openapi_register.status": GW_OPENAPI_REGISTER_STATUS,
    "oms_gateway.gw_openapi_log.result": GW_OPENAPI_LOG_RESULT,
    "oms_order.ord_order.createway": ORD_ORDER_CREATEWAY,
    "oms_order.ord_order.order_type": ORD_ORDER_ORDER_TYPE,
    "oms_order.ord_order.order_status": ORD_ORDER_ORDER_STATUS,
    "oms_order.ord_order.audit_status": ORD_ORDER_AUDIT_STATUS,
    "oms_order.ord_order.fulfill_status": ORD_ORDER_FULFILL_STATUS,
    "oms_order.ord_order.pay_status": ORD_ORDER_PAY_STATUS,
    "oms_order.ord_order.ship_status": ORD_ORDER_SHIP_STATUS,
    "oms_order.ord_order.promotion_source": ORD_ORDER_PROMOTION_SOURCE,
    "oms_order.ord_order.cross_border_type": ORD_ORDER_CROSS_BORDER_TYPE,
    "oms_order.ord_order.declare_status": ORD_ORDER_DECLARE_STATUS,
    "oms_order.ord_order.archive_flag": ORD_ORDER_ARCHIVE_FLAG,
    "oms_order.ord_order.source": ORD_ORDER_SOURCE,
    "oms_order.ord_order_item.parse_status": ORD_ORDER_ITEM_PARSE_STATUS,
    "oms_order.ord_order_pmt.pmt_type": ORD_ORDER_PMT_PMT_TYPE,
    "oms_order.ord_order_pmt.bearer": ORD_ORDER_PMT_BEARER,
    "oms_order.ord_order_invoice.invoice_type": ORD_ORDER_INVOICE_INVOICE_TYPE,
    "oms_order.ord_order_invoice.title_type": ORD_ORDER_INVOICE_TITLE_TYPE,
    "oms_order.ord_order_invoice.invoice_status": ORD_ORDER_INVOICE_INVOICE_STATUS,
    "oms_order.ord_status_log.status_domain": ORD_STATUS_LOG_STATUS_DOMAIN,
    "oms_order.ord_order_fail.fail_code": ORD_ORDER_FAIL_FAIL_CODE,
    "oms_order.ord_order_fail.handle_status": ORD_ORDER_FAIL_HANDLE_STATUS,
    "oms_order.ord_audit_rule.pass_action": ORD_AUDIT_RULE_PASS_ACTION,
    "oms_order.ord_audit_rule.status": ORD_AUDIT_RULE_STATUS,
    "oms_order.ord_fulfill_plan.plan_status": ORD_FULFILL_PLAN_PLAN_STATUS,
    "oms_order.ord_fulfill_plan.exec_status": ORD_FULFILL_PLAN_EXEC_STATUS,
    "oms_order.ord_fulfill_plan.fail_code": ORD_FULFILL_PLAN_FAIL_CODE,
    "oms_order.ord_audit_reason.plugin_name": ORD_AUDIT_REASON_PLUGIN_NAME,
    "oms_order.ord_audit_reason.level": ORD_AUDIT_REASON_LEVEL,
    "oms_order.ord_audit_reason.suggest_action": ORD_AUDIT_REASON_SUGGEST_ACTION,
    "oms_order.ord_audit_reason.route_target": ORD_AUDIT_REASON_ROUTE_TARGET,
    "oms_order.ord_audit_reason.handle_status": ORD_AUDIT_REASON_HANDLE_STATUS,
    "oms_order.ord_audit_plugin_perf.phase": ORD_AUDIT_PLUGIN_PERF_PHASE,
    "oms_order.ord_audit_plugin_perf.result": ORD_AUDIT_PLUGIN_PERF_RESULT,
    "oms_order.ord_dispatch_rule.strategy": ORD_DISPATCH_RULE_STRATEGY,
    "oms_order.ord_dispatch_rule.status": ORD_DISPATCH_RULE_STATUS,
    "oms_order.ord_audit_group.status": ORD_AUDIT_GROUP_STATUS,
    "oms_order.ord_audit_task.assign_way": ORD_AUDIT_TASK_ASSIGN_WAY,
    "oms_order.ord_audit_task.task_status": ORD_AUDIT_TASK_TASK_STATUS,
    "oms_order.ord_audit_task.result": ORD_AUDIT_TASK_RESULT,
    "oms_order.ord_audit_work_log.action": ORD_AUDIT_WORK_LOG_ACTION,
    "oms_order.ord_split_rule.split_type": ORD_SPLIT_RULE_SPLIT_TYPE,
    "oms_order.ord_split_rule.scope_type": ORD_SPLIT_RULE_SCOPE_TYPE,
    "oms_order.ord_split_rule.confirm_source": ORD_SPLIT_RULE_CONFIRM_SOURCE,
    "oms_order.ord_split_rule.status": ORD_SPLIT_RULE_STATUS,
    "oms_order.ord_split_trace.source": ORD_SPLIT_TRACE_SOURCE,
    "oms_order.ord_split_trace.result_status": ORD_SPLIT_TRACE_RESULT_STATUS,
    "oms_order.ord_split_trace.err_code": ORD_SPLIT_TRACE_ERR_CODE,
    "oms_order.ord_combine_group.status": ORD_COMBINE_GROUP_STATUS,
    "oms_order.ord_combine_group.source": ORD_COMBINE_GROUP_SOURCE,
    "oms_order.ord_combine_blacklist.level": ORD_COMBINE_BLACKLIST_LEVEL,
    "oms_order.ord_combine_blacklist.rule": ORD_COMBINE_BLACKLIST_RULE,
    "oms_order.ord_dispatch_plan.mode": ORD_DISPATCH_PLAN_MODE,
    "oms_order.ord_dispatch_plan.source": ORD_DISPATCH_PLAN_SOURCE,
    "oms_order.ord_dispatch_plan.status": ORD_DISPATCH_PLAN_STATUS,
    "oms_order.ord_dispatch_plan.lack_route": ORD_DISPATCH_PLAN_LACK_ROUTE,
    "oms_order.ord_branch_dispatch_rule.strategy_type": ORD_BRANCH_DISPATCH_RULE_STRATEGY_TYPE,
    "oms_order.ord_branch_dispatch_rule.status": ORD_BRANCH_DISPATCH_RULE_STATUS,
    "oms_order.ord_delivery.status": ORD_DELIVERY_STATUS,
    "oms_order.ord_delivery.sync_status": ORD_DELIVERY_SYNC_STATUS,
    "oms_order.ord_delivery.source": ORD_DELIVERY_SOURCE,
    "oms_order.ord_delivery_log.command": ORD_DELIVERY_LOG_COMMAND,
    "oms_order.ord_delivery_diff.diff_type": ORD_DELIVERY_DIFF_DIFF_TYPE,
    "oms_order.ord_delivery_diff.liability": ORD_DELIVERY_DIFF_LIABILITY,
    "oms_order.ord_delivery_diff.handle_way": ORD_DELIVERY_DIFF_HANDLE_WAY,
    "oms_order.ord_delivery_diff.handle_status": ORD_DELIVERY_DIFF_HANDLE_STATUS,
    "oms_order.ord_order_modify.modify_type": ORD_ORDER_MODIFY_MODIFY_TYPE,
    "oms_order.ord_order_modify.source": ORD_ORDER_MODIFY_SOURCE,
    "oms_order.ord_order_modify.status": ORD_ORDER_MODIFY_STATUS,
    "oms_order.ord_order_modify.recall_status": ORD_ORDER_MODIFY_RECALL_STATUS,
    "oms_order.ord_modify_log.action": ORD_MODIFY_LOG_ACTION,
    "oms_order.ord_modify_log.source": ORD_MODIFY_LOG_SOURCE,
    "oms_order.ord_retrial.retrial_type": ORD_RETRIAL_RETRIAL_TYPE,
    "oms_order.ord_retrial.status": ORD_RETRIAL_STATUS,
    "oms_order.ord_abnormal.exc_category": ORD_ABNORMAL_EXC_CATEGORY,
    "oms_order.ord_abnormal.source": ORD_ABNORMAL_SOURCE,
    "oms_order.ord_abnormal.status": ORD_ABNORMAL_STATUS,
    "oms_order.ord_abnormal.resolve_action": ORD_ABNORMAL_RESOLVE_ACTION,
    "oms_order.ord_abnormal_type_dict.category": ORD_ABNORMAL_TYPE_DICT_CATEGORY,
    "oms_order.ord_stockout.strategy_status": ORD_STOCKOUT_STRATEGY_STATUS,
    "oms_order.ord_oversold_batch.stage": ORD_OVERSOLD_BATCH_STAGE,
    "oms_order.ord_pause_command_log.command": ORD_PAUSE_COMMAND_LOG_COMMAND,
    "oms_order.ord_pause_command_log.result": ORD_PAUSE_COMMAND_LOG_RESULT,
    "oms_order.ord_risk_list.list_type": ORD_RISK_LIST_LIST_TYPE,
    "oms_order.ord_risk_list.dimension": ORD_RISK_LIST_DIMENSION,
    "oms_order.ord_risk_list.value_type": ORD_RISK_LIST_VALUE_TYPE,
    "oms_order.ord_risk_list.scope": ORD_RISK_LIST_SCOPE,
    "oms_order.ord_presale.presale_status": ORD_PRESALE_PRESALE_STATUS,
    "oms_order.ord_presale.reserve_mode": ORD_PRESALE_RESERVE_MODE,
    "oms_order.ord_groupon.groupon_status": ORD_GROUPON_GROUPON_STATUS,
    "oms_order.ord_luckybag_alloc.dispatch_mode": ORD_LUCKYBAG_ALLOC_DISPATCH_MODE,
    "oms_order.ord_luckybag_alloc.dispatch_result": ORD_LUCKYBAG_ALLOC_DISPATCH_RESULT,
    "oms_order.ord_card_secret.status": ORD_CARD_SECRET_STATUS,
    "oms_order.ord_virtual_delivery.sync_channel": ORD_VIRTUAL_DELIVERY_SYNC_CHANNEL,
    "oms_order.ord_virtual_delivery.sync_status": ORD_VIRTUAL_DELIVERY_SYNC_STATUS,
    "oms_order.ord_store_profile.biz_status": ORD_STORE_PROFILE_BIZ_STATUS,
    "oms_order.ord_store_order.fulfill_mode": ORD_STORE_ORDER_FULFILL_MODE,
    "oms_order.ord_store_order.accept_status": ORD_STORE_ORDER_ACCEPT_STATUS,
    "oms_order.ord_pickup.status": ORD_PICKUP_STATUS,
    "oms_order.ord_pickup.overdue_action": ORD_PICKUP_OVERDUE_ACTION,
    "oms_order.ord_declare.declare_mode": ORD_DECLARE_DECLARE_MODE,
    "oms_order.ord_declare.declare_status": ORD_DECLARE_DECLARE_STATUS,
    "oms_order.ord_declare.fail_reason_code": ORD_DECLARE_FAIL_REASON_CODE,
    "oms_order.ord_order_archive.archive_status": ORD_ORDER_ARCHIVE_ARCHIVE_STATUS,
    "oms_order.ord_order_archive.archive_source": ORD_ORDER_ARCHIVE_ARCHIVE_SOURCE,
    "oms_order.ord_archive_log.log_type": ORD_ARCHIVE_LOG_LOG_TYPE,
    "oms_order.ord_archive_log.trigger_source": ORD_ARCHIVE_LOG_TRIGGER_SOURCE,
    "oms_order.ord_archive_log.result": ORD_ARCHIVE_LOG_RESULT,
    "oms_order.ord_archive_config.scope_level": ORD_ARCHIVE_CONFIG_SCOPE_LEVEL,
    "oms_order.ord_shop_fulfill_config.lack_fulfill_mode": ORD_SHOP_FULFILL_CONFIG_LACK_FULFILL_MODE,
    "oms_order.ord_shop_fulfill_config.lend_auto_mode": ORD_SHOP_FULFILL_CONFIG_LEND_AUTO_MODE,
    "oms_order.ord_shop_fulfill_config.monitor_mode": ORD_SHOP_FULFILL_CONFIG_MONITOR_MODE,
    "oms_order.ord_shop_fulfill_config.presale_reserve_mode": ORD_SHOP_FULFILL_CONFIG_PRESALE_RESERVE_MODE,
    "oms_order.ord_shop_fulfill_config.luckybag_aftersale_mode": ORD_SHOP_FULFILL_CONFIG_LUCKYBAG_AFTERSALE_MODE,
    "oms_order.ord_shop_fulfill_config.pickup_overdue_action": ORD_SHOP_FULFILL_CONFIG_PICKUP_OVERDUE_ACTION,
    "oms_order.ord_shop_fulfill_config.o2o_fallback": ORD_SHOP_FULFILL_CONFIG_O2O_FALLBACK,
    "oms_order.ord_reason_code_dict.level": ORD_REASON_CODE_DICT_LEVEL,
    "oms_order.ord_reason_code_dict.default_route": ORD_REASON_CODE_DICT_DEFAULT_ROUTE,
    "oms_order.ord_reason_code_dict.default_suggest": ORD_REASON_CODE_DICT_DEFAULT_SUGGEST,
    "oms_order.ord_promotion_activity.activity_type": ORD_PROMOTION_ACTIVITY_ACTIVITY_TYPE,
    "oms_order.ord_promotion_activity.gift_lack_policy": ORD_PROMOTION_ACTIVITY_GIFT_LACK_POLICY,
    "oms_order.ord_promotion_activity.status": ORD_PROMOTION_ACTIVITY_STATUS,
    "oms_order.ord_promotion_rule.threshold_type": ORD_PROMOTION_RULE_THRESHOLD_TYPE,
    "oms_order.ord_promotion_rule.discount_type": ORD_PROMOTION_RULE_DISCOUNT_TYPE,
    "oms_order.ord_promotion_scope.direction": ORD_PROMOTION_SCOPE_DIRECTION,
    "oms_order.ord_promotion_scope.scope_type": ORD_PROMOTION_SCOPE_SCOPE_TYPE,
    "oms_order.ord_promotion_scope.role": ORD_PROMOTION_SCOPE_ROLE,
    "oms_order.ord_gift_log.log_type": ORD_GIFT_LOG_LOG_TYPE,
    "oms_order.ord_gift_log.revoke_reason": ORD_GIFT_LOG_REVOKE_REASON,
    "oms_order.ord_gift_log.ADD": ORD_GIFT_LOG_ADD,
    "oms_order.ord_instant_delivery.orchestrate_status": ORD_INSTANT_DELIVERY_ORCHESTRATE_STATUS,
    "oms_order.ord_instant_track.liability": ORD_INSTANT_TRACK_LIABILITY,
    "oms_order.ord_instant_track.bearer": ORD_INSTANT_TRACK_BEARER,
    "oms_order.ord_routing_decision_log.decision_mode": ORD_ROUTING_DECISION_LOG_DECISION_MODE,
    "oms_order.ord_routing_decision_log.MODIFY": ORD_ROUTING_DECISION_LOG_MODIFY,
    "oms_stock.inv_stock_recon_diff.change_field": INV_STOCK_RECON_DIFF_CHANGE_FIELD,
    "oms_stock.inv_activity_lock_pool.status": INV_ACTIVITY_LOCK_POOL_STATUS,
    "oms_stock.inv_sales_forecast.adopt_strategy": INV_SALES_FORECAST_ADOPT_STRATEGY,
    "oms_stock.inv_sales_forecast.call_status": INV_SALES_FORECAST_CALL_STATUS,
    "oms_stock.inv_price_sync_task.platform": INV_PRICE_SYNC_TASK_PLATFORM,
    "oms_finance.fin_kingdee_adapter.auth_type": FIN_KINGDEE_ADAPTER_AUTH_TYPE,
    "oms_finance.fin_invoice_pool.source": FIN_INVOICE_POOL_SOURCE,
    "oms_fulfill.ful_branch.branch_type": FUL_BRANCH_BRANCH_TYPE,
    "oms_fulfill.ful_branch.status": FUL_BRANCH_STATUS,
    "oms_fulfill.ful_branch.source": FUL_BRANCH_SOURCE,
    "oms_fulfill.ful_wms.wms_code": FUL_WMS_WMS_CODE,
    "oms_fulfill.ful_wms.status": FUL_WMS_STATUS,
    "oms_fulfill.ful_wms_binding.protocol": FUL_WMS_BINDING_PROTOCOL,
    "oms_fulfill.ful_wms_binding.env": FUL_WMS_BINDING_ENV,
    "oms_fulfill.ful_wms_binding.status": FUL_WMS_BINDING_STATUS,
    "oms_fulfill.ful_wms_health.circuit_status": FUL_WMS_HEALTH_CIRCUIT_STATUS,
    "oms_fulfill.ful_route_log.result": FUL_ROUTE_LOG_RESULT,
    "oms_fulfill.ful_cmd_fail.cmd_type": FUL_CMD_FAIL_CMD_TYPE,
    "oms_fulfill.ful_cmd_fail.err_class": FUL_CMD_FAIL_ERR_CLASS,
    "oms_fulfill.ful_cmd_fail.circuit_snapshot": FUL_CMD_FAIL_CIRCUIT_SNAPSHOT,
    "oms_fulfill.ful_cmd_fail.status": FUL_CMD_FAIL_STATUS,
    "oms_fulfill.ful_cmd_fail.resolved_by": FUL_CMD_FAIL_RESOLVED_BY,
    "oms_fulfill.ful_outbound_cmd.cmd_type": FUL_OUTBOUND_CMD_CMD_TYPE,
    "oms_fulfill.ful_outbound_cmd.source": FUL_OUTBOUND_CMD_SOURCE,
    "oms_fulfill.ful_outbound_callback.callback_type": FUL_OUTBOUND_CALLBACK_CALLBACK_TYPE,
    "oms_fulfill.ful_outbound_callback.reject_reason": FUL_OUTBOUND_CALLBACK_REJECT_REASON,
    "oms_fulfill.ful_outbound_callback.process_status": FUL_OUTBOUND_CALLBACK_PROCESS_STATUS,
    "oms_fulfill.ful_outbound_buffer.status": FUL_OUTBOUND_BUFFER_STATUS,
    "oms_fulfill.ful_channel_log.action": FUL_CHANNEL_LOG_ACTION,
    "oms_fulfill.ful_channel_log.err_class": FUL_CHANNEL_LOG_ERR_CLASS,
    "oms_fulfill.ful_inbound_cmd.bill_type": FUL_INBOUND_CMD_BILL_TYPE,
    "oms_fulfill.ful_inbound_cmd.source_type": FUL_INBOUND_CMD_SOURCE_TYPE,
    "oms_fulfill.ful_inbound_cmd.status": FUL_INBOUND_CMD_STATUS,
    "oms_fulfill.ful_inbound_callback.callback_type": FUL_INBOUND_CALLBACK_CALLBACK_TYPE,
    "oms_fulfill.ful_inbound_callback.process_status": FUL_INBOUND_CALLBACK_PROCESS_STATUS,
    "oms_fulfill.ful_inbound_diff.diff_type": FUL_INBOUND_DIFF_DIFF_TYPE,
    "oms_fulfill.ful_inbound_diff.handle_status": FUL_INBOUND_DIFF_HANDLE_STATUS,
    "oms_fulfill.ful_inbound_diff.source_notify_status": FUL_INBOUND_DIFF_SOURCE_NOTIFY_STATUS,
    "oms_fulfill.ful_dly_corp.corp_code": FUL_DLY_CORP_CORP_CODE,
    "oms_fulfill.ful_dly_corp.corp_type": FUL_DLY_CORP_CORP_TYPE,
    "oms_fulfill.ful_dly_corp.waybill_account_type": FUL_DLY_CORP_WAYBILL_ACCOUNT_TYPE,
    "oms_fulfill.ful_dly_corp.pickup_mode": FUL_DLY_CORP_PICKUP_MODE,
    "oms_fulfill.ful_dly_corp.status": FUL_DLY_CORP_STATUS,
    "oms_fulfill.ful_dly_product.product_type": FUL_DLY_PRODUCT_PRODUCT_TYPE,
    "oms_fulfill.ful_dly_product.status": FUL_DLY_PRODUCT_STATUS,
    "oms_fulfill.ful_area_router.status": FUL_AREA_ROUTER_STATUS,
    "oms_fulfill.ful_unreach_area.status": FUL_UNREACH_AREA_STATUS,
    "oms_fulfill.ful_suspend.status": FUL_SUSPEND_STATUS,
    "oms_fulfill.ful_addr_keyword.level": FUL_ADDR_KEYWORD_LEVEL,
    "oms_fulfill.ful_addr_keyword.status": FUL_ADDR_KEYWORD_STATUS,
    "oms_fulfill.ful_shop_dly.status": FUL_SHOP_DLY_STATUS,
    "oms_fulfill.ful_branch_dly.status": FUL_BRANCH_DLY_STATUS,
    "oms_fulfill.ful_freight_template.charge_mode": FUL_FREIGHT_TEMPLATE_CHARGE_MODE,
    "oms_fulfill.ful_freight_template.status": FUL_FREIGHT_TEMPLATE_STATUS,
    "oms_fulfill.ful_trace_sub.provider": FUL_TRACE_SUB_PROVIDER,
    "oms_fulfill.ful_trace_sub.sub_status": FUL_TRACE_SUB_SUB_STATUS,
    "oms_fulfill.ful_trace_node.node_status": FUL_TRACE_NODE_NODE_STATUS,
    "oms_fulfill.ful_trace_node.source": FUL_TRACE_NODE_SOURCE,
    "oms_fulfill.ful_waybill_account.account_type": FUL_WAYBILL_ACCOUNT_ACCOUNT_TYPE,
    "oms_fulfill.ful_waybill_account.circuit_status": FUL_WAYBILL_ACCOUNT_CIRCUIT_STATUS,
    "oms_fulfill.ful_waybill_account.test_result": FUL_WAYBILL_ACCOUNT_TEST_RESULT,
    "oms_fulfill.ful_waybill_account.status": FUL_WAYBILL_ACCOUNT_STATUS,
    "oms_fulfill.ful_waybill_segment.status": FUL_WAYBILL_SEGMENT_STATUS,
    "oms_fulfill.ful_waybill.source": FUL_WAYBILL_SOURCE,
    "oms_fulfill.ful_waybill.status": FUL_WAYBILL_STATUS,
    "oms_fulfill.ful_print_template.tmpl_type": FUL_PRINT_TEMPLATE_TMPL_TYPE,
    "oms_fulfill.ful_print_template.status": FUL_PRINT_TEMPLATE_STATUS,
    "oms_fulfill.ful_print_tmpl_binding.status": FUL_PRINT_TMPL_BINDING_STATUS,
    "oms_fulfill.ful_print_task.channel": FUL_PRINT_TASK_CHANNEL,
    "oms_fulfill.ful_print_task.task_status": FUL_PRINT_TASK_TASK_STATUS,
    "oms_fulfill.ful_print_log.action": FUL_PRINT_LOG_ACTION,
    "oms_fulfill.ful_print_log.channel": FUL_PRINT_LOG_CHANNEL,
    "oms_fulfill.ful_carrier.carrier_code": FUL_CARRIER_CARRIER_CODE,
    "oms_fulfill.ful_carrier.carrier_type": FUL_CARRIER_CARRIER_TYPE,
    "oms_fulfill.ful_carrier.circuit_status": FUL_CARRIER_CIRCUIT_STATUS,
    "oms_fulfill.ful_carrier.status": FUL_CARRIER_STATUS,
    "oms_fulfill.ful_rider_call.status": FUL_RIDER_CALL_STATUS,
    "oms_fulfill.ful_rider_call.fee_liability": FUL_RIDER_CALL_FEE_LIABILITY,
    "oms_fulfill.ful_rider_call.assign_mode": FUL_RIDER_CALL_ASSIGN_MODE,
    "oms_fulfill.ful_rider_track.source": FUL_RIDER_TRACK_SOURCE,
    "oms_fulfill.ful_handover.verify_mode": FUL_HANDOVER_VERIFY_MODE,
    "oms_fulfill.ful_city_freight.settle_status": FUL_CITY_FREIGHT_SETTLE_STATUS,
    "oms_fulfill.ful_shop_carrier.self_mode": FUL_SHOP_CARRIER_SELF_MODE,
    "oms_fulfill.ful_shop_carrier.status": FUL_SHOP_CARRIER_STATUS,
    "oms_org.org_owner_contract.mode_snapshot": ORG_OWNER_CONTRACT_MODE_SNAPSHOT,
    "oms_org.org_portal_message.ref_type": ORG_PORTAL_MESSAGE_REF_TYPE,
    "oms_org.org_portal_read_log.page_code": ORG_PORTAL_READ_LOG_PAGE_CODE,
    "oms_org.aud_operation_log.action": AUD_OPERATION_LOG_ACTION,
    "oms_org.aud_operation_log.channel": AUD_OPERATION_LOG_CHANNEL,
}

#: 反查索引：`schema.table.column` → 中文标签 → 值
#:   （标签写错会在查表时立刻 KeyError，而不是静默取到错误状态码）
ENUM_BY_LABEL: Final[dict[str, dict[str, int]]] = {
    "oms_base.bas_event_dict.partitioned": {v: k for k, v in BAS_EVENT_DICT_PARTITIONED.items()},
    "oms_base.bas_event_dict.blocking_flag": {v: k for k, v in BAS_EVENT_DICT_BLOCKING_FLAG.items()},
    "oms_base.bas_event_dict.status": {v: k for k, v in BAS_EVENT_DICT_STATUS.items()},
    "oms_base.bas_event_outbox.status": {v: k for k, v in BAS_EVENT_OUTBOX_STATUS.items()},
    "oms_base.bas_consume_idempotent.status": {v: k for k, v in BAS_CONSUME_IDEMPOTENT_STATUS.items()},
    "oms_base.bas_dead_letter.handle_status": {v: k for k, v in BAS_DEAD_LETTER_HANDLE_STATUS.items()},
    "oms_base.bas_schedule_task.status": {v: k for k, v in BAS_SCHEDULE_TASK_STATUS.items()},
    "oms_base.bas_schedule_log.sampled": {v: k for k, v in BAS_SCHEDULE_LOG_SAMPLED.items()},
    "oms_base.bas_task_dependency.plan_date_align": {v: k for k, v in BAS_TASK_DEPENDENCY_PLAN_DATE_ALIGN.items()},
    "oms_base.bas_task_dependency.auto_trigger": {v: k for k, v in BAS_TASK_DEPENDENCY_AUTO_TRIGGER.items()},
    "oms_base.bas_task_dependency.status": {v: k for k, v in BAS_TASK_DEPENDENCY_STATUS.items()},
    "oms_base.bas_rule_dict.preset_flag": {v: k for k, v in BAS_RULE_DICT_PRESET_FLAG.items()},
    "oms_base.bas_rule_dict.status": {v: k for k, v in BAS_RULE_DICT_STATUS.items()},
    "oms_base.bas_rule.defaulted": {v: k for k, v in BAS_RULE_DEFAULTED.items()},
    "oms_base.bas_rule.status": {v: k for k, v in BAS_RULE_STATUS.items()},
    "oms_base.bas_rule_version.status": {v: k for k, v in BAS_RULE_VERSION_STATUS.items()},
    "oms_base.bas_rule_version.agent_draft": {v: k for k, v in BAS_RULE_VERSION_AGENT_DRAFT.items()},
    "oms_base.bas_rule_test_log.run_mode": {v: k for k, v in BAS_RULE_TEST_LOG_RUN_MODE.items()},
    "oms_base.bas_rule_test_log.exec_mode": {v: k for k, v in BAS_RULE_TEST_LOG_EXEC_MODE.items()},
    "oms_base.bas_rule_test_log.run_status": {v: k for k, v in BAS_RULE_TEST_LOG_RUN_STATUS.items()},
    "oms_base.bas_plugin_registry.short_circuit": {v: k for k, v in BAS_PLUGIN_REGISTRY_SHORT_CIRCUIT.items()},
    "oms_base.bas_plugin_registry.enabled": {v: k for k, v in BAS_PLUGIN_REGISTRY_ENABLED.items()},
    "oms_base.bas_entity_meta.soft_delete": {v: k for k, v in BAS_ENTITY_META_SOFT_DELETE.items()},
    "oms_base.bas_entity_meta.crud_enabled": {v: k for k, v in BAS_ENTITY_META_CRUD_ENABLED.items()},
    "oms_base.bas_entity_meta.status": {v: k for k, v in BAS_ENTITY_META_STATUS.items()},
    "oms_base.bas_field_meta.required_flag": {v: k for k, v in BAS_FIELD_META_REQUIRED_FLAG.items()},
    "oms_base.bas_field_meta.sensitive_level": {v: k for k, v in BAS_FIELD_META_SENSITIVE_LEVEL.items()},
    "oms_base.bas_field_meta.unique_flag": {v: k for k, v in BAS_FIELD_META_UNIQUE_FLAG.items()},
    "oms_base.bas_field_meta.status": {v: k for k, v in BAS_FIELD_META_STATUS.items()},
    "oms_base.bas_pipl_policy.level": {v: k for k, v in BAS_PIPL_POLICY_LEVEL.items()},
    "oms_base.bas_pipl_policy.status": {v: k for k, v in BAS_PIPL_POLICY_STATUS.items()},
    "oms_base.bas_pipl_ds_request.restricted_flag": {v: k for k, v in BAS_PIPL_DS_REQUEST_RESTRICTED_FLAG.items()},
    "oms_base.bas_pipl_ds_request.handle_status": {v: k for k, v in BAS_PIPL_DS_REQUEST_HANDLE_STATUS.items()},
    "oms_base.bas_ie_template.status": {v: k for k, v in BAS_IE_TEMPLATE_STATUS.items()},
    "oms_base.bas_import_task.status": {v: k for k, v in BAS_IMPORT_TASK_STATUS.items()},
    "oms_base.bas_export_task.sensitive_flag": {v: k for k, v in BAS_EXPORT_TASK_SENSITIVE_FLAG.items()},
    "oms_base.bas_export_task.plain_apply": {v: k for k, v in BAS_EXPORT_TASK_PLAIN_APPLY.items()},
    "oms_base.bas_export_task.status": {v: k for k, v in BAS_EXPORT_TASK_STATUS.items()},
    "oms_base.bas_notify_template.compliance_confirmed": {v: k for k, v in BAS_NOTIFY_TEMPLATE_COMPLIANCE_CONFIRMED.items()},
    "oms_base.bas_notify_template.status": {v: k for k, v in BAS_NOTIFY_TEMPLATE_STATUS.items()},
    "oms_base.bas_notify_route.denoise_flag": {v: k for k, v in BAS_NOTIFY_ROUTE_DENOISE_FLAG.items()},
    "oms_base.bas_notify_route.default_flag": {v: k for k, v in BAS_NOTIFY_ROUTE_DEFAULT_FLAG.items()},
    "oms_base.bas_notify_route.status": {v: k for k, v in BAS_NOTIFY_ROUTE_STATUS.items()},
    "oms_base.bas_notify_log.send_status": {v: k for k, v in BAS_NOTIFY_LOG_SEND_STATUS.items()},
    "oms_base.bas_alert_record.alert_level": {v: k for k, v in BAS_ALERT_RECORD_ALERT_LEVEL.items()},
    "oms_base.bas_alert_record.recovered": {v: k for k, v in BAS_ALERT_RECORD_RECOVERED.items()},
    "oms_base.bas_migration_mapping.status": {v: k for k, v in BAS_MIGRATION_MAPPING_STATUS.items()},
    "oms_order.ord_flag_change_log.change_source": {v: k for k, v in ORD_FLAG_CHANGE_LOG_CHANGE_SOURCE.items()},
    "oms_order.ord_flag_change_log.sync_status": {v: k for k, v in ORD_FLAG_CHANGE_LOG_SYNC_STATUS.items()},
    "oms_stock.inv_io_bill_type.direction": {v: k for k, v in INV_IO_BILL_TYPE_DIRECTION.items()},
    "oms_stock.inv_io_bill_type.need_wms": {v: k for k, v in INV_IO_BILL_TYPE_NEED_WMS.items()},
    "oms_stock.inv_io_bill_type.need_approval": {v: k for k, v in INV_IO_BILL_TYPE_NEED_APPROVAL.items()},
    "oms_stock.inv_io_bill_type.settle_rel": {v: k for k, v in INV_IO_BILL_TYPE_SETTLE_REL.items()},
    "oms_stock.inv_io_bill_type.status": {v: k for k, v in INV_IO_BILL_TYPE_STATUS.items()},
    "oms_stock.inv_material_cat.status": {v: k for k, v in INV_MATERIAL_CAT_STATUS.items()},
    "oms_stock.inv_brand.status": {v: k for k, v in INV_BRAND_STATUS.items()},
    "oms_stock.inv_stock_config.config_type": {v: k for k, v in INV_STOCK_CONFIG_CONFIG_TYPE.items()},
    "oms_stock.inv_stock_config.scope_type": {v: k for k, v in INV_STOCK_CONFIG_SCOPE_TYPE.items()},
    "oms_stock.inv_stock_config.status": {v: k for k, v in INV_STOCK_CONFIG_STATUS.items()},
    "oms_stock.inv_cost_config.tax_caliber": {v: k for k, v in INV_COST_CONFIG_TAX_CALIBER.items()},
    "oms_stock.inv_cost_config.branch_cost_mode": {v: k for k, v in INV_COST_CONFIG_BRANCH_COST_MODE.items()},
    "oms_stock.inv_cost_config.return_cost_mode": {v: k for k, v in INV_COST_CONFIG_RETURN_COST_MODE.items()},
    "oms_stock.inv_cost_config.freight_in_cost": {v: k for k, v in INV_COST_CONFIG_FREIGHT_IN_COST.items()},
    "oms_stock.inv_cost_config.status": {v: k for k, v in INV_COST_CONFIG_STATUS.items()},
    "oms_stock.inv_expire_rule.scope_type": {v: k for k, v in INV_EXPIRE_RULE_SCOPE_TYPE.items()},
    "oms_stock.inv_expire_rule.threshold_type": {v: k for k, v in INV_EXPIRE_RULE_THRESHOLD_TYPE.items()},
    "oms_stock.inv_expire_rule.auto_freeze": {v: k for k, v in INV_EXPIRE_RULE_AUTO_FREEZE.items()},
    "oms_stock.inv_expire_rule.status": {v: k for k, v in INV_EXPIRE_RULE_STATUS.items()},
    "oms_stock.inv_alert_rule.rule_type": {v: k for k, v in INV_ALERT_RULE_RULE_TYPE.items()},
    "oms_stock.inv_alert_rule.scope_type": {v: k for k, v in INV_ALERT_RULE_SCOPE_TYPE.items()},
    "oms_stock.inv_alert_rule.sales_caliber": {v: k for k, v in INV_ALERT_RULE_SALES_CALIBER.items()},
    "oms_stock.inv_alert_rule.promo_exclude": {v: k for k, v in INV_ALERT_RULE_PROMO_EXCLUDE.items()},
    "oms_stock.inv_alert_rule.scan_freq": {v: k for k, v in INV_ALERT_RULE_SCAN_FREQ.items()},
    "oms_stock.inv_alert_rule.status": {v: k for k, v in INV_ALERT_RULE_STATUS.items()},
    "oms_stock.inv_stocktake_plan.cycle_type": {v: k for k, v in INV_STOCKTAKE_PLAN_CYCLE_TYPE.items()},
    "oms_stock.inv_stocktake_plan.scope_type": {v: k for k, v in INV_STOCKTAKE_PLAN_SCOPE_TYPE.items()},
    "oms_stock.inv_stocktake_plan.mode": {v: k for k, v in INV_STOCKTAKE_PLAN_MODE.items()},
    "oms_stock.inv_stocktake_plan.executor": {v: k for k, v in INV_STOCKTAKE_PLAN_EXECUTOR.items()},
    "oms_stock.inv_stocktake_plan.status": {v: k for k, v in INV_STOCKTAKE_PLAN_STATUS.items()},
    "oms_stock.inv_sync_strategy.scope_type": {v: k for k, v in INV_SYNC_STRATEGY_SCOPE_TYPE.items()},
    "oms_stock.inv_sync_strategy.oversell_mode": {v: k for k, v in INV_SYNC_STRATEGY_OVERSELL_MODE.items()},
    "oms_stock.inv_sync_strategy.water_level_type": {v: k for k, v in INV_SYNC_STRATEGY_WATER_LEVEL_TYPE.items()},
    "oms_stock.inv_sync_strategy.writeback_mode": {v: k for k, v in INV_SYNC_STRATEGY_WRITEBACK_MODE.items()},
    "oms_stock.inv_sync_strategy.status": {v: k for k, v in INV_SYNC_STRATEGY_STATUS.items()},
    "oms_stock.inv_material.type": {v: k for k, v in INV_MATERIAL_TYPE.items()},
    "oms_stock.inv_material.serial_number": {v: k for k, v in INV_MATERIAL_SERIAL_NUMBER.items()},
    "oms_stock.inv_material.storage_life_flag": {v: k for k, v in INV_MATERIAL_STORAGE_LIFE_FLAG.items()},
    "oms_stock.inv_material.is_ctrl_store": {v: k for k, v in INV_MATERIAL_IS_CTRL_STORE.items()},
    "oms_stock.inv_material.omnichannel": {v: k for k, v in INV_MATERIAL_OMNICHANNEL.items()},
    "oms_stock.inv_material.is_o2o_sales": {v: k for k, v in INV_MATERIAL_IS_O2O_SALES.items()},
    "oms_stock.inv_material.status": {v: k for k, v in INV_MATERIAL_STATUS.items()},
    "oms_stock.inv_sales_material.sales_material_type": {v: k for k, v in INV_SALES_MATERIAL_SALES_MATERIAL_TYPE.items()},
    "oms_stock.inv_sales_material.bind_status": {v: k for k, v in INV_SALES_MATERIAL_BIND_STATUS.items()},
    "oms_stock.inv_sales_material.visibled": {v: k for k, v in INV_SALES_MATERIAL_VISIBLED.items()},
    "oms_stock.inv_sales_material.status": {v: k for k, v in INV_SALES_MATERIAL_STATUS.items()},
    "oms_stock.inv_bom_version.status": {v: k for k, v in INV_BOM_VERSION_STATUS.items()},
    "oms_stock.inv_barcode.barcode_type": {v: k for k, v in INV_BARCODE_BARCODE_TYPE.items()},
    "oms_stock.inv_barcode.status": {v: k for k, v in INV_BARCODE_STATUS.items()},
    "oms_stock.inv_fukubukuro_plan.status": {v: k for k, v in INV_FUKUBUKURO_PLAN_STATUS.items()},
    "oms_stock.inv_pickone_candidate.select_type": {v: k for k, v in INV_PICKONE_CANDIDATE_SELECT_TYPE.items()},
    "oms_stock.inv_stock_ledger.is_locked": {v: k for k, v in INV_STOCK_LEDGER_IS_LOCKED.items()},
    "oms_stock.inv_stock_ledger.status": {v: k for k, v in INV_STOCK_LEDGER_STATUS.items()},
    "oms_stock.inv_stock_adjust.adjust_type": {v: k for k, v in INV_STOCK_ADJUST_ADJUST_TYPE.items()},
    "oms_stock.inv_stock_adjust.approval_status": {v: k for k, v in INV_STOCK_ADJUST_APPROVAL_STATUS.items()},
    "oms_stock.inv_stock_adjust.status": {v: k for k, v in INV_STOCK_ADJUST_STATUS.items()},
    "oms_stock.inv_stock_recon_diff.recon_type": {v: k for k, v in INV_STOCK_RECON_DIFF_RECON_TYPE.items()},
    "oms_stock.inv_stock_recon_diff.status": {v: k for k, v in INV_STOCK_RECON_DIFF_STATUS.items()},
    "oms_stock.inv_freeze_log.obj_type": {v: k for k, v in INV_FREEZE_LOG_OBJ_TYPE.items()},
    "oms_stock.inv_freeze_log.status": {v: k for k, v in INV_FREEZE_LOG_STATUS.items()},
    "oms_stock.inv_freeze_log.is_compensated": {v: k for k, v in INV_FREEZE_LOG_IS_COMPENSATED.items()},
    "oms_stock.inv_manual_freeze.approval_status": {v: k for k, v in INV_MANUAL_FREEZE_APPROVAL_STATUS.items()},
    "oms_stock.inv_manual_freeze.status": {v: k for k, v in INV_MANUAL_FREEZE_STATUS.items()},
    "oms_stock.inv_io_bill.direction": {v: k for k, v in INV_IO_BILL_DIRECTION.items()},
    "oms_stock.inv_io_bill.status": {v: k for k, v in INV_IO_BILL_STATUS.items()},
    "oms_stock.inv_io_bill.settle_status": {v: k for k, v in INV_IO_BILL_SETTLE_STATUS.items()},
    "oms_stock.inv_io_bill.approval_status": {v: k for k, v in INV_IO_BILL_APPROVAL_STATUS.items()},
    "oms_stock.inv_io_callback_log.callback_type": {v: k for k, v in INV_IO_CALLBACK_LOG_CALLBACK_TYPE.items()},
    "oms_stock.inv_io_callback_log.status": {v: k for k, v in INV_IO_CALLBACK_LOG_STATUS.items()},
    "oms_stock.inv_transfer_order.reason": {v: k for k, v in INV_TRANSFER_ORDER_REASON.items()},
    "oms_stock.inv_transfer_order.status": {v: k for k, v in INV_TRANSFER_ORDER_STATUS.items()},
    "oms_stock.inv_transfer_order.arrival_sellable": {v: k for k, v in INV_TRANSFER_ORDER_ARRIVAL_SELLABLE.items()},
    "oms_stock.inv_transfer_order.diff_type": {v: k for k, v in INV_TRANSFER_ORDER_DIFF_TYPE.items()},
    "oms_stock.inv_transfer_order.approval_status": {v: k for k, v in INV_TRANSFER_ORDER_APPROVAL_STATUS.items()},
    "oms_stock.inv_lend_rule.scope_type": {v: k for k, v in INV_LEND_RULE_SCOPE_TYPE.items()},
    "oms_stock.inv_lend_rule.settle_price_type": {v: k for k, v in INV_LEND_RULE_SETTLE_PRICE_TYPE.items()},
    "oms_stock.inv_lend_rule.move_type": {v: k for k, v in INV_LEND_RULE_MOVE_TYPE.items()},
    "oms_stock.inv_lend_rule.status": {v: k for k, v in INV_LEND_RULE_STATUS.items()},
    "oms_stock.inv_lend_rule.approval_status": {v: k for k, v in INV_LEND_RULE_APPROVAL_STATUS.items()},
    "oms_stock.inv_lend_ledger.status": {v: k for k, v in INV_LEND_LEDGER_STATUS.items()},
    "oms_stock.inv_lend_ledger.settle_status": {v: k for k, v in INV_LEND_LEDGER_SETTLE_STATUS.items()},
    "oms_stock.inv_ownership_transfer.status": {v: k for k, v in INV_OWNERSHIP_TRANSFER_STATUS.items()},
    "oms_stock.inv_ownership_transfer.approval_status": {v: k for k, v in INV_OWNERSHIP_TRANSFER_APPROVAL_STATUS.items()},
    "oms_stock.inv_stocktake_task.mode": {v: k for k, v in INV_STOCKTAKE_TASK_MODE.items()},
    "oms_stock.inv_stocktake_task.executor": {v: k for k, v in INV_STOCKTAKE_TASK_EXECUTOR.items()},
    "oms_stock.inv_stocktake_task.trigger_type": {v: k for k, v in INV_STOCKTAKE_TASK_TRIGGER_TYPE.items()},
    "oms_stock.inv_stocktake_task.status": {v: k for k, v in INV_STOCKTAKE_TASK_STATUS.items()},
    "oms_stock.inv_stocktake_task.approval_status": {v: k for k, v in INV_STOCKTAKE_TASK_APPROVAL_STATUS.items()},
    "oms_stock.inv_stocktake_item.recount_flag": {v: k for k, v in INV_STOCKTAKE_ITEM_RECOUNT_FLAG.items()},
    "oms_stock.inv_stocktake_item.diff_reason": {v: k for k, v in INV_STOCKTAKE_ITEM_DIFF_REASON.items()},
    "oms_stock.inv_stocktake_item.suspect_mixup": {v: k for k, v in INV_STOCKTAKE_ITEM_SUSPECT_MIXUP.items()},
    "oms_stock.inv_cost_change_log.change_type": {v: k for k, v in INV_COST_CHANGE_LOG_CHANGE_TYPE.items()},
    "oms_stock.inv_cost_change_log.estimate_flag": {v: k for k, v in INV_COST_CHANGE_LOG_ESTIMATE_FLAG.items()},
    "oms_stock.inv_cost_change_log.cost_estimated": {v: k for k, v in INV_COST_CHANGE_LOG_COST_ESTIMATED.items()},
    "oms_stock.inv_estimate_batch.status": {v: k for k, v in INV_ESTIMATE_BATCH_STATUS.items()},
    "oms_stock.inv_sellable_snapshot.sync_status": {v: k for k, v in INV_SELLABLE_SNAPSHOT_SYNC_STATUS.items()},
    "oms_stock.inv_sync_log.trigger_type": {v: k for k, v in INV_SYNC_LOG_TRIGGER_TYPE.items()},
    "oms_stock.inv_sync_log.sync_status": {v: k for k, v in INV_SYNC_LOG_SYNC_STATUS.items()},
    "oms_stock.inv_batch.status": {v: k for k, v in INV_BATCH_STATUS.items()},
    "oms_stock.inv_batch_stock.near_expire_level": {v: k for k, v in INV_BATCH_STOCK_NEAR_EXPIRE_LEVEL.items()},
    "oms_stock.inv_batch_assign.strategy": {v: k for k, v in INV_BATCH_ASSIGN_STRATEGY.items()},
    "oms_stock.inv_batch_assign.is_match": {v: k for k, v in INV_BATCH_ASSIGN_IS_MATCH.items()},
    "oms_stock.inv_serial_no.status": {v: k for k, v in INV_SERIAL_NO_STATUS.items()},
    "oms_stock.inv_expire_disposal.disposal_type": {v: k for k, v in INV_EXPIRE_DISPOSAL_DISPOSAL_TYPE.items()},
    "oms_stock.inv_expire_disposal.approval_status": {v: k for k, v in INV_EXPIRE_DISPOSAL_APPROVAL_STATUS.items()},
    "oms_stock.inv_expire_disposal.status": {v: k for k, v in INV_EXPIRE_DISPOSAL_STATUS.items()},
    "oms_stock.inv_replenish_suggestion.suggest_type": {v: k for k, v in INV_REPLENISH_SUGGESTION_SUGGEST_TYPE.items()},
    "oms_stock.inv_replenish_suggestion.alert_level": {v: k for k, v in INV_REPLENISH_SUGGESTION_ALERT_LEVEL.items()},
    "oms_stock.inv_replenish_suggestion.status": {v: k for k, v in INV_REPLENISH_SUGGESTION_STATUS.items()},
    "oms_stock.inv_replenish_suggestion.ignore_reason": {v: k for k, v in INV_REPLENISH_SUGGESTION_IGNORE_REASON.items()},
    "oms_stock.inv_sales_forecast.degrade_flag": {v: k for k, v in INV_SALES_FORECAST_DEGRADE_FLAG.items()},
    "oms_stock.inv_price_archive.below_floor_flag": {v: k for k, v in INV_PRICE_ARCHIVE_BELOW_FLOOR_FLAG.items()},
    "oms_stock.inv_price_archive.status": {v: k for k, v in INV_PRICE_ARCHIVE_STATUS.items()},
    "oms_stock.inv_price_version.sync_flag": {v: k for k, v in INV_PRICE_VERSION_SYNC_FLAG.items()},
    "oms_stock.inv_price_adjust_plan.expire_writeback": {v: k for k, v in INV_PRICE_ADJUST_PLAN_EXPIRE_WRITEBACK.items()},
    "oms_stock.inv_price_adjust_item.below_floor": {v: k for k, v in INV_PRICE_ADJUST_ITEM_BELOW_FLOOR.items()},
    "oms_stock.inv_price_sync_task.alert_flag": {v: k for k, v in INV_PRICE_SYNC_TASK_ALERT_FLAG.items()},
    "oms_aftersale.aft_reason_dict.duty_party": {v: k for k, v in AFT_REASON_DICT_DUTY_PARTY.items()},
    "oms_aftersale.aft_reason_dict.audit_white": {v: k for k, v in AFT_REASON_DICT_AUDIT_WHITE.items()},
    "oms_aftersale.aft_reason_dict.reject_suggest": {v: k for k, v in AFT_REASON_DICT_REJECT_SUGGEST.items()},
    "oms_aftersale.aft_reason_dict.status": {v: k for k, v in AFT_REASON_DICT_STATUS.items()},
    "oms_aftersale.aft_return_address.address_type": {v: k for k, v in AFT_RETURN_ADDRESS_ADDRESS_TYPE.items()},
    "oms_aftersale.aft_return_address.status": {v: k for k, v in AFT_RETURN_ADDRESS_STATUS.items()},
    "oms_aftersale.aft_auto_audit_rule.action_type": {v: k for k, v in AFT_AUTO_AUDIT_RULE_ACTION_TYPE.items()},
    "oms_aftersale.aft_auto_audit_rule.rescue_flag": {v: k for k, v in AFT_AUTO_AUDIT_RULE_RESCUE_FLAG.items()},
    "oms_aftersale.aft_auto_audit_rule.defaulted": {v: k for k, v in AFT_AUTO_AUDIT_RULE_DEFAULTED.items()},
    "oms_aftersale.aft_auto_audit_rule.status": {v: k for k, v in AFT_AUTO_AUDIT_RULE_STATUS.items()},
    "oms_aftersale.aft_return_apply.aftersale_type": {v: k for k, v in AFT_RETURN_APPLY_AFTERSALE_TYPE.items()},
    "oms_aftersale.aft_return_apply.reship_only": {v: k for k, v in AFT_RETURN_APPLY_RESHIP_ONLY.items()},
    "oms_aftersale.aft_return_apply.status": {v: k for k, v in AFT_RETURN_APPLY_STATUS.items()},
    "oms_aftersale.aft_return_apply.goods_status": {v: k for k, v in AFT_RETURN_APPLY_GOODS_STATUS.items()},
    "oms_aftersale.aft_return_apply.is_archived_order": {v: k for k, v in AFT_RETURN_APPLY_IS_ARCHIVED_ORDER.items()},
    "oms_aftersale.aft_return_apply.warn_level": {v: k for k, v in AFT_RETURN_APPLY_WARN_LEVEL.items()},
    "oms_aftersale.aft_return_apply.sync_status": {v: k for k, v in AFT_RETURN_APPLY_SYNC_STATUS.items()},
    "oms_aftersale.aft_return_apply.auto_agreed_by_platform": {v: k for k, v in AFT_RETURN_APPLY_AUTO_AGREED_BY_PLATFORM.items()},
    "oms_aftersale.aft_return_apply.audit_channel": {v: k for k, v in AFT_RETURN_APPLY_AUDIT_CHANNEL.items()},
    "oms_aftersale.aft_return_apply_item.gift_flag": {v: k for k, v in AFT_RETURN_APPLY_ITEM_GIFT_FLAG.items()},
    "oms_aftersale.aft_return_apply_log.operator_type": {v: k for k, v in AFT_RETURN_APPLY_LOG_OPERATOR_TYPE.items()},
    "oms_aftersale.aft_reship.reship_type": {v: k for k, v in AFT_RESHIP_RESHIP_TYPE.items()},
    "oms_aftersale.aft_reship.status": {v: k for k, v in AFT_RESHIP_STATUS.items()},
    "oms_aftersale.aft_reship.sn_check_status": {v: k for k, v in AFT_RESHIP_SN_CHECK_STATUS.items()},
    "oms_aftersale.aft_reship.diff_status": {v: k for k, v in AFT_RESHIP_DIFF_STATUS.items()},
    "oms_aftersale.aft_reship.close_type": {v: k for k, v in AFT_RESHIP_CLOSE_TYPE.items()},
    "oms_aftersale.aft_reship_item.refund_trigger_status": {v: k for k, v in AFT_RESHIP_ITEM_REFUND_TRIGGER_STATUS.items()},
    "oms_aftersale.aft_reship_item.diff_flag": {v: k for k, v in AFT_RESHIP_ITEM_DIFF_FLAG.items()},
    "oms_aftersale.aft_reship_sn.check_stage": {v: k for k, v in AFT_RESHIP_SN_CHECK_STAGE.items()},
    "oms_aftersale.aft_reship_sn.check_result": {v: k for k, v in AFT_RESHIP_SN_CHECK_RESULT.items()},
    "oms_aftersale.aft_reship_sn.swap_suspect_flag": {v: k for k, v in AFT_RESHIP_SN_SWAP_SUSPECT_FLAG.items()},
    "oms_aftersale.aft_reship_sn.before_sn_status": {v: k for k, v in AFT_RESHIP_SN_BEFORE_SN_STATUS.items()},
    "oms_aftersale.aft_reship_sn.handle_result": {v: k for k, v in AFT_RESHIP_SN_HANDLE_RESULT.items()},
    "oms_aftersale.aft_defect_disposal.disposal_type": {v: k for k, v in AFT_DEFECT_DISPOSAL_DISPOSAL_TYPE.items()},
    "oms_aftersale.aft_defect_disposal.approval_status": {v: k for k, v in AFT_DEFECT_DISPOSAL_APPROVAL_STATUS.items()},
    "oms_aftersale.aft_defect_disposal.status": {v: k for k, v in AFT_DEFECT_DISPOSAL_STATUS.items()},
    "oms_aftersale.aft_return_logistics.trace_status": {v: k for k, v in AFT_RETURN_LOGISTICS_TRACE_STATUS.items()},
    "oms_aftersale.aft_return_logistics.warn_flag": {v: k for k, v in AFT_RETURN_LOGISTICS_WARN_FLAG.items()},
    "oms_aftersale.aft_refund.status": {v: k for k, v in AFT_REFUND_STATUS.items()},
    "oms_aftersale.aft_refund.channel": {v: k for k, v in AFT_REFUND_CHANNEL.items()},
    "oms_aftersale.aft_refund.platform_intervened": {v: k for k, v in AFT_REFUND_PLATFORM_INTERVENED.items()},
    "oms_aftersale.aft_refund.loss_type": {v: k for k, v in AFT_REFUND_LOSS_TYPE.items()},
    "oms_aftersale.aft_refund.audit_channel": {v: k for k, v in AFT_REFUND_AUDIT_CHANNEL.items()},
    "oms_aftersale.aft_refund.risk_flag": {v: k for k, v in AFT_REFUND_RISK_FLAG.items()},
    "oms_aftersale.aft_refund.ledger_status": {v: k for k, v in AFT_REFUND_LEDGER_STATUS.items()},
    "oms_aftersale.aft_refund_alloc.is_last_line": {v: k for k, v in AFT_REFUND_ALLOC_IS_LAST_LINE.items()},
    "oms_aftersale.aft_refund_log.operator_type": {v: k for k, v in AFT_REFUND_LOG_OPERATOR_TYPE.items()},
    "oms_aftersale.aft_exchange.exchange_type": {v: k for k, v in AFT_EXCHANGE_EXCHANGE_TYPE.items()},
    "oms_aftersale.aft_exchange.reship_only": {v: k for k, v in AFT_EXCHANGE_RESHIP_ONLY.items()},
    "oms_aftersale.aft_exchange.status": {v: k for k, v in AFT_EXCHANGE_STATUS.items()},
    "oms_aftersale.aft_exchange.diff_type": {v: k for k, v in AFT_EXCHANGE_DIFF_TYPE.items()},
    "oms_aftersale.aft_exchange.diff_status": {v: k for k, v in AFT_EXCHANGE_DIFF_STATUS.items()},
    "oms_aftersale.aft_exchange.sn_reentry_policy": {v: k for k, v in AFT_EXCHANGE_SN_REENTRY_POLICY.items()},
    "oms_aftersale.aft_exchange_log.operator_type": {v: k for k, v in AFT_EXCHANGE_LOG_OPERATOR_TYPE.items()},
    "oms_aftersale.aft_auto_audit_log.decision": {v: k for k, v in AFT_AUTO_AUDIT_LOG_DECISION.items()},
    "oms_aftersale.aft_auto_audit_log.risk_flag": {v: k for k, v in AFT_AUTO_AUDIT_LOG_RISK_FLAG.items()},
    "oms_aftersale.aft_auto_audit_log.deadline_rescue": {v: k for k, v in AFT_AUTO_AUDIT_LOG_DEADLINE_RESCUE.items()},
    "oms_aftersale.aft_auto_audit_log.manual_final_decision": {v: k for k, v in AFT_AUTO_AUDIT_LOG_MANUAL_FINAL_DECISION.items()},
    "oms_aftersale.aft_auto_audit_log.overturn_flag": {v: k for k, v in AFT_AUTO_AUDIT_LOG_OVERTURN_FLAG.items()},
    "oms_aftersale.aft_audit_task.task_type": {v: k for k, v in AFT_AUDIT_TASK_TASK_TYPE.items()},
    "oms_aftersale.aft_audit_task.priority": {v: k for k, v in AFT_AUDIT_TASK_PRIORITY.items()},
    "oms_aftersale.aft_audit_task.status": {v: k for k, v in AFT_AUDIT_TASK_STATUS.items()},
    "oms_aftersale.aft_audit_task.result": {v: k for k, v in AFT_AUDIT_TASK_RESULT.items()},
    "oms_aftersale.aft_risk_flag.dim_type": {v: k for k, v in AFT_RISK_FLAG_DIM_TYPE.items()},
    "oms_aftersale.aft_risk_flag.blacklist_flag": {v: k for k, v in AFT_RISK_FLAG_BLACKLIST_FLAG.items()},
    "oms_aftersale.aft_risk_flag.high_freq_flag": {v: k for k, v in AFT_RISK_FLAG_HIGH_FREQ_FLAG.items()},
    "oms_aftersale.aft_risk_flag.calibrate_status": {v: k for k, v in AFT_RISK_FLAG_CALIBRATE_STATUS.items()},
    "oms_aftersale.aft_timeout_monitor.aftersale_type": {v: k for k, v in AFT_TIMEOUT_MONITOR_AFTERSALE_TYPE.items()},
    "oms_aftersale.aft_timeout_monitor.warn_level": {v: k for k, v in AFT_TIMEOUT_MONITOR_WARN_LEVEL.items()},
    "oms_aftersale.aft_timeout_monitor.escalate_flag": {v: k for k, v in AFT_TIMEOUT_MONITOR_ESCALATE_FLAG.items()},
    "oms_aftersale.aft_timeout_monitor.auto_agreed_flag": {v: k for k, v in AFT_TIMEOUT_MONITOR_AUTO_AGREED_FLAG.items()},
    "oms_aftersale.aft_timeout_monitor.loss_review_flag": {v: k for k, v in AFT_TIMEOUT_MONITOR_LOSS_REVIEW_FLAG.items()},
    "oms_aftersale.aft_timeout_monitor.status": {v: k for k, v in AFT_TIMEOUT_MONITOR_STATUS.items()},
    "oms_aftersale.aft_buyer_profile.appeal_status": {v: k for k, v in AFT_BUYER_PROFILE_APPEAL_STATUS.items()},
    "oms_purchase.pur_dict.status": {v: k for k, v in PUR_DICT_STATUS.items()},
    "oms_purchase.pur_supplier.status": {v: k for k, v in PUR_SUPPLIER_STATUS.items()},
    "oms_purchase.pur_supplier.pay_type": {v: k for k, v in PUR_SUPPLIER_PAY_TYPE.items()},
    "oms_purchase.pur_supplier.settle_type": {v: k for k, v in PUR_SUPPLIER_SETTLE_TYPE.items()},
    "oms_purchase.pur_supply_relation.tax_flag": {v: k for k, v in PUR_SUPPLY_RELATION_TAX_FLAG.items()},
    "oms_purchase.pur_supply_relation.is_default": {v: k for k, v in PUR_SUPPLY_RELATION_IS_DEFAULT.items()},
    "oms_purchase.pur_supply_relation.status": {v: k for k, v in PUR_SUPPLY_RELATION_STATUS.items()},
    "oms_purchase.pur_supply_price_log.tax_flag": {v: k for k, v in PUR_SUPPLY_PRICE_LOG_TAX_FLAG.items()},
    "oms_purchase.pur_request.request_type": {v: k for k, v in PUR_REQUEST_REQUEST_TYPE.items()},
    "oms_purchase.pur_request.status": {v: k for k, v in PUR_REQUEST_STATUS.items()},
    "oms_purchase.pur_request.approval_result": {v: k for k, v in PUR_REQUEST_APPROVAL_RESULT.items()},
    "oms_purchase.pur_request.close_reason": {v: k for k, v in PUR_REQUEST_CLOSE_REASON.items()},
    "oms_purchase.pur_request_item.source_type": {v: k for k, v in PUR_REQUEST_ITEM_SOURCE_TYPE.items()},
    "oms_purchase.pur_request_item.item_status": {v: k for k, v in PUR_REQUEST_ITEM_ITEM_STATUS.items()},
    "oms_purchase.pur_order.source_type": {v: k for k, v in PUR_ORDER_SOURCE_TYPE.items()},
    "oms_purchase.pur_order.po_type": {v: k for k, v in PUR_ORDER_PO_TYPE.items()},
    "oms_purchase.pur_order.audit_status": {v: k for k, v in PUR_ORDER_AUDIT_STATUS.items()},
    "oms_purchase.pur_order.inbound_status": {v: k for k, v in PUR_ORDER_INBOUND_STATUS.items()},
    "oms_purchase.pur_order.purchase_status": {v: k for k, v in PUR_ORDER_PURCHASE_STATUS.items()},
    "oms_purchase.pur_order.settle_status": {v: k for k, v in PUR_ORDER_SETTLE_STATUS.items()},
    "oms_purchase.pur_order.damage_status": {v: k for k, v in PUR_ORDER_DAMAGE_STATUS.items()},
    "oms_purchase.pur_order.wms_sync_status": {v: k for k, v in PUR_ORDER_WMS_SYNC_STATUS.items()},
    "oms_purchase.pur_order.terminate_flag": {v: k for k, v in PUR_ORDER_TERMINATE_FLAG.items()},
    "oms_purchase.pur_order.emergency": {v: k for k, v in PUR_ORDER_EMERGENCY.items()},
    "oms_purchase.pur_order.supplier_confirm_flag": {v: k for k, v in PUR_ORDER_SUPPLIER_CONFIRM_FLAG.items()},
    "oms_purchase.pur_order_item.item_status": {v: k for k, v in PUR_ORDER_ITEM_ITEM_STATUS.items()},
    "oms_purchase.pur_order_fee.fee_type": {v: k for k, v in PUR_ORDER_FEE_FEE_TYPE.items()},
    "oms_purchase.pur_order_fee.alloc_type": {v: k for k, v in PUR_ORDER_FEE_ALLOC_TYPE.items()},
    "oms_purchase.pur_arrival_plan.deviation_flag": {v: k for k, v in PUR_ARRIVAL_PLAN_DEVIATION_FLAG.items()},
    "oms_purchase.pur_arrival_plan.status": {v: k for k, v in PUR_ARRIVAL_PLAN_STATUS.items()},
    "oms_purchase.pur_order_change.change_type": {v: k for k, v in PUR_ORDER_CHANGE_CHANGE_TYPE.items()},
    "oms_purchase.pur_order_change.reaudit_flag": {v: k for k, v in PUR_ORDER_CHANGE_REAUDIT_FLAG.items()},
    "oms_purchase.pur_order_change.status": {v: k for k, v in PUR_ORDER_CHANGE_STATUS.items()},
    "oms_purchase.pur_arrival.out_of_plan_flag": {v: k for k, v in PUR_ARRIVAL_OUT_OF_PLAN_FLAG.items()},
    "oms_purchase.pur_arrival.status": {v: k for k, v in PUR_ARRIVAL_STATUS.items()},
    "oms_purchase.pur_arrival.source_type": {v: k for k, v in PUR_ARRIVAL_SOURCE_TYPE.items()},
    "oms_purchase.pur_receipt.estimate_flag": {v: k for k, v in PUR_RECEIPT_ESTIMATE_FLAG.items()},
    "oms_purchase.pur_receipt.bill_status": {v: k for k, v in PUR_RECEIPT_BILL_STATUS.items()},
    "oms_purchase.pur_receipt.settle_status": {v: k for k, v in PUR_RECEIPT_SETTLE_STATUS.items()},
    "oms_purchase.pur_receipt_item.quality_result": {v: k for k, v in PUR_RECEIPT_ITEM_QUALITY_RESULT.items()},
    "oms_purchase.pur_receipt_item.estimate_flag": {v: k for k, v in PUR_RECEIPT_ITEM_ESTIMATE_FLAG.items()},
    "oms_purchase.pur_damage.damage_reason": {v: k for k, v in PUR_DAMAGE_DAMAGE_REASON.items()},
    "oms_purchase.pur_damage.claim_flag": {v: k for k, v in PUR_DAMAGE_CLAIM_FLAG.items()},
    "oms_purchase.pur_damage.claim_object_type": {v: k for k, v in PUR_DAMAGE_CLAIM_OBJECT_TYPE.items()},
    "oms_purchase.pur_damage.claim_result": {v: k for k, v in PUR_DAMAGE_CLAIM_RESULT.items()},
    "oms_purchase.pur_damage.status": {v: k for k, v in PUR_DAMAGE_STATUS.items()},
    "oms_purchase.pur_diff_decision.diff_type": {v: k for k, v in PUR_DIFF_DECISION_DIFF_TYPE.items()},
    "oms_purchase.pur_diff_decision.decision": {v: k for k, v in PUR_DIFF_DECISION_DECISION.items()},
    "oms_purchase.pur_diff_decision.status": {v: k for k, v in PUR_DIFF_DECISION_STATUS.items()},
    "oms_purchase.pur_payable.accrual_strategy": {v: k for k, v in PUR_PAYABLE_ACCRUAL_STRATEGY.items()},
    "oms_purchase.pur_payable.estimate_flag": {v: k for k, v in PUR_PAYABLE_ESTIMATE_FLAG.items()},
    "oms_purchase.pur_payable.settle_status": {v: k for k, v in PUR_PAYABLE_SETTLE_STATUS.items()},
    "oms_purchase.pur_payable.status": {v: k for k, v in PUR_PAYABLE_STATUS.items()},
    "oms_purchase.pur_statement.check_result": {v: k for k, v in PUR_STATEMENT_CHECK_RESULT.items()},
    "oms_purchase.pur_statement.close_status": {v: k for k, v in PUR_STATEMENT_CLOSE_STATUS.items()},
    "oms_purchase.pur_statement.recon_confirm_status": {v: k for k, v in PUR_STATEMENT_RECON_CONFIRM_STATUS.items()},
    "oms_purchase.pur_statement_item.object_type": {v: k for k, v in PUR_STATEMENT_ITEM_OBJECT_TYPE.items()},
    "oms_purchase.pur_statement_item.direction": {v: k for k, v in PUR_STATEMENT_ITEM_DIRECTION.items()},
    "oms_purchase.pur_invoice.match_status": {v: k for k, v in PUR_INVOICE_MATCH_STATUS.items()},
    "oms_purchase.pur_invoice.estimate_reversed": {v: k for k, v in PUR_INVOICE_ESTIMATE_REVERSED.items()},
    "oms_purchase.pur_invoice.status": {v: k for k, v in PUR_INVOICE_STATUS.items()},
    "oms_purchase.pur_invoice_match.match_result": {v: k for k, v in PUR_INVOICE_MATCH_MATCH_RESULT.items()},
    "oms_purchase.pur_payment.pay_type": {v: k for k, v in PUR_PAYMENT_PAY_TYPE.items()},
    "oms_purchase.pur_payment.status": {v: k for k, v in PUR_PAYMENT_STATUS.items()},
    "oms_purchase.pur_payment.kd_push_status": {v: k for k, v in PUR_PAYMENT_KD_PUSH_STATUS.items()},
    "oms_purchase.pur_payment_verify.direction": {v: k for k, v in PUR_PAYMENT_VERIFY_DIRECTION.items()},
    "oms_purchase.pur_payment_verify.fifo_flag": {v: k for k, v in PUR_PAYMENT_VERIFY_FIFO_FLAG.items()},
    "oms_purchase.pur_payment_verify.kd_reverse_flag": {v: k for k, v in PUR_PAYMENT_VERIFY_KD_REVERSE_FLAG.items()},
    "oms_purchase.pur_recon_diff.diff_type": {v: k for k, v in PUR_RECON_DIFF_DIFF_TYPE.items()},
    "oms_purchase.pur_recon_diff.handle_path": {v: k for k, v in PUR_RECON_DIFF_HANDLE_PATH.items()},
    "oms_purchase.pur_recon_diff.force_verify_flag": {v: k for k, v in PUR_RECON_DIFF_FORCE_VERIFY_FLAG.items()},
    "oms_purchase.pur_recon_diff.status": {v: k for k, v in PUR_RECON_DIFF_STATUS.items()},
    "oms_dealer.dlr_price_type.tax_mode": {v: k for k, v in DLR_PRICE_TYPE_TAX_MODE.items()},
    "oms_dealer.dlr_price_type.status": {v: k for k, v in DLR_PRICE_TYPE_STATUS.items()},
    "oms_dealer.dlr_dealer.dealer_level": {v: k for k, v in DLR_DEALER_DEALER_LEVEL.items()},
    "oms_dealer.dlr_dealer.coop_mode": {v: k for k, v in DLR_DEALER_COOP_MODE.items()},
    "oms_dealer.dlr_dealer.status": {v: k for k, v in DLR_DEALER_STATUS.items()},
    "oms_dealer.dlr_dealer_shop.shop_type": {v: k for k, v in DLR_DEALER_SHOP_SHOP_TYPE.items()},
    "oms_dealer.dlr_dealer_shop.is_dropship": {v: k for k, v in DLR_DEALER_SHOP_IS_DROPSHIP.items()},
    "oms_dealer.dlr_dealer_shop.status": {v: k for k, v in DLR_DEALER_SHOP_STATUS.items()},
    "oms_dealer.dlr_credit_account.over_policy": {v: k for k, v in DLR_CREDIT_ACCOUNT_OVER_POLICY.items()},
    "oms_dealer.dlr_credit_account.status": {v: k for k, v in DLR_CREDIT_ACCOUNT_STATUS.items()},
    "oms_dealer.dlr_credit_txn.txn_type": {v: k for k, v in DLR_CREDIT_TXN_TXN_TYPE.items()},
    "oms_dealer.dlr_credit_txn.direction": {v: k for k, v in DLR_CREDIT_TXN_DIRECTION.items()},
    "oms_dealer.dlr_credit_period.start_anchor": {v: k for k, v in DLR_CREDIT_PERIOD_START_ANCHOR.items()},
    "oms_dealer.dlr_credit_period.status": {v: k for k, v in DLR_CREDIT_PERIOD_STATUS.items()},
    "oms_dealer.dlr_product_auth.auth_level": {v: k for k, v in DLR_PRODUCT_AUTH_AUTH_LEVEL.items()},
    "oms_dealer.dlr_product_auth.delivery_mode": {v: k for k, v in DLR_PRODUCT_AUTH_DELIVERY_MODE.items()},
    "oms_dealer.dlr_product_auth.status": {v: k for k, v in DLR_PRODUCT_AUTH_STATUS.items()},
    "oms_dealer.dlr_sales_order.channel": {v: k for k, v in DLR_SALES_ORDER_CHANNEL.items()},
    "oms_dealer.dlr_sales_order.pay_mode": {v: k for k, v in DLR_SALES_ORDER_PAY_MODE.items()},
    "oms_dealer.dlr_sales_order.amount_caliber": {v: k for k, v in DLR_SALES_ORDER_AMOUNT_CALIBER.items()},
    "oms_dealer.dlr_sales_order.allow_split": {v: k for k, v in DLR_SALES_ORDER_ALLOW_SPLIT.items()},
    "oms_dealer.dlr_sales_order.status": {v: k for k, v in DLR_SALES_ORDER_STATUS.items()},
    "oms_dealer.dlr_sales_order.close_reason": {v: k for k, v in DLR_SALES_ORDER_CLOSE_REASON.items()},
    "oms_dealer.dlr_sales_order.convert_status": {v: k for k, v in DLR_SALES_ORDER_CONVERT_STATUS.items()},
    "oms_dealer.dlr_sales_order_item.moq_check": {v: k for k, v in DLR_SALES_ORDER_ITEM_MOQ_CHECK.items()},
    "oms_dealer.dlr_sales_order_item.status": {v: k for k, v in DLR_SALES_ORDER_ITEM_STATUS.items()},
    "oms_dealer.dlr_price_list.status": {v: k for k, v in DLR_PRICE_LIST_STATUS.items()},
    "oms_dealer.dlr_price_change.action": {v: k for k, v in DLR_PRICE_CHANGE_ACTION.items()},
    "oms_dealer.dlr_price_change.approval_level": {v: k for k, v in DLR_PRICE_CHANGE_APPROVAL_LEVEL.items()},
    "oms_dealer.dlr_price_change.approval_status": {v: k for k, v in DLR_PRICE_CHANGE_APPROVAL_STATUS.items()},
    "oms_dealer.dlr_transfer_order.source_type": {v: k for k, v in DLR_TRANSFER_ORDER_SOURCE_TYPE.items()},
    "oms_dealer.dlr_transfer_order.transfer_status": {v: k for k, v in DLR_TRANSFER_ORDER_TRANSFER_STATUS.items()},
    "oms_dealer.dlr_transfer_order.channel_type": {v: k for k, v in DLR_TRANSFER_ORDER_CHANNEL_TYPE.items()},
    "oms_dealer.dlr_transfer_order_item.dropship_flag": {v: k for k, v in DLR_TRANSFER_ORDER_ITEM_DROPSHIP_FLAG.items()},
    "oms_dealer.dlr_transfer_order_item.status": {v: k for k, v in DLR_TRANSFER_ORDER_ITEM_STATUS.items()},
    "oms_dealer.dlr_dropship_ledger.object_type": {v: k for k, v in DLR_DROPSHIP_LEDGER_OBJECT_TYPE.items()},
    "oms_dealer.dlr_dropship_ledger.direction": {v: k for k, v in DLR_DROPSHIP_LEDGER_DIRECTION.items()},
    "oms_dealer.dlr_dropship_ledger.settle_price_type": {v: k for k, v in DLR_DROPSHIP_LEDGER_SETTLE_PRICE_TYPE.items()},
    "oms_dealer.dlr_dropship_ledger.settle_status": {v: k for k, v in DLR_DROPSHIP_LEDGER_SETTLE_STATUS.items()},
    "oms_finance.fin_dict.status": {v: k for k, v in FIN_DICT_STATUS.items()},
    "oms_finance.fin_gap_account.need_handle": {v: k for k, v in FIN_GAP_ACCOUNT_NEED_HANDLE.items()},
    "oms_finance.fin_gap_account.status": {v: k for k, v in FIN_GAP_ACCOUNT_STATUS.items()},
    "oms_finance.fin_credit_period.status": {v: k for k, v in FIN_CREDIT_PERIOD_STATUS.items()},
    "oms_finance.fin_settle_config.platform_in_settle": {v: k for k, v in FIN_SETTLE_CONFIG_PLATFORM_IN_SETTLE.items()},
    "oms_finance.fin_settle_config.zero_period_skip": {v: k for k, v in FIN_SETTLE_CONFIG_ZERO_PERIOD_SKIP.items()},
    "oms_finance.fin_settle_config.status": {v: k for k, v in FIN_SETTLE_CONFIG_STATUS.items()},
    "oms_finance.fin_service_fee_rule.with_refund": {v: k for k, v in FIN_SERVICE_FEE_RULE_WITH_REFUND.items()},
    "oms_finance.fin_service_fee_rule.status": {v: k for k, v in FIN_SERVICE_FEE_RULE_STATUS.items()},
    "oms_finance.fin_invoice_channel.status": {v: k for k, v in FIN_INVOICE_CHANNEL_STATUS.items()},
    "oms_finance.fin_code_mapping.direction": {v: k for k, v in FIN_CODE_MAPPING_DIRECTION.items()},
    "oms_finance.fin_code_mapping.gap_flag": {v: k for k, v in FIN_CODE_MAPPING_GAP_FLAG.items()},
    "oms_finance.fin_code_mapping.status": {v: k for k, v in FIN_CODE_MAPPING_STATUS.items()},
    "oms_finance.fin_kingdee_adapter.status": {v: k for k, v in FIN_KINGDEE_ADAPTER_STATUS.items()},
    "oms_finance.fin_receivable.settle_status": {v: k for k, v in FIN_RECEIVABLE_SETTLE_STATUS.items()},
    "oms_finance.fin_receivable.settle_carry_next": {v: k for k, v in FIN_RECEIVABLE_SETTLE_CARRY_NEXT.items()},
    "oms_finance.fin_receivable.lend_flag": {v: k for k, v in FIN_RECEIVABLE_LEND_FLAG.items()},
    "oms_finance.fin_receivable.platform_intervened": {v: k for k, v in FIN_RECEIVABLE_PLATFORM_INTERVENED.items()},
    "oms_finance.fin_receivable.wait_link_flag": {v: k for k, v in FIN_RECEIVABLE_WAIT_LINK_FLAG.items()},
    "oms_finance.fin_platform_bill_item.direction": {v: k for k, v in FIN_PLATFORM_BILL_ITEM_DIRECTION.items()},
    "oms_finance.fin_platform_bill_item.split_status": {v: k for k, v in FIN_PLATFORM_BILL_ITEM_SPLIT_STATUS.items()},
    "oms_finance.fin_bill_diff.auto_judge": {v: k for k, v in FIN_BILL_DIFF_AUTO_JUDGE.items()},
    "oms_finance.fin_platform_fee.settle_status": {v: k for k, v in FIN_PLATFORM_FEE_SETTLE_STATUS.items()},
    "oms_finance.fin_platform_fee.reverse_flag": {v: k for k, v in FIN_PLATFORM_FEE_REVERSE_FLAG.items()},
    "oms_finance.fin_ar_ledger.check_status": {v: k for k, v in FIN_AR_LEDGER_CHECK_STATUS.items()},
    "oms_finance.fin_settlement.owner_type": {v: k for k, v in FIN_SETTLEMENT_OWNER_TYPE.items()},
    "oms_finance.fin_settlement.net_direction": {v: k for k, v in FIN_SETTLEMENT_NET_DIRECTION.items()},
    "oms_finance.fin_settlement.kd_push_status": {v: k for k, v in FIN_SETTLEMENT_KD_PUSH_STATUS.items()},
    "oms_finance.fin_settlement.period_lock": {v: k for k, v in FIN_SETTLEMENT_PERIOD_LOCK.items()},
    "oms_finance.fin_settlement_item.lend_direction": {v: k for k, v in FIN_SETTLEMENT_ITEM_LEND_DIRECTION.items()},
    "oms_finance.fin_receipt.direction": {v: k for k, v in FIN_RECEIPT_DIRECTION.items()},
    "oms_finance.fin_write_off.writeoff_type": {v: k for k, v in FIN_WRITE_OFF_WRITEOFF_TYPE.items()},
    "oms_finance.fin_write_off.auto_flag": {v: k for k, v in FIN_WRITE_OFF_AUTO_FLAG.items()},
    "oms_finance.fin_write_off.reverse_flag": {v: k for k, v in FIN_WRITE_OFF_REVERSE_FLAG.items()},
    "oms_finance.fin_error_table.diff_direction": {v: k for k, v in FIN_ERROR_TABLE_DIFF_DIRECTION.items()},
    "oms_finance.fin_freight_bill_item.tolerance_result": {v: k for k, v in FIN_FREIGHT_BILL_ITEM_TOLERANCE_RESULT.items()},
    "oms_finance.fin_invoice_apply.buyer_type": {v: k for k, v in FIN_INVOICE_APPLY_BUYER_TYPE.items()},
    "oms_finance.fin_invoice_pool.condition_type": {v: k for k, v in FIN_INVOICE_POOL_CONDITION_TYPE.items()},
    "oms_finance.fin_invoice.color": {v: k for k, v in FIN_INVOICE_COLOR.items()},
    "oms_finance.fin_invoice.issuer_type": {v: k for k, v in FIN_INVOICE_ISSUER_TYPE.items()},
    "oms_finance.fin_kingdee_supply.feed_type": {v: k for k, v in FIN_KINGDEE_SUPPLY_FEED_TYPE.items()},
    "oms_finance.fin_kingdee_supply_file.encrypt_flag": {v: k for k, v in FIN_KINGDEE_SUPPLY_FILE_ENCRYPT_FLAG.items()},
    "oms_finance.fin_kingdee_supply_file.notify_flag": {v: k for k, v in FIN_KINGDEE_SUPPLY_FILE_NOTIFY_FLAG.items()},
    "oms_finance.fin_kingdee_receipt.check_result": {v: k for k, v in FIN_KINGDEE_RECEIPT_CHECK_RESULT.items()},
    "oms_finance.fin_kingdee_receipt.timeout_alert": {v: k for k, v in FIN_KINGDEE_RECEIPT_TIMEOUT_ALERT.items()},
    "oms_org.org_node.status": {v: k for k, v in ORG_NODE_STATUS.items()},
    "oms_org.org_node_relation.is_primary": {v: k for k, v in ORG_NODE_RELATION_IS_PRIMARY.items()},
    "oms_org.org_node_relation.status": {v: k for k, v in ORG_NODE_RELATION_STATUS.items()},
    "oms_org.org_owner.status": {v: k for k, v in ORG_OWNER_STATUS.items()},
    "oms_org.org_owner_contract.status": {v: k for k, v in ORG_OWNER_CONTRACT_STATUS.items()},
    "oms_org.org_owner_settle_config.settle_period_type": {v: k for k, v in ORG_OWNER_SETTLE_CONFIG_SETTLE_PERIOD_TYPE.items()},
    "oms_org.org_owner_settle_config.payment_start_basis": {v: k for k, v in ORG_OWNER_SETTLE_CONFIG_PAYMENT_START_BASIS.items()},
    "oms_org.org_owner_settle_config.status": {v: k for k, v in ORG_OWNER_SETTLE_CONFIG_STATUS.items()},
    "oms_org.org_shop_owner_transfer.approval_status": {v: k for k, v in ORG_SHOP_OWNER_TRANSFER_APPROVAL_STATUS.items()},
    "oms_org.org_shop_owner_transfer.status": {v: k for k, v in ORG_SHOP_OWNER_TRANSFER_STATUS.items()},
    "oms_org.org_tenant.status": {v: k for k, v in ORG_TENANT_STATUS.items()},
    "oms_org.org_account.status": {v: k for k, v in ORG_ACCOUNT_STATUS.items()},
    "oms_org.org_account_credential.must_change_pwd": {v: k for k, v in ORG_ACCOUNT_CREDENTIAL_MUST_CHANGE_PWD.items()},
    "oms_org.org_account_credential.status": {v: k for k, v in ORG_ACCOUNT_CREDENTIAL_STATUS.items()},
    "oms_org.org_session.status": {v: k for k, v in ORG_SESSION_STATUS.items()},
    "oms_org.org_session.login_result": {v: k for k, v in ORG_SESSION_LOGIN_RESULT.items()},
    "oms_org.org_role.portal_flag": {v: k for k, v in ORG_ROLE_PORTAL_FLAG.items()},
    "oms_org.org_role.status": {v: k for k, v in ORG_ROLE_STATUS.items()},
    "oms_org.org_idp_config.enabled": {v: k for k, v in ORG_IDP_CONFIG_ENABLED.items()},
    "oms_org.org_perm_point.internal_only": {v: k for k, v in ORG_PERM_POINT_INTERNAL_ONLY.items()},
    "oms_org.org_perm_point.portal_visible": {v: k for k, v in ORG_PERM_POINT_PORTAL_VISIBLE.items()},
    "oms_org.org_perm_point.status": {v: k for k, v in ORG_PERM_POINT_STATUS.items()},
    "oms_org.org_data_permission.status": {v: k for k, v in ORG_DATA_PERMISSION_STATUS.items()},
    "oms_org.org_filterable_entity.status": {v: k for k, v in ORG_FILTERABLE_ENTITY_STATUS.items()},
    "oms_org.org_field_perm.portal_forbidden": {v: k for k, v in ORG_FIELD_PERM_PORTAL_FORBIDDEN.items()},
    "oms_org.org_field_perm.status": {v: k for k, v in ORG_FIELD_PERM_STATUS.items()},
    "oms_org.org_perm_violation.audit_pushed": {v: k for k, v in ORG_PERM_VIOLATION_AUDIT_PUSHED.items()},
    "oms_org.org_portal_account.audit_status": {v: k for k, v in ORG_PORTAL_ACCOUNT_AUDIT_STATUS.items()},
    "oms_org.org_portal_message.read_status": {v: k for k, v in ORG_PORTAL_MESSAGE_READ_STATUS.items()},
    "oms_org.org_portal_read_log.sampled": {v: k for k, v in ORG_PORTAL_READ_LOG_SAMPLED.items()},
    "oms_org.org_approval_scene.default_need": {v: k for k, v in ORG_APPROVAL_SCENE_DEFAULT_NEED.items()},
    "oms_org.org_approval_scene.fixed_must": {v: k for k, v in ORG_APPROVAL_SCENE_FIXED_MUST.items()},
    "oms_org.org_approval_scene.stub_mode": {v: k for k, v in ORG_APPROVAL_SCENE_STUB_MODE.items()},
    "oms_org.org_approval_scene.status": {v: k for k, v in ORG_APPROVAL_SCENE_STATUS.items()},
    "oms_org.org_approval_threshold.need_approval": {v: k for k, v in ORG_APPROVAL_THRESHOLD_NEED_APPROVAL.items()},
    "oms_org.org_approval_threshold.status": {v: k for k, v in ORG_APPROVAL_THRESHOLD_STATUS.items()},
    "oms_org.org_approval_instance.urgent_flag": {v: k for k, v in ORG_APPROVAL_INSTANCE_URGENT_FLAG.items()},
    "oms_org.org_approval_instance.auto_flag": {v: k for k, v in ORG_APPROVAL_INSTANCE_AUTO_FLAG.items()},
    "oms_org.org_approval_instance.status": {v: k for k, v in ORG_APPROVAL_INSTANCE_STATUS.items()},
    "oms_org.org_approval_instance.execute_check_status": {v: k for k, v in ORG_APPROVAL_INSTANCE_EXECUTE_CHECK_STATUS.items()},
    "oms_org.org_oa_callback_log.direction": {v: k for k, v in ORG_OA_CALLBACK_LOG_DIRECTION.items()},
    "oms_org.org_oa_callback_log.sign_verified": {v: k for k, v in ORG_OA_CALLBACK_LOG_SIGN_VERIFIED.items()},
    "oms_org.org_oa_callback_log.process_status": {v: k for k, v in ORG_OA_CALLBACK_LOG_PROCESS_STATUS.items()},
    "oms_org.aud_operation_log.sensitive_level": {v: k for k, v in AUD_OPERATION_LOG_SENSITIVE_LEVEL.items()},
    "oms_org.aud_data_access_log.risk_flag": {v: k for k, v in AUD_DATA_ACCESS_LOG_RISK_FLAG.items()},
    "oms_org.aud_data_access_log.anonymized": {v: k for k, v in AUD_DATA_ACCESS_LOG_ANONYMIZED.items()},
    "oms_org.aud_entity_registry.status": {v: k for k, v in AUD_ENTITY_REGISTRY_STATUS.items()},
    "oms_org.aud_hash_anchor.verify_status": {v: k for k, v in AUD_HASH_ANCHOR_VERIFY_STATUS.items()},
    "oms_org.aud_retention_policy.policy_level": {v: k for k, v in AUD_RETENTION_POLICY_POLICY_LEVEL.items()},
    "oms_org.aud_retention_policy.status": {v: k for k, v in AUD_RETENTION_POLICY_STATUS.items()},
    "oms_report.rpt_indicator_dict.status": {v: k for k, v in RPT_INDICATOR_DICT_STATUS.items()},
    "oms_report.rpt_snapshot_task.status": {v: k for k, v in RPT_SNAPSHOT_TASK_STATUS.items()},
    "oms_report.rpt_snapshot_task.rerun_flag": {v: k for k, v in RPT_SNAPSHOT_TASK_RERUN_FLAG.items()},
    "oms_report.rpt_product_sale_rank.window_type": {v: k for k, v in RPT_PRODUCT_SALE_RANK_WINDOW_TYPE.items()},
    "oms_report.rpt_product_sale_rank.rank_type": {v: k for k, v in RPT_PRODUCT_SALE_RANK_RANK_TYPE.items()},
    "oms_report.rpt_stock_snapshot.owner_type": {v: k for k, v in RPT_STOCK_SNAPSHOT_OWNER_TYPE.items()},
    "oms_report.rpt_stock_age.age_bucket": {v: k for k, v in RPT_STOCK_AGE_AGE_BUCKET.items()},
    "oms_report.rpt_near_expire.expire_level": {v: k for k, v in RPT_NEAR_EXPIRE_EXPIRE_LEVEL.items()},
    "oms_report.rpt_near_expire.disposal_status": {v: k for k, v in RPT_NEAR_EXPIRE_DISPOSAL_STATUS.items()},
    "oms_report.rpt_stockout.age_level": {v: k for k, v in RPT_STOCKOUT_AGE_LEVEL.items()},
    "oms_report.rpt_stockout.suggest_status": {v: k for k, v in RPT_STOCKOUT_SUGGEST_STATUS.items()},
    "oms_report.rpt_timeout_alert.status": {v: k for k, v in RPT_TIMEOUT_ALERT_STATUS.items()},
    "oms_report.rpt_aftersale.apply_type": {v: k for k, v in RPT_AFTERSALE_APPLY_TYPE.items()},
    "oms_report.rpt_aftersale.denominator_type": {v: k for k, v in RPT_AFTERSALE_DENOMINATOR_TYPE.items()},
    "oms_report.rpt_profit.category_level": {v: k for k, v in RPT_PROFIT_CATEGORY_LEVEL.items()},
    "oms_report.rpt_profit.freight_caliber": {v: k for k, v in RPT_PROFIT_FREIGHT_CALIBER.items()},
    "oms_report.rpt_profit.period_locked": {v: k for k, v in RPT_PROFIT_PERIOD_LOCKED.items()},
    "oms_report.rpt_service_fee.net_direction": {v: k for k, v in RPT_SERVICE_FEE_NET_DIRECTION.items()},
    "oms_report.rpt_order_wide.order_type": {v: k for k, v in RPT_ORDER_WIDE_ORDER_TYPE.items()},
    "oms_report.rpt_order_wide.audit_mode": {v: k for k, v in RPT_ORDER_WIDE_AUDIT_MODE.items()},
    "oms_report.rpt_order_wide.has_aftersale": {v: k for k, v in RPT_ORDER_WIDE_HAS_AFTERSALE.items()},
    "oms_report.rpt_order_wide.aftersale_type": {v: k for k, v in RPT_ORDER_WIDE_AFTERSALE_TYPE.items()},
    "oms_report.rpt_order_wide.refund_status": {v: k for k, v in RPT_ORDER_WIDE_REFUND_STATUS.items()},
    "oms_report.rpt_order_wide.qc_good_flag": {v: k for k, v in RPT_ORDER_WIDE_QC_GOOD_FLAG.items()},
    "oms_report.rpt_order_wide.platform_intervened": {v: k for k, v in RPT_ORDER_WIDE_PLATFORM_INTERVENED.items()},
    "oms_report.rpt_stock_wide.owner_type": {v: k for k, v in RPT_STOCK_WIDE_OWNER_TYPE.items()},
    "oms_report.rpt_stock_wide.slow_moving_flag": {v: k for k, v in RPT_STOCK_WIDE_SLOW_MOVING_FLAG.items()},
    "oms_report.rpt_settlement_wide.owner_type": {v: k for k, v in RPT_SETTLEMENT_WIDE_OWNER_TYPE.items()},
    "oms_report.rpt_settlement_wide.redflush_flag": {v: k for k, v in RPT_SETTLEMENT_WIDE_REDFLUSH_FLAG.items()},
    "oms_report.rpt_settlement_wide.net_direction": {v: k for k, v in RPT_SETTLEMENT_WIDE_NET_DIRECTION.items()},
    "oms_report.rpt_settlement_wide.status": {v: k for k, v in RPT_SETTLEMENT_WIDE_STATUS.items()},
    "oms_report.rpt_bi_push_log.batch_type": {v: k for k, v in RPT_BI_PUSH_LOG_BATCH_TYPE.items()},
    "oms_report.rpt_bi_push_log.channel": {v: k for k, v in RPT_BI_PUSH_LOG_CHANNEL.items()},
    "oms_report.rpt_bi_push_log.status": {v: k for k, v in RPT_BI_PUSH_LOG_STATUS.items()},
    "oms_report.rpt_bi_push_log.recon_status": {v: k for k, v in RPT_BI_PUSH_LOG_RECON_STATUS.items()},
    "oms_report.rpt_monitor_metric.alert_mark": {v: k for k, v in RPT_MONITOR_METRIC_ALERT_MARK.items()},
    "oms_report.rpt_monitor_metric.reg_status": {v: k for k, v in RPT_MONITOR_METRIC_REG_STATUS.items()},
    "oms_report.rpt_alert_claim.alert_level": {v: k for k, v in RPT_ALERT_CLAIM_ALERT_LEVEL.items()},
    "oms_report.rpt_alert_claim.status": {v: k for k, v in RPT_ALERT_CLAIM_STATUS.items()},
    "oms_report.rpt_alert_claim.escalate_level": {v: k for k, v in RPT_ALERT_CLAIM_ESCALATE_LEVEL.items()},
}
