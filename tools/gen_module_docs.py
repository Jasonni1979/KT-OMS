"""生成 8 份模块契约草案（contract.md + tables.yaml）
数据来源：docs/架构-模块化改造设计.md 的切分表 + information_schema 实测表名
"""
import pathlib

OUT = pathlib.Path("/Users/wise01/Documents/Workbuddy workspace/OMS:WMS 自研/KT-OMS/docs/架构/modules")
OUT.mkdir(parents=True, exist_ok=True)

BASE_ALL = """bas_alert_record bas_consume_idempotent bas_dead_letter bas_entity_meta
bas_event_dict bas_export_task bas_field_meta bas_ie_template bas_import_error
bas_import_task bas_message_trace bas_migration_mapping bas_notify_log
bas_notify_route bas_notify_template bas_pipl_consent bas_pipl_ds_request
bas_pipl_policy bas_plugin_registry bas_rule bas_rule_condition bas_rule_dict
bas_rule_test_log bas_rule_version bas_schedule_log bas_schedule_task bas_seq
bas_task_dependency""".split()

ORG_ALL = """org_account org_account_credential org_account_role org_approval_instance
org_approval_scene org_approval_threshold org_data_permission org_field_perm
org_filterable_entity org_idp_config org_node org_node_relation org_oa_callback_log
org_owner org_owner_contract org_owner_settle_config org_perm_point
org_perm_violation org_portal_account org_portal_export_log org_portal_message
org_portal_notify_pref org_portal_read_log org_role org_role_perm org_session
org_shop_owner_transfer org_tenant""".split()

STOCK_ALL = """inv_activity_lock_pool inv_alert_rule inv_barcode inv_batch inv_batch_assign
inv_batch_stock inv_bom_item inv_bom_version inv_brand inv_consignment_value
inv_cost_change_log inv_cost_config inv_cost_snapshot inv_estimate_batch
inv_expire_disposal inv_expire_rule inv_freeze_log inv_fukubukuro_item
inv_fukubukuro_plan inv_independent_quota inv_io_bill inv_io_bill_item
inv_io_bill_type inv_io_callback_log inv_lend_ledger inv_lend_rule
inv_manual_freeze inv_material inv_material_cat inv_ownership_transfer
inv_ownership_transfer_item inv_pickone_candidate inv_price_adjust_item
inv_price_adjust_plan inv_price_archive inv_price_sync_task inv_price_version
inv_replenish_suggestion inv_sales_forecast inv_sales_material inv_sellable_snapshot
inv_serial_no inv_stock_adjust inv_stock_change_log inv_stock_config
inv_stock_ledger inv_stock_recon_diff inv_stock_snapshot inv_stocktake_item
inv_stocktake_plan inv_stocktake_task inv_sync_log inv_sync_strategy
inv_transfer_item inv_transfer_order""".split()

ORDER_TRADE = """ord_order ord_order_item ord_receiver ord_order_pmt ord_order_fail
ord_status_log ord_audit_reason ord_audit_plugin_perf ord_audit_work_log
ord_audit_task ord_audit_batch_log ord_audit_group ord_audit_rule
ord_combine_blacklist ord_combine_group""".split()

AUDIT_ALL = """aud_data_access_log aud_destroy_log aud_entity_registry
aud_hash_anchor aud_operation_log aud_retention_policy""".split()

FULFILL_ALL = """ful_addr_keyword ful_area_router ful_branch ful_branch_dly
ful_call_decision ful_carrier ful_carrier_metric ful_channel_log ful_city_freight
ful_cmd_fail ful_dly_corp ful_dly_product ful_freight_region_price
ful_freight_template ful_handover ful_inbound_callback ful_inbound_cmd
ful_inbound_diff ful_outbound_buffer ful_outbound_callback ful_outbound_cmd
ful_print_log ful_print_task ful_print_template ful_print_tmpl_binding
ful_rider_call ful_rider_track ful_route_log ful_shop_carrier ful_shop_dly
ful_store_carrier_map ful_suspend ful_trace_node ful_trace_sub
ful_unreach_area ful_waybill ful_waybill_account ful_waybill_segment ful_wms
ful_wms_binding ful_wms_health""".split()

ORDER_FULFILL = """ord_delivery ord_delivery_item ord_delivery_item_detail
ord_delivery_log ord_delivery_diff ord_delivery_package ord_dispatch_plan
ord_dispatch_rule ord_branch_dispatch_rule ord_routing_decision_log
ord_branch_change_log ord_split_rule ord_split_trace ord_fulfill_plan""".split()

ORDER_ABNORMAL = """ord_abnormal ord_abnormal_type_dict ord_reason_code_dict
ord_stockout ord_oversold_batch ord_risk_list ord_pause_command_log
ord_retrial""".split()

AFTERSALE_ALL = """aft_audit_task aft_auto_audit_log aft_auto_audit_rule
aft_buyer_profile aft_defect_disposal aft_exchange aft_exchange_item
aft_exchange_log aft_reason_dict aft_refund aft_refund_alloc aft_refund_log
aft_reship aft_reship_item aft_reship_package aft_reship_sn aft_return_address
aft_return_apply aft_return_apply_item aft_return_apply_log aft_return_logistics
aft_risk_flag aft_timeout_monitor""".split()

ORDER_MODIFY = "ord_order_modify ord_order_snapshot ord_modify_log".split()

GATEWAY_ALL = """gw_adapter_config gw_api_fail gw_api_log gw_credential_audit
gw_enum_mapping gw_errcode_dict gw_msg_notify gw_openapi_app gw_openapi_log
gw_openapi_register gw_order_buffer gw_order_buffer_item
gw_order_buffer_promotion gw_platform_config gw_pull_watermark
gw_ratelimit_config gw_recon_diff gw_rpc_pending gw_shop gw_shop_auth
gw_shop_config gw_stock_sync_batch gw_stock_sync_item gw_writeback_task""".split()

REPORT_ALL = """rpt_aftersale rpt_alert_claim rpt_audit_perf rpt_bi_push_log
rpt_fulfill_sla rpt_indicator_dict rpt_monitor_metric rpt_near_expire
rpt_order_wide rpt_platform_compare rpt_product_sale_rank rpt_profit
rpt_sales_daily rpt_sales_monthly rpt_service_fee rpt_settlement_wide
rpt_slow_moving rpt_snapshot_task rpt_stock_age rpt_stock_snapshot
rpt_stock_turnover rpt_stock_wide rpt_stockout rpt_timeout_alert""".split()

UNASSIGNED = """ord_archive_config ord_archive_log ord_card_secret ord_declare
ord_flag_change_log ord_gift_log ord_groupon ord_instant_delivery
ord_instant_track ord_luckybag_alloc ord_order_archive ord_order_invoice
ord_pickup ord_presale ord_promotion_activity ord_promotion_gift
ord_promotion_rule ord_promotion_scope ord_shop_fulfill_config
ord_store_order ord_store_profile ord_virtual_delivery""".split()


def q(schema, names):
    return [f"oms_{schema}.{n}" for n in names]


MODULES = [
    dict(
        code="M1", slug="m1_master", name="基础主数据", dir="m1_master",
        duty="组织树 / 货主 / 店铺 / 账号 / 角色 / 数据权限范围 / 字典与规则 / 事件字典",
        services=["master", "branch_owner", "auth", "permission"],
        lines=1197,
        write=[("oms_base", BASE_ALL), ("oms_org", ORG_ALL)],
        ro=[
            ("master.get_node", "按 id 取组织节点"),
            ("master.list_nodes", "按父节点列子节点"),
            ("master.children", "递归子树"),
            ("master.search", "按关键字搜节点"),
            ("master.is_buyout", "是否买断型货主"),
            ("branch_owner.list_by_owner", "货主 → 关联组织"),
            ("branch_owner.list_by_branch", "组织 → 关联货主"),
            ("permission.get_scope", "账户的数据权限范围（owner/shop/branch/brand）"),
            ("auth.permissions_of", "账户权限点集合"),
        ],
        rw=[
            ("master.create_node", "建组织节点"),
            ("master.update_node", "改组织节点"),
            ("master.delete_node", "删组织节点（软删）"),
            ("branch_owner.bind", "绑定货主与组织"),
            ("branch_owner.unbind", "解绑"),
        ],
        deps=[],           # (下游模块, 类型, 说明)
        forbids_read=[],
        forbids_write=[],
        notes=[
            "**最底层模块**：不得依赖任何其它模块（门禁 R1 强约束）。",
            "`bas_event_outbox` 是**多写者白名单表**（M4 / M7 共同写），不计入本模块独占写权。",
            "权限与数据范围（`org_data_permission` / `org_field_perm`）由本模块独家维护 —— "
            "改权限规则只应动 M1，不应从其它模块绕过。",
        ],
    ),
    dict(
        code="M2", slug="m2_stock", name="商品与库存账本", dir="m2_stock",
        duty="物料 / SKU 映射 / 可用量计算 / 库存台账 / 预占冻结 / 出入库单 / 盘点对账",
        services=["material", "sku_mapping", "stock_ledger", "freeze", "sellable",
                  "stock_recon", "io_bill"],
        lines=3161,
        write=[("oms_stock", STOCK_ALL)],
        ro=[
            ("stock_ledger.available_of", "查可用量（扣冻结后）"),
            ("stock_ledger.get_balance", "查台账余额"),
            ("stock_ledger.get_row", "按库存键查台账行"),
            ("stock_ledger.query", "台账流水查询"),
            ("sku_mapping.find_sales_material", "平台 SKU → 基础物料"),
            ("sellable.calc", "批量算可售"),
            ("sellable.calc_single", "单物料算可售"),
            ("sellable.get_strategy", "取可售策略"),
            ("sellable.shop_branches", "店铺可用仓"),
            ("material.get", "按 id 取物料"),
            ("material.list_all", "物料全量列表"),
            ("material.children", "物料分类子树"),
            ("freeze.query_logs", "冻结流水查询"),
        ],
        rw=[
            ("stock_ledger.apply_change", "台账变更（唯一写入口）"),
            ("stock_ledger.adjust", "库存调整"),
            ("freeze.reserve", "预占冻结"),
            ("freeze.release", "释放冻结"),
            ("freeze.settle", "冻结结算（发货核销）"),
            ("freeze.expire_reclaim", "过期回收"),
            ("io_bill.create", "出入库单创建"),
            ("io_bill.push_to_wms", "出入库单推 WMS"),
            ("io_bill.confirm", "出入库单确认"),
            ("material.create", "建物料"),
            ("material.update", "改物料"),
        ],
        deps=[("M1", "读", "查组织 / 货主 / 店铺（`material→master`）")],
        forbids_read=["M3 / M4 / M5 / M6 / M7 的任何符号"],
        forbids_write=["oms_order.*", "oms_fulfill.*", "oms_aftersale.*", "oms_gateway.*"],
        notes=[
            "**库存是全系统唯一的余额真相源** —— 其它模块不得直接写 `inv_stock_ledger` / `inv_freeze_log`。",
            "`freeze` 与 `stock_ledger` 的耦合方向必须保持 `freeze → stock_ledger`（冻结记流水，台账记余额）。",
            "Redis 可售缓存由 `sellable` 独占维护，失效只经 `sellable.invalidate*`。",
        ],
    ),
    dict(
        code="M3", slug="m3_trade", name="订单与审单", dir="m3_trade",
        duty="订单建单 / 单号生成 / 金额分摊 / 审单插件链 / 审单原因落库",
        services=["order_create", "order_bn", "allocation", "audit_engine",
                  "audit_plugins", "audit_rule"],
        lines=2461,
        write=[("oms_order", ORDER_TRADE), ("oms_audit", AUDIT_ALL)],
        ro=[
            ("audit_engine.blocked", "订单是否被审单拦截"),
            ("audit_engine.reason_codes", "该单的审单原因码集合"),
            ("audit_engine.load_context", "审单上下文（插件链共享）"),
            ("audit_rule.matches", "规则命中判定"),
            ("audit_rule.explain", "规则命中解释"),
            ("audit_rule.in_effective_window", "规则是否在生效窗口"),
            ("order_create.get_order", "取订单快照（**需新增**）"),
        ],
        rw=[
            ("order_create.create", "建单（幂等）"),
            ("audit_engine.submit", "提交审单（跑插件链）"),
            ("audit_engine.write_reasons", "落审单原因"),
            ("audit_engine.save_plan", "落分派计划"),
            ("audit_engine.clear_reasons", "清审单原因（闭环联动，**M4 需经此接口**）"),
        ],
        deps=[
            ("M1", "读", "组织 / 货主 / 店铺"),
            ("M2", "读", "查库存可用量（`audit_plugins→stock_ledger`）、SKU 映射（`order_create→sku_mapping`）"),
            ("M4", "读", "审单插件做**预演拆单**（`audit_plugins→split_service/dispatch_service`）"),
            ("M5", "写", "审单落异常单（`audit_engine→abnormal`）"),
        ],
        forbids_read=["M6 / M7 / M8 的任何符号"],
        forbids_write=["oms_fulfill.*", "oms_aftersale.*", "oms_gateway.*",
                        "oms_order.ord_abnormal*", "oms_order.ord_delivery*"],
        notes=[
            "**M3 → M4 属「相邻层协作·读」**：审单阶段预演拆单（选仓 / 拆单测算）是业务必需，登记为白名单边。",
            "**M3 → M5 属「相邻层协作·写」**：审单落异常单。M5 必须暴露公开写接口 `abnormal.raise_by_reason`。",
            "`ord_audit_reason` 的写权**独归 M3** —— M4 的 `plan_executor` 当前直接写该表，"
            "**待收口**：改调 M3 的 `audit_engine.clear_reasons`。",
        ],
    ),
    dict(
        code="M4", slug="m4_fulfill", name="履约与发货", dir="m4_fulfill",
        duty="拆单 / 发货单 / 四指令状态机 / 分派计划执行 / 换仓重试",
        services=["split_service", "plan_executor", "delivery_service",
                  "dispatch", "dispatch_service"],
        lines=4402,
        write=[("oms_fulfill", FULFILL_ALL), ("oms_order", ORDER_FULFILL)],
        ro=[
            ("delivery_service.get", "取发货单快照"),
            ("delivery_service.query_order", "按订单查发货单"),
            ("dispatch_service.get_fulfill_view", "订单的履约视图"),
            ("plan_executor.get_plan", "取分派计划"),
            ("plan_executor.list_plans", "列分派计划"),
            ("split_service.get", "取拆单结果"),
            ("dispatch.match_rule", "分派规则匹配"),
        ],
        rw=[
            ("delivery_service.create_from_plan", "由计划生成发货单"),
            ("delivery_service.transit", "发货单状态机推进（唯一入口）"),
            ("delivery_service.push", "推 WMS"),
            ("delivery_service.recall", "叫回"),
            ("delivery_service.recall_result", "叫回结果回写"),
            ("delivery_service.resume", "恢复（重推）"),
            ("delivery_service.confirm", "发货确认"),
            ("delivery_service.finish", "完结"),
            ("plan_executor.execute", "执行计划"),
            ("plan_executor.execute_manual_plan", "执行人工计划"),
            ("plan_executor.discard_plan", "废弃计划"),
            ("dispatch_service.dispatch", "分派"),
            ("dispatch_service.change_branch", "换仓"),
            ("dispatch_service.retry_with_gap", "错峰重试"),
        ],
        deps=[
            ("M1", "读", "组织 / 货主 / 店铺"),
            ("M2", "读写", "占用与释放库存（`dispatch_service/split_service→stock_ledger`、`plan_executor→freeze`）"),
            ("M7", "写", "推 WMS 指令 / 叫回（`delivery_service→wms_channel`）"),
        ],
        forbids_read=["M5 / M6 / M8 的任何符号"],
        forbids_write=["oms_order.ord_order", "oms_order.ord_order_item",
                        "oms_order.ord_abnormal*", "oms_order.ord_audit_reason",
                        "oms_stock.*", "oms_aftersale.*"],
        notes=[
            "**M4 → M7 属「适配器调用」**：发货推 WMS 指令是主链路，方向合理。",
            "**M4 ↔ M7 的反向边（M7 → M4，回传推进发货单）属「回调关系」**，不是逻辑环 —— "
            "已在设计文档 §5.2 登记为白名单。",
            "**待收口**：`plan_executor` 直接写 `ord_audit_reason`（M3 的表）→ 改调 M3 的 `clear_reasons`。",
            "**待收口**：`wms_channel ⇄ wms_events` 模块内循环依赖 → P3 拆分时消除。",
            "本模块是**最大的一个**（4.4k 行 / 5 service）→ P3 必须把 `delivery_service`（1403 行）拆开。",
        ],
    ),
    dict(
        code="M5", slug="m5_abnormal", name="异常单域", dir="m5_abnormal",
        duty="异常单 / 类型字典 / 分派引擎 / 动作执行器 / 缺货策略链 / 应急批次 / 名单服务 / 告警扫描",
        services=["abnormal", "abnormal_action", "abnormal_dispatch",
                  "abnormal_ext", "stockout_strategy"],
        lines=2604,
        write=[("oms_order", ORDER_ABNORMAL)],
        ro=[
            ("abnormal.types_all", "全部异常类型"),
            ("abnormal.reason_dict", "原因码字典"),
            ("abnormal.type_by_reason_code", "原因码 → 类型"),
            ("abnormal.get", "取异常单详情"),
            ("abnormal_ext.batch_sla_status", "批次分级 SLA 状态"),
            ("abnormal_ext.list_pause_logs", "暂停命令日志"),
        ],
        rw=[
            ("abnormal.create", "创建异常单（幂等）"),
            ("abnormal.raise_by_reason", "由审单原因落异常单（**M3 需经此接口**）"),
            ("abnormal.transit", "异常单状态流转"),
            ("abnormal.dispatch", "触发分派"),
            ("abnormal_action.execute", "执行动作（白名单校验）"),
            ("abnormal_action.clear_reasons", "清审单原因（经 M3 接口）"),
            ("abnormal_ext.aggregate_oversold_batch", "超卖聚合建批"),
            ("abnormal_ext.advance_batch", "批次阶段推进"),
            ("abnormal_ext.pause_order", "订单暂停编排"),
            ("abnormal_ext.resume_order", "订单恢复"),
            ("abnormal_ext.add_to_list", "加名单（须带 OA 审批单号）"),
            ("abnormal_ext.remove_from_list", "移名单"),
            ("stockout_strategy.calc_switch_branch", "换仓测算"),
            ("stockout_strategy.switch_branch", "换仓重试"),
            ("stockout_strategy.release_and_retry", "解除重审"),
        ],
        deps=[
            ("M1", "读", "组织 / 货主 / 店铺 / 审批场景"),
            ("M2", "读", "查库存可用量（`stockout_strategy→stock_ledger`）"),
            ("M3", "读写", "读审单引擎与单号规则；清审单原因经 M3 接口"),
            ("M4", "读写", "换仓重试 / 解除重审需改履约（`abnormal_action/stockout_strategy→plan_executor/dispatch_service`）"),
            ("M6", "写", "转售后（`abnormal_action→aftersale`）"),
        ],
        forbids_read=["M7 / M8 的任何符号"],
        forbids_write=["oms_order.ord_order", "oms_order.ord_order_item",
                        "oms_order.ord_audit_reason", "oms_order.ord_delivery*",
                        "oms_fulfill.*", "oms_aftersale.*", "oms_gateway.*"],
        notes=[
            "**M5 ↔ M6 属「业务协作」**（异常单 → 转售后 / 改单 → 落异常单），双向已在设计文档登记。",
            "**动作白名单由 DDL 的 `action_set` 决定** —— 越权动作被拒是正确行为（FR-02d），不是缺陷。",
            "`ord_abnormal` 无 `batch_id` 列 —— 批次关联路径是 **异常单 → `ord_stockout.batch_id` → 批次**。",
            "名单服务（`ord_risk_list`）两层库：私有优先（货主 > 租户 > 全局）。",
        ],
    ),
    dict(
        code="M6", slug="m6_aftersale", name="售后与改单", dir="m6_aftersale",
        duty="售后申请 / 审核 / 退款单 / 改地址（快照 + 差异对比 + 叫回联动）",
        services=["aftersale", "modify"],
        lines=1522,
        write=[("oms_aftersale", AFTERSALE_ALL), ("oms_order", ORDER_MODIFY)],
        ro=[
            ("aftersale.list_applies", "列售后申请"),
            ("aftersale.get_apply", "取售后申请详情"),
            ("modify.list_modifies", "列改单"),
            ("modify.get_modify", "取改单详情（含快照与差异）"),
        ],
        rw=[
            ("aftersale.create_apply", "建售后申请（幂等）"),
            ("aftersale.transit", "售后单状态流转（§5.1 权威流转表）"),
            ("aftersale.audit", "审核（同意 / 拒绝）"),
            ("aftersale.create_refund", "生成退款单"),
            ("aftersale.refund_transit", "退款单状态推进"),
            ("modify.create_address_modify", "发起改地址改单"),
            ("modify.complete_recall_and_effective", "叫回成功后生效"),
            ("modify.cancel_recall_modify", "撤销改单恢复现场"),
        ],
        deps=[
            ("M1", "读", "组织 / 货主 / 店铺"),
            ("M4", "写", "叫回发货单（`modify→wms_channel` 经 M7，此处为业务协作）"),
            ("M5", "读写", "查异常单；改单失败落异常单（`modify→abnormal`）"),
            ("M7", "写", "叫回指令（`modify→wms_channel`）"),
        ],
        forbids_read=["M2 / M3 / M8 的任何符号"],
        forbids_write=["oms_order.ord_order", "oms_order.ord_order_item",
                        "oms_order.ord_abnormal*", "oms_order.ord_audit_reason",
                        "oms_stock.*", "oms_fulfill.*", "oms_gateway.*"],
        notes=[
            "**收货人密文不落明文**：`ord_receiver.name_enc/mobile_enc/address_enc` 是 blob，"
            "快照与差异对比一律用 hex（PIPL 合规）。",
            "售后状态是 **tinyint**（0=待关联 … 7=完成 / 8=拒绝 / 9=关闭），枚举以 **DDL COMMENT 为权威**。",
            "`aft_return_apply` 有 3 个 **VIRTUAL 生成列**（`platform_refund_id` / `cs_intervene_flag` / "
            "`platform_aftersale_type_raw`）→ **不得 INSERT、不得映射为 ORM 可写列**。",
            "改单表 `ord_order_modify` / `ord_order_snapshot` 此前**无 ORM 模型**，W9 已补。",
        ],
    ),
    dict(
        code="M7", slug="m7_integration", name="外部集成", dir="m7_integration",
        duty="平台拉单 / 平台回传 / WMS 指令通道 / 导入中心",
        services=["gateway", "pull", "sync", "wms_channel", "wms_events",
                  "writeback", "import_center"],
        lines=3206,
        write=[("oms_gateway", GATEWAY_ALL)],
        ro=[
            ("gateway.call", "调平台 OpenAPI（统一入口）"),
            ("pull.get_watermark", "拉单水位"),
            ("sync.sync_status", "库存同步状态"),
            ("wms_channel.query_order", "查 WMS 侧订单状态"),
            ("writeback.list_tasks", "列回传任务"),
        ],
        rw=[
            ("pull.poll_shop", "按店铺轮询拉单"),
            ("pull.pull_single", "单店拉单"),
            ("sync.writeback", "库存回传"),
            ("sync.writeback_shop", "单店库存回传"),
            ("sync.recon_shop", "库存对账"),
            ("wms_channel.push", "推 WMS 出库指令"),
            ("wms_channel.recall", "叫回"),
            ("wms_channel.resume", "恢复（重推）"),
            ("wms_channel.receive_callback", "接收 WMS 回传（落回调 + 触发编排）"),
            ("writeback.send_delivery", "发货回传平台"),
            ("writeback.on_order_shipped", "订单已发货回传"),
            ("writeback.retry_pending", "重试待发回传"),
            ("import_center.create_task", "建导入任务"),
            ("import_center.run_task", "跑导入任务"),
        ],
        deps=[
            ("M1", "读", "店铺 / 货主 / 组织"),
            ("M2", "读", "SKU 映射 / 可售（`pull→sku_mapping`、`sync→sellable`）"),
            ("M3", "写", "拉单建单（`pull→order_create`）"),
            ("M4", "写", "回传推进发货单（`wms_events→delivery_service`）"),
            ("M5", "写", "回传异常落单（`wms_events→abnormal`）"),
        ],
        forbids_read=["M6 / M8 的任何符号"],
        forbids_write=["oms_order.*", "oms_fulfill.*", "oms_stock.*",
                        "oms_aftersale.*", "oms_base.bas_event_outbox（白名单除外）"],
        notes=[
            "**本模块是未来的首个拆分候选**（IO 密集 / 故障域独立），契约已为此预留。",
            "**两套错误分级不可混用**：通道侧 `ful_cmd_fail.err_class` = RETRYABLE/FATAL/BIZ_REJECT；"
            "平台侧 `gw_api_fail.err_level` = RETRYABLE/RATE_LIMITED/AUTH/MANUAL/FATAL。",
            "**回传幂等键 = 发货单号 + 批次号 + 类型** —— 造演示数据时单号必须唯一。",
            "**待收口**：`wms_channel ⇄ wms_events` 模块内循环 → P3 消除。",
        ],
    ),
    dict(
        code="M8", slug="m8_insight", name="报表与监控", dir="m8_insight",
        duty="履约监控看板 / 指标 / 数据体检（只读全部模块）",
        services=["monitor"],
        lines=298,
        write=[("oms_report", REPORT_ALL)],
        ro=[
            ("monitor.overview", "看板总览（指标卡 + 分域明细）"),
            ("monitor.pull_watermark", "拉单水位"),
            ("monitor.audit_backlog", "审单积压 + SLA 分级"),
            ("monitor.writeback_failures", "回传失败台账"),
            ("monitor.abnormal_realtime", "异常单实时分布"),
        ],
        rw=[],
        deps=[],
        forbids_read=["M1 / M2 / M3 / M4 / M5 / M6 / M7 的内部符号"],
        forbids_write=["除 oms_report.* 外的任何表"],
        notes=[
            "**只读全部模块，但不被任何模块依赖**（最顶层）。",
            "看板当前是**实时快照口径**（直查业务表），非 D11.01 报表口径 —— 差异须在 `caliber_note` 明示。",
            "拉单水位尚未含 Redis 分钟埋点 → W10 统一接入。",
        ],
    ),
]

# ============ P1 门禁 R3 暴露的归属修正（人工裁决结果）============
def _find(code: str) -> dict:
    for _m in MODULES:
        if _m["code"] == code:
            return _m
    raise KeyError(code)


def _move_table(src_code: str, dst_code: str, table: str) -> None:
    """把一张表从某模块的可写清单移到另一模块（人工裁决）"""
    src, dst = _find(src_code), _find(dst_code)
    for _m in (src, dst):
        for _i, (_schema, _names) in enumerate(list(_m["write"])):
            _names = [n for n in _names if f"{_schema}.{n}" != table]
            _m["write"][_i] = (_schema, _names)
    _schema, _tail = table.split(".", 1)
    for _i, (_s, _names) in enumerate(dst["write"]):
        if _s == _schema:
            dst["write"][_i] = (_schema, [*_names, _tail])
            return
    dst["write"].append((_schema, [_tail]))


# ① WMS 通道写的「指令/日志」表归 M7（通道侧产物），不是 M4
for _t in ("ful_outbound_cmd", "ful_outbound_callback", "ful_outbound_buffer",
           "ful_cmd_fail", "ful_channel_log"):
    _move_table("M4", "M7", f"oms_fulfill.{_t}")
# ② 导入中心（import_center）已归 M2 → 其两张表归 M2
for _t in ("bas_import_task", "bas_import_error"):
    _move_table("M1", "M2", f"oms_base.{_t}")

# ---------------- 生成 contract.md ----------------
for m in MODULES:
    lines = []
    A = lines.append
    A(f"# {m['code']} {m['name']}\n")
    A(f"**目录** `backend/app/modules/{m['dir']}/` · **代码行** {m['lines']:,} · "
      f"**service** {len(m['services'])} 个\n")
    A(f"**职责**：{m['duty']}\n")
    A(f"**收编 service**：{', '.join(m['services'])}\n")
    A("---\n")
    A("## 可写表\n")
    A("| schema | 表数 | 表 |")
    A("|---|---|---|")
    for schema, names in m["write"]:
        A(f"| {schema} | {len(names)} | {' '.join(f'`{n}`' for n in names)} |")
    A("\n完整清单见同目录 `tables.yaml`。\n")
    A("## 对外只读接口（跨模块可自由调用）\n")
    A("| 接口 | 说明 |")
    A("|---|---|")
    for sig, desc in m["ro"]:
        A(f"| `{sig}` | {desc} |")
    A("\n## 对外写接口（跨模块调用须在本模块登记）\n")
    if m["rw"]:
        A("| 接口 | 说明 |")
        A("|---|---|")
        for sig, desc in m["rw"]:
            A(f"| `{sig}` | {desc} |")
    else:
        A("（无 —— 本模块不向外暴露写接口）")
    A("\n## 允许的跨模块调用\n")
    if m["deps"]:
        A("| 下游模块 | 类型 | 说明 |")
        A("|---|---|---|")
        for d, t, note in m["deps"]:
            A(f"| {d} | {t} | {note} |")
    else:
        A("（无 —— 本模块不依赖其它模块）")
    A("\n## 禁止\n")
    for f in m["forbids_read"]:
        A(f"- 不得 import {f}")
    for f in m["forbids_write"]:
        A(f"- 不得写 {f}")
    A("- 不得直接 import 其它模块的 `service/` 内部实现 —— 只能从对方 `contract.py` 导入")
    A("- 不得 import `app.tools.simulation`（仿真造数工具，非业务代码）")
    A("\n## 已知待收口点\n")
    for n in m["notes"]:
        A(f"- {n}")
    A("\n## 测试入口\n")
    A(f"```bash\npytest backend/tests/modules/{m['dir']}/ -q\n```\n")
    (OUT / f"{m['code']}-{m['dir']}-contract.md").write_text("\n".join(lines), encoding="utf-8")

    # ---------------- 生成 tables.yaml ----------------
    y = []
    y.append(f"# {m['code']} {m['name']} —— 表所有权声明")
    y.append(f"# 模块目录: backend/app/modules/{m['dir']}/")
    y.append(f"# 门禁: tools/check_table_ownership.py 依据本文件校验「一表一写者」")
    y.append(f"module: {m['code']}")
    y.append(f"slug: {m['dir']}")
    y.append(f"name: {m['name']}")
    y.append("write:")
    for schema, names in m["write"]:
        for n in names:
            # ⚠ schema 已是 "oms_xxx"（不要重复加前缀 —— 之前踩过，
            #   生成了 oms_oms_gateway.* 导致门禁 R3 全部误报）
            full = f"{schema}.{n}" if schema.startswith("oms_") else f"oms_{schema}.{n}"
            y.append(f"  - {full}")
    if not m["write"]:
        y.append("  []")
    y.append("read_only:")
    y.append("  # 本模块只读其它模块的表；读取须经对方 contract.py 的只读接口")
    y.append("  []")
    y.append("external:")
    if m["deps"]:
        for d, t, _note in m["deps"]:
            y.append(f"  - module: {d}")
            y.append(f"    access: {t}")
    else:
        y.append("  []")
    y.append("forbidden_write:")
    for f in m["forbids_write"]:
        if "*" in f:
            schema = f.replace("oms_", "").split(".")[0]
            y.append(f"  - oms_{schema}.*")
        else:
            y.append(f"  - {f}")
    y.append("shared_write:")
    y.append("  # 多写者白名单表（outbox 是事件基础设施，非业务数据）")
    if m["code"] in ("M4", "M7"):
        y.append("  - oms_base.bas_event_outbox")
    y.append("")
    (OUT / f"{m['code']}-{m['dir']}-tables.yaml").write_text("\n".join(y), encoding="utf-8")

# 未分配表清单（后续批次）
un = [
    "# 未分配到任何模块的表（后续批次规划，非缺陷）",
    "# 门禁放行：这些表当前无写者，agent 不得随意认领",
    "",
    "unassigned:",
]
for n in UNASSIGNED:
    un.append(f"  - oms_order.{n}")
un.append("")
(OUT / "UNASSIGNED-tables.yaml").write_text("\n".join(un), encoding="utf-8")

# 后续批次域（财务 / 采购 / 经销）—— 整域留白，不纳入本轮 8 模块
deferred = [
    "# 后续批次域 —— 本轮 8 模块**不覆盖**（整域留白）",
    "# 门禁放行：agent 不得认领这些表的写权",
    "#",
    "# oms_finance 42 张 · oms_purchase 25 张 · oms_dealer 14 张 = 81 张",
    "# 计划归属：W10 财务与采购接入时再切分独立模块",
    "",
    "deferred_domains:",
    "  - schema: oms_finance",
    "    tables: 42",
    "  - schema: oms_purchase",
    "    tables: 25",
    "  - schema: oms_dealer",
    "    tables: 14",
    "",
]
(OUT / "DEFERRED-tables.yaml").write_text("\n".join(deferred), encoding="utf-8")

print(f"已生成 {len(MODULES) * 2 + 2} 个文件 → {OUT}")
for f in sorted(OUT.iterdir()):
    print(f"  {f.name}  ({f.stat().st_size} B)")
