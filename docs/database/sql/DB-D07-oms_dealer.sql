-- ============================================================================
-- ██ DB-D07 经销域建表脚本（oms_dealer）—— P2 建库占位 ██
-- ██ 显著声明: 本脚本为 P2（M4 之后启动）占位建库脚本，P0/P1 期【不执行】；      ██
-- ██ P2 启动时执行建库，表结构随 P2 启动按业务确认结果细化（只增列不改契约位）。  ██
-- ============================================================================
-- 文档编号: DB-D07 · 版本 V1.0 · 2026-10-24 · MySQL 8.0 语法 DDL（P2 占位）
-- 上游契约: DB-00 数据库设计总册（schema=oms_dealer / 表前缀 dlr_ / 公共字段 / 不建物理外键）
-- 需求依据: SRS-D07.01 经销商管理 / SRS-D07.02 B2B销售订单 / SRS-D07.03 批发价格体系 /
--           SRS-D07.04 转单与货权拆分（4份均 P2 占位）§6 数据字段
-- ----------------------------------------------------------------------------
-- 执行顺序（P2 启动时）:
--   1) CREATE DATABASE oms_dealer
--   2) 字典: dlr_price_type
--   3) 主数据: dlr_dealer / dlr_dealer_shop
--   4) 信用: dlr_credit_account / dlr_credit_txn / dlr_credit_period
--   5) 授权: dlr_product_auth
--   6) 交易: dlr_sales_order / dlr_sales_order_item
--   7) 价格: dlr_price_list / dlr_price_change
--   8) 转单: dlr_transfer_order / dlr_transfer_order_item / dlr_dropship_ledger
--   9) 初始字典数据 INSERT: dlr_price_type（三类价格类型）
-- 依赖: 仅本 schema；跨域为逻辑外键 LFK（应用层校验），不建物理外键
-- 复用契约（P0/P1 预留位，零改动既有表）: DEALER_TC 货主枚举(D10.01 R1) / reserved_dealer 组织节点(R2) /
--   账期落 org_owner_settle_config(R3) / dealer 外部租户(D10.02 R4) / 门户外壳(D10.04 R5) /
--   B2B 转入通道(D03.01, order_source=b2b) / owner 拆单策略(D03.04 FR-05f) / ar_type=b2b_receivable(D08.01) /
--   DEALER_TC 货主结算(D08.02) / 借调台账模式镜像(D04.05)
-- 例外约定: dlr_credit_txn / dlr_dropship_ledger 为 append-only 流水（无 is_deleted/version/update_time，红冲纠错）；
--   单据类（dlr_sales_order/_item、dlr_transfer_order/_item、dlr_price_change）禁用软删
-- 命名/类型基线: DB-00 §2/§6；utf8mb4 / utf8mb4_0900_ai_ci / InnoDB；枚举不用 ENUM，COMMENT 写全枚举值
-- ============================================================================

-- ██ P2 启动时执行以下建库语句（P0/P1 期注释保持） ██
CREATE DATABASE IF NOT EXISTS oms_dealer DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE oms_dealer;

-- ============================================================================
-- 一、字典
-- ============================================================================

-- 9. 价格类型字典（D07.03 FR-01 · P2占位，配置表 owner_id 免填）
CREATE TABLE dlr_price_type (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id   BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  type_code   VARCHAR(32)     NOT NULL COMMENT '类型码(唯一):dealer_price=经销价(买断转售出货价,主类型),wholesale_price=批发价(一般批发客户通用价,等级价目表默认承载),special_price=特批价(单商单SKU临时特价)',
  type_name   VARCHAR(64)     NOT NULL COMMENT '类型名称',
  tax_mode    TINYINT         NOT NULL DEFAULT 1 COMMENT '价格属性:1=含税价,2=不含税价(税率引用D04.01物料开票属性;不含税=毛利分析口径)',
  status      TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=停用',
  create_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version     INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted  TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_dlr_price_type_code (type_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='价格类型字典(D07.03,P2占位)';

-- ============================================================================
-- 二、主数据（D07.01）
-- ============================================================================

-- 1. 经销商档案（D07.01 FR-01/02 · P2占位，单据类禁软删）
-- ← 商派 dealer.business(bs) 改造:+owner_id货主贯通(DEALER_TC)、组织编码收敛org_node_id单引用(规避双写脆弱性)
CREATE TABLE dlr_dealer (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  dealer_bn         VARCHAR(32)     NOT NULL COMMENT '经销商编码(全局唯一,Redis发号)',
  dealer_name       VARCHAR(128)    NOT NULL COMMENT '经销商名称',
  tax_no            VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '统一社会信用代码(格式校验)',
  dealer_level      TINYINT         NOT NULL DEFAULT 3 COMMENT '等级:1=战略,2=A级,3=B级,4=C级(驱动D07.03取价;变更走OA只对未来订单生效,历史订单价格快照不变)',
  region_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '区域(区域树节点:大区→省→市;驱动取价与串货管控;区域树载体P2启动定:复用org_node或本域字典)',
  coop_mode         TINYINT         NOT NULL DEFAULT 1 COMMENT '合作模式:1=买断转售,2=代发,3=混合(业务假设待P2启动前确认)',
  owner_id          BIGINT UNSIGNED NOT NULL COMMENT '联动货主(DEALER_TC类型,一对一,建档联动创建R1) LFK→oms_org.org_owner',
  org_node_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '组织节点(reserved_dealer类型R2) LFK→oms_org.org_node;层级:集团→销售团队→贸易公司→经销商→经销店铺',
  portal_tenant_id  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '门户外部租户(tenant_type=dealer,R4) LFK→oms_org.org_tenant',
  salesman_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '归属业务员 LFK→oms_org.org_account(业绩维度,D11供数)',
  sales_org_id      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '销售团队组织节点 LFK→oms_org.org_node',
  contact_name_enc  VARBINARY(255)  NULL DEFAULT NULL COMMENT '联系人姓名密文(D01.05信封加密,DB-00 §3.2)',
  contact_phone_enc VARBINARY(255)  NULL DEFAULT NULL COMMENT '联系电话密文',
  contact_phone_hash CHAR(64)       NOT NULL DEFAULT '' COMMENT '电话盲索引(HMAC,检索用)',
  invoice_json      JSON            NULL DEFAULT NULL COMMENT '发票信息(抬头/税号/开户行等)',
  address_json      JSON            NULL DEFAULT NULL COMMENT '收货地址集(可多个)',
  status            TINYINT         NOT NULL DEFAULT 1 COMMENT '生命周期:1=合作中,2=暂停(新单停止/门户降级只读),3=终止(前置校验:信用占用=0+无在途B2B订单+无未闭环售后+无未决对账单;OA审批;货主/租户/档案三处联动只读禁用,复用D10.01 FR-06状态机)',
  source            VARCHAR(16)     NOT NULL DEFAULT 'local' COMMENT '数据来源:local=手工,import=导入,migration=迁移(DB-00 §7)',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_dlr_dealer_bn (dealer_bn),
  UNIQUE KEY uk_dlr_dealer_owner (owner_id),
  KEY idx_dlr_dealer_level (dealer_level, region_id),
  KEY idx_dlr_dealer_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='经销商档案(D07.01,P2占位,与货主一对一)';

-- 2. 经销商店铺关联（D07.01 FR-02b · P2占位，关联表）一店铺只归一经销商(商派series_endorse约束继承)
CREATE TABLE dlr_dealer_shop (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id   BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id    BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(冗余自经销商档案,DEALER_TC)',
  dealer_id   BIGINT UNSIGNED NOT NULL COMMENT '经销商 LFK→dlr_dealer',
  shop_id     BIGINT UNSIGNED NOT NULL COMMENT '店铺 LFK→oms_gateway.gw_shop(店铺授权挂经销组织层级节点D02.06)',
  shop_type   TINYINT         NOT NULL DEFAULT 1 COMMENT '店铺类型:1=线上店(接入OMS拉单),2=线下门店',
  is_dropship TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '代发店铺标记:0=否,1=是(消费者订单走D07.04转单链路)',
  status      TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=停用',
  create_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version     INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted  TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_dlr_dealer_shop (shop_id),
  KEY idx_dlr_dealer_shop_dealer (dealer_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='经销商店铺关联(D07.01,P2占位,一店铺只归一经销商)';

-- ============================================================================
-- 三、信用（D07.01 FR-03 · 商派缺失自建核心）
-- ============================================================================

-- 3. 信用账户（D07.01 FR-03 · P2占位，高频竞争表必备version;Lua原子占用对齐D04.03预占模式）
CREATE TABLE dlr_credit_account (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NOT NULL COMMENT '货主(冗余自经销商,DEALER_TC)',
  dealer_id        BIGINT UNSIGNED NOT NULL COMMENT '经销商(一商一户) LFK→dlr_dealer',
  credit_limit     DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '授信额度(静态;调整一律OA审批——资金红线FR-03f,调整历史版本化留档)',
  temp_limit       DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '临时额度(超额OA审批产物:金额+有效期)',
  temp_expire_time DATETIME(3)     NULL DEFAULT NULL COMMENT '临时额度有效期(到期自动回收,回收前占用校验计入)',
  occupied         DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '已占用(动态派生缓存:下单占用→审核扣减→发货转应收仍占用→回款核销恢复;流水驱动失效,Redis缓存下单热路径P99≤5ms)',
  overdue          DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '逾期额(应收超账期未核销部分,D08应收台账日终扫描取数)',
  available_cache  DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '可用额度缓存=credit_limit+有效temp_limit-occupied-overdue(派生值;日终守恒对账:授信-Σ占用流水余额-逾期=缓存值,不平告警按流水重建§5.2,禁止人工直改余额)',
  over_policy      TINYINT         NOT NULL DEFAULT 1 COMMENT '超额管控策略:1=拦截(默认,下单直接拒绝,返回可用额/本单额/缺口结构化原因),2=OA审批放行(超额单挂起推审批附信用快照+历史回款,通过后临时额度放行)',
  freeze_threshold DECIMAL(9,4)    NOT NULL DEFAULT 0.1000 COMMENT '冻结阈值(逾期额>授信额度×该占比触发自动冻结新单,默认10%,经销商级可配)',
  freeze_days      INT             NOT NULL DEFAULT 15 COMMENT '冻结逾期天数(逾期>N天触发冻结,默认15)',
  status           TINYINT         NOT NULL DEFAULT 1 COMMENT '账户状态:1=正常,2=冻结(禁新下单,存量在途订单继续履约;回款核销后自动解冻;冻结/解冻事件广播dealer.credit.frozen/unfrozen+审计)',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(占用/释放CAS)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_dlr_credit_account_dealer (dealer_id),
  KEY idx_dlr_credit_account_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='信用账户(D07.01,P2占位,三口径:可用=授信+临时-已占-逾期)';

-- 4. 信用流水（D07.01 FR-03c · P2占位，append-only:无is_deleted/version/update_time,红冲纠错）
-- 镜像 D04.03 inv_freeze_log 预占流水设计(独立流水+余额派生)
CREATE TABLE dlr_credit_txn (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(冗余,DEALER_TC)',
  dealer_id      BIGINT UNSIGNED NOT NULL COMMENT '经销商 LFK→dlr_credit_account',
  txn_type       TINYINT         NOT NULL COMMENT '流水类型(§5.2六种):1=下单预占(占用+订单额),2=释放(订单取消/关闭,占用-订单额),3=审核扣减(预占转正式,额度语义不变),4=转应收(发货生成应收,占用性质标记转应收金额不变——杜绝发货二次占用双计FR-05c),5=回款恢复(D08.03核销事件驱动,占用-核销额),6=逾期登记(日终扫描,逾期额+可用额联动下降)',
  direction      TINYINT         NOT NULL COMMENT '方向:1=占用增加,2=占用减少,3=性质转换(金额不变),4=逾期登记',
  amount         DECIMAL(18,2)   NOT NULL COMMENT '流水金额',
  balance_after  DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '流水后占用余额快照(任意时点重算/对账基础)',
  ref_so_bn      VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '关联B2B销售单号 LFK→dlr_sales_order.sales_order_bn(全链路可追溯)',
  ref_ar_bn      VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '关联应收单号 LFK→oms_finance(D08.01 ar_type=b2b_receivable;应收台账勾稽位——经销商应收台账镜像D06.04八列结构落oms_finance不落本域)',
  idempotent_key VARCHAR(128)    NOT NULL COMMENT '幂等键=(销售单号+动作类型)拼接(IF-D07.01-03幂等契约,同一订单重复回调幂等)',
  operator       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '操作人(系统动作=系统账号名)',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '流水时间(毫秒)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_dlr_credit_txn_key (idempotent_key),
  KEY idx_dlr_credit_txn_dealer (dealer_id, create_time),
  KEY idx_dlr_credit_txn_so (ref_so_bn)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='信用流水(D07.01,P2占位,append-only只增不改不删)';

-- 5. 账期配置（D07.01 FR-03b · P2占位，配置表;权威载体=D10.01 FR-05c货主结算配置位R3,本表为经销域视图化冗余,P2启动可裁剪直接读R3）
CREATE TABLE dlr_credit_period (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(冗余,DEALER_TC)',
  dealer_id      BIGINT UNSIGNED NOT NULL COMMENT '经销商 LFK→dlr_dealer',
  credit_days    INT             NOT NULL DEFAULT 30 COMMENT '账期天数(默认30,经销商级可谈判差异化;落D10.01 settle_config位R3)',
  start_anchor   TINYINT         NOT NULL DEFAULT 1 COMMENT '起算日锚点:1=发货日,2=结算单归档日(可配;到期日=起算日+credit_days)',
  warn_days_json JSON            NULL DEFAULT NULL COMMENT '预警提前天数集(默认[7,3,1]三级,D01.07通道推商务+门户;逾期发生升级通知财务+商务负责人)',
  grace_days     INT             NOT NULL DEFAULT 0 COMMENT '宽限期天数(R3 settle_config扩展组同源)',
  status         TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=历史(变更版本化留档,走OA)',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_dlr_credit_period (dealer_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='账期配置(D07.01,P2占位,视图化R3配置位)';

-- ============================================================================
-- 四、授权（D07.01 FR-04）
-- ============================================================================

-- 6. 产品线授权到店（D07.01 FR-04 · P2占位）
-- ← 商派 dealer.series/series_products/series_endorse/series_endorse_products 四表改造:授权记录为主体+时间窗版本化
CREATE TABLE dlr_product_auth (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(经销商,DEALER_TC)',
  auth_bn        VARCHAR(32)     NOT NULL COMMENT '授权记录号(唯一)',
  dealer_id      BIGINT UNSIGNED NOT NULL COMMENT '授权经销商 LFK→dlr_dealer',
  shop_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '细化店铺(0=经销商全店铺;一店铺只归一经销商dlr_dealer_shop约束) LFK→oms_gateway.gw_shop',
  auth_level     TINYINT         NOT NULL COMMENT '授权粒度:1=品牌级,2=分类级(D04.01分类树节点),3=SKU级(基础物料清单)',
  auth_ref       JSON            NOT NULL COMMENT '授权对象集:品牌级{"brand_ids":[...]}/分类级{"cat_ids":[...]}/SKU级{"bm_ids":[...]}/产品线{"series_id":x,"bm_ids":[...]}(series层去留P2启动按业务定FR-04e;运行期展开SKU集合缓存,校验只查SKU级)',
  delivery_mode  TINYINT         NOT NULL DEFAULT 1 COMMENT '发货方式:1=自发(凯淳发货至经销商,买断转售),2=代发(经销商店铺消费者订单凯淳直发,D07.04转单场景);模式切换=新记录带切换时间窗(切换日前订单按旧模式履约,继承商派时间范围语义)',
  cargo_owner_id BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货权方货主(代发时必填:品牌方BRAND_CONSIGN/贸易公司DEALER_TC) LFK→oms_org.org_owner(D07.04 §5.1行货权方判定依据)',
  start_time     DATETIME(3)     NOT NULL COMMENT '授权时间窗起',
  end_time       DATETIME(3)     NOT NULL COMMENT '授权时间窗止(到期自动失效订货拦截,续期=新记录历史留档;事件dealer.endorse.expired广播)',
  auth_version   INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '版本(续期/切换+1,历史留档不可改删)',
  status         TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=已失效(到期/被替换),3=已终止(经销商终止联动)',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version        INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_dlr_product_auth_bn (auth_bn),
  KEY idx_dlr_product_auth_dealer (dealer_id, shop_id, status, end_time),
  KEY idx_dlr_product_auth_mode (delivery_mode, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='产品线授权到店(D07.01,P2占位,三级粒度×时间窗×自发/代发)';

-- ============================================================================
-- 五、交易（D07.02）
-- ============================================================================

-- 7. B2B销售单头（D07.02 FR-02 · P2占位，单据类禁软删）
-- 销售单管商务协议(价格/账期/信用),履约订单管物流执行——显式两层分离,一对多分批关联
CREATE TABLE dlr_sales_order (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id            BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id             BIGINT UNSIGNED NOT NULL COMMENT '货主(经销商,DEALER_TC;转履约后履约订单货主=凯淳买断-自发场景)',
  sales_order_bn       VARCHAR(32)     NOT NULL COMMENT '销售单号(唯一,BS{YYYYMMDD}{5位},Redis发号防遍历)',
  dealer_id            BIGINT UNSIGNED NOT NULL COMMENT '经销商 LFK→dlr_dealer',
  channel              TINYINT         NOT NULL DEFAULT 1 COMMENT '订货通道:1=门户自助(主通道,门户写操作按D10.04 FR-01a升版本R7),2=业务员代下单(独立授权点+客户确认凭证附件,全程审计),3=批量导入(D01.06异步,取价一律系统重算不采信外部价格——防篡改红线,错误行输出报告不阻塞正确行),4=EDI直连(P2内预留占位,经D02.07网关,幂等键=经销商侧单号)',
  pay_mode             TINYINT         NOT NULL DEFAULT 1 COMMENT '支付模式:1=账期赊销(默认,联动信用),2=先款后货,3=预存款抵扣(镜像D06.04 §5.4预付款抵扣为收款侧)(业务假设待P2确认)',
  amount_caliber       TINYINT         NOT NULL DEFAULT 1 COMMENT '转履约金额口径:1=批发价口径(默认,订单金额=批发价直接驱动应收),2=0元内部口径(订单0元走履约,应收按销售单批发价独立挂账,订单金额与应收解耦)——系统级配置选定后全局一致,防双挂校验FR-04b',
  total_amount         DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '头金额=Σ行金额(2位小数)',
  currency             CHAR(3)         NOT NULL DEFAULT 'CNY' COMMENT '币种(默认CNY,多币种P2内预留字段不实现)',
  salesman_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '业务员 LFK→oms_org.org_account(业绩维度)',
  sales_org_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '销售团队 LFK→oms_org.org_node',
  receiver_json        JSON            NULL DEFAULT NULL COMMENT '收货地址快照(引用经销商档案地址集)',
  expect_delivery_date DATE            NULL DEFAULT NULL COMMENT '期望发货日(交付要求;缺货风险行提示不可达)',
  allow_split          TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '分批许可:0=整单一次转,1=允许分批转履约(SC-05:现货先发,余量待采购到货续转)',
  status               TINYINT         NOT NULL DEFAULT 1 COMMENT '状态机:1=草稿(不占信用),2=待审核(提交即占用CreditService.occupy),3=超额审批中(挂起推OA附信用快照,已按含临时额度预占不重复占用),4=已审核(占用转正式confirm;变更走变更单新版本超阈值OA,已转单部分不可变更),5=部分转单,6=全部转单,7=部分发货,8=已完成(全部发货+应收挂账),9=已关闭(信用释放联动)',
  close_reason         TINYINT         NOT NULL DEFAULT 0 COMMENT '关闭原因:0=无,1=经销商取消,2=凯淳拒绝,3=超时未审核自动关闭,4=OA驳回(已审核取消需商务确认+OA涉及备货;已发货部分不可取消走B2B退货冲减)',
  convert_status       TINYINT         NOT NULL DEFAULT 1 COMMENT '转单状态(商派convert_status枚举语义继承):1=unconvert未转,2=splitting分批中,3=converted已转,4=fail转失败,5=needless无需转',
  oa_instance_id       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '超额审批OA实例引用(D10.05,挂起场景;回调按实例号幂等)',
  credit_snapshot_json JSON            NULL DEFAULT NULL COMMENT '提交时信用快照(可用额/占用/本单额;OA审批附件+审计依据)',
  source               VARCHAR(16)     NOT NULL DEFAULT 'local' COMMENT '数据来源:local=手工,portal=门户,import=导入,edi=EDI,migration=迁移',
  create_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version              INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(状态机CAS)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_dlr_sales_order_bn (sales_order_bn),
  KEY idx_dlr_sales_order_dealer (dealer_id, status),
  KEY idx_dlr_sales_order_status (status, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='B2B销售单头(D07.02,P2占位,订货协议单据)';

-- 8. B2B销售单行（D07.02 FR-02 · P2占位，单据类禁软删）
CREATE TABLE dlr_sales_order_item (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(冗余自单头)',
  sales_order_id   BIGINT UNSIGNED NOT NULL COMMENT '销售单头 LFK→dlr_sales_order',
  bm_id            BIGINT UNSIGNED NOT NULL COMMENT '基础物料 LFK→oms_stock.inv_material',
  qty              INT             NOT NULL DEFAULT 0 COMMENT '订货数量(>0)',
  price            DECIMAL(18,4)   NOT NULL DEFAULT 0 COMMENT '批发价快照(D07.03 PriceService.quote结果固化;价格快照=应收/结算/金蝶全链路唯一金额源头,禁二次取价FR-07a;折让/补差走应收红字调整不改快照)',
  price_version_id BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '价格表版本 LFK→dlr_price_list(随单永久可追溯,历史订单价格精确回放)',
  price_hit_json   JSON            NULL DEFAULT NULL COMMENT '取价命中快照:{"hit_level":"special|contract|level","ladder_band":"≥100","list_id":x}(D07.03 FR-05c返回固化;优先级:特批>合同>等级)',
  amount           DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '行金额=qty×price',
  tax_rate         DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '税率快照(随价格版本;含税价挂应收,价税分离供金蝶D08.06)',
  moq_check        TINYINT         NOT NULL DEFAULT 1 COMMENT '起订量校验结果:1=通过,2=低于起订量拦截,3=非整箱倍数拦截(MOQ_*原因码,行级拦截可剔行重提)',
  endorse_ref      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '授权记录引用 LFK→dlr_product_auth(AUTH_SKU/AUTH_TIME/AUTH_SHOP/AUTH_MODE四类拦截留痕)',
  converted_qty    INT             NOT NULL DEFAULT 0 COMMENT '已转履约量(守恒校验:Σ历史已转量+本批量≤qty,违反拒绝;分批关系经dlr_transfer_order行级溯源,幂等键=(sales_order_id,批次号))',
  status           TINYINT         NOT NULL DEFAULT 1 COMMENT '行状态:1=正常,2=已关闭(行级取消),3=已转完',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  KEY idx_dlr_sales_order_item_so (sales_order_id),
  KEY idx_dlr_sales_order_item_bm (bm_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='B2B销售单行(D07.02,P2占位,批发价快照固化)';

-- ============================================================================
-- 六、价格（D07.03）
-- ============================================================================

-- 10. 价格表（D07.03 FR-02/03 · P2占位，头行合一:一行=表头组×SKU,阶梯JSON;表组为审批与生效原子单位）
-- ← 商派 dealer.goods_price 改造:单维→等级×区域×时间窗×数量阶梯四维+版本治理
CREATE TABLE dlr_price_list (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(配置类免填=0;货权方专属价场景P2定)',
  list_group_bn    VARCHAR(32)     NOT NULL COMMENT '价格表组号(表头标识:名称/类型/适用范围承载于组,同组多version_no)',
  list_name        VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '价格表名称',
  price_type       VARCHAR(32)     NOT NULL COMMENT '价格类型 LFK→dlr_price_type.type_code(dealer_price/wholesale_price/special_price,三类共用结构与取价引擎)',
  version_no       INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '版本号(同list_group_bn递增)',
  status           TINYINT         NOT NULL DEFAULT 1 COMMENT '版本状态:1=草稿(可改),2=审批中,3=待生效,4=生效中(不可变,纠错=新版本+OA),5=已失效(永久留档);同维度键任意时刻至多一份生效中(时间轴不重叠发布期强制校验);定时任务按生效日原子切换(旧失效+新生效同事务)',
  level_scope      JSON            NULL DEFAULT NULL COMMENT '适用等级集(含通配档"通用";同维命中多条时精确>通配,并列取版本新者,歧义发布期拦截)',
  region_scope     JSON            NULL DEFAULT NULL COMMENT '适用区域集(含通配档"全国";精确>通配)',
  effect_from      DATETIME(3)     NOT NULL COMMENT '生效时间窗起(断档允许但发布页提示,断档期取价=PRICE_MISSING拦截)',
  effect_to        DATETIME(3)     NOT NULL COMMENT '生效时间窗止',
  dealer_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '特批/合同价精确键经销商(0=等级默认价) LFK→dlr_dealer(合同价=限定单商的特批价常态化形态,共用结构FR-05b)',
  bm_id            BIGINT UNSIGNED NOT NULL COMMENT '基础物料(SKU级最小粒度;分类/品牌级批量生成后落SKU行,取价只查SKU级避免运行期层级回溯) LFK→oms_stock.inv_material',
  ladder_json      JSON            NOT NULL COMMENT '数量阶梯:[{"min":1,"max":100,"price":95.00},{"min":100,"max":500,"discount":0.95}](区间左闭右开,同SKU内不重叠不留缝校验;按订单行数量落档,不跨行/跨单合并FR-05d)',
  price_tax        DECIMAL(18,4)   NOT NULL DEFAULT 0 COMMENT '含税价(应收按含税挂账)',
  price_net        DECIMAL(18,4)   NOT NULL DEFAULT 0 COMMENT '不含税价(毛利分析口径D11)',
  tax_rate         DECIMAL(9,4)    NOT NULL DEFAULT 0 COMMENT '税率(引用物料开票属性快照随版本)',
  cost_ref         DECIMAL(18,4)   NOT NULL DEFAULT 0 COMMENT '成本参考价(D04.07口径;最高敏感字段D10.03字段级权限:仅商务/财务角色,经销商门户只见本商成交价永不见成本与他人价格)',
  below_cost_flag  TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '低于成本标记(审批加签依据:财务总监强制加签FR-06b)',
  qty_limit        INT             NOT NULL DEFAULT 0 COMMENT '特批数量上限(0=不限;累计成交达上限自动失效,超额回落下一优先级,失效不追溯已成交订单快照保护FR-04c)',
  sold_qty         INT             NOT NULL DEFAULT 0 COMMENT '特批累计成交(成交回写,日终对账兜底最终一致)',
  oa_instance_id   VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '审批OA实例引用(发布/变更一律OA,复用D10.05「改价」审批类型R5;回调按实例号幂等)',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_dlr_price_list (list_group_bn, version_no, bm_id, dealer_id),
  KEY idx_dlr_price_list_quote (price_type, bm_id, dealer_id, status, effect_from),
  KEY idx_dlr_price_list_group (list_group_bn, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='价格表(D07.03,P2占位,四维:等级×区域×时间窗×数量阶梯;百万行/版本仅生效版进Redis缓存quote P99≤10ms)';

-- 11. 价格变更审批（D07.03 FR-06 · P2占位，单据类禁软删;SRS §6.2 b2b_price_version_log语义并入action列,append-only留痕）
CREATE TABLE dlr_price_change (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id           BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(配置类免填=0)',
  change_bn          VARCHAR(32)     NOT NULL COMMENT '变更单号(唯一)',
  list_group_bn      VARCHAR(32)     NOT NULL COMMENT '目标价格表组 LFK→dlr_price_list',
  target_version_no  INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '目标版本号',
  action             TINYINT         NOT NULL COMMENT '动作:1=发布,2=变更,3=提前失效,4=版本切换,5=特批价申请,6=合同价录入(全量OA资金条款红线FR-06a)',
  diff_snapshot_json JSON            NULL DEFAULT NULL COMMENT '差异对比快照(新版本vs现行:调价SKU数/平均涨跌幅/低于成本清单——审批附件同源)',
  approval_level     TINYINT         NOT NULL DEFAULT 1 COMMENT '审批分级:1=销售总监(常规调价),2=财务总监加签(低于成本价/涨跌幅超阈值默认±15%可配),3=总经理(战略经销商合同价)',
  oa_instance_id     VARCHAR(64)     NOT NULL DEFAULT '' COMMENT 'OA实例号(防重幂等,审批回调驱动版本状态迁移)',
  approval_status    TINYINT         NOT NULL DEFAULT 1 COMMENT '审批状态:1=待审,2=通过,3=驳回',
  operator           VARCHAR(64)     NOT NULL COMMENT '发起人',
  action_time        DATETIME(3)     NOT NULL COMMENT '动作时间(append-only不可改删)',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_dlr_price_change_bn (change_bn),
  KEY idx_dlr_price_change_oa (oa_instance_id),
  KEY idx_dlr_price_change_list (list_group_bn, action_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='价格变更审批(D07.03,P2占位,全量OA)';

-- ============================================================================
-- 七、转单与货权拆分（D07.04）
-- ============================================================================

-- 12. 转单单据头（D07.04 FR-01 · P2占位，单据类禁软删）
-- 转单=D03.04 owner策略业务化+D03.01标准转入通道,本表仅映射跟踪层不落第二套订单引擎
-- ← 商派 dealer.platform_orders 转单(confirmOrder按贸易公司betc分组batchCreateErpOrders)改造:货权主体显式货主档案化
CREATE TABLE dlr_transfer_order (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id           BIGINT UNSIGNED NOT NULL COMMENT '货主(经销商,DEALER_TC)',
  transfer_bn        VARCHAR(32)     NOT NULL COMMENT '转单号(唯一,Redis发号)',
  source_type        TINYINT         NOT NULL COMMENT '源单类型:1=B2B销售单(自发转履约/代发直发),2=平台单(经销商店铺消费者订单,代发场景D03.01接入时判定dropship_mode/cargo_owner_id字段位)',
  source_bn          VARCHAR(32)     NOT NULL COMMENT '源单号(dlr_sales_order.sales_order_bn或ord_order.order_bn)',
  dealer_id          BIGINT UNSIGNED NOT NULL COMMENT '经销商 LFK→dlr_dealer',
  cargo_owner_id     BIGINT UNSIGNED NOT NULL COMMENT '货权方货主(owner策略分组键:BRAND_CONSIGN品牌方代发/DEALER_TC贸易公司/凯淳买断=自发组) LFK→oms_org.org_owner;代发库存按货权方三元行预占扣减(R4),凯淳买断行零流水(货不动凯淳账SC-02)',
  batch_no           INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '批次号(分批转单;(source_bn,cargo_owner_id,batch_no)幂等键)',
  transfer_status    TINYINT         NOT NULL DEFAULT 1 COMMENT '转单状态(商派convert_status枚举语义继承):1=unconvert未转,2=splitting拆分中,3=converted已转,4=fail转失败,5=needless无需转',
  fulfill_order_ids  JSON            NULL DEFAULT NULL COMMENT '货权方履约单ID集合(1:N映射 LFK→oms_order.ord_order;经D03.01标准转入通道创建)',
  split_trace_json   JSON            NULL DEFAULT NULL COMMENT '行级溯源与守恒登记(源单行→履约单行映射,对齐D03.04 split_trace;组级部分成功时「分配+挂起=余量」守恒口径显式登记防丢行;到货续拆D03.04 FR-06c复用)',
  channel_type       TINYINT         NOT NULL DEFAULT 1 COMMENT '履约通道:1=凯淳仓代发(货存凯淳仓常规推仓通天晓,出库扣货权方三元行),2=货权方仓,3=供应商直发(2/3=dropship通道,发货指令下发货权方+物流回传对接,D09适配层扩展P2实现;dropship标记复用D03.04 channel策略R7)',
  fail_code          VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '失败原因码(D03.04错误码族复用;NO_STOCK组级挂起进缺货流程D03.09,group_independent=true组间独立不阻断其他组SC-05)',
  fail_detail        VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '失败明细(转单工作台人工介入:改货权方/改仓/协商退款联动)',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version            INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(转单CAS)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_dlr_transfer_order_bn (transfer_bn),
  UNIQUE KEY uk_dlr_transfer_order_idem (source_bn, cargo_owner_id, batch_no),
  KEY idx_dlr_transfer_order_dealer (dealer_id, transfer_status),
  KEY idx_dlr_transfer_order_status (transfer_status, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='转单单据头(D07.04,P2占位,代发货权分组映射跟踪层)';

-- 13. 转单单据行（D07.04 FR-01 · P2占位，单据类禁软删）
CREATE TABLE dlr_transfer_order_item (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id           BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(冗余自单头)',
  transfer_id         BIGINT UNSIGNED NOT NULL COMMENT '转单头 LFK→dlr_transfer_order',
  source_item_ref     BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '源单行引用(dlr_sales_order_item.id或ord_order_item.id,行级溯源)',
  bm_id               BIGINT UNSIGNED NOT NULL COMMENT '基础物料 LFK→oms_stock.inv_material',
  qty                 INT             NOT NULL DEFAULT 0 COMMENT '本批转单数量',
  endorse_ref         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '授权记录引用 LFK→dlr_product_auth(无授权记录=AUTH_MISSING拦截,禁止无授权代发§5.1;结算与追溯依据)',
  dropship_flag       TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '直发标记:0=否(凯淳仓代发),1=是(R7推仓通道分流依据,order.split.completed事件组属性携带)',
  fulfill_order_item_id BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '履约订单行映射 LFK→oms_order.ord_order_item(转成功后回填)',
  status              TINYINT         NOT NULL DEFAULT 1 COMMENT '行状态:1=待转,2=已转,3=挂起(NO_STOCK待续拆,余量保留),4=失败,5=已取消(协商退款联动D07.02行级冲减)',
  create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  KEY idx_dlr_transfer_order_item_tid (transfer_id),
  KEY idx_dlr_transfer_order_item_src (source_item_ref)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='转单单据行(D07.04,P2占位,全链路追溯:源单行→履约单→发货单→台账行)';

-- 14. 代发双向结算台账（D07.04 FR-04 · P2占位，append-only:无is_deleted/version/update_time,红冲纠错）
-- 镜像D04.05借调台账(inv_lend_ledger)模式R8:settle_month/settle_status回写位+双向勾稽+月度差额校验关账
CREATE TABLE dlr_dropship_ledger (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(=cargo_owner_id冗余,台账按货权方维度)',
  cargo_owner_id    BIGINT UNSIGNED NOT NULL COMMENT '货权方货主(双向维度①) LFK→oms_org.org_owner',
  dealer_id         BIGINT UNSIGNED NOT NULL COMMENT '经销商(双向维度②) LFK→dlr_dealer',
  period            CHAR(7)         NOT NULL COMMENT '账务期间(YYYY-MM,月度快照维度)',
  object_type       TINYINT         NOT NULL COMMENT '流水类型:1=代发出库(凯淳应付货款=num×结算价),2=代发服务费(货权方应付凯淳,合同费率/件或货值×费率,D08.02服务费引擎复用),3=经销商侧代发应收(=num×批发价快照,入oms_finance应收台账),4=调整(红冲)',
  direction         TINYINT         NOT NULL COMMENT '方向:1=凯淳应付,2=凯淳应收(append-only红冲纠错)',
  num               INT             NOT NULL DEFAULT 0 COMMENT '代发数量',
  settle_price_type TINYINT         NOT NULL DEFAULT 1 COMMENT '结算价类型:1=内部购销价,2=成本价,3=免费(D04.05 settle_price_type枚举复用)',
  unit_price        DECIMAL(18,4)   NOT NULL DEFAULT 0 COMMENT '结算单价(货权方侧)/批发价快照(经销商侧)',
  amount            DECIMAL(18,2)   NOT NULL DEFAULT 0 COMMENT '流水金额=num×unit_price',
  ref_delivery_id   BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '关联发货单 LFK→oms_order.ord_delivery(逐单勾稽依据;order.delivery.shipped事件驱动写入,重复投递不双写幂等)',
  ref_transfer_bn   VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '关联转单号 LFK→dlr_transfer_order',
  settle_month      CHAR(7)         NOT NULL DEFAULT '' COMMENT '结算归属月(D08.02归档回写位,R8借调台账同款;净额=Σ应付货款-Σ应收服务费→D08.02货权方结算单既有五要素结构不新建单据类型)',
  settle_status     TINYINT         NOT NULL DEFAULT 0 COMMENT '结算状态:0=未结算,1=已入结算单,2=已归档(D08.02回写;镜像双向勾稽:凯淳侧台账行↔货权方结算单明细金额相等方向相反,D08.02 §5.2校验复用)',
  snapshot_json     JSON            NULL DEFAULT NULL COMMENT '月度快照行(期初/增加/已结/期末+差额校验=0才许关账,不平阻断+定位工单,D06.04 §5.2算法)',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '流水时间',
  PRIMARY KEY (id),
  KEY idx_dlr_dropship_ledger_owner (cargo_owner_id, period, settle_status),
  KEY idx_dlr_dropship_ledger_dealer (dealer_id, period),
  KEY idx_dlr_dropship_ledger_ref (ref_delivery_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='代发双向结算台账(D07.04,P2占位,双本账:货权方侧+经销商侧,联动fin_settlement)';

-- ============================================================================
-- 八、初始字典数据（P2 启动时执行）
-- ============================================================================

INSERT INTO dlr_price_type (tenant_id, type_code, type_name, tax_mode, status) VALUES
(1, 'dealer_price',    '经销价', 1, 1),
(1, 'wholesale_price', '批发价', 1, 1),
(1, 'special_price',   '特批价', 1, 1);

-- ============================================================================
-- 脚本结束 · 共 14 张表 · 全部 P2 建库占位（表结构随 P2 启动细化，只增列不改契约位）
-- 自查: 括号/逗号/分号配对、COMMENT内无未转义单引号、JSON默认值均为NULL或显式提供、
--       保留字规避(等级列用dealer_level非level、无rank/system/groups)、流水类无软删/乐观锁例外已体现
-- ============================================================================
