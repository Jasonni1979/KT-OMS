-- =====================================================================
-- DB-D03 oms_order 订单履约域 建表脚本（MySQL 8.0）
-- 版本 V1.0 · 2026-10-24 · 依据：DB-00 总册 + DB-D03 数据字典 + SRS-D03.01~13
-- 执行顺序：DB-00 建库约定之后执行；与 oms_gateway 无先后依赖（不建物理外键）
-- 约定：utf8mb4/utf8mb4_0900_ai_ci/InnoDB；公共字段见 DB-00 §3；
--       枚举不用 MySQL ENUM（字段注释写全枚举值）；敏感字段 _enc 密文 + _hash 盲索引；
--       日志/流水/追溯类表只增不改（无 update_time/version/is_deleted）
-- 状态机契约：四套状态枚举以 SRS-D03.01 §4.1/§5.1 为唯一权威；
--             发货单指令状态机以 SRS-D03.07 §4.1 为权威；不设 process_status
-- =====================================================================

CREATE DATABASE IF NOT EXISTS oms_order DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE oms_order;

-- ---------------------------------------------------------------------
-- 1. ord_order 订单主表（SRS-D03.01 §6.1；含在线摘要行形态 archive_flag）
--    溯源：商派 ome.orders 改造（process_status 拆分/位图废弃/收货人移出/双口径）
-- ---------------------------------------------------------------------
CREATE TABLE ord_order (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID（内部租户=1）',
  owner_id            BIGINT UNSIGNED NULL COMMENT '货主ID（多货主订单头级为空、行级归属）',
  order_bn            VARCHAR(32)  NOT NULL COMMENT 'OMS订单号：前缀(P平台/L手工/I导入/C换货/B补发/R-B2B)+yyMMdd+店铺码3位+混淆序列7位，共17位，全局唯一',
  platform_order_bn   VARCHAR(64)  NULL COMMENT '平台单号原文（手工/导入单可空）',
  external_bn         VARCHAR(64)  NULL COMMENT '外部单号（导入单幂等键成分）',
  platform_msg_id     VARCHAR(128) NULL COMMENT '平台消息ID（二级防重，重复投递直接ACK）',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID（LFK→oms_gateway.gw_shop）',
  brand_id            BIGINT UNSIGNED NULL COMMENT '品牌ID（LFK→org域；数据权限四维之一）',
  createway           VARCHAR(16)  NOT NULL COMMENT '来源：platform平台/local手工/import导入/exchange换货/b2b经销(P2预留)/after补发',
  order_type          VARCHAR(16)  NOT NULL DEFAULT 'normal' COMMENT '订单类型：normal普通/exchange换货/reship补发/presale预售/groupon团购/luckybag福袋/virtual虚拟',
  special_tags        VARCHAR(128) NULL COMMENT '特殊单型多标签（逗号分隔：presale,groupon,luckybag,virtual；D03.10 detect写入）',
  order_status        VARCHAR(16)  NOT NULL DEFAULT 'processing' COMMENT '总开关：processing进行中/finished已完成/cancelled已取消（取消/完成时四套状态冻结现值）',
  audit_status        VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT '审核状态：pending待审核/passed已审核/rejected驳回/retrial复审中（SRS-D03.01 §4.1契约）',
  fulfill_status      VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT '履约状态：pending待履约/fulfilling履约中/partial_shipped部分发货/shipped已发货/finished完成/paused暂停编排/aftersale售后中',
  pay_status          VARCHAR(16)  NOT NULL DEFAULT 'unpaid' COMMENT '支付状态：unpaid未支付/partial部分支付(预售定金)/paid已支付/refunding退款中/partial_refund部分退款/full_refund全额退款',
  ship_status         VARCHAR(16)  NOT NULL DEFAULT 'unshipped' COMMENT '发货状态：unshipped未发货/partial部分发货/shipped已发货/partial_return部分退货/returned已退货',
  list_amount         DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '原价合计（双口径恒等式：paid=list-shop_discount-platform_subsidy+freight）',
  shop_discount       DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '商家承担优惠合计',
  platform_subsidy    DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '平台承担优惠合计（不摊薄行实付口径，D08双口径供数）',
  paid_amount         DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '客户实付',
  freight             DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '运费（客户实付口径，不参与优惠分摊）',
  is_cod              TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '货到付款：0否/1是（COD未支付可审）',
  promotion_source    VARCHAR(16)  NOT NULL DEFAULT 'organic' COMMENT '推广来源（SRS-D03.01 V1.1 FR-04g，佣金归因）：organic自然流量/taoke淘客联盟/live直播带货/private私域/other其他',
  promotion_pid       VARCHAR(128) NULL COMMENT '推广位ID（淘客pid/京东联盟subunionId/抖音精选联盟，佣金归属键，供D08.01扣费归因）',
  promotion_id        VARCHAR(128) NULL COMMENT '推广活动ID（平台侧推广计划标识）',
  buyer_id_enc        VARBINARY(512) NULL COMMENT '买家标识密文（平台open_id，PIPL信封加密）',
  buyer_nick          VARCHAR(128) NULL COMMENT '买家昵称（展示脱敏）',
  order_time          DATETIME(3)  NOT NULL COMMENT '下单时间',
  pay_time            DATETIME(3)  NULL COMMENT '付款时间（缓冲池排序基准；COD用order_time）',
  combine_hash        CHAR(32)     NULL COMMENT '合单指纹md5（收货人密文标识+区划+COD+店铺参数；空=不参与聚组；改址后重算）',
  combine_idx         INT UNSIGNED NULL COMMENT '同店同指纹序号（D03.05口径）',
  combine_group_id    BIGINT UNSIGNED NULL COMMENT '当前合单组（LFK→ord_combine_group；封窗写入，拆回清空）',
  batch_no            VARCHAR(32)  NULL COMMENT '投审批次号（防重复投审；回池清空）',
  splited_num         INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '拆单轮次计数（每轮落库成功+1；发货单取消不回退；拆分进度为派生视图不设状态字段）',
  router_num          INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '审单路由次数（D03.02回池累加，超限强制人工）',
  is_fail             TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '接入失败标记：0否/1是（硬失败单不进缓冲池，原始报文在ord_order_fail）',
  fail_code           VARCHAR(32)  NULL COMMENT '失败码',
  is_pause            TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '暂停标记：0否/1是（D03.09编排结果：全部发货单叫回处置完成后才置位）',
  cancel_reason_code  VARCHAR(32)  NULL COMMENT '取消原因码（结构化字典）',
  cancel_time         DATETIME(3)  NULL COMMENT '取消时间',
  flag_color          TINYINT      NOT NULL DEFAULT 0 COMMENT '旗帜颜色（V1.4 FR-04h，双向同步平台seller_flag）：0无旗/1红=停发暂缓/2黄=待确认/3绿=优先放行/4蓝=已联系买家/5紫=VIP关注（语义店铺级可配，与平台flag值映射可配）',
  urge_flag           TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '催发货标记（V1.4 FR-04h）：0否/1是（平台催发货消息或客服代标；审单队列提权+推仓加急；发货后自动消标）',
  urge_cnt            INT          NOT NULL DEFAULT 0 COMMENT '催单次数累计（V1.4）',
  first_urge_time     DATETIME(3)  NULL COMMENT '首催时间（V1.4，临近平台承诺发货时效48h红色告警依据）',
  warehouse_memo      VARCHAR(512) NULL COMMENT '商家备注（卖家备注，多条追加存JSON于platform_extra.seller_memo_timeline或本列摘要；敏感词打标供审单memo_flag插件）',
  buyer_memo          VARCHAR(512) NULL COMMENT '买家留言（PIPL：可能含敏感信息，展示脱敏）',
  logi_id             BIGINT UNSIGNED NULL COMMENT '物流公司ID（LFK→oms_fulfill；首发货单回写）',
  logi_no             VARCHAR(64)  NULL COMMENT '运单号（多运单存包裹表）',
  delivery_time       DATETIME(3)  NULL COMMENT '发货时间（全部出库确认时点）',
  finish_time         DATETIME(3)  NULL COMMENT '完结时间（fulfill=finished时点；归档时滞基准）',
  self_delivery       TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '自发货店铺标记：0否/1是',
  cross_border_type   VARCHAR(16)  NULL COMMENT '跨境类型（P2预留）：NULL无/bonded保税/direct直邮',
  declare_status      VARCHAR(16)  NOT NULL DEFAULT 'none' COMMENT '申报状态（P0预留独立字段，SRS-D03.12 §4.2）：none无需申报/wait待申报/declaring申报中/released放行/failed申报失败/returned已退单/exported已出区/refund_declare退单申报',
  declare_id          BIGINT UNSIGNED NULL COMMENT '申报单引用（LFK→ord_declare，P2）',
  platform_extra      JSON         NULL COMMENT '平台扩展属性（source_status/step_trade_status/orderhost达人/store_code指定仓/promised时效等原始报文关键属性留档）',
  archive_flag        VARCHAR(16)  NOT NULL DEFAULT 'online' COMMENT '归档标记：online在线/archived已归档/recalled已回捞（摘要行形态，SRS-D03.13 §4.3；摘要行永久保留）',
  archive_locator     JSON         NULL COMMENT '归档库定位键：{shard_table,unit_id}（明细删除后凭此读归档库oms_archive）',
  archive_time        DATETIME(3)  NULL COMMENT '归档时间',
  recall_flag         TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '回捞标记：0否/1是（冷却期判定依据）',
  recall_time         DATETIME(3)  NULL COMMENT '最近回捞时间',
  source              VARCHAR(16)  NOT NULL DEFAULT 'api' COMMENT '数据来源：api/local/import/migration（DB-00 §7）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间（接入时间）',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁（状态写入CAS）',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_order_order_bn (order_bn),
  UNIQUE KEY uk_ord_order_shop_platform (shop_id, platform_order_bn),
  KEY idx_ord_order_shop_ext (shop_id, external_bn),
  KEY idx_ord_order_status (audit_status, order_status, pay_time),
  KEY idx_ord_order_combine (shop_id, combine_hash, combine_idx),
  KEY idx_ord_order_batch (batch_no),
  KEY idx_ord_order_fulfill (fulfill_status, finish_time),
  KEY idx_ord_order_paytime (pay_time),
  KEY idx_ord_order_promotion (promotion_source, promotion_pid),
  KEY idx_ord_order_flag (flag_color, urge_flag),
  KEY idx_ord_order_archive (archive_flag)
) ENGINE=InnoDB COMMENT='订单主表（订单聚合根头表，四套状态+双口径金额+归档摘要行，D03.01）';

-- ---------------------------------------------------------------------
-- 2. ord_order_item 订单行（BOM展开快照，SRS-D03.01 §6.2）
--    溯源：商派 ome.order_items + order_objects 合并改造
-- ---------------------------------------------------------------------
CREATE TABLE ord_order_item (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NULL COMMENT '行级货主（BOM展开取基础物料货主；跨货主同单允许，按货主拆单依据）',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '归属订单（LFK→ord_order）',
  sm_id               BIGINT UNSIGNED NULL COMMENT '销售物料ID（LFK→oms_stock.inv_material；快照留档）',
  platform_sku_code   VARCHAR(64)  NULL COMMENT '平台商品/SKU编码原文',
  platform_oid        VARCHAR(64)  NULL COMMENT '平台子单号oid（order_host拆单策略分组键；商派order_objects.oid）',
  bm_id               BIGINT UNSIGNED NULL COMMENT 'BOM展开快照：基础物料ID（落库固化，档案变更不回溯；未绑定时NULL+parse_status=pending）',
  bm_number           VARCHAR(64)  NULL COMMENT '基础物料编码快照',
  bm_name             VARCHAR(256) NULL COMMENT '基础物料名称快照',
  parent_item_id      BIGINT UNSIGNED NULL COMMENT '组合装父行引用（展开子行必填；金额按rate/fixed_price分摊继承）',
  nums                INT          NOT NULL DEFAULT 0 COMMENT '购买数量',
  split_num           INT          NOT NULL DEFAULT 0 COMMENT '已拆数量（发货单落库累加/取消打回扣减；≤nums强校验）',
  sendnum             INT          NOT NULL DEFAULT 0 COMMENT '已发数量（出库回传settle聚合，ship_status派生依据）',
  refund_num          INT          NOT NULL DEFAULT 0 COMMENT '已退数量（D05.02退货入库回写）',
  list_price          DECIMAL(18,4) NOT NULL DEFAULT 0 COMMENT '行原价单价',
  list_amount         DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '行原价金额',
  shop_discount       DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '行分摊商家优惠（Σ行=单，尾差归最大金额行）',
  platform_subsidy    DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '行分摊平台承担优惠（双口径二次拆分）',
  paid_amount         DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '行客户实付（=list-shop-platform；退款计算基数，D05取数口径）',
  bom_version         INT UNSIGNED NULL COMMENT 'BOM快照版本（追溯用）',
  bom_candidates      JSON         NULL COMMENT '多选一候选集（审单择一后回填bm_id）',
  is_virtual          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '虚拟行：0否/1是（免推仓，走D03.10自动发货分支）',
  is_gift             TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '赠品行：0否/1是（gift_separate拆单策略识别；仅赠品订单拒绝出单转人工）',
  parse_status        VARCHAR(16)  NOT NULL DEFAULT 'parsed' COMMENT '行解析状态：parsed已解析/pending待解析(商品未绑定)/failed解析失败',
  estimate_con_time   DATETIME(3)  NULL COMMENT '预售预计发货时间（行级，D03.10用）',
  weight              DECIMAL(18,4) NULL COMMENT '行重量kg（weight拆单策略输入快照）',
  tax_amount          DECIMAL(18,2) NULL COMMENT '行税费（P2跨境预留，SRS-D03.12 §6.4）',
  platform_extra      JSON         NULL COMMENT '平台行级扩展（divide_order_fee平台行级分摊原值/promotion_id/达人信息等）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  KEY idx_ord_order_item_order (order_id),
  KEY idx_ord_order_item_bm (bm_id, owner_id),
  KEY idx_ord_order_item_sm (sm_id),
  KEY idx_ord_order_item_parse (parse_status)
) ENGINE=InnoDB COMMENT='订单行（BOM展开快照固化，行级双口径分摊，D03.01）';

-- ---------------------------------------------------------------------
-- 3. ord_receiver 收货人（PIPL加密表，SRS-D03.01 §6.3，对齐D01.05）
--    溯源：商派 ome.order_receiver 改造（全字段_enc+_hash信封加密）
-- ---------------------------------------------------------------------
CREATE TABLE ord_receiver (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NULL COMMENT '货主ID',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '归属订单（1:1，LFK→ord_order）',
  name_enc            VARBINARY(512) NOT NULL COMMENT '收货人姓名密文（KMS信封加密，D01.05）',
  name_hash           CHAR(64)     NULL COMMENT '姓名盲索引（HMAC-SHA256等值检索；密文单用平台稳定串）',
  mobile_enc          VARBINARY(512) NOT NULL COMMENT '手机密文',
  mobile_hash         CHAR(64)     NULL COMMENT '手机盲索引',
  mobile_tail4        CHAR(4)      NULL COMMENT '手机末四位（脱敏检索辅助，非敏感）',
  phone_enc           VARBINARY(512) NULL COMMENT '固定电话密文',
  province            VARCHAR(32)  NULL COMMENT '省（地址库标准名，非敏感明文）',
  city                VARCHAR(32)  NULL COMMENT '市',
  district            VARCHAR(32)  NULL COMMENT '区/县',
  town                VARCHAR(64)  NULL COMMENT '街道/镇',
  area_code           VARCHAR(16)  NULL COMMENT '标准行政区划码（解析失败NULL+地址待清洗标）',
  address_enc         VARBINARY(1024) NOT NULL COMMENT '详址密文',
  address_hash        CHAR(64)     NULL COMMENT '详址盲索引（合单指纹成分）',
  zip                 VARCHAR(16)  NULL COMMENT '邮编',
  is_cipher           TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '平台密文单标识：0否/1是（抖音/拼多多：打单必须用原密文，商派is_encrypt机制）',
  cipher_blob         JSON         NULL COMMENT '平台密文原文包（姓名/电话/地址密文串+密文标识，原样保存不解密）',
  key_version         VARCHAR(32)  NOT NULL DEFAULT 'v1' COMMENT '加密密钥版本（轮换支持）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_receiver_order (order_id),
  KEY idx_ord_receiver_mobile_hash (mobile_hash),
  KEY idx_ord_receiver_name_hash (name_hash),
  KEY idx_ord_receiver_addr_hash (address_hash)
) ENGINE=InnoDB COMMENT='收货人（PIPL加密：姓名/电话/地址_enc密文+_hash盲索引；明文查看需授权点+留痕，D03.01）';

-- ---------------------------------------------------------------------
-- 4. ord_order_pmt 优惠分摊明细（双口径二次拆分，SRS-D03.01 §6.4）
--    溯源：商派 ome.order_pmt 改造（+bearer承担方/+item_id行级/+pmt_type字典化）
-- ---------------------------------------------------------------------
CREATE TABLE ord_order_pmt (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NULL COMMENT '货主ID',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '归属订单（LFK→ord_order）',
  item_id             BIGINT UNSIGNED NULL COMMENT '归属订单行（NULL=单级分摊，非空=行级；LFK→ord_order_item）',
  pmt_type            VARCHAR(32)  NOT NULL COMMENT '优惠类型（字典可扩展）：platform_coupon平台券/shop_full_reduce店铺满减/item_discount单品直降/freight_coupon运费券/other其他',
  bearer              VARCHAR(16)  NOT NULL COMMENT '承担方：platform平台/shop商家（双口径核心维度；D08.01应收与平台结算分别取数）',
  amount              DECIMAL(18,2) NOT NULL COMMENT '优惠金额（>0；行级Σ=单级）',
  platform_pmt_id     VARCHAR(64)  NULL COMMENT '平台优惠流水号（D08对账用）',
  pmt_memo            VARCHAR(256) NULL COMMENT '优惠说明（平台原文）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  KEY idx_ord_order_pmt_order (order_id),
  KEY idx_ord_order_pmt_item (item_id)
) ENGINE=InnoDB COMMENT='优惠分摊明细（单级+行级两层，双口径bearer维度，D03.01）';

-- ---------------------------------------------------------------------
-- 5. ord_order_invoice 发票申请信息（SRS-D03.01 §6.4；状态流转归D08.05）
-- ---------------------------------------------------------------------
CREATE TABLE ord_order_invoice (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NULL COMMENT '货主ID',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '归属订单（1:1，LFK→ord_order）',
  invoice_type        VARCHAR(16)  NOT NULL COMMENT '发票类型：e_normal电子普票/special专票/paper纸质普票',
  title_type          VARCHAR(16)  NOT NULL COMMENT '抬头类型：personal个人/company企业（企业必填税号）',
  title               VARCHAR(256) NOT NULL COMMENT '发票抬头',
  tax_no              VARCHAR(32)  NULL COMMENT '税号（格式校验；审单invoice_check插件用）',
  register_no         VARCHAR(64)  NULL COMMENT '工商注册号',
  amount              DECIMAL(18,2) NULL COMMENT '开票金额',
  invoice_status      VARCHAR(16)  NOT NULL DEFAULT 'applied' COMMENT '状态快照：applied已申请/issuing开票中/issued已开票/failed开票失败（权威流转在D08.05）',
  invoice_extra       JSON         NULL COMMENT '扩展要素（开户行/账号/地址电话/收票邮箱等）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_order_invoice_order (order_id)
) ENGINE=InnoDB COMMENT='发票申请信息（本域只落申请要素，开票状态归D08.05，D03.01）';

-- ---------------------------------------------------------------------
-- 6. ord_status_log 状态变迁日志（SRS-D03.01 FR-05b；只增不改禁软删）
-- ---------------------------------------------------------------------
CREATE TABLE ord_status_log (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NULL COMMENT '货主ID',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '归属订单（LFK→ord_order）',
  order_bn            VARCHAR(32)  NOT NULL COMMENT '订单号冗余（免JOIN检索）',
  status_domain       VARCHAR(16)  NOT NULL COMMENT '状态域：audit审核/fulfill履约/pay支付/ship发货/order总开关',
  from_value          VARCHAR(16)  NOT NULL COMMENT '前值（枚举同ord_order对应列）',
  to_value            VARCHAR(16)  NOT NULL COMMENT '后值',
  trigger_source      VARCHAR(32)  NOT NULL COMMENT '触发方：D03.02/D03.03/D03.07/D03.08/D05.02/D05.03/D09.02/D01.02/schedule等',
  trigger_ref         VARCHAR(64)  NULL COMMENT '触发单据引用（发货单号/退款单号/复审单号等）',
  operator            VARCHAR(64)  NOT NULL COMMENT '操作者（system或账户ID）',
  memo                VARCHAR(256) NULL COMMENT '备注',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间（变迁时间）',
  PRIMARY KEY (id),
  KEY idx_ord_status_log_order (order_id, status_domain),
  KEY idx_ord_status_log_time (create_time)
) ENGINE=InnoDB COMMENT='四套状态变迁日志（transit唯一入口全留痕，状态机审计依据，D03.01）';

-- ---------------------------------------------------------------------
-- 7. ord_order_fail 接入失败单（SRS-D03.01 §5.5硬失败；商派is_fail/api_fail机制）
-- ---------------------------------------------------------------------
CREATE TABLE ord_order_fail (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NULL COMMENT '货主ID',
  fail_bn             VARCHAR(32)  NOT NULL COMMENT '失败单号（FAIL+日期+序列）',
  shop_id             BIGINT UNSIGNED NULL COMMENT '店铺ID（可解析时填）',
  platform_order_bn   VARCHAR(64)  NULL COMMENT '平台单号（可解析时填）',
  platform_msg_id     VARCHAR(128) NULL COMMENT '平台消息ID',
  createway           VARCHAR(16)  NOT NULL DEFAULT 'platform' COMMENT '来源（枚举同ord_order.createway）',
  fail_code           VARCHAR(32)  NOT NULL COMMENT '失败码：SHOP_INVALID店铺无效/AUTH_EXPIRED授权过期/AMOUNT_MISMATCH金额勾稽超差/ITEM_EMPTY商品行空/REQUIRED_MISSING必填缺失',
  fail_reason         VARCHAR(512) NULL COMMENT '失败原因（人读）',
  raw_payload         JSON         NULL COMMENT 'canonical原始报文（>2KB存OSS引用，DB-00 §1.3）',
  handle_status       VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT '处理状态：pending待处理/repushed已修复重推/ignored已忽略',
  retry_count         INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '重推次数',
  operator            VARCHAR(64)  NULL COMMENT '处理人',
  handle_time         DATETIME(3)  NULL COMMENT '处理时间',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_order_fail_bn (fail_bn),
  KEY idx_ord_order_fail_status (handle_status, create_time),
  KEY idx_ord_order_fail_shop (shop_id, platform_order_bn)
) ENGINE=InnoDB COMMENT='接入失败单（硬失败拒单原始报文留档，独立列表人工修复重推，D03.01）';

-- ---------------------------------------------------------------------
-- 8. ord_audit_rule 审单规则配置（SRS-D03.02 §6.1；三层：条件/插件/动作）
-- ---------------------------------------------------------------------
CREATE TABLE ord_audit_rule (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NULL COMMENT '货主ID（规则可按货主隔离）',
  rule_name           VARCHAR(128) NOT NULL COMMENT '规则名称（租户内唯一）',
  conditions          JSON         NOT NULL COMMENT '条件层：18维度数组[{dim,op,values}]（店铺/品牌/货主/平台/金额区间/订单类型/商品分类/SKU含指定/物料类型/SKU种类数/明细件数/重量/COD/收货地区/有无备注/买家标签/达人/客户分类），AND组合、同维度多值OR',
  weight              INT          NOT NULL DEFAULT 0 COMMENT '优先级（DESC排序首个全命中生效）',
  plugin_config       JSON         NULL COMMENT '插件层：逐插件{name,enable,params}覆盖（未配置走全局默认参数）',
  auto_confirm        TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '自动通过开关：0决策草稿转人工确认/1自动产出plan',
  pass_action         VARCHAR(32)  NOT NULL DEFAULT 'exec_plan' COMMENT '通过动作：exec_plan生成plan执行/draft_confirm仅决策转人工确认',
  fail_route          JSON         NULL COMMENT '不通过路由表：{原因码→manual人工/shortage缺货/retrial复审/requeue回池}（缺省用原因码字典默认路由）',
  effective_window    JSON         NULL COMMENT '生效时段（周期时段表达式）',
  exclude_window      JSON         NULL COMMENT '排除时段（大促夜间停审）',
  default_audit_group BIGINT UNSIGNED NULL COMMENT '缺省审核组（LFK→ord_audit_group；D03.03分派规则优先）',
  router_num_limit    INT UNSIGNED NOT NULL DEFAULT 5 COMMENT '路由次数上限（防回池死循环）',
  status              VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '启停：enabled启用/disabled停用',
  is_default          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '系统内置缺省规则：0否/1是（不可删，autoConfirm=关全转人工）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_audit_rule_name (tenant_id, rule_name),
  KEY idx_ord_audit_rule_weight (weight)
) ENGINE=InnoDB COMMENT='审单规则配置（条件18维/插件开关参数/动作路由三层，weight DESC首命中，D03.02）';

-- ---------------------------------------------------------------------
-- 9. ord_fulfill_plan 履约方案（SRS-D03.02 §6.2；plan四要素，决策执行分离）
-- ---------------------------------------------------------------------
CREATE TABLE ord_fulfill_plan (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键（plan_id）',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID（组内订单货主一致才可merge）',
  plan_bn             VARCHAR(32)  NOT NULL COMMENT '方案号（PL+日期+序列），唯一',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '首订单（检索用，LFK→ord_order）',
  order_ids           JSON         NOT NULL COMMENT '覆盖订单集（合单组多单共享一plan）',
  plan_version        INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '版本（按order_id递增；同单唯一非终态；打回重审产出新version，版本链完整保留可回放）',
  warehouse_alloc     JSON         NOT NULL COMMENT '仓库分配：组→{branch_id,候选仓快照,选择依据}',
  split_matrix        JSON         NOT NULL COMMENT '拆单方案：行→发货单组分配矩阵[{item_id,num,group_key,strategy_id}]',
  logistics_alloc     JSON         NOT NULL COMMENT '物流方案：组→{logi_id,区域/重量/费用匹配依据快照}',
  combine_group       JSON         NULL COMMENT '合单组：母子单结构标记{group_id,parent_order_id,members}',
  rule_snapshot_id    VARCHAR(64)  NULL COMMENT '规则快照ID（D01.03快照库，回放依据）',
  plugin_trace        JSON         NULL COMMENT '插件决策明细：各插件输出/耗时/原因（MUTATE结果）',
  decision_by         VARCHAR(64)  NOT NULL COMMENT '决策者：auto自动 或 账户ID（人工同源执行，FR-05f）',
  decision_time       DATETIME(3)  NOT NULL COMMENT '决策时间',
  plan_status         VARCHAR(16)  NOT NULL DEFAULT 'draft' COMMENT '决策状态：draft草稿(转人工确认)/pending待执行/discarded已废弃(打回重审)',
  exec_status         VARCHAR(16)  NOT NULL DEFAULT 'waiting' COMMENT '执行状态：waiting待执行/executing执行中/success成功/partial部分成功/failed_compensated失败已补偿',
  delivery_ids        JSON         NULL COMMENT '执行产物发货单ID集',
  fail_code           VARCHAR(32)  NULL COMMENT '执行失败码：STOCK_RACE库存竞态(回待审或转缺货)/DELIVERY_CREATE_FAIL/RESERVE_FAIL',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID（四维过滤）',
  brand_id            BIGINT UNSIGNED NULL COMMENT '品牌ID',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_fulfill_plan_bn (plan_bn),
  UNIQUE KEY uk_ord_fulfill_plan_order_ver (order_id, plan_version),
  KEY idx_ord_fulfill_plan_exec (exec_status, plan_status),
  KEY idx_ord_fulfill_plan_shop (shop_id)
) ENGINE=InnoDB COMMENT='履约方案（plan四要素：仓库分配/拆单方案/物流方案/合单组；可重算可回放，D03.02）';

-- ---------------------------------------------------------------------
-- 10. ord_audit_reason 结构化审核原因（SRS-D03.02 §6.3；替代商派auto_status位图）
-- ---------------------------------------------------------------------
CREATE TABLE ord_audit_reason (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NULL COMMENT '货主ID',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '归属订单（LFK→ord_order）',
  batch_no            VARCHAR(32)  NULL COMMENT '审单批次（重审按order_id+batch_no归档旧记录再写新）',
  plugin_name         VARCHAR(64)  NOT NULL COMMENT '插件名：admit_special/admit_status/admit_pay/blacklist/branch_select/split/stock_check/logi_match/combine_check/goods_match/price_check/address_check/memo_flag/gift_check/invoice_check/amount_check/routernum/label_mark/auto_pass',
  reason_code         VARCHAR(64)  NOT NULL COMMENT '原因码（D01.03字典登记，初始集见文末INSERT）',
  level               VARCHAR(8)   NOT NULL COMMENT '级别：BLOCK拦截(触发路由)/WARN提示(不拦截随单流转)',
  description         VARCHAR(1024) NULL COMMENT '人读描述（含数据快照文本：缺口数量/命中关键字/候选仓列表）',
  detail              JSON         NULL COMMENT '决策明细结构化（工作台渲染与统计下钻）',
  suggest_action      VARCHAR(32)  NULL COMMENT '建议动作字典：change_branch换仓/modify_address改地址/contact_buyer联系买家/wait_restock等补货/to_retrial转复审/reship补发',
  route_target        VARCHAR(16)  NULL COMMENT '路由结果：manual人工/shortage缺货/retrial复审/requeue回池/suspend挂起',
  handle_status       VARCHAR(16)  NOT NULL DEFAULT 'open' COMMENT '原因状态：open未处理/handled已处理（人工处理后回填处理方式）',
  handle_way          VARCHAR(64)  NULL COMMENT '处理方式回填',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID（统计维度冗余）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  KEY idx_ord_audit_reason_order (order_id, batch_no),
  KEY idx_ord_audit_reason_code (reason_code, create_time),
  KEY idx_ord_audit_reason_shop (shop_id, create_time)
) ENGINE=InnoDB COMMENT='结构化审核原因（插件/原因码/级别/建议动作/路由，替代位标记，D03.02）';

-- ---------------------------------------------------------------------
-- 11. ord_audit_batch_log 审单批次日志（SRS-D03.02 §6.4；只增）
-- ---------------------------------------------------------------------
CREATE TABLE ord_audit_batch_log (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  batch_no            VARCHAR(32)  NOT NULL COMMENT '审单批次号，唯一',
  group_count         INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '订单组数',
  order_count         INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '订单数',
  result_dist         JSON         NULL COMMENT '结果分布：{passed,manual,shortage,requeue,retrial}',
  total_cost_ms       INT UNSIGNED NULL COMMENT '批次总耗时ms',
  worker_id           VARCHAR(64)  NULL COMMENT '消费实例标识',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_audit_batch_log_bn (batch_no),
  KEY idx_ord_audit_batch_log_time (create_time)
) ENGINE=InnoDB COMMENT='审单批次日志（吞吐指标上报D11.03源数据，只增，D03.02）';

-- ---------------------------------------------------------------------
-- 12. ord_audit_plugin_perf 插件耗时日志（SRS-D03.02 FR-01e；只增，在线3个月滚动清理）
-- ---------------------------------------------------------------------
CREATE TABLE ord_audit_plugin_perf (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  batch_no            VARCHAR(32)  NULL COMMENT '审单批次号',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '订单ID',
  plugin_name         VARCHAR(64)  NOT NULL COMMENT '插件名（枚举同ord_audit_reason.plugin_name）',
  phase               VARCHAR(16)  NOT NULL COMMENT '插件段：ADMIT准入/WAREHOUSE仓/STOCK库存/LOGISTICS物流/CHECK校验',
  cost_ms             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '耗时ms（单插件P99>500ms告警）',
  result              VARCHAR(16)  NOT NULL COMMENT '结果：PASS通过/HOLD挂起/SHORT_CIRCUIT短路/MUTATE数据变更/ERROR异常',
  reason_codes        VARCHAR(512) NULL COMMENT '原因码集（逗号分隔）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  KEY idx_ord_audit_plugin_perf_order (order_id),
  KEY idx_ord_audit_plugin_perf_plugin (plugin_name, create_time)
) ENGINE=InnoDB COMMENT='审单插件耗时日志（TOP慢插件分析源，只增滚动清理，D03.02）';

-- ---------------------------------------------------------------------
-- 13. ord_dispatch_rule 人工审单分派规则（SRS-D03.03 §6.1）
-- ---------------------------------------------------------------------
CREATE TABLE ord_dispatch_rule (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  rule_name           VARCHAR(128) NOT NULL COMMENT '规则名（租户内唯一）',
  conditions          JSON         NOT NULL COMMENT '条件维度数组（店铺/品牌/货主/平台/金额区间/订单分类/原因码集/商品分类/买家标签，AND组合）',
  weight              INT          NOT NULL DEFAULT 0 COMMENT '优先级（DESC首命中）',
  target_group_id     BIGINT UNSIGNED NOT NULL COMMENT '目标审核组（LFK→ord_audit_group）',
  target_op_id        BIGINT UNSIGNED NULL COMMENT '直接指定人（跳过负载均衡）',
  strategy            VARCHAR(16)  NOT NULL DEFAULT 'round_robin' COMMENT '负载策略：round_robin轮询/least_task最少任务',
  filter_on_duty      TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '在班过滤开关：0关/1开（默认开）',
  status              VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '启停：enabled启用/disabled停用',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_dispatch_rule_name (tenant_id, rule_name),
  KEY idx_ord_dispatch_rule_weight (weight)
) ENGINE=InnoDB COMMENT='人工审单分派规则（多维条件→目标组→负载策略选人，D03.03）';

-- ---------------------------------------------------------------------
-- 14. ord_audit_group 审核组（SRS-D03.03 §6.2；成员JSON收敛）
-- ---------------------------------------------------------------------
CREATE TABLE ord_audit_group (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  group_name          VARCHAR(128) NOT NULL COMMENT '组名（租户内唯一）',
  org_id              BIGINT UNSIGNED NULL COMMENT '归属组织（LFK→oms_org.org_node）',
  leader_op_id        BIGINT UNSIGNED NULL COMMENT '组长账户（回收/指派权限载体，LFK→org_account）',
  default_shop_scope  JSON         NULL COMMENT '默认数据范围：店铺/品牌/货主集合（分派候选过滤用）',
  members             JSON         NOT NULL COMMENT '成员集[{op_id,duty_status(on在班/off离班/leave请假),task_limit(默认50),skill_tags[]}]',
  status              VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '启停：enabled启用/disabled停用',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_audit_group_name (tenant_id, group_name)
) ENGINE=InnoDB COMMENT='审核组（含成员集JSON：在班状态/任务上限/技能标签，D03.03）';

-- ---------------------------------------------------------------------
-- 15. ord_audit_task 人工审单任务（SRS-D03.03 §6.3；一单一活跃任务）
-- ---------------------------------------------------------------------
CREATE TABLE ord_audit_task (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '归属订单（LFK→ord_order；驳回重提生成新任务历史留档）',
  batch_no            VARCHAR(32)  NULL COMMENT '审单批次',
  assign_group        BIGINT UNSIGNED NULL COMMENT '分派组（LFK→ord_audit_group）',
  assign_op           BIGINT UNSIGNED NULL COMMENT '分派审核员（LFK→org_account）',
  assign_time         DATETIME(3)  NULL COMMENT '分派时间',
  assign_way          VARCHAR(16)  NULL COMMENT '分派方式：rule规则/manual手动指派/transfer转派/recycle回收重分',
  task_status         VARCHAR(16)  NOT NULL DEFAULT 'wait_assign' COMMENT '任务状态（SRS-D03.03 §4.2状态机）：wait_assign待分派/assigned已分派/processing处理中/executing执行中/rejected已驳回/skip_approving跳过审批中/finished已完结/transferred转出',
  lock_op             BIGINT UNSIGNED NULL COMMENT '处理中软锁人',
  lock_expire         DATETIME(3)  NULL COMMENT '软锁过期时间（默认30分钟自动释放）',
  sla_deadline        DATETIME(3)  NULL COMMENT 'SLA截止时间',
  overtime_level      TINYINT      NOT NULL DEFAULT 0 COMMENT '超时级别：0正常/1组长/2运营负责人（50%提醒→100%组长→150%负责人）',
  result              VARCHAR(16)  NULL COMMENT '终态结果：passed通过/rejected驳回/skipped跳过/transferred转出',
  result_reason_code  VARCHAR(64)  NULL COMMENT '驳回原因码（结构化字典）',
  plan_id             BIGINT UNSIGNED NULL COMMENT '关联人工plan（通过/跳过时必填，LFK→ord_fulfill_plan）',
  approval_id         VARCHAR(64)  NULL COMMENT 'OA审批单号（跳过审单必填，LFK→org_approval）',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID（队列过滤）',
  is_active           TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '活跃任务标记：0历史/1活跃（一单一活跃）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  KEY idx_ord_audit_task_op (assign_op, task_status, is_active),
  KEY idx_ord_audit_task_group (assign_group, task_status),
  KEY idx_ord_audit_task_order (order_id),
  KEY idx_ord_audit_task_sla (task_status, sla_deadline)
) ENGINE=InnoDB COMMENT='人工审单任务（分派/认领/软锁/SLA/终态，D03.03）';

-- ---------------------------------------------------------------------
-- 16. ord_audit_work_log 审单作业埋点流水（SRS-D03.03 §6.3；只增，绩效统计源）
-- ---------------------------------------------------------------------
CREATE TABLE ord_audit_work_log (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  task_id             BIGINT UNSIGNED NOT NULL COMMENT '审单任务（LFK→ord_audit_task）',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '订单ID',
  op_id               BIGINT UNSIGNED NOT NULL COMMENT '操作人账户',
  action              VARCHAR(32)  NOT NULL COMMENT '动作：assign分派/dispatch指派/transfer转派/recycle回收/open打开/pass通过/reject驳回/skip跳过/batch_pass批量通过/batch_item批量项',
  from_op             BIGINT UNSIGNED NULL COMMENT '转出人',
  to_op               BIGINT UNSIGNED NULL COMMENT '转入人',
  batch_flag          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '批量单列标记：0否/1是',
  memo                VARCHAR(256) NULL COMMENT '备注',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间（动作时间）',
  PRIMARY KEY (id),
  KEY idx_ord_audit_work_log_op (op_id, create_time),
  KEY idx_ord_audit_work_log_task (task_id)
) ENGINE=InnoDB COMMENT='审单作业埋点流水（绩效统计源，D11物化日结，只增，D03.03）';

-- ---------------------------------------------------------------------
-- 17. ord_split_rule 拆单策略规则（SRS-D03.04 §6.1；16策略+三级级联）
-- ---------------------------------------------------------------------
CREATE TABLE ord_split_rule (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID（货主隔离）',
  rule_name           VARCHAR(128) NOT NULL COMMENT '规则名（租户内唯一）',
  split_type          VARCHAR(32)  NOT NULL COMMENT '一级策略类型码（16选1）：branch按仓/owner按货主/sku按SKU/goods_type实物虚拟/customer_classify客户分类/sku_category商品分类/weight重量/volume体积/store门店/gift_separate赠品分离/presale预售现货/order_host平台子单/stock_depth库存深度/channel渠道/virtual_sku虚拟SKU/cascade级联编排器',
  split_config        JSON         NOT NULL COMMENT '一级策略配置（按策略注册schema保存期校验）',
  split_type_2        VARCHAR(32)  NULL COMMENT '二级级联策略（类型≠一级）',
  split_config_2      JSON         NULL COMMENT '二级配置',
  split_type_3        VARCHAR(32)  NULL COMMENT '三级级联策略（≠一二级；须在一级getSpecial兼容清单内）',
  split_config_3      JSON         NULL COMMENT '三级配置',
  scope_type          VARCHAR(16)  NOT NULL DEFAULT 'global' COMMENT '生效范围：global全局/shop店铺/order_group订单分组（D03.02审单配置引用）',
  scope_ref           JSON         NULL COMMENT '范围引用（店铺ID集等）',
  confirm_source      VARCHAR(16)  NOT NULL DEFAULT 'all' COMMENT '适用审单来源：auto自动/manual手工/all全部',
  status              VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '启停：enabled启用/disabled停用（停用后引用报错）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁（规则版本号）',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_split_rule_name (tenant_id, rule_name),
  KEY idx_ord_split_rule_type (split_type)
) ENGINE=InnoDB COMMENT='拆单策略规则（策略类型码+JSON配置+三级级联，D03.04）';

-- ---------------------------------------------------------------------
-- 18. ord_split_trace 拆分追溯轨迹（SRS-D03.04 §6.2；不可变只追加）
-- ---------------------------------------------------------------------
CREATE TABLE ord_split_trace (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '归属订单（LFK→ord_order）',
  round_no            INT UNSIGNED NOT NULL COMMENT '拆单轮次（=splited_num递增值）',
  split_rule_id       BIGINT UNSIGNED NOT NULL COMMENT '拆单规则（LFK→ord_split_rule）',
  rule_snapshot       JSON         NOT NULL COMMENT '规则快照：策略链+各级config（不可变追溯依据）',
  input_snapshot      JSON         NOT NULL COMMENT '输入明细快照：行/数量/货主/关键属性',
  group_result        JSON         NOT NULL COMMENT '分组结果：组键/行分配/组属性（branch/owner/virtual等）',
  source              VARCHAR(16)  NOT NULL DEFAULT 'auto' COMMENT '执行来源：auto自动/manual手工（含操作人账号）',
  result_status       VARCHAR(16)  NOT NULL COMMENT '结果：success成功/fail失败',
  delivery_ids        JSON         NULL COMMENT '成功产物发货单ID列表',
  err_code            VARCHAR(32)  NULL COMMENT '失败错误码族：NO_STOCK/CONFIG_INVALID/PRECONDITION_UNMET/CONSERVATION_VIOLATION',
  err_detail          JSON         NULL COMMENT '失败明细',
  cost_ms             INT UNSIGNED NULL COMMENT '耗时ms（策略性能观测，D11.03）',
  operator            VARCHAR(64)  NOT NULL DEFAULT 'system' COMMENT '操作人（auto=system/manual=真实账号）',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_split_trace_order_round (order_id, round_no),
  KEY idx_ord_split_trace_rule (split_rule_id, create_time)
) ENGINE=InnoDB COMMENT='拆分追溯轨迹（策略快照+输入快照+分组结果，只增，D03.04）';

-- ---------------------------------------------------------------------
-- 19. ord_combine_group 合单组台账（SRS-D03.05 §6.2）
-- ---------------------------------------------------------------------
CREATE TABLE ord_combine_group (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID（组内订单货主须一致才可merge，发货单owner唯一约束传导）',
  group_bn            VARCHAR(32)  NOT NULL COMMENT '合单组号（CB+日期+序列），唯一',
  combine_hash        CHAR(32)     NOT NULL COMMENT '合单指纹md5',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID（同店约束）',
  member_order_ids    JSON         NOT NULL COMMENT '成员订单集（封窗后锁定）',
  window_start        DATETIME(3)  NOT NULL COMMENT '窗口起点（=最早付款时间）',
  window_end          DATETIME(3)  NULL COMMENT '窗口终点',
  status              VARCHAR(16)  NOT NULL DEFAULT 'grouping' COMMENT '组状态：grouping聚组中/hold等待/sealed已封窗/merged已merge/split_back已拆回/voided已作废',
  seal_result         JSON         NULL COMMENT '封箱结果：切组明细/被切出订单与原因',
  parent_delivery_id  BIGINT UNSIGNED NULL COMMENT '母发货单（merge后写入，LFK→ord_delivery）',
  source              VARCHAR(16)  NOT NULL DEFAULT 'auto' COMMENT '来源：auto自动/manual手工',
  operator            VARCHAR(64)  NULL COMMENT '手工操作人',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_combine_group_bn (group_bn),
  KEY idx_ord_combine_group_hash (shop_id, combine_hash, status),
  KEY idx_ord_combine_group_status (status, window_end)
) ENGINE=InnoDB COMMENT='合单组台账（聚组→封窗→merge母发货单/拆回/作废生命周期，D03.05）';

-- ---------------------------------------------------------------------
-- 20. ord_combine_blacklist 平台合单黑名单（SRS-D03.05 §6.4）
-- ---------------------------------------------------------------------
CREATE TABLE ord_combine_blacklist (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  level               VARCHAR(16)  NOT NULL COMMENT '级别：platform平台/shop_type店铺类型/tag标签',
  match_key           VARCHAR(64)  NOT NULL COMMENT '匹配键（平台码/店铺类型/标签码）',
  rule                VARCHAR(16)  NOT NULL COMMENT '规则：forbid禁合/same_tag_only仅同标签合',
  reason              VARCHAR(256) NULL COMMENT '原因（变更审计）',
  effective_start     DATETIME(3)  NULL COMMENT '生效开始',
  effective_end       DATETIME(3)  NULL COMMENT '生效结束',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  KEY idx_ord_combine_blacklist_key (level, match_key)
) ENGINE=InnoDB COMMENT='平台合单黑名单（三级禁合/仅同标签合规则，D03.05）';

-- ---------------------------------------------------------------------
-- 21. ord_dispatch_plan 分仓方案（SRS-D03.06 §6.1；一轮一份不可变）
-- ---------------------------------------------------------------------
CREATE TABLE ord_dispatch_plan (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '归属订单（LFK→ord_order）',
  round_no            INT UNSIGNED NOT NULL COMMENT '分仓轮次',
  alloc               JSON         NOT NULL COMMENT '行级分配：{item_id→branch_id→分配量}',
  mode                VARCHAR(16)  NOT NULL COMMENT '分配模式：single整仓/multi多仓/lack缺货/appointed指定仓(平台store_code)',
  split_required      TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '需拆单标记：0否/1是（multi时1，D03.04 branch策略消费）',
  fulfill_snapshot    JSON         NULL COMMENT '满足度快照：各候选仓满足率/可用量明细（人工界面数据源）',
  lack_detail         JSON         NULL COMMENT '缺货明细：行/SKU/需求量/最佳可用/候选分布（D03.09消费）',
  rule_hit            JSON         NULL COMMENT '规则命中记录：规则ID/策略类型/仓序（可回放）',
  source              VARCHAR(16)  NOT NULL DEFAULT 'auto' COMMENT '来源：auto自动/retry换仓重试/manual改仓(含操作人)/platform平台指定仓',
  status              VARCHAR(16)  NOT NULL DEFAULT 'effective' COMMENT '状态：effective生效/superseded已被替代',
  lack_route          VARCHAR(16)  NULL COMMENT '缺货路径：retry_branch换仓重试中/lend_suggest借调建议/to_shortage转缺货',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间（快照时点）',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_dispatch_plan_order_round (order_id, round_no),
  KEY idx_ord_dispatch_plan_status (order_id, status)
) ENGINE=InnoDB COMMENT='分仓方案（行级仓分配+满足度+缺货明细快照，不可变，D03.06）';

-- ---------------------------------------------------------------------
-- 22. ord_branch_dispatch_rule 选仓分仓规则（SRS-D03.06 §6.2）
-- ---------------------------------------------------------------------
CREATE TABLE ord_branch_dispatch_rule (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NULL COMMENT '货主ID（配置表可空）',
  rule_name           VARCHAR(128) NOT NULL COMMENT '规则名（租户内唯一）',
  conditions          JSON         NOT NULL COMMENT '条件集：店铺/平台/区域(省市区)/订单类型/货主/物料分类/重量体积/标签',
  strategy_type       VARCHAR(32)  NOT NULL COMMENT '选仓策略：binding_priority店铺绑定优先/region_route区域路由/stock_depth库存深度/owner_assign货主指定/store_o2o门店分单/round_robin轮询',
  branch_seq          JSON         NULL COMMENT '输出仓序（绑定/区域策略显式仓序；region_route附区域→仓映射表引用）',
  weight              INT          NOT NULL DEFAULT 0 COMMENT '匹配权重（DESC首个命中）',
  effective_period    JSON         NULL COMMENT '生效时间段（大促临时切仓）',
  exclude_period      JSON         NULL COMMENT '排除时间段',
  default_flag        TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '缺省规则：0否/1是（兜底唯一）',
  status              VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '启停：enabled启用/disabled停用',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_branch_dispatch_rule_name (tenant_id, rule_name),
  KEY idx_ord_branch_dispatch_rule_weight (weight)
) ENGINE=InnoDB COMMENT='选仓分仓规则（条件集→选仓策略→输出仓序，D03.06）';

-- ---------------------------------------------------------------------
-- 23. ord_branch_change_log 手工改仓记录（SRS-D03.06 §6.4；只增，投递D10.06审计）
-- ---------------------------------------------------------------------
CREATE TABLE ord_branch_change_log (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '目标订单（LFK→ord_order）',
  plan_round          INT UNSIGNED NULL COMMENT '产生轮次（LFK→ord_dispatch_plan.round_no）',
  old_branch          BIGINT UNSIGNED NULL COMMENT '旧仓（LFK→ful_branch）',
  new_branch          BIGINT UNSIGNED NOT NULL COMMENT '新仓',
  old_fulfill         DECIMAL(9,4) NULL COMMENT '改前满足度',
  new_fulfill         DECIMAL(9,4) NULL COMMENT '改后满足度',
  reason              VARCHAR(256) NOT NULL COMMENT '原因（必填）',
  forced              TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '是否强制（低满足度）：0否/1是',
  approval_id         VARCHAR(64)  NULL COMMENT 'OA审批单号（强制时必填）',
  recall_ref          VARCHAR(64)  NULL COMMENT '叫回引用（已推仓场景）',
  operator            VARCHAR(64)  NOT NULL COMMENT '操作人（审计投递D10.06）',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  KEY idx_ord_branch_change_log_order (order_id),
  KEY idx_ord_branch_change_log_time (create_time)
) ENGINE=InnoDB COMMENT='手工改仓记录（改前后满足度对比/强制审批/叫回引用，只增，D03.06）';

-- ---------------------------------------------------------------------
-- 24. ord_delivery 发货单（SRS-D03.07 §6.1；指令状态机唯一载体）
--     溯源：商派 ome.delivery（92列）改造：混杂状态收敛为单一status指令状态机
-- ---------------------------------------------------------------------
CREATE TABLE ord_delivery (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键（delivery_id）',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID（按货主拆单传导：一单一货主，行不混货主落库强校验；D08分账单据粒度）',
  delivery_bn         VARCHAR(32)  NOT NULL COMMENT '发货单号（DLV+日期+序列），唯一',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '首关联订单（单订单场景=唯一订单，LFK→ord_order）',
  order_ids           JSON         NULL COMMENT '覆盖订单集（合单母单必填）',
  combine_group_id    BIGINT UNSIGNED NULL COMMENT '合单组引用（LFK→ord_combine_group）',
  status              VARCHAR(20)  NOT NULL DEFAULT 'draft' COMMENT '指令状态（SRS-D03.07 §4.1契约）：draft草稿/pushed已推送/push_failed推送失败/processing作业中/partial_outbound部分出库/outbound已出库/shipped已发货确认/finished已完结/recalling叫回中/recalled已叫回/rejected已打回/cancelled已取消',
  sync_status         VARCHAR(16)  NOT NULL DEFAULT 'init' COMMENT '推仓同步状态：init未推/success成功/fail失败/no_need无需推仓(虚拟/门店)',
  sync_msg            VARCHAR(512) NULL COMMENT '推仓失败原因',
  branch_id           BIGINT UNSIGNED NOT NULL COMMENT '发货仓（LFK→oms_fulfill.ful_branch；门店仓时=门店）',
  wms_channel_id      BIGINT UNSIGNED NULL COMMENT 'WMS通道（LFK→ful_wms_binding，D09.01路由依据）',
  wms_bill_no         VARCHAR(64)  NULL COMMENT 'WMS侧单号（回执落库，反查对账键）',
  logi_id             BIGINT UNSIGNED NULL COMMENT '物流公司（LFK→oms_fulfill物流档案D09.04）',
  logi_no             VARCHAR(64)  NULL COMMENT '运单号（多运单存包裹表）',
  is_bind             TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '母单标记：0否/1是（合单merge后=1，唯一推仓对象；子单指令级联）',
  parent_id           BIGINT UNSIGNED NULL COMMENT '子单→母单引用（LFK→ord_delivery）',
  is_virtual          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '虚拟发货单：0否/1是（免推仓直发，D03.10自动发货）',
  hold_flag           TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '暂缓推仓：0否/1是（预售到期放行指令触发推送）',
  hold_until          DATETIME(3)  NULL COMMENT '暂缓截止（预计发货日）',
  receiver_name_enc   VARBINARY(512) NULL COMMENT '收货人姓名密文快照（打单用，自ord_receiver复制）',
  receiver_mobile_enc VARBINARY(512) NULL COMMENT '手机密文快照',
  receiver_address_enc VARBINARY(1024) NULL COMMENT '详址密文快照（含省市区明文前缀）',
  receiver_cipher     JSON         NULL COMMENT '平台密文包快照（is_cipher单原样透传WMS/面单）',
  weight              DECIMAL(18,4) NULL COMMENT '预估重量kg（实际以回传称重为准，D08.04对账）',
  volume              DECIMAL(18,4) NULL COMMENT '预估体积m³',
  est_freight         DECIMAL(18,2) NULL COMMENT '预估运费',
  plan_id             BIGINT UNSIGNED NULL COMMENT '履约方案溯源（LFK→ord_fulfill_plan）',
  split_trace_id      BIGINT UNSIGNED NULL COMMENT '拆单轨迹溯源（LFK→ord_split_trace）',
  source              VARCHAR(16)  NOT NULL DEFAULT 'auto' COMMENT '来源：auto自动/manual人工/virtual虚拟/store门店',
  delivery_time       DATETIME(3)  NULL COMMENT '发货确认时间',
  finish_time         DATETIME(3)  NULL COMMENT '完结时间（收货确认/超时自动确认）',
  memo                VARCHAR(512) NULL COMMENT '发货备注',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID',
  brand_id            BIGINT UNSIGNED NULL COMMENT '品牌ID',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁（状态机并发防护）',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_delivery_bn (delivery_bn),
  KEY idx_ord_delivery_order (order_id, status),
  KEY idx_ord_delivery_status (status, sync_status),
  KEY idx_ord_delivery_parent (parent_id),
  KEY idx_ord_delivery_wms (wms_bill_no),
  KEY idx_ord_delivery_logi (logi_no),
  KEY idx_ord_delivery_branch (branch_id, status),
  KEY idx_ord_delivery_hold (hold_flag, hold_until)
) ENGINE=InnoDB COMMENT='发货单（指令状态机：推送/叫回/恢复/确认；母子单/虚拟/hold，D03.07）';

-- ---------------------------------------------------------------------
-- 25. ord_delivery_item 发货单行（SRS-D03.07 §6.2；行内货主唯一）
-- ---------------------------------------------------------------------
CREATE TABLE ord_delivery_item (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  delivery_id         BIGINT UNSIGNED NOT NULL COMMENT '归属发货单（LFK→ord_delivery）',
  bm_id               BIGINT UNSIGNED NOT NULL COMMENT '基础物料ID（快照自订单行）',
  bm_number           VARCHAR(64)  NULL COMMENT '物料编码快照',
  sm_id               BIGINT UNSIGNED NULL COMMENT '销售物料引用',
  num                 INT          NOT NULL COMMENT '指令数量',
  settled_num         INT          NOT NULL DEFAULT 0 COMMENT '已核销量（出库回传settle累加；≤num）',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID（行内唯一；D08分账与三元扣减依据）',
  lend_flag           TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '借调标记：0否/1是（记账货主=借出方不变）',
  lend_ledger_id      BIGINT UNSIGNED NULL COMMENT '借调台账引用（LFK→oms_stock D04.05，结算归属）',
  price               DECIMAL(18,4) NULL COMMENT '单价快照',
  memo                VARCHAR(256) NULL COMMENT '行备注',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  KEY idx_ord_delivery_item_delivery (delivery_id),
  KEY idx_ord_delivery_item_bm (bm_id, owner_id)
) ENGINE=InnoDB COMMENT='发货单行（物料×数量×货主，核销进度settled_num，D03.07）';

-- ---------------------------------------------------------------------
-- 26. ord_delivery_item_detail 发货单行明细溯源（SRS-D03.07 §6.2 detail）
-- ---------------------------------------------------------------------
CREATE TABLE ord_delivery_item_detail (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  delivery_id         BIGINT UNSIGNED NOT NULL COMMENT '归属发货单',
  delivery_item_id    BIGINT UNSIGNED NOT NULL COMMENT '归属发货单行（LFK→ord_delivery_item）',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '订单ID',
  order_item_id       BIGINT UNSIGNED NOT NULL COMMENT '订单行（LFK→ord_order_item；行内拆多对一溯源，Σsplit_qty=item.num守恒）',
  split_qty           INT          NOT NULL COMMENT '分摊数量',
  freeze_ref          VARCHAR(64)  NULL COMMENT '预占台账引用（LFK→oms_stock.inv_freeze_log；settle匹配依据，幂等键成分）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_dli_detail_freeze (freeze_ref, delivery_item_id),
  KEY idx_ord_dli_detail_item (delivery_item_id),
  KEY idx_ord_dli_detail_order_item (order_item_id)
) ENGINE=InnoDB COMMENT='发货单行明细溯源（发货单行↔订单行映射+预占引用，全链路库存足迹，D03.07）';

-- ---------------------------------------------------------------------
-- 27. ord_delivery_package 包裹（SRS-D03.07 §6.3；出库回传落库）
-- ---------------------------------------------------------------------
CREATE TABLE ord_delivery_package (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NULL COMMENT '货主ID',
  delivery_id         BIGINT UNSIGNED NOT NULL COMMENT '归属发货单（LFK→ord_delivery）',
  package_no          VARCHAR(64)  NULL COMMENT '包裹号',
  waybill_no          VARCHAR(64)  NULL COMMENT '运单号（D09.05面单关联）',
  logi_id             BIGINT UNSIGNED NULL COMMENT '物流公司',
  weight              DECIMAL(18,4) NULL COMMENT '实际称重kg（回传落库，D08.04运费对账）',
  volume              DECIMAL(18,4) NULL COMMENT '体积',
  pack_items          JSON         NULL COMMENT '装箱明细[{delivery_item_id,num}]',
  batch_no            VARCHAR(64)  NOT NULL COMMENT '回传批次号（幂等键成分）',
  callback_time       DATETIME(3)  NULL COMMENT '回传时间',
  sign_time           DATETIME(3)  NULL COMMENT '签收时间（物流轨迹回填）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_delivery_package_batch (delivery_id, batch_no, package_no),
  KEY idx_ord_delivery_package_waybill (waybill_no)
) ENGINE=InnoDB COMMENT='发货包裹（包裹/称重/面单号，回传批次幂等，D03.07）';

-- ---------------------------------------------------------------------
-- 28. ord_delivery_log 发货单状态机日志（SRS-D03.07 §6.4；只增，与状态落库同事务）
-- ---------------------------------------------------------------------
CREATE TABLE ord_delivery_log (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  delivery_id         BIGINT UNSIGNED NOT NULL COMMENT '归属发货单（LFK→ord_delivery）',
  command             VARCHAR(32)  NOT NULL COMMENT '指令：push推送/recall叫回/resume恢复/cancel取消/confirm发货确认/outbound_callback出库回传/reject打回/finish完结',
  from_status         VARCHAR(20)  NOT NULL COMMENT '旧态（枚举同ord_delivery.status）',
  to_status           VARCHAR(20)  NOT NULL COMMENT '新态',
  operator            VARCHAR(64)  NOT NULL COMMENT '操作者（system/账号）',
  reason              VARCHAR(512) NULL COMMENT '原因（叫回失败/打回原因结构化）',
  ref_id              VARCHAR(64)  NULL COMMENT '关联引用（改单单/异常单/WMS回执号）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  KEY idx_ord_delivery_log_delivery (delivery_id, create_time)
) ENGINE=InnoDB COMMENT='发货单状态机日志（transit全留痕，只增，D03.07）';

-- ---------------------------------------------------------------------
-- 29. ord_delivery_diff 发货差异登记（SRS-D03.07 §6.4 diff）
-- ---------------------------------------------------------------------
CREATE TABLE ord_delivery_diff (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  delivery_id         BIGINT UNSIGNED NOT NULL COMMENT '归属发货单',
  delivery_item_id    BIGINT UNSIGNED NULL COMMENT '发货单行',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '订单ID',
  diff_type           VARCHAR(16)  NOT NULL COMMENT '差异类型：lack少发/over多发/damage破损/mismatch行不匹配',
  diff_num            INT          NOT NULL COMMENT '差异数量（少发差额release/多发差额直扣store）',
  liability           VARCHAR(16)  NULL COMMENT '责任：wms/logistics物流/brand品牌方/unknown待判',
  handle_way          VARCHAR(16)  NULL COMMENT '处理：reship补发/refund退款/reconcile对账挂账/pending待定',
  handle_status       VARCHAR(16)  NOT NULL DEFAULT 'open' COMMENT '处理状态：open待处理/handled已处理/closed已闭环',
  rel_aftersale_id    BIGINT UNSIGNED NULL COMMENT '关联售后单（LFK→oms_aftersale）',
  memo                VARCHAR(512) NULL COMMENT '备注',
  operator            VARCHAR(64)  NULL COMMENT '登记/处理人',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  KEY idx_ord_delivery_diff_delivery (delivery_id),
  KEY idx_ord_delivery_diff_status (handle_status, diff_type)
) ENGINE=InnoDB COMMENT='发货差异登记（少发/多发/破损，责任与处置闭环，D03.07）';

-- ---------------------------------------------------------------------
-- 30. ord_order_modify 改单单据（SRS-D03.08 §6.1；改单状态机载体）
-- ---------------------------------------------------------------------
CREATE TABLE ord_order_modify (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  modify_bn           VARCHAR(32)  NOT NULL COMMENT '改单单号（MO+日期+序列），唯一',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '目标订单（LFK→ord_order）',
  order_bn            VARCHAR(32)  NOT NULL COMMENT '订单号冗余',
  modify_type         VARCHAR(16)  NOT NULL COMMENT '改单类型：address地址/item_add加商品/item_sub减商品/item_swap换商品/price价格/invoice发票/remark备注',
  source              VARCHAR(16)  NOT NULL COMMENT '发起来源：manual人工(客服/运营)/platform平台消息/system系统',
  snapshot_id         BIGINT UNSIGNED NOT NULL COMMENT '改单前快照（必填，LFK→ord_order_snapshot）',
  status              VARCHAR(16)  NOT NULL DEFAULT 'editing' COMMENT '改单状态（SRS-D03.08 §4.3状态机）：editing编辑中/freezing冻结中/recalling叫回中/wait_approval待审批/wait_confirm待确认/suspended挂起/effective已生效/rolled_back已回滚/closed已关闭',
  need_recall         TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '是否需叫回发货单：0否/1是',
  recall_status       VARCHAR(16)  NULL COMMENT '叫回结果：recalling叫回中/success成功/fail失败/timeout超时',
  recall_refs         JSON         NULL COMMENT '涉及发货单指令引用[{delivery_id,ref_id}]',
  approval_id         VARCHAR(64)  NULL COMMENT 'OA审批单号（改价必填-生效后，LFK→org_approval）',
  diff_summary        JSON         NULL COMMENT '差异摘要：字段路径/旧值引用/新值引用（敏感字段存密文引用）',
  saga_log            JSON         NULL COMMENT '冻结补偿日志（排障用）',
  operator            VARCHAR(64)  NOT NULL COMMENT '发起人',
  effective_time      DATETIME(3)  NULL COMMENT '生效时间',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID',
  brand_id            BIGINT UNSIGNED NULL COMMENT '品牌ID',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间（发起时间）',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁（回滚冲突检测）',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_order_modify_bn (modify_bn),
  KEY idx_ord_order_modify_order (order_id, status),
  KEY idx_ord_order_modify_status (status, create_time)
) ENGINE=InnoDB COMMENT='改单单据（冻结/叫回/审批/生效状态机编排载体，D03.08）';

-- ---------------------------------------------------------------------
-- 31. ord_order_snapshot 改单前订单快照（SRS-D03.08 §6.2；不可变）
-- ---------------------------------------------------------------------
CREATE TABLE ord_order_snapshot (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键（snapshot_id）',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  snapshot_bn         VARCHAR(32)  NOT NULL COMMENT '快照号，唯一（不可变）',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '归属订单',
  modify_bn           VARCHAR(32)  NULL COMMENT '关联改单单号',
  snap_order          JSON         NOT NULL COMMENT '订单头业务快照',
  snap_items          JSON         NOT NULL COMMENT '明细行快照',
  snap_receiver       JSON         NOT NULL COMMENT '收货人快照（字段值加密后存，PIPL D01.05）',
  snap_extend         JSON         NULL COMMENT '扩展快照',
  freeze_ids          JSON         NULL COMMENT '快照时点预占流水集合（回滚恢复依据）',
  status_snap         JSON         NOT NULL COMMENT '四态值快照{audit,fulfill,pay,ship,order}',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间（快照时间，毫秒级）',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_order_snapshot_bn (snapshot_bn),
  KEY idx_ord_order_snapshot_order (order_id)
) ENGINE=InnoDB COMMENT='改单前订单快照（四实体JSON+预占集合+四态值，复审对比与回滚依据，D03.08）';

-- ---------------------------------------------------------------------
-- 32. ord_modify_log 改单操作记录（SRS-D03.08；只增，投递D10.06字段级审计）
-- ---------------------------------------------------------------------
CREATE TABLE ord_modify_log (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '订单ID',
  modify_bn           VARCHAR(32)  NULL COMMENT '改单单号',
  action              VARCHAR(32)  NOT NULL COMMENT '动作：create发起/freeze冻结/recall叫回/approval_submit提审/approval_pass审批通过/approval_reject审批驳回/confirm确认/effect生效/rollback回滚/cancel撤销/suspend挂起',
  field_path          VARCHAR(128) NULL COMMENT '变更字段路径',
  old_value_ref       VARCHAR(512) NULL COMMENT '旧值引用（敏感字段存密文引用）',
  new_value_ref       VARCHAR(512) NULL COMMENT '新值引用',
  operator            VARCHAR(64)  NOT NULL COMMENT '操作人',
  source              VARCHAR(16)  NOT NULL DEFAULT 'manual' COMMENT '来源：manual人工/platform平台消息/system系统',
  memo                VARCHAR(256) NULL COMMENT '备注',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  KEY idx_ord_modify_log_order (order_id, create_time),
  KEY idx_ord_modify_log_modify (modify_bn)
) ENGINE=InnoDB COMMENT='改单操作记录（字段级流水，投递D10.06审计，只增，D03.08）';

-- ---------------------------------------------------------------------
-- 33. ord_retrial 复审单（SRS-D03.08 §6.3）
--     溯源：商派 ome.order_retrial 改造（+hit_detail结构化/+snapshot_id/+SLA/+四维）
-- ---------------------------------------------------------------------
CREATE TABLE ord_retrial (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  retrial_bn          VARCHAR(32)  NOT NULL COMMENT '复审单号（RT+日期+序列），唯一',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '关联订单（LFK→ord_order；触发时audit_status置retrial冻结fulfill推进）',
  modify_bn           VARCHAR(32)  NULL COMMENT '触发改单单（自动触发时为空）',
  retrial_type        VARCHAR(16)  NOT NULL COMMENT '复审类型：audit价格/amount大额/blacklist黑名单/normal人工发起',
  status              VARCHAR(20)  NOT NULL DEFAULT 'wait' COMMENT '复审状态（SRS-D03.08 §4.2状态机）：wait待复审/passed复审通过/rejected_rollback驳回-回滚/rejected_cancel驳回-取消/closed_by_cancel已取消收口',
  hit_detail          JSON         NULL COMMENT '命中明细结构化：价格类{rule,实付,基准价,倍数}/黑名单类{名单ID,维度,匹配值}（替代商派字符串拼接）',
  snapshot_id         BIGINT UNSIGNED NULL COMMENT '对比与回滚依据（价格复审触发时生成，LFK→ord_order_snapshot）',
  assign_group        BIGINT UNSIGNED NULL COMMENT '复审组（复用D03.03分派机制）',
  assign_op           BIGINT UNSIGNED NULL COMMENT '复审员',
  handle_opinion      VARCHAR(512) NULL COMMENT '处理意见（通过或驳回必填）',
  handle_time         DATETIME(3)  NULL COMMENT '处理时间',
  handle_op           BIGINT UNSIGNED NULL COMMENT '处理人',
  sla_deadline        DATETIME(3)  NULL COMMENT '复审时限（超时升级提醒）',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID',
  brand_id            BIGINT UNSIGNED NULL COMMENT '品牌ID',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_retrial_bn (retrial_bn),
  KEY idx_ord_retrial_order (order_id, status),
  KEY idx_ord_retrial_op (assign_op, status),
  KEY idx_ord_retrial_sla (status, sla_deadline)
) ENGINE=InnoDB COMMENT='复审单（价格/大额/黑名单/人工四类，快照对比与回滚，D03.08）';

-- ---------------------------------------------------------------------
-- 34. ord_abnormal 异常单（SRS-D03.09 §6.1）
--     溯源：商派 ome.order_abnormal（6列）改造：状态机/分派/SLA/处置/时间线
-- ---------------------------------------------------------------------
CREATE TABLE ord_abnormal (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  abnormal_bn         VARCHAR(32)  NOT NULL COMMENT '异常单号（EX+日期+序列），唯一',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '关联订单（LFK→ord_order）',
  order_bn            VARCHAR(32)  NOT NULL COMMENT '订单号冗余',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID',
  exc_type            VARCHAR(32)  NOT NULL COMMENT '异常类型编码（LFK→ord_abnormal_type_dict.type_code；初始16类见文末INSERT）',
  exc_category        VARCHAR(16)  NOT NULL COMMENT '分类冗余（便于统计）：data数据/risk风控/stock库存/fulfill履约/platform平台',
  source              VARCHAR(16)  NOT NULL COMMENT '识别来源：plugin审单插件/event事件/scan定时扫描/manual人工/linkage联动',
  source_ref          VARCHAR(128) NULL COMMENT '来源单据引用（reason_code/事件ID/任务ID/名单ID）',
  reason_detail       JSON         NULL COMMENT '结构化原因（对齐ord_audit_reason格式：原因码/字段/期望/实际）',
  status              VARCHAR(16)  NOT NULL DEFAULT 'wait_dispatch' COMMENT '状态（SRS-D03.09 §4.1状态机）：wait_dispatch待分派/dispatched已分派/processing处理中/suspended已挂起/resolved已解决/cancelled已取消（订单取消收口，收口失败不阻断取消）',
  group_id            BIGINT UNSIGNED NULL COMMENT '处理组（分派后必填，LFK→ord_audit_group）',
  op_id               BIGINT UNSIGNED NULL COMMENT '处理人',
  dispatch_time       DATETIME(3)  NULL COMMENT '分派时间',
  sla_deadline        DATETIME(3)  NULL COMMENT 'SLA截止（按类型字典SLA计算）',
  escalate_level      TINYINT      NOT NULL DEFAULT 0 COMMENT '升级级别：0正常/1组长(48h)/2运营负责人(72h)',
  resolve_action      VARCHAR(16)  NULL COMMENT '处置动作：reaudit重新审单/to_retrial转复审/cancel取消/suspend挂起/to_aftersale转售后/force_pass强制放行(OA)/refund退款',
  rel_retrial_id      BIGINT UNSIGNED NULL COMMENT '关联复审单（LFK→ord_retrial）',
  rel_refund_id       BIGINT UNSIGNED NULL COMMENT '关联售后/退款单（LFK→oms_aftersale）',
  rel_delivery_ids    JSON         NULL COMMENT '涉及发货单（叫回场景）',
  suspend_until       DATETIME(3)  NULL COMMENT '挂起预计恢复时间（挂起必填，到期提醒）',
  timeline            JSON         NULL COMMENT '时间线：[{time,status,operator,action,memo}]（状态变迁全留痕）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间（last_modified）',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_abnormal_bn (abnormal_bn),
  KEY idx_ord_abnormal_order (order_id, status),
  KEY idx_ord_abnormal_op (op_id, status),
  KEY idx_ord_abnormal_type (exc_type, status, create_time),
  KEY idx_ord_abnormal_sla (status, sla_deadline)
) ENGINE=InnoDB COMMENT='异常单（类型字典化/处理状态机/分派/SLA升级/处置动作，D03.09）';

-- ---------------------------------------------------------------------
-- 35. ord_abnormal_type_dict 异常类型字典（SRS-D03.09 §6.2；内置16类+租户扩展）
-- ---------------------------------------------------------------------
CREATE TABLE ord_abnormal_type_dict (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  type_code           VARCHAR(32)  NOT NULL COMMENT '类型编码（租户内唯一）',
  type_name           VARCHAR(64)  NOT NULL COMMENT '类型名称',
  category            VARCHAR(16)  NOT NULL COMMENT '分类：data数据/risk风控/stock库存/fulfill履约/platform平台',
  default_group_id    BIGINT UNSIGNED NULL COMMENT '默认处理组（LFK→ord_audit_group）',
  default_sla_hours   INT UNSIGNED NOT NULL DEFAULT 24 COMMENT '默认SLA小时',
  need_abnormal_bill  TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '审单原因是否自动落异常单：0否/1是',
  block_fulfill       TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '是否阻断履约：0否/1是（商派is_delivery=N语义）',
  action_set          JSON         NULL COMMENT '允许处置动作集（枚举同ord_abnormal.resolve_action）',
  reason_code_map     JSON         NULL COMMENT '映射的审单原因码清单（ord_audit_reason.reason_code）',
  is_system           TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '系统内置不可删：0否/1是',
  disabled            TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '启停：0启用/1停用',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_abnormal_type_dict_code (tenant_id, type_code)
) ENGINE=InnoDB COMMENT='异常类型字典（编码→分类/默认组/SLA/阻断/处置集/原因码映射，D03.09）';

-- ---------------------------------------------------------------------
-- 36. ord_stockout 缺货明细与策略记录（SRS-D03.09 §6.3）
-- ---------------------------------------------------------------------
CREATE TABLE ord_stockout (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID（缺货三元键之一）',
  abnormal_id         BIGINT UNSIGNED NOT NULL COMMENT '归属异常单（LFK→ord_abnormal）',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '归属订单',
  branch_id           BIGINT UNSIGNED NOT NULL COMMENT '缺货仓（三元键，预占失败现场）',
  bm_id               BIGINT UNSIGNED NOT NULL COMMENT '基础物料（三元键）',
  lack_num            INT          NOT NULL COMMENT '缺口量',
  stock_snapshot      JSON         NULL COMMENT '缺货时点五口径库存快照（D04.02口径）',
  strategy_status     VARCHAR(16)  NOT NULL DEFAULT 'wait_calc' COMMENT '策略链状态：wait_calc待测算/change_branch换仓中/lending借调中/purchase_urgent采购加急/negotiating协商中/refunding退款中/resolved已解除',
  strategy_result     JSON         NULL COMMENT '各步骤测算结果与建议：{可满足仓清单,借调额度,净缺口,协商记录引用}',
  promise_deadline    DATETIME(3)  NULL COMMENT '平台承诺发货时限（协商与加急测算依据）',
  oversold_flag       TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '超卖标记：0否/1是（平台已成交OMS无货）',
  batch_id            BIGINT UNSIGNED NULL COMMENT '应急批次引用（LFK→ord_oversold_batch）',
  negotiate_record    JSON         NULL COMMENT '买家协商记录（触达时间/买家选择/话术版本；24h触达SLA，48h无响应默认退款）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  KEY idx_ord_stockout_abnormal (abnormal_id),
  KEY idx_ord_stockout_order (order_id),
  KEY idx_ord_stockout_key (branch_id, bm_id, owner_id, strategy_status)
) ENGINE=InnoDB COMMENT='缺货明细与策略记录（三元键缺口现场+策略链：换仓/借调/加急/协商/退款，D03.09）';

-- ---------------------------------------------------------------------
-- 37. ord_oversold_batch 超卖应急批次（SRS-D03.09 §6.4；赔付JSON收敛）
-- ---------------------------------------------------------------------
CREATE TABLE ord_oversold_batch (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID（聚合键）',
  batch_bn            VARCHAR(32)  NOT NULL COMMENT '批次号（OS+日期+序列），唯一',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID（聚合键）',
  bm_id               BIGINT UNSIGNED NOT NULL COMMENT '基础物料（聚合键）',
  total_orders        INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '批次单量',
  resolved_orders     INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '已解决单量',
  refund_orders       INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '已退款单量',
  stage               VARCHAR(16)  NOT NULL DEFAULT 'alarm' COMMENT '批次阶段：alarm告警/alloc_calc调拨测算/negotiate协商/refund退款/compensate赔付/review复盘关闭',
  stage_timeline      JSON         NULL COMMENT '各阶段到达时间（SLA计时依据：T+0告警/T+4h调拨测算/T+24h协商/超时赔付）',
  promo_mode          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '大促模式标记：0否/1是（SLA收紧）',
  compensation        JSON         NULL COMMENT '赔付登记[{order_id,type(平台罚金/补偿券/运费),amount,liability,oa_approval_id}]',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_oversold_batch_bn (batch_bn),
  KEY idx_ord_oversold_batch_key (shop_id, bm_id, owner_id, stage)
) ENGINE=InnoDB COMMENT='超卖应急批次（店铺×SKU×货主聚合，分级SLA阶段推进+赔付登记，D03.09）';

-- ---------------------------------------------------------------------
-- 38. ord_pause_command_log 暂停/恢复指令记录（SRS-D03.09 §6.5；只增）
-- ---------------------------------------------------------------------
CREATE TABLE ord_pause_command_log (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '订单ID',
  delivery_id         BIGINT UNSIGNED NOT NULL COMMENT '发货单ID（LFK→ord_delivery）',
  command             VARCHAR(16)  NOT NULL COMMENT '指令：recall叫回/resume恢复重推',
  result              VARCHAR(16)  NOT NULL COMMENT '结果：success成功/fail失败/timeout超时',
  fail_code           VARCHAR(32)  NULL COMMENT '失败码（fail即cancel_fail登记）',
  fail_reason         VARCHAR(512) NULL COMMENT '失败原因（WMS返回）',
  abnormal_id         BIGINT UNSIGNED NULL COMMENT '关联跟进异常单（RECALL_FAILED，LFK→ord_abnormal）',
  operator            VARCHAR(64)  NOT NULL COMMENT '操作人（system/账号）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  KEY idx_ord_pause_command_log_order (order_id, create_time),
  KEY idx_ord_pause_command_log_delivery (delivery_id)
) ENGINE=InnoDB COMMENT='暂停/恢复指令记录（逐发货单叫回/重推结果留痕，只增，D03.09）';

-- ---------------------------------------------------------------------
-- 39. ord_risk_list 风控名单库（SRS-D03.09 §6.5；黑/灰/白×四维）
-- ---------------------------------------------------------------------
CREATE TABLE ord_risk_list (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NULL COMMENT '货主ID（scope=owner时必填）',
  list_type           VARCHAR(8)   NOT NULL COMMENT '名单类型：black黑名单/gray灰名单/white白名单',
  dimension           VARCHAR(16)  NOT NULL COMMENT '维度：mobile手机/address地址/account账号/name姓名',
  match_value         VARCHAR(256) NOT NULL COMMENT '匹配值（归一化；mobile/name/address存HMAC hash，account明文）',
  value_type          VARCHAR(8)   NOT NULL DEFAULT 'plain' COMMENT '值类型：plain明文/hash盲索引',
  scope               VARCHAR(16)  NOT NULL DEFAULT 'tenant' COMMENT '作用域：global全局/tenant租户/owner货主',
  effective_start     DATETIME(3)  NULL COMMENT '生效开始',
  effective_end       DATETIME(3)  NULL COMMENT '生效结束',
  reason              VARCHAR(256) NULL COMMENT '原因',
  source              VARCHAR(32)  NULL COMMENT '来源',
  oa_approval_id      VARCHAR(64)  NULL COMMENT 'OA授权单号（变更走OA留痕）',
  disabled            TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '启停：0启用/1停用',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  KEY idx_ord_risk_list_match (dimension, match_value, disabled),
  KEY idx_ord_risk_list_scope (scope, tenant_id)
) ENGINE=InnoDB COMMENT='风控名单库（黑/灰/白×手机/地址/账号/姓名，审单blacklist插件匹配源，D03.09）';

-- ---------------------------------------------------------------------
-- 40. ord_presale 预售单扩展（SRS-D03.10 §6.1预售+FR-02；两阶段状态机）
-- ---------------------------------------------------------------------
CREATE TABLE ord_presale (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '关联订单（1:1，LFK→ord_order）',
  presale_status      VARCHAR(16)  NOT NULL DEFAULT 'deposit_paid' COMMENT '预售状态（SRS-D03.10 §4.2状态机）：deposit_paid定金已付(hold)/balance_paid尾款已付/wait_audit待审单(放行)/fulfilling履约中/finished已完成/closed已关闭(定金退款或超时未付尾款)',
  deposit_amount      DECIMAL(18,2) NULL COMMENT '定金金额（双口径入ord_order金额组）',
  deposit_pay_time    DATETIME(3)  NULL COMMENT '定金支付时间',
  balance_amount      DECIMAL(18,2) NULL COMMENT '尾款金额',
  balance_pay_time    DATETIME(3)  NULL COMMENT '尾款支付时间',
  balance_deadline    DATETIME(3)  NULL COMMENT '尾款支付截止（超时关闭+定金退款）',
  estimate_con_time   DATETIME(3)  NULL COMMENT '预计发货日（平台报文同步可改期；发货日看板聚合键）',
  reserve_mode        VARCHAR(16)  NOT NULL DEFAULT 'none' COMMENT '预售预占模式快照（落店铺配置）：none不预占/immediate定金后立即预占',
  release_advance_days INT         NOT NULL DEFAULT 0 COMMENT '放行提前量快照（店铺级配置，天）',
  release_time        DATETIME(3)  NULL COMMENT 'hold解除放行时间',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_presale_order (order_id),
  KEY idx_ord_presale_release (presale_status, estimate_con_time)
) ENGINE=InnoDB COMMENT='预售单扩展（定金/尾款/预计发货日，两阶段状态机+到期批量放行，D03.10）';

-- ---------------------------------------------------------------------
-- 41. ord_groupon 团购单扩展（SRS-D03.10 §6.1团购+FR-03；成团状态机）
-- ---------------------------------------------------------------------
CREATE TABLE ord_groupon (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '关联订单（1:1，LFK→ord_order）',
  groupon_id          VARCHAR(64)  NULL COMMENT '团购活动号（平台侧）',
  groupon_status      VARCHAR(16)  NOT NULL DEFAULT 'wait_group' COMMENT '成团状态：wait_group待成团(hold)/succeed已成团/fulfilling履约中/finished完成/failed_cancel未成团取消/refunding退款中/closed关闭',
  groupon_deadline    DATETIME(3)  NULL COMMENT '成团截止（超时未成团自动取消+仅退款；消息丢失定时反查兜底D02.05）',
  succeed_time        DATETIME(3)  NULL COMMENT '成团时间',
  dispatch_deadline   DATETIME(3)  NULL COMMENT '活动发货承诺期（成团距承诺期不足阈值打时效紧张标签）',
  refund_id           BIGINT UNSIGNED NULL COMMENT '未成团自动仅退款单引用（LFK→oms_aftersale D05.03）',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_groupon_order (order_id),
  KEY idx_ord_groupon_status (groupon_status, groupon_deadline)
) ENGINE=InnoDB COMMENT='团购单扩展（成团状态机，未成团自动取消退款，D03.10）';

-- ---------------------------------------------------------------------
-- 42. ord_luckybag_alloc 福袋分配日志（SRS-D03.10 §6.2；追加不可改无update通道）
-- ---------------------------------------------------------------------
CREATE TABLE ord_luckybag_alloc (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID（品牌方门户可见本货主日志）',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '订单ID',
  order_item_id       BIGINT UNSIGNED NOT NULL COMMENT '福袋行（LFK→ord_order_item）',
  piece_no            INT UNSIGNED NOT NULL COMMENT '件序号（一件一行）',
  scheme_id           BIGINT UNSIGNED NOT NULL COMMENT '派发方案（LFK→oms_stock福袋方案档案D04.01）',
  dispatch_mode       VARCHAR(16)  NOT NULL COMMENT '派发模式：random随机(按权重抽签)/rule规则(会员等级/店铺/时段)/manual人工指定',
  dispatch_result     VARCHAR(16)  NOT NULL DEFAULT 'success' COMMENT '派发结果：success成功/fail_preempt预占失败改派/fail_final全部失败转人工',
  operator            VARCHAR(64)  NOT NULL COMMENT '操作者（system或账户ID）',
  dispatch_time       DATETIME(3)  NOT NULL COMMENT '派发时间（追加不可改）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_luckybag_alloc_piece (order_item_id, piece_no, dispatch_time),
  KEY idx_ord_luckybag_alloc_order (order_id)
) ENGINE=InnoDB COMMENT='福袋分配日志（一件一行派发记录，只增不可改，D03.10）';

-- ---------------------------------------------------------------------
-- 43. ord_card_secret 卡密库（SRS-D03.10 §6.3；加密存储，一卡一密原子领取）
-- ---------------------------------------------------------------------
CREATE TABLE ord_card_secret (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键（card_id）',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID（三元键）',
  card_no             VARCHAR(128) NOT NULL COMMENT '卡号（卡号+SKU+货主唯一=导入去重键）',
  card_secret_enc     VARBINARY(2048) NOT NULL COMMENT '卡密内容密文（D01.05信封加密；展示脱敏；解密仅内存）',
  key_version         VARCHAR(32)  NOT NULL DEFAULT 'v1' COMMENT '加密密钥版本',
  bm_id               BIGINT UNSIGNED NOT NULL COMMENT '基础物料ID（三元键）',
  branch_id           BIGINT UNSIGNED NOT NULL COMMENT '卡密虚拟仓（专用branch类型，三元键）',
  batch_no            VARCHAR(64)  NOT NULL COMMENT '导入批次（必填）',
  expire_date         DATE         NULL COMMENT '卡密有效期',
  status              VARCHAR(16)  NOT NULL DEFAULT 'unused' COMMENT '状态：unused未核销/bound已绑定(原子领取)/settled已核销(发货确认)/voided已作废（已回传平台的卡密作废不回滚，走补发/退款）',
  order_id            BIGINT UNSIGNED NULL COMMENT '绑定订单（已绑定起必填）',
  order_item_id       BIGINT UNSIGNED NULL COMMENT '绑定订单行',
  bind_time           DATETIME(3)  NULL COMMENT '绑定（原子领取）时间',
  settle_time         DATETIME(3)  NULL COMMENT '核销时间（发货确认联动）',
  shop_id             BIGINT UNSIGNED NULL COMMENT '店铺ID（回传用）',
  void_approval_id    VARCHAR(64)  NULL COMMENT '批量作废OA审批单号',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁（原子领取并发防护）',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_card_secret_no (card_no, bm_id, owner_id),
  KEY idx_ord_card_secret_pick (bm_id, owner_id, branch_id, status),
  KEY idx_ord_card_secret_order (order_id),
  KEY idx_ord_card_secret_batch (batch_no)
) ENGINE=InnoDB COMMENT='卡密库（加密存储，一卡一密：领取置bound/确认置settled/发货前取消回滚unused，D03.10）';

-- ---------------------------------------------------------------------
-- 44. ord_virtual_delivery 虚拟发货核销记录（SRS-D03.10 FR-05）
-- ---------------------------------------------------------------------
CREATE TABLE ord_virtual_delivery (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '订单ID',
  order_item_id       BIGINT UNSIGNED NOT NULL COMMENT '订单行（虚拟行）',
  delivery_id         BIGINT UNSIGNED NULL COMMENT '虚拟发货单引用（LFK→ord_delivery）',
  card_id             BIGINT UNSIGNED NULL COMMENT '卡密引用（LFK→ord_card_secret；无卡密型P1为NULL）',
  sync_channel        VARCHAR(16)  NOT NULL COMMENT '回传方式：card_api接口带卡密/virtual_waybill虚拟运单号/status_only仅记状态(人工补发)',
  waybill_no          VARCHAR(64)  NULL COMMENT '虚拟运单号',
  sync_status         VARCHAR(16)  NOT NULL DEFAULT 'wait' COMMENT '回传状态：wait待发/syncing发送中/success成功/fail失败(D02.05分级重试卡密保持绑定)/manual人工补发',
  sync_msg            VARCHAR(512) NULL COMMENT '失败码与消息',
  retry_count         INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '重试次数（超上限转人工异常单+企微告警）',
  sync_time           DATETIME(3)  NULL COMMENT '最近回传时间',
  verify_time         DATETIME(3)  NULL COMMENT '核销确认时间',
  operator            VARCHAR(64)  NOT NULL DEFAULT 'system' COMMENT '操作者（system/账户）',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  KEY idx_ord_virtual_delivery_order (order_id),
  KEY idx_ord_virtual_delivery_status (sync_status, create_time),
  KEY idx_ord_virtual_delivery_card (card_id)
) ENGINE=InnoDB COMMENT='虚拟发货核销记录（领卡密→平台回传→发货确认自动通道，D03.10）';

-- ---------------------------------------------------------------------
-- 45. ord_store_profile 门店履约属性（SRS-D03.11 §6.1；P1）
-- ---------------------------------------------------------------------
CREATE TABLE ord_store_profile (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '归属货主ID',
  branch_id           BIGINT UNSIGNED NOT NULL COMMENT '门店仓ID（1:1，branch类型=门店仓，LFK→oms_fulfill.ful_branch）',
  store_name          VARCHAR(128) NOT NULL COMMENT '门店名',
  contact             VARCHAR(64)  NULL COMMENT '联系人',
  phone_enc           VARBINARY(512) NULL COMMENT '门店电话密文（脱敏展示）',
  biz_status          VARCHAR(16)  NOT NULL DEFAULT 'open' COMMENT '营业状态：open营业中/closed停业/pause_accept暂停接单（停业即时剔除分单候选；达日接单上限自动pause_accept）',
  daily_order_limit   INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '日接单上限（>0）',
  today_dispatch_count INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '当日派单量（调度回写，每日清零）',
  cover_area_codes    JSON         NULL COMMENT '覆盖行政区编码集（P1行政区，与围栏二选一）',
  geo_fence           JSON         NULL COMMENT '电子围栏GeoJSON（P2预留）',
  lng                 DECIMAL(10,6) NULL COMMENT '经度（评分用，必填）',
  lat                 DECIMAL(10,6) NULL COMMENT '纬度',
  pickup_enabled      TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '自提能力开关：0关/1开（关闭不参与自提分单）',
  biz_hours           VARCHAR(128) NULL COMMENT '营业时间（通知文案与超期提醒时段判断）',
  priority            INT          NOT NULL DEFAULT 50 COMMENT '门店优先级0-100（评分输入）',
  accept_timeout      INT UNSIGNED NULL COMMENT '接单超时分钟（空取店铺默认30）',
  shop_scope          JSON         NULL COMMENT '服务店铺集',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_store_profile_branch (branch_id),
  KEY idx_ord_store_profile_status (biz_status)
) ENGINE=InnoDB COMMENT='门店履约属性（1:1挂门店仓：营业状态/接单上限/覆盖区域/自提能力，P1，D03.11）';

-- ---------------------------------------------------------------------
-- 46. ord_store_order 门店履约路由扩展（SRS-D03.11 §6.2；1:1挂发货单；P1）
-- ---------------------------------------------------------------------
CREATE TABLE ord_store_order (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  delivery_id         BIGINT UNSIGNED NOT NULL COMMENT '发货单（1:1，LFK→ord_delivery；门店单sync_status=no_need）',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '订单ID',
  fulfill_mode        VARCHAR(16)  NOT NULL DEFAULT 'store_ship' COMMENT '履约方式：store_ship门店发货/store_pickup门店自提/city_delivery同城配送(P2预留)',
  store_branch_id     BIGINT UNSIGNED NOT NULL COMMENT '履约门店仓（LFK→ord_store_profile）',
  accept_status       VARCHAR(16)  NOT NULL DEFAULT 'wait' COMMENT '接单状态：wait待接单/accepted已接单/refused已拒单/timeout_redispatch超时转派',
  accept_operator     VARCHAR(64)  NULL COMMENT '接单人',
  accept_time         DATETIME(3)  NULL COMMENT '接单时间',
  refuse_reason       VARCHAR(256) NULL COMMENT '拒单原因（拒单必填）',
  rejected_store_ids  JSON         NULL COMMENT '本单已拒门店集（重分剔除输入）',
  dispatch_round      INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '分单轮次（≥1；>3告警监控重分次数）',
  waybill_no          VARCHAR(64)  NULL COMMENT '运单号（发货确认前必填）',
  print_time          DATETIME(3)  NULL COMMENT '面单打印时间（D09.05回写）',
  notify_time         DATETIME(3)  NULL COMMENT '作业台推送/企微通知时间',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_store_order_delivery (delivery_id),
  KEY idx_ord_store_order_store (store_branch_id, accept_status),
  KEY idx_ord_store_order_order (order_id)
) ENGINE=InnoDB COMMENT='门店履约路由扩展（履约方式/接单状态机/分单轮次/已拒门店集，P1，D03.11）';

-- ---------------------------------------------------------------------
-- 47. ord_pickup 自提单（SRS-D03.11 §6.3；自提码/核销即发货；P1）
-- ---------------------------------------------------------------------
CREATE TABLE ord_pickup (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  pickup_bn           VARCHAR(32)  NOT NULL COMMENT '自提单号（PK+日期+序列），唯一',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '关联订单',
  delivery_id         BIGINT UNSIGNED NULL COMMENT '关联发货单',
  store_branch_id     BIGINT UNSIGNED NOT NULL COMMENT '自提门店（LFK→ord_store_profile）',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID（码唯一性维度）',
  pickup_code         CHAR(6)      NOT NULL COMMENT '自提码（6位数字随机防猜测；错误码连续5次锁定10分钟防暴破）',
  code_date           DATE         NOT NULL COMMENT '码生效日期（(shop_id,code_date,pickup_code)唯一）',
  status              VARCHAR(16)  NOT NULL DEFAULT 'wait_verify' COMMENT '状态（SRS-D03.11 §4.3）：wait_verify待核销/verified已核销(完成)/cancelled已取消/overdue_handling超期处理中',
  expire_time         DATETIME(3)  NOT NULL COMMENT '自提期限（生成时间+期限，店铺级默认7天；到期前1天提醒）',
  verify_operator     VARCHAR(64)  NULL COMMENT '核销店员（核销必填，绑定作业台登录态）',
  verify_time         DATETIME(3)  NULL COMMENT '核销时间（核销=发货确认：settle+平台回传+订单完成事件）',
  verify_device       VARCHAR(64)  NULL COMMENT '核销设备留痕',
  overdue_action      VARCHAR(16)  NULL COMMENT '超期处理方式快照：return_stock退回库存/to_delivery转配送',
  remind_sent         TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '到期提醒已发标记：0否/1是（防重发）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁（核销与超期处理互斥）',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_pickup_bn (pickup_bn),
  UNIQUE KEY uk_ord_pickup_code (shop_id, code_date, pickup_code),
  KEY idx_ord_pickup_order (order_id),
  KEY idx_ord_pickup_expire (status, expire_time)
) ENGINE=InnoDB COMMENT='自提单（6位自提码/核销即发货/超期退回或转配送，P1，D03.11）';

-- ---------------------------------------------------------------------
-- 48. ord_declare 跨境申报单（SRS-D03.12 §6.1；P2建表预留，P0期ord_order已留字段位）
-- ---------------------------------------------------------------------
CREATE TABLE ord_declare (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  declare_bn          VARCHAR(32)  NOT NULL COMMENT '申报流水号，唯一（关联海关回执号）',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '归属订单（LFK→ord_order）',
  declare_mode        VARCHAR(16)  NOT NULL COMMENT '申报模式：bonded保税/direct直邮',
  channel_code        VARCHAR(64)  NULL COMMENT '报关通道（服务商×口岸，按保税仓路由）',
  order_bill          JSON         NULL COMMENT '订单单快照（密文；申报金额=Σ行海关口径+运费+保费，SRS-D03.12 §5.1）',
  pay_bill            JSON         NULL COMMENT '支付单快照（密文；须=订单单金额容差0）',
  logistics_bill      JSON         NULL COMMENT '物流单快照（密文，预取号）',
  id_card_enc         VARBINARY(512) NULL COMMENT '收件人身份证密文（PIPL单独授权后采集）',
  id_card_hash        CHAR(64)     NULL COMMENT '身份证盲索引（脱敏检索）',
  total_amount        DECIMAL(18,2) NULL COMMENT '申报金额（海关口径）',
  tax_amount          DECIMAL(18,2) NULL COMMENT '试算税费（供D08财务）',
  declare_status      VARCHAR(16)  NOT NULL DEFAULT 'wait' COMMENT '申报状态（SRS-D03.12 §4.2状态机，与ord_order.declare_status同步）：wait待申报/declaring申报中/released放行/failed申报失败/returned已退单/exported已出区/refund_declare退单申报',
  retry_count         INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '重报次数（≤3，超限人工退单/取消）',
  fail_reason_code    VARCHAR(32)  NULL COMMENT '失败原因码：AMOUNT_MISMATCH对碰不一致/ID_INVALID身份证/QUOTA_OVER额度/RECORD备案问题/OTHER',
  fail_reason         VARCHAR(512) NULL COMMENT '失败原因原文',
  receipt_raw_enc     VARBINARY(4096) NULL COMMENT '海关回执原文密文（稽查要求保存≥3年）',
  declare_raw_enc     VARBINARY(4096) NULL COMMENT '申报报文原文密文',
  release_time        DATETIME(3)  NULL COMMENT '放行时间（时效监控依据）',
  export_time         DATETIME(3)  NULL COMMENT '出区时间（账册核减联动）',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_declare_bn (declare_bn),
  KEY idx_ord_declare_order (order_id),
  KEY idx_ord_declare_status (declare_status, create_time)
) ENGINE=InnoDB COMMENT='跨境申报单（三单对碰/申报状态机/重报与失败原因，P2建表预留，D03.12）';

-- ---------------------------------------------------------------------
-- 49. ord_order_archive 归档单元台账（SRS-D03.13 §6.2；在线摘要行复用ord_order）
-- ---------------------------------------------------------------------
CREATE TABLE ord_order_archive (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  unit_bn             VARCHAR(32)  NOT NULL COMMENT '归档单元号（AU+日期+序列），唯一',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '订单ID（LFK→ord_order摘要行）',
  order_bn            VARCHAR(32)  NOT NULL COMMENT '订单号',
  shard_key           CHAR(6)      NOT NULL COMMENT '分片键（完结年月YYYYMM）',
  schema_version      VARCHAR(16)  NOT NULL COMMENT '归档时点结构版本（结构快照冻结依据）',
  item_counts         JSON         NOT NULL COMMENT '子单据计数清单{明细行数/发货单数/包裹数/售后单数/改单数}（完整性校验与对账依据）',
  amount_check        TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '金额勾稽结果：0未通过/1双口径平衡校验通过',
  archive_status      VARCHAR(16)  NOT NULL DEFAULT 'done' COMMENT '单元状态：done完成/recalled已回捞待清理（冷却期后归档任务重新判定清理）',
  migrate_batch       VARCHAR(64)  NULL COMMENT '迁移批次号（仅M4导入单必填；批次对账与回滚依据）',
  source_ref          VARCHAR(128) NULL COMMENT '源系统引用（迁移单：源系统+源单号=幂等键）',
  archive_source      VARCHAR(16)  NOT NULL DEFAULT 'task' COMMENT '归档来源：task归档任务/migration迁移导入(M4)',
  archive_locator     JSON         NOT NULL COMMENT '归档库定位{shard_table,unit_id}（与ord_order.archive_locator同源冗余）',
  recall_flag         TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '回捞标记：0否/1是',
  recall_time         DATETIME(3)  NULL COMMENT '回捞时间',
  archive_time        DATETIME(3)  NOT NULL COMMENT '归档时间',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID（冗余）',
  brand_id            BIGINT UNSIGNED NULL COMMENT '品牌ID（冗余，分片扫描维度）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_order_archive_unit (unit_bn),
  UNIQUE KEY uk_ord_order_archive_order (order_id),
  KEY idx_ord_order_archive_shard (shard_key, archive_status),
  KEY idx_ord_order_archive_migrate (migrate_batch)
) ENGINE=InnoDB COMMENT='归档单元台账（分片/结构版本/计数勾稽/迁移批次/回捞标记；历史全量在oms_archive归档库，D03.13）';

-- ---------------------------------------------------------------------
-- 50. ord_archive_log 归档/回捞流水（SRS-D03.13 §6.3；只增）
-- ---------------------------------------------------------------------
CREATE TABLE ord_archive_log (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  log_type            VARCHAR(16)  NOT NULL COMMENT '动作类型：archive归档/recall回捞/import迁移导入/cold_offload冷备卸载/batch_rollback批次回滚',
  unit_id             BIGINT UNSIGNED NULL COMMENT '归档单元（LFK→ord_order_archive）',
  order_bn            VARCHAR(32)  NULL COMMENT '订单号',
  trigger_source      VARCHAR(32)  NOT NULL COMMENT '触发方：schedule调度任务/aftersale售后建单/manual客服人工/finance财务/migration迁移工具',
  rows_moved          INT UNSIGNED NULL COMMENT '搬迁行数（监控依据）',
  duration_ms         INT UNSIGNED NULL COMMENT '耗时ms',
  operator            VARCHAR(64)  NULL COMMENT '操作人/系统（人工动作必填账号）',
  result              VARCHAR(16)  NOT NULL COMMENT '结果：success成功/fail失败',
  error_msg           VARCHAR(1024) NULL COMMENT '失败原因（失败必附）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  KEY idx_ord_archive_log_unit (unit_id),
  KEY idx_ord_archive_log_type (log_type, create_time)
) ENGINE=InnoDB COMMENT='归档/回捞流水（搬迁行数/耗时/结果，监控与对账依据，只增，D03.13）';

-- ---------------------------------------------------------------------
-- 51. ord_archive_config 归档策略配置（SRS-D03.13 §6.4）
-- ---------------------------------------------------------------------
CREATE TABLE ord_archive_config (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  scope_level         VARCHAR(16)  NOT NULL DEFAULT 'global' COMMENT '配置粒度：global全局/owner货主/brand品牌',
  scope_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '范围ID（global时0）',
  archive_months      INT UNSIGNED NOT NULL DEFAULT 6 COMMENT '完结后归档时滞N（月，正整数默认6）',
  aftersale_protect_days INT UNSIGNED NOT NULL DEFAULT 90 COMMENT '售后保护期（天，默认90；实际生效max(N,保护期)）',
  recall_cooldown_months INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '回捞冷却期（月，默认1；冷却期内不再归档）',
  batch_size          INT UNSIGNED NOT NULL DEFAULT 500 COMMENT '单元批大小（默认500）',
  qps_limit           INT UNSIGNED NULL COMMENT '限速（在线库删除压力可控，可配）',
  brand_switch        TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '品牌灰度开关：0停/1启（迁移双跑期老品牌不归档）',
  cold_offload_years  INT UNSIGNED NOT NULL DEFAULT 5 COMMENT '冷备卸载年限（默认5；摘要行不受影响永久保留）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_archive_config_scope (tenant_id, scope_level, scope_id)
) ENGINE=InnoDB COMMENT='归档策略配置（全局/货主/品牌三级：时滞/保护期/冷却期/限速/灰度，D03.13）';

-- ---------------------------------------------------------------------
-- 52. ord_shop_fulfill_config 店铺履约参数配置（D03.05/06/08/10/11店铺级参数收敛）
-- ---------------------------------------------------------------------
CREATE TABLE ord_shop_fulfill_config (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NULL COMMENT '货主ID（货主级价格监控行shop_id=0时填）',
  shop_id             BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺ID（0=货主级价格监控配置行）',
  combine_enabled     TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '合单开关：0关(默认,Q17)/1开（继承全局）',
  buffer_minutes      INT UNSIGNED NOT NULL DEFAULT 15 COMMENT '缓冲窗大小0-1440分钟（0=即投；开启合单建议10-30）',
  merge_limit         INT UNSIGNED NOT NULL DEFAULT 10 COMMENT '合单组内订单数上限（超上限按paytime切分多组）',
  max_wait_rounds     INT UNSIGNED NOT NULL DEFAULT 2 COMMENT '疑可合并最大等待轮次（router_num防死循环）',
  hash_dims           JSON         NULL COMMENT '合单指纹维度集合（默认全集）',
  weight_limit        DECIMAL(18,4) NULL COMMENT '包裹重量上限kg（装箱用）',
  volume_limit        DECIMAL(18,4) NULL COMMENT '包裹体积上限m³',
  sku_kind_limit      INT UNSIGNED NULL COMMENT '包裹SKU种类上限',
  manual_merge_enabled TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '手工合单开关：0关/1开（独立配置）',
  cross_shop_enabled  TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '跨店合单：0禁(默认)/1允许（P2预留）',
  lack_fulfill_mode   VARCHAR(16)  NOT NULL DEFAULT 'manual' COMMENT '部分缺货履约策略：ship_first先发后缺/wait_all整单等货/manual人工',
  branch_retry_limit  INT UNSIGNED NOT NULL DEFAULT 2 COMMENT '换仓重试上限（默认2）',
  lend_auto_mode      VARCHAR(16)  NOT NULL DEFAULT 'manual' COMMENT '借调建议处置：auto自动借调/manual人工确认（P1）',
  include_lend_in_view TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '借调可用量纳入满足度：0否(默认)/1是（P1）',
  force_change_approval DECIMAL(9,4) NULL COMMENT '强制低满足度改仓审批阈值（满足率低于此值改仓需OA）',
  is_monitor          TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '价格监控开关：0关/1开(默认；货主级优先店铺级覆盖细化)',
  monitor_mode        VARCHAR(8)   NOT NULL DEFAULT 'item' COMMENT '监控模式：item行级/order整单',
  cost_multiple       DECIMAL(9,4) NULL COMMENT '成本倍数阈值（正数支持小数如0.8）',
  limit_multiple      DECIMAL(9,4) NULL COMMENT '限价倍数阈值',
  discount_ceiling    DECIMAL(9,4) NULL COMMENT '折扣率上限0-1',
  big_amount_threshold DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '大额复审阈值（0=关闭）',
  blacklist_switch    TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '黑名单复审开关：0关/1开',
  presale_release_ahead INT        NOT NULL DEFAULT 0 COMMENT '预售放行提前量（天，0=到期日当天放行）',
  presale_reserve_mode VARCHAR(16) NOT NULL DEFAULT 'none' COMMENT '预售预占模式：none不预占(默认)/immediate定金后立即预占',
  groupon_urgent_hours INT UNSIGNED NOT NULL DEFAULT 24 COMMENT '团购时效紧张阈值（成团距承诺期不足小时数打急标）',
  luckybag_no_repeat  TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '福袋不重样约束开关：0关/1开(默认)',
  luckybag_aftersale_mode VARCHAR(16) NOT NULL DEFAULT 'whole' COMMENT '福袋售后：whole整套退(默认)/part部分退(退款额=方案分摊价；注入D05校验)',
  pickup_expire_days  INT UNSIGNED NOT NULL DEFAULT 7 COMMENT '自提期限（天，默认7）',
  pickup_overdue_action VARCHAR(16) NOT NULL DEFAULT 'return_stock' COMMENT '自提超期处理：return_stock退回库存/to_delivery转配送',
  store_accept_timeout INT UNSIGNED NOT NULL DEFAULT 30 COMMENT '门店接单超时分钟（店铺默认30）',
  o2o_fallback        VARCHAR(16)  NOT NULL DEFAULT 'manual' COMMENT '无可用门店fallback：to_warehouse转电商仓/manual挂起人工',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_shop_fulfill_config_shop (tenant_id, shop_id, owner_id)
) ENGINE=InnoDB COMMENT='店铺履约参数配置（合单/分仓缺货/价格监控/特殊单型/O2O店铺级参数收敛，D03.05/06/08/10/11）';

-- =====================================================================
-- 初始字典数据 INSERT
-- =====================================================================

-- 1) 异常类型字典（SRS-D03.09 §5.1 内置全集 16 类，is_system=1 不可删）
INSERT INTO ord_abnormal_type_dict
  (tenant_id, type_code, type_name, category, default_sla_hours, need_abnormal_bill, block_fulfill, action_set, reason_code_map, is_system)
VALUES
  (1, 'PRODUCT_UNBOUND',   '商品未绑定',     'data',     24, 1, 1, '["reaudit"]',                                   '["GOODS_UNBOUND"]',                          1),
  (1, 'ADDR_REMOTE',       '收货地址偏远',   'data',     24, 1, 0, '["reaudit","to_aftersale"]',                    '["LOGI_UNREACHED"]',                         1),
  (1, 'ADDR_INCOMPLETE',   '地址不全/双地址','data',     24, 1, 0, '["reaudit","to_aftersale"]',                    '["ADDRESS_INVALID"]',                        1),
  (1, 'ADDR_POBOX',        'PO Box地址',     'data',     24, 1, 0, '["reaudit","to_aftersale"]',                    '["ADDRESS_INVALID"]',                        1),
  (1, 'PRICE_ABNORMAL',    '价格异常',       'data',      8, 1, 1, '["to_retrial","cancel"]',                       '["PRICE_ABNORMAL"]',                         1),
  (1, 'BLACKLIST',         '黑名单客户',     'risk',      8, 1, 1, '["to_retrial","cancel"]',                       '["BLACKLIST"]',                              1),
  (1, 'RISK_HIT',          '风控命中',       'risk',     24, 1, 1, '["suspend","cancel","force_pass"]',             '["ABNORMAL_RISK"]',                          1),
  (1, 'STOCK_SHORT',       '缺货',           'stock',    24, 1, 1, '["reaudit","suspend","to_aftersale","refund"]', '["STOCK_SHORTAGE","NO_STOCK"]',              1),
  (1, 'OVERSOLD',          '超卖',           'stock',     4, 1, 1, '["reaudit","refund","suspend"]',                '["STOCK_SHORTAGE"]',                         1),
  (1, 'PAY_ABNORMAL',      '支付异常',       'platform', 24, 1, 1, '["suspend","cancel","reaudit"]',                '["PAY_UNPAID","REFUND_PENDING"]',            1),
  (1, 'SPLIT_FAILED',      '拆合单失败',     'fulfill',  24, 1, 1, '["reaudit"]',                                   '["SPLIT_FAIL","COMBINE_CONFLICT"]',          1),
  (1, 'WMS_PUSH_FAILED',   '推仓失败',       'fulfill',  12, 1, 1, '["reaudit","suspend"]',                         '[]',                                         1),
  (1, 'SYNC_BACK_FAILED',  '回传失败',       'platform', 24, 1, 0, '["reaudit"]',                                   '[]',                                         1),
  (1, 'FULFILL_STAGNANT',  '履约停滞',       'fulfill',  24, 1, 0, '["reaudit","suspend"]',                         '[]',                                         1),
  (1, 'RECALL_FAILED',     '叫回失败跟进',   'fulfill',  12, 1, 0, '["to_aftersale","suspend"]',                    '[]',                                         1),
  (1, 'OTHER',             '其他异常',       'data',     48, 1, 0, '["reaudit","suspend","cancel","force_pass"]',   '[]',                                         1);

-- 2) 审单原因码字典（SRS-D03.02 FR-02 插件清单失败动作；D01.03 枚举管理的本域落地视图）
--    level：BLOCK拦截触发路由/WARN提示不拦截；route：manual人工/shortage缺货/retrial复审/requeue回池/suspend挂起
CREATE TABLE IF NOT EXISTS ord_reason_code_dict (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  reason_code         VARCHAR(64)  NOT NULL COMMENT '原因码（租户内唯一；D01.03登记）',
  reason_name         VARCHAR(128) NOT NULL COMMENT '原因名称（人读）',
  plugin_name         VARCHAR(64)  NOT NULL COMMENT '产出插件（枚举同ord_audit_reason.plugin_name）',
  level               VARCHAR(8)   NOT NULL DEFAULT 'BLOCK' COMMENT '级别：BLOCK拦截/WARN提示',
  default_route       VARCHAR(16)  NOT NULL COMMENT '默认路由：manual人工/shortage缺货/retrial复审/requeue回池/suspend挂起',
  default_suggest     VARCHAR(32)  NULL COMMENT '默认建议动作：change_branch换仓/modify_address改地址/contact_buyer联系买家/wait_restock等补货/to_retrial转复审/reship补发',
  exc_type            VARCHAR(32)  NULL COMMENT '映射异常类型（LFK→ord_abnormal_type_dict.type_code；need_abnormal_bill=1时自动落异常单）',
  is_system           TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '系统内置：0否/1是（不可删）',
  disabled            TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '启停：0启用/1停用',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_reason_code_dict_code (tenant_id, reason_code)
) ENGINE=InnoDB COMMENT='审单原因码字典（原因码→级别/默认路由/建议动作/异常类型映射，D03.02）';

INSERT INTO ord_reason_code_dict
  (tenant_id, reason_code, reason_name, plugin_name, level, default_route, default_suggest, exc_type)
VALUES
  (1, 'HOLD_SPECIAL',      '特殊单型hold（预售/团购未放行）', 'admit_special',  'BLOCK', 'requeue',   'wait_restock',    NULL),
  (1, 'ABNORMAL_STATUS',   '订单硬状态异常（暂停/平台取消/密文缺失）', 'admit_status', 'BLOCK', 'manual', 'contact_buyer', 'OTHER'),
  (1, 'ABNORMAL_RISK',     '平台风控命中（抖音WAIT_SELLER_SEND_GOODS等）', 'admit_status', 'BLOCK', 'suspend', NULL,  'RISK_HIT'),
  (1, 'ADDR_DOUBLE',       '双地址检出',                        'admit_status',  'BLOCK', 'manual',    'modify_address',  'ADDR_INCOMPLETE'),
  (1, 'PAY_UNPAID',        '未支付（非COD）',                   'admit_pay',     'BLOCK', 'requeue',   NULL,              'PAY_ABNORMAL'),
  (1, 'REFUND_PENDING',    '存在退款中明细',                    'admit_pay',     'BLOCK', 'manual',    NULL,              'PAY_ABNORMAL'),
  (1, 'BLACKLIST',         '黑名单/风控名单命中',               'blacklist',     'BLOCK', 'retrial',   NULL,              'BLACKLIST'),
  (1, 'NO_BRANCH',         '候选仓为空',                        'branch_select', 'BLOCK', 'manual',    'change_branch',   NULL),
  (1, 'SPLIT_FAIL',        '拆单策略执行失败',                  'split',         'BLOCK', 'manual',    NULL,              'SPLIT_FAILED'),
  (1, 'GIFT_ONLY',         '仅赠品订单拒绝出单',                'split',         'BLOCK', 'manual',    NULL,              'SPLIT_FAILED'),
  (1, 'STOCK_SHORTAGE',    '库存不足（附缺口明细）',            'stock_check',   'BLOCK', 'shortage',  'wait_restock',    'STOCK_SHORT'),
  (1, 'NO_LOGISTICS',      '无可用物流',                        'logi_match',    'BLOCK', 'manual',    NULL,              NULL),
  (1, 'LOGI_SUSPEND',      '物流停运',                          'logi_match',    'BLOCK', 'manual',    NULL,              NULL),
  (1, 'LOGI_UNREACHED',    '物流不可达（偏远/乡村件）',         'logi_match',    'BLOCK', 'manual',    'contact_buyer',   'ADDR_REMOTE'),
  (1, 'COMBINE_WAIT',      '疑可合并回池等待',                  'combine_check', 'BLOCK', 'requeue',   NULL,              NULL),
  (1, 'COMBINE_CONFLICT',  '合单组冲突（组内规则不一致等）',    'combine_check', 'BLOCK', 'manual',    NULL,              'SPLIT_FAILED'),
  (1, 'GOODS_UNBOUND',     '商品未绑定基础物料',                'goods_match',   'BLOCK', 'suspend',   NULL,              'PRODUCT_UNBOUND'),
  (1, 'PRICE_ABNORMAL',    '价格异常（低于成本/限价倍数）',     'price_check',   'BLOCK', 'retrial',   NULL,              'PRICE_ABNORMAL'),
  (1, 'ADDRESS_INVALID',   '地址质量不可用（区划/长度/敏感词）','address_check', 'BLOCK', 'manual',    'modify_address',  'ADDR_INCOMPLETE'),
  (1, 'ADDRESS_FORBIDDEN', '禁运区地址',                        'address_check', 'BLOCK', 'manual',    'contact_buyer',   'ADDR_INCOMPLETE'),
  (1, 'MEMO_HOLD',         '备注留言命中关键字（到付/指定快递/暗号）', 'memo_flag', 'BLOCK', 'manual',  'contact_buyer',   NULL),
  (1, 'GIFT_INVALID',      '赠品方案无效',                      'gift_check',    'BLOCK', 'manual',    NULL,              NULL),
  (1, 'INVOICE_INVALID',   '发票要素缺失/税号格式错误',         'invoice_check', 'BLOCK', 'manual',    'contact_buyer',   NULL),
  (1, 'BIG_AMOUNT',        '大额订单拦截',                      'amount_check',  'BLOCK', 'retrial',   NULL,              NULL),
  (1, 'ROUTE_LIMIT',       '路由次数超限强制人工',              'routernum',     'BLOCK', 'manual',    NULL,              NULL),
  (1, 'STOCK_RACE',        '执行期库存竞态（预占失败回待审）',  'auto_pass',     'BLOCK', 'requeue',   'wait_restock',    NULL),
  (1, 'VILLAGE_HINT',      '乡村件提示',                        'logi_match',    'WARN',  'manual',    NULL,              NULL),
  (1, 'MULTI_ADDRESS',     '同用户多地址提示',                  'combine_check', 'WARN',  'manual',    NULL,              NULL),
  (1, 'CIPHER_RECEIVER',   '密文收货人提示（打单用原密文）',    'admit_status',  'WARN',  'manual',    NULL,              NULL),
  (1, 'LABEL_MARKED',      '标记打标结果（加急/时效紧张/集运）','label_mark',    'WARN',  'manual',    NULL,              NULL);

-- 3) 系统内置缺省审单规则（autoConfirm=关，全转人工兜底；SRS-D03.02 FR-03b）
INSERT INTO ord_audit_rule
  (tenant_id, rule_name, conditions, weight, plugin_config, auto_confirm, pass_action, fail_route, router_num_limit, status, is_default)
VALUES
  (1, '系统缺省规则（全转人工）', '[]', -999999, NULL, 0, 'draft_confirm', NULL, 5, 'enabled', 1);

-- 4) 全局缺省归档配置（SRS-D03.13 §6.4 默认值）
INSERT INTO ord_archive_config
  (tenant_id, scope_level, scope_id, archive_months, aftersale_protect_days, recall_cooldown_months, batch_size, qps_limit, brand_switch, cold_offload_years)
VALUES
  (1, 'global', 0, 6, 90, 1, 500, NULL, 1, 5);

-- =====================================================================
-- V1.1 增补：促销与赠品引擎（SRS-D03.14，P1·M3；P0 期建表预留）
--   商派溯源：ome.gift_rule / gift_logs / gift_set_logs + crm.gift_rule_base
--   关键差异：承载于 D01.03 规则框架（rule_id 引用，本域存业务档案）；
--            赠品也占库存（D04.03 预占）；货主隔离；加赠日志可回放可撤销
-- =====================================================================

-- ---------------------------------------------------------------------
-- P1. ord_promotion_activity 促销活动（SRS-D03.14 §6.1）
-- ---------------------------------------------------------------------
CREATE TABLE ord_promotion_activity (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID（隔离红线：品牌A促销绝不影响品牌B）',
  activity_bn         VARCHAR(32)  NOT NULL COMMENT '活动编号：PA+yyMMdd+序列，租户内唯一',
  activity_name       VARCHAR(128) NOT NULL COMMENT '活动名称',
  activity_type       VARCHAR(24)  NOT NULL COMMENT '活动类型：full_gift满赠/buy_gift买赠/ladder_gift阶梯满赠/qty_discount满件折/amount_reduce满减',
  rule_id             BIGINT UNSIGNED NULL COMMENT '承载规则ID（LFK→oms_base.bas_rule，条件DSL+动作schema存规则框架）',
  rule_snapshot_id    BIGINT UNSIGNED NULL COMMENT '规则版本快照ID（决策留痕，回放依据）',
  start_time          DATETIME(3)  NOT NULL COMMENT '活动开始时间（判定基准=订单pay_time）',
  end_time            DATETIME(3)  NOT NULL COMMENT '活动结束时间',
  scope_shops         JSON         NULL COMMENT '生效店铺集（空=货主全店铺）',
  scope_brands        JSON         NULL COMMENT '生效品牌集',
  priority            INT          NOT NULL DEFAULT 0 COMMENT '优先级（数值大者优先，同分按id ASC）',
  mutex_group         VARCHAR(32)  NULL COMMENT '互斥组（同组互斥取胜者，空=独立组）',
  stackable           TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '叠加规则：0否(全局仅执行1个活动)/1是',
  total_limit         INT UNSIGNED NULL COMMENT '活动总量上限（限量赠品封顶，空=不限）',
  total_consumed      INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '已消耗量（原子扣减，≥80%提醒）',
  gift_lack_policy    VARCHAR(16)  NOT NULL DEFAULT 'skip_gift' COMMENT '赠品缺货策略：skip_gift放弃赠品(默认不阻断主品)/hold_order整单挂起/replace换等价赠品/manual人工',
  status              VARCHAR(16)  NOT NULL DEFAULT 'draft' COMMENT '活动状态：draft草稿/pending待生效/active生效中/paused已暂停/ended已结束/voided已作废',
  creator             VARCHAR(64)  NULL COMMENT '创建人',
  auditor             VARCHAR(64)  NULL COMMENT '审核人（上线双人复核防门槛配错资损）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_promo_activity_bn (tenant_id, activity_bn),
  KEY idx_ord_promo_activity_owner (owner_id, status, start_time, end_time),
  KEY idx_ord_promo_activity_type (activity_type, status)
) ENGINE=InnoDB COMMENT='促销活动（满赠/买赠/阶梯/满减折，货主隔离，D03.14）';

-- ---------------------------------------------------------------------
-- P2. ord_promotion_rule 促销规则动作（活动1:1，动作结构化冗余供查询，§6.2）
-- ---------------------------------------------------------------------
CREATE TABLE ord_promotion_rule (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  activity_id         BIGINT UNSIGNED NOT NULL COMMENT '活动ID（LFK→ord_promotion_activity，1:1）',
  threshold_type      VARCHAR(16)  NULL COMMENT '门槛类型：amount实付金额/qty件数（满减折/满赠用）',
  threshold           DECIMAL(18,2) NULL COMMENT '门槛值',
  ladders             JSON         NULL COMMENT '阶梯档位：[{threshold_type,threshold,gifts[]}]，档位threshold严格递增（保存期校验）',
  gift_per            INT UNSIGNED NULL COMMENT '买赠比例（买N送M的N，买赠必填）',
  order_limit         INT UNSIGNED NULL COMMENT '单均赠品上限（防单单薅赠）',
  discount_type       VARCHAR(16)  NULL COMMENT '调价类型（满减折专用）：reduce立减/discount折扣',
  discount_value      DECIMAL(18,4) NULL COMMENT '调价值（立减金额/折扣率）',
  confirm_mode        VARCHAR(16)  NOT NULL DEFAULT 'manual' COMMENT '调价确认模式（P1恒manual人工复核）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_promo_rule_activity (activity_id)
) ENGINE=InnoDB COMMENT='促销规则动作（门槛/阶梯/买赠比例/调价参数，D03.14）';

-- ---------------------------------------------------------------------
-- P3. ord_promotion_gift 赠品明细（活动1:N，§6.2）
-- ---------------------------------------------------------------------
CREATE TABLE ord_promotion_gift (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  activity_id         BIGINT UNSIGNED NOT NULL COMMENT '活动ID（LFK→ord_promotion_activity）',
  ladder_no           INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '阶梯档位号（满赠=0，阶梯满赠=1,2,3...）',
  sm_id               BIGINT UNSIGNED NOT NULL COMMENT '赠品销售物料ID（LFK→oms_stock.inv_sales_material，必须type=赠品且已绑定BOM，保存期校验）',
  num                 INT UNSIGNED NULL COMMENT '固定赠品数量（满赠用）',
  num_per_unit        INT UNSIGNED NULL COMMENT '按主品件数倍率（买赠用，每gift_per件送num_per_unit）',
  backup_seq          INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '备选序（replace策略换赠顺序，0=主赠品）',
  gift_owner_id       BIGINT UNSIGNED NOT NULL COMMENT '赠品货主（=BOM展开货主，必须∈活动scope货主，强校验）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记',
  PRIMARY KEY (id),
  KEY idx_ord_promo_gift_activity (activity_id, ladder_no, backup_seq)
) ENGINE=InnoDB COMMENT='促销赠品明细（赠品物料/数量/备选序/货主，D03.14）';

-- ---------------------------------------------------------------------
-- P4. ord_promotion_scope 活动商品范围（§6.3）
-- ---------------------------------------------------------------------
CREATE TABLE ord_promotion_scope (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  activity_id         BIGINT UNSIGNED NOT NULL COMMENT '活动ID（LFK→ord_promotion_activity）',
  direction           VARCHAR(16)  NOT NULL DEFAULT 'include' COMMENT '方向：include参与/exclude排除（优先于include）',
  scope_type          VARCHAR(16)  NOT NULL COMMENT '圈选方式：sku(bm_id清单)/category分类树节点/brand品牌/all全部',
  scope_value         JSON         NULL COMMENT '圈选值（sku清单上限5000，超限强制转category/all）',
  role                VARCHAR(16)  NOT NULL DEFAULT 'base' COMMENT '范围角色：base满赠基数商品/main买赠主品（同活动可两条）',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID（范围行级货主过滤，多货主店铺按行归属）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记',
  PRIMARY KEY (id),
  KEY idx_ord_promo_scope_activity (activity_id, direction, role)
) ENGINE=InnoDB COMMENT='促销活动商品范围（参与/排除×SKU/分类/品牌，D03.14）';

-- ---------------------------------------------------------------------
-- P5. ord_gift_log 加赠日志（只增不改，对齐商派 ome.gift_logs，§6.4）
--     溯源：可回放（rule_snapshot_id）、可撤销（revoke回链原log_id）
-- ---------------------------------------------------------------------
CREATE TABLE ord_gift_log (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID（行级过滤）',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '订单ID（LFK→ord_order）',
  order_item_id       BIGINT UNSIGNED NULL COMMENT '赠品订单行ID（行未生成时为空，如放弃场景）',
  activity_id         BIGINT UNSIGNED NOT NULL COMMENT '活动ID（LFK→ord_promotion_activity）',
  rule_snapshot_id    BIGINT UNSIGNED NULL COMMENT '规则版本快照ID（回放依据，不受活动后续变更影响）',
  log_type            VARCHAR(16)  NOT NULL COMMENT '类型：applied加赠/revoke撤销(回链原log_id)/skipped缺货放弃或落选备查',
  origin_log_id       BIGINT UNSIGNED NULL COMMENT '撤销回链原加赠日志ID（log_type=revoke时）',
  sm_id               BIGINT UNSIGNED NULL COMMENT '赠品销售物料ID',
  bm_expand           JSON         NULL COMMENT 'BOM展开快照：[{bm_id,num,owner_id}]（D04.01 §5.3口径）',
  gift_num            INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '加赠数量（>0）',
  hit_basis           JSON         NULL COMMENT '命中依据快照：基数金额/件数/档位/买赠比例计算过程',
  judge_detail        JSON         NULL COMMENT '裁决明细：命中集/胜出集/落选集与原因（FR-05c）',
  revoke_reason       VARCHAR(64)  NULL COMMENT '撤销原因：order_cancel订单取消/modify_downgrade改单降档/race_give_up竞态放弃/manual人工撤销/reaudit重审重算',
  idempotent_key      VARCHAR(128) NOT NULL COMMENT '幂等键：(order_id,plan_version)（FR-03e防重复加赠）',
  operator            VARCHAR(64)  NOT NULL DEFAULT 'system' COMMENT '操作者（auto=system，人工撤销=真实账号）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间（追加不可改）',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_gift_log_idem (idempotent_key, log_type),
  KEY idx_ord_gift_log_order (order_id),
  KEY idx_ord_gift_log_activity (activity_id, create_time)
) ENGINE=InnoDB COMMENT='加赠日志（可回放可撤销，对齐商派gift_logs，只增不改，D03.14）';

-- =====================================================================
-- V1.2 增补（2026-10-24，友商对标 7 项决策落地）
--   ① SRS-D03.06 V1.2 FR-08a：DOM 路由决策日志 ord_routing_decision_log
--      （只增、按月分表 _YYYYMM，算法寻源训练数据地基，G4 决策A）
--   ② SRS-D03.09 V1.2：ord_abnormal_type_dict 补 ADDR_FAKE / PURCHASE_LIMIT
--      两条字典数据（G2 决策A，联动 D03.02 V1.2 插件 address_check/purchase_limit）
--   ③ SRS-D03.02 V1.2：限购规则承载于 oms_base.bas_rule（D01.03，无需新表）；
--      ord_risk_list.list_type 为 VARCHAR 字符串码（DB-00 §3.3 值可扩展），
--      「风控观察名单」由 gray 灰名单码值承载，仅补列注释说明（无 DDL 结构变更）
--   ④ SRS-D03.15 即时零售履约（新模块 P1，G1 决策）：
--      ord_order 增列（§6.1）+ ord_store_profile 增列（§6.4）
--      + ord_instant_delivery 发货单扩展（§6.2）+ ord_instant_track 时效台账（§6.3）
--      售后扩展（§6.5）挂 oms_aftersale.aft_return_apply，见 DB-D05（本脚本不涉及）
-- =====================================================================

-- ---------------------------------------------------------------------
-- V1.2-1. ord_order 即时零售增列（SRS-D03.15 §6.1，canonical 主表冗余+扩展列）
-- ---------------------------------------------------------------------
ALTER TABLE ord_order
  ADD COLUMN fulfill_channel VARCHAR(16) NOT NULL DEFAULT 'express' COMMENT '履约通道（SRS-D03.15 §6.1，落单即定不可变）：express常规快递/store门店履约(D03.11)/instant即时零售(D03.15)' AFTER self_delivery,
  ADD COLUMN promise_time    DATETIME(3) NULL COMMENT '期望送达时间（即时零售必填；平台报文优先，缺失按店铺默认60分钟兜底+转换告警；时效监控高频查询冗余列）' AFTER fulfill_channel,
  ADD COLUMN promise_type    VARCHAR(16) NULL COMMENT '时效承诺类型：min30三十分钟达/hour1一小时达/scheduled定时达（平台字典映射，D02.02 enum_mapping）' AFTER promise_time,
  ADD COLUMN receiver_lng    DECIMAL(10,6) NULL COMMENT '收货地经度（即时零售必填：派店球面距离+运力呼叫；PIPL敏感：脱敏展示+明文查看留痕D01.05/D10.06）' AFTER promise_type,
  ADD COLUMN receiver_lat    DECIMAL(10,6) NULL COMMENT '收货地纬度（同 receiver_lng 口径）' AFTER receiver_lng,
  ADD COLUMN delivery_fee    DECIMAL(18,2) NULL COMMENT '配送费（即时零售；明细存 platform_extra.instant）' AFTER receiver_lat,
  ADD COLUMN fee_bearer      VARCHAR(16) NULL COMMENT '配送费承担方：platform平台/merchant商家/consumer消费者' AFTER delivery_fee,
  ADD COLUMN instant_platform VARCHAR(32) NULL COMMENT '即时零售平台标识：meituan_shangou美团闪购/ele_retail饿了么零售/jddj京东到家秒送/douyin_hour抖音小时达/taobao_hour淘宝小时达（fulfill_channel=instant时必填）' AFTER fee_bearer,
  ADD KEY idx_ord_order_instant (fulfill_channel, promise_time);

-- ---------------------------------------------------------------------
-- V1.2-2. ord_store_profile 门店即时零售属性增列（SRS-D03.15 §6.4）
-- ---------------------------------------------------------------------
ALTER TABLE ord_store_profile
  ADD COLUMN instant_enabled       TINYINT(1) NOT NULL DEFAULT 0 COMMENT '即时零售能力开关：0关(不参与instant派店)/1开' AFTER pickup_enabled,
  ADD COLUMN instant_platforms     JSON NULL COMMENT '开通即时零售平台集（与店铺授权D02.06联动校验）' AFTER instant_enabled,
  ADD COLUMN pick_time_limit       INT UNSIGNED NOT NULL DEFAULT 15 COMMENT '拣货时限分钟（默认15；实际=min(本配置, promise_time−配送预计−交接缓冲)，SRS-D03.15 §5.2④）' AFTER instant_platforms,
  ADD COLUMN accept_timeout_instant INT UNSIGNED NOT NULL DEFAULT 5 COMMENT '即时零售接单超时分钟（默认5；常规单仍走accept_timeout=30）' AFTER pick_time_limit,
  ADD COLUMN self_delivery_enabled TINYINT(1) NOT NULL DEFAULT 0 COMMENT '自配送开关：0关/1开（D09.06 FR-06 兜底数据源）' AFTER accept_timeout_instant,
  ADD COLUMN courier_pool          JSON NULL COMMENT '自配送配送员池：[{姓名,手机号(加密),状态(在班/休息),在途单数}]（D09.06 FR-06b）' AFTER self_delivery_enabled;

-- ---------------------------------------------------------------------
-- V1.2-3. ord_instant_delivery 即时零售发货单扩展（SRS-D03.15 §6.2；1:1 挂发货单）
-- ---------------------------------------------------------------------
CREATE TABLE ord_instant_delivery (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  delivery_id         BIGINT UNSIGNED NOT NULL COMMENT '发货单（1:1，LFK→ord_delivery；即时零售单sync_status=no_need免推仓，状态由编排状态机映射驱动D03.07）',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '订单ID（LFK→ord_order，fulfill_channel=instant）',
  fulfill_mode        VARCHAR(16)  NOT NULL DEFAULT 'city_delivery' COMMENT '履约方式：city_delivery同城即时配送（启用D03.11 fulfill_mode的P2预留值，SRS-D03.15 §6.2）',
  orchestrate_status  VARCHAR(24)  NOT NULL DEFAULT 'accepted' COMMENT '编排状态（SRS-D03.15 §4.2权威状态机）：accepted已接单/refused已拒单/picking拣货中/lack_handling缺货处理中/wait_pickup待取货/delivering配送中/delivered已送达/redispatching改派中/self_delivering自配送中/exception_handling异常处理中/aftersale售后中/finished完成/cancelled已取消（经DeliveryStateMachine::transit映射驱动D03.07发货单状态，映射表配置化）',
  store_branch_id     BIGINT UNSIGNED NOT NULL COMMENT '履约门店仓（LFK→ord_store_profile；改派时变更，留痕见store_change_log）',
  store_change_log    JSON         NULL COMMENT '门店改派留痕：[{原店,新店,原因,时间}]（§6.2改派时变更留痕；拣货超时改派原因=拣货超时+原门店责任登记，赔付台账输入§5.3）',
  pick_deadline       DATETIME(3)  NULL COMMENT '拣货时限时间点=min(店铺配置15min, promise_time−配送预计时长−交接缓冲5min)（倒计时分级60%/80%/100%/130%基准，FR-03b）',
  pick_progress       DECIMAL(9,4) NOT NULL DEFAULT 0 COMMENT '拣货进度=已确认行/总行（0-1；≥0.7触发预呼叫，FR-04b）',
  rider_order_no      VARCHAR(64)  NULL COMMENT '运力方单号（D09.06呼叫受理回执落库；改派历史存oms_fulfill.ful_rider_call轮次行）',
  carrier_code        VARCHAR(32)  NULL COMMENT '运力方编码（LFK→oms_fulfill.ful_carrier.carrier_code；SELF=自配送兜底）',
  pre_call_flag       TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '预呼叫标记：0否/1是（店铺级开关默认开，拣货进度≥70%提前呼叫，FR-04b）',
  call_round          INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '呼叫轮次（≥1，>3告警；对齐D03.11 dispatch_round口径；幂等键=(delivery_id,call_round)由D09.06承接）',
  handover_operator   VARCHAR(64)  NULL COMMENT '交接店员账户（扫码交接落库；未扫码补录走差异标记，FR-04c）',
  handover_time       DATETIME(3)  NULL COMMENT '交接时间（rider.handover.done事件时间戳）',
  self_delivery_flag  TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '自配送标记：0否/1是（改派连续失败≥2次或剩余时效不足时兜底切换，D09.06 FR-06联动）',
  courier_info        JSON         NULL COMMENT '自配送配送员信息：{姓名,手机号(脱敏),状态}（兜底切换时启用，作业台自配送面板数据源）',
  promise_risk_flag   TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '时效风险标记：0否/1是（全链路预测超时=剩余节点预估耗时>剩余时效时置位，FR-08b看板过滤）',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁（编排状态机CAS写入）',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_instant_delivery_delivery (delivery_id),
  KEY idx_ord_instant_delivery_order (order_id),
  KEY idx_ord_instant_delivery_status (orchestrate_status, promise_risk_flag),
  KEY idx_ord_instant_delivery_store (store_branch_id, orchestrate_status)
) ENGINE=InnoDB COMMENT='即时零售发货单扩展（编排状态机/拣货倒计时/骑手呼叫/扫码交接/自配送兜底，1:1挂发货单，P1，D03.15）';

-- ---------------------------------------------------------------------
-- V1.2-4. ord_instant_track 即时零售时效台账（SRS-D03.15 §6.3；FR-08a 8节点）
-- ---------------------------------------------------------------------
CREATE TABLE ord_instant_track (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID（SRS-00契约必填）',
  delivery_id         BIGINT UNSIGNED NOT NULL COMMENT '发货单（LFK→ord_delivery，1:1）',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '订单ID（LFK→ord_order）',
  store_branch_id     BIGINT UNSIGNED NOT NULL COMMENT '履约门店仓（LFK→ord_store_profile）',
  ts_platform_order   DATETIME(3)  NULL COMMENT '节点1：平台下单时间（报文携带）',
  ts_oms_accept       DATETIME(3)  NULL COMMENT '节点2：OMS接单时间（订单落库+下单即预占成功）',
  ts_store_accept     DATETIME(3)  NULL COMMENT '节点3：门店接单时间',
  ts_pick_start       DATETIME(3)  NULL COMMENT '节点4：拣货开始时间',
  ts_pick_done        DATETIME(3)  NULL COMMENT '节点5：拣货完成时间（打包确认）',
  ts_handover         DATETIME(3)  NULL COMMENT '节点6：骑手取货交接时间（扫码/补录）',
  ts_delivered        DATETIME(3)  NULL COMMENT '节点7：送达确认时间（超时判定基准 vs promise_time）',
  ts_sync_done        DATETIME(3)  NULL COMMENT '节点8：平台状态回传成功时间（逐节点回传以末次为准）',
  dur_dispatch        INT UNSIGNED NULL COMMENT '派店耗时秒（派生：oms接单→门店接单）',
  dur_pick            INT UNSIGNED NULL COMMENT '拣货耗时秒（派生：拣货开始→拣货完成）',
  dur_wait_rider      INT UNSIGNED NULL COMMENT '等骑手耗时秒（派生：拣货完成→交接；交接差异细分输入D09.06 FR-04d）',
  dur_deliver         INT UNSIGNED NULL COMMENT '配送耗时秒（派生：交接→送达）',
  overtime_flag       TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '配送超时标记：0否/1是（ts_delivered>promise_time，平台口径优先）',
  overtime_minutes    INT UNSIGNED NULL COMMENT '超时时长分钟',
  liability           VARCHAR(16)  NULL COMMENT '超时责任方（§5.6判定链顺序短路）：store门店(接单/拣货超时)/carrier运力方(接单率/配送超时)/system系统(呼叫失败延误)/merchant商家承担(不可抗力人工登记)',
  compensation_amount DECIMAL(18,2) NULL COMMENT '赔付金额（平台规则/运力方协议；赔付台账登记）',
  bearer              VARCHAR(16)  NULL COMMENT '赔付承担方：carrier运力方(联动D09.06结算台账核减)/platform平台(平台扣款承接)/merchant商家',
  evidence_snapshot   JSON         NULL COMMENT '依据快照=8节点时间戳固化（赔付争议可回放，AC-11）',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间（节点时间戳渐进回填）',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ord_instant_track_delivery (delivery_id),
  KEY idx_ord_instant_track_order (order_id),
  KEY idx_ord_instant_track_overtime (overtime_flag, liability, create_time),
  KEY idx_ord_instant_track_store (store_branch_id, create_time)
) ENGINE=InnoDB COMMENT='即时零售时效台账（8节点时间戳+派生耗时+超时责任+赔付登记，随订单归档D03.13，P1，D03.15）';

-- ---------------------------------------------------------------------
-- V1.2-5. ord_routing_decision_log 路由决策日志（SRS-D03.06 V1.2 FR-08a；
--         DOM埋点=算法寻源训练数据地基；只增不改，按月分表 _YYYYMM 基表模板）
-- ---------------------------------------------------------------------
CREATE TABLE ord_routing_decision_log (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '订单ID（LFK→ord_order）',
  round_no            INT UNSIGNED NOT NULL COMMENT '路由轮次（对齐ord_dispatch_plan.round_no）',
  candidate_branches  JSON         NOT NULL COMMENT '候选仓集合：[branch_id]（候选生成=货主仓属∩店铺绑定∪区域路由，FR-08a）',
  branch_features     JSON         NOT NULL COMMENT '各仓特征快照：[{branch_id,available可用量,depth库存深度,distance区域距离,freight预估运费,eta预估时效,backlog作业负载}]（算法训练特征，FR-08a）',
  rule_hit            JSON         NULL COMMENT '命中规则：{规则ID,策略类型,仓序}（可回放，同ord_dispatch_plan.rule_hit口径）',
  chosen_branch       BIGINT UNSIGNED NULL COMMENT '最终选仓（LFK→oms_fulfill.ful_branch；缺货/转人工时NULL）',
  cost_compare        JSON         NULL COMMENT '成本对比：{split_cost拆单成本(多包裹运费+包材),wait_cost等货成本(时效损失),transfer_cost调拨成本(D04.05),weights权重,suggest建议}（FR-08b规则式打分）',
  decision_mode       VARCHAR(16)  NOT NULL DEFAULT 'rule' COMMENT '决策模式：rule规则式(首期)/algorithm算法寻源(P2 RoutingOptimizer扩展点预留，FR-08d)',
  duration_ms         INT UNSIGNED NULL COMMENT '决策耗时毫秒',
  shop_id             BIGINT UNSIGNED NOT NULL COMMENT '店铺ID',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间（分表路由键；只增不改无update_time）',
  PRIMARY KEY (id),
  KEY idx_ord_routing_decision_log_order (order_id, round_no),
  KEY idx_ord_routing_decision_log_time (create_time),
  KEY idx_ord_routing_decision_log_branch (chosen_branch, create_time)
) ENGINE=InnoDB COMMENT='路由决策日志（DOM埋点：候选仓/特征快照/命中规则/选仓/成本对比/耗时，只增，按月分表_YYYYMM，在线3个月+归档，D03.06 FR-08a）';
-- 月表示例（调度器滚动创建）：CREATE TABLE ord_routing_decision_log_202611 LIKE ord_routing_decision_log;

-- ---------------------------------------------------------------------
-- V1.2-6. ord_risk_list 名单类型注释补充（SRS-D03.02 V1.2 限购/风控观察名单；
--         list_type为VARCHAR字符串码已具扩展性=DB-00 §3.3，无结构变更仅改注释）
-- ---------------------------------------------------------------------
ALTER TABLE ord_risk_list
  MODIFY COLUMN list_type VARCHAR(8) NOT NULL COMMENT '名单类型：black黑名单/gray灰名单(含风控观察名单：限购命中ADDR_FAKE/PURCHASE_LIMIT等观察对象，SRS-D03.02/09 V1.2 G2；如需细分可扩展watch码值，字符串码免DDL)/white白名单';

-- ---------------------------------------------------------------------
-- V1.2-7. 异常类型字典补 2 条（SRS-D03.09 V1.2，格式同上方初始 INSERT）
-- ---------------------------------------------------------------------
INSERT INTO ord_abnormal_type_dict
  (tenant_id, type_code, type_name, category, default_sla_hours, need_abnormal_bill, block_fulfill, action_set, reason_code_map, is_system)
VALUES
  (1, 'ADDR_FAKE',       '虚假/不可达地址', 'data',     24, 1, 0, '["reaudit","to_aftersale"]',                '["ADDRESS_FAKE"]',                           1),
  (1, 'PURCHASE_LIMIT',  '限购命中',        'risk',      8, 1, 1, '["suspend","force_pass","cancel"]',         '["PURCHASE_LIMIT"]',                         1);

-- 联动：审单原因码字典补 2 码（SRS-D03.02 V1.2 插件 address_check 增强 / purchase_limit 新增）
INSERT INTO ord_reason_code_dict
  (tenant_id, reason_code, reason_name, plugin_name, level, default_route, default_suggest, exc_type)
VALUES
  (1, 'ADDRESS_FAKE',      '地图API校验虚假/不可达地址（V1.2增强，降级规则校验）', 'address_check',  'BLOCK', 'manual',  'contact_buyer', 'ADDR_FAKE'),
  (1, 'PURCHASE_LIMIT',    '限购命中（同收货人/手机/地址/设备时间窗超限，附命中规则）', 'purchase_limit', 'BLOCK', 'manual', NULL,          'PURCHASE_LIMIT');

-- =====================================================================
-- 附：分表/分区说明（DB-00 §1.3）
-- 1. ord_order 预留按 create_time 月度 RANGE 分区（order_bn 前缀含日期天然支持
--    冷热路由）；P0 单表起步，量级触阈值后 ALTER TABLE ... PARTITION BY RANGE。
-- 2. 归档库 oms_archive 同构表（ord_order_archive 定位的分片表，后缀 _archive，
--    按完结年月 YYYYMM 分表）由归档任务在归档库创建，本脚本不建（跨库只读账号）。
-- 3. ord_audit_plugin_perf 在线 3 个月滚动清理（调度任务 DELETE 按 create_time）。
-- 4. ord_routing_decision_log（V1.2 增补）按月分表 _YYYYMM，基表为结构模板，
--    月表由调度任务 CREATE TABLE ... LIKE 滚动创建；在线 3 个月+归档（DB-00 §1.3）。
-- =====================================================================

-- ----------------------------------------------------------------------------
-- V1.4 业务完整性仿真增补（S1 客服协同标记体系）
-- 来源：SRS-D03.01 V1.4 §6.5 / FR-04h；SRS-D03.03 FR-09；SRS-D02.04 FR-09
-- ----------------------------------------------------------------------------
CREATE TABLE ord_flag_change_log (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  order_id           BIGINT UNSIGNED NOT NULL COMMENT '订单ID LFK→ord_order',
  order_bn           VARCHAR(32)     NOT NULL COMMENT '订单号（冗余检索）',
  before_color       TINYINT         NOT NULL DEFAULT 0 COMMENT '变更前旗帜：0无旗/1红/2黄/3绿/4蓝/5紫',
  after_color        TINYINT         NOT NULL DEFAULT 0 COMMENT '变更后旗帜',
  change_source      TINYINT         NOT NULL COMMENT '来源：1=平台同步（拉单/消息解析），2=人工标旗（客服/审单员），3=系统规则（审单插件自动标旗）',
  operator_account   VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '操作者账号（人工时必填；平台同步=platform）',
  sync_status        TINYINT         NOT NULL DEFAULT 0 COMMENT '回传平台状态（V1.4 D02.04 FR-09a）：0=无需回传，1=待回传，2=回传成功，3=回传失败（低优队列重试）',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '变更时间',
  PRIMARY KEY (id),
  KEY idx_ord_flag_log_order (order_id, create_time),
  KEY idx_ord_flag_log_sync (sync_status, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='订单旗帜变更留痕（只增不改；双向同步审计依据）（D03.01 V1.4,P1）';
