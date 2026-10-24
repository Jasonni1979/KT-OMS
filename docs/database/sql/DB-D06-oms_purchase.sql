-- ============================================================================
-- DB-D06 采购域建表脚本（oms_purchase）
-- 文档编号: DB-D06 · 版本 V1.0 · 2026-10-24 · MySQL 8.0 可执行 DDL
-- 上游契约: DB-00 数据库设计总册（schema=oms_purchase / 表前缀 pur_ / 公共字段 / 不建物理外键）
-- 需求依据: SRS-D06.01 ~ SRS-D06.04 §6 数据字段章节（D06.01/02/03=P0，D06.04=P1）
-- 关联契约: DB-D04 库存域（采购入库联动 inv_io_bill、在途联动 inv_stock_ledger.arrive_store、
--           成本联动 inv_estimate_batch/inv_cost_change_log）——跨域均为逻辑外键 LFK
-- ----------------------------------------------------------------------------
-- 执行顺序:
--   1) CREATE DATABASE oms_purchase
--   2) 字典表: pur_dict
--   3) 供应商档案族: pur_supplier / pur_supply_relation / pur_supply_price_log
--   4) 申请族: pur_request / pur_request_item
--   5) 采购单族: pur_order(★5状态分离) / pur_order_item / pur_order_fee / pur_arrival_plan / pur_order_change
--   6) 到货入库族: pur_arrival / pur_arrival_item / pur_receipt / pur_receipt_item / pur_damage / pur_diff_decision
--   7) 对账结算族: pur_payable / pur_statement(★差额校验) / pur_statement_item / pur_invoice / pur_invoice_match / pur_payment / pur_payment_verify / pur_recon_diff
--   8) 初始字典数据 INSERT: pur_dict（单据类型/挂账策略/不良原因/费用类型/关闭原因/取消原因）
-- 依赖: 仅本 schema；跨域为逻辑外键 LFK（应用层校验），不建物理外键
-- 命名/类型基线: 见 DB-00 §2/§6；金额 DECIMAL(18,2) / 单价 DECIMAL(18,4)；
--               保留字规避: 商派 po.statement 结算状态更名 settle_status，表名带 pur_ 前缀
-- utf8mb4 / utf8mb4_0900_ai_ci / InnoDB
-- ============================================================================

CREATE DATABASE IF NOT EXISTS oms_purchase DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE oms_purchase;

-- ============================================================================
-- 一、域级字典
-- ============================================================================

-- 25. 采购域字典（域级 · P0，配置表 owner_id 免填）
CREATE TABLE pur_dict (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id   BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  dict_type   VARCHAR(32)     NOT NULL COMMENT '字典类型:bill_type=单据类型,accrual_strategy=挂账策略,damage_reason=不良原因,fee_type=价外费用类型,close_reason=申请关闭原因,cancel_reason=采购取消原因',
  dict_code   VARCHAR(32)     NOT NULL COMMENT '字典码(类型内唯一)',
  dict_name   VARCHAR(64)     NOT NULL COMMENT '字典名称',
  dict_value  JSON            NULL DEFAULT NULL COMMENT '扩展参数:单据类型={"prefix":"PO","seq_len":5};挂账策略={"trigger_event":"purchase.po.checked","amount_caliber":"head","accrual_time":"audit"}',
  sort_no     INT             NOT NULL DEFAULT 0 COMMENT '排序',
  status      TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=停用',
  create_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted  TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_pur_dict (dict_type, dict_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='采购域字典(域级,P0,配置表)';

-- ============================================================================
-- 二、供应商档案族（D06.01 · P0）
-- ============================================================================

-- 3. 供应商档案（D06.01 · P0，档案表 owner_id 免填=0）← 商派 purchase.supplier 改造:主数据外置金蝶/OA(Q28)
CREATE TABLE pur_supplier (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(档案表免填=0)',
  supplier_code     VARCHAR(32)     NOT NULL COMMENT '本地供应商编号,唯一',
  kd_supplier_code  VARCHAR(64)     NOT NULL COMMENT '金蝶供应商编码(映射键唯一,经D08.06通道同步;P1前人工映射兜底)',
  supplier_name     VARCHAR(128)    NOT NULL COMMENT '供应商名称(主数据同步冗余)',
  short_name        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '简称(同步冗余)',
  status            TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=停用,3=冻结(随主数据同步+本地可加严;映射缺失时申请/采购单选不到该供应商)',
  pay_type          TINYINT         NOT NULL DEFAULT 2 COMMENT '付款方式:1=现购cash,2=赊购credit(采购视角本地扩展;pur_order.po_type默认来源,D06.04挂账策略输入)',
  credit_days       INT             NOT NULL DEFAULT 0 COMMENT '账期天数(pay_type=2赊购有效)',
  settle_type       TINYINT         NOT NULL DEFAULT 3 COMMENT '结算方式:1=票到付款,2=货到付款,3=月结(应付到期日规则输入,D06.04 FR-01b)',
  credit_lv         VARCHAR(10)     NOT NULL DEFAULT '' COMMENT '信用等级(本地评估,镜像商派supplier.credit_lv;D06.03履约统计参考)',
  default_branch_id BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '默认收货仓 LFK→oms_fulfill.ful_branch',
  contact_ext       JSON            NULL DEFAULT NULL COMMENT '本地联系人扩展(采购对接人/电话摘要,不回写主数据;敏感字段按DB-00§3.2信封加密)',
  bank_ext          JSON            NULL DEFAULT NULL COMMENT '银行账户展示冗余(账户权威在金蝶,D06.04 FR-04b;脱敏展示)',
  sync_time         DATETIME(3)     NULL DEFAULT NULL COMMENT '最近主数据同步时间',
  sync_source       VARCHAR(16)     NOT NULL DEFAULT 'manual' COMMENT '同步来源:kingdee=金蝶,oa=OA,manual=人工补录,migration=迁移',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted        TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_pur_supplier_code (supplier_code),
  UNIQUE KEY uk_pur_supplier_kd (kd_supplier_code),
  KEY idx_pur_supplier_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='供应商档案-金蝶映射+采购视角本地扩展(D06.01,P0)';

-- 4. 供货关系（D06.01 · P0）← 商派 purchase.supplier_goods 改造:+价格版本引用+含税口径
CREATE TABLE pur_supply_relation (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id           BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(冗余自物料归属,行级过滤用)',
  supplier_id         BIGINT UNSIGNED NOT NULL COMMENT '供应商 LFK→pur_supplier(联合唯一①)',
  bm_id               BIGINT UNSIGNED NOT NULL COMMENT '基础物料 LFK→oms_stock.inv_material(联合唯一②)',
  default_price       DECIMAL(18,4)   NOT NULL DEFAULT 0 COMMENT '默认供货价(单价4位小数)',
  tax_flag            TINYINT         NOT NULL DEFAULT 1 COMMENT '含税标记:1=含税,2=不含税(口径与D04.07§5.3全局配置一致)',
  price_version_id    BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '当前价格版本 LFK→pur_supply_price_log',
  lead_time           INT             NOT NULL DEFAULT 7 COMMENT '采购提前期(天,D04.10补货公式与期望到货日推导消费;无档案默认7天)',
  moq                 INT             NOT NULL DEFAULT 0 COMMENT '最小起订量(D04.10建议量修正消费)',
  pack_qty            INT             NOT NULL DEFAULT 1 COMMENT '订货倍数/箱规(建议量向上取整修正)',
  is_default          TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '是否默认供应商:0=否,1=是(同物料多供应商时唯一默认,应用层校验)',
  last_purchase_time  DATETIME(3)     NULL DEFAULT NULL COMMENT '最近采购时间(D06.03入库确认回写,IF-D06.01-04)',
  last_purchase_price DECIMAL(18,4)   NOT NULL DEFAULT 0 COMMENT '最近采购价(入库回写)',
  status              TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=停用',
  create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(入库回写并发)',
  is_deleted          TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_pur_supply_relation (supplier_id, bm_id),
  KEY idx_pur_supply_relation_bm (bm_id, is_default),
  KEY idx_pur_supply_relation_owner (owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='供货关系-物料x供应商提前期/MOQ/箱规/默认供货价(D06.01,P0)';

-- 5. 供货价历史（D06.01 · P0，流水类只增不改:无is_deleted/version/update_time）← 商派 branch_product_batch+dealer.goods_price 有效期版本化
CREATE TABLE pur_supply_price_log (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(冗余自物料归属)',
  supplier_id    BIGINT UNSIGNED NOT NULL COMMENT '供应商 LFK→pur_supplier',
  bm_id          BIGINT UNSIGNED NOT NULL COMMENT '基础物料 LFK→oms_stock.inv_material',
  price          DECIMAL(18,4)   NOT NULL DEFAULT 0 COMMENT '供货价(本版本价格,单价4位小数)',
  tax_flag       TINYINT         NOT NULL DEFAULT 1 COMMENT '含税口径:1=含税,2=不含税',
  effective_time DATETIME(3)     NOT NULL COMMENT '生效时间',
  expire_time    DATETIME(3)     NULL DEFAULT NULL COMMENT '失效时间(NULL=当前有效版本)',
  change_reason  VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '变更原因',
  operator       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '操作人',
  source         VARCHAR(16)     NOT NULL DEFAULT 'manual' COMMENT '来源:manual=手工,inbound_writeback=入库回写(D06.03),migration=迁移',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  KEY idx_pur_supply_price_log_pair (supplier_id, bm_id, effective_time),
  KEY idx_pur_supply_price_log_current (supplier_id, bm_id, expire_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='供货价历史-版本化流水,申请/采购行价格快照隔离依据(D06.01,P0)';

-- ============================================================================
-- 三、采购申请族（D06.01 · P0）
-- ============================================================================

-- 1. 采购申请单（D06.01 · P0，单据类无软删）凯淳显式补建(商派无独立申请实体)
CREATE TABLE pur_request (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id           BIGINT UNSIGNED NOT NULL COMMENT '货主(必填,仅凯淳买断强校验OWNER_NOT_BUYOUT,SRS-D06.01§5.1) LFK→oms_org.org_owner',
  request_bn         VARCHAR(32)     NOT NULL COMMENT '申请单号 PR{YYYYMMDD}{5位序列} 全局唯一(Redis发号)',
  branch_id          BIGINT UNSIGNED NOT NULL COMMENT '目标仓(一单一仓) LFK→oms_fulfill.ful_branch',
  request_type       TINYINT         NOT NULL DEFAULT 1 COMMENT '来源类型:1=手工,2=补货建议转单,3=批量导入(头级=混合时取主导来源,行级source_type为准)',
  status             TINYINT         NOT NULL DEFAULT 1 COMMENT '单据状态:1=草稿,2=审批中,3=已通过,4=已驳回,5=部分转单,6=已转单,7=已关闭,8=已作废(驳回可修改重提;撤回以OA终止回调为准回草稿)',
  oa_instance_id     VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '泛微OA流程实例号(D10.05;回调幂等键=(instance_id,result_version))',
  oa_link            VARCHAR(255)    NOT NULL DEFAULT '' COMMENT 'OA单据跳转链接(OMS不存审批节点明细,FR-02d)',
  approval_result    TINYINT         NOT NULL DEFAULT 0 COMMENT '审批结果:0=无,1=通过,2=驳回,3=撤回确认(OA回调回写)',
  approval_opinion   VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '审批意见(驳回意见企微通知申请人D01.07)',
  approval_time      DATETIME(3)     NULL DEFAULT NULL COMMENT '审批完成时间',
  expect_arrive_date DATE            NULL DEFAULT NULL COMMENT '期望到货日(头级默认,行可覆盖;推导=min(断货日-1,今天+提前期))',
  total_amount       DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '申请总金额=Σ(参考价x数量),预算口径(供货价变更不影响已提交申请,快照隔离)',
  applicant          VARCHAR(64)     NOT NULL COMMENT '申请人',
  apply_dept         VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '申请部门',
  close_reason       TINYINT         NOT NULL DEFAULT 0 COMMENT '关闭原因:0=无,1=需求取消,2=供应商断供,3=价格谈崩,4=转由调拨解决,9=其他(关闭必填,不可逆;已部分转单只能关未转部分)',
  close_time         DATETIME(3)     NULL DEFAULT NULL COMMENT '关闭时间',
  import_batch_no    VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '导入批次号(request_type=3填,D01.06留痕,可追溯每行来源)',
  memo               VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '备注',
  attachment         JSON            NULL DEFAULT NULL COMMENT '附件(OSS URL数组)',
  source             VARCHAR(16)     NOT NULL DEFAULT 'local' COMMENT '数据来源:local=手工,suggest=建议转单,import=导入,migration=迁移',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version            INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(转单防重)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_pur_request_bn (request_bn),
  KEY idx_pur_request_owner (owner_id, status),
  KEY idx_pur_request_status (status, create_time),
  KEY idx_pur_request_oa (oa_instance_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='采购申请单-手工/建议转单/导入三通道,OA审批(D06.01,P0)';

-- 2. 采购申请明细（D06.01 · P0，单据类无软删）
CREATE TABLE pur_request_item (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id           BIGINT UNSIGNED NOT NULL COMMENT '货主(继承头)',
  request_id         BIGINT UNSIGNED NOT NULL COMMENT '申请单 LFK→pur_request',
  bm_id              BIGINT UNSIGNED NOT NULL COMMENT '基础物料 LFK→oms_stock.inv_material(货主归属与头一致,getProfile校验)',
  apply_num          INT             NOT NULL COMMENT '申请数量>0(箱规倍数软提示;已通过申请只可减不可增)',
  transferred_num    INT             NOT NULL DEFAULT 0 COMMENT '已转单数量(累计<=apply_num,转单回写;余额=apply_num-transferred_num-closed_num)',
  closed_num         INT             NOT NULL DEFAULT 0 COMMENT '已关闭数量(行级关闭)',
  expect_arrive_date DATE            NULL DEFAULT NULL COMMENT '期望到货日(行级,空则取头)',
  supplier_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '建议供应商 LFK→pur_supplier(可空=0,转单前必填且映射有效)',
  ref_price          DECIMAL(18,4)   NOT NULL DEFAULT 0 COMMENT '参考供货价(供货关系默认价带出,预算口径)',
  price_version_id   BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '价格版本引用 LFK→pur_supply_price_log(快照隔离依据,转单时D06.02重取当时有效价)',
  source_type        TINYINT         NOT NULL DEFAULT 1 COMMENT '行来源:1=手工,2=补货建议转单,3=导入',
  source_ref         VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '来源引用:suggest_bn(LFK→oms_stock.inv_replenish_suggestion)/导入批次号;同suggest_bn重复adopt拒绝(FR-03d幂等)',
  calc_snapshot      JSON            NULL DEFAULT NULL COMMENT '测算依据快照(建议转单行必存:日均销量/可售/在途/ROP/断货日等D04.10§5.4契约;合并转单同物料多行为数组逐来源可溯;只读固化不可改,改量另记adjust_reason)',
  adjust_reason      VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '人工调量原因(修改建议量时必填)',
  item_status        TINYINT         NOT NULL DEFAULT 1 COMMENT '行状态:1=待转单,2=部分转单,3=已转单,4=已关闭',
  target_order_bn    VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '转单后采购单号(追溯链回写:建议→申请→采购单;D04.10建议单target_bill_bn同步更新)',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version            INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  KEY idx_pur_request_item_req (request_id),
  KEY idx_pur_request_item_bm (bm_id),
  KEY idx_pur_request_item_supplier (supplier_id, item_status),
  KEY idx_pur_request_item_source (source_ref)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='采购申请明细-物料/数量/期望到货日/建议供应商/测算快照(D06.01,P0)';

-- ============================================================================
-- 四、采购单族（D06.02 · P0）
-- ============================================================================

-- 6. 采购单（D06.02 · P0，单据类无软删）★核心 ← 商派 purchase.po 改造:5组状态字段保留+规范化命名,sync独立集成层
CREATE TABLE pur_order (
  id                     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id              BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id               BIGINT UNSIGNED NOT NULL COMMENT '货主(必填=凯淳买断,守卫同D06.01§5.1) LFK→oms_org.org_owner',
  order_bn               VARCHAR(32)     NOT NULL COMMENT '采购单号 PO{YYYYMMDD}{5位序列} 全局唯一(变更不产生新单号,版本留痕pur_order_change)',
  supplier_id            BIGINT UNSIGNED NOT NULL COMMENT '供应商 LFK→pur_supplier(映射有效校验)',
  branch_id              BIGINT UNSIGNED NOT NULL COMMENT '收货仓(一单一仓,改仓=取消重建) LFK→oms_fulfill.ful_branch',
  source_type            TINYINT         NOT NULL DEFAULT 1 COMMENT '来源:1=申请转单,2=直接创建,3=复制创建',
  source_request_bns     VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '关联申请单号(逗号分隔,合并转单可多个,mergeKey=货主+供应商+币种) LFK→pur_request.request_bn',
  direct_reason          VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '直建原因(source_type=2必填,权限=采购主管及以上,不论金额必审)',
  po_type                TINYINT         NOT NULL DEFAULT 2 COMMENT '付款类型:1=现购cash,2=赊购credit(取供应商档案默认;D06.04挂账策略依据:现购按单挂账/赊购按入库挂账)',
  currency               VARCHAR(8)      NOT NULL DEFAULT 'CNY' COMMENT '币种(默认CNY,多币种P2预留)',
  audit_status           TINYINT         NOT NULL DEFAULT 1 COMMENT '审核状态①(本模块写,OA回调驱动):1=未审核(草稿),2=审批中(OA在途,锁定不记在途),3=已审核(生效,在途已记:触发inv_stock_ledger.arrive_store+num),4=已驳回,5=已作废(商派check_status)',
  inbound_status         TINYINT         NOT NULL DEFAULT 0 COMMENT '入库状态②(消费D04.04 iobill.confirmed/D09.03事件重算回写):0=不适用(未审核),1=待入库,2=部分入库(Σin_num<num),3=已入库(Σ(in_num+shortage_num)>=num),4=未入库终止(取消且零入库)(商派eo_status)',
  purchase_status        TINYINT         NOT NULL DEFAULT 1 COMMENT '采购状态③(本模块终态编排,显式置位禁止隐式推导):1=执行中,2=采购完成(inbound_status=3且damage_status属于{0,2}),3=已终止(整单取消零入库),4=部分终止(取消时已部分入库,terminate_flag伴生,已入库部分保留走结算),5=采购退货(退供全量核销,P1)(商派po_status)',
  settle_status          TINYINT         NOT NULL DEFAULT 1 COMMENT '结算状态④(回写权归D06.04,本模块只读;枚举与D04.04 inv_io_bill.settle_status对齐):1=未结算,2=部分结算,3=已结算,4=拒绝结算(差异冻结)(商派statement字段)',
  damage_status          TINYINT         NOT NULL DEFAULT 0 COMMENT '残损状态⑤(D06.03残损闭环回写):0=无需确认(无残损),1=待确认(回传有残损待三分流决策:拒收/让步/索赔),2=已确认(残损处理闭环)(商派defective_status)',
  wms_sync_status        TINYINT         NOT NULL DEFAULT 1 COMMENT 'WMS同步状态⑥(集成层投影,非业务状态机,D09.03指令事件回写):1=无需同步(未下发/本地仓免推),2=已下发(dispatch成功),3=推送失败(wms.inbound.push.failed告警人工),4=已取消同步(wms.inbound.cancel.succ)(商派sync_status独立化)',
  terminate_flag         TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '部分终止标记:0=否,1=是(FR-05b,purchase_status=4伴生)',
  total_amount           DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '商品总额=Σ行金额(审批阈值比对基数=total_amount+total_extra_fee,默认5万必审,可按货主/供应商/类型配置)',
  total_extra_fee        DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '价外费用总额(明细pur_order_fee;任一行入库前可改自动重摊,有入库行后锁定)',
  check_time             DATETIME(3)     NULL DEFAULT NULL COMMENT '审核时间(在途记账唯一+时点,D04.02契约)',
  check_operator         VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '审核人(OA终审人或"系统免审";免审通道=申请已审+未超阈值+价未偏离申请参考价)',
  oa_instance_id         VARCHAR(64)     NOT NULL DEFAULT '' COMMENT 'OA流程实例号(采购单/取消/反审核审批,D10.05)',
  oa_link                VARCHAR(255)    NOT NULL DEFAULT '' COMMENT 'OA单据链接',
  emergency              TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '紧急标记:0=否,1=是',
  supplier_confirm_flag  TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '供应商接单确认:0=未确认,1=已确认(人工可选标记,线下回签勾选,不阻塞流程;P2门户协同预留)',
  buyer                  VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '采购员',
  memo                   VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '备注',
  attachment             JSON            NULL DEFAULT NULL COMMENT '附件(比价说明/交货条款等OSS URL数组)',
  source                 VARCHAR(16)     NOT NULL DEFAULT 'local' COMMENT '数据来源:local=手工,apply=申请转单,api=自动,import=导入,migration=迁移',
  create_time            DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time            DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version                INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(变更/取消/状态回写并发,行级乐观锁+状态防护)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_pur_order_bn (order_bn),
  KEY idx_pur_order_supplier (supplier_id, audit_status),
  KEY idx_pur_order_owner (owner_id, create_time),
  KEY idx_pur_order_status (audit_status, inbound_status, purchase_status),
  KEY idx_pur_order_settle (settle_status),
  KEY idx_pur_order_sync (wms_sync_status),
  KEY idx_pur_order_branch (branch_id, inbound_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='采购单-★5状态分离(audit/inbound/purchase/settle/damage)+wms_sync集成投影(D06.02,P0)';

-- 7. 采购单明细（D06.02 · P0，单据类无软删）← 商派 po_items 改造
CREATE TABLE pur_order_item (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id           BIGINT UNSIGNED NOT NULL COMMENT '货主(继承头)',
  order_id           BIGINT UNSIGNED NOT NULL COMMENT '采购单 LFK→pur_order',
  bm_id              BIGINT UNSIGNED NOT NULL COMMENT '基础物料 LFK→oms_stock.inv_material(货主归属一致校验)',
  num                INT             NOT NULL COMMENT '采购数量>0(变更后=最新有效数量,旧值在pur_order_change;减量不得低于已入库量,已入库部分不可逆)',
  price              DECIMAL(18,4)   NOT NULL DEFAULT 0 COMMENT '含税单价(口径=D04.07§5.3全局配置;价格快照固化,后续供货价变更不影响本单;调价原因必填,偏离默认价超阈值需附件比价说明)',
  tax_rate           DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '税率(百分数值,如13.0000)',
  price_net          DECIMAL(18,4)   NOT NULL DEFAULT 0 COMMENT '不含税派生价=price/(1+tax_rate),4位小数',
  price_version_id   BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '供货价版本引用 LFK→pur_supply_price_log',
  amount             DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '行金额=price x num',
  extra_fee_share    DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '价外费用分摊额(费用总额x行占比,尾差入最后一行;行入库成本价=price+extra_fee_share/num传D04.07 priceIn计入存货成本)',
  in_num             INT             NOT NULL DEFAULT 0 COMMENT '已入库数=Σ关联入库单据行正品确认量(D06.03事件重算回写,重算式幂等)',
  out_num            INT             NOT NULL DEFAULT 0 COMMENT '已退供数(退供出库P1预留)',
  shortage_num       INT             NOT NULL DEFAULT 0 COMMENT '短缺核销量(差异闭环"短缺不补"量,pur_diff_decision回写;in_num+shortage_num=num视同完成)',
  expect_arrive_date DATE            NULL DEFAULT NULL COMMENT '期望到货日(合并转单同物料多行取最早)',
  request_item_id    BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '来源申请行 LFK→pur_request_item(申请转单行必填,行级追溯)',
  calc_snapshot_refs JSON            NULL DEFAULT NULL COMMENT '测算快照引用数组(合并行逐来源可溯,元素={request_item_id,calc_snapshot摘要})',
  item_status        TINYINT         NOT NULL DEFAULT 1 COMMENT '行状态:1=待入库,2=部分入库,3=完成入库,4=已关闭(余量人工关闭,同步释放在途)',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version            INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(行级核销回写高频竞争)',
  PRIMARY KEY (id),
  KEY idx_pur_order_item_order (order_id),
  KEY idx_pur_order_item_bm (bm_id),
  KEY idx_pur_order_item_request (request_item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='采购单明细-数量/单价/价外分摊/已入库量/残损短缺量(D06.02,P0)';

-- 8. 采购价外费用（D06.02 · P0）← 商派 po.delivery_cost 单字段改造:类型字典化+分摊显式化
CREATE TABLE pur_order_fee (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(继承单头)',
  order_id       BIGINT UNSIGNED NOT NULL COMMENT '采购单 LFK→pur_order',
  fee_type       TINYINT         NOT NULL COMMENT '费用类型:1=运费,2=装卸费,3=保险费,4=关税,9=其他(字典可扩展pur_dict.fee_type)',
  fee_amount     DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '费用金额',
  alloc_type     TINYINT         NOT NULL DEFAULT 1 COMMENT '分摊方式:1=按金额占比,2=按数量占比',
  alloc_version  INT             NOT NULL DEFAULT 1 COMMENT '分摊版本(入库前修改费用自动重摊+1,旧版本快照留档)',
  alloc_snapshot JSON            NULL DEFAULT NULL COMMENT '分摊结果快照:[{order_item_id,share_amount}]行级份额数组,尾差入最后一行,分摊合计=费用总额分级校验',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version        INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  KEY idx_pur_order_fee_order (order_id, fee_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='采购价外费用-头级费用行与分摊快照(D06.02,P0)';

-- 9. 到货计划（D06.02 · P0）凯淳新增(商派无到货计划)
CREATE TABLE pur_arrival_plan (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(随采购单头冗余)',
  order_id       BIGINT UNSIGNED NOT NULL COMMENT '采购单 LFK→pur_order',
  order_item_id  BIGINT UNSIGNED NOT NULL COMMENT '采购行 LFK→pur_order_item',
  batch_seq      INT             NOT NULL DEFAULT 1 COMMENT '计划批次序号(行内递增)',
  plan_date      DATE            NOT NULL COMMENT '计划到货日(供应商延期改期留痕pur_order_change)',
  plan_num       INT             NOT NULL COMMENT '计划数量(Σ<=行数量,余量不排计划=一次性到货默认)',
  arrived_num    INT             NOT NULL DEFAULT 0 COMMENT '已核销数量(D06.03到货登记按计划批次核销回写,先到先核或指定批次)',
  deviation_flag TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '偏离标记:0=无,1=日期偏离,2=量差偏离,3=双偏离(供应商履约统计供数:准时率/足量率→D11)',
  status         TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=待到货,2=部分核销,3=已核销,4=已关闭(余量人工关闭,同步触发在途差额释放=减量变更路径)',
  close_reason   VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '关闭原因(status=4必填)',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version        INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_pur_arrival_plan (order_item_id, batch_seq),
  KEY idx_pur_arrival_plan_date (plan_date, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='到货计划-分批到货批次安排与核销(D06.02,P0)';

-- 10. 采购变更留痕（D06.02 · P0，流水类只增不改:无is_deleted/version/update_time）
CREATE TABLE pur_order_change (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id           BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(冗余自单头)',
  order_id           BIGINT UNSIGNED NOT NULL COMMENT '采购单 LFK→pur_order',
  order_bn           VARCHAR(32)     NOT NULL COMMENT '采购单号(冗余,归档追溯加速)',
  order_item_id      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '采购行(行级变更填,头级=0)',
  change_version     INT             NOT NULL DEFAULT 1 COMMENT '变更版本号(单内递增;在途记账幂等键成分=(bill_type,bill_item_id,action+变更版本号),D04.02§6.2契约)',
  change_type        TINYINT         NOT NULL COMMENT '变更类型:1=加量,2=减量,3=价格调整,4=价外费用,5=到货计划,6=头信息,7=整单取消,8=部分终止,9=反审核(严格条件:未入库未下发+OA重审+双人复核)',
  field_name         VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '变更字段名(num/price/extra_fee_share/plan_date等,字段级审计D10.06)',
  old_value          VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '旧值',
  new_value          VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '新值',
  reason             VARCHAR(512)    NOT NULL COMMENT '变更原因(必填;取消原因:1=需求取消,2=供应商违约,3=价格谈崩,4=重复下单,9=其他)',
  arrive_adjust_num  INT             NOT NULL DEFAULT 0 COMMENT '在途差额调整量(±Δ:加量+/减量-/取消-未入库量;经D04.02 StockLedgerService::change记inv_stock_ledger.arrive_store,action=采购变更/采购取消)',
  reaudit_flag       TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '重审标记:0=免审生效,1=跨阈值上移需OA重审(原<阈值且新>=阈值→重审挂起;下移/同侧不重审,SRS§5.5三分支)',
  oa_instance_id     VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '重审OA流程引用',
  status             TINYINT         NOT NULL DEFAULT 2 COMMENT '状态:1=挂起(待重审),2=已生效,3=已驳回,4=已撤销',
  operator           VARCHAR(64)     NOT NULL COMMENT '操作人',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '变更时间',
  PRIMARY KEY (id),
  KEY idx_pur_order_change_order (order_id, change_version),
  KEY idx_pur_order_change_bn (order_bn)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='采购变更留痕-加量/减量/取消版本链流水(D06.02,P0)';

-- ============================================================================
-- 五、到货入库族（D06.03 · P0）
-- ============================================================================

-- 11. 到货登记单 ASN（D06.03 · P0，单据类无软删）凯淳显式建单层(商派直接录实收生成eo)
CREATE TABLE pur_arrival (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id           BIGINT UNSIGNED NOT NULL COMMENT '货主(继承PO)',
  arrival_bn         VARCHAR(32)     NOT NULL COMMENT '到货登记号 ASN{YYYYMMDD}{5位序列} 唯一',
  order_id           BIGINT UNSIGNED NOT NULL COMMENT '采购单 LFK→pur_order(一登记单一PO,多行可)',
  order_bn           VARCHAR(32)     NOT NULL COMMENT '采购单号(冗余追溯)',
  supplier_id        BIGINT UNSIGNED NOT NULL COMMENT '供应商(冗余自PO) LFK→pur_supplier',
  branch_id          BIGINT UNSIGNED NOT NULL COMMENT '收货仓(冗余自PO) LFK→oms_fulfill.ful_branch',
  plan_batch_id      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '到货计划批次 LFK→pur_arrival_plan(0=计划外到货,out_of_plan_flag标记)',
  out_of_plan_flag   TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '计划外到货标记:0=否,1=是',
  expect_arrive_date DATE            NULL DEFAULT NULL COMMENT '预计到货日(改期留痕;已下发则经D09.03取消通道撤回指令后重新下发新轮次)',
  carrier            VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '承运物流',
  tracking_no        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '运单号',
  packing_list_ref   JSON            NULL DEFAULT NULL COMMENT '装箱清单附件(OSS URL数组)',
  receipt_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '生成的采购入库单 LFK→pur_receipt(1:1回填,幂等防重)',
  status             TINYINT         NOT NULL DEFAULT 1 COMMENT '登记状态:1=已登记,2=已生成入库单据,3=已下发,4=收货中(WMS接收确认),5=已回传,6=已确认(confirm闭环),7=已取消,8=异常(create失败告警;WMS已收货拒绝取消→照单收货路径恢复)',
  source_type        TINYINT         NOT NULL DEFAULT 1 COMMENT '登记来源:1=手工,2=供应商通知代录(邮件/电话,附件留存),3=导入(D01.06),4=无单认领(无头件衔接D04.04 FR-03c,7天未认领升级告警采购主管)',
  headless_ref       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '无主回传引用(source_type=4填,D09.03无主队列ID;按供应商+物料+数量模糊匹配评分认领)',
  operator           VARCHAR(64)     NOT NULL COMMENT '经手人',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version            INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_pur_arrival_bn (arrival_bn),
  KEY idx_pur_arrival_order (order_id, status),
  KEY idx_pur_arrival_status (status, expect_arrive_date),
  KEY idx_pur_arrival_supplier (supplier_id, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='到货登记单ASN-预约/代录/导入/无单认领四通道(D06.03,P0)';

-- 12. 到货登记明细（D06.03 · P0，单据类无软删）
CREATE TABLE pur_arrival_item (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id     BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id      BIGINT UNSIGNED NOT NULL COMMENT '货主(继承头)',
  arrival_id    BIGINT UNSIGNED NOT NULL COMMENT '到货登记单 LFK→pur_arrival',
  order_item_id BIGINT UNSIGNED NOT NULL COMMENT '采购行 LFK→pur_order_item',
  bm_id         BIGINT UNSIGNED NOT NULL COMMENT '基础物料(冗余) LFK→oms_stock.inv_material',
  arrive_num    INT             NOT NULL COMMENT '本次到货数量>0(<=行余额=num-in_num-shortage_num-在途登记量,超量拒绝提示走D06.02变更加量,FR-01d)',
  plan_batch_id BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '行级计划批次关联(多批次拆分登记用) LFK→pur_arrival_plan',
  memo          VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '行备注',
  create_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version       INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  KEY idx_pur_arrival_item_arrival (arrival_id),
  KEY idx_pur_arrival_item_poitem (order_item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='到货登记明细-行级数量与计划批次关联(D06.03,P0)';

-- 13. 采购入库单（D06.03 · P0，单据类无软删）← 商派 purchase.eo 拆解:记账归D04.04/D04.02,本表=采购侧业务视图
CREATE TABLE pur_receipt (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id     BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id      BIGINT UNSIGNED NOT NULL COMMENT '货主(继承PO)',
  receipt_bn    VARCHAR(32)     NOT NULL COMMENT '采购入库单号(=inv_io_bill.bill_bn同值,唯一)',
  bill_bn       VARCHAR(32)     NOT NULL COMMENT '出入库单据号 LFK→oms_stock.inv_io_bill(1:1绑定,幂等键;IoBillService::create(type=采购入库,源单=PO)生成,dispatch触发D09.03 push)',
  bill_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '单据头ID LFK→oms_stock.inv_io_bill.id(冗余加速)',
  arrival_id    BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '到货登记单 LFK→pur_arrival(1:1)',
  order_id      BIGINT UNSIGNED NOT NULL COMMENT '采购单 LFK→pur_order(源单)',
  order_bn      VARCHAR(32)     NOT NULL COMMENT '采购单号(冗余=inv_io_bill.source_bill_bn)',
  supplier_id   BIGINT UNSIGNED NOT NULL COMMENT '供应商 LFK→pur_supplier',
  branch_id     BIGINT UNSIGNED NOT NULL COMMENT '收货仓 LFK→oms_fulfill.ful_branch',
  wms_batch_no  VARCHAR(64)     NOT NULL DEFAULT '' COMMENT 'WMS回传批次号(D09.03回调透传,追溯)',
  estimate_flag TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '暂估标记:0=正式价(发票已到),1=暂估价(发票未到,confirm时D04.07 priceIn落inv_estimate_batch暂估批次;发票匹配由D06.04触发reverseEstimate转正,本模块不介入发票流程)',
  bill_status   TINYINT         NOT NULL DEFAULT 1 COMMENT '单据状态投影:1=草稿,2=已下发WMS,3=部分回传,4=全部回传,5=已确认,6=已红冲,7=已关闭(权威在inv_io_bill.status,本字段只读投影冗余,事件同步;改判纠错走D04.04红冲机制)',
  settle_status TINYINT         NOT NULL DEFAULT 1 COMMENT '结算状态:0=无需结算,1=未结算,2=部分结算,3=已结算,4=结算锁定(禁红冲)(D06.04 markSettled回写投影,与inv_io_bill.settle_status同枚举语义;purchase.receipt.confirmed事件供赊购挂账取数)',
  settle_bn     VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '结算核销单号 LFK→pur_payment.payment_bn',
  confirm_time  DATETIME(3)     NULL DEFAULT NULL COMMENT '确认记账时间(在途-/实际+唯一时点,D04.02契约;分批确认模式按批分段释放;赊购挂账时点)',
  operator      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '经手人',
  create_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version       INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_pur_receipt_bn (receipt_bn),
  UNIQUE KEY uk_pur_receipt_bill (bill_bn),
  KEY idx_pur_receipt_order (order_id),
  KEY idx_pur_receipt_settle (settle_status, supplier_id),
  KEY idx_pur_receipt_estimate (estimate_flag, confirm_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='采购入库单-采购侧视图1:1引用inv_io_bill,实收/质检/暂估(D06.03,P0)';

-- 14. 采购入库单明细（D06.03 · P0，单据类无软删）
CREATE TABLE pur_receipt_item (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NOT NULL COMMENT '货主(继承头)',
  receipt_id     BIGINT UNSIGNED NOT NULL COMMENT '采购入库单 LFK→pur_receipt',
  bill_item_id   BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '出入库单据行 LFK→oms_stock.inv_io_bill_item(1:1投影)',
  order_item_id  BIGINT UNSIGNED NOT NULL COMMENT '采购行 LFK→pur_order_item(source_item_id追溯链,D04.04§6.2)',
  bm_id          BIGINT UNSIGNED NOT NULL COMMENT '基础物料 LFK→oms_stock.inv_material',
  issued_num     INT             NOT NULL DEFAULT 0 COMMENT '下发数量(=登记本次到货量)',
  returned_num   INT             NOT NULL DEFAULT 0 COMMENT '累计回传数量(WMS收货登记,分批回传累积,容差校验权威=D04.04§5.1类型级配置)',
  actual_num     INT             NOT NULL DEFAULT 0 COMMENT '实收数量(质检前)',
  qualified_num  INT             NOT NULL DEFAULT 0 COMMENT '合格确认量(正品入账=inv_io_bill_item.confirmed_num主体;残损分流结果量Σ校验:qualified+defect+discount+reject+shortage=issued±容差)',
  defect_num     INT             NOT NULL DEFAULT 0 COMMENT '次品量(残损分流=让步接收-次品→D04.04模板defect_num→D04.02 defective口径入账,可用不增加)',
  discount_num   INT             NOT NULL DEFAULT 0 COMMENT '折让转正量(残损分流=让步接收-折让转正,按正品confirmed_num入账,折让金额登记供D06.04应付扣减,货值>2000元OA审批)',
  reject_num     INT             NOT NULL DEFAULT 0 COMMENT '拒收量(残损分流=拒收退回,不入账,核销走短缺路径;退供出库单据P1预留,本期人工线下+登记闭环)',
  shortage_num   INT             NOT NULL DEFAULT 0 COMMENT '短少量(差异决策核销量回写pur_order_item.shortage_num,在途差额按D04.04§5.1模板释放)',
  discount_amount DECIMAL(18,2)  NOT NULL DEFAULT 0 COMMENT '折让金额(协议价扣减,D06.04应付扣减来源)',
  batch_no       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '批次号(效期物料必填→D04.09 BatchService::registerIn登记;WMS不支持批次降级场景人工补录)',
  produce_date   DATE            NULL DEFAULT NULL COMMENT '生产日期(效期物料必填)',
  expire_date    DATE            NULL DEFAULT NULL COMMENT '效期到期日',
  serial_nos     JSON            NULL DEFAULT NULL COMMENT '序列号清单(SN物料必填,JSON数组→D04.09)',
  quality_result TINYINT         NOT NULL DEFAULT 0 COMMENT '质检结果:0=免检,1=合格,2=部分不良,3=整批不良',
  quality_detail JSON            NULL DEFAULT NULL COMMENT '质检明细(不良原因分布/抽检比例/WMS质检单引用)',
  unit_cost      DECIMAL(18,4)   NOT NULL DEFAULT 0 COMMENT '入库成本价=PO行price+extra_fee_share/num(D04.07 priceIn价源,价外分摊入单价契约§5.3;单价4位小数)',
  estimate_flag  TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '行暂估标记:0=正式价,1=暂估价(同头;发票到→D06.04 reverseEstimate转正联动inv_estimate_batch状态:暂估中→已转正/部分转正)',
  amount         DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '行金额=unit_cost x 确认量(含折让转正量)',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version        INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(行级回传高频回写)',
  PRIMARY KEY (id),
  KEY idx_pur_receipt_item_receipt (receipt_id),
  KEY idx_pur_receipt_item_poitem (order_item_id),
  KEY idx_pur_receipt_item_billitem (bill_item_id),
  KEY idx_pur_receipt_item_batch (bm_id, batch_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='采购入库单明细-实收/质检/批次效期/残损分流结果量(D06.03,P0)';

-- 15. 残损与索赔登记（D06.03 · P0，单据类无软删:决策留痕不可删,纠错走D04.04红冲+重新决策）← SRS purchase_defect+purchase_claim 合并
CREATE TABLE pur_damage (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL COMMENT '货主(继承PO)',
  damage_bn         VARCHAR(32)     NOT NULL COMMENT '残损单号 DM{YYYYMMDD}{5位} 唯一',
  order_id          BIGINT UNSIGNED NOT NULL COMMENT '采购单 LFK→pur_order(生成后回写damage_status=1待确认)',
  order_bn          VARCHAR(32)     NOT NULL COMMENT '采购单号(冗余追溯)',
  order_item_id     BIGINT UNSIGNED NOT NULL COMMENT '采购行 LFK→pur_order_item',
  receipt_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '采购入库单 LFK→pur_receipt',
  bill_item_id      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '入库单据行 LFK→oms_stock.inv_io_bill_item(追溯链)',
  bm_id             BIGINT UNSIGNED NOT NULL COMMENT '基础物料(冗余) LFK→oms_stock.inv_material',
  damage_num        INT             NOT NULL COMMENT '残损数量(=WMS回传defect_num原始值不可改,改判走红冲;回传defect_num>0或wms.inbound.diff破损自动生成)',
  damage_reason     TINYINT         NOT NULL DEFAULT 9 COMMENT '不良原因:1=运输破损,2=生产不良,3=包装破损,4=效期异常,5=货差短少,9=其他(字典pur_dict.damage_reason,D09.03 diff透传)',
  wms_evidence_ref  JSON            NULL DEFAULT NULL COMMENT 'WMS凭证引用(照片OSS URL/差异登记ID)',
  decision_json     JSON            NULL DEFAULT NULL COMMENT '分流决策明细:[{num,flow(1=拒收退回,2=让步接收-次品,3=让步接收-折让转正),discount_amount,approval_ref}],Σnum=damage_num强校验(行级可拆分组合)',
  claim_flag        TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '是否发起索赔:0=否,1=是(与分流并行,不影响记账)',
  claim_bn          VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '索赔号 CL{YYYYMMDD}{5位}(claim_flag=1生成;短缺/超收拒收来源索赔经pur_diff_decision.damage_id关联同字段族)',
  claim_object_type TINYINT         NOT NULL DEFAULT 0 COMMENT '索赔对象类型:0=无,1=供应商,2=物流承运商',
  claim_object_id   BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '索赔对象ID(供应商LFK→pur_supplier/承运商)',
  claim_amount      DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '索赔金额=责任归属残损量x PO行price',
  claim_result      TINYINT         NOT NULL DEFAULT 0 COMMENT '索赔结果:0=处理中,1=认赔(D06.04应付扣减/收款登记),2=部分认赔,3=放弃(损失登记,超阈值需OA)',
  claim_result_amount DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '认定金额(结果=1/2填)',
  settle_ref        VARCHAR(32)     NOT NULL DEFAULT '' COMMENT 'D06.04应付扣减引用(调整单/台账流水object_bn,purchase.defect.closed事件联动)',
  status            TINYINT         NOT NULL DEFAULT 1 COMMENT '残损单状态:1=待决策,2=审批中(让步/放弃超阈值OA),3=已决策,4=已闭环(全部残损行决策完成→回写damage_status=2已确认;超期7天未决升级告警)',
  oa_instance_id    VARCHAR(64)     NOT NULL DEFAULT '' COMMENT 'OA审批引用(让步接收货值>2000元/索赔放弃必填,D10.05,审批类型=采购残损处理)',
  handler           VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '决策人',
  decide_time       DATETIME(3)     NULL DEFAULT NULL COMMENT '决策时间',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_pur_damage_bn (damage_bn),
  KEY idx_pur_damage_claim (claim_bn),
  KEY idx_pur_damage_order (order_id, status),
  KEY idx_pur_damage_status (status, create_time),
  KEY idx_pur_damage_claim_result (claim_result, claim_object_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='残损与索赔登记-三分流(拒收/让步次品/折让转正)+索赔闭环(D06.03,P0)';

-- 16. 到货差异决策登记（D06.03 · P0，单据类无软删）
CREATE TABLE pur_diff_decision (
  id                     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id              BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id               BIGINT UNSIGNED NOT NULL COMMENT '货主(继承PO)',
  diff_ref               VARCHAR(64)     NOT NULL DEFAULT '' COMMENT 'D09.03差异登记引用(fulfill_inbound_diff,双向闭环其FR-05c:决策结果回写handle_status)',
  order_id               BIGINT UNSIGNED NOT NULL COMMENT '采购单 LFK→pur_order',
  order_item_id          BIGINT UNSIGNED NOT NULL COMMENT '采购行 LFK→pur_order_item',
  receipt_id             BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '采购入库单 LFK→pur_receipt',
  bill_bn                VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '入库单据号 LFK→oms_stock.inv_io_bill',
  supplier_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '供应商(冗余自PO,差异台账统计维度) LFK→pur_supplier',
  diff_type              TINYINT         NOT NULL COMMENT '差异类型:1=短缺,2=超收(容差内,D04.04类型配置如+5%),3=超收(容差外,D09.03拒绝+差异挂起人工决策),4=拒收差异',
  diff_num               INT             NOT NULL DEFAULT 0 COMMENT '差异数量',
  decision               TINYINT         NOT NULL DEFAULT 0 COMMENT '决策:0=待决策;短缺:1=供应商补发(保持部分入库,等补发登记同PO行核销),2=短缺核销(不再补发,视同完成,需原因+超阈值审批),3=索赔(与残损索赔同机制);超收:4=追认(D06.02变更加量补单,事后审批),5=拒收超出(同残损拒收路径)',
  shortage_num_writeback INT             NOT NULL DEFAULT 0 COMMENT '核销量回写值(decision=2时回写pur_order_item.shortage_num;在途差额按D04.04§5.1模板释放,本模块不自定记账)',
  damage_id              BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '关联残损/索赔单 LFK→pur_damage(decision=3时填)',
  reason                 VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '决策原因(核销/放弃必填)',
  approval_ref           VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '审批引用(核销超阈值OA,D10.05)',
  status                 TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=待决策,2=已决策,3=已闭环',
  operator               VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '决策人',
  create_time            DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time            DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version                INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  KEY idx_pur_diff_decision_order (order_id, status),
  KEY idx_pur_diff_decision_ref (diff_ref),
  KEY idx_pur_diff_decision_supplier (supplier_id, diff_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='到货差异决策登记-短缺/超收决策与双向闭环(D06.03,P0)';

-- ============================================================================
-- 六、对账结算族（D06.04 · P1）
-- ============================================================================

-- 17. 应付挂账单（D06.04 · P1，单据类无软删）← 商派 purchase_payments(现购)+credit_sheet(赊购) 分叉显式化为策略字段
CREATE TABLE pur_payable (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id            BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id             BIGINT UNSIGNED NOT NULL COMMENT '货主(分账维度,预留经销采购) LFK→oms_org.org_owner',
  payable_bn           VARCHAR(32)     NOT NULL COMMENT '应付单号 AP{YYYYMMDD}{5位} 唯一',
  supplier_id          BIGINT UNSIGNED NOT NULL COMMENT '供应商 LFK→pur_supplier',
  accrual_strategy     TINYINT         NOT NULL COMMENT '挂账策略:1=现购按单挂账(采购单审核时点,触发事件purchase.po.checked,金额=商品总额+价外费用头级,镜像商派payable=product_cost+delivery_cost),2=赊购按入库挂账(入库确认时点,触发事件purchase.receipt.confirmed,金额=Σ(入库成本价x确认量)行级含价外分摊入单价)(供应商级默认+单据级覆盖,pur_dict.accrual_strategy)',
  accrual_time         DATETIME(3)     NOT NULL COMMENT '挂账时点(=审核时间/confirm时间,口径快照)',
  accrual_amount       DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '挂账金额(策略1=total_amount+total_extra_fee;策略2=Σ(unit_cost x 确认量))',
  accrual_basis_snapshot JSON          NULL DEFAULT NULL COMMENT '金额口径快照(行级明细/事件载荷摘要,可解释审计)',
  source_order_bn      VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '关联采购单号 LFK→pur_order.order_bn',
  source_bill_bns      JSON            NULL DEFAULT NULL COMMENT '关联入库单据号数组 LFK→oms_stock.inv_io_bill.bill_bn(赊购可多单;现购入库事件不再挂账防双挂,只建入库-应付行级对照关联)',
  estimate_flag        TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '暂估标记:0=正式(发票已匹配,金额调整为发票口径+差额冲减留痕),1=暂估(发票未到;入库后60天未到进暂估超期预警清单)',
  adjust_amount        DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '调整扣减累计(红字负值:折让/索赔认定purchase.defect.closed/拒付差额;调整超1000元OA审批)',
  settled_amount       DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '已核销金额(付款核销累计)',
  balance              DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '余额=accrual_amount+adjust_amount-settled_amount(应用层校验恒等式;余额>0部分核销settle_status=2)',
  deposit_offset_amount DECIMAL(18,2)  NOT NULL DEFAULT 0 COMMENT '预付款抵扣额(镜像商派deposit_balance:预付>=结算额→抵扣后余款挂应收方向退供应商/留抵下期策略配置;预付<结算额→抵扣清零差额付款)',
  due_date             DATE            NULL DEFAULT NULL COMMENT '到期日(票到付款=发票日+账期,发票未到不出到期日挂暂估应付;货到付款=入库日+账期;月结=账期月末汇总;取pur_supplier.settle_type+credit_days)',
  settle_status        TINYINT         NOT NULL DEFAULT 1 COMMENT '结算状态:1=未结算,2=部分结算,3=已结算,4=拒绝结算(差异冻结)(与pur_order.settle_status/inv_io_bill.settle_status同枚举语义)',
  settle_bn            VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '核销付款单号 LFK→pur_payment.payment_bn',
  status               TINYINT         NOT NULL DEFAULT 1 COMMENT '单据状态:1=生效,2=差异挂起(pur_recon_diff关联),3=已关闭',
  idempotent_key       VARCHAR(128)    NOT NULL COMMENT '幂等键=(event_id,source_bill)拼接,唯一索引防双挂(同事件重复投递返回首次结果)',
  create_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version              INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(核销回写高频竞争)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_pur_payable_bn (payable_bn),
  UNIQUE KEY uk_pur_payable_idem (idempotent_key),
  KEY idx_pur_payable_supplier (supplier_id, settle_status, due_date),
  KEY idx_pur_payable_estimate (estimate_flag, accrual_time),
  KEY idx_pur_payable_owner (owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='应付挂账单-现购按单/赊购按入库挂账策略引擎(D06.04,P1)';

-- 18. 供应商台账·月度快照（D06.04 · P1）★差额校验 ← 商派 purchase.statement 八列镜像+货主分账+关账强制校验
CREATE TABLE pur_statement (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id            BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id             BIGINT UNSIGNED NOT NULL COMMENT '货主(分账维度,凯淳买断即凯淳本体,预留经销采购分账)',
  supplier_id          BIGINT UNSIGNED NOT NULL COMMENT '供应商 LFK→pur_supplier',
  period               CHAR(7)         NOT NULL COMMENT '账期(月,格式YYYY-MM)',
  initial_pay          DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '期初应付(=上月final_pay;首期=期初导入值source=migration)',
  pay_add              DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '本期增加应付(Σ挂账,含暂估转正调整±)',
  paid                 DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '本期已付(Σ核销付款)',
  deduct_amount        DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '本期扣减(Σ红字调整:索赔认定/折让/拒付差额;商派混入pay_add负值,本表显式化列)',
  final_pay            DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '期末应付=initial_pay+pay_add-paid-deduct_amount',
  initial_receive      DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '期初应收(应收供应商方向:退款/索赔应收/预付抵扣余额挂应收)',
  receive_add          DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '本期增加应收',
  received             DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '本期已收',
  final_receive        DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '期末应收(应收方向四列同构校验;object_type=退款汇总做减法,商派statementDo口径)',
  difference           DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '差额=initial_pay+pay_add-paid-deduct_amount-final_pay(★关账校验必须=0;≠0强制阻断关账+逐笔回放定位工单)',
  check_result         TINYINT         NOT NULL DEFAULT 0 COMMENT '差额校验结果:0=未校验,1=通过,2=不通过(阻断关账,校验结果留痕)',
  check_ticket_ref     VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '校验不平定位工单引用 LFK→pur_recon_diff.diff_bn(按pur_statement_item流水逐笔回放定位,balance_after运行余额链)',
  close_status         TINYINT         NOT NULL DEFAULT 1 COMMENT '关账状态:1=未关账,2=关账中(校验),3=已关账(台账快照锁定,追溯调整走次期+调整留痕;已关账期间禁止补录,反关账需财务主管OA审批)',
  close_time           DATETIME(3)     NULL DEFAULT NULL COMMENT '关账时间',
  reopen_ref           VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '反关账OA审批引用(全留痕)',
  recon_doc_ref        JSON            NULL DEFAULT NULL COMMENT '对账单文档引用(八列汇总+明细清单PDF盖章位/Excel OSS URL、邮件发送时间D01.07、回签影像登记)',
  recon_confirm_status TINYINT         NOT NULL DEFAULT 0 COMMENT '对账单确认状态:0=未生成,1=待发送,2=已发送,3=已确认(回签),4=有异议(转pur_recon_diff差异处理)(发送后10天截止,逾期未回默认不视同确认,升级人工跟进;P2供应商门户在线确认预留)',
  create_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version              INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted           TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_pur_statement (supplier_id, owner_id, period),
  KEY idx_pur_statement_period (period, close_status),
  KEY idx_pur_statement_owner (owner_id, period)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='供应商台账月度快照-期初/增加/已付/期末+差额校验强制阻断关账(D06.04,P1)';

-- 19. 供应商台账明细（D06.04 · P1，流水类只增不改删:无is_deleted/version/update_time,红冲纠错）
CREATE TABLE pur_statement_item (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id     BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id      BIGINT UNSIGNED NOT NULL COMMENT '货主(分账维度,必填)',
  supplier_id   BIGINT UNSIGNED NOT NULL COMMENT '供应商 LFK→pur_supplier',
  period        CHAR(7)         NOT NULL DEFAULT '' COMMENT '归属账期(YYYY-MM,动作时点所在月;关账后补录拒绝走反关账审批通道)',
  statement_id  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '归属月度快照 LFK→pur_statement(0=未归集)',
  object_type   TINYINT         NOT NULL COMMENT '业务类型:1=赊购入库挂账,2=现购按单挂账,3=付款核销,4=退货退款,5=调整扣减(索赔/折让/拒付),6=预付款抵扣,7=暂估转正调整,9=其他(商派statement.object_type:1赊购入库/2现款结算/3采购退货语义扩展)',
  object_bn     VARCHAR(32)     NOT NULL COMMENT '关联单号(AP应付单/PP付款单/DM残损单/IV发票等)',
  direction     TINYINT         NOT NULL DEFAULT 1 COMMENT '方向:1=应付方向,2=应收方向(退款/索赔应收供应商)',
  amount        DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '金额(带符号:挂账正/付款核销负/红字调整负;object_type=4退款在应收方向汇总做减法)',
  balance_after DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '该方向动作后运行余额(回放校验链,差额定位依据)',
  red_flush_of  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '红冲引用原流水id(纠错流水必填;非空即红冲行,禁止改删原流水)',
  operator      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '经手人(系统动作=系统账号名)',
  create_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '动作时间(实时写入,流水式)',
  PRIMARY KEY (id),
  KEY idx_pur_statement_item_supplier (supplier_id, owner_id, period, create_time),
  KEY idx_pur_statement_item_object (object_type, object_bn),
  KEY idx_pur_statement_item_stmt (statement_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='供应商台账明细-流水式只增不改删,差额校验回放基础(D06.04,P1)';

-- 20. 采购发票（D06.04 · P1，单据类无软删:作废/红冲走状态字段）凯淳新增(商派无进项发票匹配层)
CREATE TABLE pur_invoice (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NOT NULL COMMENT '货主 LFK→oms_org.org_owner',
  invoice_no       VARCHAR(64)     NOT NULL COMMENT '发票号(供应商内唯一防重)',
  invoice_code     VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '发票代码',
  invoice_date     DATE            NOT NULL COMMENT '开票日期(票到付款账期起算点)',
  supplier_id      BIGINT UNSIGNED NOT NULL COMMENT '开票方 LFK→pur_supplier(映射校验)',
  amount_net       DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '不含税金额',
  tax_rate         DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '税率(百分数值,如13.0000)',
  tax_amount       DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '税额',
  amount_total     DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '价税合计(三单匹配金额比对基准:|价税合计-Σ发票行匹配金额|<=1元自动尾差记尾差科目月报汇总)',
  match_status     TINYINT         NOT NULL DEFAULT 0 COMMENT '匹配状态:0=未匹配,1=部分匹配,2=已匹配,3=差异挂起(pur_recon_diff工单)(三单匹配=采购单-入库单-发票:数量/单价/金额三维+容差规则§5.3)',
  match_detail_json JSON           NULL DEFAULT NULL COMMENT '三单比对快照(数量:发票量vs入库确认量+差异闭环量,严格一致;单价:|发票价-采购价快照|<=0.01元/件;金额比对结果,可解释审计)',
  estimate_reversed TINYINT(1)     NOT NULL DEFAULT 0 COMMENT '暂估转正触发标记:0=未触发,1=已触发(匹配通过→CostService::reverseEstimate(invoiceRef)回执;oms_stock.inv_estimate_batch状态:暂估中→已转正/部分转正按发票覆盖量;价差回冲=在库调均价+已出库差异明细,D04.07 FR-03b)',
  status           TINYINT         NOT NULL DEFAULT 1 COMMENT '发票状态:1=正常,2=作废,3=红冲(关联原发票,应付与暂估反向联动:已转正暂估回退为暂估中+价差反冲)',
  origin_invoice_no VARCHAR(64)    NOT NULL DEFAULT '' COMMENT '红冲/作废原发票号(status=2/3必填)',
  attachment_ref   JSON            NULL DEFAULT NULL COMMENT '影像附件(OSS URL数组)',
  registrant       VARCHAR(64)     NOT NULL COMMENT '登记人',
  register_time    DATETIME(3)     NULL DEFAULT NULL COMMENT '登记时间',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_pur_invoice (supplier_id, invoice_no, invoice_code),
  KEY idx_pur_invoice_match (match_status, invoice_date),
  KEY idx_pur_invoice_owner (owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='采购发票-三单匹配与暂估转正联动inv_estimate_batch(D06.04,P1)';

-- 21. 发票匹配明细（D06.04 · P1）
CREATE TABLE pur_invoice_match (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(继承发票)',
  invoice_id        BIGINT UNSIGNED NOT NULL COMMENT '发票 LFK→pur_invoice',
  order_bn          VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '采购单号 LFK→pur_order.order_bn(一发票多PO按PO拆行匹配)',
  bill_bn           VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '入库单据号 LFK→oms_stock.inv_io_bill.bill_bn',
  payable_bn        VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '应付单号 LFK→pur_payable.payable_bn(暂估转正式追溯)',
  match_num         INT             NOT NULL DEFAULT 0 COMMENT '本关联行匹配数量(发票量vs入库确认量+差异闭环量,严格一致才通过;数量差异必须有D06.03闭环记录背书,无记录=数量差异工单)',
  match_amount      DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '本关联行匹配金额(一PO多发票累计匹配量<=挂账量)',
  match_result      TINYINT         NOT NULL DEFAULT 0 COMMENT '匹配结果:0=待匹配,1=通过,2=价格差异(|发票价-采购价快照|>0.01元/件),3=数量差异(无闭环记录),4=金额尾差(<=1元自动通过记尾差科目)',
  price_diff_amount DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '价格差异额=(发票价-采购价)x数量(处理路径:拒付差额供应商红字重开/追认调价补D06.02变更审批+差额补付)',
  num_diff_num      INT             NOT NULL DEFAULT 0 COMMENT '数量差异量(追查D06.03差异台账,缺失即补决策后重匹配)',
  tail_diff_amount  DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '尾差金额(自动通过时记尾差科目月报清理)',
  diff_ticket_bn    VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '关联差异工单 LFK→pur_recon_diff.diff_bn(match_result=2/3时生成)',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted        TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  KEY idx_pur_invoice_match_invoice (invoice_id),
  KEY idx_pur_invoice_match_order (order_bn),
  KEY idx_pur_invoice_match_payable (payable_bn)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='发票匹配明细-发票x采购单x入库单x应付单多对多(D06.04,P1)';

-- 22. 付款申请与付款单（D06.04 · P1，单据类无软删）← 商派 purchase_payments 改造:申请/付款两阶段+deposit承接
CREATE TABLE pur_payment (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id           BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主 LFK→oms_org.org_owner',
  apply_bn            VARCHAR(32)     NOT NULL COMMENT '付款申请号 PA{YYYYMMDD}{5位} 唯一',
  payment_bn          VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '付款单号 PP{YYYYMMDD}{5位}(付款事实登记后生成,非空唯一;未付款为空串)',
  supplier_id         BIGINT UNSIGNED NOT NULL COMMENT '供应商 LFK→pur_supplier',
  pay_type            TINYINT         NOT NULL DEFAULT 2 COMMENT '付款类型:1=预付款(PO带deposit>0审核时生成,挂预付资产科目方向;承接商派po.deposit字段族),2=货款,3=退款收回抵扣',
  apply_amount        DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '申请付款额=Σ应付余额-调整扣减(索赔/折让)-预付款余额抵扣',
  payable_scope       JSON            NULL DEFAULT NULL COMMENT '勾选应付单范围(ap_bn数组;空=全量到期应付)',
  deposit_offset_amount DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '预付款余额抵扣额(§5.4镜像商派deposit_balance:预付>=结算额抵扣后余款挂应收方向退供应商/留抵下期;预付<结算额抵扣清零差额进实付)',
  pay_amount          DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '实付金额(银行付款事实;资金通道线下执行,OMS只登记)',
  pay_date            DATE            NULL DEFAULT NULL COMMENT '付款日期',
  bank_serial_no      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '银行流水号',
  bank_account        VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '付款账户(展示冗余,账户权威在金蝶;脱敏展示)',
  status              TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=申请草稿,2=审批中(OA金额分级),3=审批通过待付款,4=已付款,5=已核销,6=已驳回,7=已取消',
  oa_instance_id      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT 'OA审批引用(D10.05,金额分级阈值)',
  kd_push_status      TINYINT         NOT NULL DEFAULT 0 COMMENT '金蝶推送状态:0=未推送,1=已推送,2=推送失败,3=已冲销同步(核销撤销补偿任务;付款/核销明细经D08.06可插拔适配层供数,凭证在金蝶生成)',
  kd_push_time        DATETIME(3)     NULL DEFAULT NULL COMMENT '金蝶推送时间',
  operator            VARCHAR(64)     NOT NULL COMMENT '发起人/登记人',
  create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_pur_payment_apply (apply_bn),
  KEY idx_pur_payment_bn (payment_bn),
  KEY idx_pur_payment_supplier (supplier_id, status),
  KEY idx_pur_payment_kd (kd_push_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='付款申请与付款单-OA审批/银行事实登记/金蝶供数(D06.04,P1)';

-- 23. 付款核销日志（D06.04 · P1，流水类只增不删:无is_deleted/version/update_time,撤销=反向日志）
CREATE TABLE pur_payment_verify (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL COMMENT '货主',
  verify_bn       VARCHAR(32)     NOT NULL COMMENT '核销流水号 PV{YYYYMMDD}{6位} 唯一',
  payment_id      BIGINT UNSIGNED NOT NULL COMMENT '付款单 LFK→pur_payment',
  payment_bn      VARCHAR(32)     NOT NULL COMMENT '付款单号(冗余追溯)',
  payable_id      BIGINT UNSIGNED NOT NULL COMMENT '应付单 LFK→pur_payable',
  payable_bn      VARCHAR(32)     NOT NULL COMMENT '应付单号(冗余追溯)',
  verify_amount   DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '核销金额(正向>0;反向撤销<0,原日志不可删)',
  balance_after   DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '核销后应付余额(=0则settle_status=已结算;联动IoBillService::markSettled回写inv_io_bill.settle_status/settle_bn触发结算锁定:已结算禁红冲;pur_order.settle_status回写IF-D06.02-06)',
  deposit_offset  DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '本笔预付款抵扣额(§5.4)',
  direction       TINYINT         NOT NULL DEFAULT 1 COMMENT '方向:1=正向核销,2=反向撤销(撤销需先解锁结算锁定,财务侧双审批;撤销后应付余额与settle_status正确回退)',
  fifo_flag       TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '核销方式:0=人工指定(原因必填+留痕),1=到期日FIFO自动(先到期先核销,同期按挂账时点)',
  reason          VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '人工指定/撤销原因',
  kd_reverse_flag TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '金蝶冲销标记:0=无需,1=已推金蝶需冲销供数(D08.06补偿任务,最终一致)',
  operator        VARCHAR(64)     NOT NULL COMMENT '操作人',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '核销时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_pur_payment_verify_bn (verify_bn),
  KEY idx_pur_payment_verify_pay (payment_id),
  KEY idx_pur_payment_verify_ap (payable_id, create_time),
  KEY idx_pur_payment_verify_kd (kd_reverse_flag)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='付款核销日志-FIFO/人工指定,撤销反向日志,台账paid写入(D06.04,P1)';

-- 24. 采购对账差异工单（D06.04 · P1，单据类无软删）凯淳新增(商派无差异工单)
CREATE TABLE pur_recon_diff (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL COMMENT '货主 LFK→oms_org.org_owner',
  diff_bn         VARCHAR(32)     NOT NULL COMMENT '差异工单号 DF{YYYYMMDD}{5位} 唯一',
  diff_type       TINYINT         NOT NULL COMMENT '差异类型:1=价格差异(发票价<>采购价),2=数量差异(发票量<>确认量且无闭环记录),3=金额尾差(容差内自动),4=对账异议(供应商提出),5=暂估超期(入库后60天发票未到),6=台账差额校验不平(pur_statement.check_ticket_ref来源,逐笔回放定位),7=索赔争议',
  supplier_id     BIGINT UNSIGNED NOT NULL COMMENT '供应商 LFK→pur_supplier',
  invoice_id      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '关联发票 LFK→pur_invoice',
  order_bn        VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '关联采购单号 LFK→pur_order.order_bn',
  bill_bn         VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '关联入库单据号 LFK→oms_stock.inv_io_bill.bill_bn',
  payable_bn      VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '关联应付单号 LFK→pur_payable.payable_bn',
  statement_id    BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '关联台账快照 LFK→pur_statement(diff_type=6必填)',
  snapshot_json   JSON            NULL DEFAULT NULL COMMENT '三单数据快照(采购单/入库单/发票三维比对数据,定位依据可解释)',
  diff_amount     DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '差异额',
  handle_path     TINYINT         NOT NULL DEFAULT 0 COMMENT '处理路径:0=待定,1=拒付差额(应付按采购价,供应商红字重开后重匹配),2=追认调价(补D06.02价格变更审批+差额补付),3=补决策(追查D06.03差异台账后重匹配),4=重开发票,5=强制核销(差异挂账强行闭环),9=其他',
  handle_result   VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '处理结果说明',
  force_verify_flag TINYINT(1)    NOT NULL DEFAULT 0 COMMENT '强制核销标记:0=否,1=是(需OA审批+subject_mapping必填,进差异台账月报;镜像D08.03三档核销:正常/差异/强制)',
  subject_mapping VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '借贷科目说明(金蝶调整分录参考,审计可解释)',
  oa_instance_id  VARCHAR(64)     NOT NULL DEFAULT '' COMMENT 'OA审批引用(强制核销/坏账放弃,D10.05)',
  deadline        DATE            NULL DEFAULT NULL COMMENT '处理截止(超期30天升级采购主管+财务;差异率=差异单数/应付单数进供应商履约统计)',
  status          TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=待处理,2=处理中,3=已闭环,4=已升级',
  owner_operator  VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '责任人',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_pur_recon_diff_bn (diff_bn),
  KEY idx_pur_recon_diff_supplier (supplier_id, status),
  KEY idx_pur_recon_diff_type (diff_type, status, deadline),
  KEY idx_pur_recon_diff_stmt (statement_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='采购对账差异工单-五类差异登记与闭环,强制核销三档(D06.04,P1)';

-- ============================================================================
-- 七、初始字典数据
-- ============================================================================

-- 单据类型字典（单号前缀+发号规则，Redis发号器 DB-00 §3.1）
INSERT INTO pur_dict (tenant_id, dict_type, dict_code, dict_name, dict_value, sort_no, status) VALUES
(1, 'bill_type', 'request',  '采购申请单',   '{"prefix":"PR","seq_len":5}',  1, 1),
(1, 'bill_type', 'order',    '采购单',       '{"prefix":"PO","seq_len":5}',  2, 1),
(1, 'bill_type', 'arrival',  '到货登记单',   '{"prefix":"ASN","seq_len":5}', 3, 1),
(1, 'bill_type', 'receipt',  '采购入库单',   '{"prefix":"RCP","seq_len":5}', 4, 1),
(1, 'bill_type', 'damage',   '残损处理单',   '{"prefix":"DM","seq_len":5}',  5, 1),
(1, 'bill_type', 'claim',    '索赔记录',     '{"prefix":"CL","seq_len":5}',  6, 1),
(1, 'bill_type', 'payable',  '应付挂账单',   '{"prefix":"AP","seq_len":5}',  7, 1),
(1, 'bill_type', 'pay_apply','付款申请',     '{"prefix":"PA","seq_len":5}',  8, 1),
(1, 'bill_type', 'payment',  '付款单',       '{"prefix":"PP","seq_len":5}',  9, 1),
(1, 'bill_type', 'recon_diff','对账差异工单','{"prefix":"DF","seq_len":5}', 10, 1);

-- 挂账策略字典（SRS-D06.04 FR-01a 策略引擎:现购按单挂账/赊购按入库挂账）
INSERT INTO pur_dict (tenant_id, dict_type, dict_code, dict_name, dict_value, sort_no, status) VALUES
(1, 'accrual_strategy', 'cash_on_audit',    '现购按单挂账',   '{"po_type":"cash","trigger_event":"purchase.po.checked","amount_caliber":"head","amount_formula":"total_amount+total_extra_fee","accrual_time":"audit_time"}', 1, 1),
(1, 'accrual_strategy', 'credit_on_inbound','赊购按入库挂账', '{"po_type":"credit","trigger_event":"purchase.receipt.confirmed","amount_caliber":"line","amount_formula":"SUM(unit_cost*confirmed_num)","accrual_time":"confirm_time"}', 2, 1);

-- 不良原因字典（残损三分流决策输入，D09.03 diff 透传）
INSERT INTO pur_dict (tenant_id, dict_type, dict_code, dict_name, dict_value, sort_no, status) VALUES
(1, 'damage_reason', 'transport_damage', '运输破损', NULL, 1, 1),
(1, 'damage_reason', 'produce_defect',   '生产不良', NULL, 2, 1),
(1, 'damage_reason', 'package_damage',   '包装破损', NULL, 3, 1),
(1, 'damage_reason', 'expire_abnormal',  '效期异常', NULL, 4, 1),
(1, 'damage_reason', 'shortage',         '货差短少', NULL, 5, 1),
(1, 'damage_reason', 'other',            '其他',     NULL, 9, 1);

-- 价外费用类型字典（采购价外费用区，分摊入存货成本 D04.07 §5.3 契约）
INSERT INTO pur_dict (tenant_id, dict_type, dict_code, dict_name, dict_value, sort_no, status) VALUES
(1, 'fee_type', 'freight',   '运费',   NULL, 1, 1),
(1, 'fee_type', 'handling',  '装卸费', NULL, 2, 1),
(1, 'fee_type', 'insurance', '保险费', NULL, 3, 1),
(1, 'fee_type', 'tariff',    '关税',   NULL, 4, 1),
(1, 'fee_type', 'other',     '其他',   NULL, 9, 1);

-- 申请关闭原因字典（SRS-D06.01 SC-06）
INSERT INTO pur_dict (tenant_id, dict_type, dict_code, dict_name, dict_value, sort_no, status) VALUES
(1, 'close_reason', 'demand_cancel',    '需求取消',     NULL, 1, 1),
(1, 'close_reason', 'supply_cut',       '供应商断供',   NULL, 2, 1),
(1, 'close_reason', 'price_breakdown',  '价格谈崩',     NULL, 3, 1),
(1, 'close_reason', 'transfer_solved',  '转由调拨解决', NULL, 4, 1),
(1, 'close_reason', 'other',            '其他',         NULL, 9, 1);

-- 采购取消原因字典（SRS-D06.02 FR-05a）
INSERT INTO pur_dict (tenant_id, dict_type, dict_code, dict_name, dict_value, sort_no, status) VALUES
(1, 'cancel_reason', 'demand_cancel',   '需求取消',   NULL, 1, 1),
(1, 'cancel_reason', 'supplier_breach', '供应商违约', NULL, 2, 1),
(1, 'cancel_reason', 'price_breakdown', '价格谈崩',   NULL, 3, 1),
(1, 'cancel_reason', 'duplicate_order', '重复下单',   NULL, 4, 1),
(1, 'cancel_reason', 'other',           '其他',       NULL, 9, 1);

-- ============================================================================
-- 脚本结束 · 共 25 张表（P0×16 / P1×8 / 域级字典×1）+ 初始字典数据
-- 自查: 括号/逗号/分号配对、COMMENT 内无未转义单引号、JSON 默认值均为 NULL 或显式提供、
--       保留字规避(statement→settle_status 更名/表名带 pur_ 前缀)、
--       流水类4表(pur_supply_price_log/pur_order_change/pur_statement_item/pur_payment_verify)无软删例外、
--       单据类无 is_deleted 逐表核对 DB-00 §3
-- ============================================================================
