-- ============================================================================
-- DB-D04 库存域建表脚本（oms_stock）
-- 文档编号: DB-D04 · 版本 V1.0 · 2026-10-24 · MySQL 8.0 可执行 DDL
-- 上游契约: DB-00 数据库设计总册（schema=oms_stock / 表前缀 inv_ / 公共字段 / 不建物理外键）
-- 需求依据: SRS-D04.01 ~ SRS-D04.10 §6 数据字段章节
-- ----------------------------------------------------------------------------
-- 执行顺序:
--   1) CREATE DATABASE oms_stock
--   2) 字典/配置表: inv_io_bill_type / inv_material_cat / inv_brand / inv_stock_config / inv_cost_config / inv_expire_rule / inv_alert_rule / inv_stocktake_plan / inv_sync_strategy
--   3) 物料档案族: inv_material / inv_sales_material / inv_bom_version / inv_bom_item / inv_barcode / 福袋 / 多选一
--   4) 记账核心: inv_stock_ledger / inv_stock_change_log / inv_stock_snapshot / inv_stock_adjust / inv_stock_recon_diff
--   5) 预占: inv_freeze_log / inv_manual_freeze
--   6) 单据族: inv_io_bill / inv_io_bill_item / inv_io_callback_log
--   7) 调拨借调: inv_transfer_order / inv_transfer_item / inv_lend_rule / inv_lend_ledger / 货权转移
--   8) 盘点: inv_stocktake_task / inv_stocktake_item
--   9) 成本: inv_cost_change_log / inv_estimate_batch / inv_consignment_value / inv_cost_snapshot
--  10) 可售同步: inv_sellable_snapshot / inv_sync_log / inv_independent_quota
--  11) 批次SN: inv_batch / inv_batch_stock / inv_batch_assign / inv_serial_no / inv_expire_disposal
--  12) 预警建议: inv_replenish_suggestion
--  13) 初始字典数据 INSERT: inv_io_bill_type（出入库单据类型）/ inv_stock_config 全局默认
-- 依赖: 仅本 schema；跨域为逻辑外键 LFK（应用层校验），不建物理外键
-- 分表约定: inv_stock_change_log / inv_sync_log 按月分表 _YYYYMM，本脚本为结构基线表，
--           月度表由调度任务 CREATE TABLE ... LIKE 创建；归档表后缀 _arc
-- 命名/类型基线: 见 DB-00 §2/§6；utf8mb4 / utf8mb4_0900_ai_ci / InnoDB
-- ============================================================================

CREATE DATABASE IF NOT EXISTS oms_stock DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE oms_stock;

-- ============================================================================
-- 一、字典 / 配置表
-- ============================================================================

-- 21. 出入库单据类型字典（D04.04 · P0）← 商派 ome_iostock_type + siso 初始数据改造
CREATE TABLE inv_io_bill_type (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  type_code       VARCHAR(32)     NOT NULL COMMENT '类型码(唯一): purchase_in=采购入库等,见初始数据',
  type_name       VARCHAR(64)     NOT NULL COMMENT '类型名称',
  direction       TINYINT         NOT NULL COMMENT '方向:1=入库,2=出库',
  effect_template JSON            NOT NULL COMMENT '口径影响模板: 数组元素含field(store/freeze/arrive/defective)与sign(1/-1); 销售出库为action=settle经D04.03转扣减',
  need_wms        TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '是否需WMS执行:0=本地记账类,1=仓执行类',
  need_approval   TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '是否需审批:0=否,1=是',
  settle_rel      TINYINT         NOT NULL DEFAULT 0 COMMENT '结算相关性:0=无,1=应付,2=应收',
  status          TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=停用',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_io_bill_type_code (type_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='出入库单据类型字典(D04.04,P0)';

-- 2. 物料分类树（D04.01 · P0，配置表 owner_id 免填）← 商派 basic_material_cat
CREATE TABLE inv_material_cat (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id   BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  cat_name    VARCHAR(128)    NOT NULL COMMENT '分类名称',
  parent_id   BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '父分类ID(0=根)',
  cat_path    VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '分类路径冗余(/根/.../本节点/,子树查询用)',
  cat_level   TINYINT         NOT NULL DEFAULT 1 COMMENT '层级(根=1)',
  sort_no     INT             NOT NULL DEFAULT 0 COMMENT '同级排序',
  status      TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=停用',
  create_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version     INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted  TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  KEY idx_inv_material_cat_parent (parent_id),
  KEY idx_inv_material_cat_path (cat_path)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='物料分类树(D04.01,P0,配置表)';

-- 3. 品牌档案（D04.01 · P0）owner_id=0 表示公共品牌
CREATE TABLE inv_brand (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id     BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '归属货主(0=公共品牌) LFK→oms_org.org_owner',
  brand_name    VARCHAR(128)    NOT NULL COMMENT '品牌名称',
  brand_name_en VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '品牌英文名',
  org_node_id   BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '组织树品牌节点映射 LFK→oms_org.org_node',
  status        TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=停用',
  create_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version       INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted    TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_brand_name (brand_name, owner_id),
  KEY idx_inv_brand_org (org_node_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='品牌档案(D04.01,P0)';

-- 16. 库存参数配置（D04.02/03 · P0，辅助配置表，owner_id 免填）
CREATE TABLE inv_stock_config (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id   BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  config_type TINYINT         NOT NULL COMMENT '配置类型:1=负卖开关,2=调整审批阈值,3=预占有效期(小时),4=超收容差,5=调拨在途可售默认',
  scope_type  TINYINT         NOT NULL DEFAULT 1 COMMENT '适用范围:1=全局,2=货主,3=店铺,4=仓库,5=仓库x货主,6=调整类型',
  scope_ref   VARCHAR(64)     NOT NULL DEFAULT '0' COMMENT '范围引用(scope对应ID;仓库x货主=branch:owner拼接)',
  config_json JSON            NOT NULL COMMENT '参数集: 如负卖{"allow_negative":1}/阈值{"num_threshold":10,"value_threshold":5000}/有效期{"hours":72}',
  status      TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=停用',
  create_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted  TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_stock_config (config_type, scope_type, scope_ref)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='库存参数配置(D04.02,P0,辅助)';

-- 36. 成本口径配置（D04.07 · P1，辅助配置表，owner_id 免填）
CREATE TABLE inv_cost_config (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  tax_caliber      TINYINT         NOT NULL DEFAULT 1 COMMENT '成本口径:1=含税,2=不含税(与金蝶一致,待确认)',
  branch_cost_mode TINYINT         NOT NULL DEFAULT 1 COMMENT '核算粒度:1=分仓均价(三元行独立),2=全局均价',
  return_cost_mode TINYINT         NOT NULL DEFAULT 1 COMMENT '退货成本取值:1=原单成本快照,2=当前均价',
  freight_in_cost  TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '运费/关税计入成本:0=否,1=是(价外费用分摊)',
  effective_time   DATETIME(3)     NOT NULL COMMENT '生效时间(口径变更只未来生效,历史不重算)',
  status           TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=历史',
  operator         VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '配置人',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  KEY idx_inv_cost_config_status (status, effective_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='成本口径配置(D04.07,P1,辅助)';

-- 45. 临期规则（D04.09 · P1，配置表 owner_id 免填）
CREATE TABLE inv_expire_rule (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id    BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  rule_name    VARCHAR(128)    NOT NULL COMMENT '规则名称',
  scope_type   TINYINT         NOT NULL DEFAULT 1 COMMENT '适用范围:1=全局,2=货主,3=品牌,4=分类,5=物料(数字大优先覆盖)',
  scope_ref    JSON            NULL DEFAULT NULL COMMENT '范围引用ID集',
  threshold_type TINYINT       NOT NULL DEFAULT 1 COMMENT '阈值类型:1=到期前天数,2=剩余效期比例%',
  yellow_days  INT             NOT NULL DEFAULT 180 COMMENT '黄色预警阈值(天数或比例值)',
  orange_days  INT             NOT NULL DEFAULT 90 COMMENT '橙色预警阈值',
  red_days     INT             NOT NULL DEFAULT 30 COMMENT '红色阈值(触发自动冻结)',
  auto_freeze  TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '红色自动冻结:0=否,1=是(联动D04.08可售重算)',
  notify_route JSON            NULL DEFAULT NULL COMMENT '通知路由(品牌方门户/采购/运营,D01.07)',
  status       TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=停用',
  create_time  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version      INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted   TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  KEY idx_inv_expire_rule_scope (scope_type, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='临期规则(D04.09,P1,配置表)';

-- 47. 库存预警规则（D04.10 · P1，配置表 owner_id 免填）
CREATE TABLE inv_alert_rule (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  rule_name         VARCHAR(128)    NOT NULL COMMENT '规则名称',
  rule_type         TINYINT         NOT NULL COMMENT '规则类型:1=低库存(补货点),2=断货风险(预测断货日≤N天),3=滞销(M天无动销),4=仓间不均衡(可售天数差≥N),5=超储(可售天数≥上限)',
  scope_type        TINYINT         NOT NULL DEFAULT 1 COMMENT '适用范围:1=全局,2=货主,3=品牌,4=分类,5=物料(数字大优先覆盖)',
  scope_ref         JSON            NULL DEFAULT NULL COMMENT '范围引用ID集',
  params            JSON            NOT NULL COMMENT '参数集: 安全库存/N天/系数/提前期/阈值,如{"safe_store":100,"lead_days":7,"stockout_days":3}',
  sales_caliber     TINYINT         NOT NULL DEFAULT 3 COMMENT '日均销量口径:1=近7天,2=近14天,3=近30天',
  promo_exclude     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '大促日剔除:0=否(乘系数),1=是(大促日历配置)',
  promo_coefficient DECIMAL(9,4)    NOT NULL DEFAULT 1.0000 COMMENT '大促系数(预测期在大促窗口内时乘算)',
  scan_freq         TINYINT         NOT NULL DEFAULT 1 COMMENT '扫描频率:1=日批,2=实时,3=日批+实时',
  notify_route      JSON            NULL DEFAULT NULL COMMENT '通知路由: 买断→采购/运营企微;代销→品牌方门户+运营跟催',
  status            TINYINT         NOT NULL DEFAULT 1 COMMENT '启用状态:1=启用,2=停用',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted        TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  KEY idx_inv_alert_rule_type (rule_type, scope_type, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='库存预警规则(D04.10,P1,配置表)';

-- 29. 盘点计划（D04.06 · P1，配置表 owner_id 免填）← 商派 taoguaninventory 计划语义
CREATE TABLE inv_stocktake_plan (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id     BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  plan_name     VARCHAR(128)    NOT NULL COMMENT '计划名称',
  cycle_type    TINYINT         NOT NULL COMMENT '周期:1=月盘,2=周盘,3=日盘,4=动碰抽盘',
  scope_type    TINYINT         NOT NULL DEFAULT 1 COMMENT '范围类型:1=仓x货主全量,2=分类,3=物料清单,4=动碰规则',
  scope_ref     JSON            NOT NULL COMMENT '范围引用: 仓/货主/分类/物料ID集;动碰={"days":7,"last_overdue_days":90}',
  mode          TINYINT         NOT NULL DEFAULT 1 COMMENT '盘点模式:1=明盘,2=盲盘(SN物料强制盲盘)',
  executor      TINYINT         NOT NULL DEFAULT 1 COMMENT '执行方:1=WMS,2=人工',
  next_run_time DATETIME(3)     NULL DEFAULT NULL COMMENT '下次执行时间(调度)',
  status        TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=停用',
  create_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version       INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted    TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  KEY idx_inv_stocktake_plan_next (status, next_run_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='盘点计划(D04.06,P1,配置表)';

-- 37. 平台同步策略（D04.08 · P0，配置表 owner_id 免填）← 商派 inventorydepth_regulation 改造
CREATE TABLE inv_sync_strategy (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  shop_id          BIGINT UNSIGNED NOT NULL COMMENT '店铺 LFK→oms_gateway.gw_shop',
  scope_type       TINYINT         NOT NULL DEFAULT 1 COMMENT '覆盖范围:1=全店,2=分类,3=品牌,4=指定物料(下探覆盖,数字大优先)',
  scope_ref        JSON            NULL DEFAULT NULL COMMENT '范围引用(分类/品牌/物料ID数组;全店=NULL)',
  strategy_type    VARCHAR(16)     NOT NULL DEFAULT 'shared_safe' COMMENT '策略类型:independent=分平台独立,shared_ratio=共享池比例分配,shared_safe=全量共享-安全库存预留',
  safe_num         INT             NOT NULL DEFAULT 0 COMMENT '安全库存量(shared_safe用)',
  safe_ratio       DECIMAL(9,4)    NOT NULL DEFAULT 0.0000 COMMENT '安全库存比例%(与safe_num二选一)',
  alloc_ratio      DECIMAL(9,4)    NOT NULL DEFAULT 0.0000 COMMENT '分配比例%(shared_ratio用;多平台合计可>100%=软超卖)',
  oversell_mode    TINYINT         NOT NULL DEFAULT 1 COMMENT '超卖模式:1=硬分配(合计≤100%),2=软超卖(可>100%)(shared_ratio用)',
  quota_num        INT             NOT NULL DEFAULT 0 COMMENT '独立配额默认量(independent用,明细见inv_independent_quota)',
  water_level      INT             NOT NULL DEFAULT 0 COMMENT '水位线(低于则高频回写+动态安全库存上浮)',
  water_level_type TINYINT         NOT NULL DEFAULT 1 COMMENT '水位类型:1=绝对值,2=销量天数(日均x天数)',
  min_sellable     INT             NOT NULL DEFAULT 0 COMMENT '可售下限修正',
  max_sellable     INT             NOT NULL DEFAULT 0 COMMENT '可售上限修正(0=不限)',
  writeback_mode   TINYINT         NOT NULL DEFAULT 1 COMMENT '回写模式:1=实时,2=准实时批量,3=定时',
  threshold_rate   DECIMAL(9,4)    NOT NULL DEFAULT 0.0000 COMMENT '回写变化阈值率(防抖:差值≥max(1,上次x rate)才回写;跨0线强制回写)',
  status           TINYINT         NOT NULL DEFAULT 1 COMMENT '启用状态:1=启用,2=停用',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted       TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  KEY idx_inv_sync_strategy_shop (shop_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='平台同步策略(D04.08,P0,配置表;范围唯一性应用层校验)';

-- ============================================================================
-- 二、物料档案族（D04.01）
-- ============================================================================

-- 1. 基础物料档案（D04.01 · P0）← 商派 basic_material 改造: +owner_id必填不可改 +金蝶编码 +same_code_group
CREATE TABLE inv_material (
  id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id             BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id              BIGINT UNSIGNED NOT NULL COMMENT '货主(必填,建档后不可改;改货主走货权转移D04.05) LFK→oms_org.org_owner',
  material_bn           VARCHAR(64)     NOT NULL COMMENT '货号(全局唯一;建议:品牌缩写+品类+规格)',
  material_bn_crc32     INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '货号CRC32整型辅助索引(大表查询加速,商派惯例)',
  material_name         VARCHAR(128)    NOT NULL COMMENT '物料名称',
  material_spu          VARCHAR(128)    NOT NULL DEFAULT '' COMMENT 'SPU/款号',
  type                  TINYINT         NOT NULL DEFAULT 3 COMMENT '物料属性:1=成品,2=半成品,3=普通,4=礼盒,5=虚拟(虚拟不开记账行)',
  cat_id                BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '分类ID LFK→inv_material_cat',
  cat_path              VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '分类路径冗余(/1/5/23/,子树查询用)',
  brand_id              BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '品牌 LFK→inv_brand',
  color                 VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '颜色',
  size                  VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '尺码',
  same_code_group       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '同货号跨货主关联组(报表合并/借调/串货识别用)',
  kingdee_material_code VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '金蝶物料编码(买断货主建议必填,D08.06推送用)',
  serial_number         TINYINT(1)      NOT NULL DEFAULT 0 COMMENT 'SN码管理开关:0=关,1=开(开启后出入库必录SN→D04.09)',
  storage_life_flag     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '效期管理开关:0=关,1=开(开启后批次/效期必填→D04.09)',
  is_ctrl_store         TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '库存管控开关:0=不记账(低值易耗),1=记账',
  omnichannel           TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '全渠道开关:0=否,1=是',
  is_o2o_sales          TINYINT(1)      NOT NULL DEFAULT 0 COMMENT 'O2O门店可售开关:0=否,1=是(D03.11取用)',
  tax_rate              DECIMAL(9,4)    NOT NULL DEFAULT 0.0000 COMMENT '开票税率(百分数值,如13.0000)',
  tax_name              VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '开票名称',
  tax_code              VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '开票分类编码',
  cos_id                BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '组织架构节点 LFK→oms_org.org_node(数据权限维度)',
  org_id                BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '运营组织 LFK→oms_org.org_node',
  status                TINYINT         NOT NULL DEFAULT 1 COMMENT '档案状态:1=启用,2=停用',
  source                VARCHAR(16)     NOT NULL DEFAULT 'local' COMMENT '数据来源:local=手工,api=自动,import=导入,migration=迁移',
  remark                VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '备注',
  create_time           DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time           DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version               INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted            TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_material_bn (material_bn),
  KEY idx_inv_material_owner (owner_id),
  KEY idx_inv_material_cat (cat_id),
  KEY idx_inv_material_crc32 (material_bn_crc32),
  KEY idx_inv_material_group (same_code_group)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='基础物料档案(D04.01,P0)';

-- 4. 销售物料档案（D04.01 · P0）← 商派 sales_material 改造: +tenant_id +owner_id冗余回填
CREATE TABLE inv_sales_material (
  id                      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id               BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id                BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(绑定后自基础物料冗余回填;未绑定=0) LFK→oms_org.org_owner',
  shop_id                 BIGINT UNSIGNED NOT NULL COMMENT '店铺 LFK→oms_gateway.gw_shop',
  sales_material_bn       VARCHAR(128)    NOT NULL COMMENT '平台商品编码(sku级,店铺内唯一;api来源=平台原始编码,故超32位基线)',
  sales_material_bn_crc32 INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '编码CRC32整型辅助索引',
  sales_material_name     VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '平台商品标题(自动建档取平台原文,可人工修正)',
  spec_text               VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '平台规格文本(自动建档原文)',
  sales_material_type     TINYINT         NOT NULL DEFAULT 1 COMMENT '物料类型:1=普通,2=组合,3=赠品,4=多选一,5=礼盒,6=福袋',
  bind_status             TINYINT         NOT NULL DEFAULT 0 COMMENT '绑定状态:0=未绑定,1=已绑定(SRS-D04.01 §4.2生命周期)',
  class_id                BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '客户分类(审单/拆单策略维度)',
  tax_rate                DECIMAL(9,4)    NOT NULL DEFAULT 0.0000 COMMENT '开票税率',
  tax_name                VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '开票名称',
  tax_code                VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '开票分类编码',
  org_id                  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '运营组织 LFK→oms_org.org_node',
  visibled                TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '销售状态:0=下架,1=上架',
  status                  TINYINT         NOT NULL DEFAULT 1 COMMENT '档案状态:1=正常,2=已停用(有未完结订单不可停用,应用层校验)',
  source                  VARCHAR(16)     NOT NULL DEFAULT 'local' COMMENT '数据来源:local=手工,api=自动建档,import=导入,migration=迁移',
  create_time             DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time             DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version                 INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted              TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_sales_material_shop_bn (shop_id, sales_material_bn),
  KEY idx_inv_sales_material_bind (bind_status, shop_id),
  KEY idx_inv_sales_material_crc32 (sales_material_bn_crc32),
  KEY idx_inv_sales_material_owner (owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='销售物料档案(D04.01,P0)';

-- 5. BOM版本头（D04.01 · P0）凯淳新增(商派无版本化)
CREATE TABLE inv_bom_version (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(冗余自销售物料)',
  sm_id          BIGINT UNSIGNED NOT NULL COMMENT '销售物料 LFK→inv_sales_material',
  version_no     INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT 'BOM版本号(变更+1)',
  status         TINYINT         NOT NULL DEFAULT 1 COMMENT '版本状态:1=草稿,2=生效,3=历史(同sm_id仅一个生效版)',
  effective_time DATETIME(3)     NULL DEFAULT NULL COMMENT '生效时间',
  operator       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '操作人',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version        INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_bom_version (sm_id, version_no),
  KEY idx_inv_bom_version_status (sm_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='BOM版本头(D04.01,P0)';

-- 6. BOM绑定明细（D04.01 · P0）← 商派 sales_basic_material 改造: +版本化 +owner_id
CREATE TABLE inv_bom_item (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NOT NULL COMMENT '货主(冗余自基础物料;同销售物料全部明细同货主,应用层校验)',
  bom_version_id BIGINT UNSIGNED NOT NULL COMMENT 'BOM版本 LFK→inv_bom_version',
  sm_id          BIGINT UNSIGNED NOT NULL COMMENT '销售物料(冗余,查询加速)',
  bm_id          BIGINT UNSIGNED NOT NULL COMMENT '基础物料 LFK→inv_material',
  bind_num       INT             NOT NULL DEFAULT 1 COMMENT '基础物料数量≥1(SRS §6.3 number;命名对齐DB-00数量规范)',
  rate           DECIMAL(9,4)    NOT NULL DEFAULT 0.0000 COMMENT '价格贡献占比%(同销售物料下合计=100;与fixed_price二选一,D08分摊用)',
  fixed_price    DECIMAL(18,4)   NOT NULL DEFAULT 0.0000 COMMENT '固定价(与rate二选一)',
  is_virtual     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '虚拟物料标记(冗余自inv_material.type=5,展开加速)',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_bom_item_ver_bm (bom_version_id, bm_id),
  KEY idx_inv_bom_item_sm (sm_id),
  KEY idx_inv_bom_item_bm (bm_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='BOM绑定明细(D04.01,P0)';

-- 7. 条码档案（D04.01 · P0）← 商派 codebase 改造: +全局唯一强约束
CREATE TABLE inv_barcode (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id    BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id     BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(冗余自基础物料,查询过滤用)',
  barcode      VARCHAR(64)     NOT NULL COMMENT '条码值(全局唯一,跨货主跨店铺冲突拒绝)',
  bm_id        BIGINT UNSIGNED NOT NULL COMMENT '归属基础物料 LFK→inv_material',
  barcode_type TINYINT         NOT NULL DEFAULT 1 COMMENT '条码类型:1=厂商码,2=店铺码,3=WMS码,9=其他',
  shop_id      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '关联店铺(店铺码时填) LFK→oms_gateway.gw_shop',
  status       TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=停用',
  create_time  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version      INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted   TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_barcode (barcode),
  KEY idx_inv_barcode_bm (bm_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='条码档案(D04.01,P0)';

-- 8. 福袋组合方案（D04.01 · P1）← 商派 fukubukuro_combine
CREATE TABLE inv_fukubukuro_plan (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id     BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主',
  plan_bn       VARCHAR(32)     NOT NULL COMMENT '方案编码(唯一)',
  plan_name     VARCHAR(128)    NOT NULL COMMENT '方案名称',
  sm_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '关联销售物料(type=6福袋) LFK→inv_sales_material',
  pick_num      INT             NOT NULL DEFAULT 1 COMMENT '选中物料个数(商派selected_number)',
  include_num   INT             NOT NULL DEFAULT 1 COMMENT '包含件数',
  lowest_price  DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '成员最低价',
  highest_price DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '成员最高价',
  status        TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=停用',
  create_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version       INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted    TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_fukubukuro_plan_bn (plan_bn),
  KEY idx_inv_fukubukuro_plan_sm (sm_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='福袋组合方案(D04.01,P1)';

-- 9. 福袋方案明细（D04.01 · P1）← 商派 fukubukuro_combine_items
CREATE TABLE inv_fukubukuro_item (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id    BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id     BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(冗余自基础物料)',
  plan_id      BIGINT UNSIGNED NOT NULL COMMENT '福袋方案 LFK→inv_fukubukuro_plan',
  bm_id        BIGINT UNSIGNED NOT NULL COMMENT '基础物料 LFK→inv_material',
  retail_price DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '零售价',
  pick_ratio   TINYINT         NOT NULL DEFAULT -1 COMMENT '选中比例%(-1=随机)',
  create_time  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted   TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_fukubukuro_item (plan_id, bm_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='福袋方案明细(D04.01,P1)';

-- 10. 多选一候选（D04.01 · P1）← 商派 pickone_rules 改造(bm_id串列拆行)
CREATE TABLE inv_pickone_candidate (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id   BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id    BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(冗余自基础物料)',
  sm_id       BIGINT UNSIGNED NOT NULL COMMENT '多选一销售物料 LFK→inv_sales_material',
  bm_id       BIGINT UNSIGNED NOT NULL COMMENT '候选基础物料 LFK→inv_material',
  sort_no     INT             NOT NULL DEFAULT 0 COMMENT '候选排序(指定顺序策略用)',
  select_type TINYINT         NOT NULL DEFAULT 1 COMMENT '择一策略:1=库存深度优先,2=成本优先,3=指定顺序(审单时择一,D03)',
  create_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted  TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_pickone_candidate (sm_id, bm_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='多选一候选(D04.01,P1)';

-- ============================================================================
-- 三、记账核心（D04.02）
-- ============================================================================

-- 11. 三元记账行（D04.02 · P0）★核心 ← 商派 branch_product+basic_material_stock 改造: +owner_id三元键
--     可用库存 available = store - freeze - defective - (is_locked?safe_store:0) 为派生计算值不落库
CREATE TABLE inv_stock_ledger (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL COMMENT '货主(三元键③,冗余自物料档案,写入时应用层校验一致) LFK→oms_org.org_owner',
  branch_id       BIGINT UNSIGNED NOT NULL COMMENT '仓库(三元键①) LFK→oms_fulfill.ful_branch',
  bm_id           BIGINT UNSIGNED NOT NULL COMMENT '基础物料(三元键②) LFK→inv_material',
  store           INT             NOT NULL DEFAULT 0 COMMENT '实际库存(含锁定与次品;负卖行允许<0并告警)',
  freeze          INT             NOT NULL DEFAULT 0 COMMENT '锁定库存(已预占未出库;恒≤store,对账校验项)',
  arrive_store    INT             NOT NULL DEFAULT 0 COMMENT '在途库存(采购/调拨未入库)',
  defective       INT             NOT NULL DEFAULT 0 COMMENT '次品库存(不良品实物,不参与可售)',
  safe_store      INT             NOT NULL DEFAULT 0 COMMENT '安全库存',
  is_locked       TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '锁定安全库存开关:0=否,1=是(参与可用公式)',
  unit_cost       DECIMAL(18,4)   NOT NULL DEFAULT 0.0000 COMMENT '单位成本(移动加权均价,D04.07回写,本域唯一写入方为成本模块)',
  inventory_cost  DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '库存成本(货值=均价x实际数量,D04.07回写)',
  status          TINYINT         NOT NULL DEFAULT 1 COMMENT '行状态:1=活跃,2=停用(五口径全零且无在途无锁定可停用;新记账动作自动重开)',
  last_store_time DATETIME(3)     NULL DEFAULT NULL COMMENT '实际库存最后变动时间(动碰盘点圈定用)',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间(记账行开立时间)',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(DB降级路径并发控制)',
  is_deleted      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_stock_ledger_triple (branch_id, bm_id, owner_id),
  KEY idx_inv_stock_ledger_owner (owner_id, bm_id),
  KEY idx_inv_stock_ledger_bm (bm_id),
  KEY idx_inv_stock_ledger_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='三元记账行(D04.02,P0,全系统唯一库存账本)';

-- 12. 库存变动流水（D04.02 · P0）★核心·按月分表基线 ← 商派 stock_change_log 改造
--     只增不改不删: 无is_deleted/version/update_time
CREATE TABLE inv_stock_change_log (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NOT NULL COMMENT '货主(三元键③)',
  branch_id      BIGINT UNSIGNED NOT NULL COMMENT '仓库(三元键①)',
  bm_id          BIGINT UNSIGNED NOT NULL COMMENT '基础物料(三元键②)',
  change_field   VARCHAR(16)     NOT NULL COMMENT '变动口径:store=实际,freeze=锁定,arrive=在途,defective=次品',
  change_num     INT             NOT NULL COMMENT '变动数量(±整数)',
  before_balance INT             NOT NULL DEFAULT 0 COMMENT '变动前该口径余额快照',
  after_balance  INT             NOT NULL DEFAULT 0 COMMENT '变动后该口径余额快照(审计与重算基础)',
  bill_type      VARCHAR(32)     NOT NULL COMMENT '业务单据类型(inv_io_bill_type.type_code/调整单/预占等,幂等键成分)',
  bill_bn        VARCHAR(32)     NOT NULL COMMENT '业务单据号(幂等键成分)',
  bill_item_id   BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '业务单据行ID(无行级=0,幂等键成分)',
  action         VARCHAR(32)     NOT NULL COMMENT '动作:reserve=预占,release=释放,deduct=扣减,inbound=入库,outbound=出库,adjust=调整,transfer=调拨,stocktake=盘点,compensate=补偿回滚',
  operator       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '操作人(系统动作=系统账号名)',
  source         VARCHAR(32)     NOT NULL DEFAULT 'oms' COMMENT '来源系统:manual=人工,oms=OMS自动,wms=WMS回传,migration=迁移',
  idempotent_key VARCHAR(128)    NOT NULL COMMENT '幂等键=(bill_type,bill_item_id,action)拼接,重复投递只记账一次',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '变动时间(毫秒)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_stock_change_log_key (idempotent_key),
  KEY idx_inv_stock_change_log_triple (branch_id, bm_id, owner_id, create_time),
  KEY idx_inv_stock_change_log_bill (bill_type, bill_bn),
  KEY idx_inv_stock_change_log_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='库存变动流水(D04.02,P0,按月分表_YYYYMM,只增不改)';

-- 14. 日终库存快照（D04.02 · P0）
CREATE TABLE inv_stock_snapshot (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NOT NULL COMMENT '货主',
  snapshot_date  DATE            NOT NULL COMMENT '快照日期',
  branch_id      BIGINT UNSIGNED NOT NULL COMMENT '仓库',
  bm_id          BIGINT UNSIGNED NOT NULL COMMENT '基础物料',
  store          INT             NOT NULL DEFAULT 0 COMMENT '实际库存',
  freeze         INT             NOT NULL DEFAULT 0 COMMENT '锁定库存',
  arrive_store   INT             NOT NULL DEFAULT 0 COMMENT '在途库存',
  defective      INT             NOT NULL DEFAULT 0 COMMENT '次品库存',
  safe_store     INT             NOT NULL DEFAULT 0 COMMENT '安全库存',
  available_num  INT             NOT NULL DEFAULT 0 COMMENT '可用库存(派生公式固化值,报表口径统一)',
  unit_cost      DECIMAL(18,4)   NOT NULL DEFAULT 0.0000 COMMENT '单位成本(量价双快照,D04.07)',
  inventory_cost DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '库存货值',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_stock_snapshot (snapshot_date, branch_id, bm_id, owner_id),
  KEY idx_inv_stock_snapshot_owner (owner_id, snapshot_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='日终库存快照(D04.02,P0,流水重算基线S0)';

-- 13. 人工调整单（D04.02 · P0，单据类无软删）
CREATE TABLE inv_stock_adjust (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL COMMENT '货主',
  adjust_bn       VARCHAR(32)     NOT NULL COMMENT '调整单号(唯一,生效即记账的流水单据号)',
  branch_id       BIGINT UNSIGNED NOT NULL COMMENT '仓库',
  bm_id           BIGINT UNSIGNED NOT NULL COMMENT '基础物料',
  adjust_num      INT             NOT NULL COMMENT '调整数量(±整数)',
  adjust_type     TINYINT         NOT NULL COMMENT '调整类型:1=盘盈,2=盘亏,3=报损,4=退货修正,5=系统纠错,9=其他(字典可扩展)',
  reason          VARCHAR(512)    NOT NULL COMMENT '调整原因(必填)',
  attachment      JSON            NULL DEFAULT NULL COMMENT '附件(OSS URL数组)',
  approval_status TINYINT         NOT NULL DEFAULT 0 COMMENT '审批状态:0=免审,1=待审(OA),2=通过,3=驳回(超阈值推泛微OA,D10.05)',
  oa_flow_id      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '泛微OA流程ID',
  status          TINYINT         NOT NULL DEFAULT 1 COMMENT '单据状态:1=草稿,2=生效,3=关闭',
  operator        VARCHAR(64)     NOT NULL COMMENT '发起人',
  confirm_time    DATETIME(3)     NULL DEFAULT NULL COMMENT '生效(记账)时间',
  source          VARCHAR(16)     NOT NULL DEFAULT 'local' COMMENT '来源:local=手工,import=导入,migration=迁移',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_stock_adjust_bn (adjust_bn),
  KEY idx_inv_stock_adjust_status (status, approval_status),
  KEY idx_inv_stock_adjust_triple (branch_id, bm_id, owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='人工调整单(D04.02,P0,单据类无软删)';

-- 15. 对账差异清单（D04.02 · P0，辅助）
CREATE TABLE inv_stock_recon_diff (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id     BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id      BIGINT UNSIGNED NOT NULL COMMENT '货主',
  recon_date    DATE            NOT NULL COMMENT '对账日期',
  recon_type    TINYINT         NOT NULL COMMENT '对账类型:1=Redis vs DB,2=WMS vs OMS,3=批次账 vs 数量账',
  branch_id     BIGINT UNSIGNED NOT NULL COMMENT '仓库',
  bm_id         BIGINT UNSIGNED NOT NULL COMMENT '基础物料',
  change_field  VARCHAR(16)     NOT NULL DEFAULT 'store' COMMENT '差异口径:store/freeze/arrive/defective',
  oms_num       INT             NOT NULL DEFAULT 0 COMMENT 'OMS侧数值',
  peer_num      INT             NOT NULL DEFAULT 0 COMMENT '对端数值(Redis/WMS/批次账)',
  diff_num      INT             NOT NULL DEFAULT 0 COMMENT '差异量=peer-oms',
  status        TINYINT         NOT NULL DEFAULT 1 COMMENT '处理状态:1=待处理,2=已自动修复,3=已人工处理,4=误报忽略',
  handle_remark VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '处理说明(人工处理走调整单/盘点闭环时记单号)',
  handler       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '处理人',
  handle_time   DATETIME(3)     NULL DEFAULT NULL COMMENT '处理时间',
  create_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  KEY idx_inv_stock_recon_diff_date (recon_date, recon_type, status),
  KEY idx_inv_stock_recon_diff_triple (branch_id, bm_id, owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='对账差异清单(D04.02,P0,辅助)';

-- ============================================================================
-- 四、预占（D04.03）
-- ============================================================================

-- 17. 预占台账（D04.03 · P0）★核心 ← 商派 basic_material_stock_freeze 改造: +货主/借调/状态机/幂等键
CREATE TABLE inv_freeze_log (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NOT NULL COMMENT '预占归属货主(借调时=借入方;记账freeze发生在借出方行)',
  obj_type       TINYINT         NOT NULL COMMENT '对象类型:1=订单,2=售后换货,3=调拨,4=人工,5=借调',
  obj_bn         VARCHAR(32)     NOT NULL COMMENT '对象单号(订单号/售后单号/调拨单号/人工预占单号)',
  obj_item_id    BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '对象行ID(幂等键成分)',
  branch_id      BIGINT UNSIGNED NOT NULL COMMENT '仓库(三元键①)',
  bm_id          BIGINT UNSIGNED NOT NULL COMMENT '基础物料(三元键②)',
  shop_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '关联店铺(订单预占必填) LFK→oms_gateway.gw_shop',
  num            INT             NOT NULL COMMENT '预占数量(>0)',
  settled_num    INT             NOT NULL DEFAULT 0 COMMENT '已核销数量(累计转扣减,≤num)',
  released_num   INT             NOT NULL DEFAULT 0 COMMENT '已释放数量(累计,settled+released≤num)',
  status         TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=已生效,2=部分核销,3=已核销,4=已释放(SRS-D04.03 §4.1状态机)',
  expire_time    DATETIME(3)     NULL DEFAULT NULL COMMENT '过期时间(默认72h;货主>店铺>全局配置;预售=预计发货日+缓冲;到期自动释放+告警)',
  lend_owner_id  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '借出货主(借调预占必填,=0非借调) LFK→oms_org.org_owner',
  lend_ledger_id BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '借调台账ID LFK→inv_lend_ledger',
  source         VARCHAR(32)     NOT NULL DEFAULT 'audit' COMMENT '调用来源:audit=审单,manual=人工,compensate=系统补偿,wms=WMS回传',
  is_compensated TINYINT(1)      NOT NULL DEFAULT 0 COMMENT 'Saga补偿标记:0=正常,1=已补偿回滚(预占失败反向释放留痕)',
  idempotent_key VARCHAR(128)    NOT NULL COMMENT '幂等键=(obj_type,obj_item_id,action)拼接,唯一索引兜底防重复预占',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version        INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(核销与释放互斥)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_freeze_log_key (idempotent_key),
  KEY idx_inv_freeze_log_obj (obj_type, obj_bn),
  KEY idx_inv_freeze_log_triple (branch_id, bm_id, owner_id, status),
  KEY idx_inv_freeze_log_expire (status, expire_time),
  KEY idx_inv_freeze_log_shop (shop_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='预占台账(D04.03,P0,单据类无软删)';

-- 18. 人工预占单（D04.03 · P0，单据类无软删）
CREATE TABLE inv_manual_freeze (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL COMMENT '货主',
  freeze_bn       VARCHAR(32)     NOT NULL COMMENT '人工预占单号(唯一)',
  branch_id       BIGINT UNSIGNED NOT NULL COMMENT '仓库',
  bm_id           BIGINT UNSIGNED NOT NULL COMMENT '基础物料',
  num             INT             NOT NULL COMMENT '预占数量(>0)',
  consumed_num    INT             NOT NULL DEFAULT 0 COMMENT '已消耗数量(转扣减累计)',
  start_time      DATETIME(3)     NOT NULL COMMENT '锁定期间起',
  end_time        DATETIME(3)     NOT NULL COMMENT '锁定期间止(期间外自动释放)',
  reason          VARCHAR(512)    NOT NULL COMMENT '原因(必填)',
  attachment      JSON            NULL DEFAULT NULL COMMENT '附件',
  approval_status TINYINT         NOT NULL DEFAULT 0 COMMENT 'OA审批状态:0=免审,1=待审,2=通过,3=驳回',
  status          TINYINT         NOT NULL DEFAULT 1 COMMENT '单据状态:1=草稿,2=生效,3=部分消耗,4=已释放,5=已过期',
  operator        VARCHAR(64)     NOT NULL COMMENT '发起人',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_manual_freeze_bn (freeze_bn),
  KEY idx_inv_manual_freeze_status (status, end_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='人工预占单(D04.03,P0,单据类无软删)';

-- ============================================================================
-- 五、出入库单据族（D04.04）
-- ============================================================================

-- 19. 出入库单据头（D04.04 · P0）★核心 ← 商派 iostock(43列平铺) 改造: 头/行拆分+货主+红冲
CREATE TABLE inv_io_bill (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NOT NULL COMMENT '货主(行级可覆盖,退仓混货主场景)',
  bill_bn          VARCHAR(32)     NOT NULL COMMENT '单据号(全局唯一:{类型码}{YYYYMMDD}{6位序列};红冲单=原单号+R后缀)',
  bill_type        VARCHAR(32)     NOT NULL COMMENT '单据类型码 LFK→inv_io_bill_type.type_code',
  direction        TINYINT         NOT NULL COMMENT '出入方向:1=入库,2=出库(类型派生冗余,查询加速)',
  branch_id        BIGINT UNSIGNED NOT NULL COMMENT '仓库 LFK→oms_fulfill.ful_branch',
  source_bill_type VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '源单类型:pur_order=采购单,delivery=发货单,aftersale=售后单,transfer=调拨单,stocktake=盘点单,adjust=调整单,空=人工',
  source_bill_bn   VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '源单号(四级追溯链:源单→单据→流水→余额)',
  wms_bill_no      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT 'WMS侧单号(下发回填,回传匹配键)',
  shop_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '关联店铺(销售出库填)',
  status           TINYINT         NOT NULL DEFAULT 1 COMMENT '单据状态:1=草稿,2=已下发WMS,3=部分回传,4=全部回传,5=已确认,6=已红冲,7=已关闭(SRS-D04.04 §4.1状态机)',
  red_flush_of     VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '红冲引用原单号(红冲单据必填;非空即红冲单;已确认单据不可改删仅可红冲)',
  settle_status    TINYINT         NOT NULL DEFAULT 0 COMMENT '结算状态:0=无需结算,1=未结算,2=部分结算,3=已结算,4=结算锁定(禁止红冲)',
  settle_bn        VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '结算单号 LFK→oms_finance.fin_settlement',
  settle_num       INT             NOT NULL DEFAULT 0 COMMENT '结算数量',
  settle_money     DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '结算金额',
  approval_status  TINYINT         NOT NULL DEFAULT 0 COMMENT '审批状态:0=免审,1=待审(OA),2=通过,3=驳回(需审批类型必填)',
  operator         VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '经手人',
  confirm_time     DATETIME(3)     NULL DEFAULT NULL COMMENT '确认记账时间',
  memo             VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '备注',
  attachment       JSON            NULL DEFAULT NULL COMMENT '附件',
  source           VARCHAR(16)     NOT NULL DEFAULT 'local' COMMENT '来源:local=人工,api=源单自动,wms=WMS上报,import=导入,migration=期初迁移',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_io_bill_bn (bill_bn),
  KEY idx_inv_io_bill_source (source_bill_type, source_bill_bn),
  KEY idx_inv_io_bill_branch (branch_id, status, create_time),
  KEY idx_inv_io_bill_type_time (bill_type, create_time),
  KEY idx_inv_io_bill_wms (wms_bill_no),
  KEY idx_inv_io_bill_settle (settle_status, settle_bn)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='出入库单据头(D04.04,P0,单据类无软删)';

-- 20. 出入库单据行（D04.04 · P0）★核心
CREATE TABLE inv_io_bill_item (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NOT NULL COMMENT '行级货主(默认继承单据头)',
  bill_id        BIGINT UNSIGNED NOT NULL COMMENT '单据头 LFK→inv_io_bill',
  bill_bn        VARCHAR(32)     NOT NULL COMMENT '单据号(冗余,分表/追溯加速)',
  bm_id          BIGINT UNSIGNED NOT NULL COMMENT '基础物料 LFK→inv_material',
  issued_num     INT             NOT NULL DEFAULT 0 COMMENT '下发数量(>0)',
  returned_num   INT             NOT NULL DEFAULT 0 COMMENT '累计回传数量(分批回传累积,≤下发;超收按容差配置拒绝或允许+告警)',
  confirmed_num  INT             NOT NULL DEFAULT 0 COMMENT '确认记账数量(=最终记账量)',
  defect_num     INT             NOT NULL DEFAULT 0 COMMENT '不良数量(退货/采购入库适用,入次品口径)',
  batch_no       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '批次号(效期物料必填→D04.09)',
  expire_date    DATE            NULL DEFAULT NULL COMMENT '效期(到期日)',
  serial_nos     JSON            NULL DEFAULT NULL COMMENT '序列号清单(SN物料必填,JSON数组→D04.09)',
  unit_cost      DECIMAL(18,4)   NOT NULL DEFAULT 0.0000 COMMENT '成本快照单价(出库=当时均价;入库=采购价或暂估价,D04.07口径)',
  amount         DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '金额=unit_cost x confirmed_num',
  source_item_id BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '源单行ID(追溯链)',
  remark         VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '行备注',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version        INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(回传累计高频更新)',
  PRIMARY KEY (id),
  KEY idx_inv_io_bill_item_bill (bill_id),
  KEY idx_inv_io_bill_item_bm (bm_id, owner_id),
  KEY idx_inv_io_bill_item_source (source_item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='出入库单据行(D04.04,P0,单据类无软删)';

-- 22. WMS回传登记（D04.04 · P0，辅助流水类）回传幂等防重
CREATE TABLE inv_io_callback_log (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id     BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(冗余自单据头)',
  bill_id       BIGINT UNSIGNED NOT NULL COMMENT '单据头 LFK→inv_io_bill',
  bill_bn       VARCHAR(32)     NOT NULL COMMENT '单据号(冗余)',
  wms_batch_no  VARCHAR(64)     NOT NULL COMMENT 'WMS回传批次号(幂等成分:同单据同批次只处理一次)',
  callback_type TINYINT         NOT NULL DEFAULT 1 COMMENT '回传类型:1=入库回传,2=出库回传,3=质检结果',
  content       JSON            NULL DEFAULT NULL COMMENT '回传明细摘要(行数/数量/批次/SN汇总;大报文截断存OSS引用)',
  status        TINYINT         NOT NULL DEFAULT 1 COMMENT '处理状态:1=成功,2=失败待重试,3=丢弃(重复)',
  error_msg     VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '失败原因',
  create_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '回传接收时间',
  update_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_io_callback_log (bill_id, wms_batch_no),
  KEY idx_inv_io_callback_log_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='WMS回传登记(D04.04,P0,辅助)';

-- ============================================================================
-- 六、调拨与借调（D04.05）
-- ============================================================================

-- 23. 调拨单头（D04.05 · P0，单据类无软删）← 商派 taoguanallocate_appropriation 改造
CREATE TABLE inv_transfer_order (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NOT NULL COMMENT '货主(单一,全单一致,不允许一单多货主)',
  transfer_bn      VARCHAR(32)     NOT NULL COMMENT '调拨单号(唯一)',
  out_branch_id    BIGINT UNSIGNED NOT NULL COMMENT '出库仓(不等于入库仓;可跨WMS) LFK→oms_fulfill.ful_branch',
  in_branch_id     BIGINT UNSIGNED NOT NULL COMMENT '入库仓 LFK→oms_fulfill.ful_branch',
  reason           TINYINT         NOT NULL DEFAULT 1 COMMENT '调拨原因:1=平衡,2=归集,3=退仓前置,4=借调移位,9=其他',
  status           TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=草稿,2=已确认,3=出库中,4=在途,5=入库中,6=已完结,7=差异完结,8=已关闭(SRS §4.1,不可跳态)',
  arrival_sellable TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '在途可售开关:0=否(默认),1=是(D04.08联动)',
  out_bill_bn      VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '配对调拨出库单据号 LFK→inv_io_bill',
  in_bill_bn       VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '配对调拨入库单据号 LFK→inv_io_bill',
  diff_num         INT             NOT NULL DEFAULT 0 COMMENT '差异量(入库<出库,差异完结必填;差额走出库仓盘亏闭环)',
  diff_type        TINYINT         NOT NULL DEFAULT 0 COMMENT '差异类型:0=无,1=运输损耗,2=短少,3=溢余,9=其他',
  diff_duty        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '差异责任方',
  approval_status  TINYINT         NOT NULL DEFAULT 0 COMMENT 'OA审批:0=免审,1=待审,2=通过,3=驳回',
  operator         VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '发起人',
  confirm_time     DATETIME(3)     NULL DEFAULT NULL COMMENT '确认时间',
  finish_time      DATETIME(3)     NULL DEFAULT NULL COMMENT '完结时间',
  memo             VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '备注',
  source           VARCHAR(16)     NOT NULL DEFAULT 'local' COMMENT '来源:local=手工,suggest=建议转单(D04.10),migration=迁移',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_transfer_order_bn (transfer_bn),
  KEY idx_inv_transfer_order_status (status),
  KEY idx_inv_transfer_order_out (out_branch_id, in_branch_id),
  KEY idx_inv_transfer_order_owner (owner_id, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='调拨单头(D04.05,P0,单据类无软删)';

-- 24. 调拨单行（D04.05 · P0，单据类无软删）
CREATE TABLE inv_transfer_item (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id    BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id     BIGINT UNSIGNED NOT NULL COMMENT '货主(继承单头,冗余存储便于行级过滤)',
  transfer_id  BIGINT UNSIGNED NOT NULL COMMENT '调拨单 LFK→inv_transfer_order',
  bm_id        BIGINT UNSIGNED NOT NULL COMMENT '基础物料 LFK→inv_material',
  issued_num   INT             NOT NULL DEFAULT 0 COMMENT '调出数量(>0)',
  returned_num INT             NOT NULL DEFAULT 0 COMMENT '入库回传数量(累计)',
  batch_no     VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '批次号(效期物料带批次,FIFO建议→D04.09)',
  expire_date  DATE            NULL DEFAULT NULL COMMENT '效期',
  remark       VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '备注',
  create_time  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version      INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  KEY idx_inv_transfer_item_tid (transfer_id),
  KEY idx_inv_transfer_item_bm (bm_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='调拨单行(D04.05,P0,单据类无软删)';

-- 25. 借调规则（D04.05 · P1，配置表 owner_id 免填=0）凯淳原创(商派无借调模型)
CREATE TABLE inv_lend_rule (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(配置表免填=0)',
  rule_name         VARCHAR(128)    NOT NULL COMMENT '规则名称',
  lend_owner_id     BIGINT UNSIGNED NOT NULL COMMENT '借出货主(不等于借入货主) LFK→oms_org.org_owner',
  borrow_owner_id   BIGINT UNSIGNED NOT NULL COMMENT '借入货主 LFK→oms_org.org_owner',
  scope_type        TINYINT         NOT NULL DEFAULT 1 COMMENT '物料范围类型:1=指定清单,2=分类,3=品牌(命中优先级1>2>3,同级按创建时间)',
  scope_ref         JSON            NOT NULL COMMENT '范围引用(物料ID/分类ID/品牌ID数组)',
  quota_total       INT             NOT NULL DEFAULT 0 COMMENT '总额度(0=不限;与月量至少一项>0)',
  quota_monthly     INT             NOT NULL DEFAULT 0 COMMENT '月额度(0=不限)',
  reserve_floor     INT             NOT NULL DEFAULT 0 COMMENT '借出方保留底线(可借调量=min(额度余量,借出available-底线))',
  period_start      DATE            NOT NULL COMMENT '期间起',
  period_end        DATE            NOT NULL COMMENT '期间止(到期自动关闭台账)',
  settle_price_type TINYINT         NOT NULL DEFAULT 2 COMMENT '结算方式:1=内部购销价,2=成本价,3=免费额度(D08取数)',
  move_type         TINYINT         NOT NULL DEFAULT 1 COMMENT '借调性质:1=货不动,2=货动(借调+调拨组合,货权不随物理移动转移)',
  status            TINYINT         NOT NULL DEFAULT 1 COMMENT '生效状态:1=待审批,2=生效,3=暂停,4=已到期,5=已关闭',
  approval_status   TINYINT         NOT NULL DEFAULT 1 COMMENT 'OA审批:1=待审,2=通过,3=驳回(涉及货主间利益,新建/变更必审)',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted        TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  KEY idx_inv_lend_rule_pair (lend_owner_id, borrow_owner_id, status),
  KEY idx_inv_lend_rule_period (period_start, period_end)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='借调规则(D04.05,P1,凯淳原创)';

-- 26. 借调台账（D04.05 · P1）owner_id=借入货主视角;记账行货主恒定(借出方),本表为业务归属第二本账
CREATE TABLE inv_lend_ledger (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL COMMENT '借入货主(=borrow_owner_id)',
  rule_id         BIGINT UNSIGNED NOT NULL COMMENT '借调规则 LFK→inv_lend_rule',
  lend_owner_id   BIGINT UNSIGNED NOT NULL COMMENT '借出货主 LFK→oms_org.org_owner',
  borrow_owner_id BIGINT UNSIGNED NOT NULL COMMENT '借入货主(冗余,与owner_id一致)',
  branch_id       BIGINT UNSIGNED NOT NULL COMMENT '仓库(借出方记账行所在仓)',
  bm_id           BIGINT UNSIGNED NOT NULL COMMENT '基础物料',
  lend_num        INT             NOT NULL DEFAULT 0 COMMENT '借调量(额度占用)',
  committed_num   INT             NOT NULL DEFAULT 0 COMMENT '预占承诺量(reserve累计;释放则减;额度余量=额度-已承诺)',
  consumed_num    INT             NOT NULL DEFAULT 0 COMMENT '已消耗量(=出库转扣减累计,消耗确认时点,结算基数)',
  released_num    INT             NOT NULL DEFAULT 0 COMMENT '已释放量',
  status          TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=耗尽,3=到期,4=关闭(到期调度自动关闭并释放未消耗预占)',
  order_refs      JSON            NULL DEFAULT NULL COMMENT '关联订单集(order_id数组,追溯用)',
  settle_month    CHAR(7)         NOT NULL DEFAULT '' COMMENT '结算月份(YYYY-MM)',
  settle_status   TINYINT         NOT NULL DEFAULT 0 COMMENT '结算状态:0=未结算,1=已结算(D08回写;月度按台账聚合内部交易明细)',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(额度承诺并发控制)',
  is_deleted      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  KEY idx_inv_lend_ledger_rule (rule_id, status),
  KEY idx_inv_lend_ledger_triple (branch_id, bm_id, lend_owner_id),
  KEY idx_inv_lend_ledger_settle (settle_month, settle_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='借调台账(D04.05,P1,凯淳原创)';

-- 27. 货权转移单（D04.05 · P1，单据类无软删）购销式货权转移
CREATE TABLE inv_ownership_transfer (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL COMMENT '货主(=源货主from_owner_id冗余)',
  transfer_bn       VARCHAR(32)     NOT NULL COMMENT '转移单号(唯一)',
  from_owner_id     BIGINT UNSIGNED NOT NULL COMMENT '源货主 LFK→oms_org.org_owner',
  to_owner_id       BIGINT UNSIGNED NOT NULL COMMENT '目标货主(不等于源货主) LFK→oms_org.org_owner',
  branch_id         BIGINT UNSIGNED NOT NULL COMMENT '仓库',
  status            TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=草稿,2=待审批,3=待双方确认,4=执行中,5=已完成,6=已驳回,7=已关闭',
  approval_status   TINYINT         NOT NULL DEFAULT 1 COMMENT 'OA审批:1=待审,2=通过,3=驳回(强制审批)',
  from_confirm_time DATETIME(3)     NULL DEFAULT NULL COMMENT '源货主确认时间(品牌方门户动作)',
  to_confirm_time   DATETIME(3)     NULL DEFAULT NULL COMMENT '目标货主确认时间',
  out_bill_bn       VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '配对销售出库单据号(货主=源) LFK→inv_io_bill',
  in_bill_bn        VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '配对采购入库单据号(货主=目标) LFK→inv_io_bill',
  operator          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '发起人',
  memo              VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '备注',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_ownership_transfer_bn (transfer_bn),
  KEY idx_inv_ownership_transfer_owner (from_owner_id, to_owner_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='货权转移单(D04.05,P1,单据类无软删)';

-- 28. 货权转移单行（D04.05 · P1，单据类无软删）
CREATE TABLE inv_ownership_transfer_item (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NOT NULL COMMENT '货主(=源货主)',
  transfer_id    BIGINT UNSIGNED NOT NULL COMMENT '转移单 LFK→inv_ownership_transfer',
  from_bm_id     BIGINT UNSIGNED NOT NULL COMMENT '源基础物料(源货主档案) LFK→inv_material',
  to_bm_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '目标基础物料(新建/已有档案,same_code_group关联;执行后回填)',
  num            INT             NOT NULL COMMENT '转移数量(>0)',
  transfer_price DECIMAL(18,4)   NOT NULL DEFAULT 0.0000 COMMENT '转移价(购销价,重新计价依据D04.07)',
  amount         DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '金额=transfer_price x num',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version        INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  KEY idx_inv_ownership_transfer_item_tid (transfer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='货权转移单行(D04.05,P1,单据类无软删)';

-- ============================================================================
-- 七、盘点（D04.06）
-- ============================================================================

-- 30. 盘点任务（D04.06 · P1完整版/简版随M1，单据类无软删）← 商派 taoguaninventory 改造
CREATE TABLE inv_stocktake_task (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL COMMENT '货主(单仓单货主,多货主盘点拆多任务)',
  task_bn         VARCHAR(32)     NOT NULL COMMENT '盘点任务号(唯一,下发WMS)',
  plan_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '来源计划 LFK→inv_stocktake_plan(0=手动/对账触发)',
  branch_id       BIGINT UNSIGNED NOT NULL COMMENT '仓库',
  scope_desc      VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '范围描述',
  mode            TINYINT         NOT NULL DEFAULT 1 COMMENT '盘点模式:1=明盘,2=盲盘(SN物料强制盲盘;盲盘下发报文不含账面数)',
  executor        TINYINT         NOT NULL DEFAULT 1 COMMENT '执行方:1=WMS,2=人工',
  trigger_type    TINYINT         NOT NULL DEFAULT 1 COMMENT '触发来源:1=手动,2=计划调度,3=对账差异(D04.02联动生成待核查任务)',
  status          TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=待下发,2=执行中,3=已回传,4=差异核查,5=审批中,6=已完结,7=已关闭(无差异直接完结)',
  snapshot_time   DATETIME(3)     NOT NULL COMMENT '基线快照时间(窗口起点,账面基线不可变)',
  window_end      DATETIME(3)     NULL DEFAULT NULL COMMENT '回传截止(窗口终点;差异=实盘-(基线+窗口内已确认入库-窗口内已确认出库))',
  wms_task_no     VARCHAR(64)     NOT NULL DEFAULT '' COMMENT 'WMS侧盘点任务号',
  diff_rows       INT             NOT NULL DEFAULT 0 COMMENT '差异行数(报告用)',
  diff_rate       DECIMAL(9,4)    NOT NULL DEFAULT 0.0000 COMMENT '差异率%',
  diff_amount     DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '差异金额(按均价估算)',
  approval_status TINYINT         NOT NULL DEFAULT 0 COMMENT 'OA审批:0=免审,1=待审,2=通过,3=驳回(差异超阈值走OA)',
  report_summary  JSON            NULL DEFAULT NULL COMMENT '盘点报告汇总(原因分布/审批链,归档只读)',
  operator        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '发起人',
  finish_time     DATETIME(3)     NULL DEFAULT NULL COMMENT '完结时间',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_stocktake_task_bn (task_bn),
  KEY idx_inv_stocktake_task_status (status, branch_id),
  KEY idx_inv_stocktake_task_owner (owner_id, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='盘点任务(D04.06,P1,单据类无软删)';

-- 31. 盘点明细行（D04.06 · P1，单据类无软删）
CREATE TABLE inv_stocktake_item (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL COMMENT '货主(冗余存储,串货识别跨货主查询用)',
  task_id           BIGINT UNSIGNED NOT NULL COMMENT '盘点任务 LFK→inv_stocktake_task',
  bm_id             BIGINT UNSIGNED NOT NULL COMMENT '基础物料',
  batch_no          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '批次号(效期物料按批次行)',
  serial_no         VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '序列号(SN物料按SN行)',
  location_code     VARCHAR(64)     NOT NULL DEFAULT '' COMMENT 'WMS库位(局部复盘用)',
  book_num          INT             NOT NULL DEFAULT 0 COMMENT '账面数(基线+窗口修正后)',
  window_adjust_num INT             NOT NULL DEFAULT 0 COMMENT '窗口修正量(窗口内已确认出入库净影响,留痕可解释)',
  actual_num        INT             NOT NULL DEFAULT 0 COMMENT '实盘数(初盘)',
  recount_flag      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '复盘标记:0=无,1=已复盘(复盘覆盖初盘,留痕)',
  recount_num       INT             NOT NULL DEFAULT 0 COMMENT '复盘结果',
  diff_num          INT             NOT NULL DEFAULT 0 COMMENT '差异量=实盘(复盘优先)-账面',
  diff_reason       TINYINT         NOT NULL DEFAULT 0 COMMENT '差异原因:0=无差异,1=货损,2=货差,3=单据未闭环,4=回传丢失,5=串货(货主间),9=其他(每差异行必填)',
  duty              VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '责任方',
  suspect_mixup     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '疑似串货标记:0=否,1=是(同same_code_group一盈一亏数量相近;不直接盘盈盘亏)',
  adjust_bill_bn    VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '生成的盘盈入库/盘亏出库单据号 LFK→inv_io_bill',
  remark            VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '备注',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  KEY idx_inv_stocktake_item_task (task_id, bm_id),
  KEY idx_inv_stocktake_item_diff (task_id, diff_reason)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='盘点明细行(D04.06,P1,单据类无软删)';

-- ============================================================================
-- 八、成本核算（D04.07）
-- ============================================================================

-- 32. 成本流水（D04.07 · P1，流水类只增不改）← 商派 tgstockcost 语义改造: +三元键分账+均价前后快照
CREATE TABLE inv_cost_change_log (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL COMMENT '货主(三元键③;买断=完整核算,代销=代管口径)',
  branch_id         BIGINT UNSIGNED NOT NULL COMMENT '仓库(三元键①)',
  bm_id             BIGINT UNSIGNED NOT NULL COMMENT '基础物料(三元键②)',
  change_type       TINYINT         NOT NULL COMMENT '流水类型:1=入库计价,2=出库结转,3=退货冲回,4=暂估回冲,5=调整,6=期初,7=代管入,8=代管出',
  bill_type         VARCHAR(32)     NOT NULL COMMENT '来源单据类型(幂等键成分)',
  bill_bn           VARCHAR(32)     NOT NULL COMMENT '来源单据号',
  bill_item_id      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '来源单据行ID',
  num               INT             NOT NULL DEFAULT 0 COMMENT '数量(方向±)',
  price             DECIMAL(18,4)   NOT NULL DEFAULT 0.0000 COMMENT '单价(本笔计价/结转价)',
  amount            DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '金额(±)',
  before_unit_cost  DECIMAL(18,4)   NOT NULL DEFAULT 0.0000 COMMENT '变动前移动加权均价快照',
  after_unit_cost   DECIMAL(18,4)   NOT NULL DEFAULT 0.0000 COMMENT '变动后均价快照(可回放)',
  before_value      DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '变动前货值',
  after_value       DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '变动后货值',
  estimate_flag     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '暂估标记:0=正式价,1=暂估价(暂估批次追踪)',
  cost_estimated    TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '退货无原单人工确认标记:0=原单快照,1=均价替代+人工确认',
  recalc_seq        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '重算序号(串行重算顺序,回放依据)',
  operator          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '经手人',
  source            VARCHAR(32)     NOT NULL DEFAULT 'oms' COMMENT '来源:oms=自动,manual=人工调整,migration=期初迁移',
  idempotent_key    VARCHAR(128)    NOT NULL COMMENT '幂等键=(bill_type,bill_item_id,change_type)拼接',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_cost_change_log_key (idempotent_key),
  KEY idx_inv_cost_change_log_triple (branch_id, bm_id, owner_id, create_time),
  KEY idx_inv_cost_change_log_bill (bill_type, bill_bn),
  KEY idx_inv_cost_change_log_seq (branch_id, bm_id, owner_id, recalc_seq)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='成本流水(D04.07,P1,只增不改)';

-- 33. 暂估批次（D04.07 · P1）
CREATE TABLE inv_estimate_batch (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL COMMENT '货主',
  branch_id       BIGINT UNSIGNED NOT NULL COMMENT '仓库',
  bm_id           BIGINT UNSIGNED NOT NULL COMMENT '基础物料',
  in_bill_bn      VARCHAR(32)     NOT NULL COMMENT '暂估入库单据号 LFK→inv_io_bill',
  in_bill_item_id BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '入库单据行ID',
  estimate_price  DECIMAL(18,4)   NOT NULL DEFAULT 0.0000 COMMENT '暂估价(货到票未到)',
  actual_price    DECIMAL(18,4)   NOT NULL DEFAULT 0.0000 COMMENT '实际价(发票到回填)',
  in_num          INT             NOT NULL DEFAULT 0 COMMENT '暂估入库数量',
  remain_num      INT             NOT NULL DEFAULT 0 COMMENT '在库未结转量(价差调均价基数)',
  settled_num     INT             NOT NULL DEFAULT 0 COMMENT '已出库量(价差生成出库成本差异明细基数)',
  status          TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=暂估中,2=部分转正,3=已转正',
  invoice_ref     VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '关联发票号 LFK→oms_finance发票台账(D08.05)',
  diff_amount     DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '价差总额=(暂估价-实际价)x数量(回冲时计算固化)',
  reverse_time    DATETIME(3)     NULL DEFAULT NULL COMMENT '回冲时间',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_estimate_batch_bill (in_bill_bn, in_bill_item_id),
  KEY idx_inv_estimate_batch_status (status, owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='暂估批次(D04.07,P1)';

-- 34. 代销代管货值账（D04.07 · P1）凯淳新增(商派无货主概念)
CREATE TABLE inv_consignment_value (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id    BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id     BIGINT UNSIGNED NOT NULL COMMENT '代销货主',
  branch_id    BIGINT UNSIGNED NOT NULL COMMENT '仓库',
  bm_id        BIGINT UNSIGNED NOT NULL COMMENT '基础物料',
  settle_price DECIMAL(18,4)   NOT NULL DEFAULT 0.0000 COMMENT '结算价(品牌方供货价)',
  num          INT             NOT NULL DEFAULT 0 COMMENT '代管数量(入库+/出库-,流水复用inv_cost_change_log type=7/8)',
  value        DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '代管货值=settle_price x num(不入凯淳存货汇总)',
  create_time  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version      INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_consignment_value_triple (branch_id, bm_id, owner_id),
  KEY idx_inv_consignment_value_owner (owner_id, branch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='代销代管货值账(D04.07,P1)';

-- 35. 日终成本快照（D04.07 · P1）量价双快照
CREATE TABLE inv_cost_snapshot (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id           BIGINT UNSIGNED NOT NULL COMMENT '货主',
  snapshot_date      DATE            NOT NULL COMMENT '快照日期',
  branch_id          BIGINT UNSIGNED NOT NULL COMMENT '仓库',
  bm_id              BIGINT UNSIGNED NOT NULL COMMENT '基础物料',
  store_num          INT             NOT NULL DEFAULT 0 COMMENT '实际库存数量',
  unit_cost          DECIMAL(18,4)   NOT NULL DEFAULT 0.0000 COMMENT '当日均价',
  inventory_value    DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '存货货值(数量x均价=货值,日终对账)',
  estimate_value     DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '其中暂估货值(暂估批次未转正部分)',
  consignment_value  DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '代管货值(代销货主行)',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_cost_snapshot (snapshot_date, branch_id, bm_id, owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='日终成本快照(D04.07,P1)';

-- ============================================================================
-- 九、可售计算与平台同步（D04.08）
-- ============================================================================

-- 38. 可售快照（D04.08 · P0）
CREATE TABLE inv_sellable_snapshot (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(冗余自销售物料绑定货主)',
  shop_id         BIGINT UNSIGNED NOT NULL COMMENT '店铺 LFK→oms_gateway.gw_shop',
  sm_id           BIGINT UNSIGNED NOT NULL COMMENT '销售物料 LFK→inv_sales_material',
  platform_sku    VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '平台SKU编码(冗余=sales_material_bn,回写通道直用)',
  calc_sellable   INT             NOT NULL DEFAULT 0 COMMENT '计算可售值(策略链结果:基础可用→借调额度→BOM min套数→策略换算→上下限修正)',
  last_writeback  INT             NOT NULL DEFAULT 0 COMMENT '上次回写值(防抖比较基线)',
  branch_detail   JSON            NULL DEFAULT NULL COMMENT '多仓明细(各仓可用贡献)',
  bom_detail      JSON            NULL DEFAULT NULL COMMENT '组合装成员明细(min套数计算过程,可解释)',
  sync_status     TINYINT         NOT NULL DEFAULT 0 COMMENT '同步状态:0=未同步,1=已同步,2=同步失败,3=熔断暂停(available≤0回写0后防抖暂停,补货恢复)',
  sync_time       DATETIME(3)     NULL DEFAULT NULL COMMENT '最近回写时间',
  retry_count     INT             NOT NULL DEFAULT 0 COMMENT '重试次数(联动D02.05)',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_sellable_snapshot (shop_id, sm_id),
  KEY idx_inv_sellable_snapshot_sync (sync_status, sync_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='可售快照(D04.08,P0)';

-- 39. 平台回写日志（D04.08 · P0，按月分表基线，流水类只增不改）
CREATE TABLE inv_sync_log (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(冗余)',
  shop_id           BIGINT UNSIGNED NOT NULL COMMENT '店铺',
  sm_id             BIGINT UNSIGNED NOT NULL COMMENT '销售物料',
  platform_sku      VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '平台SKU编码',
  calc_sellable     INT             NOT NULL DEFAULT 0 COMMENT '计算值',
  writeback_num     INT             NOT NULL DEFAULT 0 COMMENT '实际回写值',
  trigger_type      TINYINT         NOT NULL DEFAULT 1 COMMENT '触发:1=事件驱动,2=水位触发,3=定时全量,4=手动,5=对账强制',
  sync_status       TINYINT         NOT NULL DEFAULT 1 COMMENT '结果:1=成功,2=失败(失败进D02.05重试队列,指数退避)',
  platform_response VARCHAR(1024)   NOT NULL DEFAULT '' COMMENT '平台响应(截断存储)',
  error_code        VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '失败错误码',
  retry_count       INT             NOT NULL DEFAULT 0 COMMENT '重试次数',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '回写时间',
  PRIMARY KEY (id),
  KEY idx_inv_sync_log_shop (shop_id, create_time),
  KEY idx_inv_sync_log_sm (sm_id, create_time),
  KEY idx_inv_sync_log_status (sync_status, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='平台回写日志(D04.08,P0,按月分表_YYYYMM,只增不改)';

-- 40. 分平台独立配额（D04.08 · P1）independent策略配额账
CREATE TABLE inv_independent_quota (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id    BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id     BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主',
  shop_id      BIGINT UNSIGNED NOT NULL COMMENT '店铺 LFK→oms_gateway.gw_shop',
  sm_id        BIGINT UNSIGNED NOT NULL COMMENT '销售物料 LFK→inv_sales_material',
  quota_total  INT             NOT NULL DEFAULT 0 COMMENT '配额总量(划拨;专供/JIT/包货场景,配额独立不回收)',
  quota_sold   INT             NOT NULL DEFAULT 0 COMMENT '已售(订单占用累计)',
  quota_remain INT             NOT NULL DEFAULT 0 COMMENT '余量=quota_total-quota_sold',
  create_time  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version      INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(高频竞争)',
  is_deleted   TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_independent_quota (shop_id, sm_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='分平台独立配额(D04.08,P1)';

-- ============================================================================
-- 十、批次效期与序列号（D04.09）
-- ============================================================================

-- 41. 批次档案（D04.09 · P1）← 商派 basic_material_storage_life 改造: +货主
CREATE TABLE inv_batch (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL COMMENT '货主(跨货主隔离:同批次号不同货主=不同批次行)',
  bm_id           BIGINT UNSIGNED NOT NULL COMMENT '基础物料 LFK→inv_material',
  batch_no        VARCHAR(64)     NOT NULL COMMENT '批次号(WMS/厂商原文,物料x货主内唯一)',
  produce_date    DATE            NULL DEFAULT NULL COMMENT '生产日期(效期物料必填)',
  expire_date     DATE            NULL DEFAULT NULL COMMENT '到期日期(expire>produce,应用层校验)',
  in_date         DATE            NULL DEFAULT NULL COMMENT '入库日期',
  source_bill_bn  VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '来源入库单据号 LFK→inv_io_bill',
  shelf_life_days INT             NOT NULL DEFAULT 0 COMMENT '保质期天数(冗余=到期-生产,报表用)',
  status          TINYINT         NOT NULL DEFAULT 1 COMMENT '批次状态:1=正常,2=冻结(临期红),3=清空',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_batch (bm_id, owner_id, batch_no),
  KEY idx_inv_batch_expire (expire_date, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='批次档案(D04.09,P1)';

-- 42. 批次库存明细（D04.09 · P1）★四元行=三元键x批次
CREATE TABLE inv_batch_stock (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL COMMENT '货主(四元③)',
  branch_id         BIGINT UNSIGNED NOT NULL COMMENT '仓库(四元①)',
  bm_id             BIGINT UNSIGNED NOT NULL COMMENT '基础物料(四元②)',
  batch_id          BIGINT UNSIGNED NOT NULL COMMENT '批次 LFK→inv_batch(四元④)',
  batch_no          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '批次号(冗余,查询加速)',
  store             INT             NOT NULL DEFAULT 0 COMMENT '批次实际数量(Σ批次明细=数量账,日终三方对账)',
  locked            INT             NOT NULL DEFAULT 0 COMMENT '批次锁定量(临期红冻结,可售计算扣除项;无freeze口径,预占不到批次粒度)',
  defective         INT             NOT NULL DEFAULT 0 COMMENT '批次次品量',
  near_expire_level TINYINT         NOT NULL DEFAULT 0 COMMENT '临期级别:0=无,1=黄,2=橙,3=红(调度按inv_expire_rule刷新;红色自动冻结联动D04.08)',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(高频竞争)',
  is_deleted        TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_batch_stock_quad (branch_id, bm_id, owner_id, batch_id),
  KEY idx_inv_batch_stock_batch (batch_id),
  KEY idx_inv_batch_stock_level (near_expire_level, owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='批次库存明细四元行(D04.09,P1)';

-- 43. 出库批次指派记录（D04.09 · P1，辅助流水类）批次执行率考核
CREATE TABLE inv_batch_assign (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL COMMENT '货主',
  bill_item_id      BIGINT UNSIGNED NOT NULL COMMENT '出库单据行 LFK→inv_io_bill_item',
  branch_id         BIGINT UNSIGNED NOT NULL COMMENT '仓库',
  bm_id             BIGINT UNSIGNED NOT NULL COMMENT '基础物料',
  strategy          TINYINT         NOT NULL DEFAULT 1 COMMENT '指派策略:1=FEFO(先到期先出,默认),2=FIFO(先入先出),3=指定批次',
  suggest_batch_id  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '建议批次 LFK→inv_batch',
  suggest_num       INT             NOT NULL DEFAULT 0 COMMENT '建议数量',
  actual_batch_id   BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '实际批次(WMS回传,以回传为准登记)',
  actual_num        INT             NOT NULL DEFAULT 0 COMMENT '实际数量',
  is_match          TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '建议与实际一致:0=否(执行率差异→D11),1=是',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '时间',
  PRIMARY KEY (id),
  KEY idx_inv_batch_assign_item (bill_item_id),
  KEY idx_inv_batch_assign_time (branch_id, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='出库批次指派记录(D04.09,P1,辅助)';

-- 44. 序列号档案（D04.09 · P1）← 商派 product_serial/serial_history/serial_log 三表合并
CREATE TABLE inv_serial_no (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NOT NULL COMMENT '货主',
  sn_code          VARCHAR(64)     NOT NULL COMMENT 'SN码(物料x货主内唯一)',
  bm_id            BIGINT UNSIGNED NOT NULL COMMENT '基础物料 LFK→inv_material',
  branch_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '当前仓库(在库时有效)',
  status           TINYINT         NOT NULL DEFAULT 1 COMMENT 'SN状态:1=在库,2=已出库,3=售后中,4=已核销,5=换出,6=终止(不良/退款不退货)(SRS-D04.09 §4.1状态机)',
  order_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '绑定订单 LFK→oms_order.ord_order(已出库后必填;售后属单校验防调包)',
  delivery_item_id BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '绑定发货单行 LFK→oms_order.ord_delivery_item',
  aftersale_id     BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '售后单引用 LFK→oms_aftersale.aft_return_apply(售后中/核销后)',
  in_time          DATETIME(3)     NULL DEFAULT NULL COMMENT '最近入库时间',
  out_time         DATETIME(3)     NULL DEFAULT NULL COMMENT '最近出库时间',
  history          JSON            NOT NULL COMMENT '履历链(事件/单据/时间/仓时间线数组,只增不改;全生命周期追溯)',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(状态机变迁并发控制)',
  is_deleted       TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_serial_no (bm_id, owner_id, sn_code),
  KEY idx_inv_serial_no_order (order_id),
  KEY idx_inv_serial_no_status (status, branch_id),
  KEY idx_inv_serial_no_sn (sn_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='序列号档案(D04.09,P1)';

-- 46. 临期处置单（D04.09 · P1，单据类无软删）
CREATE TABLE inv_expire_disposal (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL COMMENT '货主',
  disposal_bn     VARCHAR(32)     NOT NULL COMMENT '处置单号(唯一)',
  batch_id        BIGINT UNSIGNED NOT NULL COMMENT '批次 LFK→inv_batch',
  branch_id       BIGINT UNSIGNED NOT NULL COMMENT '仓库',
  bm_id           BIGINT UNSIGNED NOT NULL COMMENT '基础物料',
  disposal_type   TINYINT         NOT NULL COMMENT '处置方式:1=促销出清(解冻+促销标记),2=退仓(还品牌方),3=报废',
  num             INT             NOT NULL COMMENT '处置数量',
  promo_start     DATETIME(3)     NULL DEFAULT NULL COMMENT '促销期间起(disposal_type=1,审单优先出该批次)',
  promo_end       DATETIME(3)     NULL DEFAULT NULL COMMENT '促销期间止',
  bill_bn         VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '关联出库单据号(退仓/报废) LFK→inv_io_bill',
  approval_status TINYINT         NOT NULL DEFAULT 0 COMMENT 'OA审批:0=免审,1=待审,2=通过,3=驳回(超阈值必审)',
  status          TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=草稿,2=执行中,3=已完成,4=已关闭',
  reason          VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '处置原因',
  operator        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '发起人',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_expire_disposal_bn (disposal_bn),
  KEY idx_inv_expire_disposal_batch (batch_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='临期处置单(D04.09,P1,单据类无软删)';

-- ============================================================================
-- 十一、预警与补货建议（D04.10）
-- ============================================================================

-- 48. 补货/处置建议单（D04.10 · P1）
CREATE TABLE inv_replenish_suggestion (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NOT NULL COMMENT '货主(三元键③;买断→采购建议,代销→门户协作不生成凯淳采购建议)',
  suggest_bn     VARCHAR(32)     NOT NULL COMMENT '建议单号(唯一)',
  suggest_type   TINYINT         NOT NULL COMMENT '建议类型:1=采购,2=调拨,3=借调,4=处置',
  rule_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '来源规则 LFK→inv_alert_rule',
  branch_id      BIGINT UNSIGNED NOT NULL COMMENT '仓库(三元键①;调拨建议=调入紧缺仓)',
  bm_id          BIGINT UNSIGNED NOT NULL COMMENT '基础物料(三元键②)',
  from_branch_id BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '调出仓(调拨/仓间不均衡建议用)',
  alert_level    TINYINT         NOT NULL DEFAULT 1 COMMENT '预警级别:1=黄(补货点触发),2=橙(断货≤7天),3=红(断货≤3天/已缺货);升级即时推送,降级不通知',
  suggest_num    INT             NOT NULL DEFAULT 0 COMMENT '建议量(目标库存-(可售+在途-已占用),含MOQ/箱规向上取整修正)',
  calc_snapshot  JSON            NOT NULL COMMENT '测算依据快照(日均销量/可售/在途/安全库存/提前期/ROP/断货日公式全输入,可解释性)',
  formula_version VARCHAR(16)    NOT NULL DEFAULT 'v1' COMMENT '公式版本(版本化可解释)',
  stockout_date  DATE            NULL DEFAULT NULL COMMENT '预测断货日=今天+(可售+在途-已占用)/预测日销',
  supplier_id    BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '建议供应商(默认供货关系) LFK→oms_purchase供应商档案',
  status         TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=待处理,2=已采纳,3=已忽略,4=已转单,5=已解除(条件恢复),6=已过期;同三元键同规则24h去重',
  target_bill_bn VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '转单后目标单据号(采购申请D06.01/调拨单D04.05草稿)',
  ignore_reason  TINYINT         NOT NULL DEFAULT 0 COMMENT '忽略原因:0=无,1=品牌方不补,2=清仓中,3=数据存疑,9=其他(统计供规则优化)',
  ignore_remark  VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '忽略备注',
  handler        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '处理人',
  handle_time    DATETIME(3)     NULL DEFAULT NULL COMMENT '处理时间',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version        INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_replenish_suggestion_bn (suggest_bn),
  KEY idx_inv_replenish_suggestion_dedup (rule_id, branch_id, bm_id, owner_id, status),
  KEY idx_inv_replenish_suggestion_status (status, alert_level),
  KEY idx_inv_replenish_suggestion_owner (owner_id, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='补货/处置建议单(D04.10,P1)';

-- ============================================================================
-- 十二、初始字典数据
-- ============================================================================

-- 出入库单据类型字典（SRS-D04.04 FR-01a 初始集 + 期初建账；类型可扩展=字典配置+口径模板,不改代码）
INSERT INTO inv_io_bill_type (tenant_id, type_code, type_name, direction, effect_template, need_wms, need_approval, settle_rel, status) VALUES
(1, 'purchase_in',        '采购入库',       1, '[{"field":"store","sign":1},{"field":"arrive","sign":-1}]',                 1, 0, 1, 1),
(1, 'return_in_good',     '退货入库-良品',  1, '[{"field":"store","sign":1}]',                                              1, 0, 0, 1),
(1, 'return_in_defect',   '退货入库-不良',  1, '[{"field":"defective","sign":1}]',                                          1, 0, 0, 1),
(1, 'transfer_in',        '调拨入库',       1, '[{"field":"store","sign":1},{"field":"arrive","sign":-1}]',                 1, 0, 0, 1),
(1, 'stocktake_in',       '盘盈入库',       1, '[{"field":"store","sign":1}]',                                              0, 0, 0, 1),
(1, 'headless_in',        '无头件入库',     1, '[{"field":"store","sign":1}]',                                              0, 1, 0, 1),
(1, 'reship_diff_in',     '差异退货入库',   1, '[{"field":"store","sign":1}]',                                              0, 1, 0, 1),
(1, 'exchange_in',        '换货入库',       1, '[{"field":"store","sign":1}]',                                              1, 0, 0, 1),
(1, 'opening_in',         '期初建账',       1, '[{"field":"store","sign":1},{"field":"freeze","sign":1},{"field":"arrive","sign":1},{"field":"defective","sign":1}]', 0, 1, 0, 1),
(1, 'sale_out',           '销售出库',       2, '[{"action":"settle"}]',                                                     1, 0, 2, 1),
(1, 'transfer_out',       '调拨出库',       2, '[{"field":"store","sign":-1},{"field":"arrive","sign":1}]',                 1, 0, 0, 1),
(1, 'stocktake_out',      '盘亏出库',       2, '[{"field":"store","sign":-1}]',                                             0, 0, 0, 1),
(1, 'damage_out',         '报损出库',       2, '[{"field":"store","sign":-1},{"field":"defective","sign":-1}]',             0, 1, 0, 1),
(1, 'return_warehouse_out','退仓出库',      2, '[{"field":"store","sign":-1},{"field":"defective","sign":-1}]',             1, 1, 1, 1),
(1, 'sample_out',         '样品领用出库',   2, '[{"field":"store","sign":-1}]',                                             0, 1, 0, 1);

-- 库存参数全局默认配置（SRS-D04.02 FR-02c 负卖默认禁止 / FR-04b 调整阈值 / D04.03 §5.4 预占有效期 / D04.04 §5.1 超收容差）
INSERT INTO inv_stock_config (tenant_id, config_type, scope_type, scope_ref, config_json, status) VALUES
(1, 1, 1, '0', '{"allow_negative": 0}',                          1),
(1, 2, 1, '0', '{"num_threshold": 10, "value_threshold": 5000}', 1),
(1, 3, 1, '0', '{"hours": 72}',                                  1),
(1, 4, 1, '0', '{"over_receive_tolerance": 0}',                  1),
(1, 5, 1, '0', '{"arrival_sellable_default": 0}',                1);

-- ============================================================================
-- V1.2 增补（2026-10-24，友商对标 7 项决策落地）
--   ① SRS-D04.08 V1.2 FR-01e/§6.4：活动锁定库存池 inv_activity_lock_pool
--      （第四种同步策略 activity_lock，G3 决策A；对标百秋活动锁定/商派 store_freeze_log）
--   ② SRS-D04.10 V1.2 FR-05：AI 销量预测 inv_sales_forecast
--      （G7 决策B首期就要；预测记录+服务调用日志并入本表字段）
--   注: 两表均为高频竞争/回测更新表，含 version；锁定池 remain=lock-sold 原子扣减
--   ③ 同步策略枚举扩展: inv_sync_strategy.strategy_type 补第四种 activity_lock（仅注释）
-- ============================================================================

-- V1.2-0. inv_sync_strategy 策略类型注释补充（SRS-D04.08 V1.2 §6.2，字符串码免DDL结构变更）
ALTER TABLE inv_sync_strategy
  MODIFY COLUMN strategy_type VARCHAR(16) NOT NULL DEFAULT 'shared_safe' COMMENT '策略类型:independent=分平台独立,shared_ratio=共享池比例分配,shared_safe=全量共享-安全库存预留,activity_lock=活动锁定(V1.2,与前三策略正交叠加:锁定量从共享池/独立配额先行扣减,本渠道池内量作为专属可售加回;明细见inv_activity_lock_pool)';

-- 49. 活动锁定库存池（D04.08 V1.2 §6.4 · P1）← 对标百秋活动锁定 + 商派 store_freeze_log 语义改造
CREATE TABLE inv_activity_lock_pool (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id     BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  activity_id   BIGINT UNSIGNED NOT NULL COMMENT '活动标识(大促/直播专场/平台活动;促销活动LFK→oms_order.ord_promotion_activity跨域,平台活动为平台侧ID)',
  activity_name VARCHAR(128)    NOT NULL COMMENT '活动名称',
  branch_id     BIGINT UNSIGNED NOT NULL COMMENT '仓库(三元键①) LFK→oms_fulfill.ful_branch',
  bm_id         BIGINT UNSIGNED NOT NULL COMMENT '基础物料(三元键②) LFK→inv_material',
  owner_id      BIGINT UNSIGNED NOT NULL COMMENT '货主(三元键③;锁定到仓xSKUx货主)',
  lock_num      INT             NOT NULL DEFAULT 0 COMMENT '锁定量(渠道级预留:圈定这批货只给该活动卖;区别于订单级预占inv_freeze_log)',
  sold_num      INT             NOT NULL DEFAULT 0 COMMENT '已售(池内订单预占双扣:池量-/available-)',
  remain_num    INT             NOT NULL DEFAULT 0 COMMENT '余量=lock_num-sold_num(原子扣减,不允许负)',
  channel_scope JSON            NULL COMMENT '绑定销售渠道(仅指定店铺/平台可售该池;JSON店铺/平台清单)',
  start_time    DATETIME(3)     NOT NULL COMMENT '生效开始(预热期占用:活动开始前锁定,不计入常规可售)',
  end_time      DATETIME(3)     NOT NULL COMMENT '生效结束(结束未售出量自动释放回共享池)',
  priority      INT             NOT NULL DEFAULT 0 COMMENT '多活动优先级(同SKU多活动锁定分配序;总量不得超available,超配预警)',
  release_rule  JSON            NULL COMMENT '释放规则:{pay_fail_return支付失败回池,end_auto_release结束自动释放,urgent_approval紧急释放走OA审批D10.05}',
  status        VARCHAR(16)     NOT NULL DEFAULT 'warmup' COMMENT '状态:warmup预热中/active生效中/ended已结束/released已释放',
  create_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version       INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(高频竞争:sold/remain原子扣减CAS)',
  is_deleted    TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_activity_lock_pool (activity_id, branch_id, bm_id, owner_id),
  KEY idx_inv_activity_lock_pool_key (branch_id, bm_id, owner_id, status),
  KEY idx_inv_activity_lock_pool_end (status, end_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='活动锁定库存池(第四种同步策略activity_lock:活动x仓xSKUx货主渠道级预留,与店铺基础策略正交叠加,可售计算链先行扣减,D04.08 V1.2,P1)';

-- 50. AI 销量预测记录（D04.10 V1.2 FR-05 · P1/M3；预测服务调用日志并入本表）
CREATE TABLE inv_sales_forecast (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL COMMENT '货主(三元键③)',
  branch_id       BIGINT UNSIGNED NOT NULL COMMENT '仓库(三元键①;分SKUx仓x货主粒度预测)',
  bm_id           BIGINT UNSIGNED NOT NULL COMMENT '基础物料(三元键②)',
  forecast_date   DATE            NOT NULL COMMENT '预测执行日期(预测基准日)',
  window_days     INT             NOT NULL DEFAULT 7 COMMENT '预测窗口天数(可配7/14/30,FR-05c)',
  forecast_json   JSON            NOT NULL COMMENT '预测值按日:[{date,num}]未来N天分日销量预测(补货建议/断货日测算输入)',
  ci_lower_json   JSON            NULL COMMENT '置信区间下界按日(与forecast_json同构)',
  ci_upper_json   JSON            NULL COMMENT '置信区间上界按日',
  model_version   VARCHAR(64)     NOT NULL COMMENT '模型版本(版本化/灰度上线/A-B对比,FR-05f)',
  adopt_strategy  VARCHAR(16)     NOT NULL DEFAULT 'blended' COMMENT '采用策略:pure_history纯历史(统计式日均)/pure_forecast纯预测/blended加权融合(冷启动新品用预测兜底,FR-05c可配置)',
  backtest_mape   DECIMAL(9,4)    NULL COMMENT '回测MAPE%(预测vs实际,持续迭代输入,FR-05d;回测完成后回填)',
  driver_factors  JSON            NULL COMMENT '主要驱动因子(可解释性:季节性/趋势/大促日历/价格变动/生命周期阶段等,FR-05e采购信任前提)',
  degrade_flag    TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '降级标记:0=ML预测,1=算法服务不可用自动降级统计式(FR-05e不阻塞补货建议)',
  call_status     VARCHAR(16)     NOT NULL DEFAULT 'success' COMMENT '预测服务调用结果(调用日志并入):success成功/fail失败/degraded降级/timeout超时(K-AIDE Agent通道或独立算法服务)',
  call_cost_ms    INT UNSIGNED    NULL COMMENT '调用耗时毫秒',
  call_error      VARCHAR(512)    NULL COMMENT '调用失败原因(fail/timeout必填)',
  call_time       DATETIME(3)     NULL COMMENT '调用时间',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间(MAPE回测回填)',
  version         INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_sales_forecast (branch_id, bm_id, owner_id, forecast_date, model_version),
  KEY idx_inv_sales_forecast_date (forecast_date, adopt_strategy),
  KEY idx_inv_sales_forecast_model (model_version, backtest_mape)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='AI销量预测记录(ML预测叠加统计式:分日预测值+置信区间+模型版本+采用策略+回测MAPE+驱动因子;服务调用日志并入,D04.10 V1.2,P1)';

-- ============================================================================
-- V1.5 增补（2026-10-24，价格管理修正增补 · SRS-D04.11 §6 五表）
--   ① inv_price_archive    价格档案（§6.1，货主x店铺x销售物料维度，四类价格台账）
--   ② inv_price_version    价格版本历史（§6.2，只增不改删=审计红线，按流水类惯例无软删/无乐观锁/无update_time）
--   ③ inv_price_adjust_plan 调价计划（§6.3，单据类惯例：状态机纠错禁用软删，含version乐观锁）
--   ④ inv_price_adjust_item 调价计划明细（§6.4，单据行同inv_io_bill_item惯例无软删）
--   ⑤ inv_price_sync_task  价格回传批次（§6.5，计划维度执行批次视图，SKU级明细在④与D02.04台账gw_writeback_task sync_type=price）
--   敏感字段取舍：inv域此前无_enc先例，但floor_price属DB-00 §3.2敏感字段（字段级权限d04.price.floor.view），
--   故按总册约定采用 VARBINARY 密文列（_enc后缀，D01.05信封加密）：archive.floor_price_enc /
--   version.old_price_enc+new_price_enc（仅price_type=floor时写入）/ item.floor_snapshot_enc；
--   底价值不作为检索条件（唯一键与查询均走shop/sm/type维度），故不加_hash盲索引（DB-00 §3.2按需原则）。
--   价格类型基线：DB-00 §6 单价 DECIMAL(18,4)（SRS §6.1 decimal(20,3) 归一至总册基线）。
-- ============================================================================

-- 51. 价格档案（D04.11 §6.1 · P1/M3；P0预留表结构降级兼容见SRS §8）
CREATE TABLE inv_price_archive (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL COMMENT '货主(档案维度①,全域口径) LFK→oms_org.org_owner',
  shop_id           BIGINT UNSIGNED NOT NULL COMMENT '店铺(档案维度②) LFK→oms_gateway.gw_shop',
  sm_id             BIGINT UNSIGNED NOT NULL COMMENT '销售物料(档案维度③,店铺xSKU语义) LFK→inv_sales_material',
  platform_sku_code VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '平台SKU编码(冗余,回传priceUpdate用;对齐sales_material_bn宽度)',
  tag_price         DECIMAL(18,4)   NOT NULL DEFAULT 0.0000 COMMENT '吊牌价(划线价,参考属性,无时间窗,≥0)',
  sale_price        DECIMAL(18,4)   NOT NULL DEFAULT 0.0000 COMMENT '日常销售价(当前生效值冗余,权威在inv_price_version版本表)',
  floor_price_enc   VARBINARY(255)  NULL DEFAULT NULL COMMENT '底价红线密文(D01.05信封加密,DB-00 §3.2;字段级权限d04.price.floor.view,无权限展示***;审单拦截/破线审批基准)',
  currency          VARCHAR(8)      NOT NULL DEFAULT 'CNY' COMMENT '币种(默认CNY;跨境多币种P2预留,本期只落字段不做汇率换算)',
  below_floor_flag  TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '当前售价破线标记:0=否,1=是(FR-02d软提示产物,治理清单用)',
  sync_status       VARCHAR(16)     NOT NULL DEFAULT 'not_required' COMMENT '平台同步状态:synced=已同步,sync_failed=同步失败终态(进对账清单),not_required=纯档案不回传',
  price_source      VARCHAR(16)     NOT NULL DEFAULT 'manual' COMMENT '价格来源:manual=人工,import=导入,plan=调价计划,algo=算法(P2预留,FR-10a)',
  status            TINYINT         NOT NULL DEFAULT 1 COMMENT '档案状态:1=启用,2=停用(随销售物料状态联动,IF-D04.11-09)',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted        TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_price_archive (shop_id, sm_id),
  KEY idx_inv_price_archive_owner (owner_id, status),
  KEY idx_inv_price_archive_sync (sync_status, update_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='价格档案(D04.11,P1;货主x店铺x销售物料维度四类价格台账,编辑即产生新版本不原地覆盖,floor密文+字段级权限)';

-- 52. 价格版本历史（D04.11 §6.2 · P1/M3）只增不改删（FR-03c审计红线）,按流水类惯例无update_time/version/is_deleted
CREATE TABLE inv_price_version (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NOT NULL COMMENT '货主(冗余自档案,行级权限过滤)',
  archive_id       BIGINT UNSIGNED NOT NULL COMMENT '归属档案 LFK→inv_price_archive',
  shop_id          BIGINT UNSIGNED NOT NULL COMMENT '店铺(冗余,§5.1生效价查找索引维度)',
  sm_id            BIGINT UNSIGNED NOT NULL COMMENT '销售物料(冗余,同上)',
  price_type       VARCHAR(16)     NOT NULL COMMENT '价格类型:tag=吊牌价,sale=日常销售价,activity=活动价(必带时间窗),floor=底价红线(可带时间窗)',
  version_no       INT UNSIGNED    NOT NULL COMMENT '版本号(archive x price_type内递增)',
  old_price        DECIMAL(18,4)   NULL DEFAULT NULL COMMENT '旧值(tag/sale/activity类型用;首建NULL)',
  new_price        DECIMAL(18,4)   NULL DEFAULT NULL COMMENT '新值(tag/sale/activity类型用,必填;floor类型写new_price_enc此列为NULL)',
  old_price_enc    VARBINARY(255)  NULL DEFAULT NULL COMMENT '旧值密文(仅price_type=floor,D01.05信封加密)',
  new_price_enc    VARBINARY(255)  NULL DEFAULT NULL COMMENT '新值密文(仅price_type=floor,必填;权限d04.price.floor.view)',
  start_time       DATETIME(3)     NOT NULL COMMENT '生效时间窗起',
  end_time         DATETIME(3)     NULL DEFAULT NULL COMMENT '生效时间窗止(NULL=长期;同类型窗口不重叠应用层校验FR-02b)',
  status           VARCHAR(16)     NOT NULL DEFAULT 'pending' COMMENT '版本状态:pending=未到生效,active=生效中,expired=已过期(活动价到期调度回落§5.6),cancelled=已取消',
  change_source    VARCHAR(16)     NOT NULL COMMENT '变更来源:manual=人工编辑,import=导入,plan=调价计划执行,schedule=活动价到期回落,algo=算法(P2预留)',
  ref_plan_bn      VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '关联调价计划号 LFK→inv_price_adjust_plan.plan_bn',
  ref_approval_bn  VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '关联OA审批单号(场景price_below_floor,D10.05)',
  ref_import_batch VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '关联导入批次号(D01.06导入中心)',
  sync_flag        TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '是否已回传平台:0=否,1=是(回传绑定版本快照§5.4,重试用原快照值)',
  sync_time        DATETIME(3)     NULL DEFAULT NULL COMMENT '回传成功时间',
  operator         VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '操作人(审计要素)',
  operated_at      DATETIME(3)     NOT NULL COMMENT '操作时间(审计要素)',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_price_version (archive_id, price_type, version_no),
  KEY idx_inv_price_version_eff (shop_id, sm_id, price_type, status, start_time),
  KEY idx_inv_price_version_expire (status, end_time),
  KEY idx_inv_price_version_plan (ref_plan_bn)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='价格版本历史(D04.11,P1;只增不改删审计红线,时点重建生效价供审单price_check,按月分区年增约300万条)';

-- 53. 调价计划（D04.11 §6.3 · P1/M3）单据类惯例：状态机纠错禁用软删（同inv_expire_disposal）
CREATE TABLE inv_price_adjust_plan (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id           BIGINT UNSIGNED NOT NULL COMMENT '货主',
  plan_bn            VARCHAR(32)     NOT NULL COMMENT '计划号(唯一,Redis发号器)',
  shop_id            BIGINT UNSIGNED NOT NULL COMMENT '目标店铺 LFK→oms_gateway.gw_shop',
  target_price_type  VARCHAR(16)     NOT NULL COMMENT '目标价格类型:sale=日常销售价,activity=活动价(必带时间窗)',
  effect_mode        VARCHAR(16)     NOT NULL DEFAULT 'immediate' COMMENT '生效方式:immediate=立即,scheduled=定时(effect_time必填,到点调度器转执行)',
  effect_time        DATETIME(3)     NULL DEFAULT NULL COMMENT '定时生效时间(effect_mode=scheduled必填)',
  expire_writeback   TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '到期是否自动回传回落:0=否(档案标记platform_price_drift_risk进对账清单),1=是(activity场景,SC-05)',
  source_type        VARCHAR(16)     NOT NULL DEFAULT 'manual' COMMENT '计划来源:manual=人工,import=Excel导入圈选,algorithm=算法(P2预留,FR-10b;算法建议价同样不破审批红线)',
  sku_count          INT             NOT NULL DEFAULT 0 COMMENT '总SKU数(创建校验产出)',
  below_floor_count  INT             NOT NULL DEFAULT 0 COMMENT '破线SKU数(破线判定产出§5.2,决定OA/内部复核分流)',
  review_mode        VARCHAR(16)     NOT NULL DEFAULT 'dual' COMMENT '复核方式:dual=内部双人复核(录入人不等于复核人),auto=免审(店铺级配置快照,免审也落复核记录FR-06d)',
  reviewer           VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '复核人(不等于创建人,系统校验)',
  reviewed_at        DATETIME(3)     NULL DEFAULT NULL COMMENT '复核时间',
  approval_bn        VARCHAR(32)     NOT NULL DEFAULT '' COMMENT 'OA审批单号(破线子计划必填,场景price_below_floor,D10.05)',
  oa_instance_id     VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '泛微OA流程实例ID',
  status             VARCHAR(32)     NOT NULL DEFAULT 'draft' COMMENT '状态机:draft=草稿,pending_review=待复核,pending_approval=待审批(OA在途冻结不可编辑),approved=已通过,pending_exec=待执行(定时中),executing=执行中,completed=已完成,partial_failed=部分失败,cancelled=已取消,approved_not_exec=通过未执行(FR-06e二次校验失败+告警)',
  reason             VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '调价理由(破线推OA时必填,审批要素)',
  result_summary     JSON            NULL DEFAULT NULL COMMENT '执行汇总:{succ成功数,fail失败数,skip跳过数,fail_rate失败率}(失败率超阈值5%触发D01.07企微告警)',
  creator            VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '创建人',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version            INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(状态机变迁并发控制)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_price_adjust_plan_bn (plan_bn),
  KEY idx_inv_price_adjust_plan_shop (shop_id, status),
  KEY idx_inv_price_adjust_plan_exec (status, effect_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='调价计划(D04.11,P1;批量+定时改价,破线拆OA子计划/不破线内部复核,单据类无软删)';

-- 54. 调价计划明细（D04.11 §6.4 · P1/M3）单据行惯例无软删（同inv_io_bill_item）
CREATE TABLE inv_price_adjust_item (
  id                     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id              BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id               BIGINT UNSIGNED NOT NULL COMMENT '货主(冗余自计划头)',
  plan_id                BIGINT UNSIGNED NOT NULL COMMENT '归属计划 LFK→inv_price_adjust_plan',
  plan_bn                VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '计划号(冗余,追溯加速)',
  sm_id                  BIGINT UNSIGNED NOT NULL COMMENT '销售物料 LFK→inv_sales_material(停用物料拒绝入计划FR-05b)',
  platform_sku_code      VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '平台SKU编码(冗余,回传用)',
  current_price_snapshot DECIMAL(18,4)   NOT NULL DEFAULT 0.0000 COMMENT '创建时点生效价快照(审批要素快照非实时值,D10.05 FR-02b)',
  floor_snapshot_enc     VARBINARY(255)  NULL DEFAULT NULL COMMENT '创建时点底价快照密文(D01.05信封加密;破线判定依据§5.2;无底价档案NULL=不判定破线记提示)',
  target_price           DECIMAL(18,4)   NOT NULL COMMENT '目标价(>0)',
  below_floor            TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '是否破线:0=否(内部复核子计划),1=是(强制OA子计划,FR-06a)',
  activity_start         DATETIME(3)     NULL DEFAULT NULL COMMENT '活动时间窗起(target=activity必填;target=sale可空)',
  activity_end           DATETIME(3)     NULL DEFAULT NULL COMMENT '活动时间窗止',
  exec_status            VARCHAR(16)     NOT NULL DEFAULT 'pending' COMMENT '执行状态:pending=待执行,succ=成功,retrying=重试中(D02.05退避),skip=跳过(业务失败如商品已下架不重试,进部分失败清单),fail_final=失败终态(档案标记sync_failed),terminated=未发出已终止(FR-05e)',
  version_id             BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '执行成功后生成的档案版本 LFK→inv_price_version(关联追溯)',
  sync_task_ref          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT 'D02.04回传台账引用(gw_writeback_task,sync_type=price,幂等键price/plan_id#sku/update)',
  fail_reason            VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '失败原因',
  retry_count            INT             NOT NULL DEFAULT 0 COMMENT '重试次数(D02.05指数退避累计)',
  create_time            DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time            DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version                INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(执行状态高频更新)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_price_adjust_item (plan_id, sm_id),
  KEY idx_inv_price_adjust_item_sm (sm_id),
  KEY idx_inv_price_adjust_item_status (exec_status, plan_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='调价计划明细(D04.11,P1;SKU级目标价+快照+破线标记+执行状态,单据行无软删)';

-- 55. 价格回传批次（D04.11 §6.5 · P1/M3）计划维度执行批次视图（一个计划一次执行=一个批次）
CREATE TABLE inv_price_sync_task (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id   BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  batch_bn    VARCHAR(32)     NOT NULL COMMENT '批次号(唯一,Redis发号器)',
  plan_id     BIGINT UNSIGNED NOT NULL COMMENT '调价计划 LFK→inv_price_adjust_plan(货主/租户维度经计划头获取,§6.5字段清单)',
  shop_id     BIGINT UNSIGNED NOT NULL COMMENT '目标店铺 LFK→oms_gateway.gw_shop',
  platform    VARCHAR(32)     NOT NULL COMMENT '平台标识:taobao/jd/pdd/xhs/vop/douyin/wechat/kuaishou(枚举同gw_platform_config.platform)',
  total       INT             NOT NULL DEFAULT 0 COMMENT '本批次总SKU数',
  succ        INT             NOT NULL DEFAULT 0 COMMENT '成功数(条目台账记succ并更新档案synced)',
  fail        INT             NOT NULL DEFAULT 0 COMMENT '失败数(限流/网络经D02.05退避重试;失败率超阈值5%告警)',
  skip        INT             NOT NULL DEFAULT 0 COMMENT '跳过数(业务失败不重试,进部分失败清单)',
  qps_limit   INT             NOT NULL DEFAULT 0 COMMENT '本批次QPS限速参数快照(店铺/平台级配置,D02.01令牌桶;价格回传队列优先级=低)',
  shard_size  INT             NOT NULL DEFAULT 0 COMMENT '批量分片大小快照(万级SKU计划分片排队§5.3)',
  status      VARCHAR(16)     NOT NULL DEFAULT 'executing' COMMENT '批次状态:executing=执行中,completed=已完成,partial_failed=部分失败',
  alert_flag  TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '失败率超阈值告警标记:0=否,1=已触发(D01.07企微)',
  create_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间(计数汇总滚动)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_inv_price_sync_task_bn (batch_bn),
  KEY idx_inv_price_sync_task_plan (plan_id),
  KEY idx_inv_price_sync_task_status (status, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='价格回传批次(D04.11,P1;计划维度执行批次视图,SKU级明细在inv_price_adjust_item与D02.04台账sync_type=price)';

-- ============================================================================
-- 脚本结束 · 共 55 张表（P0×24 / P1×31，含 V1.2 增补 2 张、V1.5 增补 5 张）+ 初始字典数据
-- 自查: 括号/逗号/分号配对、COMMENT 内无未转义引号、JSON 默认值均为 NULL 或显式提供
-- ============================================================================
