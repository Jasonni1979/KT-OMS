-- ============================================================================
-- DB-D05 售后域建表脚本（oms_aftersale）
-- 文档编号: DB-D05 · 版本 V1.0 · 2026-10-24 · MySQL 8.0 可执行 DDL
-- 上游契约: DB-00 数据库设计总册（schema=oms_aftersale / 表前缀 aft_ / 公共字段 / 不建物理外键 /
--           敏感字段 _enc+_hash / JSON 扩展列 platform_extra 替代商派 15 张平台镜像表）
-- 需求依据: SRS-D05.01 ~ SRS-D05.05 §6 数据字段章节
-- ----------------------------------------------------------------------------
-- 执行顺序:
--   1) CREATE DATABASE oms_aftersale
--   2) 字典/配置: aft_reason_dict / aft_return_address / aft_auto_audit_rule
--   3) 申请单族(D05.01): aft_return_apply / aft_return_apply_item / aft_return_apply_log
--   4) 执行单族(D05.02): aft_reship / aft_reship_item / aft_reship_package / aft_reship_sn
--                        / aft_defect_disposal / aft_return_logistics
--   5) 退款单族(D05.03): aft_refund / aft_refund_alloc / aft_refund_log
--   6) 换货族(D05.04): aft_exchange / aft_exchange_item / aft_exchange_log
--   7) 自动审核与风控(D05.05): aft_auto_audit_log / aft_audit_task / aft_risk_flag / aft_timeout_monitor
--   8) 初始字典数据 INSERT: aft_reason_dict（售后类型枚举/标准原因/平台原因码映射/不良原因-责任方/损失类型/拒绝原因码）
-- 依赖: 仅本 schema；跨域为逻辑外键 LFK（应用层校验），不建物理外键
--   主要跨域 LFK: order_id→oms_order.ord_order / order_item_id→oms_order.ord_order_item
--   / io_bill_id→oms_stock.inv_io_bill / serial_id→oms_stock.inv_serial_no / bm_id→oms_stock.inv_material
--   / branch_id→oms_fulfill.ful_branch / shop_id→oms_gateway.gw_shop / owner_id→oms_org.org_owner
--   / rule_id→oms_base.bas_rule / diff_receivable_id→oms_finance.fin_receivable
-- 命名/类型基线: 见 DB-00 §2/§6；utf8mb4 / utf8mb4_0900_ai_ci / InnoDB；枚举不用 MySQL ENUM，注释写全
-- ============================================================================

CREATE DATABASE IF NOT EXISTS oms_aftersale DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE oms_aftersale;

-- ============================================================================
-- 一、字典 / 配置表
-- ============================================================================

-- 4. 售后字典（D05.01 · P0，字典表 owner_id 免填）← 商派 return_product_problem/_type + refund_reason 改造:
--    平台原因码→OMS 原因映射合一（D02.02 MappingService 数据源），dict_type 区分子字典
CREATE TABLE aft_reason_dict (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id    BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  dict_type    VARCHAR(24)     NOT NULL COMMENT '字典类别: aftersale_type=售后类型枚举,reason=售后申请原因,reject_reason=审核拒绝原因码,defect_reason=质检不良原因(含责任方),loss_type=退款损失类型,close_type=申请关闭原因',
  reason_code  VARCHAR(32)     NOT NULL COMMENT 'OMS 标准码(同 dict_type 内唯一,如 refund_only/return_refund/exchange/seven_no_reason/OTHER_UNCLASSIFIED)',
  reason_name  VARCHAR(128)    NOT NULL COMMENT 'OMS 标准名称',
  platform     VARCHAR(16)     NOT NULL DEFAULT 'all' COMMENT '平台映射来源: all=OMS标准行(无映射),taobao,tmall,jd,pdd,douyin,xhs,vip,private(映射行:平台原因码→reason_code,SRS-D05.01 §5.5)',
  native_code  VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '平台原始原因码(映射行必填;标准行=空)',
  native_name  VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '平台原始原因文案(保真展示用)',
  duty_party   TINYINT         NOT NULL DEFAULT 0 COMMENT '责任方(defect_reason 用,质检差价扣减依据 SRS-D05.02 §5.3): 0=无,1=买家责任(扣减),2=物流责任(不扣减+索赔登记),3=卖家/质量责任(不扣减),4=平台责任',
  audit_white  TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '自动审核原因白名单: 0=否,1=是(D05.03 FR-04a/D05.05 reason_check 消费)',
  reject_suggest TINYINT(1)    NOT NULL DEFAULT 0 COMMENT '拒绝建议清单标记: 0=否,1=是(临期兜底不放行,D05.05 FR-05b)',
  sort_no      INT             NOT NULL DEFAULT 0 COMMENT '同级排序',
  status       TINYINT         NOT NULL DEFAULT 1 COMMENT '状态: 1=启用,2=停用',
  create_time  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version      INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted   TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记: 0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_reason_dict_code (dict_type, reason_code, platform, native_code),
  KEY idx_aft_reason_dict_platform (platform, dict_type, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='售后字典(类型/原因/平台原因码映射/不良原因/损失类型)(D05.01,P0,字典表)';

-- 10. 退货地址路由配置（D05.02 · P0，配置维度=货主x店铺x品牌，路由优先级: 店铺覆盖>货主默认>全局兜底）
--     ← 商派 return_address 改造: +货主维度(代销/买断双形态必需) +原仓优先策略落 §5.1 算法 +收件电话加密
CREATE TABLE aft_return_address (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(0=全局兜底行-凯淳总仓) LFK→oms_org.org_owner',
  shop_id           BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺覆盖(0=货主默认,>0=店铺级覆盖,优先级更高) LFK→oms_gateway.gw_shop',
  brand_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '品牌维度(可选,0=不限) LFK→oms_stock.inv_brand',
  address_type      TINYINT         NOT NULL DEFAULT 1 COMMENT '退货地址类型: 1=凯淳仓(买断默认原发货仓/集中退货仓),2=品牌方指定仓(代销直退),3=凯淳代收仓(代质检后退品牌方,处置走 aft_defect_disposal)',
  return_branch_id  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '退货仓(必须支持退货入库+质检分流,D09.01 能力矩阵前置校验) LFK→oms_fulfill.ful_branch',
  province          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '省',
  city              VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '市',
  district          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '区/县',
  detail_addr       VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '详细地址',
  contact_name      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '收件人姓名',
  contact_phone_enc VARBINARY(256)  NULL DEFAULT NULL COMMENT '收件人电话密文(D01.05 信封加密)',
  contact_phone_hash CHAR(64)       NOT NULL DEFAULT '' COMMENT '收件人电话盲索引(HMAC,检索用)',
  return_notice     VARCHAR(1024)   NOT NULL DEFAULT '' COMMENT '退货须知文案(随预报下发 WMS+经 D05.01 回传平台买家侧展示)',
  status            TINYINT         NOT NULL DEFAULT 1 COMMENT '状态: 1=启用,2=停用',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted        TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记: 0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_return_address_scope (owner_id, shop_id, brand_id),
  KEY idx_aft_return_address_branch (return_branch_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='退货地址路由配置(货主配置+店铺覆盖,D05.02 FR-02,P0)';

-- 18. 售后自动审核规则参数（D05.05 · P1，配置表 owner_id=0 表示全局）
--     规则本体(元数据/启停/缓存失效)承载于 oms_base.bas_rule(D01.03)，本表存售后特有参数(1:1 关联)
CREATE TABLE aft_auto_audit_rule (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id           BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主隔离(0=全局规则) LFK→oms_org.org_owner',
  rule_id            BIGINT UNSIGNED NOT NULL COMMENT '规则框架本体 LFK→oms_base.bas_rule(D01.03 注册表,1:1)',
  rule_name          VARCHAR(128)    NOT NULL COMMENT '规则名称(租户内唯一)',
  conditions         JSON            NOT NULL COMMENT '条件层12维数组(维度/操作符/值集,AND组合,同维度多值OR): 售后类型/金额区间/原因码/客户等级/商品分类/店铺/货主/平台/货物状态/签收天数/买家标签/来源(SRS-D05.05 FR-01a)',
  weight             INT             NOT NULL DEFAULT 0 COMMENT '优先级(DESC排序,首个全条件命中即裁决,不叠加)',
  action_type        TINYINT         NOT NULL COMMENT '决策动作: 1=自动同意退款,2=自动同意退货,3=自动拒绝建议(强制人工确认),4=转人工',
  gray_ratio         TINYINT         NOT NULL DEFAULT 0 COMMENT '灰度比例0-100(apply_id尾号hash稳定分流,0=不放量)',
  effective_window   JSON            NULL DEFAULT NULL COMMENT '生效时段(如 {"days":[1,2,3,4,5],"from":"09:00","to":"21:00"})',
  exclude_window     JSON            NULL DEFAULT NULL COMMENT '排除时段(大促停自动审核,D05.05 FR-05d)',
  rescue_flag        TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '临期兜底参与标记: 0=否,1=是(FR-05)',
  rescue_cap_amount  DECIMAL(18,2)   NOT NULL DEFAULT 500.00 COMMENT '临期兜底金额封顶(默认500元,超限升级人工不放行)',
  defaulted          TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '系统缺省规则标记: 0=否,1=是(动作=转人工,不可删不可停)',
  owner_account      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '规则Owner(改判率超阈值告警接收人,FR-06b)',
  shop_scope         JSON            NULL DEFAULT NULL COMMENT '适用店铺集(NULL=货主全部店铺)',
  status             TINYINT         NOT NULL DEFAULT 1 COMMENT '状态: 1=启用,2=停用',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version            INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted         TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记: 0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_auto_audit_rule (rule_id),
  UNIQUE KEY uk_aft_auto_audit_rule_name (tenant_id, rule_name),
  KEY idx_aft_auto_audit_rule_weight (status, weight)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='售后自动审核规则参数(承载于D01.03 bas_rule,售后特有参数)(D05.05,P1)';

-- ============================================================================
-- 二、售后申请单族（D05.01 · P0）
-- ============================================================================

-- 1. 售后申请单（D05.01 · P0，单据类禁用软删）★核心
--    ← 商派 return_product + refund_apply 两级审批收敛为一级申请单;
--    15 张平台镜像表(return_product_taobao/tmall/pdd/... + refund_apply_*)→ platform_extra JSON + 3 个生成列索引
CREATE TABLE aft_return_apply (
  id                          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id                   BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id                    BIGINT UNSIGNED NOT NULL COMMENT '货主 LFK→oms_org.org_owner',
  apply_bn                    VARCHAR(32)     NOT NULL COMMENT '申请单号: 平台单 RA{YYYYMMDD}{6位序列},手工单 MA 前缀(Redis发号,全局唯一)',
  source                      VARCHAR(16)     NOT NULL DEFAULT 'platform' COMMENT '来源: platform=平台同步,manual=手工建单,import=导入,migration=迁移',
  platform                    VARCHAR(16)     NOT NULL DEFAULT '' COMMENT '平台: taobao,tmall,jd,pdd,douyin,xhs,vip,private(私域/线下)等',
  shop_id                     BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺 LFK→oms_gateway.gw_shop(手工线下单可=0)',
  platform_aftersale_bn       VARCHAR(64)     NULL DEFAULT NULL COMMENT '平台售后单号(平台单必填,手工单NULL不冲突;幂等键成分,原文可长故加宽)',
  aftersale_type              TINYINT         NOT NULL COMMENT '售后类型: 1=仅退款(refund_only,不动货),2=退货退款(return_refund),3=换货(exchange,含平台换货/京东ASC),4=补发(reshipment,不退货不退款只补货,V1.4 S3:平台补寄单/手工安抚补发,复用0元补发链路,SRS-D05.01 FR-01d)',
  reship_only                 TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '补寄单型标记: 0=否,1=是(无退货链路纯补发,D05.04 FR-03e)',
  status                      TINYINT         NOT NULL DEFAULT 1 COMMENT '申请单状态(§4.1状态机): 0=待关联(订单缺失异常态),1=待审核,2=待退货,3=待收货,4=待退款,5=退款中,6=换货执行中,7=完成,8=拒绝(可reopen),9=关闭;类型裁剪:仅退款无2/3,换货无4/5',
  goods_status                TINYINT         NOT NULL DEFAULT 0 COMMENT '货物状态(canonical): 0=未发货,1=已发货未收,2=已收货(已发货仅退款=type1+本值2,库存损失登记联动D05.03)',
  order_id                    BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '关联订单(待关联异常态可暂=0) LFK→oms_order.ord_order',
  order_bn                    VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '关联订单号快照 LFK→oms_order.ord_order',
  is_archived_order           TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '归档回捞标记: 0=否,1=是(关联归档单经 ArchiveService.recall 回捞后置位,IF-D03.13-02)',
  apply_amount_customer       DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '申请金额-客户实付口径(>=0,<=行级可退余额,SRS-D05.01 §5.3)',
  apply_amount_platform_bear  DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '申请金额-平台承担口径(平台券/补贴部分)',
  approved_amount_customer    DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '审核同意金额-客户实付口径(<=申请金额,部分同意调整留痕)',
  approved_amount_platform_bear DECIMAL(18,2) NOT NULL DEFAULT 0.00 COMMENT '审核同意金额-平台承担口径',
  reason_code                 VARCHAR(32)     NOT NULL DEFAULT '' COMMENT 'OMS售后原因字典码 LFK→aft_reason_dict(字典未命中=OTHER_UNCLASSIFIED其他-待归类+映射维护提醒)',
  reason_raw                  VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '平台原因原文(保真,映射前后对照)',
  buyer_claim                 VARCHAR(1024)   NOT NULL DEFAULT '' COMMENT '买家诉求描述',
  evidence_urls               JSON            NULL DEFAULT NULL COMMENT '买家凭证图片URL数组(PIPL授权访问留痕)',
  buyer_id_enc                VARBINARY(256)  NULL DEFAULT NULL COMMENT '买家平台标识密文(open_id等,D01.05信封加密)',
  buyer_id_hash               CHAR(64)        NOT NULL DEFAULT '' COMMENT '买家标识盲索引(HMAC,风控跨店合并/检索用)',
  buyer_nick                  VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '买家昵称(展示脱敏)',
  buyer_phone_enc             VARBINARY(256)  NULL DEFAULT NULL COMMENT '买家手机密文',
  buyer_phone_hash            CHAR(64)        NOT NULL DEFAULT '' COMMENT '买家手机盲索引',
  deadline                    DATETIME(3)     NULL DEFAULT NULL COMMENT '平台处理截止时间(落单即按 平台x售后类型x店铺覆写 时效规则计算,FR-06a)',
  warn_level                  TINYINT         NOT NULL DEFAULT 0 COMMENT '超时预警级别: 0=无,1=黄色(剩余<=24h,工作台置顶+企微),2=红色(剩余<=4h,升级主管),3=已超时',
  platform_status_raw         VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '平台原始状态串(原样保真,对账回放依据,FR-04c;canonical状态与原始状态双轨)',
  platform_modified_version   VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '版本收敛依据(platform_modified时间戳/平台退款版本号,单调递增,乱序防护FR-01c)',
  sync_status                 TINYINT         NOT NULL DEFAULT 0 COMMENT '平台回传状态: 0=未回传,1=回传中,2=成功,3=失败待重试(D02.05),4=转人工;回传失败不阻塞本地状态机(FR-02d)',
  auto_agreed_by_platform     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '平台超时自动同意标记: 0=否,1=是(被动收敛置位,入资损复盘清单,FR-06b)',
  audit_channel               TINYINT         NOT NULL DEFAULT 0 COMMENT '审核通道: 0=未审核,1=人工,2=自动规则(D05.05),3=临期兜底(deadline_rescue),4=OA审批(D10.05)',
  operator                    VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '建单人(手工单必填;建单人!=审核人,FR-03c)',
  auditor                     VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '审核人(AUTO_RULE:{rule_id}/DEADLINE_RESCUE:{rule_id}=自动)',
  audit_time                  DATETIME(3)     NULL DEFAULT NULL COMMENT '审核时间',
  platform_extra              JSON            NULL DEFAULT NULL COMMENT '平台特有字段JSON(替代商派15张镜像表,FR-04a): 淘系{refund_id,refund_version,split_taobao_fee,split_seller_fee,good_status,cs_intervene_flag,advance_status},京东{asc_bn,service_type,platform_phase,exchange_order_bn},拼多多{aftersale_type_sub,evidence_system,fast_refund_flag},抖音{evidence,intervene_status},小红书/唯品会{supply_return_ref};类型变更轨迹亦记于此',
  platform_refund_id          VARCHAR(64)     GENERATED ALWAYS AS (json_unquote(json_extract(platform_extra, '$.refund_id'))) VIRTUAL COMMENT '生成列(FR-04b): 平台退款单号=platform_extra.$.refund_id(淘系高频查询)',
  cs_intervene_flag           VARCHAR(64)     GENERATED ALWAYS AS (json_unquote(json_extract(platform_extra, '$.cs_intervene_flag'))) VIRTUAL COMMENT '生成列(FR-04b): 平台客服介入标记=platform_extra.$.cs_intervene_flag',
  platform_aftersale_type_raw VARCHAR(64)     GENERATED ALWAYS AS (json_unquote(json_extract(platform_extra, '$.aftersale_type_raw'))) VIRTUAL COMMENT '生成列(FR-04b): 平台售后类型原文=platform_extra.$.aftersale_type_raw',
  create_time                 DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time                 DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间(SRS last_modified)',
  version                     INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(transit CAS状态推进)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_return_apply_bn (apply_bn),
  UNIQUE KEY uk_aft_return_apply_platform (platform, shop_id, platform_aftersale_bn), -- NULL不参与唯一判定:手工单(NULL)防连击锁+操作人确认(应用层)

  KEY idx_aft_return_apply_order (order_id),
  KEY idx_aft_return_apply_status (status, deadline),
  KEY idx_aft_return_apply_shop (shop_id, status),
  KEY idx_aft_return_apply_owner (owner_id, create_time),
  KEY idx_aft_return_apply_buyer (buyer_id_hash),
  KEY idx_aft_return_apply_prefund (platform_refund_id),
  KEY idx_aft_return_apply_cs (cs_intervene_flag),
  KEY idx_aft_return_apply_typeraw (platform_aftersale_type_raw)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='售后申请单(统一入口:仅退款/退货退款/换货/补发V1.4,platform_extra替代商派15张平台镜像表)(D05.01,P0,单据类无软删)';

-- 2. 售后申请单明细行（D05.01 · P0）部分售后按行按数量
CREATE TABLE aft_return_apply_item (
  id                            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id                     BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id                      BIGINT UNSIGNED NOT NULL COMMENT '货主',
  apply_id                      BIGINT UNSIGNED NOT NULL COMMENT '申请单 LFK→aft_return_apply',
  order_item_id                 BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '订单行引用 LFK→oms_order.ord_order_item',
  oid                           VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '平台子单号(平台售后对账键)',
  bm_id                         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '基础物料 LFK→oms_stock.inv_material',
  sku_name                      VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '商品名称快照(展示不回查)',
  sku_spec                      VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '规格快照',
  apply_num                     INT             NOT NULL DEFAULT 0 COMMENT '申请数量(校验: <=行购买数量-该行历史已售后数量(含处理中),多次售后累计不超购,FR-02f)',
  approved_num                  INT             NOT NULL DEFAULT 0 COMMENT '审核同意数量(行级部分同意可调整,调整留痕)',
  apply_amount_customer_line    DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '行级申请金额-客户实付口径(分摊自订单行,getDualAmount)',
  apply_amount_platform_bear_line DECIMAL(18,2) NOT NULL DEFAULT 0.00 COMMENT '行级申请金额-平台承担口径',
  approved_amount_customer_line DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '行级同意金额-客户实付口径(部分同意调整结果)[辅助]',
  gift_flag                     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '赠品标记: 0=否,1=是(赠品随主品联动校验)',
  combo_ref                     VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '组合装/福袋引用(按BOM展开校验,D04.01)',
  platform_extra                JSON            NULL DEFAULT NULL COMMENT '行级平台字段(如淘系oid级退款状态)',
  create_time                   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time                   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version                       INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted                    TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记: 0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_return_apply_item (apply_id, order_item_id),
  KEY idx_aft_return_apply_item_oi (order_item_id),
  KEY idx_aft_return_apply_item_bm (bm_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='售后申请单明细行(部分售后按行按数量)(D05.01,P0)';

-- 3. 售后申请单操作日志（D05.01 · P0，只增不改不删: 无 is_deleted/version/update_time）
CREATE TABLE aft_return_apply_log (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id     BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主',
  apply_id      BIGINT UNSIGNED NOT NULL COMMENT '申请单 LFK→aft_return_apply',
  seq           INT UNSIGNED    NOT NULL COMMENT '单内时序号(从1递增)',
  action        VARCHAR(32)     NOT NULL COMMENT '动作: created=落单,audit=审核,transit=状态变迁,sync=平台回传,type_changed=类型变更(换转退/退转换),warn=超时预警,reopen=重开,manual=人工干预,recall=归档回捞',
  from_status   TINYINT         NOT NULL DEFAULT 0 COMMENT '源状态(状态变迁时填,同主表status枚举)',
  to_status     TINYINT         NOT NULL DEFAULT 0 COMMENT '目标状态',
  operator_type TINYINT         NOT NULL DEFAULT 1 COMMENT '操作者类型: 1=系统,2=人工',
  operator      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '操作者标识(系统=事件/规则引用,人工=账号)',
  detail_json   JSON            NULL DEFAULT NULL COMMENT '依据明细: 事件ID/回传指令ID/类型变更轨迹快照/行级调整前后值',
  create_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_return_apply_log (apply_id, seq),
  KEY idx_aft_return_apply_log_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='售后申请单操作日志(只增不改,D05.01 §6.3,P0)';

-- ============================================================================
-- 三、退货执行单族（D05.02）
-- ============================================================================

-- 5. 退货执行单（D05.02 · P0，单据类禁用软删）★核心: 仓内退货作业唯一单据(货的进出)
--    ← 商派 reship 改造: 通道剥离(下发/回传归D09.03,记账归D04.04),本表纯业务编排+io_bill 引用双向追溯
CREATE TABLE aft_reship (
  id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id             BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id              BIGINT UNSIGNED NOT NULL COMMENT '货主 LFK→oms_org.org_owner',
  shop_id               BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺 LFK→oms_gateway.gw_shop',
  reship_bn             VARCHAR(32)     NOT NULL COMMENT '执行单号 RS{YYYYMMDD}{6位序列}(唯一)',
  apply_id              BIGINT UNSIGNED NOT NULL COMMENT '申请单引用(幂等键,一申请一执行单) LFK→aft_return_apply',
  reship_type           TINYINT         NOT NULL DEFAULT 1 COMMENT '执行类型: 1=退货入库,2=换货(良品入库不触发退款,触发换货出库编排D05.04 FR-08)',
  status                TINYINT         NOT NULL DEFAULT 1 COMMENT '执行单状态(§4.1状态机): 1=已创建,2=已预报(下发成功),3=下发失败(重试耗尽转人工),4=运送中(买家回填物流),5=收货中(WMS接收/分批回传),6=质检完成,7=已闭环,8=已取消,9=质检异常挂起(调包嫌疑/争议),10=差异处理中',
  order_id              BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '原订单(溯源) LFK→oms_order.ord_order',
  delivery_id           BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '原发货单(原仓路由依据: 无显式配置默认原发货仓) LFK→oms_order.ord_delivery',
  return_branch_id      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '退货仓(路由结果: 店铺覆盖>货主默认>原仓优先>全局兜底) LFK→oms_fulfill.ful_branch',
  exchange_branch_id    BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '换出仓(换货双仓: 新单发货仓不受退货仓约束,FR-08b) LFK→oms_fulfill.ful_branch',
  return_address_snapshot JSON          NULL DEFAULT NULL COMMENT '退货地址快照(地址/收件人/须知,下发时固化,路由自 aft_return_address)',
  io_bill_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '退货入库单据 LFK→oms_stock.inv_io_bill(类型=return_in_good/return_in_defect,双向追溯)',
  io_bill_bn            VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '退货入库单据号快照 LFK→oms_stock.inv_io_bill',
  expect_num            INT             NOT NULL DEFAULT 0 COMMENT '预报数量(累计口径)',
  received_good_num     INT             NOT NULL DEFAULT 0 COMMENT '良品实收数(质检合格入实际库存,D04.04分流记账)',
  received_defect_num   INT             NOT NULL DEFAULT 0 COMMENT '不良实收数(入次品口径,处置走 aft_defect_disposal)',
  diff_num              INT             NOT NULL DEFAULT 0 COMMENT '差异数量(=预报-实收,短缺为正,多退为负)',
  logistics_company     VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '退回物流公司编码(D09.04档案校验)',
  tracking_nos          JSON            NULL DEFAULT NULL COMMENT '退回运单号集(多包裹多运单数组)',
  sn_check_status       TINYINT         NOT NULL DEFAULT 0 COMMENT 'SN校验结果汇总: 0=无SN物料,1=全部通过,2=部分失败挂起,3=失败疑似调包(明细见 aft_reship_sn,FR-05b)',
  diff_status           TINYINT         NOT NULL DEFAULT 0 COMMENT '差异状态: 0=无差异,1=等待补寄(默认72h),2=期满按实收闭环,3=多退容差内,4=暂挂待认领,5=人工强制闭环',
  diff_expire_time      DATETIME(3)     NULL DEFAULT NULL COMMENT '差异等待期截止时间',
  close_type            TINYINT         NOT NULL DEFAULT 0 COMMENT '闭环类型: 0=未闭环,1=正常,2=差异闭环,3=强制闭环(留痕),4=取消',
  receive_time          DATETIME(3)     NULL DEFAULT NULL COMMENT 'WMS收货时间(时效考核供数)',
  qc_time               DATETIME(3)     NULL DEFAULT NULL COMMENT '质检完成时间',
  close_time            DATETIME(3)     NULL DEFAULT NULL COMMENT '闭环时间',
  create_time           DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time           DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version               INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(状态机CAS+回传并发累积)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_reship_bn (reship_bn),
  UNIQUE KEY uk_aft_reship_apply (apply_id),
  KEY idx_aft_reship_order (order_id),
  KEY idx_aft_reship_status (status, create_time),
  KEY idx_aft_reship_iobill (io_bill_bn),
  KEY idx_aft_reship_owner (owner_id, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='退货执行单(仓内退货作业:预报/质检/良不良分流/入库单据引用)(D05.02,P0,单据类无软删)';

-- 6. 退货执行单明细行（D05.02 · P0）
CREATE TABLE aft_reship_item (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id            BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id             BIGINT UNSIGNED NOT NULL COMMENT '货主(行级,退仓混货主预留)',
  reship_id            BIGINT UNSIGNED NOT NULL COMMENT '执行单 LFK→aft_reship',
  apply_item_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '申请单行引用(追溯链) LFK→aft_return_apply_item',
  order_item_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '订单行引用 LFK→oms_order.ord_order_item',
  bm_id                BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '基础物料 LFK→oms_stock.inv_material',
  expect_num           INT             NOT NULL DEFAULT 0 COMMENT '行级预报数量',
  good_num             INT             NOT NULL DEFAULT 0 COMMENT '行级良品实收(Σ包裹累计)',
  defect_num           INT             NOT NULL DEFAULT 0 COMMENT '行级不良实收(Σ包裹累计)',
  diff_num             INT             NOT NULL DEFAULT 0 COMMENT '行级差异数量',
  defect_reasons       JSON            NULL DEFAULT NULL COMMENT '不良原因明细数组: [{reason_code(→aft_reason_dict defect_reason),num,duty_party(责任方,质检差价扣减依据§5.3)}]',
  batch_details        JSON            NULL DEFAULT NULL COMMENT '批次退回登记明细(D04.09 registerIn 联动: 原批次优先/实际批次/效期)[{batch_id,batch_no,num,expire_date}]',
  refund_trigger_status TINYINT        NOT NULL DEFAULT 0 COMMENT '退款联动状态: 0=未触发,1=已触发(activateOnInbound),2=人工确认中(差异调整>同意金额20%阈值,FR-05f)',
  diff_flag            TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '行级差异标记: 0=无,1=有(短缺闭环后剩余可退余额保留,买家可再次申请)',
  create_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version              INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(分批回传累积)',
  is_deleted           TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记: 0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_reship_item (reship_id, apply_item_id),
  KEY idx_aft_reship_item_bm (bm_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='退货执行单明细行(良/不良数,批次,退款联动状态)(D05.02,P0)';

-- 7. 退回包裹（D05.02 · P0）← 商派 reship_package/_items 改造: 多包裹分批退回按包裹维度独立回传累积
CREATE TABLE aft_reship_package (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id           BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主',
  reship_id          BIGINT UNSIGNED NOT NULL COMMENT '执行单 LFK→aft_reship',
  package_no         INT UNSIGNED    NOT NULL COMMENT '包裹序号(执行单内从1递增)',
  tracking_no        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '运单号',
  logistics_company  VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '物流公司编码 LFK→oms_fulfill 物流档案(D09.04)',
  arrive_time        DATETIME(3)     NULL DEFAULT NULL COMMENT '到仓时间',
  items_json         JSON            NULL DEFAULT NULL COMMENT '包裹明细: [{bm_id,num,good_num,defect_num}](物料x数量x良不良)',
  callback_batch_ref VARCHAR(64)     NOT NULL DEFAULT '' COMMENT 'WMS回传批次引用(幂等关联键,D09.03 wms.inbound.callback 批次)',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version            INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted         TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记: 0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_reship_package (reship_id, package_no),
  KEY idx_aft_reship_package_tn (tracking_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='退回包裹(多包裹分批退回按包裹收货)(D05.02,P0)';

-- 8. 退货 SN 核销记录（D05.02 · P0/P1随D04.09）★联动 inv_serial_no: 属单校验防调包
--    ← 商派 reship_items_serial 改造: 仅登记回收 → +属单校验结果 +防调包标记 +人工复核闭环
CREATE TABLE aft_reship_sn (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主',
  reship_id        BIGINT UNSIGNED NOT NULL COMMENT '执行单 LFK→aft_reship',
  reship_item_id   BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '执行单行 LFK→aft_reship_item',
  apply_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '申请单(冗余,SN档案 aftersale_id 回填源) LFK→aft_return_apply',
  sn_code          VARCHAR(64)     NOT NULL COMMENT 'SN码(质检扫码实收值)',
  expect_sn_code   VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '期望SN(原订单出库SN,预报携带供仓端比对,D04.09取数)',
  bm_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '基础物料 LFK→oms_stock.inv_material',
  serial_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'SN档案 LFK→oms_stock.inv_serial_no(校验通过后核销: 售后中→已核销,良品重入回在库)',
  order_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '原订单(属单校验依据) LFK→oms_order.ord_order',
  check_stage      TINYINT         NOT NULL DEFAULT 1 COMMENT '校验环节: 1=预报登记,2=质检扫码(两次校验,FR-05b)',
  check_result     TINYINT         NOT NULL DEFAULT 0 COMMENT '属单校验结果(SerialService.validateReturn消费): 0=待校验,1=通过(属单+状态双校验),2=失败-非本订单出库SN,3=失败-SN状态异常,4=降级跳过(WMS无SN能力,高值物料人工抽检)',
  swap_suspect_flag TINYINT(1)     NOT NULL DEFAULT 0 COMMENT '防调包标记: 0=否,1=是(校验失败置位→执行单质检异常挂起,不入账不退款,人工复核工作台)',
  before_sn_status TINYINT         NOT NULL DEFAULT 0 COMMENT '校验前SN状态快照(D04.09状态机): 1=在库,2=已出库,3=售后中,4=已核销,5=换出,6=终止',
  after_sn_status  TINYINT         NOT NULL DEFAULT 0 COMMENT '处置后SN状态(核销/重入回在库/换出终止策略)',
  handle_result    TINYINT         NOT NULL DEFAULT 0 COMMENT '人工复核结论: 0=无需处理,1=确认调包-拒收该件(联动D05.01部分拒绝),2=登记错误-D04.09修正后重检(红冲重记账),3=确认正常放行',
  handler          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '复核处理人',
  handle_time      DATETIME(3)     NULL DEFAULT NULL COMMENT '复核处理时间',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_reship_sn (reship_id, sn_code, check_stage),
  KEY idx_aft_reship_sn_serial (serial_id),
  KEY idx_aft_reship_sn_order (order_id),
  KEY idx_aft_reship_sn_suspect (swap_suspect_flag, handle_result)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='退货SN核销记录(属单校验防调包,联动D04.09 inv_serial_no)(D05.02,P0)';

-- 9. 不良品处置单（D05.02 · P0，单据类禁用软删）← 商派次品滞留无处置闭环 → 凯淳独立单据化
CREATE TABLE aft_defect_disposal (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NOT NULL COMMENT '货主(代销/买断处置策略分流) LFK→oms_org.org_owner',
  disposal_bn      VARCHAR(32)     NOT NULL COMMENT '处置单号(唯一)',
  reship_id        BIGINT UNSIGNED NOT NULL COMMENT '来源执行单 LFK→aft_reship',
  reship_item_id   BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '来源执行单行 LFK→aft_reship_item',
  disposal_type    TINYINT         NOT NULL COMMENT '处置类型: 1=退仓还品牌方(代销默认),2=报废(买断,OA审批),3=促销出清(转良品需质检复判),4=退供应商(采购退货联动D06,P2预留)',
  bm_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '处置物料 LFK→oms_stock.inv_material',
  branch_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '所在仓(次品口径) LFK→oms_fulfill.ful_branch',
  num              INT             NOT NULL DEFAULT 0 COMMENT '处置数量(次品口径,处置单据confirm后次品-N闭环)',
  io_bill_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '处置出库单据 LFK→oms_stock.inv_io_bill(类型=return_warehouse_out退仓/damage_out报损)',
  io_bill_bn       VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '处置出库单据号快照',
  approval_status  TINYINT         NOT NULL DEFAULT 0 COMMENT '审批状态: 0=免审,1=待OA审批(报废超阈值,D10.05),2=通过,3=驳回,4=待品牌方门户确认(代销报废,D10.04)',
  oa_flow_id       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '泛微OA流程ID(D10.05)',
  return_tracking_no VARCHAR(64)   NOT NULL DEFAULT '' COMMENT '退仓物流单号(供品牌方对账,D08结算关联P1)',
  status           TINYINT         NOT NULL DEFAULT 1 COMMENT '处置状态: 1=待处置,2=处置中(单据已下发),3=已闭环,4=超期预警(默认30天未处置升级,FR-06d)',
  deadline         DATETIME(3)     NULL DEFAULT NULL COMMENT '处置截止时间(创建+30天默认,货主可配)',
  evidence_refs    JSON            NULL DEFAULT NULL COMMENT '凭证引用(照片/单据URL数组,访问授权留痕)',
  operator         VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '发起人',
  close_time       DATETIME(3)     NULL DEFAULT NULL COMMENT '闭环时间',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_defect_disposal_bn (disposal_bn),
  KEY idx_aft_defect_disposal_reship (reship_id),
  KEY idx_aft_defect_disposal_status (status, deadline),
  KEY idx_aft_defect_disposal_owner (owner_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='不良品处置单(退仓还品牌方/报废/促销出清)(D05.02 FR-06,P0,单据类无软删)';

-- 11. 退货物流跟踪（D05.02 · P1）轨迹订阅; P0 期以 WMS 回传+D09.03 超时反查(15天)兜底
CREATE TABLE aft_return_logistics (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主',
  reship_id        BIGINT UNSIGNED NOT NULL COMMENT '执行单 LFK→aft_reship',
  tracking_no      VARCHAR(64)     NOT NULL COMMENT '退货运单号',
  logistics_company VARCHAR(64)    NOT NULL DEFAULT '' COMMENT '物流公司编码(D09.04档案)',
  trace_status     TINYINT         NOT NULL DEFAULT 1 COMMENT '轨迹状态: 1=已揽收,2=运输中,3=已签收(提醒仓端收货),4=拒收(异常预警人工介入),5=退回买家,6=无轨迹(超时)',
  last_trace_time  DATETIME(3)     NULL DEFAULT NULL COMMENT '最新轨迹时间',
  last_trace_desc  VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '最新轨迹描述',
  sign_time        DATETIME(3)     NULL DEFAULT NULL COMMENT '签收时间',
  traces           JSON            NULL DEFAULT NULL COMMENT '全量轨迹数组(超长存OSS引用,D01.06口径)',
  warn_flag        TINYINT         NOT NULL DEFAULT 0 COMMENT '预警标记: 0=无,1=签收后超时未质检,2=拒收/退回异常,3=预报后15天无轨迹(FR-04c/04d)',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted       TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记: 0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_return_logistics (reship_id, tracking_no),
  KEY idx_aft_return_logistics_tn (tracking_no),
  KEY idx_aft_return_logistics_warn (warn_flag, trace_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='退货物流跟踪(轨迹订阅/签收提醒/超期预警)(D05.02,P1)';

-- ============================================================================
-- 四、退款单族（D05.03 · P0）——退款执行形态=平台执行,OMS 只记录(资金红线,无买家收款账户字段)
-- ============================================================================

-- 12. 退款单（D05.03 · P0，单据类禁用软删）★核心: 三段式中「钱」的唯一单据+退款台账权威
--     ← 商派 refund_apply + refunds 收敛: 审批语义并入 D05.01 申请单审核,删除 account/bank/pay_account 账户字段族(平台原路退回,OMS零资金操作)
CREATE TABLE aft_refund (
  id                       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id                BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id                 BIGINT UNSIGNED NOT NULL COMMENT '货主 LFK→oms_org.org_owner',
  shop_id                  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺 LFK→oms_gateway.gw_shop',
  refund_bn                VARCHAR(32)     NOT NULL COMMENT '退款单号 RF{YYYYMMDD}{6位序列}(唯一,单号类型码惯例继承商派gen_id思想)',
  apply_id                 BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '申请单引用(与reship_id至少其一;补建单可暂=0后关联) LFK→aft_return_apply',
  reship_id                BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '执行单引用(入库触发来源) LFK→aft_reship',
  order_id                 BIGINT UNSIGNED NOT NULL COMMENT '原订单(必填) LFK→oms_order.ord_order',
  order_bn                 VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '原订单号快照',
  source                   VARCHAR(24)     NOT NULL DEFAULT 'apply_audit' COMMENT '生成来源: apply_audit=仅退款审核同意,inbound_trigger=入库触发激活(activateOnInbound),platform_supplement=平台介入/消息先达补建,manual_offline=手工线下,exchange_diff=换货差价子单(D05.04)',
  status                   TINYINT         NOT NULL DEFAULT 1 COMMENT '退款单状态(§4.1状态机): 1=待退款,2=退款中(平台受理打款),3=已退款(吸收态不回退),4=退款失败(平台重试/买家改账户→回2),5=已退款-线下(手工登记例外,凭证+OA缺一不可),6=已取消(申请关闭且未打款)',
  channel                  TINYINT         NOT NULL DEFAULT 1 COMMENT '退款渠道: 1=platform(原路退回,平台执行,OMS只同步),2=offline(线下登记例外,不走平台同步与回传)',
  refund_customer          DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '退款金额-客户实付口径(上限校验: <=同意金额余额-Σ历史退款,§5.1防错退红线)',
  refund_platform_bear     DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '退款金额-平台承担口径(平台券/补贴随退款退回平台)',
  platform_executed_amount DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '平台实际执行金额(同步登记,与OMS期望比对,差异告警以平台为准落台账)',
  platform_refund_no       VARCHAR(64)     NULL DEFAULT NULL COMMENT '平台退款流水号(补建幂等键成分/对账主键;线下单NULL)',
  platform                 VARCHAR(16)     NOT NULL DEFAULT '' COMMENT '平台(补建幂等键成分)',
  refund_time              DATETIME(3)     NULL DEFAULT NULL COMMENT '平台受理时间(消息同步)',
  arrive_time              DATETIME(3)     NULL DEFAULT NULL COMMENT '到账时间(消息同步)',
  fail_reason_code         VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '失败原因码(退款失败必填,字典可扩展)',
  fail_reason_raw          VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '失败原因平台原文(保真)',
  platform_intervened      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '平台介入标记: 0=否,1=是(平台判定强制打款/补建单,100%入资损复盘清单,SC-04)',
  loss_type                TINYINT         NOT NULL DEFAULT 0 COMMENT '损失类型(不动货场景,FR-03d): 0=无,1=弃货退款(已发货不退货,货值=出库成本快照D04.07),2=平台介入资损,3=超时自动同意资损(→aft_reason_dict loss_type对照)',
  loss_amount              DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '货值损失金额(出库成本快照unit_cost x 数量,不回冲库存,供D08/D11资损报表)',
  audit_channel            TINYINT         NOT NULL DEFAULT 1 COMMENT '审核通道: 1=人工,2=自动(D05.05阈值内),3=OA审批(超人工权限默认2000元,D10.05);决策依据快照固化留痕(FR-04c)',
  auditor                  VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '审核人',
  approval_ref             VARCHAR(64)     NOT NULL DEFAULT '' COMMENT 'OA审批单引用(D10.05)',
  risk_flag                TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '高风险标记: 0=否,1=是(高频退款买家/退款率异常,强制人工,FR-04b→D11风控报表)',
  ledger_status            TINYINT         NOT NULL DEFAULT 0 COMMENT '台账回冲状态: 0=未入账,1=已推D08(应收红字/结算扣减),2=差异(对账工单);台账不可改,金额修正走红冲语义(FR-05c)',
  red_flush_of             BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '红冲来源退款单(负向调整记录指向原单,原记录保留审计可溯)',
  platform_extra           JSON            NULL DEFAULT NULL COMMENT '平台特有字段JSON(§5.5): 淘系{refund_version,advance_flag先行垫付},拼多多{fast_refund_flag极速退款,platform_advance垫付追偿},京东{asc_refund_id},失败原因原文等',
  create_time              DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time              DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间(last_modified)',
  version                  INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(transit CAS)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_refund_bn (refund_bn),
  UNIQUE KEY uk_aft_refund_platform_no (platform, shop_id, platform_refund_no),
  KEY idx_aft_refund_apply (apply_id),
  KEY idx_aft_refund_reship (reship_id),
  KEY idx_aft_refund_order (order_id),
  KEY idx_aft_refund_status (status, update_time),
  KEY idx_aft_refund_ledger (ledger_status, create_time),
  KEY idx_aft_refund_owner (owner_id, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='退款单(平台执行OMS只记录,双口径金额,退款台账供D08对账)(D05.03,P0,单据类无软删)';

-- 13. 退款金额行级分摊回冲（D05.03 · P0）= SRS §6.2 refund_item: 原订单优惠分摊的逆向运算,回冲明细供D08.01应收红字
CREATE TABLE aft_refund_alloc (
  id                     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id              BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id               BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主',
  refund_id              BIGINT UNSIGNED NOT NULL COMMENT '退款单 LFK→aft_refund',
  apply_item_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '申请单行引用(追溯链) LFK→aft_return_apply_item',
  order_item_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '订单行 LFK→oms_order.ord_order_item',
  oid                    VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '平台子单号',
  bm_id                  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '基础物料 LFK→oms_stock.inv_material',
  refund_num             INT             NOT NULL DEFAULT 0 COMMENT '退款数量(<=行申请数量;部分数量按数量比例二次分摊)',
  refund_customer_line   DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '行级回冲-客户实付(=行customer_paid x 行退比例,§5.2算法输出)',
  refund_platform_bear_line DECIMAL(18,2) NOT NULL DEFAULT 0.00 COMMENT '行级回冲-平台承担(平台券/补贴随退)',
  refund_merchant_bear_line DECIMAL(18,2) NOT NULL DEFAULT 0.00 COMMENT '行级回冲-商家承担券(不产生现金退回,只冲应收)',
  loss_line              DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '行级损失(不动货: 成本快照x数量,FR-03d)',
  is_last_line           TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '尾差行标记: 0=否,1=是(尾差入最后一行,保证Σ回冲=平台执行退款总额)[辅助]',
  allocation_snapshot    JSON            NOT NULL COMMENT '分摊快照固化(原订单行级分摊getDualAmount输入+比例+取数时间,可解释可审计,财务争议回放)',
  create_time            DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time            DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version                INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_refund_alloc (refund_id, order_item_id),
  KEY idx_aft_refund_alloc_oi (order_item_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='退款金额行级分摊回冲(三口径回冲明细,供D08应收红字/结算扣减)(D05.03,P0)';

-- 14. 退款日志（D05.03 · P0，只增不改不删: 无 is_deleted/version/update_time）
CREATE TABLE aft_refund_log (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id     BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主',
  refund_id     BIGINT UNSIGNED NOT NULL COMMENT '退款单 LFK→aft_refund',
  seq           INT UNSIGNED    NOT NULL COMMENT '单内时序号',
  action        VARCHAR(32)     NOT NULL COMMENT '动作: created=生成,audit=审核分流,transit=状态变迁,sync=平台状态同步,reconcile=对账差异(补建/补推/工单),red_flush=红冲,offline_register=线下登记,manual=人工干预',
  from_status   TINYINT         NOT NULL DEFAULT 0 COMMENT '源状态(同主表status枚举)',
  to_status     TINYINT         NOT NULL DEFAULT 0 COMMENT '目标状态',
  ref_json      JSON            NULL DEFAULT NULL COMMENT '依据: 消息ID/OA单号/对账批次/单拉核实结果',
  operator_type TINYINT         NOT NULL DEFAULT 1 COMMENT '操作者类型: 1=系统,2=人工',
  operator      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '操作者标识',
  create_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_refund_log (refund_id, seq),
  KEY idx_aft_refund_log_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='退款日志(只增不改,D05.03 §6.3,P0)';

-- ============================================================================
-- 五、换货族（D05.04 · P1）——换货=退货链路+0元新订单复用正向履约,本族只做双链路编排与关联追溯
-- ============================================================================

-- 15. 换货编排单（D05.04 · P1，单据类禁用软删）
--     ← 商派 reship.create_order/change_order_id 弱关联 → 独立编排单+事件驱动五单串联(原订单-申请单-执行单-编排单-新单)
CREATE TABLE aft_exchange (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id            BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id             BIGINT UNSIGNED NOT NULL COMMENT '货主(换入物料货主,跨货主时行级承载) LFK→oms_org.org_owner',
  shop_id              BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺 LFK→oms_gateway.gw_shop',
  exchange_bn          VARCHAR(32)     NOT NULL COMMENT '换货编排单号 EX{YYYYMMDD}{6位序列}(唯一)',
  apply_id             BIGINT UNSIGNED NOT NULL COMMENT '申请单引用(幂等键,重复调用返回首次) LFK→aft_return_apply',
  order_id             BIGINT UNSIGNED NOT NULL COMMENT '原订单 LFK→oms_order.ord_order',
  order_bn             VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '原订单号快照',
  reship_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '退货执行单引用(D05.02创建后回填) LFK→aft_reship',
  new_order_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '换货0元新单(补发触发后回填,C前缀,createway=exchange) LFK→oms_order.ord_order',
  new_order_bn         VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '换货新单号快照',
  rebuild_round        INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '新单重建轮次(取消重建+1,external_ref=EX单号+轮次防重)',
  delivery_ids         JSON            NULL DEFAULT NULL COMMENT '新发货单ID集(一单多发货单可能) LFK→oms_order.ord_delivery',
  exchange_type        TINYINT         NOT NULL DEFAULT 1 COMMENT '换货类型: 1=同款(换入bm_id=换出bm_id),2=异款(差价多退少补;同款不同规格视为异款)',
  reship_only          TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '补寄单型: 0=否,1=是(漏发/破损补寄,无退货链路,退货闭环判定恒真,FR-03e)',
  sequence_mode        VARCHAR(16)     NOT NULL DEFAULT 'RETURN_FIRST' COMMENT '时序模式(创建时判定固化,在途单不随配置漂移FR-02c): RETURN_FIRST=先退后发(默认,高值SN/风控名单强制),SHIP_FIRST=先发后退(低值非SN),PARALLEL=同时',
  mode_reason_snapshot JSON            NULL DEFAULT NULL COMMENT '时序判定依据快照: {mode,reason(高值SN强制/风控名单强制/配置命中项),配置版本}',
  status               TINYINT         NOT NULL DEFAULT 1 COMMENT '编排单状态(§4.1状态机): 1=已创建,2=退货链路中,3=双链路并行中,4=待补差确认(默认阻塞补发),5=补发链路中,6=补发挂起(缺货/异常),7=退货超时挂起,8=人工决策中(新单已发货取消失败),9=完成(退货闭环+新单发货+差价结清),10=已取消',
  diff_type            TINYINT         NOT NULL DEFAULT 0 COMMENT '差价方向: 0=无差价,1=退差(换入<换出,联动D05.03差价退款单),2=补差(换入>换出,联动D08.01应收登记)',
  diff_amount          DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '差价金额(客户实付口径为主,Σ行差价;计算依据快照固化,修改需OA,FR-04e)',
  diff_status          TINYINT         NOT NULL DEFAULT 0 COMMENT '差价结清状态: 0=无差价,1=处理中,2=已结清(退差终态/补差收款确认),3=已冲销(联动取消)',
  diff_refund_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '差价退款单引用 LFK→aft_refund',
  diff_receivable_id   BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '补差应收登记引用 LFK→oms_finance.fin_receivable(D08.01)',
  receiver_snapshot    JSON            NULL DEFAULT NULL COMMENT '换货收件人快照(密文引用: 默认复制原单收件人/平台新地址/客服代改留痕,PIPL D01.05,0元新单创建时传递)',
  receiver_phone_hash  CHAR(64)        NOT NULL DEFAULT '' COMMENT '收件人手机盲索引(HMAC,检索用)',
  old_serial_nos       JSON            NULL DEFAULT NULL COMMENT '换出原SN清单(退货链路核销对象)[{sn_code,serial_id}]',
  new_serial_nos       JSON            NULL DEFAULT NULL COMMENT '换入新SN清单(新单出库bindOut绑定后回填,新旧对照追溯FR-05c)',
  sn_reentry_policy    TINYINT         NOT NULL DEFAULT 1 COMMENT '良品SN重入策略(货主x物料分类配置): 1=可再售(默认,SN回在库),2=换出终止(高值/贴身分品类,防问题机再售,SN置换出终态)',
  risk_freeze_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '风险预占台账引用(SHIP_FIRST可选配置,FreezeService.reserve obj_type=售后换货,72h过期回收) LFK→oms_stock.inv_freeze_log',
  hold_reason          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '挂起原因(补发挂起-缺货/退货超时/取消失败转人工等)',
  hold_expire          DATETIME(3)     NULL DEFAULT NULL COMMENT '挂起升级时限(超期红色预警,整单兜底默认30天FR-06d)',
  cancel_reason_code   VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '取消原因码(结构化字典→aft_reason_dict close_type): type_change=换转退,closed=申请关闭,manual=人工取消,timeout=超时关闭',
  reship_close_time    DATETIME(3)     NULL DEFAULT NULL COMMENT '退货链路闭环时间(时效考核供数D11)',
  new_ship_time        DATETIME(3)     NULL DEFAULT NULL COMMENT '新单发货时间',
  complete_time        DATETIME(3)     NULL DEFAULT NULL COMMENT '编排单完成时间',
  create_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version              INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(transit CAS+双链路事件并发)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_exchange_bn (exchange_bn),
  UNIQUE KEY uk_aft_exchange_apply (apply_id),
  KEY idx_aft_exchange_order (order_id),
  KEY idx_aft_exchange_new_order (new_order_id),
  KEY idx_aft_exchange_reship (reship_id),
  KEY idx_aft_exchange_status (status, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='换货编排单(退货链路+0元新单双链路编排,时序策略/差价/SN对照)(D05.04,P1,单据类无软删)';

-- 16. 换货明细行（D05.04 · P1）
CREATE TABLE aft_exchange_item (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  exchange_id    BIGINT UNSIGNED NOT NULL COMMENT '换货编排单 LFK→aft_exchange',
  apply_item_id  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '申请单行引用(追溯链) LFK→aft_return_apply_item',
  out_bm_id      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '换出物料(原订单行) LFK→oms_stock.inv_material',
  out_num        INT             NOT NULL DEFAULT 0 COMMENT '换出数量',
  out_paid_line  DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '换出行实付(客户实付口径,getDualAmount x 换货数量/行购买数量,§5.4)',
  out_owner_id   BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '换出货主 LFK→oms_org.org_owner',
  in_bm_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '换入物料(目标SKU,补发出库对象) LFK→oms_stock.inv_material',
  in_num         INT             NOT NULL DEFAULT 0 COMMENT '换入数量',
  in_settle_price DECIMAL(18,4)  NOT NULL DEFAULT 0.0000 COMMENT '换入物料结算价(取数源: 货主协议供货价默认/D04.07移动加权成本,货主级配置)',
  in_amount      DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '换入价值(=结算价x数量)',
  in_owner_id    BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '换入货主(异款跨货主场景) LFK→oms_org.org_owner',
  diff_line      DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '行级差价(=换入价值-换出价值,>0补差<0退差;Σ行差价=单级差价)',
  price_snapshot JSON            NULL DEFAULT NULL COMMENT '差价计算依据快照(换出实付/换入结算价/取数时间/取数源,FR-04e审计可回放)',
  batch_ref      JSON            NULL DEFAULT NULL COMMENT '批次明细引用(换出批次登记+新单FEFO指派,D04.09联动)',
  serial_ref     JSON            NULL DEFAULT NULL COMMENT 'SN明细引用(原SN核销+新SN绑定对照,D04.09 SC-06链路)',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version        INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记: 0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_exchange_item (exchange_id, apply_item_id, in_bm_id),
  KEY idx_aft_exchange_item_in (in_bm_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='换货明细行(换出物料原SN+换入物料新SN,行级差价)(D05.04,P1)';

-- 17. 换货编排日志（D05.04 · P1，只增不改不删: 无 is_deleted/version/update_time）
CREATE TABLE aft_exchange_log (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id     BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主',
  exchange_id   BIGINT UNSIGNED NOT NULL COMMENT '换货编排单 LFK→aft_exchange',
  seq           INT UNSIGNED    NOT NULL COMMENT '单内时序号',
  action        VARCHAR(32)     NOT NULL COMMENT '动作: created=创建,mode_decided=时序模式判定,reship_triggered=补发触发,new_order_event=新单事件(审单/发货/取消),diff_action=差价动作(退差/补差/收款确认),hold=挂起,cancel=取消(可重入每步留痕),complete=完成,manual=人工决策',
  from_status   TINYINT         NOT NULL DEFAULT 0 COMMENT '源状态(同主表status枚举)',
  to_status     TINYINT         NOT NULL DEFAULT 0 COMMENT '目标状态',
  trigger_event VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '触发事件ID(aftersale.reship.qc_completed/order.shipped等,事件消费幂等台账键成分)',
  operator_type TINYINT         NOT NULL DEFAULT 1 COMMENT '操作者类型: 1=系统,2=人工',
  operator      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '操作者标识',
  detail_json   JSON            NULL DEFAULT NULL COMMENT '依据快照(模式判定依据/取消动作序列每步结果/差价快照)',
  create_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_exchange_log (exchange_id, seq),
  KEY idx_aft_exchange_log_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='换货编排日志(只增不改,D05.04 §6.3,P1)';

-- ============================================================================
-- 六、自动审核 / 风控 / 时效（D05.05 · P1 + D05.01/03 风控时效支撑）
-- ============================================================================

-- 19. 自动审核决策留痕（D05.05 · P1，只增: 无 is_deleted;人工终审回填改判字段故保留 update_time）
--     = SRS §6.2 decision + §6.3 reason 明细合一(结构化原因入 reasons JSON 数组,同 order_audit_reason 模式)
CREATE TABLE aft_auto_audit_log (
  id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id             BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id              BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主',
  apply_id              BIGINT UNSIGNED NOT NULL COMMENT '申请单 LFK→aft_return_apply',
  round                 INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '判定轮次(reopen/重审+1,旧记录归档不覆盖,决策链完整保留)',
  trigger_type          VARCHAR(24)     NOT NULL DEFAULT 'created' COMMENT '触发源: created=落单,reopen=拒绝后重开,amount_changed=金额变更,type_changed=类型变更,deadline_rescue=临期兜底,rejudge=人工重审',
  rule_id               BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '命中规则 LFK→aft_auto_audit_rule(0=灰度未开/缺省转人工)',
  rule_version_snapshot JSON            NULL DEFAULT NULL COMMENT '规则版本快照(条件/动作/阈值配置/风控参数当时值,可解释回放依据)',
  decision              TINYINT         NOT NULL COMMENT '决策结果: 1=自动同意(退款/退货按规则动作),2=拒绝建议(强制人工确认),3=转人工,4=灰度未开转人工,5=竞态放弃(人工先审,人工优先),6=临期兜底自动同意(deadline_rescue)',
  operator_ref          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '落地标识: AUTO_RULE:{rule_id}/DEADLINE_RESCUE:{rule_id}(经D05.01 audit同一入口落地)',
  risk_flag             TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '风控标记: 0=否,1=是(风控HOLD压制放行规则,不可配置绕过FR-01c)',
  deadline_rescue       TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '临期兜底标记: 0=否,1=是(100%入资损复盘清单,与平台超时单同池月度对比FR-05c)',
  reasons               JSON            NOT NULL COMMENT '结构化原因明细数组(同order_audit_reason模式): [{plugin(blacklist_check/fraud_freq_check/duplicate_check/period_check/amount_check/reason_check/goods_check),reason_code(BLACKLIST/FRAUD_FREQ/SHOP_REFUND_ABNORMAL/DUPLICATE_APPLY/AUDIT_PERIOD_EXPIRED/AMOUNT_OVER_AUTO/AMOUNT_OVER_MANUAL/REASON_NOT_ALLOWED/GOODS_FORCE_MANUAL/SYSTEM_ERROR),level(BLOCK/WARN),description,detail(频次统计值/余额计算/阈值/名单命中快照),suggest_action(同意/拒绝/联系买家/加黑名单/等人工)}]',
  manual_final_decision TINYINT         NOT NULL DEFAULT 0 COMMENT '人工终审决策(拒绝建议/转人工单回填): 0=未回填,1=同意,2=拒绝,3=转OA',
  manual_operator       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '人工终审人',
  overturn_flag         TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '改判标记: 0=否,1=是(人工决策与自动建议不一致,改判率统计源FR-03d,超5%告警规则Owner)',
  overturn_reason_code  VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '改判原因码(字典,规则调优样本)',
  cost_ms               INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '判定耗时ms(P95<=300ms绩效供数,含插件耗时明细见plugin_perf日志D01.03)',
  create_time           DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '判定时间',
  update_time           DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间(人工终审回填)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_auto_audit_log (apply_id, round),
  KEY idx_aft_auto_audit_log_rule (rule_id, create_time),
  KEY idx_aft_auto_audit_log_decision (decision, create_time),
  KEY idx_aft_auto_audit_log_overturn (overturn_flag, rule_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='售后自动审核决策留痕(决策+结构化原因+改判回流)(D05.05,P1)';

-- 20. 人工售后审核任务（D05.05/D05.01 · P0 基础人工审核随 P0,任务模型 P1 增强）
CREATE TABLE aft_audit_task (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主',
  shop_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺 LFK→oms_gateway.gw_shop',
  apply_id        BIGINT UNSIGNED NOT NULL COMMENT '申请单 LFK→aft_return_apply',
  seq             INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '任务轮次(reopen重开新任务+1)',
  task_type       TINYINT         NOT NULL DEFAULT 1 COMMENT '任务类型: 1=常规人工审核(P0),2=自动审核转人工(带决策依据),3=拒绝建议确认(高优,机器只给建议拒绝权留人工),4=抽检任务(自动同意单默认5%事后复核),5=风控复核(风控详情置顶),6=质检争议复核(D05.02 FR-05g)',
  priority        TINYINT         NOT NULL DEFAULT 1 COMMENT '优先级: 1=普通,2=重要(风控/金额大),3=置顶(临期);排序=临期>风控>金额大>普通(FR-03c)',
  decision_ref_id BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '自动决策记录引用 LFK→aft_auto_audit_log(转人工/拒绝建议/抽检任务携带)',
  risk_detail     JSON            NULL DEFAULT NULL COMMENT '风控详情快照(历史退款清单/累计金额/频次曲线/名单命中,工作台展示)',
  deadline        DATETIME(3)     NULL DEFAULT NULL COMMENT '处理截止(=申请单deadline,临期预警)',
  status          TINYINT         NOT NULL DEFAULT 1 COMMENT '任务状态: 1=待处理,2=已认领,3=已完成,4=已取消(申请关闭/reopen归档)',
  assignee        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '处理人(认领/分派)',
  claim_time      DATETIME(3)     NULL DEFAULT NULL COMMENT '认领时间',
  finish_time     DATETIME(3)     NULL DEFAULT NULL COMMENT '完成时间',
  result          TINYINT         NOT NULL DEFAULT 0 COMMENT '处理结果: 0=未决,1=同意,2=拒绝,3=转OA审批(超人工权限默认2000元),4=改判同意(否决拒绝建议)',
  oa_flow_id      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '泛微OA流程ID(D10.05)',
  remark          VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '处理备注(拒绝原因码经回传同步平台)',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(认领并发控制)',
  is_deleted      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记: 0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_audit_task (apply_id, task_type, seq),
  KEY idx_aft_audit_task_status (status, priority, deadline),
  KEY idx_aft_audit_task_assignee (assignee, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='人工售后审核任务(转人工/拒绝建议确认/抽检/风控复核)(D05.05,P1;基础人工审核P0)';

-- 21. 售后风控标记（D05.05 · P1）= SRS §6.4 buyer_risk_stat: 高频退款/退款率异常/黑名单,防薅羊毛
--     Redis 实时计数 + 本表日终校准(对账防漂移); 名单权威在 D03.09 ord_risk_list,本表为售后域统计画像
CREATE TABLE aft_risk_flag (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  dim_type           TINYINT         NOT NULL DEFAULT 1 COMMENT '统计维度: 1=买家(open_id跨店铺合并防跨店薅),2=店铺(退款率异常监控),3=收货地址(地址聚合异常)',
  platform           VARCHAR(16)     NOT NULL DEFAULT '' COMMENT '平台(买家维度键成分)',
  dim_key_enc        VARBINARY(256)  NULL DEFAULT NULL COMMENT '维度键密文(买家open_id/店铺ID/地址hash原值,D01.05信封加密;店铺维度=shop_id明文入库dim_key_enc可空)',
  dim_key_hash       CHAR(64)        NOT NULL COMMENT '维度键盲索引(HMAC,统计聚合键)',
  shop_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺(dim_type=2时主键维度) LFK→oms_gateway.gw_shop',
  refund_cnt_30d     INT             NOT NULL DEFAULT 0 COMMENT '30天退款次数(处理中+完成都计入,默认>=5次强制转人工,FR-04a)',
  refund_amt_30d     DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '30天退款累计金额-客户实付口径(默认>=2000元强制转人工)',
  same_order_cnt_7d  INT             NOT NULL DEFAULT 0 COMMENT '同订单7天内申请笔数(>=3笔=化整为零拆单模式风控,FR-04b)',
  refund_rate_30d    DECIMAL(9,4)    NOT NULL DEFAULT 0.0000 COMMENT '30天退款率(dim_type=2店铺维度: 退款单数/订单数;>均值+2倍标准差=该店自动同意整体降级转人工,FR-04c)',
  addr_hash          CHAR(64)        NOT NULL DEFAULT '' COMMENT '收货地址盲索引(地址聚合异常因子: 同址多买家集中退款)',
  blacklist_flag     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '黑名单标记: 0=否,1=是(D03.09名单同步;黑名单买家申请永久转人工不自动拒绝,保留申诉空间)',
  blacklist_expire   DATETIME(3)     NULL DEFAULT NULL COMMENT '黑名单失效期',
  high_freq_flag     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '高频退款标记: 0=否,1=是(风控命中入台账,D11风控报表供数)',
  stat_date          DATE            NOT NULL COMMENT '统计日期(日终校准批次)',
  calibrate_status   TINYINT         NOT NULL DEFAULT 0 COMMENT '校准状态: 0=待校准(Redis实时值),1=已日终校准(Redis-DB对账防漂移)',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version            INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted         TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记: 0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_risk_flag (dim_type, platform, dim_key_hash),
  KEY idx_aft_risk_flag_shop (shop_id, stat_date),
  KEY idx_aft_risk_flag_black (blacklist_flag, blacklist_expire)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='售后风控标记(高频退款/退款率异常/黑名单统计画像,防薅羊毛)(D05.05,P1)';

-- 22. 平台售后时效监控（D05.01 · P0）超时自动同意风险管理: 黄/红分级预警+被动收敛留痕+资损复盘
CREATE TABLE aft_timeout_monitor (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id           BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主',
  shop_id             BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺 LFK→oms_gateway.gw_shop',
  apply_id            BIGINT UNSIGNED NOT NULL COMMENT '申请单(一单一监控行,reopen状态更新) LFK→aft_return_apply',
  platform            VARCHAR(16)     NOT NULL DEFAULT '' COMMENT '平台',
  aftersale_type      TINYINT         NOT NULL DEFAULT 0 COMMENT '售后类型快照: 1=仅退款,2=退货退款,3=换货(同主表枚举)',
  time_limit_rule     JSON            NULL DEFAULT NULL COMMENT '时效规则快照: {platform,aftersale_type,limit_hours,shop_override}(如拼多多48h/淘系退货5天/抖音72h,FR-06a)',
  deadline            DATETIME(3)     NOT NULL COMMENT '平台处理截止时间(落单即计算;reopen重算)',
  warn_level          TINYINT         NOT NULL DEFAULT 0 COMMENT '预警级别(调度每10分钟扫描分级): 0=正常,1=黄色(剩余<=24h,工作台置顶+企微提醒专员),2=红色(剩余<=4h,升级售后主管),3=已超时',
  warn_time           DATETIME(3)     NULL DEFAULT NULL COMMENT '首次预警时间',
  escalate_flag       TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '升级标记: 0=否,1=已升级主管(红色)',
  auto_agreed_flag    TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '平台超时自动同意标记: 0=否,1=是(平台自动同意后被动收敛置位,同步主表auto_agreed_by_platform)',
  passive_converge_time DATETIME(3)   NULL DEFAULT NULL COMMENT '被动收敛时间(平台自动同意消息到达,版本收敛跳过本地审核)',
  loss_review_flag    TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '资损复盘标记: 0=否,1=已入复盘清单(金额/店铺/原因;高频店铺触发时效规则复审)',
  loss_amount         DECIMAL(18,2)   NOT NULL DEFAULT 0.00 COMMENT '资损金额(超时自动同意退款额,D05.03退款台账标记联动)',
  status              TINYINT         NOT NULL DEFAULT 1 COMMENT '监控状态: 1=监控中,2=已处理按时闭环(审核完成解除),3=已超时(平台未动作,红色预警持续+主管介入不静默),4=平台自动同意已收敛,5=已取消(申请关闭)',
  create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted          TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记: 0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_timeout_monitor (apply_id),
  KEY idx_aft_timeout_monitor_scan (status, warn_level, deadline),
  KEY idx_aft_timeout_monitor_shop (shop_id, status),
  KEY idx_aft_timeout_monitor_review (loss_review_flag, auto_agreed_flag)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='平台售后时效监控(超时分级预警/平台自动同意被动收敛/资损复盘)(D05.01 FR-06,P0)';

-- ============================================================================
-- 七、初始字典数据
-- ============================================================================

-- 售后类型枚举（SRS-D05.01 FR-01d 三链路 + 补寄归换货大类）
INSERT INTO aft_reason_dict (tenant_id, dict_type, reason_code, reason_name, platform, native_code, native_name, duty_party, audit_white, reject_suggest, sort_no, status) VALUES
(1, 'aftersale_type', 'refund_only',   '仅退款(不动货:未发货退款/已发货不退货退款/平台介入退款)', 'all', '', '', 0, 0, 0, 1, 1),
(1, 'aftersale_type', 'return_refund', '退货退款(退货入库+退款)',                                'all', '', '', 0, 0, 0, 2, 1),
(1, 'aftersale_type', 'exchange',      '换货(含平台换货/京东ASC服务单)',                          'all', '', '', 0, 0, 0, 3, 1),
(1, 'aftersale_type', 'reshipment',    '补发(不退货不退款只补货,V1.4 S3)', 'all', '', '', 0, 0, 0, 4, 1);

-- OMS 标准售后原因（audit_white=自动审核原因白名单, reject_suggest=临期兜底拒绝建议清单）
INSERT INTO aft_reason_dict (tenant_id, dict_type, reason_code, reason_name, platform, native_code, native_name, duty_party, audit_white, reject_suggest, sort_no, status) VALUES
(1, 'reason', 'SEVEN_NO_REASON',   '七天无理由退货',       'all', '', '', 0, 1, 0, 1,  1),
(1, 'reason', 'WRONG_PURCHASE',    '拍错/多拍/不想要',     'all', '', '', 0, 1, 0, 2,  1),
(1, 'reason', 'UNSHIPPED_REFUND',  '未发货退款',           'all', '', '', 0, 1, 0, 3,  1),
(1, 'reason', 'QUALITY_ISSUE',     '商品质量问题',         'all', '', '', 3, 0, 0, 4,  1),
(1, 'reason', 'DAMAGED',           '商品破损/包装破损',    'all', '', '', 0, 0, 0, 5,  1),
(1, 'reason', 'DESC_MISMATCH',     '与描述不符/色差/尺寸不符', 'all', '', '', 3, 0, 0, 6, 1),
(1, 'reason', 'LOGISTICS_ISSUE',   '物流问题(破损/丢件/超时)', 'all', '', '', 2, 0, 0, 7, 1),
(1, 'reason', 'MISSING_ITEM',      '少件/漏发',            'all', '', '', 3, 0, 0, 8,  1),
(1, 'reason', 'FAKE_SUSPECT',      '假冒/真伪存疑',        'all', '', '', 0, 0, 1, 9,  1),
(1, 'reason', 'BUYER_NO_RECEIVE',  '买家未收到货',         'all', '', '', 2, 0, 0, 10, 1),
(1, 'reason', 'PLATFORM_FORCE',    '平台规则强制退款',     'all', '', '', 4, 1, 0, 11, 1),
(1, 'reason', 'OTHER_UNCLASSIFIED','其他-待归类(字典未命中兜底+映射维护提醒)', 'all', '', '', 0, 0, 0, 99, 1);

-- 平台原因码映射示例（(platform, native_code)→reason_code,D02.02 MappingService 数据源;上线时按平台文档批量导入）
INSERT INTO aft_reason_dict (tenant_id, dict_type, reason_code, reason_name, platform, native_code, native_name, duty_party, audit_white, reject_suggest, sort_no, status) VALUES
(1, 'reason', 'SEVEN_NO_REASON',  '七天无理由退货', 'taobao', 'seven_no_reason',      '七天无理由退换货', 0, 1, 0, 1, 1),
(1, 'reason', 'WRONG_PURCHASE',   '拍错/多拍',      'taobao', 'wrong_item',           '拍错/多拍/不想要', 0, 1, 0, 2, 1),
(1, 'reason', 'QUALITY_ISSUE',    '质量问题',       'tmall',  'quality_problem',      '质量问题',         3, 0, 0, 3, 1),
(1, 'reason', 'DESC_MISMATCH',    '与描述不符',     'tmall',  'desc_not_match',       '商品信息拍错(规格/尺码/颜色)', 0, 0, 0, 4, 1),
(1, 'reason', 'UNSHIPPED_REFUND', '未发货退款',     'pdd',    'not_ship_refund',      '未发货仅退款',     0, 1, 0, 5, 1),
(1, 'reason', 'FAKE_SUSPECT',     '假冒存疑',       'pdd',    'fake_goods',           '假冒品牌',         0, 0, 1, 6, 1),
(1, 'reason', 'QUALITY_ISSUE',    '质量问题',       'jd',     'quality_return',       '商品质量问题(ASC)', 3, 0, 0, 7, 1),
(1, 'reason', 'SEVEN_NO_REASON',  '七天无理由',     'douyin', 'no_reason_return',     '7天无理由退货',    0, 1, 0, 8, 1);

-- 质检不良原因（duty_party 责任方→质检差价扣减依据 SRS-D05.02 §5.3: 买家责任扣减/物流责任不扣减+索赔/质量责任不扣减）
INSERT INTO aft_reason_dict (tenant_id, dict_type, reason_code, reason_name, platform, native_code, native_name, duty_party, audit_white, reject_suggest, sort_no, status) VALUES
(1, 'defect_reason', 'USE_TRACE',     '使用痕迹/人为损坏', 'all', '', '', 1, 0, 0, 1, 1),
(1, 'defect_reason', 'MISS_ACCESSORY','少配件/少附件',     'all', '', '', 1, 0, 0, 2, 1),
(1, 'defect_reason', 'TRANSIT_BROKEN','运输破损',          'all', '', '', 2, 0, 0, 3, 1),
(1, 'defect_reason', 'PACKAGE_BROKEN','包装破损(商品完好)','all', '', '', 2, 0, 0, 4, 1),
(1, 'defect_reason', 'QUALITY_DEFECT','质量缺陷',          'all', '', '', 3, 0, 0, 5, 1),
(1, 'defect_reason', 'WRONG_GOODS',   '串货/非本单商品',   'all', '', '', 1, 0, 0, 6, 1);

-- 退款损失类型（SRS-D05.03 FR-03d,不动货场景损失登记）
INSERT INTO aft_reason_dict (tenant_id, dict_type, reason_code, reason_name, platform, native_code, native_name, duty_party, audit_white, reject_suggest, sort_no, status) VALUES
(1, 'loss_type', 'goods_abandoned',     '弃货退款(已发货不退货,货值=出库成本快照)', 'all', '', '', 0, 0, 0, 1, 1),
(1, 'loss_type', 'platform_intervene',  '平台介入资损(强制退款复盘)',               'all', '', '', 0, 0, 0, 2, 1),
(1, 'loss_type', 'timeout_auto_agree',  '超时自动同意资损(平台/本地兜底)',           'all', '', '', 0, 0, 0, 3, 1);

-- 审核拒绝原因码（经回传 refuse_refund 同步平台）+ 申请关闭原因
INSERT INTO aft_reason_dict (tenant_id, dict_type, reason_code, reason_name, platform, native_code, native_name, duty_party, audit_white, reject_suggest, sort_no, status) VALUES
(1, 'reject_reason', 'OVER_PERIOD',      '超出售后时效',       'all', '', '', 0, 0, 0, 1, 1),
(1, 'reject_reason', 'EVIDENCE_MISSING', '凭证不足',           'all', '', '', 0, 0, 0, 2, 1),
(1, 'reject_reason', 'GOODS_AFFECT_SALE','商品影响二次销售',   'all', '', '', 0, 0, 0, 3, 1),
(1, 'reject_reason', 'SWAP_SUSPECT',     '疑似调包/非本单商品','all', '', '', 0, 0, 0, 4, 1),
(1, 'reject_reason', 'AMOUNT_OVER',      '申请金额超可退余额', 'all', '', '', 0, 0, 0, 5, 1),
(1, 'close_type',    'BUYER_CANCEL',     '买家撤销',           'all', '', '', 0, 0, 0, 1, 1),
(1, 'close_type',    'PLATFORM_CLOSE',   '平台关闭',           'all', '', '', 0, 0, 0, 2, 1),
(1, 'close_type',    'TIMEOUT_CLOSE',    '超时关闭(买家未退货)','all', '', '', 0, 0, 0, 3, 1),
(1, 'close_type',    'TYPE_CHANGE',      '换转退/退转换类型变更关闭', 'all', '', '', 0, 0, 0, 4, 1);

-- 全局兜底退货地址（凯淳总仓占位,上线时按实际仓配置;owner_id=0 全局兜底行）
INSERT INTO aft_return_address (tenant_id, owner_id, shop_id, brand_id, address_type, return_branch_id, province, city, district, detail_addr, contact_name, return_notice, status) VALUES
(1, 0, 0, 0, 1, 0, '上海市', '上海市', '青浦区', '凯淳总仓(上线时配置实际地址)', '凯淳售后组', '请勿寄到付件;包裹内附订单号与售后单号;退货须知以平台页面展示为准。', 1);

-- 系统缺省自动审核规则（D05.05 FR-01b: 末尾兜底动作=转人工,不可删;rule_id=0 待 bas_rule 建档后回填）
INSERT INTO aft_auto_audit_rule (tenant_id, owner_id, rule_id, rule_name, conditions, weight, action_type, gray_ratio, rescue_flag, rescue_cap_amount, defaulted, owner_account, status) VALUES
(1, 0, 0, '系统缺省规则(转人工兜底)', '[]', 0, 4, 100, 0, 500.00, 1, 'system', 1);


-- ----------------------------------------------------------------------------
-- V1.3 行业适配增补（H4 决策：高额分级 + 跨店铺退货画像）
-- 来源：SRS-D05.05 V1.3 §6.5 / FR-04f / FR-04g
-- ----------------------------------------------------------------------------
CREATE TABLE aft_buyer_profile (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  buyer_key_hash     CHAR(64)        NOT NULL COMMENT '买家维度键哈希(platform+open_id/手机号HMAC,不落明文,PIPL D01.05);跨货主全局画像,不设owner_id',
  platform           VARCHAR(16)     NOT NULL DEFAULT '' COMMENT '平台(维度键成分)',
  return_cnt_90d     INT             NOT NULL DEFAULT 0 COMMENT '退货次数(90天窗口,售后终态事件驱动增量更新)',
  return_cnt_365d    INT             NOT NULL DEFAULT 0 COMMENT '退货次数(365天窗口)',
  return_rate_90d    DECIMAL(5,4)    NOT NULL DEFAULT 0.0000 COMMENT '退货率90天(退货单数/购买单数)',
  return_rate_365d   DECIMAL(5,4)    NOT NULL DEFAULT 0.0000 COMMENT '退货率365天',
  reject_cnt_365d    INT             NOT NULL DEFAULT 0 COMMENT '拒收次数(365天)',
  reason_dist        JSON            NULL DEFAULT NULL COMMENT '售后原因分布JSON:{质量:n,无理由:n,破损:n,...}',
  swap_suspect_cnt   INT             NOT NULL DEFAULT 0 COMMENT '调包嫌疑次数(质检少件/非本单SN/防伪扣异常,D05.02/D04.09回传标记)',
  risk_score         TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '风险分0-100(规则式加权,公式全局配置版本化;>=降级阈值默认60触发PROFILE_HIGH_RISK转人工)',
  score_version      INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '风险分计算公式版本(公式变更全量重跑)',
  appeal_status      TINYINT         NOT NULL DEFAULT 0 COMMENT '申诉状态: 0=无,1=申诉中,2=申诉通过(指标清零重算),3=申诉驳回(主管审批,审计留痕)',
  appeal_clear_time  DATETIME(3)     NULL DEFAULT NULL COMMENT '申诉清除时间',
  expire_time        DATETIME(3)     NOT NULL COMMENT '画像过期时间(365天滚动,无活动到期归档删除,PIPL最小留存)',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version            INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted         TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记: 0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aft_buyer_profile (tenant_id, platform, buyer_key_hash),
  KEY idx_aft_buyer_profile_score (risk_score),
  KEY idx_aft_buyer_profile_expire (expire_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='跨店铺退货画像(代运营独有跨货主风控数据:风险分/调包嫌疑/申诉清除)(D05.05 V1.3,P1)';

-- ============================================================================
-- 脚本结束 · 共 23 张表（P0×14 / P1×9，V1.3 +aft_buyer_profile）+ 初始字典数据
-- 表清单: aft_reason_dict / aft_return_address / aft_auto_audit_rule
--         aft_return_apply / aft_return_apply_item / aft_return_apply_log
--         aft_reship / aft_reship_item / aft_reship_package / aft_reship_sn
--         aft_defect_disposal / aft_return_logistics
--         aft_refund / aft_refund_alloc / aft_refund_log
--         aft_exchange / aft_exchange_item / aft_exchange_log
--         aft_auto_audit_log / aft_audit_task / aft_risk_flag / aft_timeout_monitor
--         aft_buyer_profile (V1.3)
-- 自查: 括号/逗号/分号配对、COMMENT 内无未转义单引号、JSON 默认值均为 NULL 或显式提供、
--       生成列仅引用同表 JSON 列(json_unquote+json_extract,VIRTUAL+二级索引)
-- ============================================================================
