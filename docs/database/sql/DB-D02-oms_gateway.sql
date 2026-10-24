-- =====================================================================
-- DB-D02 oms_gateway 平台Gateway域 建表脚本（MySQL 8.0）
-- 版本 V1.0 · 2026-10-24 · 依据：DB-00 总册 + DB-D02 数据字典
-- 执行顺序：DB-00 建库约定之后、业务域（oms_order 等）之前执行本脚本
-- 约定：不建物理外键；utf8mb4/utf8mb4_0900_ai_ci/InnoDB；公共字段见 DB-00 §3
-- 分表：gw_api_log / gw_openapi_log 按月分表（_YYYYMM），本脚本建基表模板，
--       月表由调度器 CREATE TABLE ... LIKE 滚动创建（文末附示例，注释态）
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS oms_gateway DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE oms_gateway;

-- ---------------------------------------------------------------------
-- 1. gw_platform_config 平台应用配置（SRS-D02.01 §6.1）
-- ---------------------------------------------------------------------
CREATE TABLE gw_platform_config (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID（内部租户=1）',
  owner_id            BIGINT UNSIGNED NULL COMMENT '货主ID（纯配置表免填）',
  platform            VARCHAR(32)  NOT NULL COMMENT '平台标识：taobao/jd/pdd/xhs/vop/douyin/wechat/kuaishou',
  app_bn              VARCHAR(64)  NOT NULL COMMENT '应用ID（平台侧AppKey标识，业务键）',
  app_key             VARCHAR(128) NOT NULL COMMENT '平台应用key（非敏感明文）',
  app_secret_enc      VARBINARY(1024) NOT NULL COMMENT '应用secret密文（KMS信封加密）',
  key_version         VARCHAR(32)  NOT NULL DEFAULT 'v1' COMMENT '加密密钥版本（轮换支持）',
  gateway_url         VARCHAR(256) NOT NULL COMMENT '生产网关地址',
  sandbox_gateway_url VARCHAR(256) NULL COMMENT '沙箱网关地址',
  api_version         VARCHAR(32)  NOT NULL DEFAULT '2.0' COMMENT 'API版本',
  sign_strategy       VARCHAR(32)  NOT NULL COMMENT '签名策略：md5-top/hmac-sha256/bearer/jd-3des',
  rate_limit_json     JSON         NULL COMMENT '平台级默认频控：{qps,daily_quota,method_override}',
  callback_url        VARCHAR(256) NULL COMMENT '授权/消息回调地址',
  status              VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '状态：enabled启用/disabled停用/sandbox沙箱',
  source              VARCHAR(16)  NOT NULL DEFAULT 'local' COMMENT '数据来源：api/local/import/migration',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_gw_platform_config_platform_app_bn (platform, app_bn),
  KEY idx_gw_platform_config_status (status)
) ENGINE=InnoDB COMMENT='平台应用配置（D02.01）';

-- ---------------------------------------------------------------------
-- 2. gw_adapter_config 适配器注册配置（SRS-D02.02 §6.3）
-- ---------------------------------------------------------------------
CREATE TABLE gw_adapter_config (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id          BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id           BIGINT UNSIGNED NULL COMMENT '货主ID（配置表免填）',
  adapter_code       VARCHAR(64) NOT NULL COMMENT '适配器编码（唯一，如taobao-adapter）',
  platform           VARCHAR(32) NOT NULL COMMENT '平台标识（枚举同gw_platform_config.platform）',
  adapter_version    VARCHAR(32) NOT NULL COMMENT '适配器版本（转换追溯，写入order_buffer）',
  capability_json    JSON        NOT NULL COMMENT '能力组与方法级白名单：{groups:[],methods:[]}',
  native_method_json JSON        NOT NULL COMMENT '统一方法名→平台原生API名映射',
  special_flags_json JSON        NULL COMMENT '特殊能力开关：设备指纹头/京配判断/面单前置校验等',
  status             VARCHAR(16) NOT NULL DEFAULT 'enabled' COMMENT '状态：enabled启用/disabled停用/gray灰度',
  create_time        DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version            INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted         TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_gw_adapter_config_adapter_code (adapter_code),
  KEY idx_gw_adapter_config_platform (platform)
) ENGINE=InnoDB COMMENT='平台适配器注册配置（D02.02）';

-- ---------------------------------------------------------------------
-- 3. gw_enum_mapping 状态与编码映射（SRS-D02.02 §6.2）
-- ---------------------------------------------------------------------
CREATE TABLE gw_enum_mapping (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NULL COMMENT '货主ID（字典表免填）',
  platform        VARCHAR(32)  NOT NULL COMMENT '平台标识',
  map_type        VARCHAR(32)  NOT NULL COMMENT '映射类型：order_status/logistics_code/aftersale_status/aftersale_reason',
  native_value    VARCHAR(128) NOT NULL COMMENT '平台原生值（保留原样字符串）',
  canonical_value VARCHAR(128) NOT NULL COMMENT '标准值（对应canonical枚举）',
  map_version     INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '映射版本（变更递增留痕）',
  status          VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '状态：enabled启用/disabled停用',
  create_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted      TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_gw_enum_mapping_key (platform, map_type, native_value, map_version)
) ENGINE=InnoDB COMMENT='平台状态与编码映射字典（D02.02）';

-- ---------------------------------------------------------------------
-- 4. gw_ratelimit_config 接口限流配置（SRS-D02.01 FR-06）
-- ---------------------------------------------------------------------
CREATE TABLE gw_ratelimit_config (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id         BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NULL COMMENT '货主ID（配置表免填）',
  scope_type        VARCHAR(16)  NOT NULL COMMENT '作用域类型：platform/app/shop/method',
  scope_key         VARCHAR(64)  NOT NULL COMMENT '作用域键（平台码/应用ID/shop_id/统一方法名）',
  method            VARCHAR(128) NOT NULL DEFAULT '' COMMENT '限定方法（空串=作用域内全部方法）',
  qps_limit         INT UNSIGNED NOT NULL DEFAULT 10 COMMENT 'QPS上限',
  daily_quota       INT UNSIGNED NULL COMMENT '日配额（NULL=不限）',
  concurrency_limit INT UNSIGNED NULL COMMENT '并发上限（NULL=不限）',
  status            VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '状态：enabled启用/disabled停用',
  create_time       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted        TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_gw_ratelimit_config_scope (scope_type, scope_key, method)
) ENGINE=InnoDB COMMENT='接口限流配置（D02.01）';

-- ---------------------------------------------------------------------
-- 5. gw_shop 店铺档案（SRS-D02.06 §6.1）← 商派 ome.shop 改造
-- ---------------------------------------------------------------------
CREATE TABLE gw_shop (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键（全域引用键shop_id）',
  tenant_id         BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NOT NULL COMMENT '货主ID（LFK→oms_org.org_owner，跨域）',
  shop_bn           VARCHAR(32)  NOT NULL COMMENT '店铺编码（Redis发号）',
  shop_name         VARCHAR(128) NOT NULL COMMENT '店铺名称',
  platform          VARCHAR(32)  NOT NULL COMMENT '平台标识：taobao/jd/pdd/xhs/vop/douyin/wechat/kuaishou',
  platform_shop_id  VARCHAR(64)  NOT NULL COMMENT '平台侧店铺标识（sellerId/sid）',
  app_id            BIGINT UNSIGNED NOT NULL COMMENT '所属应用（LFK→gw_platform_config.id）',
  org_node_id       BIGINT UNSIGNED NOT NULL COMMENT '组织节点（LFK→oms_org.org_node，跨域；挂载关系归org域）',
  shop_type         VARCHAR(16)  NOT NULL DEFAULT 'direct' COMMENT '店铺类型：direct直营/flagship旗舰店/franchise加盟/store门店O2O/dealer经销(预留)',
  business_type     VARCHAR(16)  NOT NULL DEFAULT 'direct_sale' COMMENT '业务类型：direct_sale直销/distribution分销/dealer经销(预留)',
  auth_status       VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT '授权状态冗余：pending待授权/normal正常/expired过期/disabled停用（权威=gw_shop_auth.status）',
  seller_info_json  JSON         NULL COMMENT '平台店铺信息快照（店铺名/主体名回填校验）',
  auth_mode         VARCHAR(16)  NULL COMMENT '授权模式：self自助/agent代授权',
  auth_url_track    VARCHAR(16)  NULL COMMENT '授权链接追踪：sent已发送/clicked已点击/done已完成',
  status            VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '档案状态：enabled启用/disabled停用',
  source            VARCHAR(16)  NOT NULL DEFAULT 'local' COMMENT '数据来源：api/local/import/migration',
  create_time       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted        TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_gw_shop_shop_bn (shop_bn),
  UNIQUE KEY uk_gw_shop_platform_shop (platform, platform_shop_id),
  KEY idx_gw_shop_owner (owner_id),
  KEY idx_gw_shop_auth_status (auth_status)
) ENGINE=InnoDB COMMENT='店铺档案（D02.06；组织挂载关系在oms_org域）';

-- ---------------------------------------------------------------------
-- 6. gw_shop_auth 店铺授权凭证（SRS-D02.06 §6.1）
-- ---------------------------------------------------------------------
CREATE TABLE gw_shop_auth (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id          BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id           BIGINT UNSIGNED NULL COMMENT '货主ID（冗余gw_shop.owner_id）',
  shop_id            BIGINT UNSIGNED NOT NULL COMMENT '店铺（LFK→gw_shop.id，一店一凭证行）',
  access_token_enc   VARBINARY(2048) NULL COMMENT 'access_token密文（KMS信封加密，禁止明文）',
  refresh_token_enc  VARBINARY(2048) NULL COMMENT 'refresh_token密文',
  session_enc        VARBINARY(2048) NULL COMMENT 'session/cookie凭证密文（部分平台）',
  key_version        VARCHAR(32)  NOT NULL DEFAULT 'v1' COMMENT '加密密钥版本（轮换，7天双版本保留）',
  token_expires_at   DATETIME(3)  NULL COMMENT 'access_token有效期（巡检依据）',
  refresh_expires_at DATETIME(3)  NULL COMMENT 'refresh_token有效期',
  last_refresh_time  DATETIME(3)  NULL COMMENT '最近续期成功时间',
  refresh_fail_times INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '连续续期失败次数（超限告警转人工）',
  status             VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT '状态机：pending待授权/normal正常/expired过期/disabled停用',
  create_time        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version            INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  PRIMARY KEY (id),
  UNIQUE KEY uk_gw_shop_auth_shop (shop_id),
  KEY idx_gw_shop_auth_expires (status, token_expires_at)
) ENGINE=InnoDB COMMENT='店铺授权凭证（D02.06；状态机pending→normal→expired→disabled）';

-- ---------------------------------------------------------------------
-- 7. gw_shop_config 店铺履约参数配置（SRS-D02.06 §6.2）
-- ---------------------------------------------------------------------
CREATE TABLE gw_shop_config (
  id                     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id              BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id               BIGINT UNSIGNED NULL COMMENT '货主ID（冗余）',
  shop_id                BIGINT UNSIGNED NOT NULL COMMENT '店铺（LFK→gw_shop.id，唯一）',
  branch_bind_json       JSON         NULL COMMENT '店铺-仓绑定有序数组：[{branch_id(LFK→oms_fulfill.ful_branch跨域),priority}]',
  default_logistics_code VARCHAR(32)  NULL COMMENT '默认物流编码（LFK→oms_fulfill.ful_dly_corp.corp_code跨域）',
  platform_waybill_flag  TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '平台管控面单标识：0否/1是（D09.05消费）',
  sender_address_json    JSON         NULL COMMENT '发货地址（多地址）：[{province,city,district,address,contact,mobile_enc}]',
  back_node              VARCHAR(16)  NOT NULL DEFAULT 'shipped' COMMENT '回传时机：shipped发货时/print打印时/verify验货时（D02.04消费）',
  poll_override_json     JSON         NULL COMMENT '拉单轮询参数覆写：{poll_interval,overlap,safety_delay}（空=用水位表默认）',
  sync_strategy_ref      VARCHAR(64)  NULL COMMENT '库存同步策略引用（D04.08策略编码）',
  create_time            DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time            DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version                INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted             TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_gw_shop_config_shop (shop_id)
) ENGINE=InnoDB COMMENT='店铺履约参数配置（D02.06 §6.2）';

-- ---------------------------------------------------------------------
-- 8. gw_credential_audit 凭证审计流水（SRS-D02.06 §6.3；只增不改禁软删）
-- ---------------------------------------------------------------------
CREATE TABLE gw_credential_audit (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id      BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  shop_id        BIGINT UNSIGNED NOT NULL COMMENT '店铺（LFK→gw_shop.id）',
  action         VARCHAR(16)  NOT NULL COMMENT '动作：use取用/refresh续期/reauth重授权/revoke吊销',
  caller         VARCHAR(64)  NOT NULL COMMENT '调用方（服务名/任务名/操作人）',
  method         VARCHAR(128) NULL COMMENT '使用场景（统一方法名）',
  request_time   DATETIME(3)  NOT NULL COMMENT '请求时间',
  result         VARCHAR(16)  NOT NULL COMMENT '结果：succ成功/fail失败/denied拒绝',
  old_key_version VARCHAR(32) NULL COMMENT '旧凭证密钥版本（7天保留期标记）',
  create_time    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  KEY idx_gw_credential_audit_shop_time (shop_id, request_time),
  KEY idx_gw_credential_audit_time (request_time)
) ENGINE=InnoDB COMMENT='凭证审计流水（D02.06 §6.3，只增不改）';

-- ---------------------------------------------------------------------
-- 9. gw_api_log API调用日志基表（SRS-D02.01 §6.2；按月分表模板）← 商派 ome.api_log 改造
-- ---------------------------------------------------------------------
CREATE TABLE gw_api_log (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  log_bn          VARCHAR(32)  NOT NULL COMMENT '日志ID（雪花ID字符串，跨分表引用键）',
  direction       TINYINT      NOT NULL DEFAULT 1 COMMENT '方向：1出向(OMS→平台)/2入向(平台→OMS)',
  method          VARCHAR(128) NOT NULL COMMENT '统一方法名',
  native_method   VARCHAR(128) NULL COMMENT '平台原生方法名',
  platform        VARCHAR(32)  NOT NULL COMMENT '平台标识',
  shop_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺（0=平台级调用）',
  primary_bn      VARCHAR(64)  NULL COMMENT '业务单号（订单号/发货单号，贯穿排查）',
  request_params  TEXT         NULL COMMENT '请求参数（>2KB截断，is_truncated=1）',
  response_body   TEXT         NULL COMMENT '响应报文摘要（超阈值截断）',
  is_truncated    TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '截断标记：0否/1是',
  oss_ref         VARCHAR(256) NULL COMMENT '大报文OSS原文引用（bucket/key）',
  http_status     INT          NULL COMMENT 'HTTP状态码',
  err_code        VARCHAR(64)  NULL COMMENT '统一错误码（gw_errcode_dict归一后）',
  err_level       VARCHAR(16)  NULL COMMENT '错误分级：RETRYABLE可重试/RATE_LIMITED退避限流/AUTH需授权/MANUAL需人工/FATAL停重试',
  spendtime_ms    INT UNSIGNED NULL COMMENT '耗时（毫秒）',
  msg_id          VARCHAR(64)  NULL COMMENT '平台消息号（平台侧对账用）',
  source          VARCHAR(16)  NOT NULL COMMENT '调用来源：pull拉单/writeback回传/retry重试/passthrough透传/reconcile对账',
  retry_of        BIGINT UNSIGNED NULL COMMENT '重试关联原日志id（LFK→本表）',
  operator        VARCHAR(64)  NULL COMMENT '操作人（透传/人工重放时，审计）',
  create_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间（=调用发起时间，分表路由键）',
  PRIMARY KEY (id),
  UNIQUE KEY uk_gw_api_log_log_bn (log_bn),
  KEY idx_gw_api_log_shop_time (shop_id, create_time),
  KEY idx_gw_api_log_primary_bn (primary_bn),
  KEY idx_gw_api_log_msg_id (msg_id)
) ENGINE=InnoDB COMMENT='API调用日志基表（D02.01；按月分表gw_api_log_YYYYMM，在线3个月）';
-- 月表示例（由调度器滚动创建）：
-- CREATE TABLE gw_api_log_202611 LIKE gw_api_log;

-- ---------------------------------------------------------------------
-- 10. gw_rpc_pending 在途调用登记（SRS-D02.01 §6.3）
-- ---------------------------------------------------------------------
CREATE TABLE gw_rpc_pending (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id      BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  method         VARCHAR(128) NOT NULL COMMENT '统一方法名',
  shop_id        BIGINT UNSIGNED NOT NULL COMMENT '店铺（LFK→gw_shop.id）',
  primary_bn     VARCHAR(64)  NOT NULL COMMENT '业务单号（定位键）',
  params_snapshot TEXT        NULL COMMENT '参数快照（重放依据，>2KB存oss_ref）',
  oss_ref        VARCHAR(256) NULL COMMENT '大参数OSS引用',
  timeout_at     DATETIME(3)  NOT NULL COMMENT '超时时间（到期触发扫描反查）',
  scan_times     INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '已扫描次数',
  status         VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT '状态：pending在途/verified已核实/to_fail已转失败',
  source_log_id  BIGINT UNSIGNED NULL COMMENT '关联gw_api_log.id',
  create_time    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version        INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  PRIMARY KEY (id),
  KEY idx_gw_rpc_pending_status_timeout (status, timeout_at),
  KEY idx_gw_rpc_pending_bn (primary_bn)
) ENGINE=InnoDB COMMENT='写类调用在途登记（D02.01 §6.3；超时反查后转核实或转失败）';

-- ---------------------------------------------------------------------
-- 11. gw_api_fail 失败重试登记（SRS-D02.05 §6.1）← 商派 ome.api_fail 改造
-- ---------------------------------------------------------------------
CREATE TABLE gw_api_fail (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id        BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  obj_type         VARCHAR(32)  NOT NULL COMMENT '单据类型：delivery/stock_batch/aftersale/order_pull/order_buffer/writeback等',
  primary_bn       VARCHAR(64)  NOT NULL COMMENT '业务单号',
  sub_bn           VARCHAR(64)  NULL COMMENT '子单号',
  method           VARCHAR(128) NOT NULL COMMENT '统一方法名',
  native_method    VARCHAR(128) NULL COMMENT '平台原生方法',
  platform         VARCHAR(32)  NOT NULL COMMENT '平台标识',
  shop_id          BIGINT UNSIGNED NOT NULL COMMENT '店铺（LFK→gw_shop.id；熔断与挂起按店铺操作）',
  replay_ref       VARCHAR(128) NULL COMMENT '重放引用：业务引用ID优先（writeback_task_id/buffer_id）',
  replay_params    TEXT         NULL COMMENT '参数快照（无业务引用时兜底，>2KB截断+oss_ref）',
  oss_ref          VARCHAR(256) NULL COMMENT '大参数OSS引用',
  err_code         VARCHAR(64)  NOT NULL COMMENT '错误码（字典归一后）',
  err_msg          VARCHAR(512) NULL COMMENT '错误原文（截断）',
  err_level        VARCHAR(16)  NOT NULL COMMENT '框架分级：RETRYABLE/RATE_LIMITED/AUTH/MANUAL/FATAL',
  write_flag       TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '写类标记：0读/1写（写类重试前强制反查）',
  fail_times       INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '重放失败次数',
  probe_fail_times INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '反查失败次数（分开计数）',
  next_retry_time  DATETIME(3)  NULL COMMENT '下次重试时间（分级退避）',
  is_dead          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '死信标记：0否/1是（超限转人工）',
  status           VARCHAR(16)  NOT NULL DEFAULT 'waiting' COMMENT '状态：waiting等待/retrying重试中/succ成功/manual转人工/dead死信/suspended店铺挂起/deleted终态清理',
  resolved_by      VARCHAR(16)  NULL COMMENT '解决方式：retry重试成功/reconcile反查已生效/manual人工/biz_closed业务关闭',
  advice           VARCHAR(512) NULL COMMENT '处置建议（来自gw_errcode_dict，工作台展示）',
  source_log_id    BIGINT UNSIGNED NULL COMMENT '关联gw_api_log.id（追溯链）',
  writeback_task_id BIGINT UNSIGNED NULL COMMENT '关联gw_writeback_task.id',
  last_retry_time  DATETIME(3)  NULL COMMENT '最近重试时间',
  finish_time      DATETIME(3)  NULL COMMENT '终态时间（重试时效统计）',
  create_time      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  PRIMARY KEY (id),
  KEY idx_gw_api_fail_status_retry (status, next_retry_time),
  KEY idx_gw_api_fail_shop (shop_id, status),
  KEY idx_gw_api_fail_bn (primary_bn),
  KEY idx_gw_api_fail_cluster (platform, method, err_code)
) ENGINE=InnoDB COMMENT='失败重试登记（D02.05 §6.1；死信聚类键=platform+method+err_code）';

-- ---------------------------------------------------------------------
-- 12. gw_errcode_dict 错误码字典（SRS-D02.01 §6.4）
-- ---------------------------------------------------------------------
CREATE TABLE gw_errcode_dict (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id   BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  platform    VARCHAR(32)  NOT NULL COMMENT '平台标识（common=全平台通用）',
  native_code VARCHAR(64)  NULL COMMENT '平台原生错误码（与err_pattern二选一或并用）',
  err_pattern VARCHAR(256) NULL COMMENT '错误文本正则匹配模式',
  err_level   VARCHAR(16)  NOT NULL COMMENT '分级：RETRYABLE可重试/RATE_LIMITED退避限流/AUTH需重新授权/MANUAL需人工/FATAL停止重试',
  advice      VARCHAR(512) NULL COMMENT '处置建议（人工工作台展示）',
  note        VARCHAR(256) NULL COMMENT '备注',
  status      VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '状态：enabled启用/disabled停用',
  create_time DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version     INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted  TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  KEY idx_gw_errcode_dict_platform_code (platform, native_code)
) ENGINE=InnoDB COMMENT='错误码字典（D02.01 §6.4；精确码优先、正则兜底）';

-- ---------------------------------------------------------------------
-- 13. gw_order_buffer 订单缓冲头（SRS-D02.03 §6.1 canonical，D02→D03投递契约）
-- ---------------------------------------------------------------------
CREATE TABLE gw_order_buffer (
  id                       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键（buffer_id）',
  tenant_id                BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id                 BIGINT UNSIGNED NOT NULL COMMENT '货主ID（冗余店铺货主）',
  buffer_bn                VARCHAR(32)  NOT NULL COMMENT '缓冲单号（Redis发号）',
  platform                 VARCHAR(32)  NOT NULL COMMENT '平台标识',
  shop_id                  BIGINT UNSIGNED NOT NULL COMMENT '店铺（LFK→gw_shop.id；幂等键成分）',
  platform_order_bn        VARCHAR(64)  NOT NULL COMMENT '平台订单号（幂等键成分）',
  order_type               VARCHAR(16)  NOT NULL DEFAULT 'normal' COMMENT '订单类型：normal普通/presale预售/group团购/jit JIT采购(唯品会)/virtual虚拟/exchange0换货0元单',
  platform_status          VARCHAR(32)  NULL COMMENT '平台原始状态（保留原样）',
  canonical_status         VARCHAR(16)  NOT NULL COMMENT '标准状态：unpaid待付款/unshipped待发货/shipped已发货/closed已关闭/finished已完成',
  platform_modified        DATETIME(3)  NOT NULL COMMENT '平台最后修改时间（版本收敛依据，旧版本丢弃）',
  pay_time                 DATETIME(3)  NULL COMMENT '平台付款时间（时效考核基准）',
  platform_create_time     DATETIME(3)  NULL COMMENT '平台下单时间',
  total_amount             DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '商品总额',
  customer_paid            DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '客户实付（双口径必填）',
  platform_bear_total      DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '平台承担合计',
  freight                  DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '运费',
  buyer_message            VARCHAR(512) NULL COMMENT '买家留言',
  seller_memo              VARCHAR(512) NULL COMMENT '卖家备注（含改单指令语义时由D03解析）',
  receiver_name_enc        VARBINARY(512)  NULL COMMENT '收货人姓名密文（PIPL，D01.05信封加密）',
  receiver_mobile_enc      VARBINARY(512)  NULL COMMENT '收货人手机密文',
  receiver_mobile_hash     VARBINARY(64)   NULL COMMENT '手机盲索引（HMAC，检索用）',
  receiver_province        VARCHAR(32)  NULL COMMENT '收货省',
  receiver_city            VARCHAR(32)  NULL COMMENT '收货市',
  receiver_district        VARCHAR(32)  NULL COMMENT '收货区',
  receiver_address_enc     VARBINARY(1024) NULL COMMENT '详细地址密文',
  receiver_zip             VARCHAR(16)  NULL COMMENT '邮编',
  oaid_json                JSON         NULL COMMENT '平台密文单收件人标识（oaid/密文通道原文，单存不解密）',
  receiver_encrypted_channel VARCHAR(16) NOT NULL DEFAULT 'none' COMMENT '收件人加密通道：none明文/oaid平台密文/virtual虚拟号（决定面单与解密路径）',
  warehouse_hint           VARCHAR(64)  NULL COMMENT '平台指定仓提示（如天猫国际保税仓）',
  logistics_hint           VARCHAR(64)  NULL COMMENT '平台物流提示（如京东京配）',
  platform_extra           JSON         NULL COMMENT '平台特有字段：{platform:{...}}（关键字段生成列索引）',
  convert_warnings         JSON         NULL COMMENT '转换告警数组：未知状态/比例分摊/字段缺失降级',
  adapter_version          VARCHAR(32)  NULL COMMENT '适配器版本（追溯）',
  mapping_version          VARCHAR(32)  NULL COMMENT '映射规则版本（追溯）',
  deliver_status           VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT '投递状态：pending待投递/delivered已投递/accepted已接收/waiting建档等待/fail投递失败/manual人工处理/closed已关闭',
  deliver_times            INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '投递次数（退避重试依据）',
  last_deliver_time        DATETIME(3)  NULL COMMENT '最近投递时间',
  source                   VARCHAR(16)  NOT NULL DEFAULT 'api' COMMENT '数据来源：api/local/import/migration',
  create_time              DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time              DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version                  INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted               TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_gw_order_buffer_idem (shop_id, platform_order_bn),
  UNIQUE KEY uk_gw_order_buffer_bn (buffer_bn),
  KEY idx_gw_order_buffer_status (deliver_status, create_time),
  KEY idx_gw_order_buffer_modified (shop_id, platform_modified),
  KEY idx_gw_order_buffer_mobile_hash (receiver_mobile_hash)
) ENGINE=InnoDB COMMENT='订单缓冲头canonical标准模型（D02.03 §6.1；投递D03后滚动归档）';

-- ---------------------------------------------------------------------
-- 14. gw_order_buffer_item 订单缓冲行（SRS-D02.03 §6.1）
-- ---------------------------------------------------------------------
CREATE TABLE gw_order_buffer_item (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id          BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  buffer_id          BIGINT UNSIGNED NOT NULL COMMENT '缓冲头（LFK→gw_order_buffer.id）',
  line_no            INT UNSIGNED NOT NULL COMMENT '行号',
  oid                VARCHAR(64)  NULL COMMENT '平台子单号（售后对账键）',
  platform_sku_id    VARCHAR(64)  NOT NULL COMMENT '平台SKU ID（outer_id）',
  platform_item_id   VARCHAR(64)  NULL COMMENT '平台商品ID',
  goods_name         VARCHAR(256) NULL COMMENT '商品名（平台侧）',
  sku_spec           VARCHAR(256) NULL COMMENT '规格（平台侧）',
  local_sku_id       BIGINT UNSIGNED NULL COMMENT '映射后本地SKU（LFK→oms_stock.inv_sku跨域；未映射为空）',
  num                INT          NOT NULL DEFAULT 1 COMMENT '数量',
  sale_price         DECIMAL(18,4) NOT NULL DEFAULT 0 COMMENT '成交单价',
  customer_paid_line DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '行客户实付（分摊后）',
  platform_bear_line DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '行平台承担',
  merchant_bear_line DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '行商家承担',
  refund_status      VARCHAR(16)  NOT NULL DEFAULT 'none' COMMENT '行级退款标识：none无/refunding退款中/refunded已退款',
  gift_flag          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '赠品标记：0否/1是',
  platform_extra     JSON         NULL COMMENT '平台特有行字段',
  create_time        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_gw_order_buffer_item_line (buffer_id, line_no),
  KEY idx_gw_order_buffer_item_oid (oid)
) ENGINE=InnoDB COMMENT='订单缓冲行（D02.03 §6.1 order_buffer_item）';

-- ---------------------------------------------------------------------
-- 15. gw_order_buffer_promotion 订单优惠分摊明细（SRS-D02.03 §6.1）
-- ---------------------------------------------------------------------
CREATE TABLE gw_order_buffer_promotion (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id        BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  buffer_id        BIGINT UNSIGNED NOT NULL COMMENT '缓冲头（LFK→gw_order_buffer.id）',
  promotion_id     VARCHAR(64)  NOT NULL COMMENT '平台优惠活动ID',
  promotion_type   VARCHAR(32)  NOT NULL COMMENT '类型：platform_coupon平台券/shop_coupon店铺券/full_reduce满减/subsidy补贴',
  amount           DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '优惠金额',
  bear_by          VARCHAR(16)  NOT NULL COMMENT '承担方：platform平台/merchant商家/mixed混合',
  line_allocations JSON         NULL COMMENT '行分摊：[{line_no,amount}]',
  create_time      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  KEY idx_gw_order_buffer_promotion_buffer (buffer_id)
) ENGINE=InnoDB COMMENT='订单优惠分摊明细（D02.03 §6.1 order_buffer_promotion）';

-- ---------------------------------------------------------------------
-- 16. gw_msg_notify 平台消息缓冲（SRS-D02.03 §6.2；订单/售后/商品消息共用）
-- ---------------------------------------------------------------------
CREATE TABLE gw_msg_notify (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  platform        VARCHAR(32)  NOT NULL COMMENT '平台标识（幂等键成分）',
  shop_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '店铺（0=平台级消息；幂等键成分）',
  msg_id          VARCHAR(64)  NOT NULL COMMENT '平台消息号（幂等键成分）',
  msg_type        VARCHAR(32)  NOT NULL COMMENT '消息类型：trade订单/trade_close/aftersale售后/product商品/other其他',
  route_target    VARCHAR(16)  NOT NULL DEFAULT 'unknown' COMMENT '路由目标：order订单域/aftersale售后域/product商品域/unknown未知(人工)',
  payload         TEXT         NULL COMMENT '原始报文（>2KB截断）',
  is_truncated    TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '截断标记：0否/1是',
  oss_ref         VARCHAR(256) NULL COMMENT '原始报文OSS引用',
  status          VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT '消费状态：pending待消费/processing消费中/succ成功/fail失败/dead死信',
  fail_times      INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '失败次数',
  next_retry_time DATETIME(3)  NULL COMMENT '下次重试时间',
  received_time   DATETIME(3)  NOT NULL COMMENT '接收时间',
  consumed_time   DATETIME(3)  NULL COMMENT '消费完成时间（延迟指标=consumed-received）',
  create_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  PRIMARY KEY (id),
  UNIQUE KEY uk_gw_msg_notify_idem (platform, shop_id, msg_id),
  KEY idx_gw_msg_notify_status (status, next_retry_time),
  KEY idx_gw_msg_notify_type_time (msg_type, received_time)
) ENGINE=InnoDB COMMENT='平台消息缓冲TMC/webhook（D02.03 §6.2；售后/商品消息按msg_type区分复用）';

-- ---------------------------------------------------------------------
-- 17. gw_pull_watermark 店铺拉单水位（SRS-D02.03 §6.3）← 商派 ome.shop.last_download_time 改造
-- ---------------------------------------------------------------------
CREATE TABLE gw_pull_watermark (
  id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id             BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  shop_id               BIGINT UNSIGNED NOT NULL COMMENT '店铺（LFK→gw_shop.id）',
  channel               VARCHAR(16)  NOT NULL COMMENT '通道：order订单/aftersale售后/refund退款',
  last_download_time    DATETIME(3)  NOT NULL COMMENT '已成功窗口终点（只进不退，CAS更新）',
  overlap_sec           INT UNSIGNED NOT NULL DEFAULT 300 COMMENT '窗口重叠秒数（默认5min）',
  safety_delay_sec      INT UNSIGNED NOT NULL DEFAULT 60 COMMENT '安全延迟秒数（默认1min）',
  poll_interval_sec     INT UNSIGNED NOT NULL DEFAULT 60 COMMENT '轮询间隔秒数（默认1min，店铺级可配）',
  lag_alert_threshold_sec INT UNSIGNED NOT NULL DEFAULT 1800 COMMENT '落后告警阈值（默认30min）',
  create_time           DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time           DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version               INT UNSIGNED NOT NULL DEFAULT 0 COMMENT 'CAS版本号（水位只进不退）',
  PRIMARY KEY (id),
  UNIQUE KEY uk_gw_pull_watermark_shop_channel (shop_id, channel)
) ENGINE=InnoDB COMMENT='店铺拉单水位（D02.03 §6.3；店铺×通道粒度）';

-- ---------------------------------------------------------------------
-- 18. gw_writeback_task 回传任务台账（SRS-D02.04 §6.1）← 商派 ome.sync_task 改造
-- ---------------------------------------------------------------------
CREATE TABLE gw_writeback_task (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键（task_id）',
  tenant_id         BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NULL COMMENT '货主ID（冗余店铺货主）',
  sync_type         VARCHAR(16)  NOT NULL COMMENT '回传类型：delivery发货/stock库存/aftersale售后/lifecycle生命周期',
  biz_ref           VARCHAR(128) NOT NULL COMMENT '业务单据引用：delivery_id/订单号/平台售后单号/批次#sku',
  platform          VARCHAR(32)  NOT NULL COMMENT '平台标识',
  shop_id           BIGINT UNSIGNED NOT NULL COMMENT '店铺（LFK→gw_shop.id）',
  action            VARCHAR(64)  NOT NULL COMMENT '动作：send/resend(改单)/agree_refund/confirm_receive/cancel等',
  payload_snapshot  JSON         NULL COMMENT 'canonical指令快照（重试与审计依据）',
  trigger_event_id  VARCHAR(64)  NULL COMMENT '触发事件ID（LFK→oms_base.bas_event_outbox跨域）',
  back_node         VARCHAR(16)  NOT NULL DEFAULT 'shipped' COMMENT '实际时机：shipped发货/print打印/verify验货（读gw_shop_config.back_node）',
  status            VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT '状态：pending待处理/processing处理中/succ成功/fail_pending失败待重试/retrying重试中/manual转人工/skipped跳过',
  skip_reason       VARCHAR(64)  NULL COMMENT '跳过原因（结构化枚举：平台管控/无物流编码/店铺停用/业务关闭等）',
  err_code          VARCHAR(64)  NULL COMMENT '失败码（失败时必填）',
  err_level         VARCHAR(16)  NULL COMMENT '错误分级：RETRYABLE/RATE_LIMITED/AUTH/MANUAL/FATAL',
  api_fail_id       BIGINT UNSIGNED NULL COMMENT '重试关联（LFK→gw_api_fail.id）',
  platform_msg_id   VARCHAR(64)  NULL COMMENT '平台回执消息号（对账依据）',
  platform_receipt  VARCHAR(512) NULL COMMENT '平台回执原文摘要',
  retry_count       INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '重试次数',
  spendtime_ms      INT UNSIGNED NULL COMMENT '最近一次耗时（毫秒）',
  idempotent_key    VARCHAR(128) NOT NULL COMMENT '幂等键（sync_type+biz_ref+action+轮次派生）',
  create_time       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  PRIMARY KEY (id),
  UNIQUE KEY uk_gw_writeback_task_idem (idempotent_key),
  KEY idx_gw_writeback_task_status (status, create_time),
  KEY idx_gw_writeback_task_shop (shop_id, sync_type),
  KEY idx_gw_writeback_task_biz (biz_ref)
) ENGINE=InnoDB COMMENT='回传任务台账（D02.04 §6.1 sync_task）';

-- ---------------------------------------------------------------------
-- 19. gw_stock_sync_batch 库存同步批次（SRS-D02.04 §6.2）
-- ---------------------------------------------------------------------
CREATE TABLE gw_stock_sync_batch (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键（batch_id）',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NULL COMMENT '货主ID',
  batch_bn        VARCHAR(32)  NOT NULL COMMENT '批次号（Redis发号）',
  shop_id         BIGINT UNSIGNED NOT NULL COMMENT '店铺（LFK→gw_shop.id）',
  source_task_ref VARCHAR(64)  NULL COMMENT '来源（D04.08可售同步任务号，跨域引用）',
  total_num       INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '批次总数',
  succ_num        INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '成功数',
  fail_num        INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '失败数',
  skipped_num     INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '跳过数',
  status          VARCHAR(16)  NOT NULL DEFAULT 'running' COMMENT '状态：running进行中/done完成/partial部分失败',
  finish_time     DATETIME(3)  NULL COMMENT '完成时间',
  create_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  PRIMARY KEY (id),
  UNIQUE KEY uk_gw_stock_sync_batch_bn (batch_bn),
  KEY idx_gw_stock_sync_batch_shop (shop_id, create_time)
) ENGINE=InnoDB COMMENT='库存同步批次（D02.04 §6.2）';

-- ---------------------------------------------------------------------
-- 20. gw_stock_sync_item 库存同步批次明细（SRS-D02.04 §6.2）
-- ---------------------------------------------------------------------
CREATE TABLE gw_stock_sync_item (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  batch_id        BIGINT UNSIGNED NOT NULL COMMENT '批次（LFK→gw_stock_sync_batch.id）',
  sku_id          BIGINT UNSIGNED NOT NULL COMMENT '本地SKU（LFK→oms_stock.inv_sku跨域）',
  platform_sku_id VARCHAR(64)  NOT NULL COMMENT '平台SKU ID',
  sellable_num    INT          NOT NULL DEFAULT 0 COMMENT '同步的可售数（允许负卖场景用INT）',
  status          VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT '状态：pending待同步/succ成功/fail失败/skipped跳过',
  err_msg         VARCHAR(512) NULL COMMENT '失败原因（回写D04.08同步水位）',
  create_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_gw_stock_sync_item_sku (batch_id, sku_id),
  KEY idx_gw_stock_sync_item_batch (batch_id, status)
) ENGINE=InnoDB COMMENT='库存同步批次明细（D02.04 §6.2；滚动清理）';

-- ---------------------------------------------------------------------
-- 21. gw_recon_diff 对账反查差异流水（SRS-D02.05 §6.2；只增不改禁软删）
-- ---------------------------------------------------------------------
CREATE TABLE gw_recon_diff (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键（reconcile_id）',
  tenant_id         BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  reconcile_type    VARCHAR(16)  NOT NULL COMMENT '类型：delivery发货/stock库存/aftersale售后/order_missing漏单',
  shop_id           BIGINT UNSIGNED NOT NULL COMMENT '店铺（LFK→gw_shop.id）',
  biz_ref           VARCHAR(128) NOT NULL COMMENT '本地对账对象（单号/引用）',
  platform_ref      VARCHAR(128) NULL COMMENT '平台侧对象（平台单号）',
  local_snapshot    JSON         NULL COMMENT '本地值快照（差异证据留存）',
  platform_snapshot JSON         NULL COMMENT '平台值快照',
  result            VARCHAR(16)  NOT NULL COMMENT '结果：consistent一致/fixed差异已修正/to_manual差异转人工/repull漏单补拉',
  action_taken      VARCHAR(64)  NULL COMMENT '处置动作（补推/重放/登记api_fail等）',
  alert_id          VARCHAR(64)  NULL COMMENT '关联告警ID（oms_base通知中心，跨域）',
  create_time       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  KEY idx_gw_recon_diff_shop_time (shop_id, create_time),
  KEY idx_gw_recon_diff_biz (biz_ref),
  KEY idx_gw_recon_diff_result (result, reconcile_type)
) ENGINE=InnoDB COMMENT='对账反查差异流水（D02.05 §6.2，只增不改）';

-- ---------------------------------------------------------------------
-- 22. gw_openapi_app 对外应用档案（SRS-D02.07 §6.1，P2）
-- ---------------------------------------------------------------------
CREATE TABLE gw_openapi_app (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id          BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID（关联租户）',
  owner_id           BIGINT UNSIGNED NULL COMMENT '货主ID（配置表免填，数据范围见owner_scope_json）',
  app_bn             VARCHAR(64)  NOT NULL COMMENT '应用编号（对外appkey）',
  app_name           VARCHAR(128) NOT NULL COMMENT '应用名称',
  app_secret_enc     VARBINARY(1024) NOT NULL COMMENT '应用secret密文（KMS，规约同gw_shop_auth）',
  key_version        VARCHAR(32)  NOT NULL DEFAULT 'v1' COMMENT '密钥版本',
  app_type           VARCHAR(16)  NOT NULL COMMENT '类型：brand品牌方系统/isv ISV/kaide K-AIDE/portal门户内部',
  owner_scope_json   JSON         NULL COMMENT '数据范围（货主ID集合；空=租户全量）',
  api_whitelist_json JSON         NULL COMMENT '接口白名单（method数组；空=按配额等级默认集）',
  quota_level        VARCHAR(16)  NOT NULL DEFAULT 'standard' COMMENT '配额等级：basic/standard/premium',
  ip_whitelist       VARCHAR(512) NULL COMMENT 'IP白名单（逗号分隔，空=不限）',
  status             VARCHAR(16)  NOT NULL DEFAULT 'disabled' COMMENT '启停：enabled启用/disabled停用',
  audit_status       VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT '接入审核状态：pending待审/approved通过/rejected驳回',
  create_time        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version            INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted         TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_gw_openapi_app_bn (app_bn)
) ENGINE=InnoDB COMMENT='对外OpenAPI应用档案（D02.07 §6.1，P2启动生效）';

-- ---------------------------------------------------------------------
-- 23. gw_openapi_register 对外接口注册（SRS-D02.07 §6.2，P2）
-- ---------------------------------------------------------------------
CREATE TABLE gw_openapi_register (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id   BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  method      VARCHAR(128) NOT NULL COMMENT '接口方法名（如oms.order.get）',
  api_version VARCHAR(16)  NOT NULL DEFAULT 'v1' COMMENT '版本',
  domain      VARCHAR(32)  NOT NULL COMMENT '域：order/stock/aftersale/shop',
  rw_type     VARCHAR(8)   NOT NULL COMMENT '读写类型：read/write',
  perm_point  VARCHAR(64)  NOT NULL COMMENT '权限点编码（oms_org权限体系，跨域）',
  quota_level VARCHAR(16)  NOT NULL DEFAULT 'standard' COMMENT '最低配额等级：basic/standard/premium',
  status      VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '状态：enabled启用/disabled停用',
  create_time DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version     INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted  TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_gw_openapi_register_method (method, api_version)
) ENGINE=InnoDB COMMENT='对外OpenAPI接口注册表（D02.07 §6.2，P2）';

-- ---------------------------------------------------------------------
-- 24. gw_openapi_log 对外调用审计基表（SRS-D02.07 §6.2，P2；按月分表，只增不改）
-- ---------------------------------------------------------------------
CREATE TABLE gw_openapi_log (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id            BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  request_id           VARCHAR(32)  NOT NULL COMMENT '请求ID（雪花，应答回带）',
  app_id               BIGINT UNSIGNED NOT NULL COMMENT '应用（LFK→gw_openapi_app.id）',
  operator             VARCHAR(64)  NULL COMMENT '操作人（应用侧透传）',
  on_behalf_of         VARCHAR(64)  NULL COMMENT '代理对象（K-AIDE代操作场景）',
  method               VARCHAR(128) NOT NULL COMMENT '接口方法名',
  params_digest        VARCHAR(64)  NULL COMMENT '参数摘要（SHA-256，不留原文）',
  result               VARCHAR(16)  NOT NULL COMMENT '结果：succ成功/fail失败/denied拒绝',
  err_code             VARCHAR(64)  NULL COMMENT '错误码',
  spendtime_ms         INT UNSIGNED NULL COMMENT '耗时（毫秒）',
  ip                   VARCHAR(64)  NULL COMMENT '来源IP',
  confirmation_token_ref VARCHAR(128) NULL COMMENT '写类二次确认令牌引用',
  create_time          DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间（分表路由键）',
  PRIMARY KEY (id),
  KEY idx_gw_openapi_log_app_time (app_id, create_time),
  KEY idx_gw_openapi_log_request (request_id)
) ENGINE=InnoDB COMMENT='对外OpenAPI调用审计基表（D02.07 §6.2，P2；按月分表gw_openapi_log_YYYYMM）';

-- =====================================================================
-- 初始字典数据
-- =====================================================================

-- 平台应用配置样例（沙箱态，凭证密文由部署时 KMS 写入，此处占位）
INSERT INTO gw_platform_config (platform, app_bn, app_key, app_secret_enc, gateway_url, sandbox_gateway_url, api_version, sign_strategy, status) VALUES
('taobao', 'TB-APP-DEMO', 'demo_appkey', X'00', 'https://eco.taobao.com/router/rest', 'https://gw.api.tbsandbox.com/router/rest', '2.0', 'md5-top', 'sandbox'),
('jd',     'JD-APP-DEMO', 'demo_appkey', X'00', 'https://api.jd.com/routerjson', NULL, '2.0', 'md5-top', 'sandbox'),
('pdd',    'PDD-APP-DEMO','demo_appkey', X'00', 'https://gw-api.pinduoduo.com/api/router', NULL, 'v1', 'hmac-sha256', 'sandbox'),
('douyin', 'DY-APP-DEMO', 'demo_appkey', X'00', 'https://openapi-fxg.jinritemai.com', NULL, '2', 'hmac-sha256', 'sandbox'),
('xhs',    'XHS-APP-DEMO','demo_appkey', X'00', 'https://ark.xiaohongshu.com/ark/open_api/v3/common_controller', NULL, 'v3', 'hmac-sha256', 'sandbox'),
('vop',    'VOP-APP-DEMO','demo_appkey', X'00', 'https://api.vop.com', NULL, '1.0', 'hmac-sha256', 'sandbox');

-- 错误码字典样例（分级驱动重试策略，D02.05 §5）
INSERT INTO gw_errcode_dict (platform, native_code, err_pattern, err_level, advice, note) VALUES
('common', NULL,      'isp\\.remote-service-timeout',            'RETRYABLE',    '服务超时，按退避策略自动重试', 'TOP通用超时'),
('common', NULL,      '(flow-control|访问频率|too many requests)', 'RATE_LIMITED', '触发限流，指数退避后重试', NULL),
('taobao', '27',      NULL,                                       'AUTH',         'session过期，通知店铺重新授权', 'isv.invalid-permission'),
('taobao', '29',      NULL,                                       'AUTH',         'session过期，触发自动续期或重授权', NULL),
('taobao', '15',      NULL,                                       'RETRYABLE',    '远程服务出错，自动重试', 'isv.remote-service-error'),
('jd',     '19',      NULL,                                       'AUTH',         'accessToken失效，重授权', NULL),
('pdd',    '10019',   NULL,                                       'RETRYABLE',    '访问频率超限，退避重试', NULL),
('pdd',    '50001',   NULL,                                       'MANUAL',       '参数错误需人工核查映射配置', NULL),
('douyin', '100002',  NULL,                                       'AUTH',         '授权失效，重授权', NULL),
('common', NULL,      '订单不存在|order not exist',                'FATAL',        '停止重试，转对账反查确认平台单号', '写类先反查'),
('common', NULL,      '系统异常|system error|internal error',      'RETRYABLE',    '平台系统异常，退避重试', NULL),
('common', NULL,      '签名.*(错误|无效)|invalid signature',       'MANUAL',       '签名配置错误，检查appkey/secret与签名策略', NULL);

-- 订单状态映射样例（D02.02 enum_mapping）
INSERT INTO gw_enum_mapping (platform, map_type, native_value, canonical_value) VALUES
('taobao', 'order_status', 'WAIT_BUYER_PAY',       'unpaid'),
('taobao', 'order_status', 'WAIT_SELLER_SEND_GOODS','unshipped'),
('taobao', 'order_status', 'WAIT_BUYER_CONFIRM_GOODS','shipped'),
('taobao', 'order_status', 'TRADE_FINISHED',       'finished'),
('taobao', 'order_status', 'TRADE_CLOSED',         'closed'),
('jd',     'order_status', 'WAIT_SELLER_STOCK_OUT','unshipped'),
('jd',     'order_status', 'WAIT_GOODS_RECEIVE_CONFIRM','shipped'),
('jd',     'order_status', 'FINISHED_L',           'finished'),
('pdd',    'order_status', '1',                    'unpaid'),
('pdd',    'order_status', '2',                    'unshipped'),
('pdd',    'order_status', '3',                    'shipped'),
('pdd',    'order_status', '5',                    'finished'),
('douyin', 'order_status', '2',                    'unshipped'),
('douyin', 'order_status', '3',                    'shipped'),
('douyin', 'order_status', '4',                    'finished');

-- 限流配置样例（平台级默认）
INSERT INTO gw_ratelimit_config (scope_type, scope_key, method, qps_limit, daily_quota) VALUES
('platform', 'taobao', '', 40, NULL),
('platform', 'jd',     '', 30, NULL),
('platform', 'pdd',    '', 20, NULL),
('method',   'taobao', 'order.upload.logistics', 5, NULL);

-- 对外接口注册样例（P2 预置，随 P2 启动生效）
INSERT INTO gw_openapi_register (method, api_version, domain, rw_type, perm_point, quota_level) VALUES
('oms.order.get',      'v1', 'order', 'read',  'OPENAPI_ORDER_READ',  'basic'),
('oms.order.list',     'v1', 'order', 'read',  'OPENAPI_ORDER_READ',  'standard'),
('oms.delivery.push',  'v1', 'order', 'write', 'OPENAPI_DELIVERY_WRITE','standard'),
('oms.stock.get',      'v1', 'stock', 'read',  'OPENAPI_STOCK_READ',  'basic');

-- =====================================================================
-- 完 · 24 张表（含 2 张按月分表基表模板）
-- =====================================================================
