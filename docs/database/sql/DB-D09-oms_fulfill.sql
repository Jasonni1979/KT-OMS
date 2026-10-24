-- =====================================================================
-- DB-D09 oms_fulfill 履约集成域 建表脚本（MySQL 8.0）
-- 版本 V1.0 · 2026-10-24 · 依据：DB-00 总册 + DB-D09 数据字典
-- 执行顺序：DB-00 建库约定 → DB-D02(oms_gateway) → 本脚本
-- 约定：不建物理外键；utf8mb4/utf8mb4_0900_ai_ci/InnoDB；公共字段见 DB-00 §3
-- 分表：ful_route_log / ful_channel_log 按月分表（_YYYYMM），本脚本建基表模板
-- =====================================================================

CREATE SCHEMA IF NOT EXISTS oms_fulfill DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE oms_fulfill;

-- ---------------------------------------------------------------------
-- 1. ful_branch 仓库档案（SRS-D09.01 §6.1）← 商派 ome.branch 改造
-- ---------------------------------------------------------------------
CREATE TABLE ful_branch (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键（全系统branch_id事实源，inv_stock_ledger三元键引用）',
  tenant_id          BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id           BIGINT UNSIGNED NULL COMMENT '归属货主（单一归属仓必填；凯淳多货主仓为空；LFK→oms_org.org_owner跨域）',
  branch_bn          VARCHAR(32)  NOT NULL COMMENT '仓库编码（全局唯一不可变更）',
  branch_name        VARCHAR(128) NOT NULL COMMENT '仓库名称',
  branch_type        VARCHAR(16)  NOT NULL COMMENT '仓库类型：entity实体仓/cloud云仓/store门店仓/bonded保税仓/virtual虚拟仓/defective次品仓',
  region_code        VARCHAR(16)  NULL COMMENT '区域编码（华东/华南等，D03.06区域路由、D09.04物流分单用）',
  province           VARCHAR(32)  NULL COMMENT '省',
  city               VARCHAR(32)  NULL COMMENT '市',
  district           VARCHAR(32)  NULL COMMENT '区',
  address            VARCHAR(256) NULL COMMENT '详细地址',
  contact_name       VARCHAR(64)  NULL COMMENT '联系人',
  contact_mobile_enc VARBINARY(512) NULL COMMENT '联系人手机密文（PIPL，D01.05）',
  is_ctrl            TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '管控库存：0不管控(跳过记账，商派口径)/1管控',
  countable_flag     TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '计可售：0否(平台自发仓，D04.08排除)/1是',
  is_declare         TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '跨境申报仓：0否/1是（D03.12）',
  cutoff_time        CHAR(5)      NULL COMMENT '截单时间（HH:mm，D03.06分仓参考）',
  org_node_id        BIGINT UNSIGNED NULL COMMENT '组织树节点（LFK→oms_org.org_node跨域）',
  status             VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '状态：enabled启用/disabled停用/migrating迁移中/archived归档',
  memo               VARCHAR(512) NULL COMMENT '备注',
  source             VARCHAR(16)  NOT NULL DEFAULT 'local' COMMENT '数据来源：api/local/import/migration',
  create_time        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version            INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted         TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_branch_branch_bn (branch_bn),
  KEY idx_ful_branch_owner (owner_id),
  KEY idx_ful_branch_status_type (status, branch_type)
) ENGINE=InnoDB COMMENT='仓库档案（D09.01；仓库主档全系统事实源）';

-- ---------------------------------------------------------------------
-- 2. ful_wms WMS服务商档案（SRS-D09.01 §6.2）
-- ---------------------------------------------------------------------
CREATE TABLE ful_wms (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id    BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  wms_code     VARCHAR(32)  NOT NULL COMMENT 'WMS服务商编码：ttx通天晓/flux富勒/wln万里牛/qimen奇门通用/self自研仓内',
  wms_name     VARCHAR(128) NOT NULL COMMENT '服务商名称',
  protocol     VARCHAR(16)  NOT NULL DEFAULT 'qimen' COMMENT '默认协议：qimen奇门/restful REST/ttx_rest通天晓REST（字典可扩展）',
  adapter_code VARCHAR(64)  NULL COMMENT '默认适配器编码（注册校验，D09.01 FR-03）',
  status       VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '状态：enabled启用/disabled停用（停用即全绑定不可发）',
  create_time  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version      INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted   TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_wms_wms_code (wms_code)
) ENGINE=InnoDB COMMENT='WMS服务商档案（D09.01 §6.2）';

-- ---------------------------------------------------------------------
-- 3. ful_wms_binding 仓×WMS绑定（SRS-D09.01 §6.2/§6.3；协议+账号加密+能力矩阵）
-- ---------------------------------------------------------------------
CREATE TABLE ful_wms_binding (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id         BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id          BIGINT UNSIGNED NULL COMMENT '货主粒度（空=仓级默认绑定；LFK→oms_org.org_owner跨域）',
  branch_id         BIGINT UNSIGNED NOT NULL COMMENT '仓库（LFK→ful_branch.id）',
  wms_id            BIGINT UNSIGNED NOT NULL COMMENT 'WMS（LFK→ful_wms.id）',
  protocol          VARCHAR(16)  NOT NULL DEFAULT 'qimen' COMMENT '本协议：qimen/restful/ttx_rest',
  adapter_code      VARCHAR(64)  NOT NULL COMMENT '适配器编码（必须已注册）',
  wms_branch_code   VARCHAR(64)  NOT NULL COMMENT 'WMS侧仓编码（报文warehouseCode来源）',
  wms_owner_code    VARCHAR(64)  NULL COMMENT 'WMS侧货主编码（报文ownerCode来源）',
  app_key           VARCHAR(128) NULL COMMENT '账号appkey（奇门appKey等，非敏感）',
  secret_enc        VARBINARY(1024) NULL COMMENT '账号secret密文（KMS信封加密，D01.05）',
  key_version       VARCHAR(32)  NOT NULL DEFAULT 'v1' COMMENT '密钥版本',
  endpoint          VARCHAR(256) NULL COMMENT '接口地址（沙箱/生产）',
  env               VARCHAR(16)  NOT NULL DEFAULT 'prod' COMMENT '环境：sandbox沙箱/prod生产',
  timeout_ms        INT UNSIGNED NOT NULL DEFAULT 10000 COMMENT '超时毫秒（默认10s）',
  retry_policy_json JSON         NULL COMMENT '重试参数：{max_times:3,backoff:"exp"}（默认3次退避）',
  capability_json   JSON         NULL COMMENT '能力矩阵：{batch批次,sn序列号,stocktake盘点,waybill_callback面单回传,recall叫回,split_pkg多包裹}（绑定级覆盖WMS级默认）',
  priority          INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '优先级（同仓多绑定取最高）',
  effective_from    DATETIME(3)  NULL COMMENT '生效起（空=即时）',
  effective_to      DATETIME(3)  NULL COMMENT '生效止（空=长期）',
  status            VARCHAR(16)  NOT NULL DEFAULT 'active' COMMENT '状态：pending待生效/active生效/receive_only只收不发/archived失效归档（重叠可发绑定禁止，应用层校验）',
  create_time       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted        TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_wms_binding_unique (branch_id, wms_id, owner_id, wms_branch_code),
  KEY idx_ful_wms_binding_branch (branch_id, owner_id, status)
) ENGINE=InnoDB COMMENT='仓×WMS×协议×账号绑定与能力矩阵（D09.01 §6.3）';

-- ---------------------------------------------------------------------
-- 4. ful_wms_health WMS通道健康与熔断（SRS-D09.01 §6.4；滚动清理）
-- ---------------------------------------------------------------------
CREATE TABLE ful_wms_health (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id      BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  wms_id         BIGINT UNSIGNED NOT NULL COMMENT 'WMS（LFK→ful_wms.id）',
  binding_id     BIGINT UNSIGNED NULL COMMENT '绑定粒度（空=WMS级汇总）',
  probe_time     DATETIME(3)  NOT NULL COMMENT '探活时间',
  success        TINYINT(1)   NOT NULL COMMENT '探活结果：0失败/1成功',
  latency_ms     INT UNSIGNED NULL COMMENT '探活延迟（毫秒）',
  circuit_status VARCHAR(16)  NOT NULL DEFAULT 'closed' COMMENT '熔断状态：closed正常/open熔断中/half_open半开探测',
  open_time      DATETIME(3)  NULL COMMENT '熔断开启时间',
  buffer_depth   INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '缓冲积压快照（ful_outbound_buffer深度）',
  create_time    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  KEY idx_ful_wms_health_wms_time (wms_id, probe_time),
  KEY idx_ful_wms_health_circuit (circuit_status)
) ENGINE=InnoDB COMMENT='WMS通道健康探活与熔断状态（D09.01 §6.4）';

-- ---------------------------------------------------------------------
-- 5. ful_route_log 路由决策日志基表（SRS-D09.01 §6.4；按月分表，只增不改）
-- ---------------------------------------------------------------------
CREATE TABLE ful_route_log (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id    BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id     BIGINT UNSIGNED NULL COMMENT '货主ID',
  cmd_ref      VARCHAR(64)  NOT NULL COMMENT '指令引用（cmd_bn/bill_bn）',
  branch_id    BIGINT UNSIGNED NOT NULL COMMENT '仓库（LFK→ful_branch.id）',
  binding_id   BIGINT UNSIGNED NULL COMMENT '命中绑定（LFK→ful_wms_binding.id；失败为空）',
  result       VARCHAR(16)  NOT NULL COMMENT '结果：succ成功/degraded降级(缓冲)/fail失败',
  err_code     VARCHAR(64)  NULL COMMENT '失败码：无可用绑定/熔断/能力不匹配等',
  spendtime_ms INT UNSIGNED NULL COMMENT '路由决策耗时（毫秒）',
  create_time  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间（分表路由键）',
  PRIMARY KEY (id),
  KEY idx_ful_route_log_cmd (cmd_ref),
  KEY idx_ful_route_log_branch_time (branch_id, create_time)
) ENGINE=InnoDB COMMENT='路由决策日志基表（D09.01；按月分表ful_route_log_YYYYMM，在线3个月）';
-- 月表示例（调度器滚动创建）：CREATE TABLE ful_route_log_202611 LIKE ful_route_log;

-- ---------------------------------------------------------------------
-- 6. ful_cmd_fail 指令失败与熔断记录（SRS-D09.01 FR-05c / D09.02 §5.4）
-- ---------------------------------------------------------------------
CREATE TABLE ful_cmd_fail (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id        BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NULL COMMENT '货主ID',
  cmd_type         VARCHAR(16)  NOT NULL COMMENT '指令类型：outbound出库/inbound入库/recall叫回/cancel取消',
  cmd_id           BIGINT UNSIGNED NOT NULL COMMENT '指令ID（LFK→ful_outbound_cmd.id或ful_inbound_cmd.id，按cmd_type解释）',
  cmd_bn           VARCHAR(32)  NOT NULL COMMENT '指令号（冗余检索）',
  wms_id           BIGINT UNSIGNED NOT NULL COMMENT 'WMS（LFK→ful_wms.id）',
  binding_id       BIGINT UNSIGNED NULL COMMENT '绑定',
  err_class        VARCHAR(16)  NOT NULL COMMENT '错误分类：RETRYABLE可重试/FATAL停重试/BIZ_REJECT业务拒绝（D09.02 §5.4）',
  err_code         VARCHAR(64)  NULL COMMENT 'WMS侧错误码',
  err_msg          VARCHAR(512) NULL COMMENT '错误原文（截断）',
  circuit_snapshot VARCHAR(16)  NULL COMMENT '失败时WMS健康状态快照：closed/open/half_open',
  retry_times      INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '重试次数',
  next_retry_time  DATETIME(3)  NULL COMMENT '下次重试时间（分级退避）',
  status           VARCHAR(16)  NOT NULL DEFAULT 'waiting' COMMENT '状态：waiting等待/retrying重试中/succ成功/manual转人工/dead死信',
  resolved_by      VARCHAR(16)  NULL COMMENT '解决方式：retry重试/manual人工/biz_closed业务关闭',
  create_time      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  PRIMARY KEY (id),
  KEY idx_ful_cmd_fail_status_retry (status, next_retry_time),
  KEY idx_ful_cmd_fail_cmd (cmd_type, cmd_id),
  KEY idx_ful_cmd_fail_wms (wms_id, create_time)
) ENGINE=InnoDB COMMENT='指令失败与熔断记录（D09.01/D09.02；熔断计数窗口）';

-- ---------------------------------------------------------------------
-- 7. ful_outbound_cmd 出库指令（SRS-D09.02 §6.1）
-- ---------------------------------------------------------------------
CREATE TABLE ful_outbound_cmd (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL COMMENT '货主ID（SRS-00契约必填）',
  branch_id       BIGINT UNSIGNED NOT NULL COMMENT '仓库（LFK→ful_branch.id）',
  cmd_bn          VARCHAR(32)  NOT NULL COMMENT '指令号（delivery_bn+轮次派生，Redis发号）',
  delivery_id     BIGINT UNSIGNED NOT NULL COMMENT '发货单（LFK→oms_order.ord_delivery.id跨域）',
  delivery_bn     VARCHAR(32)  NOT NULL COMMENT '发货单号（冗余检索）',
  push_round      INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '推送轮次（重推递增；幂等键成分）',
  wms_id          BIGINT UNSIGNED NOT NULL COMMENT 'WMS路由快照（LFK→ful_wms.id）',
  binding_id      BIGINT UNSIGNED NOT NULL COMMENT '绑定快照（LFK→ful_wms_binding.id；历史溯源不漂移FR-03e）',
  adapter_code    VARCHAR(64)  NOT NULL COMMENT '适配器快照',
  wms_bill_no     VARCHAR(64)  NULL COMMENT 'WMS侧单号（受理应答回填；回传匹配键）',
  cmd_type        VARCHAR(16)  NOT NULL DEFAULT 'push' COMMENT '指令类型：push推送/recall叫回/resume恢复',
  status          VARCHAR(16)  NOT NULL DEFAULT 'accepted' COMMENT '通道状态机：accepted已受理/buffering缓冲中/sending下发中/sent已下发/retrying重试中/send_failed下发失败/processing WMS作业中/partial_callback部分回传/callback_done回传闭环/orchestrated编排完成/recalling叫回中/recall_succ叫回成功/recall_failed叫回失败/rejected已打回/voided已作废',
  waybill_no      VARCHAR(64)  NULL COMMENT '面单号（D09.05取号结果引用，FR-06）',
  print_ref       VARCHAR(128) NULL COMMENT '打印数据引用（云打印报文ID/PDF文件ID）',
  payload_oss_ref VARCHAR(256) NULL COMMENT '下发报文快照OSS引用（压缩存储FR-07a）',
  diff_flag       TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '差异标记：0无/1实发≠指令（SC-06）',
  fail_reason     VARCHAR(64)  NULL COMMENT '打回/失败结构化原因：缺货/地址不可达/仓内异常（SC-07）',
  idempotent_key  VARCHAR(128) NOT NULL COMMENT '幂等键（delivery_id+轮次派生）',
  source          VARCHAR(16)  NOT NULL DEFAULT 'local' COMMENT '数据来源：api/local/import/migration',
  create_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_outbound_cmd_idem (idempotent_key),
  UNIQUE KEY uk_ful_outbound_cmd_bn (cmd_bn),
  KEY idx_ful_outbound_cmd_delivery (delivery_id),
  KEY idx_ful_outbound_cmd_status (status, create_time),
  KEY idx_ful_outbound_cmd_wms_bill (wms_bill_no)
) ENGINE=InnoDB COMMENT='出库指令（D09.02 §6.1；状态机=D03.07通道侧投影）';

-- ---------------------------------------------------------------------
-- 8. ful_outbound_callback 出库回传登记（SRS-D09.02 §6.2；只增不改）
-- ---------------------------------------------------------------------
CREATE TABLE ful_outbound_callback (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NULL COMMENT '货主ID（匹配成功回填；无主回传为空）',
  cmd_id          BIGINT UNSIGNED NULL COMMENT '指令匹配（LFK→ful_outbound_cmd.id；无主回传为空）',
  delivery_id     BIGINT UNSIGNED NULL COMMENT '发货单匹配（跨域LFK→ord_delivery；无主为空）',
  wms_batch_no    VARCHAR(64)  NOT NULL COMMENT 'WMS回传批次号（幂等键成分）',
  idempotent_key  VARCHAR(160) NOT NULL COMMENT '幂等键（cmd_bn或delivery_bn+wms_batch_no，FR-03c/SRS-00全局决策）',
  callback_type   VARCHAR(16)  NOT NULL COMMENT '回传类型：accept接收确认/outbound出库/reject打回/cancel_result取消结果/node节点',
  lines_json      JSON         NULL COMMENT '标准明细（适配器标准化产物）：[{bm_id,num,batch_no,sn_list}]',
  packages_json   JSON         NULL COMMENT '包裹/称重/体积/运单（供D03.07落库与D08.04对账）',
  reject_reason   VARCHAR(64)  NULL COMMENT '打回结构化原因：oos缺货/address_unreachable地址不可达/wh_error仓内异常',
  process_status  VARCHAR(16)  NOT NULL DEFAULT 'registered' COMMENT '处理状态：registered已登记/event_sent已发事件/orchestrated编排闭环/exception异常缓冲',
  raw_payload_ref VARCHAR(256) NULL COMMENT '原始报文引用（压缩存储OSS）',
  receive_time    DATETIME(3)  NOT NULL COMMENT '接收时间',
  ack_time        DATETIME(3)  NULL COMMENT '应答时间（回执时效监控）',
  create_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_outbound_callback_idem (idempotent_key),
  KEY idx_ful_outbound_callback_cmd (cmd_id),
  KEY idx_ful_outbound_callback_status (process_status, receive_time)
) ENGINE=InnoDB COMMENT='出库回传登记（D09.02 §6.2；幂等=单据号+WMS批次号）';

-- ---------------------------------------------------------------------
-- 9. ful_outbound_buffer 出库指令熔断缓冲队列（SRS-D09.02 §6.3）
-- ---------------------------------------------------------------------
CREATE TABLE ful_outbound_buffer (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id    BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id     BIGINT UNSIGNED NULL COMMENT '货主ID',
  cmd_id       BIGINT UNSIGNED NOT NULL COMMENT '出库指令（LFK→ful_outbound_cmd.id）',
  branch_id    BIGINT UNSIGNED NOT NULL COMMENT '仓库（FIFO分组键）',
  wms_id       BIGINT UNSIGNED NOT NULL COMMENT '目标WMS',
  enqueue_time DATETIME(3)  NOT NULL COMMENT '入队时间（按仓FIFO序）',
  status       VARCHAR(16)  NOT NULL DEFAULT 'buffered' COMMENT '状态：buffered缓冲中/resent已补发/voided已作废（叫回/取消FR-04d）',
  create_time  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version      INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_outbound_buffer_cmd (cmd_id),
  KEY idx_ful_outbound_buffer_branch (branch_id, status, enqueue_time)
) ENGINE=InnoDB COMMENT='出库指令熔断缓冲队列（D09.02 §6.3；恢复后按仓FIFO补发）';

-- ---------------------------------------------------------------------
-- 10. ful_channel_log WMS通道日志基表（SRS-D09.02 §6.3；按月分表，只增不改）
-- ---------------------------------------------------------------------
CREATE TABLE ful_channel_log (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id    BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  cmd_id       BIGINT UNSIGNED NULL COMMENT '指令引用',
  cmd_bn       VARCHAR(32)  NULL COMMENT '指令号（冗余）',
  wms_id       BIGINT UNSIGNED NOT NULL COMMENT 'WMS',
  direction    TINYINT      NOT NULL DEFAULT 1 COMMENT '方向：1出向(OMS→WMS)/2入向(WMS回传)',
  action       VARCHAR(32)  NOT NULL COMMENT '动作：push/recall/cancel/query/callback_accept/callback_outbound等',
  payload_ref  VARCHAR(256) NULL COMMENT '请求/应答报文引用（OSS压缩）',
  err_class    VARCHAR(16)  NULL COMMENT '错误分类：RETRYABLE/FATAL/BIZ_REJECT',
  err_code     VARCHAR(64)  NULL COMMENT 'WMS错误码',
  spendtime_ms INT UNSIGNED NULL COMMENT '耗时（毫秒）',
  retry_times  INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '重试次数',
  create_time  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间（分表路由键）',
  PRIMARY KEY (id),
  KEY idx_ful_channel_log_cmd (cmd_id),
  KEY idx_ful_channel_log_wms_time (wms_id, create_time)
) ENGINE=InnoDB COMMENT='WMS通道日志基表（D09.02 §6.3；按月分表ful_channel_log_YYYYMM）';
-- 月表示例（调度器滚动创建）：CREATE TABLE ful_channel_log_202611 LIKE ful_channel_log;

-- ---------------------------------------------------------------------
-- 11. ful_inbound_cmd 入库指令（SRS-D09.03 §6.1）
-- ---------------------------------------------------------------------
CREATE TABLE ful_inbound_cmd (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL COMMENT '货主ID（SRS-00契约必填）',
  branch_id       BIGINT UNSIGNED NOT NULL COMMENT '仓库（LFK→ful_branch.id）',
  cmd_bn          VARCHAR(32)  NOT NULL COMMENT '指令号（bill_bn+轮次派生，唯一）',
  bill_id         BIGINT UNSIGNED NOT NULL COMMENT 'D04.04单据（LFK→oms_stock.inv_io_bill.id跨域，契约关联）',
  bill_bn         VARCHAR(32)  NOT NULL COMMENT '单据号（冗余检索）',
  bill_type       VARCHAR(16)  NOT NULL COMMENT '单据类型：purchase采购/transfer调拨/other其他（D04.04口径）',
  source_type     VARCHAR(16)  NOT NULL COMMENT '业务源类型：purchase采购PO/return退货RA/transfer调拨TR（模板注册表键FR-01b）',
  source_bill_bn  VARCHAR(32)  NULL COMMENT '源单号（PO/RA/TR单号，追溯链头）',
  push_round      INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '下发轮次（幂等键成分）',
  wms_id          BIGINT UNSIGNED NOT NULL COMMENT 'WMS路由快照',
  binding_id      BIGINT UNSIGNED NOT NULL COMMENT '绑定快照',
  adapter_code    VARCHAR(64)  NOT NULL COMMENT '适配器快照',
  wms_bill_no     VARCHAR(64)  NULL COMMENT 'WMS侧单号（受理回填；回传匹配键）',
  status          VARCHAR(16)  NOT NULL DEFAULT 'accepted' COMMENT '通道状态机（同出库口径，回传侧收货语义）：accepted/buffering/sending/sent/retrying/send_failed/processing/partial_callback/callback_done/orchestrated/recalling/recall_succ/recall_failed/rejected/voided',
  diff_flag       TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '差异标记：0无/1有（超收/短缺/破损/争议FR-05）',
  diff_ref        VARCHAR(64)  NULL COMMENT '差异登记引用（ful_inbound_diff关联cmd_bn）',
  payload_oss_ref VARCHAR(256) NULL COMMENT '报文快照OSS引用',
  idempotent_key  VARCHAR(128) NOT NULL COMMENT '幂等键（bill_bn+轮次）',
  create_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_inbound_cmd_idem (idempotent_key),
  UNIQUE KEY uk_ful_inbound_cmd_bn (cmd_bn),
  KEY idx_ful_inbound_cmd_bill (bill_id),
  KEY idx_ful_inbound_cmd_source (source_type, source_bill_bn),
  KEY idx_ful_inbound_cmd_wms_bill (wms_bill_no)
) ENGINE=InnoDB COMMENT='入库指令（D09.03 §6.1；三类源单：采购/退货/调拨）';

-- ---------------------------------------------------------------------
-- 12. ful_inbound_callback 入库回传登记（SRS-D09.03 §6.2；只增不改）
-- ---------------------------------------------------------------------
CREATE TABLE ful_inbound_callback (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NULL COMMENT '货主ID（无主回传为空→转D04.04无头件流程）',
  cmd_id          BIGINT UNSIGNED NULL COMMENT '指令匹配（LFK→ful_inbound_cmd.id）',
  bill_bn         VARCHAR(32)  NULL COMMENT '单据匹配',
  wms_batch_no    VARCHAR(64)  NOT NULL COMMENT 'WMS回传批次号（幂等键成分）',
  idempotent_key  VARCHAR(160) NOT NULL COMMENT '幂等键（bill_bn+wms_batch_no）',
  callback_type   VARCHAR(16)  NOT NULL COMMENT '回传类型：accept接收确认/receive收货/qc质检/diff_report差异上报/cancel_result取消结果',
  lines_json      JSON         NULL COMMENT '标准明细：[{bm_id,received_num实收,batch_no,expire_date,sn_list,good_num良品,defect_num不良,defect_reason}]（质检分流FR-04a）',
  qc_result_json  JSON         NULL COMMENT '质检结果明细（退货/残损场景，不良原因字典）',
  process_status  VARCHAR(16)  NOT NULL DEFAULT 'registered' COMMENT '处理状态：registered已登记/received已收/confirmed已确认/diff_hold差异挂起/exception异常缓冲',
  raw_payload_ref VARCHAR(256) NULL COMMENT '原始报文引用（压缩存储）',
  receive_time    DATETIME(3)  NOT NULL COMMENT '接收时间',
  ack_time        DATETIME(3)  NULL COMMENT '应答时间',
  create_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_inbound_callback_idem (idempotent_key),
  KEY idx_ful_inbound_callback_cmd (cmd_id),
  KEY idx_ful_inbound_callback_status (process_status, receive_time)
) ENGINE=InnoDB COMMENT='入库回传登记（D09.03 §6.2；幂等=单据号+WMS批次号）';

-- ---------------------------------------------------------------------
-- 13. ful_inbound_diff 入库差异登记（SRS-D09.03 §6.3）
-- ---------------------------------------------------------------------
CREATE TABLE ful_inbound_diff (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id            BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id             BIGINT UNSIGNED NULL COMMENT '货主ID',
  cmd_id               BIGINT UNSIGNED NOT NULL COMMENT '指令（LFK→ful_inbound_cmd.id）',
  bill_bn              VARCHAR(32)  NOT NULL COMMENT '单据号',
  bill_item_ref        VARCHAR(64)  NULL COMMENT '单据行引用（bill_item_id或行号）',
  diff_type            VARCHAR(16)  NOT NULL COMMENT '差异类型：over超收/short短缺/damage破损/wrong_goods串货/qc_dispute质检争议/mismatch预报不符',
  diff_num             INT          NOT NULL DEFAULT 0 COMMENT '差异数量（正=超收，负=短缺）',
  tolerance_snapshot   JSON         NULL COMMENT '当时容差规则快照（D04.04类型配置，可解释）',
  wms_evidence_ref     VARCHAR(256) NULL COMMENT 'WMS侧凭证（照片/单据OSS引用）',
  handle_status        VARCHAR(16)  NOT NULL DEFAULT 'open' COMMENT '处理状态：open待处理/handling处理中/closed已闭环',
  handle_result        VARCHAR(64)  NULL COMMENT '处理结果：按实收记账/拒收/索赔/争议升级等',
  handler              VARCHAR(64)  NULL COMMENT '经手人',
  source_notify_status VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT '源模块透传状态：pending待送达/sent事件已送达/acked已确认',
  create_time          DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time          DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version              INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted           TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  KEY idx_ful_inbound_diff_cmd (cmd_id),
  KEY idx_ful_inbound_diff_status (handle_status, diff_type),
  KEY idx_ful_inbound_diff_bill (bill_bn)
) ENGINE=InnoDB COMMENT='入库差异登记（D09.03 §6.3；闭环跟踪FR-05c）';

-- ---------------------------------------------------------------------
-- 14. ful_dly_corp 物流公司档案（SRS-D09.04 §6.1）← 商派 ome.dly_corp 改造
-- ---------------------------------------------------------------------
CREATE TABLE ful_dly_corp (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id            BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id             BIGINT UNSIGNED NULL COMMENT '归属货主（平台级共享档案=系统货主，SRS-00契约）',
  corp_code            VARCHAR(32)  NOT NULL COMMENT 'canonical物流编码（全局唯一不可变更，D02.02映射基准）：sf顺丰/zto中通/yto圆通/sto申通/yunda韵达/jd京东物流/ems邮政等',
  corp_name            VARCHAR(128) NOT NULL COMMENT '物流公司名称',
  short_name           VARCHAR(32)  NULL COMMENT '简称',
  corp_type            VARCHAR(16)  NOT NULL DEFAULT 'express' COMMENT '类型：express快递/freight快运/lastmile落地配/samecity同城/postal邮政/platform平台物流/special特殊',
  waybill_account_type VARCHAR(16)  NOT NULL DEFAULT 'cainiao' COMMENT '面单账号类型：cainiao菜鸟系/platform平台系/direct快递直客/none无需面单（D09.05路由依据）',
  protect_rate         DECIMAL(9,4) NULL COMMENT '保价费率（FR-05a联动）',
  protect_max          DECIMAL(18,2) NULL COMMENT '保价上限',
  service_tags         JSON         NULL COMMENT '服务属性标签：["冷链","大件","生鲜","贵重","到付","签返"]',
  pickup_mode          VARCHAR(16)  NULL COMMENT '揽收方式：door上门/self自送/station驿站',
  status               VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '状态：enabled启用/disabled停用（停用不可被新分单命中）',
  create_time          DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time          DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version              INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted           TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_dly_corp_code (corp_code),
  KEY idx_ful_dly_corp_status (status)
) ENGINE=InnoDB COMMENT='物流公司档案（D09.04 §6.1）';

-- ---------------------------------------------------------------------
-- 15. ful_dly_product 物流产品（SRS-D09.04 §6.2）
-- ---------------------------------------------------------------------
CREATE TABLE ful_dly_product (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id        BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NULL COMMENT '货主ID（配置表免填）',
  corp_id          BIGINT UNSIGNED NOT NULL COMMENT '物流商（LFK→ful_dly_corp.id）',
  product_code     VARCHAR(32)  NOT NULL COMMENT '产品编码（=面单取号express_type映射源，如sf_std/sf_eco）',
  product_name     VARCHAR(128) NOT NULL COMMENT '产品名称',
  product_type     VARCHAR(16)  NOT NULL DEFAULT 'standard' COMMENT '产品类型：standard标快/express特快/economy经济/cold冷链/bulky大件/samecity同城/intl国际',
  weight_min       DECIMAL(9,3) NULL COMMENT '重量段下限kg（productFit过滤§5.1）',
  weight_max       DECIMAL(9,3) NULL COMMENT '重量段上限kg',
  volume_limit     DECIMAL(9,3) NULL COMMENT '体积限制m³',
  service_tags     JSON         NULL COMMENT '服务属性（继承物流商+覆盖）',
  timeliness_table JSON         NULL COMMENT '区域时效表：{from_region×to_province:承诺天数}',
  status           VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '启停：enabled启用/disabled停用',
  create_time      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted       TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_dly_product_corp_code (corp_id, product_code)
) ENGINE=InnoDB COMMENT='物流产品（D09.04 §6.2）';

-- ---------------------------------------------------------------------
-- 16. ful_area_router 区域路由规则（SRS-D09.04 §6.3）← 商派 logistics.area_router 改造
-- ---------------------------------------------------------------------
CREATE TABLE ful_area_router (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id        BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NULL COMMENT '货主ID（配置表免填）',
  rule_name        VARCHAR(128) NOT NULL COMMENT '规则名',
  area_level       TINYINT      NOT NULL COMMENT '区域级别：4区/3市/2省/1全国（FR-03b上溯序）',
  area_id          BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '区域ID（0=全国；行政区划编码引用oms_base区划表跨域）',
  conditions       JSON         NULL COMMENT '条件集：{branch_id,shop_id,platform,category物料分类,weight_range,volume_range,tags[],time_range}',
  logi_seq         JSON         NOT NULL COMMENT '输出候选序（有序）：[{corp_id,product_id,priority}]',
  weight           INT          NOT NULL DEFAULT 0 COMMENT '匹配权重（同级多规则DESC首个命中）',
  effective_period VARCHAR(256) NULL COMMENT '生效时间段（大促临时切物流）',
  exclude_period   VARCHAR(256) NULL COMMENT '排除时间段',
  default_flag     TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '全国缺省标记：0否/1是（缺省规则全局唯一，应用层校验）',
  status           VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '启停：enabled启用/disabled停用',
  create_time      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted       TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  KEY idx_ful_area_router_area (area_level, area_id, status, weight),
  KEY idx_ful_area_router_default (default_flag)
) ENGINE=InnoDB COMMENT='区域路由规则：省市区→物流商产品优先级候选序（D09.04 §6.3）';

-- ---------------------------------------------------------------------
-- 17. ful_unreach_area 物流商×区域不可达（SRS-D09.04 §6.4；三处消费同一事实源）
-- ---------------------------------------------------------------------
CREATE TABLE ful_unreach_area (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id   BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id    BIGINT UNSIGNED NULL COMMENT '货主ID（配置表免填）',
  corp_id     BIGINT UNSIGNED NOT NULL COMMENT '物流商（LFK→ful_dly_corp.id）',
  area_id     BIGINT UNSIGNED NOT NULL COMMENT '区域ID（区/市/省级）',
  reason      VARCHAR(128) NULL COMMENT '不可达原因',
  valid_from  DATETIME(3)  NULL COMMENT '生效起（空=即时）',
  valid_to    DATETIME(3)  NULL COMMENT '生效止（空=长期）',
  status      VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '状态：enabled生效/disabled失效',
  create_time DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version     INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted  TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  KEY idx_ful_unreach_area_corp (corp_id, area_id, status)
) ENGINE=InnoDB COMMENT='物流商×区域不可达黑名单（D09.04 §6.4）';

-- ---------------------------------------------------------------------
-- 18. ful_suspend 停运时间窗（SRS-D09.04 §6.4；分钟级生效）
-- ---------------------------------------------------------------------
CREATE TABLE ful_suspend (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id    BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id     BIGINT UNSIGNED NULL COMMENT '货主ID（配置表免填）',
  corp_id      BIGINT UNSIGNED NOT NULL COMMENT '物流商（LFK→ful_dly_corp.id）',
  area_id      BIGINT UNSIGNED NULL COMMENT '区域（空=全国停运）',
  suspend_from DATETIME(3)  NOT NULL COMMENT '停运起',
  suspend_to   DATETIME(3)  NOT NULL COMMENT '停运止',
  reason       VARCHAR(128) NULL COMMENT '停运原因：台风/疫情/网点异常等',
  status       VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '状态：enabled生效/disabled撤销停运',
  create_time  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version      INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted   TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  KEY idx_ful_suspend_corp_time (corp_id, suspend_from, suspend_to)
) ENGINE=InnoDB COMMENT='物流停运时间窗（D09.04 §6.4）';

-- ---------------------------------------------------------------------
-- 19. ful_addr_keyword 地址关键字（SRS-D09.04 §6.4，FR-03e）
-- ---------------------------------------------------------------------
CREATE TABLE ful_addr_keyword (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id   BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id    BIGINT UNSIGNED NULL COMMENT '货主ID（配置表免填）',
  keyword     VARCHAR(64)  NOT NULL COMMENT '关键字（乡村件地址特征等）',
  level       VARCHAR(8)   NOT NULL DEFAULT 'WARN' COMMENT '级别：WARN提示/BLOCK拦截',
  logi_limit  VARCHAR(256) NULL COMMENT '限定物流商（corp_code逗号分隔；空=全部命中即触发）',
  status      VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '状态：enabled启用/disabled停用',
  create_time DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version     INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted  TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  KEY idx_ful_addr_keyword_status (status)
) ENGINE=InnoDB COMMENT='地址关键字表（D09.04 §6.4；乡村件等WARN/BLOCK）';

-- ---------------------------------------------------------------------
-- 20. ful_shop_dly 店铺物流绑定（SRS-D09.04 §6.5 shop_dly）
-- ---------------------------------------------------------------------
CREATE TABLE ful_shop_dly (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id   BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id    BIGINT UNSIGNED NOT NULL COMMENT '货主ID（冗余店铺货主，必填）',
  shop_id     BIGINT UNSIGNED NOT NULL COMMENT '店铺（LFK→oms_gateway.gw_shop.id跨域）',
  corp_id     BIGINT UNSIGNED NOT NULL COMMENT '物流商（LFK→ful_dly_corp.id）',
  product_id  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '默认产品（LFK→ful_dly_product.id；0=分单时定）',
  is_default  TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '默认物流：0否/1是（一店一默认）',
  priority    INT         NOT NULL DEFAULT 0 COMMENT '优先级',
  branch_id   BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '仓级覆盖（0=店铺级；非0=该仓专用绑定，LFK→ful_branch.id）',
  status      VARCHAR(16) NOT NULL DEFAULT 'enabled' COMMENT '状态：enabled启用/disabled停用',
  create_time DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version     INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted  TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_shop_dly_unique (shop_id, corp_id, branch_id),
  KEY idx_ful_shop_dly_shop (shop_id, status)
) ENGINE=InnoDB COMMENT='店铺物流绑定（D09.04 §6.5；可用集合+默认+仓级覆盖FR-04a）';

-- ---------------------------------------------------------------------
-- 21. ful_branch_dly 仓-物流揽收关系（SRS-D09.04 §6.5 branch_dly，FR-04d）
-- ---------------------------------------------------------------------
CREATE TABLE ful_branch_dly (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id      BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NULL COMMENT '货主ID（配置表免填）',
  branch_id      BIGINT UNSIGNED NOT NULL COMMENT '仓库（LFK→ful_branch.id）',
  corp_id        BIGINT UNSIGNED NOT NULL COMMENT '物流商（LFK→ful_dly_corp.id）',
  product_id     BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '产品（0=物流商全部产品）',
  pickup_support TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '支持揽收：0否/1是',
  cutoff_time    CHAR(5)      NULL COMMENT '揽收截单（HH:mm）',
  pickup_window  VARCHAR(64)  NULL COMMENT '揽收时间窗（如09:00-18:00）',
  status         VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '状态：enabled启用/disabled停用',
  create_time    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version        INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted     TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_branch_dly_unique (branch_id, corp_id, product_id)
) ENGINE=InnoDB COMMENT='仓-物流揽收关系（D09.04 §6.5）';

-- ---------------------------------------------------------------------
-- 22. ful_freight_template 运费模板头（SRS-D09.04 §6.6；D08.04预估运费数据源）
--     ← 商派 ome.dly_corp 首重续重字段拆出+版本化
-- ---------------------------------------------------------------------
CREATE TABLE ful_freight_template (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id      BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NULL COMMENT '货主ID（协议价粒度可选；空=租户级）',
  corp_id        BIGINT UNSIGNED NOT NULL COMMENT '物流商（LFK→ful_dly_corp.id）',
  product_id     BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '产品（0=物流商通用模板）',
  template_name  VARCHAR(128) NOT NULL COMMENT '模板名称',
  charge_mode    VARCHAR(16)  NOT NULL DEFAULT 'weight' COMMENT '计费模式：weight首重续重/piece按件/volume_max体积重取大',
  first_weight   DECIMAL(9,3) NULL COMMENT '首重kg',
  first_price    DECIMAL(18,2) NULL COMMENT '首重价（缺省，区域行可覆盖）',
  add_weight     DECIMAL(9,3) NULL COMMENT '续重单位kg',
  add_price      DECIMAL(18,2) NULL COMMENT '续重价（缺省）',
  volume_factor  INT UNSIGNED NULL COMMENT '体积重系数（如6000：长宽高cm/系数=体积重kg）',
  protect_rate   DECIMAL(9,4) NULL COMMENT '保价费率',
  discount_json  JSON         NULL COMMENT '折扣协议：{discount_rate,monthly_settle}',
  tmpl_version   INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '模板版本（版本化留痕FR-05c）',
  effective_from DATETIME(3)  NOT NULL COMMENT '生效时间',
  status         VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '状态：enabled启用/disabled停用/archived归档',
  create_time    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version        INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted     TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_freight_template_ver (corp_id, product_id, tmpl_version),
  KEY idx_ful_freight_template_corp (corp_id, product_id, status)
) ENGINE=InnoDB COMMENT='运费模板头（D09.04 §6.6；首重续重版本化）';

-- ---------------------------------------------------------------------
-- 23. ful_freight_region_price 运费模板区域报价行（SRS-D09.04 §6.6）
-- ---------------------------------------------------------------------
CREATE TABLE ful_freight_region_price (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NULL COMMENT '货主ID（同模板头）',
  template_id     BIGINT UNSIGNED NOT NULL COMMENT '模板头（LFK→ful_freight_template.id）',
  from_region     VARCHAR(16)  NOT NULL COMMENT '发货区域（仓region_code）',
  to_area_id      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '收货区域（省/市area_id；0=缺省行兜底）',
  to_area_level   TINYINT      NOT NULL DEFAULT 2 COMMENT '区域级别：2省/3市',
  first_price     DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '首重价',
  add_price       DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '续重价',
  timeliness_days INT UNSIGNED NULL COMMENT '承诺时效天数',
  default_flag    TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '缺省行：0否/1是（模板内from_region维度唯一缺省）',
  create_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted      TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_freight_region_price_unique (template_id, from_region, to_area_level, to_area_id),
  KEY idx_ful_freight_region_price_tmpl (template_id, from_region, to_area_id)
) ENGINE=InnoDB COMMENT='运费模板区域报价行（D09.04 §6.6；缺省行兜底）';

-- ---------------------------------------------------------------------
-- 24. ful_trace_sub 轨迹订阅登记（SRS-D09.04 §6.7，P1预留）
-- ---------------------------------------------------------------------
CREATE TABLE ful_trace_sub (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id   BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id    BIGINT UNSIGNED NULL COMMENT '货主ID',
  waybill_no  VARCHAR(64)  NOT NULL COMMENT '运单号（幂等：唯一）',
  corp_id     BIGINT UNSIGNED NOT NULL COMMENT '物流商（LFK→ful_dly_corp.id）',
  provider    VARCHAR(16)  NOT NULL DEFAULT 'kuaidi100' COMMENT '订阅通道：kuaidi100快递100/cainiao菜鸟',
  delivery_id BIGINT UNSIGNED NULL COMMENT '发货单（跨域LFK→oms_order.ord_delivery）',
  sub_status  VARCHAR(16)  NOT NULL DEFAULT 'subscribed' COMMENT '订阅状态：subscribed已订阅/closed已关闭(签收退签)/failed订阅失败',
  sub_time    DATETIME(3)  NOT NULL COMMENT '订阅时间',
  create_time DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version     INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_trace_sub_waybill (waybill_no),
  KEY idx_ful_trace_sub_status (sub_status)
) ENGINE=InnoDB COMMENT='物流轨迹订阅登记（D09.04 §6.7，P1预留）';

-- ---------------------------------------------------------------------
-- 25. ful_trace_node 轨迹节点（SRS-D09.04 §6.7，P1；只增不改）
-- ---------------------------------------------------------------------
CREATE TABLE ful_trace_node (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id   BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id    BIGINT UNSIGNED NULL COMMENT '货主ID',
  waybill_no  VARCHAR(64)  NOT NULL COMMENT '运单号',
  node_time   DATETIME(3)  NOT NULL COMMENT '节点时间',
  node_status VARCHAR(16)  NOT NULL COMMENT '节点状态：collected揽收/transit运输/delivering派送/signed签收/returned退签/exception异常',
  node_desc   VARCHAR(256) NULL COMMENT '节点描述',
  city        VARCHAR(32)  NULL COMMENT '所在城市',
  source      VARCHAR(16)  NOT NULL DEFAULT 'provider' COMMENT '来源：provider订阅推送/manual人工登记',
  create_time DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  KEY idx_ful_trace_node_waybill (waybill_no, node_time)
) ENGINE=InnoDB COMMENT='物流轨迹节点（D09.04 §6.7，P1；只增不改）';

-- ---------------------------------------------------------------------
-- 26. ful_waybill_account 面单账号档案（SRS-D09.05 §6.1）← 商派 logisticsmanager.channel 改造
-- ---------------------------------------------------------------------
CREATE TABLE ful_waybill_account (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id      BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NULL COMMENT '货主ID（共享池账号可空）',
  account_type   VARCHAR(16)  NOT NULL COMMENT '账号类型：cainiao菜鸟/platform平台系/direct快递直客/none无需面单（FR-01a字典可扩展）',
  corp_id        BIGINT UNSIGNED NULL COMMENT '归属物流商（LFK→ful_dly_corp.id；none类可空）',
  shop_id        BIGINT UNSIGNED NULL COMMENT '店铺（platform类必挂店铺，跨域LFK→gw_shop；cainiao/direct可空=共享池）',
  account_name   VARCHAR(128) NOT NULL COMMENT '账号名称',
  monthly_code   VARCHAR(64)  NULL COMMENT '月结编码（direct类必填：customerCode/月结卡号）',
  site_info_json JSON         NULL COMMENT '网点信息（cainiao类：{site_code网点编码,sender_address发货地址}）',
  app_key        VARCHAR(128) NULL COMMENT '账号appKey（非敏感部分）',
  secret_enc     VARBINARY(1024) NULL COMMENT '密钥/token密文（KMS信封加密，D01.05）',
  key_version    VARCHAR(32)  NOT NULL DEFAULT 'v1' COMMENT '密钥版本',
  daily_limit    INT UNSIGNED NULL COMMENT '日限额（空=不限；轮询剔除依据FR-04a）',
  daily_used     INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '日已用（每日零点重置）',
  pool_balance   INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '号池余量（冗余视图；实时源=ful_waybill_segment）',
  priority       INT          NOT NULL DEFAULT 0 COMMENT '优先级（加权轮询）',
  weight         INT          NOT NULL DEFAULT 1 COMMENT '权重（加权轮询）',
  circuit_status VARCHAR(16)  NOT NULL DEFAULT 'closed' COMMENT '熔断状态：closed正常/open熔断中/half_open半开探测（FR-04b）',
  last_test_time DATETIME(3)  NULL COMMENT '最近连通性测试时间（FR-01g）',
  test_result    VARCHAR(16)  NULL COMMENT '测试结果：succ成功/fail失败',
  status         VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '启停：enabled启用/disabled停用',
  create_time    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version        INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted     TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  KEY idx_ful_waybill_account_corp (corp_id, account_type, status),
  KEY idx_ful_waybill_account_shop (shop_id)
) ENGINE=InnoDB COMMENT='面单账号档案（D09.05 §6.1；类型=菜鸟/平台系/直客）';

-- ---------------------------------------------------------------------
-- 27. ful_waybill_segment 面单号段预取缓存（SRS-D09.05 §6.2 waybill_pool）
-- ---------------------------------------------------------------------
CREATE TABLE ful_waybill_segment (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id     BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id      BIGINT UNSIGNED NULL COMMENT '货主ID（随账号归属）',
  account_id    BIGINT UNSIGNED NOT NULL COMMENT '面单账号（LFK→ful_waybill_account.id）',
  corp_id       BIGINT UNSIGNED NOT NULL COMMENT '物流商（快照冗余）',
  product_code  VARCHAR(32)  NOT NULL COMMENT '产品编码（账号×物流商×产品粒度）',
  segment_start VARCHAR(64)  NOT NULL COMMENT '号段起（运单号字符串，兼容非纯数字）',
  segment_end   VARCHAR(64)  NOT NULL COMMENT '号段止',
  allocated_to  VARCHAR(64)  NULL COMMENT '已分配水位（≤segment_end；DB对账基准FR-03e）',
  expire_date   DATE         NULL COMMENT '号段有效期（T-1归还调度依据FR-03d）',
  status        VARCHAR(16)  NOT NULL DEFAULT 'in_pool' COMMENT '状态：in_pool在池/partial部分分配/exhausted已耗尽/returned已归还',
  create_time   DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time   DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version       INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  PRIMARY KEY (id),
  KEY idx_ful_waybill_segment_account (account_id, product_code, status),
  KEY idx_ful_waybill_segment_expire (expire_date, status)
) ENGINE=InnoDB COMMENT='面单号段预取缓存（D09.05 §6.2；DB为号池对账基准）';

-- ---------------------------------------------------------------------
-- 28. ful_waybill 运单号取号台账（SRS-D09.05 §6.3）← 商派 logisticsmanager.waybill 改造
-- ---------------------------------------------------------------------
CREATE TABLE ful_waybill (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id      BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id       BIGINT UNSIGNED NOT NULL COMMENT '货主ID（SRS-00契约必填）',
  shop_id        BIGINT UNSIGNED NULL COMMENT '店铺（跨域LFK→oms_gateway.gw_shop）',
  waybill_no     VARCHAR(64)  NOT NULL COMMENT '运单号（台账业务主键成分）',
  delivery_id    BIGINT UNSIGNED NULL COMMENT '发货单（跨域LFK→oms_order.ord_delivery；幂等键成分）',
  package_no     VARCHAR(32)  NOT NULL DEFAULT '1' COMMENT '包裹号（一单多包；幂等键成分）',
  order_ref      VARCHAR(64)  NULL COMMENT '订单引用（冗余检索）',
  corp_id        BIGINT UNSIGNED NOT NULL COMMENT '物流商快照（取号时点，账号变更不漂移）',
  product_code   VARCHAR(32)  NOT NULL COMMENT '产品编码快照',
  account_id     BIGINT UNSIGNED NOT NULL COMMENT '面单账号快照（LFK→ful_waybill_account.id）',
  big_head       VARCHAR(32)  NULL COMMENT '大头笔（分拣要素，随指令下发）',
  gather_place   VARCHAR(64)  NULL COMMENT '集包地',
  route_label    VARCHAR(64)  NULL COMMENT '路由标签',
  print_data_ref VARCHAR(256) NULL COMMENT '打印数据引用（云打印报文ID/PDF文件ID/平台URL）',
  template_id    BIGINT UNSIGNED NULL COMMENT '模板快照（LFK→ful_print_template.id）',
  cipher_flag    TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '密文单标记：0明文/1平台密文（不落明文§5.4）',
  source         VARCHAR(16)  NOT NULL DEFAULT 'oms' COMMENT '取号来源：oms默认/wms例外仓回传登记/manual人工登记',
  status         VARCHAR(16)  NOT NULL DEFAULT 'getting' COMMENT '生命周期：getting取号中/obtained已取号/printed已打印/used已使用/cancelled已作废/returning退回中/expired已过期（FR-08a）',
  reprint_count  INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '补打次数（FR-07c）',
  cancel_reason  VARCHAR(128) NULL COMMENT '作废原因（FR-02f）',
  idempotent_key VARCHAR(160) NOT NULL COMMENT '幂等键（delivery_id+package_no+取号轮次派生；防重复取号）',
  get_time       DATETIME(3)  NULL COMMENT '取号时间',
  print_time     DATETIME(3)  NULL COMMENT '打印时间',
  used_time      DATETIME(3)  NULL COMMENT '使用时间（出库回传核销）',
  expire_time    DATETIME(3)  NULL COMMENT '过期时间（对账与清理依据）',
  create_time    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version        INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_waybill_idem (idempotent_key),
  UNIQUE KEY uk_ful_waybill_no (waybill_no),
  KEY idx_ful_waybill_delivery (delivery_id),
  KEY idx_ful_waybill_status (status, create_time),
  KEY idx_ful_waybill_account_time (account_id, get_time)
) ENGINE=InnoDB COMMENT='运单号取号台账（D09.05 §6.3；幂等防重复取号）';

-- ---------------------------------------------------------------------
-- 29. ful_print_template 面单打印模板（SRS-D09.05 §6.5）← 商派 ome.print_tmpl 沿袭
-- ---------------------------------------------------------------------
CREATE TABLE ful_print_template (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id        BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NULL COMMENT '货主ID（配置表免填）',
  tmpl_name        VARCHAR(128) NOT NULL COMMENT '模板名称',
  tmpl_type        VARCHAR(16)  NOT NULL COMMENT '模板类型：standard标准/custom自定义/cloud云打印/local本地渲染',
  corp_id          BIGINT UNSIGNED NULL COMMENT '物流商（空=通用模板）',
  provider_tmpl_id VARCHAR(128) NULL COMMENT '服务商模板ID（菜鸟/快递100云打印模板）',
  width_mm         INT UNSIGNED NOT NULL DEFAULT 100 COMMENT '宽度mm（商派print_tmpl宽高建模沿袭）',
  height_mm        INT UNSIGNED NOT NULL DEFAULT 180 COMMENT '高度mm',
  offset_x         INT          NOT NULL DEFAULT 0 COMMENT 'X偏移mm（可负）',
  offset_y         INT          NOT NULL DEFAULT 0 COMMENT 'Y偏移mm',
  custom_area_json JSON         NULL COMMENT '自定义区定义：[{name,x,y,w,h,fields[]}]',
  file_ref         VARCHAR(256) NULL COMMENT '模板文件引用（OSS）',
  status           VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '状态：enabled启用/disabled停用',
  create_time      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted       TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  KEY idx_ful_print_template_corp (corp_id, tmpl_type, status)
) ENGINE=InnoDB COMMENT='面单打印模板（D09.05 §6.5）';

-- ---------------------------------------------------------------------
-- 30. ful_print_tmpl_binding 打印模板绑定（SRS-D09.05 §6.5 binding，FR-05b）
-- ---------------------------------------------------------------------
CREATE TABLE ful_print_tmpl_binding (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id   BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id    BIGINT UNSIGNED NULL COMMENT '货主ID（冗余店铺货主）',
  shop_id     BIGINT UNSIGNED NOT NULL COMMENT '店铺（跨域LFK→oms_gateway.gw_shop）',
  corp_id     BIGINT UNSIGNED NOT NULL COMMENT '物流商（LFK→ful_dly_corp.id）',
  product_id  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '产品（0=物流商全部产品）',
  template_id BIGINT UNSIGNED NOT NULL COMMENT '模板（LFK→ful_print_template.id）',
  is_default  TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '默认绑定：0否/1是',
  status      VARCHAR(16) NOT NULL DEFAULT 'enabled' COMMENT '状态：enabled启用/disabled停用',
  create_time DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version     INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  is_deleted  TINYINT(1)  NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_print_tmpl_binding_unique (shop_id, corp_id, product_id)
) ENGINE=InnoDB COMMENT='打印模板绑定：店铺×物流商(×产品)（D09.05 §6.5）';

-- ---------------------------------------------------------------------
-- 31. ful_print_task 打印任务队列（SRS-D09.05 §6.4 queue+item合并）← 商派 ome.print_queue 改造
-- ---------------------------------------------------------------------
CREATE TABLE ful_print_task (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键（task_id）',
  tenant_id    BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id     BIGINT UNSIGNED NOT NULL COMMENT '货主ID（SRS-00契约必填）',
  batch_no     VARCHAR(32)  NOT NULL COMMENT '打印批次号（Redis发号；同批任务共享）',
  batch_md5    CHAR(32)     NULL COMMENT '批次内容MD5（重复提交幂等，商派print_queue.md5沿袭；NULL不参与唯一约束）',
  initiator    VARCHAR(64)  NOT NULL COMMENT '发起人（操作人/系统任务）',
  channel      VARCHAR(16)  NOT NULL DEFAULT 'wh_client' COMMENT '下发通道：wh_client仓内客户端/central集中打印/store门店',
  target_client VARCHAR(64) NULL COMMENT '下发目标（仓内客户端标识/打印机编号）',
  branch_id    BIGINT UNSIGNED NULL COMMENT '仓库（仓内打印场景，LFK→ful_branch.id）',
  delivery_id  BIGINT UNSIGNED NOT NULL COMMENT '发货单（跨域LFK→oms_order.ord_delivery）',
  delivery_bn  VARCHAR(32)  NOT NULL COMMENT '发货单号（冗余，商派dly_bns沿袭）',
  package_no   VARCHAR(32)  NOT NULL DEFAULT '1' COMMENT '包裹号',
  waybill_no   VARCHAR(64)  NULL COMMENT '运单号（逻辑关联ful_waybill.waybill_no）',
  template_id  BIGINT UNSIGNED NULL COMMENT '模板快照（LFK→ful_print_template.id）',
  task_status  VARCHAR(16)  NOT NULL DEFAULT 'pending' COMMENT '任务状态：pending待下发/sent已下发/printed已打印/failed失败/reprinted已补打',
  retry_count  INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '重试次数',
  fail_reason  VARCHAR(256) NULL COMMENT '失败原因',
  sent_time    DATETIME(3)  NULL COMMENT '下发时间',
  printed_time DATETIME(3)  NULL COMMENT '打印回执时间',
  create_time  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version      INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁版本号',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_print_task_md5 (batch_md5),
  KEY idx_ful_print_task_batch (batch_no),
  KEY idx_ful_print_task_status (task_status, create_time),
  KEY idx_ful_print_task_delivery (delivery_id, package_no)
) ENGINE=InnoDB COMMENT='打印任务队列（D09.05 §6.4；下发目标=仓内客户端）';

-- ---------------------------------------------------------------------
-- 32. ful_print_log 打印操作台账（SRS-D09.05 §6.4 log；只增不改）
-- ---------------------------------------------------------------------
CREATE TABLE ful_print_log (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id    BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id     BIGINT UNSIGNED NULL COMMENT '货主ID',
  task_id      BIGINT UNSIGNED NOT NULL COMMENT '打印任务（LFK→ful_print_task.id）',
  action       VARCHAR(16)  NOT NULL COMMENT '动作：send下发/receipt回执/reprint补打/resend重发',
  channel      VARCHAR(16)  NOT NULL COMMENT '通道：wh_client仓内客户端/central集中/store门店',
  operator     VARCHAR(64)  NULL COMMENT '操作人（回执为系统时=client标识）',
  receipt_time DATETIME(3)  NULL COMMENT '回执时间',
  raw_ref      VARCHAR(256) NULL COMMENT '原始报文引用（OSS）',
  create_time  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  KEY idx_ful_print_log_task (task_id, create_time)
) ENGINE=InnoDB COMMENT='打印操作台账（D09.05 §6.4；回执与人工操作留痕）';

-- =====================================================================
-- 初始数据
-- =====================================================================

-- 物流公司样例（平台级共享档案，owner_id=NULL=系统）
INSERT INTO ful_dly_corp (corp_code, corp_name, short_name, corp_type, waybill_account_type, service_tags, pickup_mode) VALUES
('sf',     '顺丰速运', '顺丰', 'express', 'direct',   '["贵重","签返"]', 'door'),
('zto',    '中通快递', '中通', 'express', 'cainiao',  NULL, 'door'),
('yto',    '圆通速递', '圆通', 'express', 'cainiao',  NULL, 'door'),
('sto',    '申通快递', '申通', 'express', 'cainiao',  NULL, 'door'),
('yunda',  '韵达速递', '韵达', 'express', 'cainiao',  NULL, 'door'),
('jd',     '京东物流', '京东', 'express', 'platform', '["大件","到付"]', 'door'),
('ems',    '中国邮政EMS', 'EMS', 'postal', 'direct',  '["冷链"]', 'self'),
('deppon', '德邦快递', '德邦', 'freight', 'direct',   '["大件"]', 'door'),
('shansong','闪送',    '闪送', 'samecity', 'none',    NULL, 'door');

-- 物流产品样例（product_code=面单取号 express_type 映射源）
INSERT INTO ful_dly_product (corp_id, product_code, product_name, product_type, weight_min, weight_max) VALUES
((SELECT id FROM ful_dly_corp WHERE corp_code='sf'), 'sf_std',  '顺丰标快', 'standard', 0, 50),
((SELECT id FROM ful_dly_corp WHERE corp_code='sf'), 'sf_eco',  '顺丰特惠', 'economy',  0, 50),
((SELECT id FROM ful_dly_corp WHERE corp_code='zto'), 'zto_std', '中通标准', 'standard', 0, 30),
((SELECT id FROM ful_dly_corp WHERE corp_code='jd'),  'jd_std',  '京东特快', 'express',  0, 30),
((SELECT id FROM ful_dly_corp WHERE corp_code='deppon'),'db_bulk','德邦大件','bulky',    3, 500);

-- 区域路由规则样例结构（logi_seq 引用物流商/产品 ID；含全国缺省行）
INSERT INTO ful_area_router (rule_name, area_level, area_id, conditions, logi_seq, weight, default_flag) VALUES
('华东默认-中通优先', 1, 0,
 '{"branch_region":["华东"],"weight_range":[0,30]}',
 CONCAT('[{"corp_id":',(SELECT id FROM ful_dly_corp WHERE corp_code='zto'),',"product_id":',(SELECT id FROM ful_dly_product WHERE product_code='zto_std'),',"priority":1},',
        '{"corp_id":',(SELECT id FROM ful_dly_corp WHERE corp_code='yto'),',"product_id":0,"priority":2}]'),
 100, 0),
('全国缺省-顺丰兜底', 1, 0,
 NULL,
 CONCAT('[{"corp_id":',(SELECT id FROM ful_dly_corp WHERE corp_code='sf'),',"product_id":',(SELECT id FROM ful_dly_product WHERE product_code='sf_std'),',"priority":1}]'),
 0, 1),
('上海市-京东平台单', 2, 310000,
 '{"platform":["jd"]}',
 CONCAT('[{"corp_id":',(SELECT id FROM ful_dly_corp WHERE corp_code='jd'),',"product_id":',(SELECT id FROM ful_dly_product WHERE product_code='jd_std'),',"priority":1}]'),
 200, 0);

-- 地址关键字样例
INSERT INTO ful_addr_keyword (keyword, level, logi_limit) VALUES
('乡', 'WARN', NULL),
('村', 'WARN', 'zto,yto,sto,yunda'),
('海岛', 'BLOCK', NULL);

-- 运费模板样例（首重续重；D08.04 预估运费数据源）
INSERT INTO ful_freight_template (corp_id, product_id, template_name, charge_mode, first_weight, first_price, add_weight, add_price, volume_factor, effective_from) VALUES
((SELECT id FROM ful_dly_corp WHERE corp_code='zto'),
 (SELECT id FROM ful_dly_product WHERE product_code='zto_std'),
 '中通标准-华东发货', 'weight', 1.000, 4.00, 1.000, 1.00, 12000, '2026-11-01 00:00:00');

-- 运费模板区域报价行样例（含缺省兜底行）
INSERT INTO ful_freight_region_price (template_id, from_region, to_area_id, to_area_level, first_price, add_price, timeliness_days, default_flag) VALUES
((SELECT id FROM ful_freight_template WHERE template_name='中通标准-华东发货'), '华东', 310000, 2, 4.00, 1.00, 2, 0),
((SELECT id FROM ful_freight_template WHERE template_name='中通标准-华东发货'), '华东', 440000, 2, 5.00, 2.00, 3, 0),
((SELECT id FROM ful_freight_template WHERE template_name='中通标准-华东发货'), '华东', 0,      2, 6.00, 3.00, 5, 1);

-- WMS 服务商样例
INSERT INTO ful_wms (wms_code, wms_name, protocol, adapter_code) VALUES
('ttx',   '通天晓WMS', 'ttx_rest', 'ttx-adapter'),
('flux',  '富勒WMS',   'restful',  'flux-adapter'),
('wln',   '万里牛WMS', 'qimen',    'wln-adapter'),
('qimen', '奇门通用WMS','qimen',   'qimen-adapter');

-- =====================================================================
-- V1.2 增补（2026-10-24，友商对标 7 项决策落地）
--   SRS-D09.06 同城配送运力对接（新模块 P1，G1 决策）§6 全量 9 表：
--   物理表名=SRS 实体名按 DB-00 §2.1 域前缀规范化（fulfill_carrier→ful_carrier 等，
--   一一对应关系见 DB-D09 字典 V1.2 说明）：
--     §6.1 fulfill_carrier        → ful_carrier           运力方档案
--     §6.2 fulfill_rider_call     → ful_rider_call        呼叫单
--     §6.3 fulfill_rider_track    → ful_rider_track       状态轨迹（只增）
--     §6.3 fulfill_handover       → ful_handover          交接凭证（只增）
--     §6.4 fulfill_city_freight   → ful_city_freight      同城配送费台账
--     §6.5 fulfill_call_decision  → ful_call_decision     比价决策快照（只增）
--     §6.5 fulfill_carrier_metric → ful_carrier_metric    运力方滚动指标
--     §6.5 fulfill_shop_carrier   → ful_shop_carrier      店铺运力绑定
--     §6.5 store_carrier_map      → ful_store_carrier_map 运力方门店ID映射
--   溯源：商派美团系 5 适配目录配送能力散落无聚合层；本设计收敛为独立运力聚合层
-- =====================================================================

-- ---------------------------------------------------------------------
-- V1.2-33. ful_carrier 运力方档案（SRS-D09.06 §6.1；治理规则同 ful_dly_corp）
-- ---------------------------------------------------------------------
CREATE TABLE ful_carrier (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NULL COMMENT '归属货主（平台级共享档案=系统货主，SRS-00契约）',
  carrier_code    VARCHAR(32)  NOT NULL COMMENT 'canonical运力编码（全局唯一不可变，治理同D09.04 FR-01c）：MEITUAN_PAOTUI美团跑腿/FENGNIAO蜂鸟即配/DADA达达快送/SHANSONG闪送/SF_CITY顺丰同城/SELF品牌自配送(内置虚拟运力方)',
  carrier_name    VARCHAR(128) NOT NULL COMMENT '运力方名称',
  short_name      VARCHAR(32)  NULL COMMENT '简称',
  carrier_type    VARCHAR(16)  NOT NULL COMMENT '类型：platform_self平台自营(美团跑腿/蜂鸟)/crowdsource第三方众包(达达/闪送)/express_city快递同城(顺丰同城)/brand_self品牌自配送(SELF)',
  service_cities  JSON         NULL COMMENT '服务城市集（city_code列表，候选过滤输入FR-02b）',
  pickup_radius   DECIMAL(9,4) NULL COMMENT '取货范围km（门店半径；空=城市内不限）',
  capability_flags JSON        NULL COMMENT '能力声明（FR-01d白名单）：{reservation预约单,update变更,pre_query询价,trajectory轨迹}',
  agreement_json  JSON         NULL COMMENT '计费协议：{discount_rate折扣系数,price_list_ref价目表引用,monthly_account月结账号}',
  app_key         VARCHAR(128) NULL COMMENT '开放平台appKey（FR-01b接入凭证，D02.01框架托管口径；SELF为空）',
  secret_enc      VARBINARY(1024) NULL COMMENT '开放平台secret密文（D01.05 L3信封加密）',
  circuit_status  VARCHAR(16)  NOT NULL DEFAULT 'closed' COMMENT '熔断状态（FR-01f运行态）：closed闭合/open开启(剔除比价候选,存量在途回调仍消费)/half_open半开探测(每2分钟询价x3成功即闭合)',
  suspend_json    JSON         NULL COMMENT '停运配置：[{city_code,start_time,end_time}]（城市x时间窗，分钟级生效，FR-01g，同D09.04停运表机制）',
  status          VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '启停：enabled启用/disabled停用（停用不参与新派发，在途单不受影响，D09.04 FR-01c同口径；变更审计D10.06）',
  create_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted      TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_carrier_code (carrier_code),
  KEY idx_ful_carrier_status (status, circuit_status)
) ENGINE=InnoDB COMMENT='运力方档案（canonical编码/服务城市/能力声明/计费协议/熔断停运，治理同ful_dly_corp，P1，D09.06）';

-- ---------------------------------------------------------------------
-- V1.2-34. ful_rider_call 呼叫单（SRS-D09.06 §6.2；幂等键=(delivery_id,call_round)）
-- ---------------------------------------------------------------------
CREATE TABLE ful_rider_call (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id            BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id             BIGINT UNSIGNED NOT NULL COMMENT '货主ID（必填）',
  call_no              VARCHAR(32)  NOT NULL COMMENT '呼叫单号（唯一；RC+yyMMdd+序列，Redis发号器）',
  delivery_id          BIGINT UNSIGNED NOT NULL COMMENT '关联发货单（LFK→oms_order.ord_delivery跨域；幂等键=(delivery_id,call_round)）',
  order_id             BIGINT UNSIGNED NOT NULL COMMENT '关联订单（LFK→oms_order.ord_order跨域）',
  call_round           INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '呼叫轮次（≥1；>3告警；改派单调递增）',
  pre_call_flag        TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '预呼叫标记：0否/1是（拣货进度≥70%提前呼叫，FR-02e）',
  expected_pickup_time DATETIME(3)  NULL COMMENT '预计取货时间（预呼叫：支持预约语义下预约单，不支持走延迟派发定时器）',
  carrier_code         VARCHAR(32)  NOT NULL COMMENT '运力方编码（LFK→ful_carrier；受理成功必填；SELF=自配送兜底）',
  carrier_order_no     VARCHAR(64)  NULL COMMENT '运力方单号（受理回执；账单匹配键；回调幂等成分）',
  status               VARCHAR(24)  NOT NULL DEFAULT 'called' COMMENT '标准化状态（§4.2权威状态机）：called已呼叫/accepted已受理/rider_assigned骑手已接单/rider_arrived骑手到店/picked_up已取货(交接完成)/delivering配送中/delivered已送达/call_failed呼叫失败/cancelled已取消(窗口内外)/rider_cancelled骑手取消(改派触发)/delivery_exception配送异常(失联/事故/拒收)',
  pickup_code          CHAR(6)      NULL COMMENT '取货码（6位数字一次一码：呼叫单维度唯一，受理成功即生成随单下发，骑手App展示；错误码连续5次锁定10分钟）',
  code_voided          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '取货码作废标记：0有效/1作废（改派新轮次换码旧码作废，防重放留痕）',
  promise_time         DATETIME(3)  NOT NULL COMMENT '期望送达时间（比价时效分输入）',
  eta_time             DATETIME(3)  NULL COMMENT '预计送达时间（运力方回执/询价）',
  est_price            DECIMAL(18,2) NULL COMMENT '预估价（询价/协议价目表估算）',
  decision_snapshot_id BIGINT UNSIGNED NULL COMMENT '比价决策快照引用（LFK→ful_call_decision，FR-02c回放依据）',
  cancel_fee           DECIMAL(18,2) NULL COMMENT '取消费（窗口外取消产生，台账归集输入）',
  wait_fee             DECIMAL(18,2) NULL COMMENT '等待费（骑手到店拣货未完成被取消场景，责任=门店）',
  fee_liability        VARCHAR(16)  NULL COMMENT '费用责任方：store门店/carrier运力方/system系统',
  courier_name         VARCHAR(64)  NULL COMMENT '骑手姓名（脱敏展示，FR-03e）',
  courier_phone_enc    VARBINARY(512) NULL COMMENT '骑手手机密文（PIPL D01.05；联系经隐私号，明文拒绝下发）',
  self_courier_id      BIGINT UNSIGNED NULL COMMENT '自配送员ID（SELF模式，courier_pool池内引用）',
  assign_mode          VARCHAR(16)  NULL COMMENT '自配送指派方式：assign店长指派/grab抢单(先抢先得并发锁防双抢)（FR-06c）',
  store_branch_id      BIGINT UNSIGNED NOT NULL COMMENT '取货门店仓（LFK→ful_branch跨域引用oms_order.ord_store_profile）',
  shop_id              BIGINT UNSIGNED NOT NULL COMMENT '店铺ID（LFK→oms_gateway.gw_shop跨域）',
  create_time          DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time          DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version              INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁（状态机CAS+呼叫单级分布式锁DB侧兜底）',
  is_deleted           TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_rider_call_no (call_no),
  UNIQUE KEY uk_ful_rider_call_idem (delivery_id, call_round),
  KEY idx_ful_rider_call_carrier_order (carrier_order_no),
  KEY idx_ful_rider_call_status (status, create_time),
  KEY idx_ful_rider_call_store (store_branch_id, create_time)
) ENGINE=InnoDB COMMENT='骑手呼叫单（比价派发/顺位改派/预呼叫/取货码/自配送兜底，幂等键=(delivery_id,call_round)，P1，D09.06）';

-- ---------------------------------------------------------------------
-- V1.2-35. ful_rider_track 配送状态轨迹（SRS-D09.06 §6.3 track；只增不改）
-- ---------------------------------------------------------------------
CREATE TABLE ful_rider_track (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL COMMENT '货主ID（必填）',
  call_id         BIGINT UNSIGNED NOT NULL COMMENT '呼叫单ID（LFK→ful_rider_call）',
  call_no         VARCHAR(32)  NOT NULL COMMENT '呼叫单号（冗余，查询加速）',
  carrier_order_no VARCHAR(64) NULL COMMENT '运力方单号（回调幂等去重键成分）',
  std_status      VARCHAR(24)  NOT NULL COMMENT '标准化状态（枚举同ful_rider_call.status，§4.2状态机流转校验后落库）',
  native_status   VARCHAR(64)  NOT NULL COMMENT '运力方原生状态（enum_mapping映射前原文；未命中映射进异常缓冲+P1告警不静默）',
  carrier_ts      DATETIME(3)  NOT NULL COMMENT '运力方状态时间戳（回调携带；幂等去重键=(carrier_order_no,native_status,carrier_ts)）',
  receive_ts      DATETIME(3)  NOT NULL COMMENT 'OMS接收时间（推送延迟监控输入）',
  source          VARCHAR(16)  NOT NULL DEFAULT 'callback' COMMENT '来源：callback回调/query反查(停滞定时扫描/乱序校正)/supplement补录(送达后回调缺失反查补录+差异标记)',
  rider_snapshot  JSON         NULL COMMENT '骑手信息快照（姓名/手机号脱敏/运力方；状态广播payload留档）',
  lng             DECIMAL(10,6) NULL COMMENT '轨迹点经度（P2预留，FR-03d；P1仅落关键节点不采集连续轨迹）',
  lat             DECIMAL(10,6) NULL COMMENT '轨迹点纬度（P2预留）',
  point_ts        DATETIME(3)  NULL COMMENT '轨迹点时间（P2预留；在线7天滚动清理）',
  create_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间（只增不改无update_time）',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_rider_track_idem (carrier_order_no, native_status, carrier_ts),
  KEY idx_ful_rider_track_call (call_id, carrier_ts),
  KEY idx_ful_rider_track_time (create_time)
) ENGINE=InnoDB COMMENT='骑手配送状态轨迹（回调标准化流水，幂等去重，乱序反查校正留痕，只增不改，P1，D09.06）';

-- ---------------------------------------------------------------------
-- V1.2-36. ful_handover 交接凭证（SRS-D09.06 §6.3 handover；只增，举证链）
-- ---------------------------------------------------------------------
CREATE TABLE ful_handover (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL COMMENT '货主ID（必填）',
  call_id         BIGINT UNSIGNED NOT NULL COMMENT '呼叫单ID（LFK→ful_rider_call）',
  call_no         VARCHAR(32)  NOT NULL COMMENT '呼叫单号（冗余）',
  pickup_code     CHAR(6)      NOT NULL COMMENT '核验取货码（一次一码；核验链：码存在→属本呼叫单→未核验未作废→锁定检查）',
  verify_operator VARCHAR(64)  NOT NULL COMMENT '核验店员账户（操作绑定账户审计D10.06）',
  verify_time     DATETIME(3)  NOT NULL COMMENT '核验交接时间（货损责任分界=交接时点：交接前门店/交接后运力方）',
  item_snapshot   JSON         NOT NULL COMMENT '货品清单快照（核对确认时点固化，举证链依据）',
  verify_mode     VARCHAR(16)  NOT NULL DEFAULT 'scan' COMMENT '交接方式：scan扫码核验/supplement补录(回调已取货但无扫码记录→差异标记+P1告警+店员确认备注)',
  diff_flag       TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '交接差异标记：0正常/1差异（未扫码补录=举证链缺口标记）',
  remark          VARCHAR(512) NULL COMMENT '补录备注原因（verify_mode=supplement必填）',
  store_branch_id BIGINT UNSIGNED NOT NULL COMMENT '交接门店仓（LFK→ful_branch）',
  create_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间（只增不改无update_time）',
  PRIMARY KEY (id),
  KEY idx_ful_handover_call (call_id),
  KEY idx_ful_handover_diff (diff_flag, create_time)
) ENGINE=InnoDB COMMENT='骑手交接凭证（店员扫码核验：码/账户/时间/清单快照/差异标记，货损纠纷举证链，只增不改，P1，D09.06）';

-- ---------------------------------------------------------------------
-- V1.2-37. ful_city_freight 同城配送费台账（SRS-D09.06 §6.4；D08.04账单体系扩展）
-- ---------------------------------------------------------------------
CREATE TABLE ful_city_freight (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id            BIGINT UNSIGNED NOT NULL COMMENT '货主ID（必填，货主分账口径）',
  call_no             VARCHAR(32)  NOT NULL COMMENT '呼叫单号（LFK→ful_rider_call）',
  carrier_order_no    VARCHAR(64)  NOT NULL COMMENT '运力方单号（唯一=账单匹配键，D08.04同城模板按此匹配）',
  order_id            BIGINT UNSIGNED NOT NULL COMMENT '订单ID（LFK→oms_order.ord_order跨域）',
  delivery_id         BIGINT UNSIGNED NOT NULL COMMENT '发货单ID（LFK→oms_order.ord_delivery跨域）',
  carrier_code        VARCHAR(32)  NOT NULL COMMENT '运力方编码（LFK→ful_carrier）',
  base_fee            DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '基础运费',
  distance_fee        DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '距离加价',
  weight_fee          DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '重量加价',
  period_fee          DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '时段加价',
  tip_fee             DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '小费',
  cancel_fee          DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '取消费（窗口外取消；责任方标记联动）',
  wait_fee            DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '等待费（骑手到店等待超时，责任=门店）',
  compensation_deduct DECIMAL(18,2) NOT NULL DEFAULT 0 COMMENT '赔付核减（订阅instant.compensation.created责任方=运力方→应付核减登记FR-05b）',
  deduct_ref          BIGINT UNSIGNED NULL COMMENT '核减依据（关联D03.15赔付台账/事件ID，审计可解释）',
  est_price           DECIMAL(18,2) NULL COMMENT '预估价（呼叫时询价）',
  actual_price        DECIMAL(18,2) NULL COMMENT '实际价（账单口径；核减后应付=Σ计费明细−赔付核减）',
  diff_rate           DECIMAL(9,4) NULL COMMENT '预估vs实际差异率（>20%运力方生成协议复核工单，校准比价价格分FR-05c）',
  settle_status       VARCHAR(16)  NOT NULL DEFAULT 'recorded' COMMENT '结算状态（D08.04三阶段）：recorded记账/audited审核/closed关账（关账后按运力方x货主x周期汇总应付供D08.03/06金蝶链路）',
  bill_period         VARCHAR(16)  NULL COMMENT '账期（yyyyMM，月度账单归集维度）',
  create_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间（送达确认或取消产生费用即落账）',
  update_time         DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间（核减/结算推进）',
  version             INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted          TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_city_freight_carrier_order (carrier_order_no),
  KEY idx_ful_city_freight_call (call_no),
  KEY idx_ful_city_freight_settle (settle_status, bill_period, carrier_code),
  KEY idx_ful_city_freight_owner (owner_id, create_time)
) ENGINE=InnoDB COMMENT='同城配送费台账（计费明细/赔付核减/预估vs实际/三阶段结算，D08.04账单体系扩展，随订单归档，P1，D09.06）';

-- ---------------------------------------------------------------------
-- V1.2-38. ful_call_decision 比价决策快照（SRS-D09.06 §6.5 decision；只增）
-- ---------------------------------------------------------------------
CREATE TABLE ful_call_decision (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  call_no         VARCHAR(32)  NOT NULL COMMENT '呼叫单号（LFK→ful_rider_call）',
  quotes_json     JSON         NOT NULL COMMENT '各家报价快照：[{carrier_code,price,eta_送达分钟,accept_rate_7d,timeout超时标记}]（询价并发2秒/家，超时按协议价目表估算）',
  scores_json     JSON         NOT NULL COMMENT '各家评分：[{carrier_code,price_score,time_score,rate_score,total_score}]（score=W_price x价格分+W_time x时效分+W_rate x接单率分，默认0.4/0.35/0.25店铺可配）',
  weights_version VARCHAR(32)  NOT NULL COMMENT '权重版本（全局默认/店铺覆写版本标识，回放依据）',
  chosen_carrier  VARCHAR(32)  NOT NULL COMMENT '选中运力方（score DESC首位，并列取接单率高者）',
  estimated_flags JSON         NULL COMMENT '估算标记集（不支持询价/超时按价目表本地估算的运力方清单，estimated=true）',
  create_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间（只增不改无update_time）',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_call_decision_call (call_no),
  KEY idx_ful_call_decision_time (create_time)
) ENGINE=InnoDB COMMENT='比价决策快照（各家报价/评分/权重版本/选优依据，对账争议与算法校准全量可回放，只增不改，P1，D09.06）';

-- ---------------------------------------------------------------------
-- V1.2-39. ful_carrier_metric 运力方滚动指标（SRS-D09.06 §6.5 metric）
-- ---------------------------------------------------------------------
CREATE TABLE ful_carrier_metric (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id          BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id           BIGINT UNSIGNED NULL COMMENT '货主ID（平台级指标=系统货主，可空）',
  carrier_code       VARCHAR(32)  NOT NULL COMMENT '运力方编码（LFK→ful_carrier）',
  city_code          VARCHAR(16)  NOT NULL COMMENT '城市编码（运力方x城市维度）',
  stat_date          DATE         NOT NULL COMMENT '统计日期（D01.02调度日批滚动刷新）',
  accept_rate_7d     DECIMAL(9,4) NOT NULL DEFAULT 0 COMMENT '近7日接单率（比价rate_score输入）',
  accept_rate_30d    DECIMAL(9,4) NOT NULL DEFAULT 0 COMMENT '近30日接单率',
  avg_accept_seconds INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '平均接单耗时秒（预呼叫延迟派发定时输入）',
  cancel_rate        DECIMAL(9,4) NOT NULL DEFAULT 0 COMMENT '取消率',
  overtime_rate      DECIMAL(9,4) NOT NULL DEFAULT 0 COMMENT '超时率（熔断阈值输入+D11.03看板排名）',
  create_time        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version            INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted         TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_carrier_metric (carrier_code, city_code, stat_date),
  KEY idx_ful_carrier_metric_date (stat_date)
) ENGINE=InnoDB COMMENT='运力方滚动指标（接单率/接单耗时/取消率/超时率，运力方x城市x日，比价决策输入+看板供数，P1，D09.06）';

-- ---------------------------------------------------------------------
-- V1.2-40. ful_shop_carrier 店铺运力绑定（SRS-D09.06 §6.5 shop_carrier）
-- ---------------------------------------------------------------------
CREATE TABLE ful_shop_carrier (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id        BIGINT UNSIGNED NOT NULL COMMENT '货主ID（冗余店铺货主）',
  shop_id         BIGINT UNSIGNED NOT NULL COMMENT '店铺（LFK→oms_gateway.gw_shop跨域）',
  carrier_code    VARCHAR(32)  NOT NULL COMMENT '运力方编码（LFK→ful_carrier；店铺可用运力集合）',
  priority        INT          NOT NULL DEFAULT 0 COMMENT '优先级（店铺级覆写，比价排序参考）',
  self_mode       VARCHAR(16)  NOT NULL DEFAULT 'fallback_only' COMMENT 'SELF参与模式：fallback_only仅兜底(默认,第三方全失败或显式选SELF时启用)/always始终参与比价（FR-06a）',
  accept_timeout  INT UNSIGNED NOT NULL DEFAULT 3 COMMENT '接单超时分钟覆写（默认3，店铺级可配，FR-02d）',
  reassign_limit  INT UNSIGNED NOT NULL DEFAULT 3 COMMENT '改派轮次上限覆写（默认3，超过发rider.call.failed交D03.15兜底决策）',
  status          VARCHAR(16)  NOT NULL DEFAULT 'enabled' COMMENT '状态：enabled启用/disabled停用',
  create_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted      TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_shop_carrier (shop_id, carrier_code),
  KEY idx_ful_shop_carrier_shop (shop_id, status)
) ENGINE=InnoDB COMMENT='店铺运力绑定（可用运力集合+优先级+接单超时/改派上限/SELF模式覆写，FR-02b/d参数源，P1，D09.06）';

-- ---------------------------------------------------------------------
-- V1.2-41. ful_store_carrier_map 运力方门店ID映射（SRS-D09.06 §6.5 store_carrier_map）
-- ---------------------------------------------------------------------
CREATE TABLE ful_store_carrier_map (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '物理主键',
  tenant_id        BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NOT NULL COMMENT '货主ID',
  store_branch_id  BIGINT UNSIGNED NOT NULL COMMENT 'OMS门店仓ID（LFK→ful_branch，branch_type=store）',
  carrier_code     VARCHAR(32)  NOT NULL COMMENT '运力方编码（LFK→ful_carrier）',
  carrier_store_id VARCHAR(64)  NOT NULL COMMENT '运力方侧商家门店ID（入驻开通时登记，FR-01b；下单报文取货点标识）',
  create_time      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '乐观锁',
  is_deleted       TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '软删标记：0否/1是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_ful_store_carrier_map (store_branch_id, carrier_code),
  KEY idx_ful_store_carrier_map_carrier (carrier_code, carrier_store_id)
) ENGINE=InnoDB COMMENT='运力方门店ID映射（OMS门店x运力方→运力方侧门店ID，入驻登记，P1，D09.06）';

-- V1.2 初始数据：内置运力方档案（FR-01a canonical 编码全集；协议/凭证运营配置）
INSERT INTO ful_carrier
  (tenant_id, owner_id, carrier_code, carrier_name, short_name, carrier_type, capability_flags, status)
VALUES
  (1, NULL, 'MEITUAN_PAOTUI', '美团跑腿',   '美团跑腿', 'platform_self',  '{"reservation":1,"update":1,"pre_query":1,"trajectory":0}', 'enabled'),
  (1, NULL, 'FENGNIAO',       '蜂鸟即配',   '蜂鸟',     'platform_self',  '{"reservation":1,"update":0,"pre_query":1,"trajectory":0}', 'enabled'),
  (1, NULL, 'DADA',           '达达快送',   '达达',     'crowdsource',    '{"reservation":0,"update":1,"pre_query":1,"trajectory":0}', 'enabled'),
  (1, NULL, 'SHANSONG',       '闪送',       '闪送',     'crowdsource',    '{"reservation":0,"update":0,"pre_query":1,"trajectory":0}', 'enabled'),
  (1, NULL, 'SF_CITY',        '顺丰同城',   '顺丰同城', 'express_city',   '{"reservation":1,"update":1,"pre_query":1,"trajectory":0}', 'enabled'),
  (1, NULL, 'SELF',           '品牌自配送', '自配送',   'brand_self',     '{"reservation":1,"update":1,"pre_query":0,"trajectory":0}', 'enabled');

-- =====================================================================
-- 完 · 41 张表（含 2 张按月分表基表模板、2 张 P1 预留表、V1.2 同城运力 9 张）
-- =====================================================================
