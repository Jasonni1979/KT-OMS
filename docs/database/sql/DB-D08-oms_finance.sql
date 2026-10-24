-- ============================================================================
-- DB-D08 财务对账域建表脚本（oms_finance）
-- 文档编号: DB-D08 · 版本 V1.0 · 2026-10-24 · MySQL 8.0 可执行 DDL
-- 上游契约: DB-00 数据库设计总册（schema=oms_finance / 表前缀 fin_ / 公共字段 / 不建物理外键）
-- 需求依据: SRS-D08.01 ~ SRS-D08.06 §6 数据字段章节
-- ----------------------------------------------------------------------------
-- 财务域三条红线（SRS-00 §4.4 / Q5 决策）:
--   1) 所有财务单据必带 owner_id 货主维度（跨货主汇总类任务表 owner_id=0 并逐表注明例外）
--   2) 双口径金额成对出现: amount_paid 客户实付口径 / amount_platform 平台承担口径, 禁止混算
--   3) 金蝶记账, OMS 出统计+明细+排查工具: 本域不做凭证/总账, 财务单据红冲语义禁改删
-- 执行顺序:
--   1) CREATE DATABASE oms_finance
--   2) 字典/配置: fin_dict / fin_gap_account / fin_credit_period / fin_settle_config /
--      fin_service_fee_rule / fin_invoice_channel / fin_kingdee_adapter / fin_code_mapping
--   3) 应收账单族(D08.01): fin_receivable / fin_receivable_adjust / fin_platform_bill /
--      fin_platform_bill_item / fin_bill_match / fin_bill_diff / fin_platform_fee /
--      fin_ar_ledger / fin_aging
--   4) 结算族(D08.02): fin_settlement / fin_settlement_item / fin_settlement_confirm / fin_settlement_diff
--   5) 核销族(D08.03): fin_receipt / fin_write_off / fin_receipt_match / fin_error_table / fin_period_close
--   6) 运费族(D08.04): fin_freight_estimate / fin_freight_bill / fin_freight_bill_item /
--      fin_freight_match / fin_freight_diff / fin_freight_task / fin_freight_claim
--   7) 发票族(D08.05): fin_invoice_apply / fin_invoice_pool / fin_invoice / fin_invoice_red / fin_invoice_merge
--   8) 金蝶集成族(D08.06): fin_kingdee_supply / fin_kingdee_supply_file / fin_kingdee_receipt / fin_kingdee_recon
--   9) 初始字典 INSERT: fin_dict（结算周期/服务费类型/金蝶供数类别/差异类型/扣费类型/核销档位）
--      / fin_gap_account（gap 借贷科目映射样例）/ fin_invoice_channel（发票渠道）
--      / fin_kingdee_adapter（K3/EAS/云星空占位）/ fin_settle_config（全局默认月结）
-- 依赖: 仅本 schema；跨域为逻辑外键 LFK（应用层校验），不建物理外键
-- 分区/分表约定: fin_receivable 按 period 月度分区（DDL 注释标注, 分区由 DBA 实施）;
--      fin_platform_bill_item 按渠道+账期分区预留; 归档表后缀 _arc
-- 命名/类型基线: 见 DB-00 §2/§6；金额 DECIMAL(18,2) / 单价 DECIMAL(18,4) / 比例 DECIMAL(9,4)
--      / utf8mb4 / utf8mb4_0900_ai_ci / InnoDB / 枚举不用 MySQL ENUM, 注释写全枚举值
-- ============================================================================

CREATE DATABASE IF NOT EXISTS oms_finance DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE oms_finance;

-- ============================================================================
-- 一、字典 / 配置表
-- ============================================================================

-- 1. 财务域通用字典（D08 全域 · P1，配置表 owner_id 免填）
CREATE TABLE fin_dict (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id   BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID(内部租户=1)',
  dict_type   VARCHAR(32)     NOT NULL COMMENT '字典类型: settle_cycle=结算周期/service_fee_type=服务费类型/feed_type=金蝶供数类别/gap_type=差异类型/fee_type=平台扣费类型/writeoff_level=核销档位/invoice_type=票种',
  dict_code   VARCHAR(32)     NOT NULL COMMENT '字典码(类型内唯一)',
  dict_name   VARCHAR(64)     NOT NULL COMMENT '字典名称',
  parent_code VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '父码(层级字典用,空=根)',
  sort_no     INT             NOT NULL DEFAULT 0 COMMENT '同级排序',
  ext_json    JSON            NULL DEFAULT NULL COMMENT '扩展属性(如供数类别的频率/粒度/口径要点)',
  status      TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=停用',
  create_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted  TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_dict (dict_type, dict_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='财务域通用字典(D08全域,P1,配置表)';

-- 2. gap 差异借贷科目映射（D08.01 §5.3 / D08.03 FR-04b · P1）← 商派 financebase_gap 完整保留
--    差异类型→(借方科目,贷方科目) 金蝶科目编码映射; OMS 只供数不记账(Q5), 变更 OA 备案
CREATE TABLE fin_gap_account (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id            BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id             BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主ID(0=全局默认,货主级阈值覆盖用) LFK→oms_org.org_owner',
  gap_type             VARCHAR(32)     NOT NULL COMMENT '差异类型码(与fin_dict.gap_type同字典): caliber_platform=口径差异-平台承担不结算/refund_timing=退款时序差/fee_unsplit=平台扣费未拆/less_settle=金额不符-平台少结/oms_error=金额不符-OMS错记/single_platform=单边-平台侧/single_oms=单边-OMS侧/fee_tail=平台手续费尾差/penalty=平台罚没/bad_debt=坏账核销/over_receipt=多收待退/freight_weight=运费重量差/other=其他',
  gap_name             VARCHAR(64)     NOT NULL COMMENT '差异类型名称',
  debit_account        VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '借方科目编码(金蝶科目, D08.06维护; 时序差类不映射为空)',
  credit_account       VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '贷方科目编码(金蝶科目)',
  auto_clean_threshold DECIMAL(18,2)   NOT NULL DEFAULT 100.00 COMMENT '单笔自动清理上限(元,默认100; 超限逐笔人工定性, D08.03 FR-04c)',
  alert_threshold      DECIMAL(18,2)   NOT NULL DEFAULT 500.00 COMMENT '月度累计告警阈值(元,默认500,货主级可配, D08.03 FR-04d)',
  need_handle          TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '是否需处理:0=口径差无需处理(误差表累计),1=需处理',
  oa_ref               VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '映射变更OA备案单引用',
  status               TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=停用',
  create_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted           TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_gap_account (gap_type, owner_id),
  KEY idx_fin_gap_account_owner (owner_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='gap差异借贷科目映射(D08.03,P1)←商派financebase_gap;科目映射为D08.06金蝶凭证参考数据源,OMS不记账';

-- 3. 账期配置（D08.03 FR-06 · P1，货主级）
CREATE TABLE fin_credit_period (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id           BIGINT UNSIGNED NOT NULL COMMENT '货主ID(一货主一生效配置) LFK→oms_org.org_owner',
  credit_days        INT             NOT NULL DEFAULT 30 COMMENT '账期天数(结算单确认后收/付款账期,默认30,品牌方可谈判差异化)',
  start_anchor       VARCHAR(16)     NOT NULL DEFAULT 'archive_date' COMMENT '账期起算日: archive_date=结算单归档日(默认)/confirm_date=确认日',
  overdue_alert_days INT             NOT NULL DEFAULT 3 COMMENT '逾期预警提前天数(默认3,到期前提醒D01.07)',
  freeze_threshold   DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '逾期熔断阈值(元,0=关闭; P2预留联动D03审单拦截,首期只预警)',
  tolerance_abs      DECIMAL(18,2)   NOT NULL DEFAULT 5.00 COMMENT '差异核销容差-绝对额(元,默认5; 与相对值取小, D08.03 §5.1)',
  tolerance_rate     DECIMAL(9,4)    NOT NULL DEFAULT 0.0005 COMMENT '差异核销容差-相对值(默认0.0005=0.05%; min(绝对额,应收额×比例))',
  bad_debt_days      INT             NOT NULL DEFAULT 180 COMMENT '长期挂账坏账评估阈值(天,默认180, D08.03 FR-05a)',
  status             TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=历史(变更只对未来生效,留档)',
  effective_time     DATETIME(3)     NOT NULL COMMENT '生效时间',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version            INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted         TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  KEY idx_fin_credit_period_owner (owner_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='账期与核销容差配置(D08.03,P1,货主级)';

-- 4. 结算周期配置（D08.02 FR-01 · P1，货主级）
CREATE TABLE fin_settle_config (
  id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id             BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id              BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主ID(0=全局默认配置) LFK→oms_org.org_owner',
  cycle_type            VARCHAR(16)     NOT NULL DEFAULT 'monthly' COMMENT '结算周期类型: monthly=月结/semi_monthly=半月结(15日+月末)/weekly=周结(周日制)',
  anchor_day            VARCHAR(32)     NOT NULL DEFAULT 'month_end' COMMENT '结账日锚点: month_end=自然月末/自定义日(1-28)/semi=15+月末/week_sun=周日',
  grace_days            INT             NOT NULL DEFAULT 3 COMMENT '宽限期(天,默认3; 结账日后N天内延迟到达本期单据并入本期, §5.3)',
  confirm_deadline_days INT             NOT NULL DEFAULT 10 COMMENT '品牌方确认期限(天,默认10; 超期催办不视同确认-资金红线)',
  settle_caliber        VARCHAR(16)     NOT NULL DEFAULT 'paid' COMMENT '货款结算口径: paid=客户实付口径(默认)/platform_all=平台结算口径(客户实付+平台承担,合同差异)',
  platform_in_settle    TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '平台承担口径是否参与结算:0=否(默认),1=是(货主级合同配置)',
  zero_period_skip      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '零交易周期:0=生成空结算单保持连续性(默认),1=跳过(FR-02f)',
  effect_from           DATE            NOT NULL COMMENT '生效起始周期(变更只对未来周期生效, FR-01c)',
  effect_to             DATE            NULL DEFAULT NULL COMMENT '失效日期(NULL=长期有效; 历史版本留档)',
  oa_ref                VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '配置变更OA审批单引用',
  status                TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=历史',
  create_time           DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time           DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version               INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted            TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  KEY idx_fin_settle_config_owner (owner_id, status, effect_from)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='结算周期配置(D08.02,P1,货主级)';

-- 5. 代销服务费条款（D08.02 FR-04 · P1，货主合同级,一货主多条款并存）
CREATE TABLE fin_service_fee_rule (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NOT NULL COMMENT '货主ID LFK→oms_org.org_owner',
  term_name      VARCHAR(128)    NOT NULL COMMENT '条款名(如基础服务费/活动专项服务费)',
  model          VARCHAR(16)     NOT NULL COMMENT '计费模型: ratio=销售额比例/fixed=固定金额/ladder=阶梯费率/guarantee_combo=保底组合(max(固定额,基数×费率))',
  rate           DECIMAL(9,4)    NOT NULL DEFAULT 0.0000 COMMENT '费率(4位小数,如0.0500=5%; ratio/ladder模型用)',
  fixed_amount   DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '周期固定费(元; fixed/guarantee_combo模型用)',
  ladder_json    JSON            NULL DEFAULT NULL COMMENT '阶梯档位表: [{"lower":0,"upper":500000,"rate":0.0600},...](区间下限/上限/费率,周期累计落档分档计费,跨期不累计)',
  base_caliber   VARCHAR(16)     NOT NULL DEFAULT 'paid' COMMENT '计算基数口径: paid=客户实付口径(默认)/platform_all=平台结算口径(GMV全额=实付+平台承担)',
  with_refund    TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '基数是否扣减退款冲减:1=净销售额(默认),0=毛销售额(合同条款)',
  effect_from    DATE            NOT NULL COMMENT '生效起始(续签费率变更只对未来周期生效)',
  effect_to      DATE            NULL DEFAULT NULL COMMENT '失效日期(NULL=长期)',
  contract_ref   VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '合同引用编号',
  oa_ref         VARCHAR(64)     NOT NULL DEFAULT '' COMMENT 'OA备案单引用',
  status         TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=停用,3=历史',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version        INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  KEY idx_fin_service_fee_rule_owner (owner_id, status, effect_from)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='代销服务费条款(D08.02,P1);术语约定:service_fee=凯淳向品牌方收取,与平台佣金(platform_fee)严格区分';

-- 6. 电子发票渠道适配配置 + 销方主体档案（D08.05 FR-02a/03a · P1，配置表 owner_id 免填）
CREATE TABLE fin_invoice_channel (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  channel_code   VARCHAR(32)     NOT NULL COMMENT '渠道码(唯一): nuonuo=诺诺/baiwang=百旺/hangxin=航信/platform_proxy=平台代开(字典可扩展)',
  channel_name   VARCHAR(64)     NOT NULL COMMENT '渠道名称',
  api_base       VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '服务商API基地址',
  app_key        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '应用标识',
  secret_enc     VARBINARY(255)  NULL DEFAULT NULL COMMENT '密钥密文(信封加密D01.05,独立授权访问)',
  tax_device_no  VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '税控盘/税控设备编号',
  adapter_class  VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '适配器实现类名(issue/redIssue/query/getPdf/cancel五方法统一接口,可插拔)',
  issuer_json    JSON            NULL DEFAULT NULL COMMENT '销方主体档案集: [{"issuer_id":1,"issuer_name":"凯淳","tax_no":"...","addr_tel":"...","bank_account":"..."}](多主体开票:凯淳/品牌方)',
  issuer_rule    JSON            NULL DEFAULT NULL COMMENT '销方主体归属规则: 货主类型×业务类型→issuer_id 映射(买断→凯淳;代销→品牌方或凯淳代收代开,可配置【待业务确认】)',
  status         TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=停用',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version        INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_invoice_channel_code (channel_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='电子发票渠道适配配置+销方主体(D08.05,P1,配置表);新增服务商=注册新适配器零改存量';

-- 7. 编码映射（D08.06 FR-05 · P1，四套映射:物料/供应商/客户/科目）
CREATE TABLE fin_code_mapping (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主ID(0=全局映射;客户映射类可为货主粒度) LFK→oms_org.org_owner',
  map_type       VARCHAR(16)     NOT NULL COMMENT '映射类型: material=物料(只读消费D04.01 kingdee_material_code)/supplier=供应商/customer=客户(货主/店铺/经销商)/subject=科目',
  oms_code       VARCHAR(64)     NOT NULL COMMENT 'OMS编码(物料bm编码/供应商ID/货主店铺编码/业务类型码)',
  kd_code        VARCHAR(64)     NOT NULL COMMENT '金蝶编码(物料编码/供应商编码/客户编码/科目编码)',
  biz_type       VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '科目映射专用-业务类型: sales_income=销售收入/platform_income=平台承担收入/refund_offset=退款冲减/freight_expense=运费费用/service_fee=代销服务费/commission=佣金/estimate_ap=暂估应付/price_adjust=价差调整/bad_debt=坏账/claim_recovery=索赔回收',
  dimension_json JSON            NULL DEFAULT NULL COMMENT '科目映射维度: {"owner_type":"代销","shop_id":0,"bearer_type":"kaichun"}(货主类型/店铺/承担方)',
  direction      TINYINT         NOT NULL DEFAULT 0 COMMENT '记账方向:0=不适用,1=借,2=贷(科目映射用)',
  gap_flag       TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '是否gap差异科目:0=否,1=是(联动D08.03误差表,单一事实源)',
  effective_from DATE            NOT NULL COMMENT '生效时间(变更未来生效,已生成供数文件不回改)',
  map_version    INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '映射版本(随供数快照固化,历史文件可回放当时映射)',
  oa_ref         VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '变更OA备案',
  status         TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=停用',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_code_mapping (map_type, oms_code, biz_type, effective_from),
  KEY idx_fin_code_mapping_kd (map_type, kd_code),
  KEY idx_fin_code_mapping_gap (gap_flag, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='OMS↔金蝶编码映射(D08.06,P1)←商派account_chart应用场景语义升级:结构化映射替代硬编码行';

-- 8. 金蝶API适配器配置（D08.06 FR-03b · P1，配置表 owner_id 免填；K3/EAS/云星空占位【待确认版本】）
CREATE TABLE fin_kingdee_adapter (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  adapter_code    VARCHAR(32)     NOT NULL COMMENT '适配器码(唯一): FILE=文件通道(首期)/K3=金蝶K3/EAS=金蝶EAS/CLOUD_STAR=云星空WebAPI',
  adapter_name    VARCHAR(64)     NOT NULL COMMENT '适配器名称',
  channel_type    VARCHAR(16)     NOT NULL DEFAULT 'file' COMMENT '通道类型: file=文件交换/api=接口/mid_table=中间表(类别粒度可灰度切换)',
  api_base        VARCHAR(255)    NOT NULL DEFAULT '' COMMENT 'API基地址(占位空)',
  auth_type       VARCHAR(16)     NOT NULL DEFAULT '' COMMENT '鉴权方式: none/basic/oauth2/kd_token(占位)',
  credential_enc  VARBINARY(255)  NULL DEFAULT NULL COMMENT '凭据密文(信封加密D01.05)',
  support_actions JSON            NULL DEFAULT NULL COMMENT '能力矩阵: {"deliver":1,"receipt":1,"reverse":1,"queryBalance":0,"writeBackStatus":0}',
  impl_class      VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '适配器实现类名(KingdeeK3Adapter/KingdeeEasAdapter/KingdeeCloudAdapter占位,确认版本即实施)',
  status          TINYINT         NOT NULL DEFAULT 0 COMMENT '状态:0=占位,1=启用,2=停用',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_kingdee_adapter_code (adapter_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='金蝶API适配器配置(D08.06,P1,配置表);供数契约与通道解耦,金蝶版本差异隔离在本层';

-- ============================================================================
-- 二、应收与账单族（D08.01 · P1）
-- ============================================================================

-- 9. 应收明细（D08.01 §6.1/6.2 · P1，订单行级一行一应收,单头按ar_bn聚合）
--    ← 商派 finance_ar + ar_items 改造: +owner_id行级货主分账 +双口径结构化双列 +借调透传
--    红冲语义禁改删(单据类,无is_deleted); 大表按period月度分区(DBA实施)
CREATE TABLE fin_receivable (
  id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id             BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id              BIGINT UNSIGNED NOT NULL COMMENT '货主ID(行级,多货主订单按行归属分账-SRS-00契约核心) LFK→oms_org.org_owner',
  ar_bn                 VARCHAR(32)     NOT NULL COMMENT '应收单号AR{YYYYMMDD}{6位序列}(单头聚合键,一订单一单)',
  idem_key              VARCHAR(96)     NOT NULL COMMENT '幂等键: 销售={order_item_id}:sale/冲减={refund_bn}:{order_item_id}/调整=ADJ{adjust_id}(MQ重投直接返回)',
  ar_type               VARCHAR(16)     NOT NULL COMMENT '单据类型: sale=销售应收(正向)/refund_offset=退款冲减(负向,金额取负)/adjust=人工调整(正负,红冲语义新记录)',
  order_id              BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '订单ID LFK→oms_order.ord_order(销售应收必填)',
  order_bn              VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '订单号(冗余检索)',
  platform_order_bn     VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '平台单号(账单匹配主键,冗余)',
  order_item_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '订单行ID LFK→oms_order.ord_order_item(行级追溯)',
  item_seq              INT             NOT NULL DEFAULT 0 COMMENT '订单行序号',
  refund_bn             VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '退款单号 LFK→oms_aftersale.aft_refund(冲减单必填,幂等键成分)',
  bm_id                 BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '基础物料ID快照 LFK→oms_stock.inv_material',
  sm_id                 BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '销售物料ID快照 LFK→oms_stock.inv_sales_material',
  goods_num             INT             NOT NULL DEFAULT 0 COMMENT '数量(行快照)',
  amount_paid           DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '【双口径1】应收金额-客户实付口径(买家真金白银,含行分摊运费;冲减/调整可负; Σ行=订单paid_amount-freight恒等式校验)',
  amount_platform       DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '【双口径2】应收金额-平台承担口径(平台券/补贴,平台结算给商家部分;可负; 与amount_paid禁止混算)',
  amount_shop_discount  DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '商家优惠留档(商家自担不入应收,冲减收入基数,备查)',
  freight_amount        DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '运费(客户实付口径,整单挂单头行不参与行分摊,D03.01 FR-06a)',
  confirm_amount_paid   DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '已核销金额-客户实付口径(D08.03核销回写)',
  confirm_amount_platform DECIMAL(18,2) NOT NULL DEFAULT 0.00 COMMENT '已核销金额-平台承担口径(D08.03回写)',
  unconfirm_amount_paid DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '未核销余额-客户实付口径(逐笔递减CAS)',
  unconfirm_amount_platform DECIMAL(18,2) NOT NULL DEFAULT 0.00 COMMENT '未核销余额-平台承担口径',
  status                VARCHAR(16)     NOT NULL DEFAULT 'pending' COMMENT '核销状态(D08.03回写): pending=待核销/partial=部分核销/written_off=已核销',
  match_status          VARCHAR(16)     NOT NULL DEFAULT 'unmatched' COMMENT '账单匹配状态: unmatched=未匹配/matched=已匹配/amount_mismatch=金额不符/single_platform=单边-平台侧/single_oms=单边-OMS侧',
  gap_type              VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '差异类型码(匹配超差时初判,字典见fin_gap_account)',
  settle_status         TINYINT         NOT NULL DEFAULT 0 COMMENT '结算状态(D08.02回写):0=未结算,1=已进结算单锁定(禁止调整),2=结算差异处理中',
  settle_bn             VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '结算单号引用(D08.02回写)',
  settle_carry_next     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '下期结算吸收标记:0=否,1=是(原应收已进已确认结算单,冲减落下期,FR-02f)',
  period                CHAR(6)         NOT NULL COMMENT '会计周期YYYYMM(按业务发生日归属;D08.03结账联动,月度分区键)',
  biz_time              DATETIME(3)     NOT NULL COMMENT '业务发生日(销售=订单完成日/冲减=退款成功日;账龄与周期归属基准)',
  lend_flag             TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '借调标记:0=否,1=是(FR-01e透传D04.05;货款应收归借出货主)',
  lend_ledger_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '借调台账ID LFK→oms_stock.inv_lend_ledger',
  loss_type             VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '资损类型(FR-02d,不入应收独立台账): abandon=弃货退款/intervene=平台介入资损/空=无',
  loss_amount           DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '资损金额(元)',
  platform_intervened   TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '平台介入补建退款透传:0=否,1=是(资损分析)',
  wait_link_flag        TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '待关联标记:0=否,1=是(冲减先于正向应收到达时挂起,正向生成自动关联,>30天告警)',
  adjust_ref            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '调整关联(红冲语义:原记录与新记录互指id,追溯链)',
  oa_ref                VARCHAR(64)     NOT NULL DEFAULT '' COMMENT 'OA审批单引用(调整单必填)',
  shop_id               BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺ID LFK→oms_gateway.gw_shop',
  brand_id              BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '品牌ID LFK→oms_stock.inv_brand',
  allocation_snapshot   JSON            NULL DEFAULT NULL COMMENT '分摊快照(getDualAmount/getWriteOffDetails原文固化,可解释审计争议回放)',
  source                VARCHAR(16)     NOT NULL DEFAULT 'api' COMMENT '数据来源: api=事件生成/local=手工/import=导入/migration=迁移期初',
  remark                VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '备注',
  create_time           DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间(入账时间)',
  update_time           DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version               INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(状态回写CAS)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_receivable_idem (idem_key),
  KEY idx_fin_receivable_arbn (ar_bn),
  KEY idx_fin_receivable_order (order_id, ar_type),
  KEY idx_fin_receivable_pobn (platform_order_bn),
  KEY idx_fin_receivable_refund (refund_bn),
  KEY idx_fin_receivable_owner_period (owner_id, period),
  KEY idx_fin_receivable_shop (shop_id, period),
  KEY idx_fin_receivable_match (match_status, period),
  KEY idx_fin_receivable_status (status, owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='应收明细-订单行级双口径(D08.01,P1)←商派finance_ar+ar_items改造:+行级owner_id货主分账+双口径结构化双列;红冲语义禁改删';

-- 10. 应收调整单（D08.01 §6.1/FR-03 · P1，红冲语义+OA审批）
CREATE TABLE fin_receivable_adjust (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID LFK→oms_org.org_owner',
  adjust_bn           VARCHAR(32)     NOT NULL COMMENT '调整单号ADJ{YYYYMMDD}{6位序列}(唯一,OA回调按单号幂等)',
  adjust_type         VARCHAR(16)     NOT NULL COMMENT '调整类型: correction=纠错(金额/口径错误)/migration=迁移期初/bad_debt_prep=坏账核销准备(转D08.03)/other=其他(备注必填)',
  receivable_id       BIGINT UNSIGNED NOT NULL COMMENT '原应收明细ID LFK→fin_receivable(红冲语义:原记录保留)',
  offset_receivable_id BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '负向冲销新记录ID(生效后回填,与adjust_ref互指)',
  amount_paid_delta   DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '【双口径1】客户实付口径调整额(±,负向冲原+正向新增两条明细)',
  amount_platform_delta DECIMAL(18,2) NOT NULL DEFAULT 0.00 COMMENT '【双口径2】平台承担口径调整额(±)',
  reason              VARCHAR(512)    NOT NULL COMMENT '调整理由(必填,审计)',
  status              VARCHAR(16)     NOT NULL DEFAULT 'pending' COMMENT '状态: pending=待OA审批/approved=审批通过已生效/rejected=驳回/canceled=撤销',
  oa_ref              VARCHAR(64)     NOT NULL COMMENT 'OA审批单引用(D10.05,必填;超阈值默认5000元货主级可配升级审批链)',
  lock_check_note     VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '锁定校验记录(已核销/已进已确认结算单禁止调整,拒绝原因留痕)',
  period              CHAR(6)         NOT NULL COMMENT '归属会计周期YYYYMM',
  shop_id             BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺ID',
  operator            VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '发起人',
  approve_time        DATETIME(3)     NULL DEFAULT NULL COMMENT '审批通过生效时间',
  create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_receivable_adjust_bn (adjust_bn),
  KEY idx_fin_receivable_adjust_ar (receivable_id),
  KEY idx_fin_receivable_adjust_owner (owner_id, period),
  KEY idx_fin_receivable_adjust_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='应收调整单(D08.01,P1);调整明细全量供D08.06金蝶同步(调整凭证数据源)';

-- 11. 平台账单归集头（D08.01 §6.3 · P1，导入批次/渠道适配器）
CREATE TABLE fin_platform_bill (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主ID(按店铺挂货主;多货主店铺=0,明细分摊后落行级owner)',
  bill_bn         VARCHAR(32)     NOT NULL COMMENT '账单归集单号PB{YYYYMMDD}{6位序列}',
  channel         VARCHAR(32)     NOT NULL COMMENT '渠道: alipay=支付宝结算(淘系)/jdwallet=京东钱包/jdbill=京东结算/douyin=抖音支付/pdd=拼多多货款/xhs=小红书/vip=唯品会(渠道适配器插件化)',
  shop_id         BIGINT UNSIGNED NOT NULL COMMENT '店铺ID LFK→oms_gateway.gw_shop',
  bill_period     CHAR(6)         NOT NULL COMMENT '账单账期YYYYMM',
  period_start    DATE            NULL DEFAULT NULL COMMENT '账单周期起',
  period_end      DATE            NULL DEFAULT NULL COMMENT '账单周期止',
  import_batch_no VARCHAR(32)     NOT NULL COMMENT '导入批次号(D01.06异步任务,单批≤10万行)',
  file_ref        VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '账单文件OSS引用(CSV/Excel)',
  total_amount    DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '账单汇总金额(元,勾稽基准)',
  row_count       INT             NOT NULL DEFAULT 0 COMMENT '账单行数(勾稽基准)',
  import_status   VARCHAR(16)     NOT NULL DEFAULT 'parsing' COMMENT '导入状态: parsing=解析中/parsed=已解析/partial_failed=部分失败(错误报告)/voided=已作废(批次覆盖红冲留档)',
  replace_batch_id BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '被覆盖旧批次ID(同店铺同账期重复导入,新批次覆盖旧批次红冲语义)',
  source          VARCHAR(16)     NOT NULL DEFAULT 'import' COMMENT '来源: import=文件导入/api=API拉取(P1预留占位,经D02.01)',
  operator        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '导入人',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_platform_bill_bn (bill_bn),
  KEY idx_fin_platform_bill_shop (shop_id, bill_period),
  KEY idx_fin_platform_bill_batch (import_batch_no),
  KEY idx_fin_platform_bill_channel (channel, bill_period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='平台账单归集头(D08.01,P1)←商派financebase_bill_base/bill_import族8张分表收敛:渠道适配器+两层落库';

-- 12. 平台账单明细流水（D08.01 §6.3 · P1，原始JSON留档+标准化流水，红冲语义无is_deleted）
CREATE TABLE fin_platform_bill_item (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主ID(店铺级流水按分摊规则FR-06b落行级owner后回填)',
  bill_id           BIGINT UNSIGNED NOT NULL COMMENT '账单归集头ID LFK→fin_platform_bill',
  raw_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '原始行引用(=bill_id+unique_key定位;raw_data原文即原始表机制)',
  unique_key        VARCHAR(128)    NOT NULL COMMENT '单据唯一值(渠道内幂等键成分)',
  raw_data          JSON            NULL DEFAULT NULL COMMENT '原始数据JSON原文保留(商派bill_base机制,审计回放)',
  platform_order_bn VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '平台单号(账单-应收匹配主键;汇总账单可空)',
  platform_serial_no VARCHAR(64)    NOT NULL DEFAULT '' COMMENT '平台流水号(渠道内唯一,导入幂等)',
  bill_date         DATE            NOT NULL COMMENT '账单日',
  settle_period     CHAR(6)         NOT NULL COMMENT '结算账期YYYYMM(周期归属)',
  direction         TINYINT         NOT NULL DEFAULT 1 COMMENT '收支方向:1=收入(货款/补贴),2=支出(退款/扣费)',
  settle_amount     DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '结算金额(平台口径,2位小数)',
  amount_paid       DECIMAL(18,2)   NULL DEFAULT NULL COMMENT '【双口径1】客户实付口径拆分(账单可拆时;不可拆置NULL)',
  amount_platform   DECIMAL(18,2)   NULL DEFAULT NULL COMMENT '【双口径2】平台承担口径拆分(不可拆置NULL+split_status=2)',
  split_status      TINYINT         NOT NULL DEFAULT 0 COMMENT '拆分状态:0=未拆分,1=已双口径拆分,2=不可拆(平台账单未分列),3=一流水拆多订单/多费用项(商派expenses_split机制)',
  fee_type          VARCHAR(32)     NOT NULL DEFAULT 'goods' COMMENT '费用类型(账单收支分类规则自动分类,未命中转人工): goods=货款/commission=佣金/tech_service=技术服务费/promotion=推广费/freight_insurance=运费险/storage=仓储费/refund=退款/other=其他',
  match_status      VARCHAR(16)     NOT NULL DEFAULT 'unmatched' COMMENT '匹配状态: unmatched=未匹配/matched=已匹配/amount_mismatch=金额不符/single_platform=单边-平台侧/hold=汇总流水转D08.03收款匹配',
  match_ar_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '匹配应收ID LFK→fin_receivable',
  gap_amount        DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT 'GAP差异金额(=OMS应收-平台结算额,带符号保留借贷方向语义)',
  shop_id           BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺ID',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(匹配CAS)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_pbill_item_serial (platform_serial_no, unique_key, bill_id),
  KEY idx_fin_pbill_item_bill (bill_id),
  KEY idx_fin_pbill_item_pobn (platform_order_bn),
  KEY idx_fin_pbill_item_match (match_status, settle_period),
  KEY idx_fin_pbill_item_fee (fee_type, settle_period),
  KEY idx_fin_pbill_item_owner (owner_id, settle_period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='平台账单明细流水(D08.01,P1);按渠道+账期分区预留;批次覆盖走红冲(旧批作废留档)';

-- 13. 账单-应收匹配记录（D08.01 FR-05 · P1，匹配结果不可手工篡改,强制匹配OA留痕）
CREATE TABLE fin_bill_match (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL COMMENT '货主ID LFK→oms_org.org_owner',
  bill_item_id      BIGINT UNSIGNED NOT NULL COMMENT '账单流水ID LFK→fin_platform_bill_item',
  receivable_id     BIGINT UNSIGNED NOT NULL COMMENT '应收明细ID LFK→fin_receivable(拆单流水按平台单号聚合后比对,一流水配一应收聚合组)',
  platform_order_bn VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '平台单号(匹配主键冗余)',
  order_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '订单ID LFK→oms_order.ord_order',
  match_type        VARCHAR(16)     NOT NULL DEFAULT 'auto_exact' COMMENT '匹配方式: auto_exact=平台单号精确匹配/auto_aggregate=拆单流水聚合匹配/manual_force=人工强制匹配(OA审批留痕)',
  match_amount      DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '匹配金额(平台结算额vs应收双口径合计-关联扣费,容差0.01元内)',
  status            VARCHAR(16)     NOT NULL DEFAULT 'matched' COMMENT '状态: matched=已匹配/released=已解除(重导入先解除旧匹配留痕再重配)',
  oa_ref            VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '强制匹配OA审批单引用(manual_force必填)',
  operator          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '操作人(自动=system)',
  match_time        DATETIME(3)     NOT NULL COMMENT '匹配时间',
  period            CHAR(6)         NOT NULL COMMENT '会计周期YYYYMM',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_bill_match_pair (bill_item_id, receivable_id),
  KEY idx_fin_bill_match_ar (receivable_id),
  KEY idx_fin_bill_match_pobn (platform_order_bn),
  KEY idx_fin_bill_match_owner (owner_id, period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='账单-应收匹配记录(D08.01,P1);日终兜底近60天未匹配集合重跑';

-- 14. 账单匹配差异清单（D08.01 §5.3/FR-07 · P1）
CREATE TABLE fin_bill_diff (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL COMMENT '货主ID LFK→oms_org.org_owner',
  bill_item_id      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '账单流水ID LFK→fin_platform_bill_item(单边-OMS侧=0)',
  receivable_id     BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '应收明细ID LFK→fin_receivable(单边-平台侧=0)',
  platform_order_bn VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '平台单号',
  diff_type         VARCHAR(32)     NOT NULL COMMENT '差异类型码(字典见fin_gap_account): caliber_platform=口径差异-平台承担不结算/refund_timing=退款时序差/fee_unsplit=平台扣费未拆/less_settle=金额不符-平台少结/oms_error=金额不符-OMS错记/single_platform=单边-平台侧/single_oms=单边-OMS侧/other=其他',
  gap_amount        DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT 'GAP差异金额(=OMS应收-平台结算额,带符号保留借贷方向)',
  auto_judge        TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '是否引擎自动初判:0=人工判定,1=自动初判(可人工改判留痕)',
  judge_remark      VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '初判/改判说明(改判留痕)',
  handle_status     VARCHAR(16)     NOT NULL DEFAULT 'pending' COMMENT '处理状态: pending=待处理/no_action=无需处理(口径差转D08.03误差表)/wait_auto=等待自动消除(时序差)/appealing=差异工单申诉中/platform_paid=平台补结/loss_confirmed=确认损失/adjusting=OMS侧修正中(引导应收调整)/closed=已闭环',
  ticket_no         VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '平台申诉差异工单号',
  error_table_id    BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '转误差表记录ID LFK→fin_error_table(no_action/loss_confirmed时回填)',
  handle_operator   VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '处理人',
  handle_time       DATETIME(3)     NULL DEFAULT NULL COMMENT '处理时间',
  handle_remark     VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '处理结果说明',
  notify_count      INT             NOT NULL DEFAULT 0 COMMENT '日报持续提醒次数(近30个账单日未决差异持续提醒,商派bill_match_notify_log机制)',
  force_oa_ref      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '强制处理OA单(差异>60天未决强制通道:确认损失/挂账)',
  shop_id           BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺ID',
  period            CHAR(6)         NOT NULL COMMENT '会计周期YYYYMM',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  KEY idx_fin_bill_diff_item (bill_item_id),
  KEY idx_fin_bill_diff_ar (receivable_id),
  KEY idx_fin_bill_diff_owner (owner_id, period, handle_status),
  KEY idx_fin_bill_diff_type (diff_type, handle_status),
  KEY idx_fin_bill_diff_shop (shop_id, period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='账单匹配差异清单(D08.01,P1);差异日报(一致率/未决金额)推财务负责人;全部闭环是D08.03月末结账检查输入';

-- 15. 平台扣费明细（D08.01 §6.4 · P1，佣金/技术服务费/推广费/运费险,红冲语义）
CREATE TABLE fin_platform_fee (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID(订单级挂单直接归属;店铺级按分摊规则挂货主) LFK→oms_org.org_owner',
  bill_item_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '来源账单流水ID LFK→fin_platform_bill_item',
  fee_type            VARCHAR(32)     NOT NULL COMMENT '费用类型: commission=佣金/tech_service=技术服务费/promotion=推广费/freight_insurance=运费险/storage=仓储费/other=其他(字典同账单分类规则)',
  fee_amount          DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '扣费金额(元,支出为正;红冲行为负)',
  fee_level           VARCHAR(16)     NOT NULL DEFAULT 'order' COMMENT '扣费级别: order=订单级(带平台单号挂订单+店铺+货主)/shop=店铺级(推广费等无单号,按分摊规则挂货主)',
  order_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '订单ID LFK→oms_order.ord_order(店铺级=0)',
  platform_order_bn   VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '平台单号(订单级扣费)',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID LFK→oms_gateway.gw_shop',
  alloc_type          VARCHAR(16)     NOT NULL DEFAULT 'direct' COMMENT '店铺级分摊方式: direct=订单级直接归属/sales_ratio=销售额占比/fixed_ratio=固定比例/single_owner=指定货主全额(分摊规则货主级配置)',
  alloc_base_snapshot JSON            NULL DEFAULT NULL COMMENT '分摊基数快照(可解释;尾差归最大额行,Σ分摊=原额,D03.01 §5.2尾差规则同款)',
  settle_status       TINYINT         NOT NULL DEFAULT 0 COMMENT '结算状态(D08.02回写):0=未结算,1=已进结算单',
  settle_bn           VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '结算单号引用',
  reverse_flag        TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '红冲标记:0=正常,1=红冲行(扣费明细不可改,红冲语义)',
  origin_fee_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '红冲原记录ID(互指追溯)',
  period              CHAR(6)         NOT NULL COMMENT '会计周期YYYYMM(按账单日归属)',
  create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  KEY idx_fin_platform_fee_owner (owner_id, period, fee_type),
  KEY idx_fin_platform_fee_item (bill_item_id),
  KEY idx_fin_platform_fee_order (order_id),
  KEY idx_fin_platform_fee_shop (shop_id, period),
  KEY idx_fin_platform_fee_settle (settle_status, settle_bn)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='平台扣费明细(D08.01,P1)←商派order_settle佣金明细+expenses_split改造;供D08.02结算扣减/D11费用分析/D08.06金蝶费用凭证数据源';

-- 16. 应收台账（D08.01 §6.5 · P1，货主×店铺×会计周期,双口径分列）
CREATE TABLE fin_ar_ledger (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID LFK→oms_org.org_owner',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID LFK→oms_gateway.gw_shop',
  period              CHAR(6)         NOT NULL COMMENT '会计周期YYYYMM(自然月,与D08.03结账期间一致)',
  init_paid           DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '【双口径1】期初应收-客户实付口径',
  init_platform       DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '【双口径2】期初应收-平台承担口径',
  added_paid          DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '【双口径1】本期新增应收-客户实付',
  added_platform      DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '【双口径2】本期新增应收-平台承担',
  offset_paid         DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '【双口径1】本期冲减(退款+调整)-客户实付',
  offset_platform     DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '【双口径2】本期冲减-平台承担',
  received_paid       DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '【双口径1】本期已收(D08.03核销回写,本模块只读)-客户实付',
  received_platform   DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '【双口径2】本期已收-平台承担',
  final_paid          DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '【双口径1】期末待收=期初+新增-冲减-已收-客户实付',
  final_platform      DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '【双口径2】期末待收-平台承担',
  gap_pending         DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '本期未决差异额(GAP汇总,带符号)',
  check_status        TINYINT         NOT NULL DEFAULT 0 COMMENT '日终重算校验:0=未校验,1=一致,2=不一致已按明细重算(明细是唯一事实源)',
  check_time          DATETIME(3)     NULL DEFAULT NULL COMMENT '日终校验时间',
  create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(事件驱动增量更新,行锁by货主×店铺×周期)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_ar_ledger (owner_id, shop_id, period),
  KEY idx_fin_ar_ledger_period (period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='应收台账-货主×店铺×周期双口径分列(D08.01,P1)←商派statement期初期末结构镜像为应收侧';

-- 17. 账龄分析快照（D08.01 §6.5/FR-09 · P1，日算快照,双口径分列）
CREATE TABLE fin_aging (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id            BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id             BIGINT UNSIGNED NOT NULL COMMENT '货主ID LFK→oms_org.org_owner',
  shop_id              BIGINT UNSIGNED NOT NULL COMMENT '店铺ID(0=货主汇总行)',
  channel              VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '平台渠道(账龄按货主×店铺×平台维度出表,空=全部)',
  snapshot_date        DATE            NOT NULL COMMENT '快照日(D01.02调度日终快照)',
  bucket_0_30_paid     DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '【双口径1】账龄0-30天未收余额-客户实付(分档边界全局可配)',
  bucket_31_60_paid    DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '【双口径1】账龄31-60天-客户实付',
  bucket_61_90_paid    DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '【双口径1】账龄61-90天-客户实付(>90天红色预警货主级阈值可配)',
  bucket_91_180_paid   DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '【双口径1】账龄91-180天-客户实付',
  bucket_gt_180_paid   DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '【双口径1】账龄>180天-客户实付',
  bucket_0_30_platform DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '【双口径2】账龄0-30天-平台承担',
  bucket_31_60_platform DECIMAL(18,2)  NOT NULL DEFAULT 0.00 COMMENT '【双口径2】账龄31-60天-平台承担',
  bucket_61_90_platform DECIMAL(18,2)  NOT NULL DEFAULT 0.00 COMMENT '【双口径2】账龄61-90天-平台承担',
  bucket_91_180_platform DECIMAL(18,2) NOT NULL DEFAULT 0.00 COMMENT '【双口径2】账龄91-180天-平台承担',
  bucket_gt_180_platform DECIMAL(18,2) NOT NULL DEFAULT 0.00 COMMENT '【双口径2】账龄>180天-平台承担',
  dispute_amount_paid  DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '【双口径1】争议账龄单列(差异工单申诉中金额,不并入正常催收口径,FR-09d)-客户实付',
  dispute_amount_platform DECIMAL(18,2) NOT NULL DEFAULT 0.00 COMMENT '【双口径2】争议账龄-平台承担',
  create_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_aging (owner_id, shop_id, channel, snapshot_date),
  KEY idx_fin_aging_date (snapshot_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='账龄分析日快照(D08.01,P1);账龄结构变化趋势供D11;逾期清单推财务与商务催收';

-- ============================================================================
-- 三、结算族（D08.02 · P1）
-- ============================================================================

-- 18. 结算单（D08.02 §6.3 · P1，货主周期结算:期初调整+销售应收-退款-扣费-服务费+借调=应结净额）
CREATE TABLE fin_settlement (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL COMMENT '货主ID(结算单以货主为主维度-SRS-00契约) LFK→oms_org.org_owner',
  brand_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '品牌ID LFK→oms_stock.inv_brand',
  settle_bn         VARCHAR(64)     NOT NULL COMMENT '结算单号ST{货主码}{周期标识}{版本}(如ST-A01-202609-V1;红冲镜像单-R后缀)',
  period            VARCHAR(16)     NOT NULL COMMENT '结算周期标识(月结=YYYYMM/半月=YYYYMMH1|H2/周结=YYYYWW)',
  period_start      DATE            NOT NULL COMMENT '周期区间起([上期结账日+1,本期结账日],按业务发生日归属)',
  period_end        DATE            NOT NULL COMMENT '周期区间止',
  owner_type        TINYINT         NOT NULL DEFAULT 1 COMMENT '货主类型:1=代销(完整确认流),2=买断(内部简化流,无品牌方确认,附成本参考列)',
  settle_caliber    VARCHAR(16)     NOT NULL DEFAULT 'paid' COMMENT '货款结算口径快照(取自fin_settle_config): paid=客户实付/platform_all=平台结算口径',
  amt_receivable    DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT 'A本期销售应收(结算口径,=Σ正向应收明细,双口径见明细行)',
  amt_refund        DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT 'B本期退款冲减(=Σ负向应收+上期结转settle_carry_next项)',
  amt_platform_fee  DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT 'C平台扣费(佣金/技术服务费/推广费/运费险/仓储费+D08.04运费差异汇入)',
  amt_service_fee   DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT 'D代销服务费(计算引擎输出,比例/固定/阶梯/保底组合;与平台佣金严格区分)',
  amt_lend_trade    DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT 'E借调内部交易(=Σ借入方应付-借出方应收;镜像勾稽对方货主同周期金额相等方向相反)',
  amt_init_adjust   DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT 'F期初调整(上期吸收调整单+本期人工期初调整OA)',
  amt_net           DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '本期应结净额=A-B-C-D-E+F(带符号,轧差零尾差)',
  net_direction     TINYINT         NOT NULL DEFAULT 0 COMMENT '净额方向:0=零交易,1=净额>0凯淳应付品牌方(货款结算),2=净额<0品牌方应付凯淳(服务费/借调超货款)',
  payable_side      DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '双向呈现-凯淳应付品牌方金额=max(净额,0)(金蝶应付单取数)',
  receivable_side   DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '双向呈现-品牌方应付凯淳金额=max(-净额,0)(金蝶应收单取数)',
  cost_memo_amount  DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '成本参考列(买断毛利分析:D04.07销售成本聚合,不参与结算)',
  status            VARCHAR(24)     NOT NULL DEFAULT 'draft' COMMENT '状态机: draft=草稿/inner_auditing=内部审核中/brand_confirming=待品牌方确认/diff_handling=差异处理中(可循环,确认期限暂停)/confirmed=已确认/archived=已归档(期间锁定)/kd_pushed=已推金蝶/red_flushed=已红冲(保留全量数据)/canceled=已作废(草稿/审核中)',
  settle_version    INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '版本号(红冲重算递增,历史版本保留,V1→R→V2版本链)',
  origin_settle_id  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '红冲原单ID(镜像单全要素取负引用原单,互指)',
  confirm_channel   VARCHAR(16)     NOT NULL DEFAULT '' COMMENT '确认通道: online=门户在线确认/offline_sealed=线下盖章回传登记(附件必传)/inner=买断内部确认',
  kd_push_status    TINYINT         NOT NULL DEFAULT 0 COMMENT '金蝶推送状态(经D08.06):0=待推,1=已推,2=失败重试;红冲时冲销指令先于V2推送(顺序红线)',
  kd_push_time      DATETIME(3)     NULL DEFAULT NULL COMMENT '金蝶推送时间',
  archive_time      DATETIME(3)     NULL DEFAULT NULL COMMENT '归档时间(触发settle_status回写:D08.01应收/D04.05台账settle_month/D04.04单据markSettled)',
  period_lock       TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '期间锁定标记:0=未锁,1=已锁(该周期该货主结算要素禁止再进新结算单,后续差异全走调整单)',
  oa_refs           JSON            NULL DEFAULT NULL COMMENT '审批引用集(内部审核/红冲/调整/配置变更OA单)',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(状态CAS,同owner+period分布式锁)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_settlement_bn (settle_bn),
  UNIQUE KEY uk_fin_settlement_period (owner_id, period, settle_version),
  KEY idx_fin_settlement_status (status, period),
  KEY idx_fin_settlement_origin (origin_settle_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='结算单-货主周期双向净额(D08.02,P1);业务对账单非会计凭证,确认后经D08.06推金蝶;商派statement无品牌方结算模型-凯淳原创';

-- 19. 结算明细行（D08.02 §6.4 · P1，五类要素全量可下钻）
CREATE TABLE fin_settlement_item (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL COMMENT '货主ID LFK→oms_org.org_owner',
  settle_id       BIGINT UNSIGNED NOT NULL COMMENT '结算单ID LFK→fin_settlement',
  element_type    VARCHAR(16)     NOT NULL COMMENT '要素类型: receivable=销售应收/refund=退款冲减/platform_fee=平台扣费/service_fee=服务费/lend_trade=借调内部交易/init_adjust=期初调整',
  source_ref      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '来源引用: ar_id/fee_id/lend_ledger_id/term_id/adjust_id(全量可下钻)',
  amount          DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '结算口径金额(口径=settle_caliber配置)',
  amount_paid     DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '【双口径1】客户实付口径金额(应收/冲减要素必拆)',
  amount_platform DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '【双口径2】平台承担口径金额(应收/冲减要素必拆;其余要素适用时拆分)',
  lend_direction  TINYINT         NOT NULL DEFAULT 0 COMMENT '借调方向:0=非借调,1=本货主为借入方应付凯淳(+),2=本货主为借出方应收(轧抵-)',
  lend_num        INT             NOT NULL DEFAULT 0 COMMENT '借调消耗数量(consumed_num,D04.05台账)',
  lend_price      DECIMAL(18,4)   NOT NULL DEFAULT 0.0000 COMMENT '借调结算单价(内部购销价/成本价快照/免费=0)',
  lend_ledger_id  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '借调台账ID LFK→oms_stock.inv_lend_ledger(归档回写settle_month/settle_status)',
  fee_calc_trace  JSON            NULL DEFAULT NULL COMMENT '服务费计算轨迹: {"term_id":1,"model":"ladder","steps":[{"lower":0,"upper":500000,"base":500000,"rate":0.0600,"amount":30000}]}(档位×基数快照×费率固化,可回放幂等)',
  shop_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺ID',
  period          CHAR(6)         NOT NULL COMMENT '会计周期YYYYMM(分区键)',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  KEY idx_fin_settlement_item_settle (settle_id, element_type),
  KEY idx_fin_settlement_item_source (source_ref),
  KEY idx_fin_settlement_item_owner (owner_id, period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='结算明细行(D08.02,P1);勾稽校验:Σ明细行=汇总列逐要素,与D08.01台账交叉核对±0.01,不平则生成失败';

-- 20. 品牌方确认记录（D08.02 FR-05c · P1，电子签核留痕/线下盖章登记）
CREATE TABLE fin_settlement_confirm (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL COMMENT '货主ID(品牌方门户只见本货主,D10.04行隔离) LFK→oms_org.org_owner',
  settle_id       BIGINT UNSIGNED NOT NULL COMMENT '结算单ID LFK→fin_settlement',
  settle_bn       VARCHAR(64)     NOT NULL COMMENT '结算单号(冗余检索)',
  confirm_round   INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '确认轮次(V1确认/V2重新确认/红冲知情确认,多轮留痕)',
  action          VARCHAR(16)     NOT NULL COMMENT '动作: confirm=在线确认/objection=提交异议/seal_register=线下盖章登记/red_notify_ack=红冲知情确认',
  channel         VARCHAR(16)     NOT NULL DEFAULT 'online' COMMENT '通道: online=门户在线/offline_sealed=线下盖章回传(附件必传+登记人+OA备案视同确认)',
  confirmer       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '确认人(电子签核留痕)',
  confirm_time    DATETIME(3)     NULL DEFAULT NULL COMMENT '确认时间',
  confirm_ip      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '确认IP(电子签核留痕)',
  seal_attachment VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '盖章扫描件OSS引用(offline_sealed必传)',
  diff_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '异议记录ID LFK→fin_settlement_diff(action=objection时)',
  register_operator VARCHAR(64)   NOT NULL DEFAULT '' COMMENT '凯淳登记人(线下通道)',
  oa_ref          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '线下盖章例外登记OA备案',
  remark          VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '备注',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  KEY idx_fin_settlement_confirm_settle (settle_id, confirm_round),
  KEY idx_fin_settlement_confirm_owner (owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='品牌方门户确认记录(D08.02,P1);超期不视同确认(资金单据红线,必须明示确认动作)';

-- 21. 结算差异/品牌方异议与调整单（D08.02 §6.5/FR-06 · P1）
CREATE TABLE fin_settlement_diff (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NOT NULL COMMENT '货主ID LFK→oms_org.org_owner',
  settle_id        BIGINT UNSIGNED NOT NULL COMMENT '结算单ID LFK→fin_settlement',
  settle_item_id   BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '结算明细行ID(行级异议引用,0=单头级)',
  record_type      VARCHAR(16)     NOT NULL COMMENT '记录类型: objection=品牌方异议/adjust=调整单',
  adjust_type      VARCHAR(16)     NOT NULL DEFAULT '' COMMENT '调整类型(record_type=adjust时): diff_adjust=差异调整(异议成立)/init_adjust=期初调整(下期吸收承接)/manual_adjust=人工调整(商务让步)',
  adjust_bn        VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '调整单号SA{YYYYMMDD}{6位序列}(调整类必填)',
  amount           DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '金额(带方向±;异议金额=争议额)',
  absorb_mode      VARCHAR(16)     NOT NULL DEFAULT '' COMMENT '吸收方式: current_fix=本期修正(当期重算重出版本+1,原版本作废留档,限归档前)/next_absorb=下期吸收(本期按原额确认,挂账下期F项自动承接)',
  absorb_period    CHAR(6)         NOT NULL DEFAULT '' COMMENT '吸收周期(挂账追溯:哪期产生/哪期吸收;>2期未吸收告警)',
  reason           VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '异议理由/调整理由(必填)',
  attach_refs      JSON            NULL DEFAULT NULL COMMENT '附件引用集(异议证据/盖章扫描件)',
  comm_log         JSON            NULL DEFAULT NULL COMMENT '沟通留痕: [{"time":"...","role":"brand/kc","content":"..."}](异议-核实-结论全过程,门户双方可见透明对账)',
  verify_result    VARCHAR(16)     NOT NULL DEFAULT '' COMMENT '内部核实结论: established=异议成立/not_established=不成立(沟通留痕后品牌方再确认或升级商务线下协商)',
  status           VARCHAR(16)     NOT NULL DEFAULT 'submitted' COMMENT '状态: submitted=异议已提交/verifying=内部核实中/adjust_pending=调整待OA审批/effective=已生效/absorbed=已吸收/rejected=驳回/closed=关闭',
  oa_ref           VARCHAR(64)     NOT NULL DEFAULT '' COMMENT 'OA审批单(调整超阈值升级)',
  dispute_round    INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '异议轮次(一单可多轮异议每轮留痕,异议期间确认期限暂停计时)',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  KEY idx_fin_settlement_diff_settle (settle_id, record_type),
  KEY idx_fin_settlement_diff_owner (owner_id, status),
  KEY idx_fin_settlement_diff_absorb (absorb_mode, absorb_period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='结算差异/品牌方异议与调整单(D08.02,P1);调整单台账货主维度连续可查';

-- ============================================================================
-- 四、核销族（D08.03 · P1）
-- ============================================================================

-- 22. 收付款登记（D08.03 §6.1 · P1，收款/付款事实登记,OMS零资金操作红线）
CREATE TABLE fin_receipt (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主ID(可后补:未识别到账挂待认领池人工认领,超15天未认领告警;认领后回填) LFK→oms_org.org_owner',
  receipt_bn        VARCHAR(32)     NOT NULL COMMENT '单号: 收款RC{YYYYMMDD}{6位序列}/付款PY{YYYYMMDD}{6位序列}',
  direction         TINYINT         NOT NULL DEFAULT 1 COMMENT '收付方向:1=收款(平台回款/银行到账),2=付款(凯淳付品牌方,结算净额场景;金蝶付款单回传/人工登记,OMS只记录事实不发起支付)',
  arrive_date       DATE            NOT NULL COMMENT '到账日期',
  amount            DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '金额(2位小数)',
  unconfirm_amount  DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '未核销余额(逐笔递减CAS,部分核销余额可继续匹配)',
  currency          CHAR(3)         NOT NULL DEFAULT 'CNY' COMMENT '币种(默认CNY,多币种P2预留)',
  channel           VARCHAR(32)     NOT NULL COMMENT '渠道: alipay=支付宝提现/jdwallet=京东钱包/douyin=抖音支付/bank=银行到账/offline=线下收款(品牌方转账,凭证必传+双人复核)',
  bank_serial_no    VARCHAR(64)     NOT NULL COMMENT '银行/平台流水号(幂等键成分,金蝶回单重复同步直接返回)',
  source            VARCHAR(16)     NOT NULL DEFAULT 'manual' COMMENT '来源: platform=平台回款/kingdee=金蝶回单同步(EF-02自动登记)/manual=人工登记/offline=线下',
  payer_name        VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '付款方名称',
  attach_ref        VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '回单/凭证附件OSS引用(线下登记必传)',
  double_check_operator VARCHAR(64) NOT NULL DEFAULT '' COMMENT '双人复核人(线下收款必录,登记≠审批)',
  shop_id           BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺ID(可后补)',
  claim_operator    VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '认领人(待认领池认领留痕)',
  claim_time        DATETIME(3)     NULL DEFAULT NULL COMMENT '认领时间',
  status            VARCHAR(16)     NOT NULL DEFAULT 'pending_match' COMMENT '状态: pending_match=待匹配/partial=部分核销/written_off=已核销/advance=挂预收(转fin_advance池语义,预收余额台账)/on_claim=待认领/over_receipt=多收待处理(退回或转预收,30天时限超期告警)',
  period            CHAR(6)         NOT NULL COMMENT '归属账期YYYYMM(结账锁定校验位,D08.03 isPeriodOpen)',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(余额扣减CAS+收款单锁)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_receipt_bn (receipt_bn),
  UNIQUE KEY uk_fin_receipt_serial (channel, bank_serial_no),
  KEY idx_fin_receipt_owner (owner_id, period),
  KEY idx_fin_receipt_status (status, period),
  KEY idx_fin_receipt_shop (shop_id, arrive_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='收付款登记(D08.03,P1)←商派ome.payments改造:+金蝶回单同步来源+待认领池+货主维度;OMS零资金操作(只登记事实)';

-- 23. 核销记录（D08.03 §6.2 · P1，三档normal/diff/force+互冲,红冲语义禁物理删除）
CREATE TABLE fin_write_off (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL COMMENT '货主ID LFK→oms_org.org_owner',
  writeoff_bn       VARCHAR(32)     NOT NULL COMMENT '核销流水号WO{YYYYMMDD}{6位序列}',
  writeoff_batch_no VARCHAR(32)     NOT NULL COMMENT '核销批次号(幂等键,自动匹配按店铺+账期分片+分布式锁)',
  writeoff_date     DATE            NOT NULL COMMENT '核销日期',
  writeoff_type     TINYINT         NOT NULL DEFAULT 1 COMMENT '核销类型(商派枚举保留+付款扩展):0=应收应退互冲(同订单正负应收对冲不动资金,跨订单禁止-审计红线),1=收款核销,2=付款核销(结算净额,凯淳付品牌方)',
  writeoff_level    VARCHAR(16)     NOT NULL COMMENT '核销档位(三档+互冲): normal=正常核销(|diff|≤0.01自动)/diff=差异核销(|diff|≤容差min(5元,0.05%)自动,差异入误差表尾额清零)/force=强制核销(超容差人工决策+OA金额分级+二次确认)/offset=应收互冲',
  receipt_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '收款/付款单ID LFK→fin_receipt(互冲类=0)',
  receivable_id     BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '应收明细ID LFK→fin_receivable(结算核销=0)',
  settle_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '结算单ID LFK→fin_settlement(结算净额核销时;回写D08.02台账已付/已收列)',
  amount            DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '行核销金额(2位小数)',
  diff_amount       DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '差异额(差异/强制档;带符号:diff<0平台少付借方损失,diff>0多收贷方挂账)',
  auto_flag         TINYINT         NOT NULL DEFAULT 1 COMMENT '自动人工标记(商派字段语义保留):0=人工,1=自动',
  operator          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '执行人(自动=system)',
  oa_ref            VARCHAR(64)     NOT NULL DEFAULT '' COMMENT 'OA引用(强制核销/反核销必填;金额分级:>1000元财务经理,>1万财务总监,货主级阈值可配)',
  second_confirm    TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '强制核销二次确认标记(商派checkVerificate确认交互语义)',
  memo              VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '摘要',
  reverse_flag      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '反核销标记:0=正常,1=反核销负向记录(红冲语义,原记录保留)',
  origin_writeoff_id BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '原核销记录ID(反核销互指追溯)',
  period            CHAR(6)         NOT NULL COMMENT '归属账期YYYYMM(分区键)',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_write_off_batch (writeoff_batch_no, receipt_id, receivable_id, settle_id),
  KEY idx_fin_write_off_bn (writeoff_bn),
  KEY idx_fin_write_off_receipt (receipt_id),
  KEY idx_fin_write_off_ar (receivable_id),
  KEY idx_fin_write_off_settle (settle_id),
  KEY idx_fin_write_off_owner (owner_id, period),
  KEY idx_fin_write_off_level (writeoff_level, period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='核销记录(D08.03,P1)←商派verification+verification_items留痕结构保留;三档留痕表不可改删;回写D08.01应收status/台账已收+D08.02台账已付已收';

-- 24. 核销关联检索表（D08.03 §6.2 · P1，流水↔单据↔订单↔平台流水号多键检索）
CREATE TABLE fin_receipt_match (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id           BIGINT UNSIGNED NOT NULL COMMENT '货主ID LFK→oms_org.org_owner',
  writeoff_id        BIGINT UNSIGNED NOT NULL COMMENT '核销记录ID LFK→fin_write_off',
  receipt_bn         VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '收/付款单号(多键检索)',
  ar_bn              VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '应收单号',
  settle_bn          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '结算单号',
  order_bn           VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '订单号 LFK→oms_order.ord_order',
  platform_serial_no VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '平台流水号(精确匹配链路:银行/平台流水号→D08.01已匹配bill_flow→应收集合)',
  bank_serial_no     VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '银行流水号',
  period             CHAR(6)         NOT NULL COMMENT '归属账期YYYYMM',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  KEY idx_fin_receipt_match_wo (writeoff_id),
  KEY idx_fin_receipt_match_receipt (receipt_bn),
  KEY idx_fin_receipt_match_ar (ar_bn),
  KEY idx_fin_receipt_match_order (order_bn),
  KEY idx_fin_receipt_match_psn (platform_serial_no),
  KEY idx_fin_receipt_match_bank (bank_serial_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='核销关联检索表(D08.03,P1)←商派bill_verification_relation多键检索能力保留';

-- 25. 核销误差表（D08.03 §6.3 · P1，差异累计+借贷方向+gap科目映射）
CREATE TABLE fin_error_table (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL COMMENT '货主ID LFK→oms_org.org_owner',
  writeoff_id     BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '来源核销记录ID LFK→fin_write_off(核销差异)',
  bill_diff_id    BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '来源账单差异ID LFK→fin_bill_diff(口径差无需处理转入,FR-07c)',
  freight_diff_id BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '来源运费差异ID LFK→fin_freight_diff(运费差异认可/坏账转入,D08.04 FR-04d)',
  source_type     VARCHAR(16)     NOT NULL DEFAULT 'writeoff' COMMENT '差异来源: writeoff=核销差异/bill_gap=账单口径差/freight=运费差异',
  diff_amount     DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '差异金额(绝对值,借贷方向语义在diff_direction,禁止无符号混算)',
  diff_direction  TINYINT         NOT NULL DEFAULT 1 COMMENT '借贷方向:1=借方(收款<应收少收,凯淳损失/费用方向),2=贷方(收款>应收多收,负债挂账方向→预收/待退)',
  gap_type        VARCHAR(32)     NOT NULL COMMENT '差异类型码(与fin_bill_diff同字典,借贷科目映射查fin_gap_account): fee_tail=平台手续费尾差/penalty=平台罚没/bad_debt=坏账核销/over_receipt=多收待退/caliber_platform=口径差异-平台承担不结算/freight_weight=运费重量差等',
  process_status  VARCHAR(16)     NOT NULL DEFAULT 'accumulating' COMMENT '处理状态: accumulating=累计中/monthly_cleaned=已月度清理(容差内尾差批量转损益,清理批次金蝶供数)/to_pl=已转损益/manual_pending=单笔超100元待人工定性',
  clean_batch_no  VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '月度清理批次号(批量转损益追溯)',
  shop_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺ID',
  period          CHAR(6)         NOT NULL COMMENT '归属账期YYYYMM(按类型×货主×期间累计)',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  KEY idx_fin_error_table_owner (owner_id, period, gap_type),
  KEY idx_fin_error_table_wo (writeoff_id),
  KEY idx_fin_error_table_status (process_status, period),
  KEY idx_fin_error_table_clean (clean_batch_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='核销误差表(D08.03,P1)←商派financebase_bill_verification_error;月度累计超阈值(默认500元货主级)告警;连续3期同类型差异输出规则优化建议';

-- 26. 会计账期与月末结账（D08.03 §6.4 · P1，期间锁定唯一裁决方）
CREATE TABLE fin_period_close (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主ID(0=全局账期,账期状态全局统一裁决,owner_id例外注明)',
  period          CHAR(6)         NOT NULL COMMENT '账期标识YYYYMM(自然月,与D08.01/D08.02周期口径对齐)',
  start_date      DATE            NOT NULL COMMENT '账期起',
  end_date        DATE            NOT NULL COMMENT '账期止',
  status          VARCHAR(16)     NOT NULL DEFAULT 'not_open' COMMENT '账期状态机(商派colse_book枚举保留): not_open=未启用/open=未关账/closed=已关账(期间锁定:全模块该期禁止补录/修改,isPeriodOpen唯一裁决位)/反结账回open',
  close_time      DATETIME(3)     NULL DEFAULT NULL COMMENT '关账时间',
  close_operator  VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '结账人(财务负责人确认;阻断项可带病结账-逐项豁免登记+理由+OA)',
  check_report    JSON            NULL DEFAULT NULL COMMENT '结账检查报告(五项:未核销清单/差异超阈值清单/结算完整性/自动核销批次完成/上月已关账顺序校验)',
  exempt_items    JSON            NULL DEFAULT NULL COMMENT '豁免登记项: [{"item":"未核销清单","reason":"...","oa_ref":"..."}](逐项理由+OA)',
  snapshot_ref    VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '结账数据快照OSS引用(汇总固化,供D08.06金蝶)',
  reopen_oa_ref   VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '反结账OA审批单(财务总监级强制审批)',
  reopen_time     DATETIME(3)     NULL DEFAULT NULL COMMENT '反结账时间(解锁→补录late_posting→重跑检查→重关账;已推金蝶联动D08.06冲销-重推顺序)',
  reopen_reason   VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '反结账原因(全程留痕)',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(关账竞态:写入事务内校验period裁决时点)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_period_close (tenant_id, period),
  KEY idx_fin_period_close_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='会计账期与月末结账(D08.03,P1)←商派monthly_report关账语义;延迟事件late_posting落当前开放账期+原属期标记';

-- ============================================================================
-- 五、运费对账族（D08.04 · P1）
-- ============================================================================

-- 27. 运费预估单（D08.04 §6.1 · P1，发货确认实时固化,模板版本快照）
CREATE TABLE fin_freight_estimate (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID LFK→oms_org.org_owner',
  delivery_id         BIGINT UNSIGNED NOT NULL COMMENT '发货单ID LFK→oms_order.ord_delivery(事件order.delivery.shipped触发,多包裹按运单号展开行)',
  delivery_bn         VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '发货单号',
  order_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '订单ID LFK→oms_order.ord_order',
  order_bn            VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '订单号',
  waybill_no          VARCHAR(64)     NOT NULL COMMENT '运单号(逐单核对匹配键,D09.05取号结果)',
  corp_id             BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '物流商ID LFK→oms_fulfill.ful_dly_corp(canonical编码)',
  product_code        VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '物流产品码 LFK→oms_fulfill.ful_dly_product',
  ship_weight         DECIMAL(10,3)   NOT NULL DEFAULT 0.000 COMMENT '出库称重kg(delivery_package,D09.02回传,3位小数)',
  bill_calc_weight    DECIMAL(10,3)   NOT NULL DEFAULT 0.000 COMMENT '账单计费重kg(月度账单核对后回填;预估口径=max(实重,体积/系数))',
  est_freight         DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '预估运费(发货单est_freight落库值,D03.07 FR-03d)',
  est_protect_fee     DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '预估保价费',
  template_version_id BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '运费模板版本ID快照 LFK→oms_fulfill.ful_freight_template_ver(D09.04 FR-05c,差异重算回放依据-用快照版本不用当前版本)',
  receiver_province   VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '收货省(线路维度差异分析:仓region→收货省)',
  receiver_city       VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '收货市',
  ship_time           DATETIME(3)     NULL DEFAULT NULL COMMENT '发货时间',
  status              VARCHAR(16)     NOT NULL DEFAULT 'unchecked' COMMENT '状态机(仅由对账批次驱动): unchecked=未对账/partial_checked=部分核对/checked=已核对/accounted=已记账(金额固化锁定)/audited=已审核/closed=已关账/voided=作废(发货单取消/运单作废联动;已记账后作废走红冲)',
  source              VARCHAR(16)     NOT NULL DEFAULT 'shipped' COMMENT '来源: shipped=发货事件(默认)/recalc=estimateFreight补算(est_freight缺失异常路径)/manual=无主账单人工认领',
  task_id             BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '对账任务ID LFK→fin_freight_task',
  shop_id             BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺ID LFK→oms_gateway.gw_shop',
  create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_freight_estimate (delivery_id, waybill_no),
  KEY idx_fin_freight_estimate_wb (waybill_no),
  KEY idx_fin_freight_estimate_owner (owner_id, status),
  KEY idx_fin_freight_estimate_task (task_id),
  KEY idx_fin_freight_estimate_order (order_bn)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='运费预估单(D08.04,P1)←商派logisticsaccounts_estimate改造:定时补算→发货事件实时固化+模板版本快照+owner_id;幂等键=delivery_id+运单号';

-- 28. 快递月度账单头（D08.04 §6.2 · P1，导入批次,解析模板配置化）
CREATE TABLE fin_freight_bill (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主ID(账单为物流商×月结账号粒度跨货主,明细认领/匹配后落行级owner;owner_id例外注明)',
  import_batch_no   VARCHAR(32)     NOT NULL COMMENT '导入批次号(唯一,D01.06异步导入10万行级)',
  corp_id           BIGINT UNSIGNED NOT NULL COMMENT '物流商ID LFK→oms_fulfill.ful_dly_corp(顺丰/通达系/京东物流)',
  settle_account    VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '月结编码(结算账号,一快递多账号独立对账)',
  bill_period       CHAR(6)         NOT NULL COMMENT '账单账期YYYYMM',
  parse_template_code VARCHAR(32)   NOT NULL DEFAULT '' COMMENT '解析模板码(快递商×账单格式粒度:列映射+费用项字典映射配置化,新快递商=新增模板零代码)',
  file_ref          VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '账单文件OSS引用(CSV/Excel,编码/表头行偏移可配)',
  total_amount      DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '账单汇总金额(勾稽基准:明细合计vs汇总行,FR-02c)',
  row_count         INT             NOT NULL DEFAULT 0 COMMENT '账单行数',
  import_status     VARCHAR(16)     NOT NULL DEFAULT 'parsing' COMMENT '导入状态: parsing=解析中/parsed=已解析/partial_failed=部分失败(错误报告不阻塞正确行)/voided=已作废(重复导入同批次拒绝)',
  coverage_gap_rate DECIMAL(9,4)    NOT NULL DEFAULT 0.0000 COMMENT '账单覆盖度缺口率(direct类月结账号取号量vs账单行数比对,>2%告警漏账疑点,D09.05 FR-08b③供数)',
  operator          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '导入人',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_freight_bill_batch (import_batch_no),
  KEY idx_fin_freight_bill_corp (corp_id, settle_account, bill_period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='快递月度账单头(D08.04,P1)←商派logisticsaccounts_actual导入批次化改造';

-- 29. 快递账单明细（D08.04 §6.2 · P1，标准化费用行,红字金额为负）
CREATE TABLE fin_freight_bill_item (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主ID(匹配预估单/认领后回填)',
  bill_id        BIGINT UNSIGNED NOT NULL COMMENT '账单头ID LFK→fin_freight_bill',
  idem_key       VARCHAR(128)    NOT NULL COMMENT '幂等键={导入批次}:{运单号}:{费用行序}(跨批次同运单号允许多行-补账/红冲行场景)',
  waybill_no     VARCHAR(64)     NOT NULL COMMENT '运单号(核对匹配键;多包裹子单号归并主单匹配)',
  calc_weight    DECIMAL(10,3)   NOT NULL DEFAULT 0.000 COMMENT '账单计费重kg(3位小数)',
  first_fee      DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '首重费(标准费用项字典映射产物,红字行金额为负)',
  add_fee        DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '续重费',
  remote_fee     DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '偏远附加费',
  protect_fee    DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '保价费',
  fuel_fee       DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '燃油附加费',
  peak_fee       DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '旺季服务费',
  other_fee      DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '其他费用',
  total_amount   DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '费用合计(=Σ费用项,行内勾稽)',
  match_status   VARCHAR(16)     NOT NULL DEFAULT 'unmatched' COMMENT '核对状态: unmatched=未核对/matched=已匹配/no_owner=无主账单(账单有OMS无,人工认领/退回核查,超30天告警)/missing=漏账疑点(OMS有账单无,挂起下期重匹配,窗口3个月,超窗转索赔/坏账)/accounted=已记账(不重核)',
  estimate_id    BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '匹配预估单ID LFK→fin_freight_estimate',
  diff_amount    DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '差异额=实际合计-预估运费-预估保价费(含正负)',
  diff_factors   JSON            NULL DEFAULT NULL COMMENT '差异因子构成: {"weight_diff":2.80,"rate_diff":0,"surcharge":0,"protect_diff":0,"other":0}(§5.1拆解,可多因并存)',
  tolerance_result TINYINT       NOT NULL DEFAULT 0 COMMENT '容差判定:0=未判定,1=容差内自动通过(±0.5元或±5%满足其一,差异额仍如实记录不抹平-账实一致),2=超容差进差异池',
  task_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '对账任务ID LFK→fin_freight_task',
  shop_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺ID',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version        INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_fbill_item_idem (idem_key),
  KEY idx_fin_fbill_item_bill (bill_id),
  KEY idx_fin_fbill_item_wb (waybill_no),
  KEY idx_fin_fbill_item_match (match_status, task_id),
  KEY idx_fin_fbill_item_owner (owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='快递账单明细-标准化费用行(D08.04,P1);费用项字典映射:各家费用名→标准费用项(首重/续重/偏远/保价/燃油/旺季/其他)';

-- 30. 运费逐单核对记录（D08.04 FR-03 · P1，预估vs实际,差异因子拆解）
CREATE TABLE fin_freight_match (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id           BIGINT UNSIGNED NOT NULL COMMENT '货主ID LFK→oms_org.org_owner',
  task_id            BIGINT UNSIGNED NOT NULL COMMENT '对账任务ID LFK→fin_freight_task',
  bill_item_id       BIGINT UNSIGNED NOT NULL COMMENT '账单明细ID LFK→fin_freight_bill_item',
  estimate_id        BIGINT UNSIGNED NOT NULL COMMENT '预估单ID LFK→fin_freight_estimate',
  waybill_no         VARCHAR(64)     NOT NULL COMMENT '运单号',
  est_amount         DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '预估合计=预估运费+预估保价费',
  actual_amount      DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '实际合计(账单行total_amount)',
  diff_amount        DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '差异额=实际-预估(带符号,2位小数)',
  main_factor        VARCHAR(16)     NOT NULL DEFAULT 'none' COMMENT '差异主因(最大绝对值因子): none=无差异(容差内)/weight=重量差(计费重>出库称重,体积重可解释=正常;超20%不可解释=疑似称重错误转索赔)/rate=费率差(计费重一致单价不符,按模板版本重算比对)/surcharge=附加费(偏远/燃油/旺季预估未含项)/protect=保价费差/other=其他(无法归因转人工)',
  weight_diff_amount DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '重量差因子金额(重算额-预估运费;重算用预估单模板版本快照+账单计费重)',
  rate_diff_amount   DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '费率差因子金额(账单基础运费-模板重算额)',
  surcharge_amount   DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '附加费因子金额(偏远+燃油+旺季+其他附加)',
  protect_diff_amount DECIMAL(18,2)  NOT NULL DEFAULT 0.00 COMMENT '保价费差因子金额',
  other_amount       DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '其他未归因金额=差异额-Σ已归因',
  tolerance_abs      DECIMAL(18,2)   NOT NULL DEFAULT 0.50 COMMENT '容差快照-绝对值(物流商×结算账号粒度,默认±0.50元)',
  tolerance_rate     DECIMAL(9,4)    NOT NULL DEFAULT 0.0500 COMMENT '容差快照-相对值(默认±5%,满足其一即通过)',
  result             VARCHAR(16)     NOT NULL DEFAULT 'pass_tolerance' COMMENT '核对结果: pass_tolerance=容差内自动通过/in_diff_pool=超容差进差异池/claim=转索赔/bad_debt=坏账登记(OA)/manual_price=转人工核价(模板疑义回流D09.04)',
  check_time         DATETIME(3)     NOT NULL COMMENT '核对时间(10万行级≤10分钟异步;重跑覆盖未记账结果)',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version            INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_freight_match (bill_item_id, estimate_id),
  KEY idx_fin_freight_match_task (task_id, result),
  KEY idx_fin_freight_match_wb (waybill_no),
  KEY idx_fin_freight_match_owner (owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='运费逐单核对记录-预估vs实际(D08.04,P1);差异因子拆解可解释+证据链快照';

-- 31. 运费差异登记与分摊（D08.04 §6.3/§6.4 · P1，一差异可拆多分摊行-订单行级）
CREATE TABLE fin_freight_diff (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL COMMENT '货主ID(随订单归属自然携带) LFK→oms_org.org_owner',
  match_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '核对记录ID LFK→fin_freight_match',
  task_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '对账任务ID LFK→fin_freight_task',
  waybill_no      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '运单号',
  diff_type       VARCHAR(16)     NOT NULL DEFAULT 'other' COMMENT '差异分类: weight=重量差/rate=费率差/surcharge=附加费争议/protect=保价差/other=其他',
  diff_amount     DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '差异金额(带符号)',
  main_factor     VARCHAR(16)     NOT NULL DEFAULT '' COMMENT '主因(同核对记录main_factor)',
  evidence        JSON            NULL DEFAULT NULL COMMENT '证据链快照: {"weight_snapshot":1.2,"bill_row":{...},"template_recalc":7.30}(称重快照+账单明细行+模板版本重算结果)',
  handle_status   VARCHAR(16)     NOT NULL DEFAULT 'pending' COMMENT '处理状态: pending=待处理/approved=认可通过(进分摊,支持同因批量认可+抽样复核)/to_claim=转索赔/bad_debt=坏账登记(小额放弃,OA审批)/manual_price=转人工核价/closed=关闭',
  handle_operator VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '处理人',
  handle_time     DATETIME(3)     NULL DEFAULT NULL COMMENT '处理时间',
  handle_remark   VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '处理说明',
  subject_debit   VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '借方科目(认可差异与坏账按fin_gap_account/fin_code_mapping借贷科目映射入账-差异不是黑洞每笔有科目去向,D08.04 FR-04d)',
  subject_credit  VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '贷方科目',
  order_bn        VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '分摊归属订单号(一单一包裹直接归属;合单母单按子单订单金额比例分摊尾差入最大子单;多包裹按包裹归属订单行)',
  order_item_id   BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '分摊归属订单行ID LFK→oms_order.ord_order_item',
  delivery_id     BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '发货单ID',
  alloc_amount    DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '分摊额(订单行级履约成本,2位小数,比例分摊尾差入最大额行总额分毫不差)',
  est_amount      DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '预估运费(双值并存:预估列/实际列,毛利报表默认取实际,§5.4)',
  actual_amount   DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '实际运费(关账数为准)',
  bearer_type     VARCHAR(16)     NOT NULL DEFAULT 'kaichun' COMMENT '承担方(配置货主×物流商粒度判定): kaichun=凯淳承担(销售费用-运费科目)/brand=品牌方承担(入D08.02结算单费用行扣收)/buyer=买家承担(入D08.01应收,订单运费收入对冲差额即履约损益)',
  period          CHAR(6)         NOT NULL COMMENT '账期YYYYMM',
  shop_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺ID',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  KEY idx_fin_freight_diff_match (match_id),
  KEY idx_fin_freight_diff_task (task_id, handle_status),
  KEY idx_fin_freight_diff_owner (owner_id, period),
  KEY idx_fin_freight_diff_order (order_bn),
  KEY idx_fin_freight_diff_wb (waybill_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='运费差异登记与分摊明细(D08.04,P1);分摊明细供D11毛利报表(订单行级收入-商品成本-运费分摊)+D08.02结算+品牌方门户';

-- 32. 运费对账任务批次（D08.04 §6.5 · P1，结算主体×账期,记账→审核→关账三阶段）
CREATE TABLE fin_freight_task (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主ID(任务=结算主体×账期粒度跨货主,明细行携带owner;owner_id例外注明)',
  task_bn          VARCHAR(32)     NOT NULL COMMENT '任务单号FT{YYYYMMDD}{6位序列}',
  corp_id          BIGINT UNSIGNED NOT NULL COMMENT '物流商ID LFK→oms_fulfill.ful_dly_corp',
  settle_account   VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '月结编码(任务键=快递公司×月结账号×账期,一快递多账号独立对账)',
  period           CHAR(6)         NOT NULL COMMENT '账期YYYYMM(同结算主体按月顺序关账,上月未关本月阻塞)',
  bill_total       DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT 'Σ账单导入金额(勾稽恒等式左端)',
  accounted_total  DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT 'Σ记账金额(通过+认可差异)',
  claim_total      DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT 'Σ待索赔金额',
  bad_debt_total   DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT 'Σ坏账金额',
  unclaimed_total  DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT 'Σ无主未认领金额(审核前需先处置:认领入账或退回核查出账)',
  diff_rate        DECIMAL(9,4)    NOT NULL DEFAULT 0.0000 COMMENT '本期差异率=差异额/账单额(审核报告;超阈值需附说明;物流商×线路粒度超20%自动生成模板校准工单回流D09.04 FR-05c)',
  status           VARCHAR(16)     NOT NULL DEFAULT 'draft' COMMENT '状态机: draft=草稿/checking=核对中/to_account=待记账/accounted=已记账(实际运费固化+应付汇总生成,明细锁定不可改)/audited=已审核(勾稽恒等式零误差门禁)/closed=已关账(运费入应付联动D08.03+供数快照固化D08.06+终态锁定)/rejected=驳回退回/red_flushed=红冲(独立授权+OA,红字冲销明细+重开新任务)',
  account_time     DATETIME(3)     NULL DEFAULT NULL COMMENT '记账时间',
  audit_operator   VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '审核人(财务主管)',
  audit_time       DATETIME(3)     NULL DEFAULT NULL COMMENT '审核时间',
  close_time       DATETIME(3)     NULL DEFAULT NULL COMMENT '关账时间(触发事件freight.task.closed)',
  reversal_task_id BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '红冲关联任务ID(原任务/红冲任务互指;红冲任务关账后解锁后续账期)',
  oa_ref           VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '红冲OA审批单引用',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_freight_task_bn (task_bn),
  UNIQUE KEY uk_fin_freight_task_key (corp_id, settle_account, period),
  KEY idx_fin_freight_task_status (status, period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='运费对账任务批次(D08.04,P1)←商派logisticsaccounts_actual_task改造:物流公司+仓库→结算主体(快递×月结账号)×账期+勾稽门禁+红冲重开';

-- 33. 运费索赔单（D08.04 §6.3 · P1，快递公司计费错误申诉闭环）
CREATE TABLE fin_freight_claim (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id     BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主ID(索赔主体多为凯淳,涉及货主差异时回填;例外注明)',
  claim_bn      VARCHAR(32)     NOT NULL COMMENT '索赔单号FC{YYYYMMDD}{6位序列}',
  corp_id       BIGINT UNSIGNED NOT NULL COMMENT '物流商ID LFK→oms_fulfill.ful_dly_corp',
  task_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '对账任务ID LFK→fin_freight_task',
  waybill_nos   JSON            NOT NULL COMMENT '争议运单号集',
  diff_ids      JSON            NULL DEFAULT NULL COMMENT '来源差异单ID集 LFK→fin_freight_diff',
  claim_type    VARCHAR(16)     NOT NULL DEFAULT 'weight_error' COMMENT '索赔类型: weight_error=称重错误/surcharge_dispute=附加费争议(如非偏远地区收偏远费)/rate_error=费率错误/other=其他',
  claim_amount  DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '争议索赔金额',
  ack_amount    DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '快递公司认可金额(回执登记)',
  evidence_refs JSON            NULL DEFAULT NULL COMMENT '证据附件引用集(地址+偏远清单截图/称重快照等,OSS加密存储)',
  status        VARCHAR(16)     NOT NULL DEFAULT 'draft' COMMENT '状态机: draft=草稿/submitted=已提交(快递公司月度申诉)/partial_ack=部分认可/ack_refund=认可退款/rejected=驳回/closed=关闭(超30天无回执升级告警;结果回写差异单闭环)',
  offset_way    VARCHAR(16)     NOT NULL DEFAULT '' COMMENT '冲抵方式: next_red=下期账单红字行自动关联冲抵/cash_refund=现金退款登记',
  submit_date   DATE            NULL DEFAULT NULL COMMENT '提交日期',
  ack_date      DATE            NULL DEFAULT NULL COMMENT '回执日期',
  period        CHAR(6)         NOT NULL COMMENT '账期YYYYMM',
  create_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version       INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_freight_claim_bn (claim_bn),
  KEY idx_fin_freight_claim_corp (corp_id, status),
  KEY idx_fin_freight_claim_task (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='运费索赔单(D08.04,P1);商派无索赔建模-凯淳新增闭环';

-- ============================================================================
-- 六、发票族（D08.05 · P1）
-- ============================================================================

-- 34. 开票申请（D08.05 §6.1 · P1，三通道入口,购方要素PIPL加密脱敏）
CREATE TABLE fin_invoice_apply (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id           BIGINT UNSIGNED NOT NULL COMMENT '货主ID LFK→oms_org.org_owner',
  order_id           BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '订单ID LFK→oms_order.ord_order',
  order_bn           VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '订单号',
  delivery_bn        VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '发货单号',
  source             VARCHAR(16)     NOT NULL COMMENT '来源三通道: order=订单发票要素(D03.01 order_invoice随order.completed自动生成)/platform=平台开票消息(D02标准化:申请/变更/撤销,原文快照)/manual=手工补开(原因结构化+独立授权)',
  manual_reason      VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '补开原因结构化: miss=漏开/element_error=要素错误重开/refund_reopen=退款后重开',
  platform_apply_no  VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '平台开票申请单号(平台消息类)',
  platform_raw       JSON            NULL DEFAULT NULL COMMENT '平台申请原文快照(审计溯源)',
  buyer_type         TINYINT         NOT NULL DEFAULT 1 COMMENT '购方抬头类型:1=个人,2=企业',
  buyer_title_enc    VARBINARY(255)  NULL DEFAULT NULL COMMENT '购方抬头密文(PIPL信封加密D01.05,界面脱敏)',
  buyer_title_mask   VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '购方抬头脱敏展示值',
  buyer_tax_no_enc   VARBINARY(255)  NULL DEFAULT NULL COMMENT '购方税号密文(15/18/20位格式校验;专票必填地址电话开户行账号)',
  buyer_tax_no_hash  CHAR(64)        NOT NULL DEFAULT '' COMMENT '购方税号盲索引HMAC(检索用,合票指纹成分)',
  buyer_addr_tel_enc VARBINARY(512)  NULL DEFAULT NULL COMMENT '购方地址电话密文(专票必填)',
  buyer_bank_enc     VARBINARY(512)  NULL DEFAULT NULL COMMENT '购方开户行账号密文(专票必填)',
  buyer_email_enc    VARBINARY(255)  NULL DEFAULT NULL COMMENT '购方邮箱密文(交付通道)',
  status             VARCHAR(16)     NOT NULL DEFAULT 'received' COMMENT '状态: received=已接收/validated=要素校验通过/to_pool=已入需求池/validate_failed=校验失败挂起待修正(客服联系买家/平台消息回询)/voided=作废(订单取消/平台撤销/未开先退,留痕)',
  validate_fail_reason VARCHAR(255)  NOT NULL DEFAULT '' COMMENT '校验失败原因(抬头类型/税号格式/专票必填项)',
  shop_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺ID LFK→oms_gateway.gw_shop',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version            INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  KEY idx_fin_invoice_apply_order (order_id, source),
  KEY idx_fin_invoice_apply_platform (platform_apply_no),
  KEY idx_fin_invoice_apply_status (status),
  KEY idx_fin_invoice_apply_taxno (buyer_tax_no_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='开票申请(D08.05,P1)←商派invoice_order_taobao平台原始申请改造;购方要素PIPL全链路加密脱敏(商派明文存储)';

-- 35. 预发票需求池（D08.05 §6.1 · P1，应开未开清单,应开金额动态维护）
CREATE TABLE fin_invoice_pool (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID LFK→oms_org.org_owner',
  demand_bn           VARCHAR(32)     NOT NULL COMMENT '需求单号ID{YYYYMMDD}{6位序列}',
  apply_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '开票申请ID LFK→fin_invoice_apply',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '订单ID LFK→oms_order.ord_order',
  order_bn            VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '订单号',
  source              VARCHAR(16)     NOT NULL DEFAULT 'order' COMMENT '来源(同申请表): order/platform/manual',
  demand_amount       DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '应开金额=客户实付口径(D08.01双口径契约)-累计已退+运费收入行(店铺配置)-平台优惠扣减特例(D02适配器标准化,京东类优惠当支付金额使用);入池初算,退款成功事件重算;为0自动作废不产生0元票',
  refunded_amount     DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '累计已退金额(D05.03退款台账)',
  issuer_id           BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '销方主体ID(fin_invoice_channel.issuer_json内主体;归属规则=货主类型×业务类型映射:买断→凯淳/代销→品牌方或凯淳代收代开【待业务确认】)',
  condition_type      TINYINT         NOT NULL DEFAULT 3 COMMENT '开票条件(店铺级配置,商派order_setting操作条件语义):1=已发货,2=已付款,3=已完成;有平台时限按更早者',
  condition_met_time  DATETIME(3)     NULL DEFAULT NULL COMMENT '条件满足时间(进批量开票队列)',
  platform_deadline   DATETIME(3)     NULL DEFAULT NULL COMMENT '平台开票时限(如抖音48h,优先排队依据,临近预警)',
  merge_fingerprint   CHAR(64)        NOT NULL DEFAULT '' COMMENT '合票指纹=hash(购方税号+销方主体+店铺[+配置维度])(§5.2)',
  merge_group_id      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '合票组ID(同指纹归组;窗口默认自然月;窗口内成员单退款→移出合票组独立处理防整票冲红牵连)',
  status              VARCHAR(16)     NOT NULL DEFAULT 'pending' COMMENT '需求池状态机: pending=待开票/fix_pending=待修正(要素校验失败)/issuing=开票中/issued=已开票/voided=作废',
  issue_round         INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '开票轮次(幂等键=需求单ID+轮次,重试不重复出票,服务商流水号双保险)',
  invoice_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '开票成功发票ID LFK→fin_invoice',
  config_snapshot     JSON            NULL DEFAULT NULL COMMENT '开票配置快照(下单时点店铺×销方配置固化:开票内容/税率/含税标志/渠道/操作条件;配置变更未来生效,历史需求按快照执行)',
  platform_raw_ref    VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '平台申请原文快照引用',
  shop_id             BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺ID',
  period              CHAR(6)         NOT NULL DEFAULT '' COMMENT '归属账期YYYYMM',
  create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_invoice_pool_bn (demand_bn),
  UNIQUE KEY uk_fin_invoice_pool_order (order_id, source),
  KEY idx_fin_invoice_pool_status (status, condition_type),
  KEY idx_fin_invoice_pool_merge (merge_group_id),
  KEY idx_fin_invoice_pool_owner (owner_id, period),
  KEY idx_fin_invoice_pool_deadline (platform_deadline)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='预发票需求池-应开未开(D08.05,P1)←商派invoice_order_front模式保留;开票金额口径显式绑定D08.01客户实付双口径';

-- 36. 发票台账（D08.05 §6.2 · P1，蓝/红票全生命周期,OMS业务台账vs金蝶税务发票两边对账）
CREATE TABLE fin_invoice (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NOT NULL COMMENT '货主ID LFK→oms_org.org_owner',
  invoice_code     VARCHAR(32)     NOT NULL COMMENT '发票代码(台账业务主键成分;与金蝶对账键=代码+号码,§5.5边界)',
  invoice_no       VARCHAR(32)     NOT NULL COMMENT '发票号码',
  invoice_type     VARCHAR(16)     NOT NULL DEFAULT 'e_general' COMMENT '票种: e_general=电子普票/e_special=电子专票/paper=纸质普票(登记类)/external=外部开票(品牌方直开备查:不入OMS开票执行,只记票号/金额/影像引用)',
  color            TINYINT         NOT NULL DEFAULT 1 COMMENT '蓝红标识:1=蓝票,2=红票(红票金额负数,关联原蓝票)',
  origin_invoice_id BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '红票关联原蓝票ID(冲红/部分冲红追溯)',
  exchange_group_no VARCHAR(32)    NOT NULL DEFAULT '' COMMENT '换开组号(三票关联链:原蓝票↔红票↔新蓝票互指,审计可溯;换开=冲红+重开原子编排,冲红失败不出半程票,红票悬空告警)',
  issuer_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '销方主体ID(fin_invoice_channel.issuer_json)',
  issuer_type      TINYINT         NOT NULL DEFAULT 1 COMMENT '销方主体类型:1=凯淳,2=品牌方(按货主/业务类型决定)',
  issuer_name      VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '销方名称快照',
  issuer_tax_no    VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '销方纳税人识别号快照',
  buyer_info_enc   VARBINARY(512)  NULL DEFAULT NULL COMMENT '购方信息密文(抬头/税号/地址电话/开户行,PIPL加密,明文查看独立授权+审计)',
  buyer_tax_no_hash CHAR(64)       NOT NULL DEFAULT '' COMMENT '购方税号盲索引(检索/对账用)',
  amount           DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '金额(不含税,红票负数)',
  tax_amount       DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '税额',
  total_amount     DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '价税合计(Σ明细行=票面勾稽强制;合票Σ成员需求应开金额=票面,不等拒绝合开)',
  tax_rate         DECIMAL(9,4)    NOT NULL DEFAULT 0.0000 COMMENT '主税率(百分数值如13.0000;明细行各自税率见detail_json)',
  invoice_date     DATE            NOT NULL COMMENT '开票日期',
  channel_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '开票渠道ID LFK→fin_invoice_channel',
  channel_serial_no VARCHAR(64)    NOT NULL DEFAULT '' COMMENT '服务商流水号(幂等双保险核对)',
  pdf_ref          VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '版式文件PDF引用(加密存储,下载留痕)',
  ofd_ref          VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '版式文件OFD引用',
  status           VARCHAR(16)     NOT NULL DEFAULT 'issued' COMMENT '台账状态: issued=已开票/partial_red=部分冲红(+余额)/red_flushed=已冲红/voided=作废',
  issue_round      INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '开票/冲红轮次(幂等键成分)',
  demand_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '需求单ID LFK→fin_invoice_pool',
  order_bns        JSON            NULL DEFAULT NULL COMMENT '订单映射集(合票多单:["O2026...","O2026..."];行级映射见fin_invoice_merge)',
  detail_json      JSON            NULL DEFAULT NULL COMMENT '发票明细行: [{"goods_name":"...","spec":"...","num":1,"price":0.0000,"amount":0.00,"tax_rate":13.0000,"tax_code":"税收分类编码(D04.01物料属性)","order_item_ref":0}](优惠分摊后Σ行=开票金额尾差入最大行;运费独立行[税收分类=运输服务,待确认类目];明细行超服务商上限默认8行自动拆票组)',
  sync_status_raw  VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '渠道原始状态留痕(商派10态:0未同步/1开蓝中/2开蓝失败/3开蓝成功/4冲红中/5冲红失败/6冲红成功/7冲红确认中/8冲红确认失败/9冲红确认成功/10金税三期冲红;业务状态机收敛四态,原始态渠道日志留痕§5.4)',
  shop_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺ID',
  period           CHAR(6)         NOT NULL DEFAULT '' COMMENT '归属账期YYYYMM(月度快照供D08.06)',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_invoice_code_no (invoice_code, invoice_no, issue_round),
  KEY idx_fin_invoice_origin (origin_invoice_id),
  KEY idx_fin_invoice_exchange (exchange_group_no),
  KEY idx_fin_invoice_demand (demand_id),
  KEY idx_fin_invoice_owner (owner_id, period),
  KEY idx_fin_invoice_shop (shop_id, invoice_date),
  KEY idx_fin_invoice_status (status),
  KEY idx_fin_invoice_taxno (buyer_tax_no_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='发票台账-蓝红票全生命周期(D08.05,P1)←商派invoice_order/order_items改造;OMS记业务台账,金蝶记税务发票,按代码+号码逐票对账(双源并存差异显式化)';

-- 37. 发票冲红/换开单（D08.05 §6.3 · P1，业务四态状态机收敛）
CREATE TABLE fin_invoice_red (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL COMMENT '货主ID LFK→oms_org.org_owner',
  origin_invoice_id BIGINT UNSIGNED NOT NULL COMMENT '原蓝票ID LFK→fin_invoice',
  red_invoice_id    BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '冲红成功红票ID LFK→fin_invoice(回执落库回填)',
  new_invoice_id    BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '换开新蓝票ID LFK→fin_invoice(换开编排:冲红成功→自动创建重开需求→新蓝票关联;重开失败进异常队列红票必须重开闭环不允许悬空)',
  trigger_type      VARCHAR(16)     NOT NULL COMMENT '冲红触发: refund=退款成功事件(全额自动冲红申请;部分按配置全额冲红重开或部分红冲【待确认服务商支持度】)/exchange=要素错误换开/cancel=订单取消(已开票)/manual=财务人工发起(独立授权+原因必填+大额批量OA)',
  refund_bn         VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '关联退款单号 LFK→oms_aftersale.aft_refund',
  red_round         INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '冲红轮次(幂等键=原蓝票号+轮次,重试不重复出红票)',
  status            VARCHAR(16)     NOT NULL DEFAULT 'applying' COMMENT '业务状态机(商派10同步状态收敛四态): applying=申请中(可财务确认或配置自动)/red_issuing=冲红中(渠道受理;跨月购方确认流程适配器内消化,等待+超时告警默认7天)/red_done=已冲红(红票台账落库+原蓝票状态联动+事件invoice.red_issued广播D08.01应收冲减核对)/failed=失败(可重试新轮次或转线下)/offline_register=线下登记(人工闭环)',
  fail_reason       VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '失败原因(服务商原始码留痕渠道日志)',
  fail_code         VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '服务商失败码',
  confirm_deadline  DATETIME(3)     NULL DEFAULT NULL COMMENT '跨月冲红购方确认超时时限(默认7天,超时告警)',
  new_buyer_info_enc VARBINARY(512) NULL DEFAULT NULL COMMENT '换开新购方要素密文(PIPL)',
  diff_snapshot     JSON            NULL DEFAULT NULL COMMENT '新旧要素差异快照(换开留痕)',
  oa_ref            VARCHAR(64)     NOT NULL DEFAULT '' COMMENT 'OA审批单(人工发起/大额批量)',
  shop_id           BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺ID',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_invoice_red (origin_invoice_id, red_round),
  KEY idx_fin_invoice_red_status (status),
  KEY idx_fin_invoice_red_refund (refund_bn),
  KEY idx_fin_invoice_red_new (new_invoice_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='发票冲红/换开单(D08.05,P1);渠道调用留痕(action/request/response/raw_status/error_class/retry_count)见渠道日志-本表收敛业务状态,原始报文OSS留痕3年';

-- 38. 发票合票拆票映射（D08.05 §6.2/FR-05 · P1，发票行↔订单行映射保留）
CREATE TABLE fin_invoice_merge (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NOT NULL COMMENT '货主ID LFK→oms_org.org_owner',
  invoice_id     BIGINT UNSIGNED NOT NULL COMMENT '发票ID LFK→fin_invoice',
  demand_id      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '需求单ID LFK→fin_invoice_pool(合票多单:一票N需求)',
  order_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '订单ID LFK→oms_order.ord_order',
  order_bn       VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '订单号',
  order_item_id  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '订单行ID(行级映射,0=整单级;商派order_items合票原发票id/明细ID语义保留)',
  merge_group_id BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '合票组ID(合票映射;合票冲红按映射整票处理)',
  split_group_no VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '拆票组号(拆票场景:①不同销方主体强制分票-一单多货主合单发货;②明细行超服务商上限默认8行自动拆多票,票组关联每票独立台账+映射)',
  alloc_amount   DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '本映射行分摊开票金额(Σ行=票面,分摊尾差入最大行)',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  KEY idx_fin_invoice_merge_inv (invoice_id),
  KEY idx_fin_invoice_merge_demand (demand_id),
  KEY idx_fin_invoice_merge_order (order_id, order_item_id),
  KEY idx_fin_invoice_merge_group (merge_group_id),
  KEY idx_fin_invoice_merge_split (split_group_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='发票合票拆票映射(D08.05,P1);发票行↔订单行映射可溯,金蝶对账与冲红牵连判定依据';

-- ============================================================================
-- 七、金蝶集成族（D08.06 · P1）
-- ============================================================================

-- 39. 金蝶供数任务（D08.06 §6.1 · P1，七类数据契约:内容/格式/频率/口径与通道解耦）
CREATE TABLE fin_kingdee_supply (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主ID(供数任务为类别×期间粒度跨货主,明细数据行携带owner;owner_id例外注明)',
  feed_type        TINYINT         NOT NULL COMMENT '供数类别(七类数据契约): 1=销售明细(D08.01应收+D03订单行+D04.07成本结转,订单行级,日增量+月全量,双口径分列)/2=退款明细(D05.03退款台账+D08.01应退,退款单行级,日增量+月全量,双口径冲减+分摊回冲)/3=结算单(D08.02,货主×周期汇总+明细引用,月-结算周期关账后)/4=采购入库与应付(D06.04应付单+供应商台账,单据级+台账汇总,月-结账期,含税口径与D04.07§5.3全局一致)/5=运费实际(D08.04关账任务getPayable,关账汇总+运单明细,月-关账后,仅关账数据)/6=发票台账(D08.05蓝红换开链,发票级+明细行,月快照,业务口径声明)/7=存货余额与出入库成本(D04.07日终量价双快照+D04.02数量快照,三元行仓×SKU×货主,日快照+月汇总,买断/代销分文件)',
  period           CHAR(6)         NOT NULL COMMENT '供数期间YYYYMM',
  channel          VARCHAR(16)     NOT NULL DEFAULT 'file' COMMENT '投递通道: file=文件交换(首期)/api=API推送(预留)/mid_table=中间表(预留,金蝶侧中间库表写入【待确认规范】);类别粒度可灰度切换,通道切换不改数据契约与对账逻辑',
  feed_version     INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '文件版本(重出=新版本,旧版作废留痕;幂等键=类别+期间+版本)',
  trigger_type     VARCHAR(16)     NOT NULL DEFAULT 'schedule' COMMENT '触发: schedule=调度(日/月/结账期)/close_event=关账事件驱动(freight.task.closed/D08.03关账)/manual=手动重出',
  adapter_code     VARCHAR(32)     NOT NULL DEFAULT 'FILE' COMMENT '适配器码 LFK→fin_kingdee_adapter(FILE/K3/EAS/CLOUD_STAR)',
  template_version VARCHAR(16)     NOT NULL DEFAULT 'v1' COMMENT '模板版本(口径变更只未来生效,历史期间按旧模板版本重出字段一致-回放验证)',
  mapping_version  INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '编码映射版本快照(固化,历史文件可回放当时映射)',
  status           VARCHAR(16)     NOT NULL DEFAULT 'to_gen' COMMENT '任务状态机: to_gen=待生成/generated=已生成(快照固化)/delivered=已投递/receipt_closed=回执闭环/failed_regen=失败重出',
  row_count        INT             NOT NULL DEFAULT 0 COMMENT '供数快照-行数(不可变,对账OMS侧基准)',
  amount_sum       DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '供数快照-金额合计(尾行汇总行与快照指纹勾稽,不平即任务失败)',
  md5              CHAR(32)        NOT NULL DEFAULT '' COMMENT '供数快照-MD5指纹(金蝶拿到的到底是哪版数-审计可回放)',
  mapping_missing_count INT        NOT NULL DEFAULT 0 COMMENT '映射缺失行数(前置检查:缺失清单→主数据补维护;按类别策略含缺失标记/剔除行;补全后增量重出)',
  gen_time         DATETIME(3)     NULL DEFAULT NULL COMMENT '生成时间(结账日+1早8点前七类就绪SLA)',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_kingdee_supply (feed_type, period, feed_version),
  KEY idx_fin_kingdee_supply_status (status, period),
  KEY idx_fin_kingdee_supply_channel (channel, feed_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='金蝶供数任务(D08.06,P1);契约三层解耦:数据层(七类字段口径粒度频率)→载体层(CSV/Excel模板=中间表DDL=API报文schema同源定义)→通道层(file/api/mid_table)';

-- 40. 供数文件记录（D08.06 FR-02 · P1，文件版本链+红冲重出REV）
CREATE TABLE fin_kingdee_supply_file (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主ID(随任务,例外同fin_kingdee_supply)',
  supply_id       BIGINT UNSIGNED NOT NULL COMMENT '供数任务ID LFK→fin_kingdee_supply',
  file_name       VARCHAR(128)    NOT NULL COMMENT '文件名KD_{类别}_{期间}_{版本}.{ext}(红冲文件_REV_标识,如KD_SALES_202609_REV_v3.csv)',
  file_type       VARCHAR(16)     NOT NULL DEFAULT 'normal' COMMENT '文件类型: normal=正常/rev=红冲(负数金额行+origin_file引用列)/correct=更正全量',
  origin_file_id  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '红冲原文件ID(版本链v1→v2重出→REV红冲→v3更正全程留痕不可删)',
  file_ref        VARCHAR(255)    NOT NULL COMMENT '文件OSS引用(共享目录投递,金蝶侧财务下载/定时脚本拉取)',
  row_count       INT             NOT NULL DEFAULT 0 COMMENT '文件行数',
  amount_sum      DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '文件金额合计(红字为负)',
  md5             CHAR(32)        NOT NULL DEFAULT '' COMMENT '文件MD5指纹',
  encrypt_flag    TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '敏感文件加密:0=否,1=是(密码另通道送达)',
  deliver_time    DATETIME(3)     NULL DEFAULT NULL COMMENT '投递时间',
  link_expire_time DATETIME(3)    NULL DEFAULT NULL COMMENT '下载链接时效(过期不可下载,访问留痕)',
  notify_flag     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '投递通知已发:0=否,1=是(D01.07企微:文件就绪+指纹+时效链接)',
  rev_oa_ref      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '红冲重出OA审批单(FR-02d:OA审批+独立授权;重出后对账工作台核对状态重置)',
  status          VARCHAR(16)     NOT NULL DEFAULT 'generated' COMMENT '状态: generated=已生成/delivered=已投递/voided=已作废(重出/红冲后旧版作废留痕)',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  KEY idx_fin_kd_file_supply (supply_id, status),
  KEY idx_fin_kd_file_origin (origin_file_id),
  KEY idx_fin_kd_file_name (file_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='金蝶供数文件记录(D08.06,P1);文件版本与红冲重出机制对齐D08.04 FR-05e/D08.03红冲口径';

-- 41. 金蝶导入回执（D08.06 §6.1 · P1，回执勾稽快照+超时催办）
CREATE TABLE fin_kingdee_receipt (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主ID(随任务,例外注明)',
  supply_id      BIGINT UNSIGNED NOT NULL COMMENT '供数任务ID LFK→fin_kingdee_supply',
  file_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '供数文件ID LFK→fin_kingdee_supply_file',
  succ_rows      INT             NOT NULL DEFAULT 0 COMMENT '成功行数(勾稽:succ+fail=row_count,不平拒绝登记+告警)',
  fail_rows      INT             NOT NULL DEFAULT 0 COMMENT '失败行数',
  fail_rows_json JSON            NULL DEFAULT NULL COMMENT '失败行清单(原因分类:映射缺失/校验失败/金蝶侧异常)',
  voucher_nos    JSON            NULL DEFAULT NULL COMMENT '金蝶凭证号集(入账凭据引用)',
  kd_period      CHAR(6)         NOT NULL DEFAULT '' COMMENT '金蝶入账期间',
  receipt_source VARCHAR(16)     NOT NULL DEFAULT 'manual' COMMENT '回执来源: manual=人工登记/script=脚本回传/api=API同步应答(通道切换后替代人工回填)',
  receipt_time   DATETIME(3)     NULL DEFAULT NULL COMMENT '回执时间(超时默认3个工作日催办告警)',
  receipt_by     VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '回执登记人',
  check_result   TINYINT         NOT NULL DEFAULT 0 COMMENT '勾稽结果:0=待勾稽,1=勾稽通过(回执与供数快照一致),2=勾稽不平(拒绝+告警)',
  timeout_alert  TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '超时催办标记:0=未催,1=已催办',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version        INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(回执重复登记拒绝)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_kingdee_receipt_supply (supply_id),
  KEY idx_fin_kingdee_receipt_time (receipt_time, check_result)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='金蝶导入回执(D08.06,P1);回执登记闭环=供数任务终态';

-- 42. OMS-金蝶双向对账（D08.06 §6.2 · P1，多行模型:汇总卡片行+单据/流水钻取行四级）
CREATE TABLE fin_kingdee_recon (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主ID(汇总行=0;单据/流水行回填归属货主)',
  feed_type         TINYINT         NOT NULL COMMENT '供数类别(1-7,同fin_kingdee_supply)',
  period            CHAR(6)         NOT NULL COMMENT '对账期间YYYYMM',
  recon_level       VARCHAR(16)     NOT NULL DEFAULT 'summary' COMMENT '钻取层级(四级): summary=类别×期间汇总卡片行/bill=单据级行(差异分解到订单/退款单/结算单/应付单/运费任务/发票/三元行)/flow=流水级行(应收流水/成本流水cost_change_log/核销记录/D08.04差异处理记录,末层定位具体流水行)',
  parent_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '父行ID(自关联:summary→bill→flow,钻取路径全程带上下文,差异额随层收敛)',
  oms_amount        DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT 'OMS侧金额(供数快照汇总,取净版本=含红冲净额)',
  oms_rows          INT             NOT NULL DEFAULT 0 COMMENT 'OMS侧行数',
  kd_amount         DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '金蝶侧金额(导入回执入账金额⊕科目发生额回流登记;回流数据只作对账基准不落OMS业务账)',
  kd_rows           INT             NOT NULL DEFAULT 0 COMMENT '金蝶侧行数',
  diff_amount       DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '差异额=OMS-金蝶(带符号)',
  bill_ref          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '单据引用(bill级:单据号;两边都有金额不符/OMS有金蝶无/金蝶有OMS无三类)',
  flow_ref          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '流水引用(flow级:流水号)',
  time_diff_flag    TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '时间性差异候选标记(期末±3天单据自动标记跨期疑点)',
  reason_type       VARCHAR(16)     NOT NULL DEFAULT '' COMMENT '差异原因分类: timing=时间性差异(跨期,自动挂下期核对验证,下期平自动闭环)/mapping=映射差异(科目/编码错)/caliber=口径差异(含税/暂估/双口径理解)/missing_supply=漏供(文件缺行)/kd_adjust=金蝶侧调整(人工凭证)/other=其他',
  reason_desc       VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '原因说明(登记要素:原因+说明+责任人+预计闭环期)',
  owner_user        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '责任人',
  expect_close_date DATE            NULL DEFAULT NULL COMMENT '预计闭环期(超期未闭环升级告警)',
  auto_verify_period CHAR(6)        NOT NULL DEFAULT '' COMMENT '时间性差异挂下期自动验证期间',
  ticket_status     VARCHAR(16)     NOT NULL DEFAULT '' COMMENT '闭环工单状态: to_handle=待处理/handling=处理中(指派)/to_review=待复核/closed=已关闭(闭环证据:补供文件版本/金蝶调整凭证号/说明附件)',
  evidence_refs     JSON            NULL DEFAULT NULL COMMENT '闭环证据引用集',
  assignee          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '工单指派人',
  handle_log        JSON            NULL DEFAULT NULL COMMENT '工单处理日志',
  status            VARCHAR(16)     NOT NULL DEFAULT 'unchecked' COMMENT '核对状态: unchecked=未核对/balanced=核对平(金额与行数勾稽平)/diff_pending=差异待处理/diff_closed=差异已闭环/regen_recheck=重出待核对(红冲重出后状态重置)',
  check_time        DATETIME(3)     NULL DEFAULT NULL COMMENT '核对时间',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_fin_kd_recon_summary (feed_type, period, recon_level, bill_ref, flow_ref),
  KEY idx_fin_kd_recon_parent (parent_id),
  KEY idx_fin_kd_recon_status (status, period),
  KEY idx_fin_kd_recon_ticket (ticket_status, expect_close_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='OMS-金蝶双向对账(D08.06,P1);排查核对工作台数据底座:类别→期间→单据→流水四级钻取+差异原因登记+闭环工单+月度结账前置检查(六项门禁)输入';

-- ============================================================================
-- 八、初始字典数据 INSERT
-- ============================================================================

-- 8.1 财务域通用字典: 结算周期 / 服务费类型 / 金蝶供数类别 / 差异类型 / 扣费类型 / 核销档位 / 票种
INSERT INTO fin_dict (tenant_id, dict_type, dict_code, dict_name, sort_no, ext_json) VALUES
(1, 'settle_cycle', 'monthly', '月结', 1, '{"anchor":"month_end"}'),
(1, 'settle_cycle', 'semi_monthly', '半月结', 2, '{"anchor":"15+month_end"}'),
(1, 'settle_cycle', 'weekly', '周结', 3, '{"anchor":"week_sun"}'),
(1, 'service_fee_type', 'ratio', '销售额比例', 1, '{"formula":"基数×rate"}'),
(1, 'service_fee_type', 'fixed', '固定金额', 2, '{"formula":"周期固定费F"}'),
(1, 'service_fee_type', 'ladder', '阶梯费率', 3, '{"formula":"Σ档位min(max(基数-下限,0),上限-下限)×档费率,周期累计落档"}'),
(1, 'service_fee_type', 'guarantee_combo', '保底组合', 4, '{"formula":"max(F,基数×rate)"}'),
(1, 'feed_type', '1', '销售明细', 1, '{"source":"D08.01应收+D03订单行+D04.07成本结转","granularity":"订单行级","freq":"日增量+月全量","caliber":"双口径金额分列"}'),
(1, 'feed_type', '2', '退款明细', 2, '{"source":"D05.03退款台账+D08.01应退","granularity":"退款单行级","freq":"日增量+月全量","caliber":"双口径冲减+分摊回冲"}'),
(1, 'feed_type', '3', '结算单', 3, '{"source":"D08.02","granularity":"货主×周期汇总+明细引用","freq":"月(结算周期关账后)","caliber":"服务费/佣金计算结果,货主分账"}'),
(1, 'feed_type', '4', '采购入库与应付', 4, '{"source":"D06.04","granularity":"单据级+台账汇总","freq":"月(结账期)","caliber":"含税口径与D04.07§5.3全局一致,暂估/价差回冲标记"}'),
(1, 'feed_type', '5', '运费实际', 5, '{"source":"D08.04关账任务","granularity":"关账汇总+运单明细","freq":"月(关账后)","caliber":"仅关账数据,承担方/科目映射,索赔坏账单列"}'),
(1, 'feed_type', '6', '发票台账', 6, '{"source":"D08.05","granularity":"发票级+明细行","freq":"月快照","caliber":"业务口径声明,金蝶税务为权威源"}'),
(1, 'feed_type', '7', '存货余额与出入库成本', 7, '{"source":"D04.07日终量价双快照+D04.02","granularity":"三元行(仓×SKU×货主)","freq":"日快照+月汇总","caliber":"买断/代销分文件"}'),
(1, 'gap_type', 'caliber_platform', '口径差异-平台承担不结算', 1, NULL),
(1, 'gap_type', 'refund_timing', '退款时序差', 2, NULL),
(1, 'gap_type', 'fee_unsplit', '平台扣费未拆', 3, NULL),
(1, 'gap_type', 'less_settle', '金额不符-平台少结', 4, NULL),
(1, 'gap_type', 'oms_error', '金额不符-OMS错记', 5, NULL),
(1, 'gap_type', 'single_platform', '单边-平台侧', 6, NULL),
(1, 'gap_type', 'single_oms', '单边-OMS侧', 7, NULL),
(1, 'gap_type', 'fee_tail', '平台手续费尾差', 8, NULL),
(1, 'gap_type', 'penalty', '平台罚没', 9, NULL),
(1, 'gap_type', 'bad_debt', '坏账核销', 10, NULL),
(1, 'gap_type', 'over_receipt', '多收待退', 11, NULL),
(1, 'gap_type', 'freight_weight', '运费重量差', 12, NULL),
(1, 'gap_type', 'other', '其他', 99, NULL),
(1, 'fee_type', 'goods', '货款', 1, NULL),
(1, 'fee_type', 'commission', '佣金', 2, NULL),
(1, 'fee_type', 'tech_service', '技术服务费', 3, NULL),
(1, 'fee_type', 'promotion', '推广费', 4, NULL),
(1, 'fee_type', 'freight_insurance', '运费险', 5, NULL),
(1, 'fee_type', 'storage', '仓储费', 6, NULL),
(1, 'fee_type', 'refund', '退款', 7, NULL),
(1, 'fee_type', 'other', '其他', 99, NULL),
(1, 'writeoff_level', 'normal', '正常核销', 1, '{"rule":"|diff|≤0.01自动"}'),
(1, 'writeoff_level', 'diff', '差异核销', 2, '{"rule":"0.01<|diff|≤容差min(5元,0.05%)自动,差异入误差表尾额清零"}'),
(1, 'writeoff_level', 'force', '强制核销', 3, '{"rule":"|diff|>容差,人工决策+OA金额分级+二次确认"}'),
(1, 'writeoff_level', 'offset', '应收互冲', 4, '{"rule":"同订单正负应收对冲不动资金,跨订单禁止"}'),
(1, 'invoice_type', 'e_general', '电子普票', 1, NULL),
(1, 'invoice_type', 'e_special', '电子专票', 2, NULL),
(1, 'invoice_type', 'paper', '纸质普票(登记类)', 3, NULL),
(1, 'invoice_type', 'external', '外部开票(品牌方直开备查)', 4, NULL);

-- 8.2 gap 差异借贷科目映射样例（金蝶科目编码为样例值,实施时按金蝶科目表配置,变更OA备案）
INSERT INTO fin_gap_account (tenant_id, owner_id, gap_type, gap_name, debit_account, credit_account, auto_clean_threshold, alert_threshold, need_handle) VALUES
(1, 0, 'caliber_platform', '口径差异-平台承担不结算', '6601.02', '1122.02', 100.00, 500.00, 0),
(1, 0, 'refund_timing', '退款时序差', '', '', 100.00, 500.00, 1),
(1, 0, 'less_settle', '平台少结-确认损失', '6301.01', '1122.01', 100.00, 500.00, 1),
(1, 0, 'oms_error', 'OMS错记-调整', '1122.01', '1122.01', 100.00, 500.00, 1),
(1, 0, 'fee_tail', '平台手续费尾差', '6603.01', '1122.01', 100.00, 500.00, 1),
(1, 0, 'penalty', '平台罚没', '6301.02', '1122.01', 100.00, 500.00, 1),
(1, 0, 'bad_debt', '坏账核销', '6701.01', '1122.01', 100.00, 500.00, 1),
(1, 0, 'over_receipt', '多收待退', '1002.01', '2203.01', 100.00, 500.00, 1),
(1, 0, 'freight_weight', '运费重量差-认可', '6601.05', '2202.03', 100.00, 500.00, 1);

-- 8.3 电子发票渠道（诺诺/百旺/航信/平台代开,适配器可插拔,新增服务商=注册新适配器）
INSERT INTO fin_invoice_channel (tenant_id, channel_code, channel_name, adapter_class, issuer_json, status) VALUES
(1, 'nuonuo', '诺诺电子发票', 'NuonuoInvoiceAdapter', '[{"issuer_id":1,"issuer_name":"凯淳(主体样例)","tax_no":"91310000SAMPLE01","addr_tel":"","bank_account":""}]', 1),
(1, 'baiwang', '百旺电子发票', 'BaiwangInvoiceAdapter', NULL, 2),
(1, 'hangxin', '航信电子发票', 'HangxinInvoiceAdapter', NULL, 2),
(1, 'platform_proxy', '平台代开(经D02.01出口)', 'PlatformProxyInvoiceAdapter', NULL, 2);

-- 8.4 金蝶适配器占位（FILE首期启用;K3/EAS/云星空占位【待确认金蝶版本与接口】,确认哪个版本即实施哪个）
INSERT INTO fin_kingdee_adapter (tenant_id, adapter_code, adapter_name, channel_type, support_actions, impl_class, status) VALUES
(1, 'FILE', '文件交换通道(首期)', 'file', '{"deliver":1,"receipt":1,"reverse":1,"queryBalance":0,"writeBackStatus":0}', 'FileExchangeAdapter', 1),
(1, 'K3', '金蝶K3适配器(占位)', 'api', '{"deliver":0,"receipt":0,"reverse":0,"queryBalance":0,"writeBackStatus":0}', 'KingdeeK3Adapter', 0),
(1, 'EAS', '金蝶EAS适配器(占位)', 'api', '{"deliver":0,"receipt":0,"reverse":0,"queryBalance":0,"writeBackStatus":0}', 'KingdeeEasAdapter', 0),
(1, 'CLOUD_STAR', '金蝶云星空WebAPI适配器(占位)', 'api', '{"deliver":0,"receipt":0,"reverse":0,"queryBalance":0,"writeBackStatus":0}', 'KingdeeCloudAdapter', 0);

-- 8.5 全局默认结算周期配置（owner_id=0全局默认:月结+自然月末+宽限3天+确认期限10天+客户实付口径）
INSERT INTO fin_settle_config (tenant_id, owner_id, cycle_type, anchor_day, grace_days, confirm_deadline_days, settle_caliber, platform_in_settle, effect_from, status) VALUES
(1, 0, 'monthly', 'month_end', 3, 10, 'paid', 0, '2026-01-01', 1);

-- 8.6 全局默认账期配置样例（owner_id=0全局默认:账期30天+容差5元/0.05%+坏账180天）
INSERT INTO fin_credit_period (tenant_id, owner_id, credit_days, start_anchor, overdue_alert_days, tolerance_abs, tolerance_rate, bad_debt_days, effective_time, status) VALUES
(1, 0, 30, 'archive_date', 3, 5.00, 0.0005, 180, '2026-01-01 00:00:00.000', 1);

-- ============================================================================
-- 脚本结束: oms_finance 共 42 张表（应收账单族9 + 结算族4 + 核销族5 + 运费族7 + 发票族5 + 金蝶族4 + 字典配置8）
-- ============================================================================
