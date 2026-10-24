-- ============================================================================
-- DB-D11 报表域建表脚本（oms_report）
-- 文档编号: DB-D11 · 版本 V1.0 · 2026-10-24 · MySQL 8.0 可执行 DDL
-- 上游契约: DB-00 数据库设计总册（schema=oms_report / 表前缀 rpt_ / 公共字段 / 不建物理外键）
-- 需求依据: SRS-D11.01 固定报表(P1·M3) / SRS-D11.02 BI数据供给(P1·M3后段) / SRS-D11.03 履约监控看板(P1·M2) §6 数据字段
-- ----------------------------------------------------------------------------
-- 执行顺序:
--   1) CREATE DATABASE oms_report
--   2) 治理层: rpt_indicator_dict / rpt_snapshot_task
--   3) 销售类: rpt_sales_daily / rpt_sales_monthly / rpt_product_sale_rank / rpt_platform_compare
--   4) 库存类: rpt_stock_snapshot / rpt_stock_turnover / rpt_stock_age / rpt_near_expire / rpt_slow_moving / rpt_stockout
--   5) 履约类: rpt_fulfill_sla / rpt_audit_perf / rpt_timeout_alert
--   6) 售后: rpt_aftersale
--   7) 毛利服务费: rpt_profit / rpt_service_fee
--   8) BI宽表与推送: rpt_order_wide / rpt_stock_wide / rpt_settlement_wide / rpt_bi_push_log
--   9) 监控层: rpt_monitor_metric / rpt_alert_claim
--  10) 初始字典数据 INSERT: rpt_indicator_dict（指标口径字典 V1.0 基线 24 项 = SRS-D11.01 §5.1 全量）
-- 依赖: 仅本 schema；跨域为逻辑外键 LFK（应用层校验），不建物理外键
-- 红线: 报表域对业务库只读（从库）；本 schema 由快照/ETL/聚合任务写入，任何报表不得回写业务库
-- 分区约定: rpt_order_wide / rpt_stock_wide / rpt_stock_snapshot / rpt_monitor_metric 为结构基线表，
--           月分区由 DBA 脚本预建、调度滚动维护（DB-00 §1.3）；分钟行在线7天/小时行90天过期清理
-- 保留字规避: 排行列 rank_no（禁用 rank）；指标值列 metric_value（避免 value）
-- 快照/汇总/宽表类: 无 is_deleted / version（版本语义=snapshot_version 列，重跑+1旧版留档）
-- 命名/类型基线: 见 DB-00 §2/§6；utf8mb4 / utf8mb4_0900_ai_ci / InnoDB
-- ============================================================================

CREATE DATABASE IF NOT EXISTS oms_report DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE oms_report;

-- ============================================================================
-- 一、治理层（D11.01）
-- ============================================================================

-- 1. 指标口径字典（D11.01 FR-08 · P1·M3）★唯一事实源（凯淳原创，商派口径散落代码无字典）
CREATE TABLE rpt_indicator_dict (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id    BIGINT UNSIGNED NOT NULL COMMENT '租户ID(内部租户=1)',
  metric_code  VARCHAR(32)     NOT NULL COMMENT '指标编码(唯一):M-S01有效订单量/M-S02 GMV/M-S03客户实付/M-S04客单价/M-S05退款率/M-S06销售收入/M-I01五口径余额/M-I02周转率/M-I03库龄/M-I04库存货值/M-I05缺货账龄/M-F01审单时效/M-F02队列停留/M-F03推仓时效/M-F04出库时效/M-F05发货时效/M-F06签收时效/M-F07自动审单通过率/M-A01售后率/M-A02良不良比/M-A03售后处理时效/M-P01毛利/M-P02毛利率/M-P03服务费收入',
  metric_name  VARCHAR(128)    NOT NULL COMMENT '指标名称',
  category     VARCHAR(16)     NOT NULL COMMENT '分类:sale=销售,stock=库存,fulfill=履约,aftersale=售后,profit=毛利服务费,monitor=监控(监控口径与经营口径差异明示)',
  biz_define   VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '业务定义',
  formula      VARCHAR(1024)   NOT NULL COMMENT '计算公式(如M-S02:SUM(行paid_amount+platform_subsidy)+freight)',
  source_table VARCHAR(512)    NOT NULL COMMENT '数据来源表(schema.table或接口编号,如oms_order.ord_order/IF-D03.03-08)',
  caliber_note VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '口径标注:双口径归属(客户实付/平台承担)/时点归属(付款日/退款成功日/完成日)/跨期说明',
  dict_version VARCHAR(16)     NOT NULL DEFAULT 'v1.0' COMMENT '字典版本(FR-08b产品+财务+数据三方评审后递增)',
  effect_from  DATE            NOT NULL COMMENT '生效日期(口径变更只对未来数据生效,历史快照不重算;报表页脚标注分界)',
  metric_owner VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '指标负责人',
  status       TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=历史,3=废止',
  ext_json     JSON            NULL DEFAULT NULL COMMENT '扩展(关联报表清单/BI宽表字段映射)',
  owner_id     BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(配置表免填=0)',
  create_time  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version      INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted   TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_indicator_dict_code (metric_code, dict_version),
  KEY idx_rpt_indicator_dict_cat (category, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='指标口径字典(D11.01,P1·M3,全系统报表指标唯一事实源)';

-- 2. 快照任务依赖链与重跑记录（D11.01 FR-06 · P1·M3）← SRS §6.3 rpt_snapshot_version 扩展；只增+状态推进无软删
CREATE TABLE rpt_snapshot_task (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  task_bn        VARCHAR(32)     NOT NULL COMMENT '任务号(唯一,Redis发号:日期+RPT+序列)',
  domain         VARCHAR(32)     NOT NULL COMMENT '快照域:sales=销售,product_rank=商品排行,fulfill=履约,aftersale=售后,stock_rpt=库存报表汇总,agg_monthly=月汇总派生,profit=毛利,bi_order_wide/bi_stock_wide/bi_settle_wide=宽表ETL,bi_push=推送',
  biz_date       DATE            NOT NULL COMMENT '业务日期(日切归属日)',
  version        INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '快照版本(重跑+1旧版留档可回滚;下游表snapshot_version引用此值)',
  depends_on     JSON            NULL DEFAULT NULL COMMENT '上游依赖任务集(task_bn数组,DAG边,全部就绪才执行;D01.02编排)',
  status         TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=待执行,2=生成中,3=就绪,4=失败,5=待人工复核(行数较7日均值波动>50%),6=已重跑替代',
  row_count      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '快照行数',
  source_count   BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '源库COUNT(*)(行数校验±0)',
  checksum       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '校验和(金额SUM哈希±0.01;库存域=inv_stock_snapshot侧checksum锚)',
  amount_total   DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '金额合计(与源库SUM比对)',
  start_time     DATETIME(3)     NULL DEFAULT NULL COMMENT '开始时间',
  finish_time    DATETIME(3)     NULL DEFAULT NULL COMMENT '完成时间(单任务超时默认30分钟告警FR-06c)',
  retry_count    TINYINT         NOT NULL DEFAULT 0 COMMENT '自动重试次数(退避重试2次仍失败→告警人工)',
  rerun_flag     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '是否重跑批次:0=否,1=是',
  rerun_operator VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '重跑发起人(权限=报表管理员,D10.06审计)',
  rerun_reason   VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '重跑原因(必填FR-06d)',
  err_msg        VARCHAR(1024)   NOT NULL DEFAULT '' COMMENT '失败原因(联动上游域排查提示)',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_snapshot_task (task_bn),
  UNIQUE KEY uk_rpt_snapshot_task_domain (domain, biz_date, version),
  KEY idx_rpt_snapshot_task_status (status, biz_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='快照任务依赖链与重跑记录(D11.01,P1·M3,DAG台账)';

-- ============================================================================
-- 二、销售类（D11.01 FR-01）
-- ============================================================================

-- 3. 销售日快照（D11.01 FR-01/06a · P1·M3）← 商派 ome_salestatistics 改造:+货主/品牌维度+双口径分列+版本化
CREATE TABLE rpt_sales_daily (
  id                     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id              BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  stat_date              DATE            NOT NULL COMMENT '统计日期(按付款日归属,M-S01)',
  platform               VARCHAR(32)     NOT NULL COMMENT '平台码:tmall=天猫,taobao=淘宝,jd=京东,douyin=抖音,pdd=拼多多,xhs=小红书,wechat=微信,other=其他(gw_shop枚举同源)',
  shop_id                BIGINT UNSIGNED NOT NULL COMMENT '店铺(四维①) LFK→oms_gateway.gw_shop',
  brand_id               BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '品牌(四维②,0=未归属) LFK→oms_stock.inv_brand',
  owner_id               BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(四维③,门户行隔离键) LFK→oms_org.org_owner',
  branch_id              BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '仓(四维④,销售快照默认0不分仓) LFK→oms_fulfill.ful_branch',
  gmv                    DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT 'GMV·平台承担口径=SUM(paid_amount+platform_subsidy)+freight(M-S02)',
  paid_amount            DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '客户实付金额=SUM(paid_amount)+freight(M-S03);双口径强制分列禁止单口径销售额(FR-01b)',
  platform_subsidy       DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '平台承担金额(双口径差额勾稽列)',
  order_count            INT             NOT NULL DEFAULT 0 COMMENT '有效订单量=付款订单数-整单取消数,拆单不重复计按订单头(M-S01/FR-01c)',
  cancel_count           INT             NOT NULL DEFAULT 0 COMMENT '整单取消量',
  item_count             INT             NOT NULL DEFAULT 0 COMMENT '商品件数(SUM行数量)',
  avg_order_amount       DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '客单价=GMV/有效订单量(M-S04;汇总行按分子分母重算,禁止比率平均FR-07b)',
  refund_amount_customer DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '退款金额·客户实付口径(按退款成功日归属,M-S05分子)',
  refund_amount_platform DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '退款金额·平台承担口径(冲减单列FR-04b)',
  refund_count           INT             NOT NULL DEFAULT 0 COMMENT '退款笔数',
  refund_rate            DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '退款率=refund_amount_customer/gmv(M-S05,分子按退款成功日分母按付款日,跨期口径字典明示)',
  gmv_dod                DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT 'GMV环比·前日(快照固化)',
  gmv_wow                DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT 'GMV环比·上周同日(快照固化)',
  snapshot_version       INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '快照版本 LFK→rpt_snapshot_task.version',
  ready_time             DATETIME(3)     NULL DEFAULT NULL COMMENT '数据就绪时间(页头「数据截至」透出FR-06e)',
  create_time            DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time            DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_sales_daily (stat_date, platform, shop_id, brand_id, owner_id, snapshot_version),
  KEY idx_rpt_sales_daily_owner (owner_id, stat_date),
  KEY idx_rpt_sales_daily_shop (shop_id, stat_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='销售日快照(D11.01,P1·M3,日×平台×店铺×品牌×货主)';

-- 4. 销售月汇总（D11.01 FR-01 · P1·M3）rpt_sales_daily 按月派生（DAG汇总层）
CREATE TABLE rpt_sales_monthly (
  id                     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id              BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  stat_month             CHAR(7)         NOT NULL COMMENT '统计月份(YYYY-MM)',
  platform               VARCHAR(32)     NOT NULL COMMENT '平台码(同日快照枚举)',
  shop_id                BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺(四维①)',
  brand_id               BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '品牌(四维②)',
  owner_id               BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(四维③)',
  branch_id              BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '仓(四维④,默认0)',
  gmv                    DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '月GMV·平台承担口径(M-S02)',
  paid_amount            DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '月客户实付(M-S03)',
  platform_subsidy       DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '月平台承担金额',
  order_count            INT             NOT NULL DEFAULT 0 COMMENT '月有效订单量(M-S01)',
  cancel_count           INT             NOT NULL DEFAULT 0 COMMENT '月整单取消量',
  avg_order_amount       DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '月客单价(M-S04)',
  refund_amount_customer DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '月退款金额·客户实付口径',
  refund_amount_platform DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '月退款金额·平台承担口径',
  refund_rate            DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '月退款率(M-S05)',
  gmv_mom                DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '月环比(vs上月)',
  gmv_yoy                DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '年同比(vs去年同月)',
  snapshot_version       INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '快照版本(月内滚动重算随版本+1)',
  create_time            DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time            DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_sales_monthly (stat_month, platform, shop_id, brand_id, owner_id, snapshot_version),
  KEY idx_rpt_sales_monthly_owner (owner_id, stat_month)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='销售月汇总(D11.01,P1·M3)';

-- 5. 商品销售排行快照（D11.01 FR-01 · P1·M3）← 商派 products_sale/sale_products 改造;排名列 rank_no 规避保留字 rank
CREATE TABLE rpt_product_sale_rank (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  stat_date        DATE            NOT NULL COMMENT '统计日期(付款日归属)',
  window_type      TINYINT         NOT NULL DEFAULT 1 COMMENT '汇总窗口:1=当日,2=近7天滚动,3=近30天滚动,4=近90天滚动(可配,排行报表取2/3/4)',
  bm_id            BIGINT UNSIGNED NOT NULL COMMENT '基础物料 LFK→oms_stock.inv_material',
  sm_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '销售物料 LFK→oms_stock.inv_sales_material(0=跨店铺bm聚合行)',
  goods_name       VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '商品名快照(防档案变更影响历史)',
  shop_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺(四维①)',
  brand_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '品牌(四维②,冗余自物料档案)',
  owner_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(四维③,冗余自物料档案)',
  sale_num         BIGINT          NOT NULL DEFAULT 0 COMMENT '销量(SUM行数量)',
  gmv              DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT 'GMV·平台承担口径(M-S02)',
  paid_amount      DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '客户实付(M-S03)',
  refund_num       BIGINT          NOT NULL DEFAULT 0 COMMENT '退款量',
  refund_amount    DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '退款金额·客户实付口径',
  refund_rate      DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '退款率(M-S05)',
  rank_no          INT             NOT NULL DEFAULT 0 COMMENT '排行名次(窗口内降序TOP N固化;规避MySQL8保留字rank)',
  rank_type        TINYINT         NOT NULL DEFAULT 1 COMMENT '排行口径:1=按GMV,2=按销量,3=按实付,4=按退款率(SC-03多榜)',
  snapshot_version INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '快照版本',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_product_sale_rank (stat_date, window_type, rank_type, bm_id, sm_id, shop_id, owner_id, snapshot_version),
  KEY idx_rpt_product_sale_rank_top (stat_date, window_type, rank_type, rank_no),
  KEY idx_rpt_product_sale_rank_bm (bm_id, stat_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='商品销售排行快照(D11.01,P1·M3,SRS §6.1 rpt_sale_goods)';

-- 6. 平台对比月表（D11.01 FR-01 · P1·M3）← 商派 cat_sale_statis 对比思想平移
CREATE TABLE rpt_platform_compare (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  stat_month       CHAR(7)         NOT NULL COMMENT '统计月份(YYYY-MM)',
  platform         VARCHAR(32)     NOT NULL COMMENT '平台码(同销售快照枚举)',
  owner_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(0=全货主汇总行;门户按本货主行过滤)',
  gmv              DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '平台月GMV(M-S02)',
  paid_amount      DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '平台月客户实付(M-S03)',
  order_count      INT             NOT NULL DEFAULT 0 COMMENT '平台月有效订单量(M-S01)',
  avg_order_amount DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '平台月客单价(M-S04)',
  refund_rate      DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '平台月退款率(M-S05)',
  gmv_share        DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT 'GMV占比=本平台/全平台(同owner_id范围)',
  gmv_mom          DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '月环比',
  snapshot_version INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '快照版本',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_platform_compare (stat_month, platform, owner_id, snapshot_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='平台对比月表(D11.01,P1·M3)';

-- ============================================================================
-- 三、库存类（D11.01 FR-02）
-- ============================================================================

-- 7. 库存报表口径日切汇总（D11.01 FR-02 · P1·M3）← 商派 branch_product_stock_detail(day1~31平铺)改造
-- 边界: oms_stock.inv_stock_snapshot=记账快照权威源; 本表=报表口径汇总(消费inv快照+成本快照,不作记账依据); 校验锚=inv侧checksum(±0)
CREATE TABLE rpt_stock_snapshot (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  stat_date        DATE            NOT NULL COMMENT '快照日期(日切)',
  branch_id        BIGINT UNSIGNED NOT NULL COMMENT '仓(三元维度①) LFK→oms_fulfill.ful_branch',
  bm_id            BIGINT UNSIGNED NOT NULL COMMENT '基础物料(三元维度②) LFK→oms_stock.inv_material',
  owner_id         BIGINT UNSIGNED NOT NULL COMMENT '货主(三元维度③) LFK→oms_org.org_owner',
  brand_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '品牌(冗余自物料档案)',
  cat_id           BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '分类 LFK→oms_stock.inv_material_cat',
  shop_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺(库存维度默认0不分店铺)',
  store_num        INT             NOT NULL DEFAULT 0 COMMENT '实际库存(五口径①,照录inv快照,M-I01)',
  available_num    INT             NOT NULL DEFAULT 0 COMMENT '可用库存(五口径②,派生值照录不另算FR-02a)',
  freeze_num       INT             NOT NULL DEFAULT 0 COMMENT '锁定库存(五口径③)',
  arrive_num       INT             NOT NULL DEFAULT 0 COMMENT '在途库存(五口径④)',
  defective_num    INT             NOT NULL DEFAULT 0 COMMENT '次品库存(五口径⑤)',
  unit_cost        DECIMAL(18,4)   NOT NULL DEFAULT 0 COMMENT '移动加权均价(D04.07量价双快照照录)',
  stock_value      DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '库存货值(M-I04):买断=均价×实际(凯淳存货);代销=数量×settle_price(代管货值非存货FR-02b)',
  owner_type       TINYINT         NOT NULL DEFAULT 1 COMMENT '货主类型冗余:1=买断,2=代销,3=经销商DEALER_TC(P2预留)(货值口径分流标注)',
  same_code_group  VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '同货号跨货主组(FR-02c合并视角聚合键,D04.01契约:运营看总货财务分货主看账)',
  snapshot_version INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '快照版本(校验锚=inv_stock_snapshot checksum,±0)',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_stock_snapshot (stat_date, branch_id, bm_id, owner_id, snapshot_version),
  KEY idx_rpt_stock_snapshot_owner (owner_id, stat_date),
  KEY idx_rpt_stock_snapshot_group (same_code_group, stat_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='库存报表口径日切汇总(D11.01,P1·M3,消费inv_stock_snapshot)';

-- 8. 库存周转率月表（D11.01 FR-02 · P1·M3, M-I02）
CREATE TABLE rpt_stock_turnover (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  stat_month       CHAR(7)         NOT NULL COMMENT '统计月份(期间=自然月,M-I02口径)',
  owner_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(0=汇总行)',
  branch_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '仓(0=汇总行)',
  cat_id           BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '分类(0=汇总行)',
  brand_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '品牌',
  shop_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺(周转默认0)',
  outbound_cost    DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '当期销售出库成本(D04.07出库结转,成本口径非售价)',
  begin_value      DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '期初库存货值(月初日切快照)',
  end_value        DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '期末库存货值(月末日切快照)',
  avg_value        DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '平均库存货值=(期初+期末)/2',
  turnover_rate    DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '周转率=outbound_cost/avg_value(M-I02;avg=0置0并标注)',
  turnover_days    DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '周转天数=期间天数/周转率',
  snapshot_version INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '快照版本',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_stock_turnover (stat_month, owner_id, branch_id, cat_id, brand_id, snapshot_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='库存周转率月表(D11.01,P1·M3)';

-- 9. 库龄分析日表（D11.01 FR-02 · P1·M3, M-I03）
CREATE TABLE rpt_stock_age (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  stat_date        DATE            NOT NULL COMMENT '统计日期',
  owner_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主',
  branch_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '仓',
  brand_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '品牌',
  cat_id           BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '分类',
  shop_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺(默认0)',
  age_bucket       VARCHAR(16)     NOT NULL COMMENT '库龄档:b0_30=0-30天,b31_60=31-60天,b61_90=61-90天,b91_180=91-180天,b180p=>180天(边界可配;库龄=快照日-入库日,批次优先无批次取记账行首入日)',
  stock_num        BIGINT          NOT NULL DEFAULT 0 COMMENT '该档实际库存数量合计',
  stock_value      DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '该档货值合计(M-I04口径)',
  num_ratio        DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '数量占比(档内/全量)',
  value_ratio      DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '货值占比',
  snapshot_version INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '快照版本',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_stock_age (stat_date, owner_id, branch_id, cat_id, brand_id, age_bucket, snapshot_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='库龄分析日表(D11.01,P1·M3)';

-- 10. 临期库存日表（D11.01 FR-02 · P1·M3, 源 D04.09 批次）
CREATE TABLE rpt_near_expire (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  stat_date        DATE            NOT NULL COMMENT '统计日期',
  branch_id        BIGINT UNSIGNED NOT NULL COMMENT '仓(三元维度①)',
  bm_id            BIGINT UNSIGNED NOT NULL COMMENT '基础物料(三元维度②)',
  owner_id         BIGINT UNSIGNED NOT NULL COMMENT '货主(三元维度③)',
  shop_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺(四维①,默认0)',
  brand_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '品牌(四维②)',
  batch_no         VARCHAR(64)     NOT NULL COMMENT '批次号 LFK→oms_stock.inv_batch',
  expire_date      DATE            NOT NULL COMMENT '到期日(批次效期档案)',
  remain_days      INT             NOT NULL DEFAULT 0 COMMENT '剩余天数=expire_date-stat_date',
  expire_level     TINYINT         NOT NULL DEFAULT 1 COMMENT '临期级别:1=黄,2=橙,3=红(D04.09 FR-03a阈值规则)',
  batch_num        INT             NOT NULL DEFAULT 0 COMMENT '批次库存数量',
  stock_value      DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '批次货值(M-I04)',
  disposal_status  TINYINT         NOT NULL DEFAULT 0 COMMENT '处置状态:0=未处置,1=处置中,2=已处置(退仓/报废/促销),3=已过期(联动D04.09处置单inv_expire_disposal)',
  snapshot_version INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '快照版本',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_near_expire (stat_date, branch_id, bm_id, owner_id, batch_no, snapshot_version),
  KEY idx_rpt_near_expire_level (expire_level, remain_days)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='临期库存日表(D11.01,P1·M3)';

-- 11. 滞销日表（D11.01 FR-02 · P1·M3）← 商派 analysis_stocknsale+zero_sale 改造
CREATE TABLE rpt_slow_moving (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  stat_date          DATE            NOT NULL COMMENT '统计日期',
  branch_id          BIGINT UNSIGNED NOT NULL COMMENT '仓(三元维度①)',
  bm_id              BIGINT UNSIGNED NOT NULL COMMENT '基础物料(三元维度②)',
  owner_id           BIGINT UNSIGNED NOT NULL COMMENT '货主(三元维度③)',
  shop_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺',
  brand_id           BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '品牌',
  slow_days          INT             NOT NULL DEFAULT 0 COMMENT '滞销天数=stat_date-最近出库日(M天无动销判定,D04.10规则可配)',
  last_outbound_date DATE            NULL DEFAULT NULL COMMENT '最近出库日(NULL=从未动销)',
  stock_num          INT             NOT NULL DEFAULT 0 COMMENT '当前实际库存量',
  stock_value        DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '滞销货值(按货值排序主列SC-03)',
  sale_num_90d       INT             NOT NULL DEFAULT 0 COMMENT '近90天销量(0=零销售)',
  suggest_status     TINYINT         NOT NULL DEFAULT 0 COMMENT '处置建议状态:0=无建议,1=建议已生成待处理,2=已采纳,3=已忽略(LFK→oms_stock.inv_replenish_suggestion)',
  suggest_bn         VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '关联建议单号',
  snapshot_version   INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '快照版本',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_slow_moving (stat_date, branch_id, bm_id, owner_id, snapshot_version),
  KEY idx_rpt_slow_moving_value (owner_id, stat_date, stock_value)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='滞销日表(D11.01,P1·M3)';

-- 12. 缺货准实时表（D11.01 FR-02 · P1·M3, 从库分钟级缓存,非日终快照: snapshot_version恒=0标识准实时口径）
CREATE TABLE rpt_stockout (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id            BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  stat_date            DATE            NOT NULL COMMENT '刷新归属日期',
  refresh_time         DATETIME(3)     NOT NULL COMMENT '本次刷新时间(分钟级,准实时口径标注)',
  shop_id              BIGINT UNSIGNED NOT NULL COMMENT '店铺(四维①)',
  bm_id                BIGINT UNSIGNED NOT NULL COMMENT '基础物料',
  owner_id             BIGINT UNSIGNED NOT NULL COMMENT '货主(四维③)',
  branch_id            BIGINT UNSIGNED NOT NULL COMMENT '仓(四维④)',
  brand_id             BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '品牌(四维②)',
  shortage_num         INT             NOT NULL DEFAULT 0 COMMENT '缺口量(需求-可售)',
  shortage_order_count INT             NOT NULL DEFAULT 0 COMMENT '缺货订单数(ord_stockout未解除行)',
  age_level            TINYINT         NOT NULL DEFAULT 1 COMMENT '缺货账龄分级:1=>24h,2=>48h,3=>72h(M-I05,以缺货明细创建时间起算,D03.09 FR-04d)',
  first_shortage_time  DATETIME(3)     NOT NULL COMMENT '首次缺货标记时间(账龄起算点)',
  suggest_status       TINYINT         NOT NULL DEFAULT 0 COMMENT '补货建议状态:0=无,1=已生成,2=已采纳(联动D04.10)',
  source_ref           VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '来源缺货明细单号 LFK→oms_order.ord_stockout',
  snapshot_version     INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '快照版本(恒=0标识准实时口径)',
  create_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  KEY idx_rpt_stockout_refresh (stat_date, refresh_time),
  KEY idx_rpt_stockout_sku (shop_id, bm_id, stat_date),
  KEY idx_rpt_stockout_age (age_level, first_shortage_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='缺货准实时表(D11.01,P1·M3,从库分钟级缓存刷新)';

-- ============================================================================
-- 四、履约类（D11.01 FR-03）
-- ============================================================================

-- 13. 履约时效日快照（D11.01 FR-03/06a · P1·M3, SRS §6.2 rpt_fulfill_daily）← 商派 logistics_analysts 改造
CREATE TABLE rpt_fulfill_sla (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id            BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  stat_date            DATE            NOT NULL COMMENT '统计日期(各环节按业务归属日,M-F族口径)',
  shop_id              BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺(四维①)',
  branch_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '仓(四维④,0=店铺级汇总行)',
  owner_id             BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(四维③)',
  brand_id             BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '品牌(四维②)',
  wms_id               BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'WMS LFK→oms_fulfill.ful_wms(0=不分WMS汇总)',
  audit_auto_count     INT             NOT NULL DEFAULT 0 COMMENT '自动审单量(D03.02供数)',
  audit_manual_count   INT             NOT NULL DEFAULT 0 COMMENT '人工审核量',
  audit_pass_rate      DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '自动审单通过率=自动通过/投审(M-F07,按投审日归属)',
  audit_dur_avg        INT             NOT NULL DEFAULT 0 COMMENT '人工审单时效均值·秒(M-F01,分派→审核终态,口径以D03.03 §5.4为准)',
  audit_dur_p90        INT             NOT NULL DEFAULT 0 COMMENT '人工审单时效P90·秒',
  queue_dur_avg        INT             NOT NULL DEFAULT 0 COMMENT '队列停留时效均值·秒(M-F02,付款→审核终态,SLA考核口径含待分派)',
  push_dur_avg         INT             NOT NULL DEFAULT 0 COMMENT '推仓时效均值·秒(M-F03,发货单生成→WMS推送成功,多轮取首轮)',
  push_dur_p90         INT             NOT NULL DEFAULT 0 COMMENT '推仓时效P90·秒',
  push_fail_count      INT             NOT NULL DEFAULT 0 COMMENT '推送失败量(D09.02事件,失败原因分布见reason_dist)',
  outbound_dur_avg     INT             NOT NULL DEFAULT 0 COMMENT '出库时效均值·秒(M-F04,推送成功→出库回传,分批取末批)',
  outbound_dur_p90     INT             NOT NULL DEFAULT 0 COMMENT '出库时效P90·秒',
  callback_delay_count INT             NOT NULL DEFAULT 0 COMMENT '回传延迟量(>N小时阈值可配)',
  ship_24h_rate        DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '发货≤24h占比(M-F05,付款→发货确认,部分发货取首包,平台考核口径)',
  ship_48h_rate        DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '发货24-48h占比',
  ship_over48h_count   INT             NOT NULL DEFAULT 0 COMMENT '发货>48h单量(平台考核红线)',
  sign_dur_avg         INT             NOT NULL DEFAULT 0 COMMENT '签收时效均值·秒(M-F06,发货→签收,无轨迹单不计入分母)',
  overtime_order_count INT             NOT NULL DEFAULT 0 COMMENT '超时单量(付款超阈值未发货,店铺级阈值默认48h可配)',
  reason_dist          JSON            NULL DEFAULT NULL COMMENT '卡点归因分布:{"exception":n,"audit":n,"shortage":n,"pause":n,"push_fail":n,"wms_out":n,"unknown":n}(SRS §5.3优先级首个命中:异常>审单>缺货>暂停>推仓失败>WMS出库)',
  snapshot_version     INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '快照版本',
  create_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_fulfill_sla (stat_date, shop_id, branch_id, wms_id, owner_id, snapshot_version),
  KEY idx_rpt_fulfill_sla_owner (owner_id, stat_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='履约时效日快照(D11.01,P1·M3,五段时效分布呈现)';

-- 14. 审单员绩效日表（D11.01 FR-03 · P1·M3, 消费 D03.03 audit_performance,口径以其§5.4为准;仅统计不强制排名）
CREATE TABLE rpt_audit_perf (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  stat_date        DATE            NOT NULL COMMENT '统计日期',
  auditor_id       BIGINT UNSIGNED NOT NULL COMMENT '审核员 LFK→oms_org.org_account',
  audit_group_id   BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '审核组 LFK→oms_order.ord_audit_group',
  shop_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺',
  owner_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主',
  brand_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '品牌',
  handle_count     INT             NOT NULL DEFAULT 0 COMMENT '人工处理量(审核终态单数)',
  pass_count       INT             NOT NULL DEFAULT 0 COMMENT '通过量',
  reject_count     INT             NOT NULL DEFAULT 0 COMMENT '驳回量',
  reject_rate      DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '驳回率=驳回/处理量',
  dur_avg          INT             NOT NULL DEFAULT 0 COMMENT '平均处理时效·秒(分派→终态,M-F01)',
  dur_p90          INT             NOT NULL DEFAULT 0 COMMENT '处理时效P90·秒',
  queue_dur_avg    INT             NOT NULL DEFAULT 0 COMMENT '队列停留均值·秒(M-F02)',
  overtime_count   INT             NOT NULL DEFAULT 0 COMMENT '超时单数(audit.task.overtime事件计数)',
  snapshot_version INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '快照版本',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_audit_perf (stat_date, auditor_id, shop_id, owner_id, snapshot_version),
  KEY idx_rpt_audit_perf_group (stat_date, audit_group_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='审单员绩效日表(D11.01,P1·M3)';

-- 15. 超时预警清单（D11.01 FR-03 · P1·M3, 准实时:从库10分钟缓存;一行一订单幂等刷新,无软删）
CREATE TABLE rpt_timeout_alert (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  order_id         BIGINT UNSIGNED NOT NULL COMMENT '订单 LFK→oms_order.ord_order',
  order_bn         VARCHAR(32)     NOT NULL COMMENT '订单号(冗余,清单直显)',
  shop_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺(四维①)',
  branch_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '仓(四维④)',
  owner_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(四维③)',
  brand_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '品牌(四维②)',
  pay_time         DATETIME(3)     NOT NULL COMMENT '付款时间(超时起算点)',
  timeout_hours    INT             NOT NULL DEFAULT 0 COMMENT '已超时小时数=now-pay_time-阈值',
  threshold_hours  INT             NOT NULL DEFAULT 48 COMMENT '店铺级阈值快照(可配,默认48)',
  block_stage      VARCHAR(32)     NOT NULL COMMENT '卡点环节(SRS §5.3归因,首个命中):exception=异常(附类型),audit=审单(待审核/驳回),shortage=缺货,pause=暂停,push_fail=推仓失败,wms_out=WMS出库未回传,unknown=待排查(告警聚合)',
  block_ref        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '卡点关联单据号(异常单号/发货单号等,下钻跳转用)',
  status           TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=预警中,2=已解除(发货/取消),3=已升级(P0告警联动D11.03)',
  first_alert_time DATETIME(3)     NOT NULL COMMENT '首次进入清单时间',
  resolve_time     DATETIME(3)     NULL DEFAULT NULL COMMENT '解除时间',
  refresh_time     DATETIME(3)     NOT NULL COMMENT '最近刷新时间(10分钟缓存口径)',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_timeout_alert (order_id),
  KEY idx_rpt_timeout_alert_status (status, timeout_hours),
  KEY idx_rpt_timeout_alert_shop (shop_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='超时预警清单(D11.01,P1·M3,准实时订单明细)';

-- ============================================================================
-- 五、售后类（D11.01 FR-04）
-- ============================================================================

-- 16. 售后日快照（D11.01 FR-04/06a · P1·M3, SRS §6.3 rpt_aftersale_daily）← 商派 ome_salestatistics+ome_goodsrma 改造
CREATE TABLE rpt_aftersale (
  id                        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id                 BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  stat_date                 DATE            NOT NULL COMMENT '统计日期(按申请创建日归属,M-A01)',
  shop_id                   BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺(四维①)',
  owner_id                  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(四维③)',
  brand_id                  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '品牌(四维②,冗余自商品)',
  branch_id                 BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '仓(四维④,良不良比行有值)',
  bm_id                     BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '商品(0=店铺级汇总行)',
  reason_code               VARCHAR(32)     NOT NULL DEFAULT 'ALL' COMMENT '售后原因码(D05.01标准字典,平台码经D02.02映射后跨平台可比FR-04a;ALL=全原因汇总行)',
  apply_type                TINYINT         NOT NULL DEFAULT 0 COMMENT '售后类型:0=全部,1=仅退款,2=退货退款,3=换货,4=补发',
  denominator_type          TINYINT         NOT NULL DEFAULT 1 COMMENT '售后率分母口径:1=付款订单量(默认),2=发货订单量(字典明示,切换整表统一FR-04c)',
  apply_count               INT             NOT NULL DEFAULT 0 COMMENT '售后申请单数(含被拒,申请口径)',
  order_base_count          INT             NOT NULL DEFAULT 0 COMMENT '分母基数(按denominator_type取数快照固化)',
  aftersale_rate            DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '售后率=apply_count/order_base_count(M-A01)',
  refund_only_rate          DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '仅退款率(分列)',
  return_refund_rate        DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '退货退款率(分列)',
  refund_amount_customer    DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '退款金额·客户实付口径(D05.03退款台账,买家真金白银视角FR-04b)',
  refund_amount_platform    DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '退款金额·平台承担冲减(单列,对齐D08.01负向应收双口径)',
  refund_count              INT             NOT NULL DEFAULT 0 COMMENT '退款笔数',
  good_count                INT             NOT NULL DEFAULT 0 COMMENT '退货入库良品数(D05.02质检分流qc_completed事件)',
  defect_count              INT             NOT NULL DEFAULT 0 COMMENT '退货入库不良品数',
  defect_rate               DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '良不良比=不良/退货入库总数(M-A02,按质检完成日)',
  defect_disposal_dist      JSON            NULL DEFAULT NULL COMMENT '不良品处置状态分布:{"return_wh":n,"scrap":n,"pending":n}(退仓/报废/待处置)',
  audit_dur_p90             INT             NOT NULL DEFAULT 0 COMMENT '申请→审核时效P90·秒(M-A03)',
  refund_dur_p90            INT             NOT NULL DEFAULT 0 COMMENT '审核→退款时效P90·秒',
  over_sla_count            INT             NOT NULL DEFAULT 0 COMMENT '超SLA单量',
  platform_intervened_count INT             NOT NULL DEFAULT 0 COMMENT '平台介入单量(透传标记,资损观测占比列)',
  snapshot_version          INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '快照版本',
  create_time               DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time               DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_aftersale (stat_date, shop_id, owner_id, reason_code, apply_type, bm_id, branch_id, denominator_type, snapshot_version),
  KEY idx_rpt_aftersale_owner (owner_id, stat_date),
  KEY idx_rpt_aftersale_reason (stat_date, reason_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='售后日快照(D11.01,P1·M3)';

-- ============================================================================
-- 六、毛利与服务费（D11.01 FR-05，按货主类型分流）
-- ============================================================================

-- 17. 毛利月表·买断货主（D11.01 FR-05a · P1·M3, M-P01/02;代销货主自动切rpt_service_fee,门户不展示毛利）
CREATE TABLE rpt_profit (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  stat_month       CHAR(7)         NOT NULL COMMENT '统计月份',
  owner_id         BIGINT UNSIGNED NOT NULL COMMENT '货主(买断类型,D10.01档案分流依据)',
  shop_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺(0=汇总行)',
  brand_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '品牌',
  branch_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '仓',
  cat_id           BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '分类 LFK→oms_stock.inv_material_cat',
  bm_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '单品(0=分类/店铺级汇总行,三级下钻)',
  category_level   TINYINT         NOT NULL DEFAULT 1 COMMENT '汇总层级:1=货主总,2=店铺级,3=分类级,4=单品级(下钻链路标识)',
  revenue_customer DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '收入·客户实付口径(M-S06:SUM应收-SUM退款冲减,按订单完成日归属,D08.01)',
  revenue_platform DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '收入·平台承担口径对照列(FR-05a可切)',
  refund_deduct    DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '退款冲减额(已从收入扣除,明细列示)',
  sale_cost        DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '销售成本(D04.07出库结转:移动加权均价×出库量)',
  cost_return_back DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '退货成本冲回额(按原单成本快照非当期均价,单列勾稽AC-09)',
  freight          DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '运费(D08.04:关账期间=实际,未关账=预估)',
  freight_caliber  TINYINT         NOT NULL DEFAULT 1 COMMENT '运费口径:1=实际(已关账),2=预估(未关账,整表标注FR-05a)',
  gross_profit     DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '毛利=收入(客户实付)-销售成本-运费(M-P01)',
  gross_margin     DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '毛利率=毛利/收入(M-P02;收入=0不计算置0前端显—)',
  period_locked    TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '期间锁定:0=未关账(数据可能调整),1=已关账只读固化(D08.03联动FR-05d)',
  snapshot_version INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '快照版本',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_profit (stat_month, owner_id, shop_id, cat_id, bm_id, category_level, snapshot_version),
  KEY idx_rpt_profit_owner (owner_id, stat_month)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='毛利月表·买断货主(D11.01,P1·M3)';

-- 18. 代销服务费月表（D11.01 FR-05b · P1·M3, M-P03;不计算毛利——货权非凯淳）
CREATE TABLE rpt_service_fee (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  stat_month         CHAR(7)         NOT NULL COMMENT '结算周期月份',
  owner_id           BIGINT UNSIGNED NOT NULL COMMENT '货主(代销类型)',
  shop_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺',
  brand_id           BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '品牌',
  settle_bn          VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '结算单号 LFK→oms_finance.fin_settlement(空=周期货主级汇总行)',
  service_fee        DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '服务费收入(SUM结算单服务费D项含调整单,M-P03,按结算周期归属,计算轨迹可下钻)',
  fee_detail_json    JSON            NULL DEFAULT NULL COMMENT '服务费明细汇总:条款×模型×档位({"term_code":{"model":"rate","base":x,"rate":y,"amount":z}})',
  lend_trade_amount  DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '借调内部交易额(D04.05台账,D08.02第4要素)',
  net_amount         DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '结算净额',
  net_direction      TINYINT         NOT NULL DEFAULT 1 COMMENT '净额方向:1=凯淳应收,2=凯淳应付(双向呈现)',
  ledger_init        DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '台账滚动·期初',
  ledger_payable     DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '台账滚动·本期应结',
  ledger_paid        DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '台账滚动·本期已付',
  ledger_final       DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '台账滚动·期末',
  consignment_value  DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '代管货值余额(单列标注「代管,非凯淳存货」FR-05b,D04.07 inv_consignment_value供数)',
  snapshot_version   INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '快照版本',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_service_fee (stat_month, owner_id, settle_bn, snapshot_version),
  KEY idx_rpt_service_fee_owner (owner_id, stat_month)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='代销服务费月表(D11.01,P1·M3)';

-- ============================================================================
-- 七、BI 宽表与推送（D11.02）
-- 红线: OMS不做BI展示层;字段口径强制引用rpt_indicator_dict编码;schema只增不改;PIPL无买家明文
-- ============================================================================

-- 19. 订单宽表（D11.02 FR-01 · P1·M3后段, SRS §6.1 dws_order_wide）一行一订单行,upsert幂等
CREATE TABLE rpt_order_wide (
  id                     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id              BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  order_item_id          BIGINT UNSIGNED NOT NULL COMMENT '订单行 LFK→oms_order.ord_order_item(upsert主键,BI侧幂等消费)',
  order_id               BIGINT UNSIGNED NOT NULL COMMENT '订单头 LFK→oms_order.ord_order',
  order_bn               VARCHAR(32)     NOT NULL COMMENT 'OMS订单号',
  platform_order_bn      VARCHAR(64)     NOT NULL COMMENT '平台单号',
  platform               VARCHAR(32)     NOT NULL COMMENT '平台码(同销售快照枚举)',
  shop_id                BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺(四维①)',
  brand_id               BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '品牌(四维②)',
  owner_id               BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(四维③,行级)',
  branch_id              BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '仓(四维④,发货仓,未发货0)',
  order_type             TINYINT         NOT NULL DEFAULT 1 COMMENT '订单类型快照:1=普通,2=换货,3=补发,4=B2B(P2预留)等(ord_order.order_type值域)',
  create_way             VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '订单来源:api=拉单,manual=手工,import=导入,b2b=转入(P2),migration=迁移',
  order_time             DATETIME(3)     NULL DEFAULT NULL COMMENT '下单时间',
  pay_time               DATETIME(3)     NULL DEFAULT NULL COMMENT '付款时间',
  audit_status           TINYINT         NOT NULL DEFAULT 0 COMMENT '审核状态快照(ord_order.audit_status值域)',
  fulfill_status         TINYINT         NOT NULL DEFAULT 0 COMMENT '履约状态快照',
  pay_status             TINYINT         NOT NULL DEFAULT 0 COMMENT '支付状态快照',
  ship_status            TINYINT         NOT NULL DEFAULT 0 COMMENT '发货状态快照',
  buyer_id_hash          CHAR(64)        NOT NULL DEFAULT '' COMMENT '买家ID脱敏哈希(HMAC盲索引,PIPL不供明文)',
  receiver_province      VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '收货省(区域分析,不到区县以下)',
  receiver_city          VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '收货市',
  bm_id                  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '基础物料',
  sm_id                  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '销售物料',
  goods_name             VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '商品名快照(防档案变更影响历史)',
  num                    INT             NOT NULL DEFAULT 0 COMMENT '行数量',
  list_price             DECIMAL(18,4)   NOT NULL DEFAULT 0 COMMENT '吊牌价',
  deal_price             DECIMAL(18,4)   NOT NULL DEFAULT 0 COMMENT '成交单价',
  list_amount            DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '吊牌金额',
  shop_discount          DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '店铺优惠(行级分摊后快照)',
  platform_subsidy       DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '平台承担(行级分摊后快照)',
  paid_amount            DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '客户实付(行级分摊后,D03.01 §5.2 getDualAmount快照照录不重算)',
  freight                DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '运费(头级不分摊,整单冗余,口径标注列)',
  gmv                    DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT 'GMV=paid_amount+platform_subsidy(M-S02;行级不含freight头级单列)',
  audit_done_time        DATETIME(3)     NULL DEFAULT NULL COMMENT '审单完成时间',
  audit_mode             TINYINT         NOT NULL DEFAULT 0 COMMENT '审单方式:0=未审,1=自动,2=人工',
  auditor_id             BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '审核员(人工时) LFK→oms_org.org_account',
  delivery_bns           JSON            NULL DEFAULT NULL COMMENT '发货单号列表(一单多发货单JSON数组)',
  push_time              DATETIME(3)     NULL DEFAULT NULL COMMENT '推仓成功时间(M-F03)',
  outbound_time          DATETIME(3)     NULL DEFAULT NULL COMMENT '出库回传时间(M-F04,分批取末批)',
  ship_time              DATETIME(3)     NULL DEFAULT NULL COMMENT '发货确认时间(M-F05,部分发货取首包)',
  sign_time              DATETIME(3)     NULL DEFAULT NULL COMMENT '签收时间(M-F06,轨迹回传)',
  dur_audit_sec          INT             NOT NULL DEFAULT 0 COMMENT '审单时效·秒(预计算落列,口径同M-F族)',
  dur_push_sec           INT             NOT NULL DEFAULT 0 COMMENT '推仓时效·秒',
  dur_outbound_sec       INT             NOT NULL DEFAULT 0 COMMENT '出库时效·秒',
  dur_ship_sec           INT             NOT NULL DEFAULT 0 COMMENT '发货时效·秒(付款→发货,平台考核)',
  dur_sign_sec           INT             NOT NULL DEFAULT 0 COMMENT '签收时效·秒',
  has_aftersale          TINYINT         NOT NULL DEFAULT 0 COMMENT '有无售后:0=无,1=申请中,2=已完成',
  aftersale_type         TINYINT         NOT NULL DEFAULT 0 COMMENT '售后类型:0=无,1=仅退款,2=退货退款,3=换货,4=补发',
  refund_status          TINYINT         NOT NULL DEFAULT 0 COMMENT '退款状态:0=无,1=退款中,2=退款成功,3=退款关闭',
  refund_amount_customer DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '退款金额·客户实付口径(双口径)',
  refund_amount_platform DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '退款金额·平台承担口径',
  qc_good_flag           TINYINT         NOT NULL DEFAULT 0 COMMENT '退货良不良:0=未质检,1=良品,2=不良品(D05.02)',
  platform_intervened    TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '平台介入标记:0=否,1=是(资损观测)',
  lend_flag              TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '借调发货标记(D04.05透传)',
  lend_ledger_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '借调台账行 LFK→oms_stock.inv_lend_ledger',
  merge_parent_flag      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '合单母单标记(D03.05场景)',
  stat_date              DATE            NOT NULL COMMENT 'ETL归属业务日期(增量圈定日,分区键)',
  schema_version         VARCHAR(16)     NOT NULL DEFAULT 'v1' COMMENT '宽表schema版本(只增不改;破坏性变更升主版本双轨并行≥1月FR-05c)',
  etl_batch_id           VARCHAR(32)     NOT NULL DEFAULT '' COMMENT 'ETL批次 LFK→rpt_bi_push_log.batch_id(溯源)',
  snapshot_version       INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '快照版本(源快照重跑级联重推时+1)',
  create_time            DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time            DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_order_wide_item (order_item_id, stat_date),
  KEY idx_rpt_order_wide_date (stat_date, shop_id),
  KEY idx_rpt_order_wide_owner (owner_id, stat_date),
  KEY idx_rpt_order_wide_bn (order_bn)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='订单宽表(D11.02,P1·M3后段,一行一订单行,BI upsert幂等)';

-- 20. 库存宽表日切（D11.02 FR-02 · P1·M3后段, SRS §6.2 dws_stock_wide）日切×仓×SKU×货主全量切面
CREATE TABLE rpt_stock_wide (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  stat_date          DATE            NOT NULL COMMENT '快照日(日切,分区键)',
  branch_id          BIGINT UNSIGNED NOT NULL COMMENT '仓(三元粒度键①)',
  bm_id              BIGINT UNSIGNED NOT NULL COMMENT '基础物料(三元粒度键②)',
  owner_id           BIGINT UNSIGNED NOT NULL COMMENT '货主(三元粒度键③)',
  shop_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺(维度冗余,BI侧权限映射基础FR-07c)',
  brand_id           BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '品牌',
  cat_id             BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '分类',
  store_num          INT             NOT NULL DEFAULT 0 COMMENT '实际库存(五口径,D04.02契约照录,M-I01)',
  available_num      INT             NOT NULL DEFAULT 0 COMMENT '可用库存(派生值照录)',
  freeze_num         INT             NOT NULL DEFAULT 0 COMMENT '锁定库存',
  arrive_num         INT             NOT NULL DEFAULT 0 COMMENT '在途库存',
  defective_num      INT             NOT NULL DEFAULT 0 COMMENT '次品库存',
  safe_store         INT             NOT NULL DEFAULT 0 COMMENT '安全库存',
  unit_cost          DECIMAL(18,4)   NOT NULL DEFAULT 0 COMMENT '移动加权均价(D04.07)',
  stock_value        DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '货值:买断=均价×实际(凯淳存货);代销=代管货值(M-I04)',
  owner_type         TINYINT         NOT NULL DEFAULT 1 COMMENT '货主类型:1=买断,2=代销,3=经销商(P2预留)(货值口径区分列)',
  age_bucket         VARCHAR(16)     NOT NULL DEFAULT '' COMMENT '库龄档(M-I03,同rpt_stock_age档位枚举)',
  near_expire_yellow INT             NOT NULL DEFAULT 0 COMMENT '临期·黄级数量(D04.09三级汇总)',
  near_expire_orange INT             NOT NULL DEFAULT 0 COMMENT '临期·橙级数量',
  near_expire_red    INT             NOT NULL DEFAULT 0 COMMENT '临期·红级数量',
  near_expire_value  DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '临期货值合计(三级)',
  slow_moving_flag   TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '滞销标记:0=否,1=是(D04.10)',
  sale_num_7d        INT             NOT NULL DEFAULT 0 COMMENT '近7天销量(快照冗余免join)',
  sale_num_30d       INT             NOT NULL DEFAULT 0 COMMENT '近30天销量',
  schema_version     VARCHAR(16)     NOT NULL DEFAULT 'v1' COMMENT '宽表schema版本',
  etl_batch_id       VARCHAR(32)     NOT NULL DEFAULT '' COMMENT 'ETL批次 LFK→rpt_bi_push_log.batch_id',
  snapshot_version   INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '快照版本(一致性锚:行数=当日inv_stock_snapshot行数±0,五口径合计=inv侧checksum FR-02d)',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_stock_wide (stat_date, branch_id, bm_id, owner_id, snapshot_version),
  KEY idx_rpt_stock_wide_owner (owner_id, stat_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='库存宽表日切(D11.02,P1·M3后段,日切×仓×SKU×货主)';

-- 21. 结算宽表（D11.02 FR-03 · P1·M3后段, SRS §6.2 dws_settle_wide）货主×周期×版本一行,红冲多版本追加式
CREATE TABLE rpt_settlement_wide (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NOT NULL COMMENT '货主',
  owner_type       TINYINT         NOT NULL DEFAULT 1 COMMENT '货主类型:1=买断,2=代销,3=经销商(P2预留)',
  period_start     DATE            NOT NULL COMMENT '结算周期起',
  period_end       DATE            NOT NULL COMMENT '结算周期止',
  settle_bn        VARCHAR(32)     NOT NULL COMMENT '结算单号 LFK→oms_finance.fin_settlement',
  settle_version   INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '结算单版本(红冲重算+1,BI按最新版本生效,旧版本行不删可回放SC-05)',
  origin_settle_bn VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '原结算单号(红冲链引用)',
  redflush_flag    TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '红冲标记:0=正常,1=红冲单,2=被红冲原单',
  amt_receivable   DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '要素①应收货款(D08.02 FR-03a公式对应列)',
  amt_refund       DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '要素②退款冲减',
  amt_platform_fee DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '要素③平台扣费',
  amt_service_fee  DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '要素④服务费(M-P03)',
  amt_lend_trade   DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '要素⑤借调内部交易',
  amt_init_adjust  DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '要素⑥期初调整',
  amt_net          DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '结算净额(六要素公式,D08.02 FR-03a)',
  net_direction    TINYINT         NOT NULL DEFAULT 1 COMMENT '净额方向:1=凯淳应付货主,2=凯淳应收货主(双向呈现金额)',
  fee_detail_json  JSON            NULL DEFAULT NULL COMMENT '服务费明细:条款×模型×档位汇总(计算轨迹可下钻)',
  lend_detail_json JSON            NULL DEFAULT NULL COMMENT '借调交易明细汇总',
  ledger_init      DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '台账滚动·期初(fin_settle_ledger供数)',
  ledger_payable   DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '台账滚动·应结(对账锚±0.01)',
  ledger_paid      DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '台账滚动·已付',
  ledger_final     DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '台账滚动·期末',
  cost_memo        DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '成本参考列(买断货主内部结算行,供BI毛利分析,与D11.01毛利报表同源FR-03d)',
  status           TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=已归档,2=已红冲',
  confirm_time     DATETIME(3)     NULL DEFAULT NULL COMMENT '确认时间',
  stat_date        DATE            NOT NULL COMMENT 'ETL归属日期(事件到达日/兜底批日;触发=finance.settle.archived/redflushed事件+日批兜底)',
  schema_version   VARCHAR(16)     NOT NULL DEFAULT 'v1' COMMENT '宽表schema版本',
  etl_batch_id     VARCHAR(32)     NOT NULL DEFAULT '' COMMENT 'ETL批次 LFK→rpt_bi_push_log.batch_id',
  snapshot_version INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '快照版本',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_settlement_wide (settle_bn, settle_version),
  KEY idx_rpt_settlement_wide_owner (owner_id, period_start),
  KEY idx_rpt_settlement_wide_date (stat_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='结算宽表(D11.02,P1·M3后段,货主×周期×版本一行)';

-- 22. BI推送台账与对账记录（D11.02 FR-04/06 · P1·M3后段, SRS §6.3 bi_push_batch+bi_recon_record合并）台账类无软删
CREATE TABLE rpt_bi_push_log (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  batch_id        VARCHAR(32)     NOT NULL COMMENT '批次号(唯一,Redis发号)',
  table_name      VARCHAR(32)     NOT NULL COMMENT '宽表名:rpt_order_wide=订单宽表,rpt_stock_wide=库存宽表,rpt_settlement_wide=结算宽表',
  biz_date        DATE            NOT NULL COMMENT '业务日期',
  batch_type      TINYINT         NOT NULL DEFAULT 2 COMMENT '批次类型:1=全量(初始化/重建,分片+衔接日重叠1天),2=增量(日批+事件批),3=补推(人工触发可溯),4=重建(口径变更双轨)',
  batch_seq       INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '批次序号(批次唯一键成分)',
  shard_no        INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '分片号(全量按月分片,0=不分片)',
  shard_total     INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '总片数',
  row_count       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '批次行数(三级一致校验:圈定=输出=台账)',
  checksum        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '校验和(金额SUM哈希)',
  schema_version  VARCHAR(16)     NOT NULL DEFAULT 'v1' COMMENT '宽表schema版本',
  channel         TINYINT         NOT NULL DEFAULT 1 COMMENT '推送通道:1=文件OSS(Parquet/CSV+_SUCCESS标记),2=中间表(BI直连从库,PushChannel抽象切换)',
  oss_path        VARCHAR(255)    NOT NULL DEFAULT '' COMMENT 'OSS路径({bucket}/oms_bi/{table}/dt={date}/part-{n}.{ext},加密存储+ACL仅BI服务账号)',
  status          TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=加工中,2=已推送,3=对账平(闭环),4=对账不平(告警),5=失败,6=已补推替代',
  plan_time       DATETIME(3)     NULL DEFAULT NULL COMMENT '计划完成时间(SLA红线:T+1 10:00订单库存/事件后2小时结算)',
  start_time      DATETIME(3)     NULL DEFAULT NULL COMMENT '加工开始时间',
  finish_time     DATETIME(3)     NULL DEFAULT NULL COMMENT '推送完成时间',
  bi_receipt_time DATETIME(3)     NULL DEFAULT NULL COMMENT 'BI回执时间(无回执超时告警EF-D11.02-02)',
  recon_status    TINYINT         NOT NULL DEFAULT 0 COMMENT '对账状态:0=未对账,1=平,2=不平(连续2日升级数据负责人),3=无回执超时',
  recon_json      JSON            NULL DEFAULT NULL COMMENT '对账明细:[{"recon_type":"row_count|metric|checksum","oms_value":x,"bi_value":y,"diff":z,"pass":1}](三向勾稽§5.3:宽表↔快照ΣGMV±0.01/行数±0;宽表↔BI回执±0;不平四级回放定位)',
  alarm_id        VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '关联告警(不平/超时→D01.07)',
  operator        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '操作人(补推留痕,系统批=系统账号)',
  trigger_source  VARCHAR(32)     NOT NULL DEFAULT 'dag' COMMENT '触发源:dag=快照就绪事件(report.snapshot.ready),manual=人工补推,settle_event=结算归档事件,fallback=日批兜底',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_bi_push_log_batch (batch_id),
  UNIQUE KEY uk_rpt_bi_push_log_key (table_name, biz_date, batch_type, batch_seq),
  KEY idx_rpt_bi_push_log_status (status, recon_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='BI推送台账与对账记录(D11.02,P1·M3后段)';

-- ============================================================================
-- 八、监控看板层（D11.03，P1·M2——早于 D11.01/02 上线）
-- 红线: 监控=Redis实时计数为主,本域仅承载分钟级聚合落库+告警认领闭环,不走业务从库主查询
-- ============================================================================

-- 23. 监控指标注册与分钟级聚合（D11.03 FR-01/02 · P1·M2, SRS §6.1 monitor_metric+§6.3三级时序收敛单表）
CREATE TABLE rpt_monitor_metric (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  metric_code       VARCHAR(64)     NOT NULL COMMENT '指标编码:pull.watermark.lag=拉单水位落后,pull.buffer.backlog=缓冲积压,audit.queue.depth=待审队列深度,audit.auto.pass.rate=自动通过率(滚动1h),audit.throughput=审单吞吐,push.fail.count=推仓失败量(5min),push.recall.pending=叫回中未决,callback.delay.count=回传延迟量,sync.writeback.p95=回写延迟,freeze.overdue.24h/48h/72h=超期预占三档,exc.open.count=未闭环异常单,exc.overdue.count=超期异常单,wms.circuit.state=熔断状态,auth.expire.count=授权过期,waybill.segment.balance=号段余量,promo.session=大促会话行(承载会话窗口/阈值集/预案/峰值/战报)',
  metric_name       VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '指标名称(registry行必填)',
  domain            VARCHAR(16)     NOT NULL COMMENT '所属域:pull=拉单水位,audit=审单积压,push=推仓状态,sync=库存同步,freeze=预占账龄,exc=异常单,wms=WMS通道,auth=平台授权,waybill=面单打印(附属),promo=大促会话',
  period            VARCHAR(8)      NOT NULL COMMENT '行粒度:registry=注册元数据行,minute=分钟聚合(在线7天),hour=小时降采样(在线90天),day=日汇总(长期,大促同期对比源)',
  metric_type       VARCHAR(16)     NOT NULL DEFAULT '' COMMENT '指标类型(registry行):gauge=瞬时值,counter=累计,histogram=分布',
  unit              VARCHAR(16)     NOT NULL DEFAULT '' COMMENT '单位(单/分钟/秒/%/个)',
  dims_json         JSON            NULL DEFAULT NULL COMMENT 'registry行=维度组合声明(平台/店铺/仓/WMS/审核组/异常类型);时序行=维度值快照',
  dims_hash         CHAR(32)        NOT NULL DEFAULT '' COMMENT '维度组合哈希(时序粒度键;维度组合注册制控制基数,日增≈288万行)',
  redis_key_pattern VARCHAR(128)    NOT NULL DEFAULT '' COMMENT 'Redis key模式(registry行:mon:{域}.{指标}:{维度}:{时间分区},TTL 7天)',
  event_source      VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '事件来源(registry行,兜底通道:wms.outbound.push.failed/order.exception.created/stock.freeze_expired/audit.task.overtime等;双通道对账差异>5%埋点质量告警§5.3)',
  threshold_json    JSON            NULL DEFAULT NULL COMMENT '阈值规则集(registry行):{"yellow":x,"red":y,"sustain_min":2,"level_map":{"red":"P1"},"promo_set":{...}}(黄红×持续分钟防抖×P0/P1/P2映射×大促独立阈值集FR-06e)',
  caliber_note      VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '口径说明(registry行,「?」透出FR-01d;与经营口径差异明示:如通过率滚动1h vs 报表按投审日)',
  drill_route       VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '下钻链接(registry行,业务模块页面路由)',
  owner_group       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '负责人组(registry行,告警路由D01.07)',
  ts                DATETIME(3)     NOT NULL DEFAULT '1970-01-01 00:00:00.000' COMMENT '时序行时间点(分钟/小时/日桶起始;registry行=1970-01-01哨兵值参与唯一键)',
  metric_value      DECIMAL(18,4)   NOT NULL DEFAULT 0 COMMENT '时序值(gauge=切片值/counter=桶累计/histogram=聚合值;规避value命名)',
  max_value         DECIMAL(18,4)   NOT NULL DEFAULT 0 COMMENT '桶内最大(hour/day降采样列)',
  min_value         DECIMAL(18,4)   NOT NULL DEFAULT 0 COMMENT '桶内最小',
  p95_value         DECIMAL(18,4)   NOT NULL DEFAULT 0 COMMENT '桶内P95',
  sample_count      INT             NOT NULL DEFAULT 0 COMMENT '桶内样本数',
  alert_mark        TINYINT         NOT NULL DEFAULT 0 COMMENT '告警标注:0=无,1=告警触发点,2=恢复点(曲线叠加渲染FR-02d,alert_id关联经ext_json)',
  reg_status        TINYINT         NOT NULL DEFAULT 1 COMMENT '注册状态(registry行):1=启用,2=停用',
  ext_json          JSON            NULL DEFAULT NULL COMMENT '扩展(registry行=变更留痕/大促会话载荷:会话窗口/阈值集引用/plan_exec_log预案执行/peak_snapshot峰值/limit_switch_snapshot限流面板/war_report战报;时序行=alert_id关联)',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_monitor_metric_reg (metric_code, period, dims_hash, ts),
  KEY idx_rpt_monitor_metric_ts (metric_code, period, ts),
  KEY idx_rpt_monitor_metric_domain (domain, period, ts)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='监控指标注册与分钟级聚合(D11.03,P1·M2,Redis为主此为聚合落库)';

-- 24. 告警认领闭环记录（D11.03 FR-04/05 · P1·M2, SRS §6.2 monitor_alert+monitor_alert_action合并）无软删,全生命周期留痕
CREATE TABLE rpt_alert_claim (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  alert_id           VARCHAR(32)     NOT NULL COMMENT '告警ID(唯一,Redis发号)',
  metric_code        VARCHAR(64)     NOT NULL COMMENT '指标编码 LFK→rpt_monitor_metric(registry行)',
  dims_snapshot      JSON            NULL DEFAULT NULL COMMENT '触发时维度值快照(复盘依据)',
  alert_level        TINYINT         NOT NULL DEFAULT 2 COMMENT '级别:1=P0(企微+电话值班,5min未认领再呼备份),2=P1(企微即时负责人组),3=P2(汇总小时/日报)(D01.07分级触达契约)',
  trigger_value      DECIMAL(18,4)   NOT NULL DEFAULT 0 COMMENT '触发值',
  threshold_snapshot JSON            NULL DEFAULT NULL COMMENT '阈值快照(规则版本化,复盘依据)',
  trigger_time       DATETIME(3)     NOT NULL COMMENT '触发时间',
  notify_time        DATETIME(3)     NULL DEFAULT NULL COMMENT '通知时间(monitor.alert.fired→D01.07触达≤1分钟)',
  status             TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=触发,2=已通知,3=已认领,4=处置中,5=已闭环(结论必填),6=已自动恢复(指标回落持续5min+恢复通知同通道),7=已归并(挂主告警只记不发),8=已静默,9=已升级',
  dedup_key          VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '去重键=(metric_code,dims_hash,level)哈希(10分钟窗口同键更新merge_count不重发)',
  merge_count        INT             NOT NULL DEFAULT 1 COMMENT '去重归并计数(窗口内重复越阈累计)',
  parent_alert_id    VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '主告警引用(根因归并树:wms.circuit.opened期间push.fail/recall/callback延迟挂主告警;主告警闭环联动子告警SC-06)',
  escalate_level     TINYINT         NOT NULL DEFAULT 0 COMMENT '升级级别:0=未升级,1=P1→P0(30min未认领重呼),2=P0→运营负责人(15min未认领)(升级链随认领重置)',
  claim_op           VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '认领人(互斥认领防多人重复处置;转派留痕于actions_json)',
  claim_time         DATETIME(3)     NULL DEFAULT NULL COMMENT '认领时间(MTTA起算)',
  mtta_sec           INT             NOT NULL DEFAULT 0 COMMENT '认领时长·秒=claim_time-trigger_time(按域/级别/根因月度汇总)',
  recover_time       DATETIME(3)     NULL DEFAULT NULL COMMENT '恢复时间(自动恢复/处置完成)',
  recover_value      DECIMAL(18,4)   NOT NULL DEFAULT 0 COMMENT '恢复时指标值',
  mttr_sec           INT             NOT NULL DEFAULT 0 COMMENT '恢复时长·秒=recover_time-trigger_time',
  silence_reason     VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '静默原因(必填;静默期只落库不触达,大屏状态色照常计算静默≠失明;到期自动恢复发送)',
  silence_until      DATETIME(3)     NULL DEFAULT NULL COMMENT '静默到期时间',
  close_reason_code  VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '闭环根因字典(必填):platform=外部平台,wms_fault=WMS故障,config=配置错误,data=数据问题,capacity=容量不足,other=其他',
  close_memo         VARCHAR(1024)   NOT NULL DEFAULT '' COMMENT '处置结论(闭环必填:根因+动作+恢复时间)',
  rel_bills          JSON            NULL DEFAULT NULL COMMENT '关联单据(处置中跳转的业务操作引用数组)',
  review_summary     TEXT            NULL COMMENT 'P0复盘摘要(闭环后自动生成:触发/通知/认领/处置/恢复时间线+影响面指标,大促复盘归档FR-05d)',
  actions_json       JSON            NULL DEFAULT NULL COMMENT '动作时间线append:[{"action":"claim|transfer|escalate|silence|close","op":"x","time":"...","memo":"..."}](原monitor_alert_action合并承载)',
  promo_session_id   VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '大促会话引用(会话期告警挂promo.session行,战报统计源FR-06f)',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_rpt_alert_claim (alert_id),
  KEY idx_rpt_alert_claim_status (status, alert_level, trigger_time),
  KEY idx_rpt_alert_claim_dedup (dedup_key, trigger_time),
  KEY idx_rpt_alert_claim_metric (metric_code, trigger_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='告警认领闭环记录(D11.03,P1·M2,无人认领的告警=没有告警)';

-- ============================================================================
-- 九、初始字典数据：指标口径字典 V1.0 基线（= SRS-D11.01 §5.1 全量 24 项）
-- 治理红线: 任何报表/导出/推送/BI宽表字段与本字典不一致即为缺陷(FR-08b/AC-07 CI校验)
-- ============================================================================

INSERT INTO rpt_indicator_dict (tenant_id, metric_code, metric_name, category, biz_define, formula, source_table, caliber_note, dict_version, effect_from, metric_owner, status) VALUES
(1, 'M-S01', '有效订单量', 'sale', '当期真实成交的订单头数量', 'COUNT(订单头 WHERE pay_status=已付款 AND 未整单取消)', 'oms_order.ord_order', '按付款日归属;拆单不重复计(按订单头)', 'v1.0', '2026-10-24', '数据负责人', 1),
(1, 'M-S02', 'GMV', 'sale', '成交总额(平台承担口径)', 'SUM(订单行paid_amount+platform_subsidy)+freight', 'oms_order.ord_order/ord_order_item(D03.01双口径契约)', '平台承担口径;含运费(订单头freight计入);与客户实付强制分列禁止混算', 'v1.0', '2026-10-24', '数据负责人', 1),
(1, 'M-S03', '客户实付金额', 'sale', '买家真金白银支付额', 'SUM(订单行paid_amount)+freight', 'oms_order.ord_order/ord_order_item', '客户实付口径', 'v1.0', '2026-10-24', '数据负责人', 1),
(1, 'M-S04', '客单价', 'sale', '单均成交额', 'GMV/有效订单量', '派生(M-S02/M-S01)', '分子分母同口径同期;汇总行按分子分母重算,禁止对比率求平均', 'v1.0', '2026-10-24', '数据负责人', 1),
(1, 'M-S05', '退款率', 'sale', '退款金额占GMV比例', 'SUM退款成功金额(客户实付口径,按退款成功日)/SUM GMV(按付款日)', 'oms_aftersale退款台账(D05.03)+oms_order.ord_order', '跨期口径明示:分子按退款成功日分母按付款日归属,趋势解读需注意', 'v1.0', '2026-10-24', '数据负责人', 1),
(1, 'M-S06', '销售收入(毛利基数)', 'sale', '毛利计算的收入基数', 'SUM应收(ar_customer)-SUM退款冲减', 'oms_finance(D08.01,IF-D08.01-04)', '客户实付口径;按订单完成日归属(对齐D08.01 §5.4)', 'v1.0', '2026-10-24', '财务负责人', 1),
(1, 'M-I01', '五口径余额', 'stock', '库存五口径日切余额', 'store/available/freeze/arrive_store/defective', 'oms_stock.inv_stock_snapshot(D04.02 FR-06a)', 'available为派生值(D04.02 §5.1公式),报表照录不另算;五口径列不可裁剪合并', 'v1.0', '2026-10-24', '数据负责人', 1),
(1, 'M-I02', '库存周转率', 'stock', '库存周转效率', '当期销售出库成本/((期初货值+期末货值)/2);周转天数=期间天数/周转率', 'oms_stock.inv_cost_snapshot(D04.07)+出库结转', '成本口径(非售价);期间=自然月', 'v1.0', '2026-10-24', '数据负责人', 1),
(1, 'M-I03', '库龄', 'stock', '库存存放时长', '快照日-入库日(批次优先,无批次取记账行首入日)', 'oms_stock.inv_batch(D04.09)+inv_stock_snapshot', '分档0-30/31-60/61-90/91-180/>180天可配', 'v1.0', '2026-10-24', '数据负责人', 1),
(1, 'M-I04', '库存货值', 'stock', '库存金额价值', 'SUM(实际库存×unit_cost);代销=SUM(数量×settle_price)单列代管', 'oms_stock.inv_cost_snapshot(D04.07量价双快照)', '买断=凯淳存货;代销=代管货值(非存货,单列标注)', 'v1.0', '2026-10-24', '财务负责人', 1),
(1, 'M-I05', '缺货账龄', 'stock', '缺货持续时长分级', 'now-缺货标记时间,分档>24h/>48h/>72h', 'oms_order.ord_stockout(D03.09)', '以缺货明细创建时间起算', 'v1.0', '2026-10-24', '数据负责人', 1),
(1, 'M-F01', '审单时效(人工)', 'fulfill', '人工审核处理耗时', '分派时间→审核终态时间(均值/P90)', 'oms_order audit_performance(D03.03 §5.4,IF-D03.03-08)', '不含执行器耗时;口径以D03.03为准', 'v1.0', '2026-10-24', '数据负责人', 1),
(1, 'M-F02', '队列停留时效', 'fulfill', '订单在审单队列的总停留', '付款时间→审核终态', '同M-F01', 'SLA考核口径(含待分派)', 'v1.0', '2026-10-24', '数据负责人', 1),
(1, 'M-F03', '推仓时效', 'fulfill', '发货单推送WMS耗时', '发货单生成时间→WMS推送成功时间', 'oms_order.ord_delivery+oms_fulfill指令记录(D09.02)', '多轮推送取首轮成功', 'v1.0', '2026-10-24', '数据负责人', 1),
(1, 'M-F04', '出库时效', 'fulfill', 'WMS出库作业耗时', '推送成功→出库回传(wms.outbound.callback)', 'oms_fulfill回传时间戳(D09.02)', '分批次出库取末批', 'v1.0', '2026-10-24', '数据负责人', 1),
(1, 'M-F05', '发货时效', 'fulfill', '付款到发货确认耗时(平台考核)', '付款时间→发货确认(ship_status=已发货)', 'oms_order.ord_order状态时间戳', '平台考核口径;部分发货取首包;分档≤24h/24-48h/>48h', 'v1.0', '2026-10-24', '数据负责人', 1),
(1, 'M-F06', '签收时效', 'fulfill', '发货到签收耗时', '发货确认→物流签收(轨迹回传)', 'oms_gateway轨迹(D02.04)', '无轨迹单不计入分母', 'v1.0', '2026-10-24', '数据负责人', 1),
(1, 'M-F07', '自动审单通过率', 'fulfill', '自动审单占比', '自动通过单数/投审单数', 'oms_order(D03.02统计供数)', '按投审日归属;监控看板口径为滚动1h(差异明示)', 'v1.0', '2026-10-24', '数据负责人', 1),
(1, 'M-A01', '售后率', 'aftersale', '售后申请占订单比例', '售后申请单数/付款订单量(默认分母,可切发货订单量)', 'oms_aftersale.aft_return_apply(D05.01)+oms_order.ord_order', '申请口径(含被拒);按申请创建日;分母切换须整表统一', 'v1.0', '2026-10-24', '数据负责人', 1),
(1, 'M-A02', '良不良比', 'aftersale', '退货质检不良占比', '不良品入库数/退货入库总数', 'oms_aftersale(D05.02质检分流明细)', '按质检完成日', 'v1.0', '2026-10-24', '数据负责人', 1),
(1, 'M-A03', '售后处理时效', 'aftersale', '售后各段处理耗时', '申请→审核→退款各段时间差(均值/P90)', 'oms_aftersale(D05.01/03状态时间戳)', '平台介入单单独分列', 'v1.0', '2026-10-24', '数据负责人', 1),
(1, 'M-P01', '毛利(买断)', 'profit', '买断货主毛利额', 'M-S06收入-销售成本(D04.07结转,退货按原单冲回)-运费(D08.04实际/预估)', 'oms_finance应收+oms_stock.inv_cost_change_log+运费明细', '未关账期间运费=预估并整表标注;仅买断货主(代销切M-P03)', 'v1.0', '2026-10-24', '财务负责人', 1),
(1, 'M-P02', '毛利率', 'profit', '毛利占收入比例', '毛利/收入', '派生(M-P01/M-S06)', '收入=0时不计算(显示—)', 'v1.0', '2026-10-24', '财务负责人', 1),
(1, 'M-P03', '服务费收入(代销)', 'profit', '代销货主服务费收入', 'SUM结算单服务费D项(含调整单)', 'oms_finance.fin_settlement(D08.02,IF-D08.02-05)', '按结算周期归属;计算轨迹可下钻;不计算毛利(货权非凯淳)', 'v1.0', '2026-10-24', '财务负责人', 1);

-- ============================================================================
-- 脚本结束 · 共 24 张表（治理2/销售4/库存6/履约3/售后1/毛利服务费2/BI宽表推送4/监控2）+ 指标字典初始 24 项
-- 自查: 括号/逗号/分号配对、COMMENT内无未转义单引号、JSON默认值均为NULL、保留字规避(rank_no/metric_value)
-- ============================================================================
