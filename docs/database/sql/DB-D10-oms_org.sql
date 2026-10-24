-- ============================================================================
-- DB-D10 组织权限域建表脚本（oms_org + oms_audit）
-- 文档编号: DB-D10 · 版本 V1.0 · 2026-10-24 · MySQL 8.0 可执行 DDL
-- 上游契约: DB-00 数据库设计总册（schema=oms_org 前缀 org_ / 审计独立 schema=oms_audit 前缀 aud_ /
--           公共字段 / 敏感字段 _enc+_hash / 不建物理外键 / 流水日志按月分表）
-- 需求依据: SRS-D10.01 ~ SRS-D10.06 §6 数据字段章节
-- ----------------------------------------------------------------------------
-- 执行顺序:
--   1) CREATE DATABASE oms_org / oms_audit
--   2) 组织货主族: org_node / org_node_relation / org_owner / org_owner_contract
--      / org_owner_settle_config / org_shop_owner_transfer
--   3) 租户账户族: org_tenant / org_account / org_account_credential / org_session
--      / org_role / org_role_perm / org_account_role / org_idp_config
--   4) 权限族: org_perm_point / org_data_permission / org_filterable_entity
--      / org_field_perm / org_perm_violation
--   5) 门户族: org_portal_account / org_portal_message / org_portal_notify_pref
--      / org_portal_export_log / org_portal_read_log
--   6) 审批族: org_approval_scene / org_approval_threshold / org_approval_instance
--      / org_oa_callback_log
--   7) oms_audit: aud_operation_log / aud_data_access_log / aud_entity_registry
--      / aud_hash_anchor / aud_retention_policy / aud_destroy_log
--   8) 初始字典数据 INSERT: 组织根节点 / owner_KC / tenant_KC / 系统角色 /
--      权限点样例 / 审批场景31条 / 阈值默认 / 保留策略
-- 依赖: 仅本两 schema；跨域为逻辑外键 LFK（应用层校验），不建物理外键
-- 分表约定: aud_operation_log / aud_data_access_log / org_oa_callback_log /
--           org_portal_read_log 按月分表 _YYYYMM，本脚本为结构基线表，
--           月度表由调度任务 CREATE TABLE ... LIKE 创建
-- 权限隔离: oms_audit 应用账号仅授 INSERT/SELECT（防篡改第一层, D10.06 FR-03d）
-- 命名/类型基线: 见 DB-00 §2/§6；utf8mb4 / utf8mb4_0900_ai_ci / InnoDB
-- ============================================================================

CREATE DATABASE IF NOT EXISTS oms_org DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS oms_audit DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE oms_org;

-- ============================================================================
-- 一、组织与货主族（D10.01）
-- ============================================================================

-- 1. 组织树节点（D10.01 · P0）← 商派 organization cos树改造：双树合一+类型枚举
CREATE TABLE org_node (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id   BIGINT UNSIGNED NOT NULL COMMENT '租户ID(内部组织树固定=1;P2经销树按租户隔离预留)',
  org_code    VARCHAR(64)     NOT NULL COMMENT '节点编码,全局唯一,创建后不可改',
  org_name    VARCHAR(128)    NOT NULL COMMENT '节点名称,同父下不重名(应用层校验)',
  node_type   VARCHAR(32)     NOT NULL COMMENT '节点类型:group=集团(唯一根KC_ROOT),brand=品牌,owner_co=货主公司,shop=店铺,warehouse=仓,dept=部门(行政,不参与单据归属),reserved_dealer=经销商(P2预留)',
  parent_id   BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '父节点ID(0=根;严格树非DAG,层级<=8) LFK->org_node',
  cat_path    VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '节点路径冗余(,根ID,...,本节点ID,;写时补全,子树查询LIKE ,{id},%前缀索引)',
  node_level  TINYINT         NOT NULL DEFAULT 1 COMMENT '层级(根=1,<=8)',
  ref_id      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '关联业务档案:shop->oms_gateway.gw_shop.shop_id;warehouse->oms_fulfill.ful_branch.branch_id;其余=0',
  sort_no     INT             NOT NULL DEFAULT 0 COMMENT '同级排序',
  status      TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=停用(有子节点或生效关联禁止停用;停用后授权选择器置灰)',
  remark      VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '备注',
  source      VARCHAR(16)     NOT NULL DEFAULT 'local' COMMENT '数据来源:local=手工,api=自动,import=导入,migration=迁移',
  create_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version     INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted  TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是(仅无关联无子节点的停用节点可删;根节点与有货主的货主公司节点永不可删)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_node_code (org_code),
  KEY idx_org_node_parent (parent_id),
  KEY idx_org_node_path (cat_path),
  KEY idx_org_node_type (node_type, status),
  KEY idx_org_node_ref (ref_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='组织树节点(D10.01,P0,一棵带类型枚举的统一组织树)';

-- 2. 节点x业务对象关联（D10.01 · P0，关系表：无软删无version）← 商派 cos_ops 逗号串拆行改造
CREATE TABLE org_node_relation (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id   BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  node_id     BIGINT UNSIGNED NOT NULL COMMENT '组织节点 LFK->org_node',
  rel_type    VARCHAR(32)     NOT NULL COMMENT '关联类型:shop=店铺档案,branch=仓库档案,owner=货主档案,branch_owner=仓可服务货主(node_id=仓节点,rel_id=owner_id,启用后该仓可为该货主开立三元记账行),tenant_owner=租户关联货主(node_id=0时rel_type内tenant用ext)',
  rel_id      BIGINT UNSIGNED NOT NULL COMMENT '关联对象ID(gw_shop.shop_id/ful_branch.branch_id/org_owner.id)',
  is_primary  TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '是否主关联:0=否,1=是(货主<->货主公司节点/店铺<->店铺节点一对一约束用)',
  status      TINYINT         NOT NULL DEFAULT 1 COMMENT '关系状态:1=启用,2=停用',
  create_op   VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '建立人',
  create_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_node_relation (node_id, rel_type, rel_id),
  KEY idx_org_node_relation_rel (rel_type, rel_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='节点x业务对象关联(D10.01,P0,含仓-货主服务关系branch_owner)';

-- 3. 货主档案（D10.01 · P0）★货主维度契约定义源（SRS-00 §4.4，三元记账键第三元权威来源）
CREATE TABLE org_owner (
  id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键(全域owner_id外键来源)',
  tenant_id             BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_code            VARCHAR(64)     NOT NULL COMMENT '货主编码,全局唯一,创建后不可改',
  owner_name            VARCHAR(128)    NOT NULL COMMENT '货主名称',
  owner_type            VARCHAR(32)     NOT NULL COMMENT '货主类型(SRS-00契约):KC_BUYOUT=凯淳买断,BRAND_CONSIGN=品牌代销,DEALER_TC=经销商贸易公司(P2预留置灰);创建后不可改(改类型=资产转移走新货主)',
  org_node_id           BIGINT UNSIGNED NOT NULL COMMENT '归属货主公司节点(node_type=owner_co,必填) LFK->org_node',
  tax_no                VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '统一社会信用代码(格式校验)',
  contact_name          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '联系人姓名',
  contact_phone_enc     VARBINARY(256)  NULL DEFAULT NULL COMMENT '联系人电话密文(D01.05信封加密,界面脱敏展示)',
  contact_phone_hash    CHAR(64)        NOT NULL DEFAULT '' COMMENT '电话HMAC盲索引(等值检索用)',
  status                TINYINT         NOT NULL DEFAULT 1 COMMENT '生命周期:1=合作中,2=暂停(新单停止/存量继续/门户只读),3=终止(不可逆,数据只读);暂停/终止走OA审批(scene=owner_status_change)',
  contract_id_cur       BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '当前生效合同(至多一份生效中) LFK->org_owner_contract',
  kingdee_subject_code  VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '金蝶核算主体编码映射(EF-D10.01-02,D08.06推凭证用,P1)',
  terminate_check_json  JSON            NULL DEFAULT NULL COMMENT '终止前置校验未决清单快照(库存五口径/未完结订单/未闭环售后/未归档结算/在途审批,FR-06c阻断式清单留档)',
  remark                VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '备注',
  source                VARCHAR(16)     NOT NULL DEFAULT 'local' COMMENT '数据来源:local=手工,api=自动,import=导入,migration=迁移',
  create_time           DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time           DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version               INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted            TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_owner_code (owner_code),
  KEY idx_org_owner_node (org_node_id),
  KEY idx_org_owner_type (owner_type, status),
  KEY idx_org_owner_phone_hash (contact_phone_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='货主档案(D10.01,P0,凯淳新增一等公民,商派无owner实体)';

-- 4. 货主合同（D10.01 · P0）
CREATE TABLE org_owner_contract (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NOT NULL COMMENT '货主 LFK->org_owner',
  contract_no    VARCHAR(64)     NOT NULL COMMENT '合同编号,全局唯一',
  party_a        VARCHAR(128)    NOT NULL COMMENT '甲方(凯淳主体)',
  party_b        VARCHAR(128)    NOT NULL COMMENT '乙方(品牌方主体)',
  start_date     DATE            NOT NULL COMMENT '合同起始日',
  end_date       DATE            NOT NULL COMMENT '合同到期日(到期预警60/30/7天推企微通知D01.07)',
  mode_snapshot  VARCHAR(32)     NOT NULL COMMENT '合作模式快照=签约时货主类型:KC_BUYOUT/BRAND_CONSIGN/DEALER_TC',
  attachment_ref JSON            NULL DEFAULT NULL COMMENT '附件(扫描件OSS加密存储引用数组,D01.05策略)',
  status         TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=草稿,2=生效中,3=已到期,4=已作废(同货主至多一份生效中;续签=新合同+旧合同到期归档)',
  source         VARCHAR(16)     NOT NULL DEFAULT 'local' COMMENT '来源:local=手工,import=导入,migration=迁移',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version        INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_owner_contract_no (contract_no),
  KEY idx_org_owner_contract_owner (owner_id, status),
  KEY idx_org_owner_contract_end (end_date)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='货主合同(D10.01,P0,附件仅作法律凭证,结构化配置落settle_config)';

-- 5. 货主结算配置·版本化（D10.01 · P0，D08.02/D08.03 配置唯一入口）
CREATE TABLE org_owner_settle_config (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id           BIGINT UNSIGNED NOT NULL COMMENT '货主 LFK->org_owner',
  config_version     INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '配置版本号(变更+1,历史版本只读留档;结算单生成时快照当时版本)',
  settle_period_type TINYINT         NOT NULL DEFAULT 1 COMMENT '结算周期:1=月结,2=半月结,3=周结',
  settle_anchor      VARCHAR(32)     NOT NULL DEFAULT 'month_end' COMMENT '结账日锚点:month_end=自然月末,custom_day=自定义日,half=15日+月末,week_sunday=周日制',
  settle_anchor_day  TINYINT         NOT NULL DEFAULT 0 COMMENT '自定义结账日(settle_anchor=custom_day时1-28)',
  confirm_days       INT             NOT NULL DEFAULT 10 COMMENT '品牌方确认期限(天,超期催办不视同确认,D08.02 FR-05d)',
  grace_days         INT             NOT NULL DEFAULT 3 COMMENT '宽限期(天,跨期延迟单据补录窗口)',
  payment_days       INT             NOT NULL DEFAULT 30 COMMENT '收付款账期天数(可谈判差异化,D08.03 FR-06a)',
  payment_start_basis TINYINT        NOT NULL DEFAULT 1 COMMENT '账期起算日:1=结算单归档日,2=品牌方确认日',
  service_fee_json   JSON            NULL DEFAULT NULL COMMENT '服务费条款参数(费率/阶梯/计费基数口径:paid=客户实付,include_platform=含平台承担;D08.02 ServiceFeeService消费)',
  status             TINYINT         NOT NULL DEFAULT 1 COMMENT '版本状态:1=生效,2=历史(同货主仅一个生效版)',
  approval_bn        VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '变更审批单号(资金条款OA红线scene=settle_config_change) LFK->org_approval_instance',
  effective_time     DATETIME(3)     NULL DEFAULT NULL COMMENT '生效时间(变更只影响未来周期,已生成结算单不重算)',
  operator           VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '配置人',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted         TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_owner_settle_config (owner_id, config_version),
  KEY idx_org_owner_settle_config_status (owner_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='货主结算配置版本化(D10.01,P0,凯淳新增:商派配置散落无版本)';

-- 6. 店铺换货主申请单（D10.01 · P0，单据类无软删）凯淳原创：资产转移
CREATE TABLE org_shop_owner_transfer (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  transfer_bn       VARCHAR(32)     NOT NULL COMMENT '申请单号,唯一(bas_seq发号ST+日期+序列)',
  shop_id           BIGINT UNSIGNED NOT NULL COMMENT '店铺 LFK->oms_gateway.gw_shop',
  from_owner_id     BIGINT UNSIGNED NOT NULL COMMENT '原货主(须状态=合作中) LFK->org_owner',
  to_owner_id       BIGINT UNSIGNED NOT NULL COMMENT '目标货主(须状态=合作中) LFK->org_owner',
  reason            VARCHAR(512)    NOT NULL COMMENT '换货主原因(必填)',
  impact_snapshot   JSON            NOT NULL COMMENT '影响面清单快照{unfinished_orders,stock_balance,unsettled_amount,inflight_approvals}(申请时+执行前双快照,偏差>阈值中止重审)',
  approval_status   TINYINT         NOT NULL DEFAULT 0 COMMENT '审批状态:0=待发起,1=审批中,2=通过,3=驳回',
  approval_bn       VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '审批单号(scene=shop_owner_transfer全量必审) LFK->org_approval_instance',
  status            TINYINT         NOT NULL DEFAULT 1 COMMENT '单据状态:1=草稿,2=审批中,3=执行中,4=完成,5=关闭(驳回/撤销);执行以transfer_bn CAS防并发双执行,Saga可补偿',
  execute_time      DATETIME(3)     NULL DEFAULT NULL COMMENT '执行完成时间(历史单据保留原owner_id,新单切新货主,库存走D04.05货权转移,应收走D08分期切账)',
  applicant         VARCHAR(64)     NOT NULL COMMENT '发起人',
  source            VARCHAR(16)     NOT NULL DEFAULT 'local' COMMENT '来源:local=手工,migration=迁移',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_shop_owner_transfer_bn (transfer_bn),
  KEY idx_org_shop_owner_transfer_shop (shop_id, status),
  KEY idx_org_shop_owner_transfer_owner (from_owner_id, to_owner_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='店铺换货主申请单(D10.01,P0,资产转移,单据类无软删)';

-- ============================================================================
-- 二、租户账户族（D10.02）
-- ============================================================================

-- 7. 租户档案（D10.02 · P0，配置表 owner_id 免填）
CREATE TABLE org_tenant (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键(全域tenant_id来源;内部租户固定=1)',
  tenant_code      VARCHAR(64)     NOT NULL COMMENT '租户编码,全局唯一(内部租户=KC)',
  tenant_name      VARCHAR(128)    NOT NULL COMMENT '租户名称',
  tenant_type      VARCHAR(16)     NOT NULL DEFAULT 'external' COMMENT '租户类型:internal=内部(凯淳员工,全系统唯一,永不可禁用),external=外部品牌方,supplier=供应商门户(P2预留)',
  owner_scope_json JSON            NOT NULL COMMENT '关联货主集[owner_id,...](外部租户<->货主1..n;D10.03 FR-06a getOwnerScope唯一来源,门户侧不可放宽)',
  contact_name     VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '联系人',
  contact_phone_enc VARBINARY(256) NULL DEFAULT NULL COMMENT '联系电话密文(D01.05)',
  contact_phone_hash CHAR(64)      NOT NULL DEFAULT '' COMMENT '电话HMAC盲索引',
  valid_until      DATE            NULL DEFAULT NULL COMMENT '有效期(对齐合同期限,到期联动提醒)',
  status           TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=禁用(禁用即全员禁登+存量会话即时失效;货主终止联动)',
  source           VARCHAR(16)     NOT NULL DEFAULT 'local' COMMENT '来源:local=手工,migration=迁移',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted       TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_tenant_code (tenant_code),
  KEY idx_org_tenant_type (tenant_type, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='租户档案(D10.02,P0,internal/external双类型行隔离载体)';

-- 8. 账户档案·双通道（D10.02 · P0）← 商派 pam_account+desktop_users 改造
CREATE TABLE org_account (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键(全域operator/op_id引用值,历史操作人永久可解析:离职只禁用不删除)',
  tenant_id       BIGINT UNSIGNED NOT NULL COMMENT '所属租户 LFK->org_tenant',
  account_type    VARCHAR(16)     NOT NULL DEFAULT 'staff' COMMENT '账户类型:staff=内部员工(自建账号+企微扫码),portal=品牌方门户用户(手机号+验证码无密码),machine=服务账户(P2预留,D02.07 API密钥)',
  login_name      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '登录账号(仅staff:手机号或工号,全局唯一;portal为空串)',
  account_name    VARCHAR(64)     NOT NULL COMMENT '姓名/名称',
  mobile_enc      VARBINARY(256)  NULL DEFAULT NULL COMMENT '手机号密文(D01.05信封加密;portal=登录凭证)',
  mobile_hash     CHAR(64)        NOT NULL DEFAULT '' COMMENT '手机号HMAC盲索引(等值检索+portal租户内唯一约束)',
  email_enc       VARBINARY(256)  NULL DEFAULT NULL COMMENT '邮箱密文',
  email_hash      CHAR(64)        NOT NULL DEFAULT '' COMMENT '邮箱HMAC盲索引',
  org_node_id     BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '主组织节点(staff必填,dept或品牌/货主公司节点) LFK->org_node',
  dept_name       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '部门(文本双记)',
  position        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '岗位',
  status          TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=待激活,2=正常,3=锁定(连败5次,15/30分钟自动解锁),4=禁用(离职/注销/租户禁用/僵尸治理;保留只读永久追溯)',
  lock_until      DATETIME(3)     NULL DEFAULT NULL COMMENT '锁定截止时间',
  fail_count      TINYINT         NOT NULL DEFAULT 0 COMMENT '连续失败计数(密码/验证码连败,成功清零)',
  disable_reason  VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '禁用原因:resign=离职,cancel=注销,tenant_disabled=租户禁用,zombie=僵尸治理(内部90天未登录提醒/外部180天自动禁用),manual=人工',
  last_login_time DATETIME(3)     NULL DEFAULT NULL COMMENT '最近登录时间(僵尸治理依据)',
  last_login_ip   VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '最近登录IP',
  roles_ver       INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '角色绑定版本号(角色/权限变更+1;JWT内版本落后即强制刷新AuthContext)',
  create_op       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '创建人',
  source          VARCHAR(16)     NOT NULL DEFAULT 'local' COMMENT '来源:local=手工,import=批量导入(D01.06),register=自助注册,migration=迁移',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是(账户保留只读,禁用不删除)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_account_login (login_name),
  UNIQUE KEY uk_org_account_mobile (mobile_hash, tenant_id),
  KEY idx_org_account_type (account_type, status),
  KEY idx_org_account_node (org_node_id),
  KEY idx_org_account_last_login (last_login_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='账户档案双通道(D10.02,P0,staff自建+企微/portal手机验证码/machine预留)';

-- 9. 登录凭证（D10.02 · P0，1:1扩展，无软删）
CREATE TABLE org_account_credential (
  id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id             BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  account_id            BIGINT UNSIGNED NOT NULL COMMENT '账户 LFK->org_account',
  credential_type       VARCHAR(16)     NOT NULL DEFAULT 'password' COMMENT '凭证类型:password=账密,wecom=企微扫码,oidc=SSO预留,api_key=机器账户(P2)',
  password_hash         VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '密码argon2id哈希(仅staff;禁明文/可逆存储;初始密码短信下发库中只存哈希;portal无密码空串)',
  password_history_json JSON            NULL DEFAULT NULL COMMENT '历史密码哈希数组(最近3次不重复校验)',
  password_updated_time DATETIME(3)     NULL DEFAULT NULL COMMENT '密码最后修改时间(90天过期提醒,不强制断登)',
  must_change_pwd       TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '首次登录强制改密:0=否,1=是',
  wecom_corp_id         VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '企业微信corpid(多corp预留)',
  wecom_openid          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '企微成员openid(corp内与account一对一,扫码登录匹配键;解绑清空,离职自动解除)',
  sso_subject           VARCHAR(128)    NOT NULL DEFAULT '' COMMENT 'OIDC subject(K-AIDE预留,本期通道开关默认关)',
  sso_idp_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'IdP配置 LFK->org_idp_config(预留)',
  api_key_hash          VARCHAR(255)    NOT NULL DEFAULT '' COMMENT 'API密钥哈希(machine账户P2,D02.07消费)',
  status                TINYINT         NOT NULL DEFAULT 1 COMMENT '凭证状态:1=有效,2=失效(通道级禁用,如解绑企微)',
  create_time           DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time           DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_account_credential (account_id, credential_type),
  KEY idx_org_account_credential_wecom (wecom_openid),
  KEY idx_org_account_credential_sso (sso_subject)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='登录凭证(D10.02,P0,argon2id/企微openid/OIDC预留/API密钥)';

-- 10. 会话落档（D10.02 · P0，日志类扩展：无软删无version）
CREATE TABLE org_session (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  session_id         VARCHAR(64)     NOT NULL COMMENT '会话ID(Redis键session:{account_id}:{device}成分,唯一)',
  account_id         BIGINT UNSIGNED NOT NULL COMMENT '账户 LFK->org_account',
  device_type        VARCHAR(16)     NOT NULL DEFAULT 'pc' COMMENT '设备类型:pc=PC端,mobile=移动端,api=机器(多端策略键:内部PC1+移动1并存同端互踢;外部同端互踢最多2端)',
  device_fp          VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '设备指纹',
  login_ip           VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '登录IP',
  ip_region          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT 'IP库粗粒度地点(异地登录风控)',
  channel            VARCHAR(16)     NOT NULL COMMENT '登录通道:password=账密,wecom_qr=企微扫码,sms_code=手机验证码,oidc=SSO(预留),api_key=密钥(P2)',
  refresh_token_hash CHAR(64)        NOT NULL COMMENT '刷新令牌哈希(refresh 7d落库可吊销;access JWT 2h短期不落库;登出/禁用/踢出=删Redis+吊销双保险)',
  expire_time        DATETIME(3)     NOT NULL COMMENT '会话过期时间',
  status             TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=活跃,2=登出,3=被踢(同端互踢),4=被吊销(禁用/离职即时)',
  login_result       TINYINT         NOT NULL DEFAULT 1 COMMENT '登录结果:1=成功,2=失败(原因结构化投递D10.06)',
  fail_reason        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '失败原因码:pwd_error=密码错,locked=锁定,disabled=账户禁用,tenant_disabled=租户禁用,sms_error=验证码错',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间(登录时间)',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_session (session_id),
  KEY idx_org_session_account (account_id, status),
  KEY idx_org_session_expire (expire_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='会话落档(D10.02,P0,Redis主存+DB落档兜底,登录审计源)';

-- 11. 角色（D10.02 · P0，配置表 owner_id 免填）← 商派 desktop_roles 改造
CREATE TABLE org_role (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL COMMENT '所属租户(自定义角色租户内隔离;system角色tenant_id=1全局)',
  role_code         VARCHAR(64)     NOT NULL COMMENT '角色编码(租户内唯一)',
  role_name         VARCHAR(64)     NOT NULL COMMENT '角色名称',
  role_type         VARCHAR(16)     NOT NULL DEFAULT 'custom' COMMENT '角色类型:system=系统预置(不可删,权限点可升版不可任意改),custom=自定义(外部租户角色由凯淳运营模板派生,品牌方管理员仅模板内选人)',
  data_scope_mode   VARCHAR(16)     NOT NULL DEFAULT 'org_node' COMMENT '数据权限模式(D10.03 FR-02c):all=全部(仅内部超管类角色可设),org_node=按授权节点展开,custom=自定义四维组合',
  custom_scope_json JSON            NULL DEFAULT NULL COMMENT 'custom模式显式四维值{owner_ids,shop_ids,branch_ids,brand_ids}',
  portal_flag       TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '门户外部角色:0=内部,1=外部(外部租户限绑portal角色,写业务权限点不可绑定)',
  status            TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=停用(删除前校验无账户绑定)',
  remark            VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '备注',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted        TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是(system角色不可删)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_role_code (role_code, tenant_id),
  KEY idx_org_role_type (role_type, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='角色(D10.02,P0,system预置10个+custom自定义)';

-- 12. 角色-权限点绑定（D10.02 · P0，关系表无软删无version）
CREATE TABLE org_role_perm (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id   BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  role_id     BIGINT UNSIGNED NOT NULL COMMENT '角色 LFK->org_role',
  perm_code   VARCHAR(128)    NOT NULL COMMENT '权限点编码(域.模块.资源.动作) LFK->org_perm_point(未注册编码不可绑定,防拼写漂移)',
  grant_op    VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '授权人',
  create_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_role_perm (role_id, perm_code),
  KEY idx_org_role_perm_code (perm_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='角色-权限点绑定(D10.02,P0,变更即时触发D10.03权限缓存失效)';

-- 13. 账户-角色关联（D10.02 · P0，关系表无软删无version）
CREATE TABLE org_account_role (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id   BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  account_id  BIGINT UNSIGNED NOT NULL COMMENT '账户 LFK->org_account',
  role_id     BIGINT UNSIGNED NOT NULL COMMENT '角色 LFK->org_role(内部可多角色=并集语义;外部限本租户模板角色)',
  grant_op    VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '授权人',
  expire_time DATETIME(3)     NULL DEFAULT NULL COMMENT '有效期(空=长期;临时角色到期自动失效)',
  create_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_account_role (account_id, role_id),
  KEY idx_org_account_role_role (role_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='账户-角色关联(D10.02,P0,变更触发auth.role_changed事件)';

-- 14. IdP 配置·SSO预留（D10.02 · P0只落结构，开关默认关）
CREATE TABLE org_idp_config (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  idp_code          VARCHAR(64)     NOT NULL COMMENT 'IdP编码(唯一,如kaide)',
  idp_name          VARCHAR(128)    NOT NULL COMMENT 'IdP名称',
  protocol          VARCHAR(16)     NOT NULL DEFAULT 'oidc' COMMENT '协议:oidc=OIDC,saml=SAML(预留)',
  issuer            VARCHAR(255)    NOT NULL COMMENT '签发者URL',
  client_id         VARCHAR(128)    NOT NULL COMMENT '客户端ID',
  client_secret_ref VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '客户端密钥引用(KMS/OSS加密,D01.05 L3;禁明文落库)',
  jwks_uri          VARCHAR(255)    NOT NULL DEFAULT '' COMMENT 'JWKS公钥地址(缓存位)',
  mapping_policy    VARCHAR(16)     NOT NULL DEFAULT 'match' COMMENT '账户映射:match=sso_subject匹配已有账户,jit=自动开户',
  enabled           TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '通道开关:0=关(本期默认,登录页不展示OIDC入口),1=开(P1+对接)',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted        TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_idp_config_code (idp_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='IdP配置SSO预留(D10.02,P0结构/K-AIDE OIDC可插拔Authenticator)';

-- ============================================================================
-- 三、数据权限族（D10.03）
-- ============================================================================

-- 15. 权限点注册表（D10.03 · P0，字典表 owner_id 免填）
CREATE TABLE org_perm_point (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID(注册表全局tenant_id=1)',
  perm_code        VARCHAR(128)    NOT NULL COMMENT '权限点编码,全局唯一(域.模块.资源.动作,如d03.order.skipAudit/field.stock.cost.view)',
  perm_name        VARCHAR(128)    NOT NULL COMMENT '权限点名称',
  perm_type        VARCHAR(16)     NOT NULL DEFAULT 'action' COMMENT '类型:menu=菜单级,action=操作级(接口与动作),button=按钮级(页面元素),field=字段级(敏感字段可见性)',
  module_code      VARCHAR(32)     NOT NULL COMMENT '所属模块(D03.02等,随发布升版;各域迁移脚本声明式注册,唯一注册入口)',
  internal_only    TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '仅内部租户:0=外部可绑定,1=仅内部(FR-06c写业务权限点对外部租户不可绑定)',
  portal_visible   TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '门户可见:0=否,1=是(D10.04白名单=internal_only=0且portal_visible=1子集,确认类权限点逐个显式标记)',
  register_version VARCHAR(32)     NOT NULL DEFAULT 'v1' COMMENT '注册版本(模块发布升版)',
  status           TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=废弃(下线权限点绑定自动失效并提示)',
  remark           VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '说明',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted       TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_perm_point_code (perm_code),
  KEY idx_org_perm_point_module (module_code, perm_type, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='权限点注册表(D10.03,P0,全域功能权限点唯一注册入口)';

-- 16. 数据权限授权·四维（D10.03 · P0）← 商派 permission.php 展开/合并机制改造
CREATE TABLE org_data_permission (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id   BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  account_id  BIGINT UNSIGNED NOT NULL COMMENT '账户 LFK->org_account',
  dim_type    VARCHAR(16)     NOT NULL COMMENT '维度类型:org_node=组织节点(继承展开源头,四步模型第1步),shop=店铺,brand=品牌,branch=仓库,owner=货主(直接维度授权,点状如单店临时支援)',
  dim_id      BIGINT UNSIGNED NOT NULL COMMENT '维度值ID(org_node.id/gw_shop.shop_id/inv_brand.id/ful_branch.branch_id/org_owner.id)',
  grant_scope VARCHAR(16)     NOT NULL DEFAULT 'inherit' COMMENT '节点授权展开方式(dim_type=org_node用):inherit=可继承展开子树(org_path LIKE),self_only=仅本节点不展开(特殊场景)',
  grant_source VARCHAR(16)    NOT NULL DEFAULT 'direct' COMMENT '授权来源:direct=直接配置,inherit=继承展开(诊断/scope明细导出落档标记;正常继承不物化,事件驱动缓存重算FR-03d)',
  reason      VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '授权事由(直接维度授权必填,点状授权可追溯)',
  grant_op    VARCHAR(64)     NOT NULL COMMENT '授权人(独立授权点d10.grant.manage+全量审计变更前后快照)',
  expire_time DATETIME(3)     NULL DEFAULT NULL COMMENT '有效期(空=长期;到期自动失效)',
  status      TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=已失效(到期/收回留档)',
  create_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted  TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_data_permission (account_id, dim_type, dim_id),
  KEY idx_org_data_permission_dim (dim_type, dim_id),
  KEY idx_org_data_permission_expire (expire_time, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='数据权限授权四维(D10.03,P0,org_node授权+shop/brand/branch/owner直接授权,并集合并;外部租户写入校验硬隔离)';

-- 17. 实体过滤声明表（D10.03 · P0，配置表 owner_id 免填）
CREATE TABLE org_filterable_entity (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  entity_name      VARCHAR(64)     NOT NULL COMMENT '实体名(唯一,如ord_order)',
  schema_name      VARCHAR(64)     NOT NULL COMMENT '所属schema(oms_order等)',
  table_name       VARCHAR(64)     NOT NULL COMMENT '物理表名',
  dim_columns_json JSON            NOT NULL COMMENT '维度列映射{"tenant_id":"tenant_id","owner_id":"owner_id","shop_id":"shop_id","branch_id":null,"brand_id":null}(tenant_id必含;null=该实体无此维度列)',
  module_code      VARCHAR(32)     NOT NULL COMMENT '声明模块(D03.01等;未声明实体默认只注入tenant_id保底+开发期告警)',
  register_version VARCHAR(32)     NOT NULL DEFAULT 'v1' COMMENT '声明版本',
  status           TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=停用',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted       TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_filterable_entity (entity_name),
  KEY idx_org_filterable_entity_module (module_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='实体过滤声明表(D10.03,P0,数据权限中间件按声明自动注入行级过滤)';

-- 18. 敏感字段权限注册表（D10.03 · P0，配置表 owner_id 免填）
CREATE TABLE org_field_perm (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  entity_name     VARCHAR(64)     NOT NULL COMMENT '实体名(如inv_stock_ledger)',
  field_name      VARCHAR(64)     NOT NULL COMMENT '字段名(如unit_cost)',
  perm_code       VARCHAR(128)    NOT NULL COMMENT '所需权限点(field.*类) LFK->org_perm_point;无权限字段序列化层置null(服务端脱敏防抓包,非前端隐藏列)',
  mask_rule       VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '脱敏规则引用(D01.05规则编码:phone/name/address/id_card/bank_card/token/open_id;非PII字段空串)',
  portal_forbidden TINYINT(1)     NOT NULL DEFAULT 0 COMMENT '门户永不可见:0=按权限点,1=品牌方永不展示(成本/毛利/服务费率参数,D10.04红线)',
  status          TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=停用',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_field_perm (entity_name, field_name),
  KEY idx_org_field_perm_code (perm_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='敏感字段权限注册表(D10.03,P0,字段级权限+PII叠加D01.05)';

-- 19. 越权事件缓冲（D10.03 · P0，日志类无软删无version）
CREATE TABLE org_perm_violation (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  account_id     BIGINT UNSIGNED NOT NULL COMMENT '越权主体账户 LFK->org_account',
  resource_entity VARCHAR(64)    NOT NULL COMMENT '目标资源实体(如ord_order)',
  row_pk         VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '目标行主键(直查场景;404语义返回不暴露存在性)',
  miss_dim       VARCHAR(16)     NOT NULL COMMENT '缺失/越权维度:shop/brand/branch/owner/tenant',
  request_uri    VARCHAR(255)    NOT NULL COMMENT '请求URI',
  request_ip     VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '来源IP',
  param_snapshot JSON            NULL DEFAULT NULL COMMENT '请求参数快照(脱敏后存储,D01.05出口过滤;scope外维度值静默收敛+越权标记)',
  audit_pushed   TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '已投递D10.06:0=否,1=是(异步投递状态;连续3次越权触发企微告警D01.07)',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  KEY idx_org_perm_violation_account (account_id, create_time),
  KEY idx_org_perm_violation_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='越权事件缓冲(D10.03,P0,投递D10.06前落地+连续越权告警计数源)';

-- ============================================================================
-- 四、门户族（D10.04 · P1）
-- ============================================================================

-- 20. 门户账户扩展·注册审核（D10.02/D10.04 · P1）
CREATE TABLE org_portal_account (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id            BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  account_id           BIGINT UNSIGNED NOT NULL COMMENT '门户账户(唯一,已建成账户) LFK->org_account(account_type=portal)',
  apply_mobile_hash    CHAR(64)        NOT NULL DEFAULT '' COMMENT '申请手机号盲索引(注册判重:在审/已存在拒绝重复提交)',
  company_name         VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '企业名称(注册申请)',
  tax_no               VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '统一社会信用代码(运营审核核对D10.01合同)',
  apply_role_code      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '申请角色(品牌方管理员/财务/运营模板角色)',
  register_source      VARCHAR(16)     NOT NULL DEFAULT 'self' COMMENT '注册来源:self=自助注册(审核流SLA2工作日),ops_create=运营代建(跳过审核,短信通知首登激活)',
  consent_text_version VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '授权协议文本版本(PIPL授权留痕,D01.05 bas_pipl_consent记录互引)',
  audit_status         TINYINT         NOT NULL DEFAULT 0 COMMENT '注册审核状态:0=待审核,1=通过(自动建租户关联账户),2=驳回(结构化原因通知可重新提交),3=无需审核(运营代建)',
  audit_op             VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '审核人',
  audit_time           DATETIME(3)     NULL DEFAULT NULL COMMENT '审核时间(SLA2工作日超时提醒运营)',
  reject_reason        VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '驳回原因(结构化)',
  parent_account_id    BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '上级账户(品牌方管理员=0;子账户=管理员account_id,上限默认20可配)',
  create_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted           TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_portal_account (account_id),
  KEY idx_org_portal_account_apply (apply_mobile_hash, audit_status),
  KEY idx_org_portal_account_parent (parent_account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='门户账户扩展注册审核(D10.04,P1,自助注册审核流+子账户管理)';

-- 21. 门户站内信（D10.04 · P1）
CREATE TABLE org_portal_message (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id           BIGINT UNSIGNED NOT NULL COMMENT '租户ID(行隔离)',
  scene_code          VARCHAR(64)     NOT NULL COMMENT '通知场景:settle_pending=结算待确认,settle_urge=确认催办,settle_redflush=红冲V2重确认,dispute_result=异议结论,stock_red=缺货红色预警,stock_daily=橙黄预警日报,batch_red=临期红色预警,stock_adjust=库存调整知情,account_audit=账号审核结果',
  title               VARCHAR(255)    NOT NULL COMMENT '标题',
  content             TEXT            NOT NULL COMMENT '内容(模板化变量注入,敏感变量脱敏形态,D01.05)',
  link_url            VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '跳转链接(门户内页面)',
  ref_type            VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '关联业务对象类型:settle/order/suggestion/account等',
  ref_bn              VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '关联业务对象单号(如settle_bn)',
  receiver_account_id BIGINT UNSIGNED NOT NULL COMMENT '接收账户 LFK->org_account',
  read_status         TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '已读:0=未读,1=已读',
  read_time           DATETIME(3)     NULL DEFAULT NULL COMMENT '已读时间',
  push_channel_ref    JSON            NULL DEFAULT NULL COMMENT '同步推送通道记录{sms_msg_id,email_msg_id}(D01.07 bas_notify_log留痕互查)',
  create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted          TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  KEY idx_org_portal_message_receiver (receiver_account_id, read_status, create_time),
  KEY idx_org_portal_message_ref (ref_type, ref_bn)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='门户站内信(D10.04,P1,消息中心落点,9类通知场景)';

-- 22. 门户通知偏好（D10.04 · P1，配置表）
CREATE TABLE org_portal_notify_pref (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  scene_code     VARCHAR(64)     NOT NULL COMMENT '通知场景(同org_portal_message.scene_code枚举)',
  channels_json  JSON            NOT NULL COMMENT '通道开关{"inbox":1,"sms":0,"email":1}(短信仅资金与红色预警类可开,防打扰约束应用层校验)',
  receivers_json JSON            NULL DEFAULT NULL COMMENT '接收人账户ID集(空=租户全部相关角色)',
  update_op      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '变更人(偏好变更审计)',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_portal_notify_pref (tenant_id, scene_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='门户通知偏好(D10.04,P1,租户x场景通道开关与接收人)';

-- 23. 门户导出记录（D10.04 · P1，日志类无软删无version）
CREATE TABLE org_portal_export_log (
  id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id             BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  account_id            BIGINT UNSIGNED NOT NULL COMMENT '导出账户 LFK->org_account',
  scene                 VARCHAR(64)     NOT NULL COMMENT '导出场景(订单/库存/结算/售后等)',
  query_params_snapshot JSON            NULL DEFAULT NULL COMMENT '范围参数快照(脱敏存储)',
  row_count             INT             NOT NULL DEFAULT 0 COMMENT '导出行数(单次上限默认5万,超限走异步D01.06)',
  file_ref              VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '文件引用(OSS加密+时效链接)',
  watermark_text        VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '水印内容(姓名+手机后4位+租户名+yyyy-MM-dd HH:mm,斜排平铺)',
  export_ip             VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '导出IP(审计要素)',
  create_time           DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '导出时间',
  PRIMARY KEY (id),
  KEY idx_org_portal_export_log_account (account_id, create_time),
  KEY idx_org_portal_export_log_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='门户导出记录(D10.04,P1,导出100%审计+水印要素)';

-- 24. 门户访问日志（D10.04 · P1，按月分表 _YYYYMM 结构基线，日志类）
CREATE TABLE org_portal_read_log (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id   BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  account_id  BIGINT UNSIGNED NOT NULL COMMENT '访问账户 LFK->org_account',
  owner_id    BIGINT UNSIGNED NOT NULL COMMENT '访问时点货主上下文(门户行隔离主维,双身份要素:外部账户+租户+货主)',
  page_code   VARCHAR(64)     NOT NULL COMMENT '页面编码:home/order/stock/settle/aftersale/warn/msg/account',
  action      VARCHAR(32)     NOT NULL DEFAULT 'view' COMMENT '动作:view=浏览,detail=明细查询,export=导出(100%记录),confirm=确认类操作(逐笔另投aud_operation_log)',
  ref_type    VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '关联对象类型',
  ref_bn      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '关联对象单号',
  sampled     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '采样标记:0=全量(导出/确认),1=采样命中(查询10%采样,FR-06b)',
  access_ip   VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '访问IP',
  device_fp   VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '设备指纹',
  create_time DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '访问时间',
  PRIMARY KEY (id),
  KEY idx_org_portal_read_log_account (account_id, create_time),
  KEY idx_org_portal_read_log_owner (owner_id, create_time),
  KEY idx_org_portal_read_log_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='门户访问日志(D10.04,P1,按月分表_YYYYMM,在线3个月)';
-- 月表示例（调度器滚动创建）：CREATE TABLE org_portal_read_log_202611 LIKE org_portal_read_log;

-- ============================================================================
-- 五、审批族（D10.05 · P1，M1 预留接口）
-- ============================================================================

-- 25. 审批场景注册表（D10.05 · P1，字典表 owner_id 免填）31场景登记源
CREATE TABLE org_approval_scene (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id           BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  scene_code          VARCHAR(64)     NOT NULL COMMENT '场景编码,全局唯一(31场景见初始数据,如purchase_request/stock_manual_adjust)',
  scene_name          VARCHAR(128)    NOT NULL COMMENT '场景名称',
  source_module       VARCHAR(32)     NOT NULL COMMENT '来源模块(D03.08/D04.02/D06.01等,SRS引用位;场景清单升版需SRS-D10.05变更记录登记)',
  oa_template_id      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '泛微OA流程模板ID(workflowId,M1桩期空串;映射配置化,OA模板升版不改代码)',
  field_mapping_json  JSON            NULL DEFAULT NULL COMMENT '表单字段映射(OMS要素JSON->OA表单字段)',
  element_schema_json JSON            NULL DEFAULT NULL COMMENT '要素schema(JSON Schema,发起时校验完整性;要素含业务快照防审批期间数据被改)',
  perm_code           VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '发起权限点 LFK->org_perm_point(D10.03注册)',
  default_need        TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '默认需审:0=免审(阈值内approved_auto留痕),1=需审(阈值规则未命中时兜底)',
  fixed_must          TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '固定必审:0=有阈值配置,1=全量必审无阈值豁免(如purchase_request/settle_red_flush)',
  sla_hours           INT             NOT NULL DEFAULT 24 COMMENT 'SLA小时(超时催办企微当前处理人,超2xSLA升级告警审批管理员)',
  callback_consumers  JSON            NULL DEFAULT NULL COMMENT '结果事件订阅方["D06.01","D04.02"](approval.finished经bas_event_outbox分发登记)',
  stub_mode           TINYINT(1)      NOT NULL DEFAULT 1 COMMENT 'M1桩模式:0=正式OA,1=桩(阈值内直通/超阈值pending_manual线下登记企微通知管理员;M3切DI实现业务代码零改动)',
  status              TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=废弃(在途单跑完为止)',
  register_version    VARCHAR(32)     NOT NULL DEFAULT 'v1' COMMENT '注册版本',
  create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted          TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_approval_scene_code (scene_code),
  KEY idx_org_approval_scene_module (source_module, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='审批场景注册表(D10.05,P1,31场景汇总登记源,OA管人与流程/OMS管事与数据)';

-- 26. 审批阈值规则（D10.05 · P1，配置表 owner_id 免填）
CREATE TABLE org_approval_threshold (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  scene_code         VARCHAR(64)     NOT NULL COMMENT '审批场景 LFK->org_approval_scene',
  dim_condition_json JSON            NULL DEFAULT NULL COMMENT '维度条件{"owner_id":5,"branch_id":3,"adjust_type":1}(空=全局默认;货主/仓/店铺/类型等场景自定义维度;特异性高者优先)',
  dim_specificity    TINYINT         NOT NULL DEFAULT 0 COMMENT '维度特异性(条件维度数,匹配排序:货主+仓+类型>货主>全局默认)',
  rule_expr          VARCHAR(512)    NOT NULL COMMENT '阈值表达式(数值/比例/枚举,如abs_qty>10 OR value_amount>5000;语义定义权在各业务域SRS)',
  need_approval      TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '命中后是否需审:0=免审(approved_auto留痕),1=需审',
  effect_start       DATETIME(3)     NULL DEFAULT NULL COMMENT '生效期间起(支持大促临时策略,空=不限)',
  effect_end         DATETIME(3)     NULL DEFAULT NULL COMMENT '生效期间止',
  rule_version       INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '规则版本(审批实例记录发起时命中版本rule_ver,可解释当时为什么需/免审)',
  priority           INT             NOT NULL DEFAULT 0 COMMENT '同特异性优先级(大者优先)',
  status             TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=停用',
  update_op          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '变更人(高权限点d10.approval.threshold.manage;资金类场景19/21-27变更自举走OA;变更前后快照审计)',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted         TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_approval_threshold_ver (scene_code, rule_version, dim_specificity, priority),
  KEY idx_org_approval_threshold_scene (scene_code, status, dim_specificity, priority)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='审批阈值规则(D10.05,P1,阈值配置中心统一载体,版本化可解释)';

-- 27. 审批实例·审批单档案（D10.05 · P1，单据类无软删）
CREATE TABLE org_approval_instance (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id            BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  approval_bn          VARCHAR(32)     NOT NULL COMMENT 'OMS审批单号,唯一(bas_seq发号AP+日期+序列)',
  scene_code           VARCHAR(64)     NOT NULL COMMENT '审批场景 LFK->org_approval_scene',
  biz_type             VARCHAR(32)     NOT NULL COMMENT '业务类型(pur_request/stock_adjust/settle等)',
  biz_bn               VARCHAR(32)     NOT NULL COMMENT '业务单号(与scene_code联合在途唯一,重复submit幂等返回已有实例防双发起)',
  initiator_id         BIGINT UNSIGNED NOT NULL COMMENT '发起人账户 LFK->org_account(回避规则OA侧执行:发起人!=审批人;离职在途审批转交提醒)',
  urgent_flag          TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '加急:0=否,1=是(独立权限点;透传OA加急标记+企微通知当前处理人;加急率进看板治理)',
  urgent_reason        VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '加急理由(勾选加急必填)',
  element_snapshot     JSON            NOT NULL COMMENT '要素快照(发起时点数据,审批人看快照非实时值;执行前二次校验基准FR-04d)',
  snapshot_ver         INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '快照版本(回调分发事件携带,业务域执行前重验:权限仍有效/数据未漂移超容差)',
  rule_ver             VARCHAR(32)     NOT NULL DEFAULT 'default' COMMENT '命中阈值规则版本(rule_id:rule_version;免审=default;可解释性闭环)',
  auto_flag            TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '免审通过:0=否,1=是(阈值内approved_auto;免审也要有记录=审计红线FR-05d)',
  oa_instance_id       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '泛微OA流程实例ID(发起成功必填;M1桩期空串标记)',
  oa_template_id       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT 'OA模板ID快照(发起时点)',
  status               TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=发起中,2=审批中,3=通过,4=驳回,5=撤回,6=发起失败(OA创建重试3次失败,业务解冻+告警),7=撤回中(等OA确认回调,双轨状态红线),8=通过未执行(二次校验失败,告警人工介入);终态不可逆(通过后问题走业务红冲/反审核+新审批)',
  result_opinion       VARCHAR(1024)   NOT NULL DEFAULT '' COMMENT '终态意见(驳回意见结构化回传业务域,企微通知申请人)',
  flow_summary         JSON            NULL DEFAULT NULL COMMENT 'OA流转记录摘要[{node,handler,opinion,time,delegate_flag}](回调/补偿查询同步;代理以OA为权威仅透传展示)',
  execute_check_status TINYINT         NOT NULL DEFAULT 0 COMMENT '执行前二次校验:0=未执行,1=通过,2=失败(权限收回/数据漂移,标记通过未执行+告警;资金/敏感写操作回调执行前重查scope,D10.03 §5.5)',
  sla_due_time         DATETIME(3)     NULL DEFAULT NULL COMMENT 'SLA截止时间(超时催办依据,场景级可配默认24h)',
  finish_time          DATETIME(3)     NULL DEFAULT NULL COMMENT '完成时间(终态)',
  trace_id             VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '全链路追踪ID(D01.01契约)',
  create_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间(发起时间)',
  update_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version              INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(CAS状态迁移,补偿查询与回调并发防双写)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_approval_instance_bn (approval_bn),
  KEY idx_org_approval_instance_oa (oa_instance_id),
  KEY idx_org_approval_instance_inflight (scene_code, biz_type, biz_bn, status),
  KEY idx_org_approval_instance_initiator (initiator_id, status),
  KEY idx_org_approval_instance_sla (status, sla_due_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='审批实例审批单档案(D10.05,P1,状态机+要素快照+规则版本+OA流转摘要可解释闭环,单据类无软删)';

-- 28. OA回调报文日志（D10.05 · P1，按月分表 _YYYYMM 结构基线，日志类）
CREATE TABLE org_oa_callback_log (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  log_type       VARCHAR(16)     NOT NULL DEFAULT 'callback' COMMENT '日志类型:callback=OA回调,request=OMS调OA请求/响应(oa_api_log语义,对齐D02.01 api_log机制),compensate=补偿查询结果(每5分钟扫描审批中/撤回中超2h实例主动查OA)',
  oa_instance_id VARCHAR(64)     NOT NULL COMMENT 'OA流程实例号',
  result_version INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '结果版本(幂等键成分:重复回调直接ACK/乱序旧版本忽略留标记)',
  direction      TINYINT         NOT NULL DEFAULT 1 COMMENT '方向:1=入(回调),2=出(创建/撤回/状态查询)',
  raw_payload    JSON            NOT NULL COMMENT '原始报文全量(先落库再处理;审计与重放依据;敏感字段按D01.05出口规则脱敏)',
  sign_verified  TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '签名验证:0=失败(拒绝处理+告警),1=通过',
  source_ip      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '来源IP(白名单校验)',
  process_status TINYINT         NOT NULL DEFAULT 0 COMMENT '处理状态:0=待处理,1=已处理,2=重复忽略,3=乱序忽略,4=处理失败',
  approval_bn    VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '关联审批单号 LFK->org_approval_instance',
  trace_id       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '全链路追踪ID',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '接收时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_org_oa_callback_log_dedup (oa_instance_id, result_version, log_type),
  KEY idx_org_oa_callback_log_bn (approval_bn),
  KEY idx_org_oa_callback_log_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='OA回调报文日志(D10.05,P1,按月分表_YYYYMM,幂等去重键(oa_instance_id,result_version),在线6个月)';
-- 月表示例（调度器滚动创建）：CREATE TABLE org_oa_callback_log_202611 LIKE org_oa_callback_log;

-- ============================================================================
-- 六、oms_audit 审计（D10.06 · 独立 schema）
-- ============================================================================
USE oms_audit;

-- 29. 操作审计事件（D10.06 · P0框架，按月分表 _YYYYMM 结构基线）★核心，只增不改不删
CREATE TABLE aud_operation_log (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键(物理)',
  event_id            BIGINT UNSIGNED NOT NULL COMMENT '事件ID(雪花ID,时间有序=链序基础;应用发号非AUTO_INCREMENT)',
  event_class         VARCHAR(32)     NOT NULL COMMENT '事件分类:data_change=数据变更(自动diff),auth_event=认证事件(登录/登出/锁定),perm_event=权限事件(授权/角色/越权/模拟),decision_event=决策事件(审批/调整/确认签核包),access_event=访问事件(PII明文/敏感导出/审计检索本身=审计的审计),system_event=系统事件(配置变更/豁免通道调用withoutDataScope)',
  action              VARCHAR(32)     NOT NULL COMMENT '操作类型:create/update/delete/login/logout/export/approve/grant/revoke/simulate/view_pii/business_event/config_change',
  scene_code          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '业务场景码(与D10.05审批场景/D10.06事件字典对齐,防拼写漂移)',
  perm_code           VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '关联权限点(操作对应授权依据)',
  actor_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '操作人账户ID(system=0) LFK->oms_org.org_account',
  actor_name_snapshot VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '操作人姓名快照(账户禁用后仍可解析展示)',
  actor_type          VARCHAR(16)     NOT NULL DEFAULT 'staff' COMMENT '操作人类型:staff=内部,portal=门户,system=系统(MQ worker/调度,含任务标识)',
  simulate_origin_id  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '模拟模式原身份账户(D10.03 FR-09a双身份:谁模拟了谁,全部操作以模拟标记写审计)',
  owner_id            BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主上下文(门户/货主维度检索)',
  event_time          DATETIME(3)     NOT NULL COMMENT '业务发生时间(毫秒,服务端时间权威)',
  receive_time        DATETIME(3)     NOT NULL COMMENT '落库接收时间(延迟监控P99<=30s)',
  ip                  VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '来源IP',
  ip_region           VARCHAR(64)     NOT NULL DEFAULT '' COMMENT 'IP库粗粒度地点',
  device_fp           VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '设备指纹',
  channel             VARCHAR(16)     NOT NULL DEFAULT '' COMMENT '渠道:web/h5/api/mq/scheduler/oa_callback',
  entity_name         VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '对象实体(如ord_order)',
  table_name          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '物理表名',
  row_pk              VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '对象行主键(时间线检索主维度)',
  biz_type            VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '业务单据类型(settle_confirm=结算确认签核/stock_adjust等;门户签核包以decision_event落本表)',
  biz_bn              VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '业务单号(对象时间线/纠纷取证检索键)',
  field_diffs         JSON            NULL DEFAULT NULL COMMENT '字段级diff[{field,old,new,mask_rule,mask_hint}];PII密文+脱敏摘要(D01.05);delete=全字段快照;create=[{field,old:null,new:v}]',
  source              VARCHAR(32)     NOT NULL DEFAULT 'manual' COMMENT '来源:manual=人工界面,scheduler=调度,mq=MQ消费,oa_callback=OA回调,platform_notify=平台通知,openapi=OpenAPI',
  ref_ids_json        JSON            NULL DEFAULT NULL COMMENT '关联单据引用{approval_bn,modify_bn,callback_log_id}(决策语境链互引:审批单/改单单/回调报文)',
  result              VARCHAR(16)     NOT NULL DEFAULT 'success' COMMENT '结果:success=成功,fail=失败,denied=拒绝(越权必记)',
  fail_reason         VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '失败/拒绝原因(结构化)',
  sensitive_level     TINYINT         NOT NULL DEFAULT 1 COMMENT '敏感级别:1=普通(在线6月+归档1年),2=一般变更决策(在线1年+归档>=3年),3=资金/PII明文/权限变更(在线1年+归档>=5年;检索导出需独立授权点d10.audit.sensitive.view,导出走OA审批)',
  trace_id            VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '全链路追踪ID(D01.01契约,贯穿业务日志)',
  prev_hash           CHAR(64)        NOT NULL DEFAULT '' COMMENT '前条记录哈希(hash链:分表内串行成链,Redis缓存链尾,miss查MAX(id)行)',
  row_hash            CHAR(64)        NOT NULL COMMENT '本条哈希=SHA256(canonical_json(八要素+diffs)+prev_hash+event_id);任何中间篡改导致后续全链校验失败',
  tenant_id           BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aud_operation_log_event (event_id),
  KEY idx_aud_operation_log_actor (actor_id, event_time),
  KEY idx_aud_operation_log_row (entity_name, row_pk, event_time),
  KEY idx_aud_operation_log_biz (biz_type, biz_bn),
  KEY idx_aud_operation_log_time (event_time),
  KEY idx_aud_operation_log_class (event_class, action, sensitive_level)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='操作审计事件(D10.06,P0框架,按月分表_YYYYMM,八要素+hash链防篡改,只增不改不删,应用账号仅INSERT/SELECT,在线1年+归档OSS WORM)';
-- 月表示例（调度器滚动创建）：CREATE TABLE aud_operation_log_202611 LIKE aud_operation_log;

-- 30. 数据明文访问日志·PIPL（D10.06/D01.05 · P0，按月分表 _YYYYMM 结构基线，日志类）
CREATE TABLE aud_data_access_log (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  access_type     VARCHAR(32)     NOT NULL COMMENT '访问类型:plain_view=明文查看(字段级),batch_decrypt=批量解密(服务账号级),credential_use=凭证取用(D02.06 token),export=导出,dsr_op=权利响应操作,consent_query=授权记录访问,key_op=密钥操作(轮换/销毁)',
  accessor_type   VARCHAR(16)     NOT NULL DEFAULT 'staff' COMMENT '访问者类型:staff=内部,portal=门户,service=服务账号(L3白名单:申报组装服务账号可解身份证明文且逐次审计)',
  accessor_id     BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '人员账户ID(service时=0) LFK->oms_org.org_account',
  service_account VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '服务账号标识(accessor_type=service时必填)',
  entity_name     VARCHAR(64)     NOT NULL COMMENT '访问实体',
  record_ref      VARCHAR(64)     NOT NULL COMMENT '记录定位(row_pk或业务单号;消费者投诉按订单号/手机号密文匹配检索)',
  field_name      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '字段名(字段级明文查看;批量/导出为空)',
  batch_size      INT             NOT NULL DEFAULT 0 COMMENT '批量大小(批量解密/导出条数,批量明文查看上限默认50需独立权限点)',
  scene_context   VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '场景上下文(业务单号/工作台/接口方法)',
  perm_code       VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '命中权限点({entity}.field.{f}.plain)',
  result          VARCHAR(16)     NOT NULL DEFAULT 'success' COMMENT '结果:success=成功,denied=拒绝(无权拒绝也记,拒绝本身记审计)',
  risk_flag       TINYINT         NOT NULL DEFAULT 0 COMMENT '异常探测标记:0=正常,1=高频(>50次/日或>10次/小时,角色可配),2=非工作时段批量,3=爬取模式(短时跨大量无关订单),4=服务账号解密量突增;命中->D01.07告警P1+安全工单',
  source_ip       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '来源IP',
  anonymized      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '已匿名化:0=否,1=是(PIPL超期匿名化标记:actor降粒度+PII值销毁留脱敏摘要,保留统计价值消除个体关联)',
  tenant_id       BIGINT UNSIGNED NOT NULL COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主上下文',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '访问时间',
  PRIMARY KEY (id),
  KEY idx_aud_data_access_log_accessor (accessor_id, create_time),
  KEY idx_aud_data_access_log_record (entity_name, record_ref),
  KEY idx_aud_data_access_log_type (access_type, risk_flag, create_time),
  KEY idx_aud_data_access_log_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='数据明文访问日志PIPL(D10.06/D01.05,P0,按月分表_YYYYMM,频次异常探测,超期匿名化而非删除,保留期=业务必要期默认3年)';
-- 月表示例（调度器滚动创建）：CREATE TABLE aud_data_access_log_202611 LIKE aud_data_access_log;

-- 31. 审计采集声明表（D10.06 · P0，配置表）
CREATE TABLE aud_entity_registry (
  id                      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id               BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  entity_name             VARCHAR(64)     NOT NULL COMMENT '实体名(唯一,与org_filterable_entity同模式注册)',
  table_name              VARCHAR(64)     NOT NULL COMMENT '物理表名(schema.table)',
  fields_include_json     JSON            NULL DEFAULT NULL COMMENT '字段白名单(空=全字段默认)',
  fields_exclude_json     JSON            NULL DEFAULT NULL COMMENT '字段黑名单(大文本/无意义字段,防无差别采集爆量)',
  default_sensitive_level TINYINT         NOT NULL DEFAULT 2 COMMENT '默认敏感级别:1/2/3(事件落库级别基线,资金类实体=3)',
  module_code             VARCHAR(32)     NOT NULL COMMENT '声明模块(未注册实体不自动采集+开发期告警;接入注册台FR-07a进度管理数据源)',
  register_version        VARCHAR(32)     NOT NULL DEFAULT 'v1' COMMENT '声明版本',
  status                  TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=停用',
  create_time             DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time             DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aud_entity_registry (entity_name),
  KEY idx_aud_entity_registry_module (module_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='审计采集声明表(D10.06,P0,自动diff采集范围声明驱动)';

-- 32. hash链月锚点（D10.06 · P0，只增）
CREATE TABLE aud_hash_anchor (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  month_table        VARCHAR(64)     NOT NULL COMMENT '月表名(aud_operation_log_202610)',
  last_event_id      BIGINT UNSIGNED NOT NULL COMMENT '月末最后事件ID',
  last_hash          CHAR(64)        NOT NULL COMMENT '月末链尾哈希(跨月锚点)',
  row_count          INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '当月记录数',
  external_proof_ref VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '外部存证引用(企微机器人频道消息ID/邮件Message-ID,低成本第三方见证;法务取证出具防篡改证明可复验)',
  verify_status      TINYINT         NOT NULL DEFAULT 0 COMMENT '校验状态:0=待校验,1=通过,2=断链(每日抽样+周末全量校验任务;断链->告警安全管理员+运维,断点定位报告:时间窗/表/记录区间)',
  verify_time        DATETIME(3)     NULL DEFAULT NULL COMMENT '最后校验时间',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aud_hash_anchor (month_table)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='hash链月锚点(D10.06,P0,月末链尾哈希+外部存证,只增)';

-- 33. 审计保留策略·版本化（D10.06 · P0，配置表）
CREATE TABLE aud_retention_policy (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  policy_level         TINYINT         NOT NULL COMMENT '敏感级别:1=普通,2=一般变更决策,3=资金/PII明文/权限变更(对应sensitive_level)',
  policy_type          VARCHAR(16)     NOT NULL DEFAULT 'audit' COMMENT '策略类型:audit=审计事件,pipl=PIPL数据访问日志专项',
  online_months        INT             NOT NULL DEFAULT 12 COMMENT '在线保留月数(等保2.0>=6个月加严)',
  archive_years        INT             NOT NULL DEFAULT 3 COMMENT '归档保留年数(OSS WORM桶Object Lock,保留期内任何人不可删改)',
  pii_anonymize_months INT             NOT NULL DEFAULT 0 COMMENT 'PIPL匿名化期限月数(0=不适用;访问日志默认36=业务必要期(合同履行+诉讼时效),超期匿名化而非删除)',
  policy_version       INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '策略版本(变更留痕+审计;与法规冲突以法务书面意见为准)',
  status               TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=历史',
  update_op            VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '变更人',
  create_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_aud_retention_policy (policy_type, policy_level, policy_version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='审计保留策略版本化(D10.06,P0,分级保留+PIPL专项匿名化)';

-- 34. 销毁留痕（D10.06 · P0，只增）
CREATE TABLE aud_destroy_log (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  policy_id     BIGINT UNSIGNED NOT NULL COMMENT '保留策略 LFK->aud_retention_policy',
  destroy_range VARCHAR(255)    NOT NULL COMMENT '销毁/匿名化范围(月表名+记录区间)',
  method        VARCHAR(16)     NOT NULL DEFAULT 'destroy' COMMENT '处理方式:destroy=物理销毁(归档期满),anonymize=匿名化(PIPL超期,DEK销毁=密码学擦除+标识符泛化,不可逆声明)',
  record_count  INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '涉及记录数',
  confirm_op_1  VARCHAR(64)     NOT NULL COMMENT '确认人1(安全管理员,双确认必填)',
  confirm_op_2  VARCHAR(64)     NOT NULL COMMENT '确认人2(内审负责人,双确认必填)',
  verify_result VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '抽样校验结果(匿名化:原明文不可恢复+统计可用性D11聚合仍可跑)',
  destroy_time  DATETIME(3)     NOT NULL COMMENT '执行时间',
  create_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  KEY idx_aud_destroy_log_policy (policy_id),
  KEY idx_aud_destroy_log_time (destroy_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='销毁留痕(D10.06,P0,归档期满销毁/匿名化双人确认,销毁记录本身留痕,只增)';

-- ============================================================================
-- 七、初始字典数据
-- ============================================================================
USE oms_org;

-- 7.1 组织树初始化（SRS-D10.01 FR-08a：幂等脚本，编码判重可重跑）
INSERT INTO org_node (id, tenant_id, org_code, org_name, node_type, parent_id, cat_path, node_level, sort_no, status, source) VALUES
(1, 1, 'KC_ROOT',  '凯淳集团',       'group',    0, ',1,', 1, 1, 1, 'migration'),
(2, 1, 'KC_TRADE', '凯淳贸易主体',   'owner_co', 1, ',1,2,', 2, 1, 1, 'migration');

-- 7.2 默认货主 owner_KC（FR-03c：凯淳买断，系统自身单据默认归属，不可停用）
INSERT INTO org_owner (id, tenant_id, owner_code, owner_name, owner_type, org_node_id, status, source) VALUES
(1, 1, 'KC', '凯淳自营（买断）', 'KC_BUYOUT', 2, 1, 'migration');

INSERT INTO org_node_relation (tenant_id, node_id, rel_type, rel_id, is_primary, status, create_op) VALUES
(1, 2, 'owner', 1, 1, 1, 'system');

-- 7.3 内部租户 tenant_KC（FR-01a：全系统唯一，id=1 固定，永不可禁用）
INSERT INTO org_tenant (id, tenant_code, tenant_name, tenant_type, owner_scope_json, status, source) VALUES
(1, 'KC', '凯淳内部租户', 'internal', '[1]', 1, 'migration');

-- 7.4 系统角色预置（SRS-D10.02 FR-04a：10 个 system 角色，不可删除）
INSERT INTO org_role (tenant_id, role_code, role_name, role_type, data_scope_mode, portal_flag, status, remark) VALUES
(1, 'super_admin',    '超级管理员',     'system', 'all',      0, 1, '唯一可设all模式;预置不可删'),
(1, 'org_admin',      '组织管理员',     'system', 'org_node', 0, 1, '组织树/货主/授权管理'),
(1, 'order_auditor',  '审单员',         'system', 'org_node', 0, 1, 'D03.03人工审单工作台'),
(1, 'stock_keeper',   '库存专员',       'system', 'org_node', 0, 1, 'D04库存管理(无成本字段权限)'),
(1, 'finance',        '财务',           'system', 'org_node', 0, 1, 'D08财务对账(含成本/毛利字段权限)'),
(1, 'purchaser',      '采购',           'system', 'org_node', 0, 1, 'D06采购管理'),
(1, 'customer_service','客服',          'system', 'org_node', 0, 1, 'D05售后+D03.08改单'),
(1, 'brand_admin',    '品牌方管理员',   'system', 'custom',   1, 1, '门户:本租户子账户管理+结算确认'),
(1, 'brand_finance',  '品牌方财务',     'system', 'custom',   1, 1, '门户:结算中心确认/异议'),
(1, 'brand_operator', '品牌方运营',     'system', 'custom',   1, 1, '门户:订单/库存/售后/预警只读');

-- 7.5 权限点注册样例（D10 域自身权限点；各业务域随迁移脚本注册，此处为初始化必备集）
INSERT INTO org_perm_point (tenant_id, perm_code, perm_name, perm_type, module_code, internal_only, portal_visible, status, remark) VALUES
(1, 'd10.org.manage',                '组织树与货主管理',       'menu',   'D10.01', 1, 0, 1, '组织/货主/合同/结算配置管理界面'),
(1, 'd10.account.manage',            '账户与角色管理',         'menu',   'D10.02', 1, 0, 1, '账户/角色/授权管理界面'),
(1, 'd10.grant.manage',              '数据权限授权管理',       'action', 'D10.03', 1, 0, 1, '授权变更独立授权点(FR-02e)'),
(1, 'd10.perm.simulate',             '权限模拟',               'action', 'D10.03', 1, 0, 1, '模拟会话独立授权点(FR-09a,双身份审计+红色水印)'),
(1, 'd10.approval.threshold.manage', '审批阈值配置管理',       'action', 'D10.05', 1, 0, 1, '高权限点;资金类场景阈值变更自举走OA'),
(1, 'd10.audit.view',                '审计检索',               'menu',   'D10.06', 1, 0, 1, '审计工作台(level1/2)'),
(1, 'd10.audit.sensitive.view',      '敏感审计检索',           'action', 'D10.06', 1, 0, 1, 'sensitive_level=3检索/导出独立授权点'),
(1, 'field.stock.cost.view',         '库存成本字段可见',       'field',  'D04.02', 1, 0, 1, 'inv_stock_ledger.unit_cost/inventory_cost(SC-D10.03-03)'),
(1, 'field.pii.plaintext.view',      'PII明文查看',            'field',  'D01.05', 1, 0, 1, '消费者姓名/电话/地址明文;每次查看投递审计;门户永不开放'),
(1, 'd08.settle.confirmBrand',       '结算单品牌方确认',       'action', 'D08.02', 0, 1, 1, '门户确认类白名单(电子签核留痕)'),
(1, 'd08.settle.dispute',            '结算单行级异议',         'action', 'D08.02', 0, 1, 1, '门户确认类白名单'),
(1, 'd10.portal.account.selfManage', '门户账号自助管理',       'action', 'D10.04', 0, 1, 1, '品牌方管理员子账户管理(限本租户,上限20可配)');

-- 7.6 审批场景注册表：31 场景全量（SRS-D10.05 FR-02 清单，本文档=登记源）
INSERT INTO org_approval_scene (tenant_id, scene_code, scene_name, source_module, perm_code, default_need, fixed_must, sla_hours, callback_consumers, stub_mode, status) VALUES
(1, 'order_price_change',      '订单改价',                     'D03.08', 'd03.order.priceChange',  1, 0, 24, '["D03.08"]', 1, 1),
(1, 'order_skip_audit',        '跳过审单',                     'D03.03', 'd03.order.skipAudit',    1, 1, 24, '["D03.03"]', 1, 1),
(1, 'order_force_ship',        '强制发货(跳过库存校验)',       'D03.09', 'd03.order.forceShip',    1, 1, 24, '["D03.09"]', 1, 1),
(1, 'order_blacklist_change',  '黑名单加入/移除',              'D03.09', 'd03.order.blacklist',    1, 1, 24, '["D03.09"]', 1, 1),
(1, 'order_oversell_refund',   '超卖自动退款超阈值',           'D03.09', 'd03.order.oversellRefund',1, 0, 24, '["D03.09"]', 1, 1),
(1, 'order_batch_cancel',      '批量取消订单',                 'D03.10', 'd03.order.batchCancel',  1, 0, 24, '["D03.10"]', 1, 1),
(1, 'card_batch_void',         '卡密批量作废',                 'D03.10', 'd03.card.batchVoid',     1, 0, 24, '["D03.10"]', 1, 1),
(1, 'warehouse_force_change',  '强制低满足度改仓',             'D03.06', 'd03.route.forceWarehouse',1, 0, 24, '["D03.06"]', 1, 1),
(1, 'order_export_plaintext',  '历史订单明文导出',             'D03.13', 'd03.order.exportPlain',  1, 1, 24, '["D03.13","D01.06"]', 1, 1),
(1, 'stock_manual_adjust',     '手工库存调整超阈值',           'D04.02', 'd04.stock.adjust',       1, 0, 24, '["D04.02"]', 1, 1),
(1, 'stocktake_diff',          '盘点差异超阈值',               'D04.06', 'd04.stocktake.diff',     1, 0, 24, '["D04.06"]', 1, 1),
(1, 'manual_freeze',           '人工预占(活动锁库)',           'D04.03', 'd04.freeze.manual',      1, 0, 24, '["D04.03"]', 1, 1),
(1, 'stock_transfer_over',     '仓间调拨超阈值',               'D04.05', 'd04.transfer.over',      1, 0, 24, '["D04.05"]', 1, 1),
(1, 'lend_rule_change',        '借调规则新建/变更',            'D04.05', 'd04.lend.ruleChange',    1, 1, 24, '["D04.05"]', 1, 1),
(1, 'ownership_transfer',      '货权转移(购销)',               'D04.05', 'd04.ownership.transfer', 1, 1, 24, '["D04.05"]', 1, 1),
(1, 'purchase_request',        '采购申请',                     'D06.01', 'd06.purchase.request',   1, 1, 24, '["D06.01"]', 1, 1),
(1, 'purchase_order_over',     '采购单超阈值/取消/反审核',     'D06.02', 'd06.purchase.orderOver', 1, 0, 24, '["D06.02"]', 1, 1),
(1, 'purchase_damage_accept',  '残损让步接收/索赔放弃',        'D06.03', 'd06.purchase.damage',    1, 0, 24, '["D06.03"]', 1, 1),
(1, 'payment_apply',           '供应商付款申请',               'D06.04', 'd06.payment.apply',      1, 0, 24, '["D06.04"]', 1, 1),
(1, 'refund_over_limit',       '超额退款',                     'D05.03', 'd05.refund.overLimit',   1, 0, 24, '["D05.03"]', 1, 1),
(1, 'settle_internal_review',  '结算单内部审核',               'D08.02', 'd08.settle.review',      1, 0, 24, '["D08.02"]', 1, 1),
(1, 'settle_adjust_over',      '结算差异调整超阈值',           'D08.02', 'd08.settle.adjustOver',  1, 0, 24, '["D08.02"]', 1, 1),
(1, 'settle_red_flush',        '结算单红冲',                   'D08.02', 'd08.settle.redFlush',    1, 1, 24, '["D08.02"]', 1, 1),
(1, 'writeoff_force',          '强制核销/反核销',              'D08.03', 'd08.writeoff.force',     1, 0, 24, '["D08.03"]', 1, 1),
(1, 'period_reopen',           '反结账/豁免结账',              'D08.03', 'd08.period.reopen',      1, 1, 24, '["D08.03","D08.01"]', 1, 1),
(1, 'bad_debt',                '坏账处理',                     'D08.03', 'd08.baddebt.handle',     1, 0, 24, '["D08.03"]', 1, 1),
(1, 'freight_red_flush',       '运费对账红冲重开',             'D08.04', 'd08.freight.redFlush',   1, 1, 24, '["D08.04"]', 1, 1),
(1, 'shop_owner_transfer',     '店铺换货主(资产转移)',         'D10.01', 'd10.org.shopTransfer',   1, 1, 24, '["D10.01"]', 1, 1),
(1, 'owner_status_change',     '货主暂停/终止',                'D10.01', 'd10.org.ownerStatus',    1, 1, 24, '["D10.01"]', 1, 1),
(1, 'settle_config_change',    '货主结算配置变更',             'D10.01', 'd10.org.settleConfig',   1, 1, 24, '["D10.01"]', 1, 1),
(1, 'declare_element_change',  '跨境申报要素人工修改/账册差异强制调整', 'D03.12', 'd03.declare.elementChange', 1, 1, 24, '["D03.12"]', 1, 1);

-- 7.7 审批阈值全局默认样例（各业务域阈值语义见其 SRS；此处为初始化必备默认）
INSERT INTO org_approval_threshold (tenant_id, scene_code, dim_condition_json, dim_specificity, rule_expr, need_approval, rule_version, priority, status, update_op) VALUES
(1, 'stock_manual_adjust',   NULL, 0, 'abs_qty>10 OR value_amount>5000',              1, 1, 0, 1, 'system'),
(1, 'refund_over_limit',     NULL, 0, 'refund_amount>2000',                           1, 1, 0, 1, 'system'),
(1, 'settle_internal_review',NULL, 0, 'settle_amount>500000',                         1, 1, 0, 1, 'system'),
(1, 'purchase_damage_accept',NULL, 0, 'damage_value>2000',                            1, 1, 0, 1, 'system'),
(1, 'order_price_change',    NULL, 0, 'abs_change_amount>100 OR change_ratio>0.1',    1, 1, 0, 1, 'system');

-- 7.8 敏感字段权限注册样例（D10.03 FR-05a）
INSERT INTO org_field_perm (tenant_id, entity_name, field_name, perm_code, mask_rule, portal_forbidden, status) VALUES
(1, 'inv_stock_ledger',  'unit_cost',       'field.stock.cost.view',   '',      1, 1),
(1, 'inv_stock_ledger',  'inventory_cost',  'field.stock.cost.view',   '',      1, 1),
(1, 'pur_order',         'supply_price',    'field.po.price.view',     '',      1, 1),
(1, 'fin_settlement',    'margin_amount',   'field.settle.margin.view','',      1, 1),
(1, 'ord_order',         'receiver_mobile', 'field.pii.plaintext.view','phone', 0, 1),
(1, 'ord_order',         'receiver_name',   'field.pii.plaintext.view','name',  0, 1),
(1, 'ord_order',         'receiver_address','field.pii.plaintext.view','address',0, 1);

-- 7.9 实体过滤声明样例（D10.03 FR-04b，各域随迁移脚本注册）
INSERT INTO org_filterable_entity (tenant_id, entity_name, schema_name, table_name, dim_columns_json, module_code, status) VALUES
(1, 'ord_order',       'oms_order', 'ord_order',       '{"tenant_id":"tenant_id","owner_id":"owner_id","shop_id":"shop_id","branch_id":null,"brand_id":null}', 'D03.01', 1),
(1, 'inv_stock_ledger','oms_stock', 'inv_stock_ledger','{"tenant_id":"tenant_id","owner_id":"owner_id","shop_id":null,"branch_id":"branch_id","brand_id":null}', 'D04.02', 1),
(1, 'inv_material',    'oms_stock', 'inv_material',    '{"tenant_id":"tenant_id","owner_id":"owner_id","shop_id":null,"branch_id":null,"brand_id":"brand_id"}', 'D04.01', 1);

USE oms_audit;

-- 7.10 审计保留策略（D10.06 FR-08a 分级 + FR-08c PIPL 专项）
INSERT INTO aud_retention_policy (policy_level, policy_type, online_months, archive_years, pii_anonymize_months, policy_version, status, update_op) VALUES
(3, 'audit', 12, 5,  0,  1, 1, 'system'),
(2, 'audit', 12, 3,  0,  1, 1, 'system'),
(1, 'audit', 6,  1,  0,  1, 1, 'system'),
(1, 'pipl',  12, 3,  36, 1, 1, 'system');

-- ============================================================================
-- 脚本结束 · oms_org 28 张 + oms_audit 6 张（共 34 张）+ 初始字典数据
-- 自查: 括号/逗号/分号配对、COMMENT 内无未转义引号(->代替→,!=代替≠)、
--       JSON 默认值均为 NULL 或显式提供、避开 MySQL8 保留字
--       (grant_type->grant_scope / condition->dim_condition_json / system->actor_type码值)
-- ============================================================================
