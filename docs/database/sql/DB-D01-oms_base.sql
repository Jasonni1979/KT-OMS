-- ============================================================================
-- DB-D01 平台底座域建表脚本（oms_base）
-- 文档编号: DB-D01 · 版本 V1.0 · 2026-10-24 · MySQL 8.0 可执行 DDL
-- 上游契约: DB-00 数据库设计总册（schema=oms_base / 表前缀 bas_ / 公共字段 /
--           不建物理外键 / 流水日志按月分表 / §7.3 migration_mapping 预留）
-- 需求依据: SRS-D01.01 ~ SRS-D01.07 §6 数据字段章节 + SRS-00 §4.4 事件字典契约
-- ----------------------------------------------------------------------------
-- 执行顺序:
--   1) CREATE DATABASE oms_base
--   2) MQ族: bas_event_dict / bas_event_outbox / bas_consume_idempotent
--      / bas_dead_letter / bas_message_trace
--   3) 调度族: bas_schedule_task / bas_schedule_log / bas_task_dependency
--   4) 规则族: bas_rule_dict / bas_rule / bas_rule_condition / bas_rule_version
--      / bas_rule_test_log / bas_plugin_registry
--   5) 元数据族: bas_entity_meta / bas_field_meta
--   6) PIPL族: bas_pipl_policy / bas_pipl_consent / bas_pipl_ds_request
--   7) 导入导出族: bas_ie_template / bas_import_task / bas_import_error / bas_export_task
--   8) 通知族: bas_notify_template / bas_notify_route / bas_notify_log / bas_alert_record
--   9) 基础: bas_seq / bas_migration_mapping
--  10) 初始字典数据 INSERT: 事件字典12条 / 调度白名单14条 / DAG首批 / PIPL分级+脱敏+留存 /
--      插件策略样例 / 规则字典样例 / 发号域码 / 通知模板路由样例
-- 依赖: 仅本 schema；跨域为逻辑外键 LFK（应用层校验），不建物理外键
-- 分表约定: bas_message_trace / bas_schedule_log / bas_notify_log 按月分表 _YYYYMM，
--           本脚本为结构基线表，月度表由调度任务 CREATE TABLE ... LIKE 创建
-- 保留字规避: 不用 groups/rank/system/condition/read（MySQL8 保留字，D03 域曾遇 groups 问题）
-- 命名/类型基线: 见 DB-00 §2/§6；utf8mb4 / utf8mb4_0900_ai_ci / InnoDB
-- ============================================================================

CREATE DATABASE IF NOT EXISTS oms_base DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE oms_base;

-- ============================================================================
-- 一、MQ 与异步任务（D01.01）
-- ============================================================================

-- 2. 领域事件字典（D01.01/SRS-00 §4.4 · P0，字典表 owner_id 免填）
CREATE TABLE bas_event_dict (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID(全局字典=1)',
  event_name          VARCHAR(64)     NOT NULL COMMENT '事件名,全局唯一(域.实体.动作小写点分,SRS-00 §4.2命名契约;登记后方可发布,CI校验防拼写漂移)',
  event_desc          VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '事件说明',
  domain_code         VARCHAR(16)     NOT NULL COMMENT '发布域:D01~D11(交换机oms.{域}.events路由)',
  publisher_module    VARCHAR(32)     NOT NULL COMMENT '发布方模块(D03.07等)',
  subscribers_json    JSON            NOT NULL COMMENT '订阅方清单[{"module":"D08.01","queue":"q.finance.order_completed"}](一订阅方一队列,topic广播互不影响)',
  payload_schema_json JSON            NULL DEFAULT NULL COMMENT 'payload结构定义(JSON Schema;瘦事件原则:只带ID与关键状态,<=64KB超限走OSS引用)',
  reliability         VARCHAR(16)     NOT NULL DEFAULT 'reliable' COMMENT '可靠性等级:reliable=强制outbox(驱动业务状态联动,publishDirect被CI拦截),best-effort=可直发(通知/埋点类)',
  partitioned         TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '分区保序:0=否,1=是(分区数默认8高频域16;扩分区=新建队列组灰度切流,不支持在线改N)',
  partition_key_field VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '分区键字段(order_group_key/shop_id/triple_hash/delivery_id)',
  blocking_flag       TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '分区内失败阻塞:1=阻塞后续(强保序默认,head-of-line),0=旁路重试(放弃跨消息顺序,登记时显式选择)',
  sla_minutes         INT             NOT NULL DEFAULT 5 COMMENT '消费延迟SLA分钟(occurred_at->消费完成P95;超限告警D01.07,如stock.change.logged<=5分钟=D04.02对账窗口)',
  status              TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=废弃(下线事件禁发布)',
  create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted          TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_event_dict_name (event_name),
  KEY idx_bas_event_dict_domain (domain_code, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='领域事件字典(D01.01,P0,SRS-00事件登记表持久化载体)';

-- 1. 事务性发件箱（D01.01 · P0）★outbox模式防丢事件（流水类扩展:状态可更新只增不删,无is_deleted）
CREATE TABLE bas_event_outbox (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  event_id        VARCHAR(26)     NOT NULL COMMENT '消息唯一ID(ULID,时间有序;轨迹查询主键)',
  event_name      VARCHAR(64)     NOT NULL COMMENT '事件名=路由键(域.实体.动作;须在bas_event_dict登记) LFK->bas_event_dict',
  reliability     VARCHAR(16)     NOT NULL DEFAULT 'reliable' COMMENT '可靠性等级:reliable=强制outbox,best-effort=可直发(broker故障时direct路径降级也写本表兜底补投)',
  idempotent_key  VARCHAR(128)    NOT NULL COMMENT '业务幂等键(发布方定义:order_id+动作/bill_type+bill_item_id+action,同事件名内唯一)',
  aggregate_type  VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '聚合类型(ord_order/inv_io_bill等,轨迹与排障定位)',
  aggregate_id    VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '聚合ID(业务主键/单号,业务单号轨迹检索用)',
  owner_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(SRS-00契约,事件携带消费方免回查)',
  trace_id        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '全链路追踪ID(HTTP/调度/上游消息继承透传)',
  partition_key   VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '分区键(partitioned事件必填;hash(partition_key) mod N路由固定分区)',
  payload         JSON            NOT NULL COMMENT '业务数据(瘦事件原则;<=64KB;禁敏感明文D01.05:只放加密引用或脱敏值)',
  schema_version  VARCHAR(16)     NOT NULL DEFAULT 'v1' COMMENT 'payload结构版本(消费方兼容解析依据)',
  delay_seconds   INT             NOT NULL DEFAULT 0 COMMENT '延迟秒数(>0为延迟消息:RabbitMQ延迟插件为主TTL+DLX兜底,上限7天超期改用调度扫描;如delivery.timeout.accept=900)',
  status          TINYINT         NOT NULL DEFAULT 0 COMMENT '投递状态:0=待投递,1=已投递(publisher confirm确认),2=投递失败(超20次告警人工)',
  retry_count     INT             NOT NULL DEFAULT 0 COMMENT '投递重试次数(指数退避1s/5s/30s/2min/10min封顶30min)',
  next_retry_time DATETIME(3)     NULL DEFAULT NULL COMMENT '下次重试时间(投递器扫描条件;多实例SELECT FOR UPDATE SKIP LOCKED分片认领)',
  publish_time    DATETIME(3)     NULL DEFAULT NULL COMMENT '投递成功时间(事务提交->broker可见P95<=1s;已投递保留7天后归档删除)',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '写入时间(业务同事务)',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version         INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(投递状态CAS)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_event_outbox_event (event_id),
  KEY idx_bas_event_outbox_pending (status, next_retry_time, id),
  KEY idx_bas_event_outbox_idem (event_name, idempotent_key),
  KEY idx_bas_event_outbox_agg (aggregate_type, aggregate_id),
  KEY idx_bas_event_outbox_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='事务性发件箱(D01.01,P0,业务变更+事件写入同一本地事务防丢,凯淳新增商派无)';

-- 3. 消费幂等台账（D01.01 · P0，辅助表，流水类无软删无version，30天滚动清理）
CREATE TABLE bas_consume_idempotent (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  queue_name     VARCHAR(128)    NOT NULL COMMENT '消费队列名(q.{消费域}.{用途})',
  idempotent_key VARCHAR(128)    NOT NULL COMMENT '业务幂等键(信封携带)',
  status         TINYINT         NOT NULL DEFAULT 1 COMMENT '台账状态:1=PROCESSING(在途,重复到达延迟重投防并发双跑),2=SUCCESS(已成功,直接ack跳过)',
  event_id       VARCHAR(26)     NOT NULL DEFAULT '' COMMENT '首次成功消费消息ID(溯源)',
  consumer_name  VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '消费方名称',
  consume_time   DATETIME(3)     NULL DEFAULT NULL COMMENT '消费成功时间',
  cost_ms        INT             NOT NULL DEFAULT 0 COMMENT '处理耗时毫秒',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间(30天滚动清理键;Redis SETNX快路径+本表DB兜底,Redis丢失以DB为准)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_consume_idempotent (queue_name, idempotent_key),
  KEY idx_bas_consume_idempotent_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='消费幂等台账(D01.01,P0,辅助;at-least-once+幂等台账=业务exactly-once,业务级幂等责任仍在消费方)';

-- 4. 死信（D01.01 · P0，单据类扩展无软删）← 商派 taskmgr 失败告警改造
CREATE TABLE bas_dead_letter (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  dead_bn            VARCHAR(32)     NOT NULL COMMENT '死信编号,唯一(DL+日期+序列,bas_seq发号)',
  source_queue       VARCHAR(128)    NOT NULL COMMENT '来源队列名(dlq.{queue}投递后落库)',
  consumer_name      VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '消费方名称',
  event_id           VARCHAR(26)     NOT NULL DEFAULT '' COMMENT '消息ID(轨迹互查)',
  event_name         VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '事件名(聚类维度)',
  idempotent_key     VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '业务幂等键',
  envelope           JSON            NOT NULL COMMENT '信封全文(FR-02a契约结构;敏感字段已脱敏形态)',
  fail_reason        VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '最后一次失败原因',
  exception_digest   VARCHAR(1024)   NOT NULL DEFAULT '' COMMENT '异常堆栈摘要(脱敏,D01.05出口过滤;禁裸堆栈)',
  error_fingerprint  CHAR(64)        NOT NULL DEFAULT '' COMMENT '错误指纹=hash(异常类+首行)(聚类摘要TOP统计:队列x错误指纹计数,即时告警D01.07)',
  retry_count        INT             NOT NULL DEFAULT 0 COMMENT '累计重试次数(达retry声明上限进死信)',
  dead_time          DATETIME(3)     NOT NULL COMMENT '死信时间(积压>24h未处理升级告警P0)',
  handle_status      TINYINT         NOT NULL DEFAULT 0 COMMENT '处理状态:0=未处理,1=已重放(重投原队列走原链路,幂等台账防重复生效),2=已作废(无效消息),3=已修复关闭',
  handle_op          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '处理人(重放/作废为高危权限点,写审计D10.06)',
  handle_time        DATETIME(3)     NULL DEFAULT NULL COMMENT '处理时间',
  handle_remark      VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '处理说明',
  trace_id           VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '全链路追踪ID',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version            INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(批量重放CAS)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_dead_letter_bn (dead_bn),
  KEY idx_bas_dead_letter_status (handle_status, dead_time),
  KEY idx_bas_dead_letter_queue (source_queue, event_name, error_fingerprint),
  KEY idx_bas_dead_letter_event (event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='死信(D01.01,P0,死信工作台+聚类告警+审计重放)';

-- 5. 消息轨迹（D01.01 · P0，辅助表，按月分表 _YYYYMM 结构基线，流水类）
CREATE TABLE bas_message_trace (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id     BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  event_id      VARCHAR(26)     NOT NULL COMMENT '消息ID(检索键双索引)',
  trace_id      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '全链路追踪ID(跨事件级联视图:发货确认->shipped->回传任务->回传完成)',
  stage         VARCHAR(32)     NOT NULL COMMENT '环节:outbox_write=outbox写入,dispatch=投递,confirm=broker确认,consume_start=消费开始,consume_success=消费成功,consume_fail=消费失败,retry=重试,dead=死信,replay=重放',
  node_id       VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '实例标识(pod/进程,哪个订阅方拖垮链路快速定位)',
  queue_name    VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '归属队列',
  consumer_name VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '消费方名称',
  cost_ms       INT             NOT NULL DEFAULT 0 COMMENT '环节耗时毫秒',
  detail        VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '摘要(无敏感明文;失败原因/重试次数/confirm结果)',
  create_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '轨迹时间',
  PRIMARY KEY (id),
  KEY idx_bas_message_trace_event (event_id, create_time),
  KEY idx_bas_message_trace_trace (trace_id),
  KEY idx_bas_message_trace_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='消息轨迹(D01.01,P0,辅助,按月分表_YYYYMM,在线3个月)';
-- 月表示例（调度器滚动创建）：CREATE TABLE bas_message_trace_202611 LIKE bas_message_trace;

-- ============================================================================
-- 二、统一调度器（D01.02）
-- ============================================================================

-- 6. 调度任务白名单（D01.02 · P0，配置表 owner_id 免填）← 商派 taskmgr whitelist 改造
CREATE TABLE bas_schedule_task (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  task_name           VARCHAR(64)     NOT NULL COMMENT '任务名,全局唯一({域}.{任务},如stock.reconcile_sample/gateway.pull_orders;未注册任务名手动触发被拒)',
  task_desc           VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '任务说明',
  domain_code         VARCHAR(16)     NOT NULL COMMENT '归属域:D01~D11(治理与告警寻址)',
  owner_name          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '任务Owner负责人(治理必填)',
  schedule_type       VARCHAR(16)     NOT NULL DEFAULT 'cron' COMMENT '调度模式:cron=5位表达式(时区Asia/Shanghai,支持多表达式),fixed_rate=固定频率(>=10s,首轮对齐整点可配偏移),once=一次性(执行后置完成可复制重建),dag=依赖触发(bas_task_dependency)',
  expression          VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '调度表达式(cron串或频率秒数;多表达式逗号分隔;once=ISO时间)',
  thread_num          INT             NOT NULL DEFAULT 1 COMMENT '并发实例数:1=串行(skip_if_running重叠跳过本轮,连续>=3轮告警=任务跑不动信号),N=分片并行(分片号注入handler,店铺集合不重叠不遗漏)',
  shard_count         INT             NOT NULL DEFAULT 1 COMMENT '分片数(各分片独立锁sched:lock:{task}:{plan_time}:shard{i},分片间并行分片内互斥,分配稳定)',
  timeout_sec         INT             NOT NULL DEFAULT 30 COMMENT '单次执行超时秒(超时终止记失败不阻塞下一轮;直跑协程级取消/委托发终止信号+worker侧timeout双保险)',
  retry_times         INT             NOT NULL DEFAULT 0 COMMENT '失败自动重试次数(默认0;重试仍失败才告警)',
  retry_interval_sec  INT             NOT NULL DEFAULT 60 COMMENT '重试间隔秒',
  rule_json           JSON            NULL DEFAULT NULL COMMENT '启停规则{enabled,window:"02:00-05:00",mutex_group,misfire:"skip|fire_once",skip_if_running}(归档仅凌晨窗口,窗口外手动触发被拒;misfire:高频=skip日结=fire_once补一次携带原plan_date)',
  alarm_json          JSON            NULL DEFAULT NULL COMMENT '告警策略{level:"P0|P1|P2",continuous_fail_threshold:3,receivers}(缺省按域值班表D01.07路由;失败/超时/连续失败/DAG阻断/窗口未完成触发)',
  exec_mode           VARCHAR(8)      NOT NULL DEFAULT 'inline' COMMENT '运行方式:inline=调度进程内协程直跑(<10s轻任务),mq=委托D01.01任务通道worker池运行(重活;触发!=完成,完成态以handler回报为准)',
  param_schema_json   JSON            NULL DEFAULT NULL COMMENT '补跑参数schema(plan_time/period/店铺范围等,表单化输入依据,按schema校验防注入)',
  promo_preset_json   JSON            NULL DEFAULT NULL COMMENT '大促模式预设参数组(拉单30秒/对账加密/归档暂停/非核心统计停跑;模式切换热更<=10s全实例感知+事件通知各域Owner)',
  task_config_version INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '配置版本(热更与审计依据,变更写D10.06)',
  status              TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=停用',
  create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version             INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted          TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_schedule_task_name (task_name),
  KEY idx_bas_schedule_task_domain (domain_code, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='调度任务白名单(D01.02,P0,商派taskmgr四要素threadNum/timeout/retry/rule继承并扩展)';

-- 7. 调度执行日志（D01.02 · P0，按月分表 _YYYYMM 结构基线，流水类）
CREATE TABLE bas_schedule_log (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  exec_id           VARCHAR(32)     NOT NULL COMMENT '执行标识,唯一(SE+日期+序列)',
  task_name         VARCHAR(64)     NOT NULL COMMENT '任务名 LFK->bas_schedule_task',
  plan_time         DATETIME(3)     NOT NULL COMMENT '计划时间(补跑=业务时间参数;分布式锁键成分sched:lock:{task}:{plan_time},任一任务任一计划点恰好触发一次)',
  trigger_type      VARCHAR(16)     NOT NULL DEFAULT 'auto' COMMENT '触发方式:auto=自动,manual=手动(高危任务二次确认+权限点+审计D10.06),dag=依赖触发,retry=自动重试,backfill=批量补跑(按日序列前日失败即停)',
  instance_id       VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '执行实例(pod标识;锁值含实例ID可观测谁在执行)',
  shard_index       INT             NOT NULL DEFAULT 0 COMMENT '分片号(0=非分片)',
  start_time        DATETIME(3)     NULL DEFAULT NULL COMMENT '开始时间',
  end_time          DATETIME(3)     NULL DEFAULT NULL COMMENT '结束时间',
  cost_ms           INT             NOT NULL DEFAULT 0 COMMENT '耗时毫秒(统计视图P50/P95/max由D11报表任务日聚合)',
  result            VARCHAR(24)     NOT NULL COMMENT '结果:success=成功,failed=失败,timeout=超时,skipped_overlapping=重叠跳过,skipped_window=窗口外跳过,cancelled=取消',
  error_digest      VARCHAR(1024)   NOT NULL DEFAULT '' COMMENT '错误摘要(脱敏)',
  biz_summary_json  JSON            NULL DEFAULT NULL COMMENT '业务摘要(如{"scanned":1200,"fixed_diff":3})',
  operator          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '手动触发人(trigger_type=manual/backfill必填)',
  related_exec_id   VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '关联原失败记录(补跑溯源)',
  sampled           TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '抽样标记:0=全量(失败/手动),1=成功抽样(高频任务失败全量+成功1/10降级,防日志爆量)',
  trace_id          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '全链路追踪ID(贯穿D01.01消息与业务日志)',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_schedule_log_exec (exec_id),
  KEY idx_bas_schedule_log_task (task_name, plan_time),
  KEY idx_bas_schedule_log_result (result, create_time),
  KEY idx_bas_schedule_log_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='调度执行日志(D01.02,P0,按月分表_YYYYMM,在线90天)';
-- 月表示例（调度器滚动创建）：CREATE TABLE bas_schedule_log_202611 LIKE bas_schedule_log;

-- 8. 任务DAG依赖（D01.02 · P0，配置表）
CREATE TABLE bas_task_dependency (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  task_name       VARCHAR(64)     NOT NULL COMMENT '下游任务名 LFK->bas_schedule_task',
  after_task_name VARCHAR(64)     NOT NULL COMMENT '上游任务名 LFK->bas_schedule_task(多上游=多行AND语义:全部成功才触发;注册期拓扑校验成环拒绝)',
  plan_date_align TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '业务日期对齐:0=否,1=是(同plan_date维度,上游今日成功->下游携带同plan_date触发;上游失败->下游blocked+连带告警)',
  auto_trigger    TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '上游补跑成功后下游:0=手动补触发,1=自动补触发',
  status          TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=停用',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_task_dependency (task_name, after_task_name),
  KEY idx_bas_task_dependency_after (after_task_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='任务DAG依赖(D01.02,P0,简单DAG无环,不做复杂工作流引擎)';

-- ============================================================================
-- 三、规则引擎框架（D01.03）
-- ============================================================================

-- 14. 规则维度/枚举字典（D01.03 · P0，辅助字典表 owner_id 免填）
CREATE TABLE bas_rule_dict (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id       BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID(租户级可扩展,系统预置项不可删)',
  dict_category   VARCHAR(16)     NOT NULL DEFAULT 'enum' COMMENT '字典类别:dim=维度字典(每个rule_group注册可用维度,条件保存期校验+可视化构建器数据契约同源),enum=枚举字典(原因码/决策码统一登记,后台增项不发版即生效)',
  dict_type       VARCHAR(64)     NOT NULL COMMENT '字典类型(dim用=rule_group如order.audit;enum用=audit_reason_code/aftersale_reason_code/decision_code/suggest_action等)',
  item_code       VARCHAR(64)     NOT NULL COMMENT '项编码(dim=维度键如order.amount_paid/shop_id;enum=原因码如BLACKLIST_HIT)',
  item_name       VARCHAR(128)    NOT NULL COMMENT '项名称/中文标签',
  value_type      VARCHAR(16)     NOT NULL DEFAULT 'string' COMMENT '值类型(dim用:string/int/decimal/bool/enum/ref/time;决定操作符候选集)',
  ops_allowed_json JSON           NULL DEFAULT NULL COMMENT '允许操作符子集(dim用;空=按value_type默认全集:eq/neq/gt/gte/lt/lte/between/in/not_in/any_in/all_in/contains/starts_with/regex/is_true/is_false/is_null/not_null/in_window/before/after)',
  value_source    VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '取值来源(dim用:enum:{dict_type}=枚举字典引用/ref:{entity}=档案服务URL/free=自由输入)',
  level           VARCHAR(16)     NOT NULL DEFAULT '' COMMENT '级别(enum用:BLOCK=阻断/WARN=提示)',
  ext_json        JSON            NULL DEFAULT NULL COMMENT '扩展属性(enum用:原因码绑定默认路由与审核组建议{"default_route":"manual","audit_group":"risk"})',
  preset_flag     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '系统预置:0=租户扩展,1=预置(不可删)',
  sort_no         INT             NOT NULL DEFAULT 0 COMMENT '排序',
  status          TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=停用(插件产出未登记code运行期校验拦截留痕;变更审计+缓存失效广播)',
  create_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_rule_dict (dict_category, dict_type, item_code, tenant_id),
  KEY idx_bas_rule_dict_type (dict_category, dict_type, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='规则维度/枚举字典(D01.03,P0,辅助;维度字典+原因码/决策码统一登记)';

-- 9. 规则主表（D01.03 · P0）← 商派 omeauto_order_type 改造
CREATE TABLE bas_rule (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  rule_name          VARCHAR(128)    NOT NULL COMMENT '规则名称(rule_group内唯一)',
  rule_group         VARCHAR(64)     NOT NULL COMMENT '规则集:order.audit=审单(18维),aftersale.audit=售后审核(12维),logistics.route=物流分单,branch.route=配货仓序,audit.dispatch=人工分派(五个消费方共用同一模型;动作schema按组注册校验)',
  weight             INT             NOT NULL DEFAULT 0 COMMENT '优先级(DESC排序首个全命中生效;同weight按id ASC稳定命中;无命中返回缺省兜底规则)',
  scope_json         JSON            NULL DEFAULT NULL COMMENT '生效范围{"scope_type":"global|tenant|owner|shop_set","owner_ids":[],"shop_ids":[]}(SRS-00货主维度契约)',
  effective_window   VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '生效时段(如09:00-21:00;空=不限)',
  exclude_window     VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '排除时段(大促停自动审单D03.02 SC-07)',
  gray_ratio         TINYINT         NOT NULL DEFAULT 0 COMMENT '灰度比例%(0=不灰度;分流=hash(分流键)%100<ratio稳定分流,同键同路径;灰度期新旧版本并行,指标对比)',
  gray_key_field     VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '灰度分流键(order_id/apply_id尾号hash,rule_group声明)',
  actions_json       JSON            NULL DEFAULT NULL COMMENT '动作配置(结构由rule_group注册schema校验:审单=autoConfirm+插件参数+路由表;拆单=策略链+config;物流=优先级序列;当前生效版本快照在bas_rule_version)',
  current_version_id BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '生效版本指针 LFK->bas_rule_version(同规则同时只有一个生效版+至多一个灰度中版)',
  gray_version_id    BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '灰度版本指针 LFK->bas_rule_version',
  defaulted          TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '系统缺省规则:0=否,1=是(兜底不可删/不可停/不可改动作;缺省兜底命中率过高=规则覆盖不足信号)',
  status             TINYINT         NOT NULL DEFAULT 1 COMMENT '启停:1=启用,2=停用(停用即缓存失效广播rule.config.changed,全worker<=5s重载)',
  remark             VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '备注',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version            INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(缓存版本核对)',
  is_deleted         TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是(缺省规则不可删)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_rule_group_name (rule_group, rule_name, tenant_id),
  KEY idx_bas_rule_group (rule_group, status, weight),
  KEY idx_bas_rule_version (current_version_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='规则主表(D01.03,P0,通用条件->动作实体,五消费方共用)';

-- 10. 规则条件明细DSL（D01.03 · P0）
CREATE TABLE bas_rule_condition (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id            BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  rule_id              BIGINT UNSIGNED NOT NULL COMMENT '规则 LFK->bas_rule',
  condition_version_id BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '所属版本 LFK->bas_rule_version(0=当前编辑草稿态;版本固化后行随版本只读;快照回放走version.content_json)',
  dim_key              VARCHAR(64)     NOT NULL COMMENT '维度键(如order.amount_paid/shop_id/order.items.category;rule_group维度字典注册,保存期校验合法/类型匹配/值域有效)',
  op_code              VARCHAR(16)     NOT NULL COMMENT '操作符:eq/neq/gt/gte/lt/lte/between/in/not_in/any_in(明细行任一命中)/all_in/contains/starts_with/regex(保存期复杂度校验+执行超时防ReDoS)/is_true/is_false/is_null/not_null/in_window/before/after',
  value_json           JSON            NOT NULL COMMENT '条件值(标量/数组/区间{"from":x,"to":y};类型与维度字典value_type匹配校验)',
  sort_no              INT             NOT NULL DEFAULT 0 COMMENT '条件项顺序(两层模型:items全AND同维度多值OR;短路求值首项不命中即止;明确不做跨维度运算与嵌套多层逻辑)',
  create_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  KEY idx_bas_rule_condition_rule (rule_id, condition_version_id, sort_no),
  KEY idx_bas_rule_condition_dim (dim_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='规则条件明细DSL(D01.03,P0,结构化可解释,求值纯内存单规则20项<=1ms)';

-- 11. 规则版本/快照/灰度（D01.03 · P0）版本链只追加
CREATE TABLE bas_rule_version (
  id                    BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键(=snapshot_id,决策留痕引用:D03.02 plan.rule_snapshot_id/D05.05 decision数据源)',
  tenant_id             BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  rule_id               BIGINT UNSIGNED NOT NULL COMMENT '规则 LFK->bas_rule',
  rule_version_no       INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '版本号(递增,版本链只追加不改)',
  content_json          JSON            NOT NULL COMMENT '规则全量固化快照{conditions,actions,scope,windows,gray,dim_value_refs}(不可变;回放一致性根基:replay(snapshot_id,历史上下文)与当时决策一致)',
  content_hash          CHAR(64)        NOT NULL DEFAULT '' COMMENT '内容哈希(快照不可变校验:直接改库被版本校验检出)',
  status                TINYINT         NOT NULL DEFAULT 1 COMMENT '版本状态:1=草稿(可沙箱,Agent草案仅落此态无旁路生效),2=待发布,3=灰度中,4=已生效(唯一),5=已废弃,6=已回滚',
  publish_type          VARCHAR(16)     NOT NULL DEFAULT '' COMMENT '发布方式:full=全量,gray=灰度,rollback=回滚(新建版本指向历史快照)',
  gray_ratio            TINYINT         NOT NULL DEFAULT 0 COMMENT '灰度比例%快照',
  rollback_from_version INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '回滚来源版本号(publish_type=rollback时记录)',
  agent_draft           TINYINT(1)      NOT NULL DEFAULT 0 COMMENT 'Agent草案:0=人工,1=K-AIDE生成(D02.07;必须附沙箱报告才允许提交人工评审,硬约束)',
  sandbox_run_id        BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '关联沙箱试跑记录 LFK->bas_rule_test_log(发布评审引用;未做沙箱验证灰度前软约束提示)',
  publish_op            VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '发布人(灰度/回滚为高危权限点+审计D10.06)',
  publish_time          DATETIME(3)     NULL DEFAULT NULL COMMENT '发布时间',
  note                  VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '变更原因备注(必填,审计要素)',
  create_time           DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time           DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_rule_version (rule_id, rule_version_no),
  KEY idx_bas_rule_version_status (rule_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='规则版本快照灰度(D01.03,P0,快照不可变,版本化/灰度/回滚,商派无版本误配置=生产事故)';

-- 12. 沙箱试跑记录（D01.03 · P0）
CREATE TABLE bas_rule_test_log (
  id                  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id           BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  run_bn              VARCHAR(32)     NOT NULL COMMENT '试跑编号,唯一(SB+日期+序列)',
  rule_group          VARCHAR(64)     NOT NULL COMMENT '规则集 LFK->bas_rule.rule_group',
  rule_id             BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '规则(0=整组试跑)',
  rule_version_id     BIGINT UNSIGNED NOT NULL COMMENT '试跑版本 LFK->bas_rule_version(草稿/灰度/任意历史版)',
  compare_version_id  BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '对比基准版本(0=当前生效版;对比模式=决策变化清单数据源)',
  sample_source       VARCHAR(16)     NOT NULL DEFAULT 'manual' COMMENT '样本来源:biz_no=指定业务单号,filter=按条件圈选历史数据(店铺+时间段,上限默认5000),manual=手工构造(表单造数边界场景)',
  sample_ref_json     JSON            NULL DEFAULT NULL COMMENT '样本引用(单号集/圈选条件;装载器SampleLoader按rule_group注册,外部依赖以快照数据替代)',
  sample_count        INT             NOT NULL DEFAULT 0 COMMENT '样本量',
  run_mode            TINYINT         NOT NULL DEFAULT 1 COMMENT '模式:1=单跑,2=对比(vs基准版:决策变化清单/命中率diff/异常清单)',
  exec_mode           TINYINT         NOT NULL DEFAULT 1 COMMENT '执行方式:1=同步(单样本,配置界面即时反馈P95<=2s),2=异步(批量,D01.01任务通道资源隔离)',
  change_summary_json JSON            NULL DEFAULT NULL COMMENT '变化摘要{"decision_changed":37,"hit_rate_diff":-0.02,"exception_count":0,"side_effect_violations":0}(副作用尝试数=dry-run四层代理拦截DB/Redis/MQ/HTTP的违例证据)',
  report_ref          VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '报告存储引用(OSS:逐样本决策+逐项求值明细+插件trace)',
  run_status          TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=运行中,2=完成,3=失败',
  operator            VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '发起人(发布评审引用依据)',
  create_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time         DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_rule_test_log_bn (run_bn),
  KEY idx_bas_rule_test_log_version (rule_version_id),
  KEY idx_bas_rule_test_log_group (rule_group, create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='沙箱试跑记录(D01.03,P0,dry-run零副作用铁律,商派无试算能力)';

-- 13. 插件/策略注册表（D01.03 · P0，配置表）← 商派硬编码插件链+lib/split注册表改造
CREATE TABLE bas_plugin_registry (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  registry_type      VARCHAR(16)     NOT NULL DEFAULT 'plugin' COMMENT '注册类型:plugin=插件链(审单五段19插件/售后七插件),strategy=策略注册表(拆单16策略族)',
  chain_id           VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '链归属(plugin用:order.audit/aftersale.audit;chain_id隔离不同消费方的链;strategy为空)',
  registry_id        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '策略族(strategy用:split=拆单;后续可扩展赠品/分仓策略族)',
  item_name          VARCHAR(64)     NOT NULL COMMENT '插件名/策略类型码(chain或registry内唯一,如blacklist_check/owner_split)',
  item_desc          VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '说明(describe元信息)',
  phase              VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '阶段标识(plugin用:ADMIT/WAREHOUSE/STOCK/LOGISTICS/CHECK五段,RISK=风控段;段间依赖固定不可调,段内可插拔)',
  phase_order        INT             NOT NULL DEFAULT 0 COMMENT '段内顺序(编排排序键)',
  short_circuit      TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '段级短路策略:0=不短路全收集(CHECK段),1=短路终止(配置而非代码)',
  error_policy       VARCHAR(16)     NOT NULL DEFAULT 'strict' COMMENT '异常策略:strict=异常整链HOLD转人工(售后唯一模式),dual=严格+宽松可逐插件配(审单FR-01f);异常必留痕入reasons',
  timeout_ms         INT             NOT NULL DEFAULT 500 COMMENT '单插件超时毫秒(超时按异常策略处理)',
  config_schema_json JSON            NULL DEFAULT NULL COMMENT '配置schema(strategy=describe().config_schema托管:动态表单渲染+validateConfig保存期校验;schema变更需升版本,向后兼容校验:新版必须能解析旧版配置)',
  class_ref          VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '实现类引用(DI定位;新增插件/策略=实现接口+DI注册,零引擎代码改动)',
  item_version       VARCHAR(16)     NOT NULL DEFAULT 'v1' COMMENT '插件/策略版本(升版->规则引用记录版本,历史决策按当时快照回放)',
  enabled            TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '启停:0=停用(引用规则保存报错+执行返回STRATEGY_DISABLED),1=启用(全局默认,规则actions.plugin_config可覆盖)',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted         TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_plugin_registry (chain_id, registry_id, item_name),
  KEY idx_bas_plugin_registry_chain (chain_id, phase, phase_order),
  KEY idx_bas_plugin_registry_type (registry_type, enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='插件/策略注册表(D01.03,P0,DI标签注册DB镜像,启动同步一致性校验)';

-- ============================================================================
-- 四、元数据驱动 CRUD（D01.04）
-- ============================================================================

-- 15. 实体元数据（D01.04 · P0，配置表 owner_id 免填）
CREATE TABLE bas_entity_meta (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  entity_name      VARCHAR(64)     NOT NULL COMMENT '实体名,全局唯一(如inv_brand)',
  entity_label     VARCHAR(128)    NOT NULL COMMENT '中文标签(品牌档案)',
  domain_code      VARCHAR(16)     NOT NULL COMMENT '归属域:D01~D11',
  schema_name      VARCHAR(64)     NOT NULL COMMENT '所属schema(oms_stock等)',
  table_name       VARCHAR(64)     NOT NULL COMMENT '物理表名(启动期一致性校验:注解与物理表不一致fail-fast报错定位实体与字段;元数据不生成DDL,建表权归DB-Dxx数据字典与迁移文件)',
  row_scope_json   JSON            NULL DEFAULT NULL COMMENT '行级过滤维度["tenant_id","owner_id"](D10.03中间件注入依据;与org_filterable_entity双向一致校验)',
  soft_delete      TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '软删开关:0=否(流水/单据类),1=是',
  recycle_bin      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '回收站开关(回收站视图独立权限点)',
  perm_prefix      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '权限点前缀(自动生成{prefix}.list/.create/.update/.delete/.export+敏感字段明文点{prefix}.field.{f}.plain推送D10.03,同源防漏:杜绝有页面无权限点)',
  actions_json     JSON            NULL DEFAULT NULL COMMENT '自定义动作声明[{code,name,perm_code,param_schema,confirm_tip,danger_level,handler_ref}](DI标签EntityAction路由到消费方服务方法,业务编排留在各域)',
  list_config_json JSON            NULL DEFAULT NULL COMMENT '列表契约(列顺序/宽度/可排序/渲染修饰:enum_label枚举转中文/ref_name档案转名称/mask脱敏/format格式化;默认筛选器集;批量与行操作;商派dbeav modifier思想新栈化)',
  form_config_json JSON            NULL DEFAULT NULL COMMENT '表单契约(字段分组tab/分节;控件类型:输入/下拉/多选/日期/开关/档案选择器;联动显隐规则;编辑态差异:新建可填编辑只读)',
  default_sort     VARCHAR(64)     NOT NULL DEFAULT '-create_time' COMMENT '默认排序',
  meta_version     INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '元数据版本(前端契约响应携带=缓存失效依据304协商;变更分级:兼容自动通过/受限影响报告/破坏性CI阻断强制三步流程)',
  content_hash     CHAR(64)        NOT NULL DEFAULT '' COMMENT '内容哈希(版本协商)',
  code_version     VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '代码版本(发布追踪)',
  crud_enabled     TINYINT(1)      NOT NULL DEFAULT 1 COMMENT '通用CRUD:0=定制页面仅局部复用元数据(审单工作台/核销工作台/打印批次等FR-07b清单),1=走通用骨架(覆盖60%配置类/档案类页面)',
  status           TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=停用',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted       TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_entity_meta (entity_name),
  KEY idx_bas_entity_meta_domain (domain_code, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='实体元数据(D01.04,P0,注册中心DB镜像,前端schema契约数据源)';

-- 16. 字段元数据（D01.04 · P0，配置表）
CREATE TABLE bas_field_meta (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  entity_name       VARCHAR(64)     NOT NULL COMMENT '所属实体 LFK->bas_entity_meta',
  field_name        VARCHAR(64)     NOT NULL COMMENT '字段名(与物理表一致性启动校验)',
  field_label       VARCHAR(128)    NOT NULL COMMENT '中文标签(列表表头/表单label/导入模板表头/打印模板字段树同源)',
  value_type        VARCHAR(16)     NOT NULL DEFAULT 'string' COMMENT '值类型:string/int/decimal/datetime/date/bool/enum/json/ref(档案引用)',
  required_flag     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '必填:0=否,1=是(服务端校验为安全底线,前端校验只是体验层)',
  length_max        INT             NOT NULL DEFAULT 0 COMMENT '长度上限(0=不限)',
  range_min         DECIMAL(18,4)   NULL DEFAULT NULL COMMENT '数值范围下限',
  range_max         DECIMAL(18,4)   NULL DEFAULT NULL COMMENT '数值范围上限',
  default_val       VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '默认值',
  enum_dict_type    VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '枚举字典引用(bas_rule_dict.dict_type;禁实体私定义枚举,启动期校验拒绝:全系统一套枚举多处消费)',
  ref_entity        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '档案引用目标实体(value_type=ref用:owner_id->org_owner)',
  ref_display_field VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '档案引用显示字段(owner_name;列表修饰批量预取防N+1)',
  ref_filter_json   JSON            NULL DEFAULT NULL COMMENT '档案引用过滤条件(选择器数据源收窄;停用档案引用提示)',
  sensitive_level   VARCHAR(8)      NOT NULL DEFAULT 'L0' COMMENT '敏感级别:L0=公开,L1=内部,L2=敏感(加密+默认脱敏),L3=高敏(全脱敏);与bas_pipl_policy字段登记双向一致校验,不一致启动报错;列表/表单/导出/详情四处行为一致',
  readonly_scene    VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '只读场景:空=可编辑,create_only=建档后不可改(如owner_id),edit=编辑态只读',
  unique_flag       TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '唯一约束声明:0=否,1=是(保存期唯一性校验,409冲突结构化返回)',
  sort_no           INT             NOT NULL DEFAULT 0 COMMENT '字段顺序',
  status            TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=废弃(破坏性变更三步流程:新增替代字段->数据迁移->废弃标记,下个大版本物理清理)',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_field_meta (entity_name, field_name),
  KEY idx_bas_field_meta_dict (enum_dict_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='字段元数据(D01.04,P0,校验/枚举/档案引用/敏感级别声明,导入模板列同源生成)';

-- ============================================================================
-- 五、PIPL 隐私合规（D01.05）
-- ============================================================================

-- 17. PIPL分级/脱敏/留存/字段登记字典（D01.05 · P0，字典表 owner_id 免填）
CREATE TABLE bas_pipl_policy (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  policy_type       VARCHAR(16)     NOT NULL COMMENT '策略类型:level_dict=分级字典,mask_rule=脱敏规则,retention=留存策略,field_registry=敏感字段登记(四类统一载体)',
  policy_code       VARCHAR(64)     NOT NULL COMMENT '策略编码(level_dict=L0/L1/L2/L2P/L3;mask_rule=phone/name/address/id_card/bank_card/token/open_id;retention/field_registry=实体名或自定义码)',
  policy_name       VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '策略名称',
  entity_name       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '实体名(retention/field_registry用:ord_order/order_receiver/shop_auth等)',
  field_name        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '字段名(field_registry用:receiver_mobile;与D01.04元数据sensitive声明双向一致校验;CI扫描疑似敏感字段名模式phone/id_card/token等强制申报防漏登记)',
  level             VARCHAR(8)      NOT NULL DEFAULT '' COMMENT '敏感级别(level_dict=级别定义;field_registry=字段级别):L0=公开(明文),L1=内部(一般个人信息:买家昵称/open_id),L2=敏感(个人敏感:姓名/电话/地址,信封加密+默认脱敏),L2P=平台密文(oaid类原样保存不解密,密文直传),L3=高敏(身份证/银行卡/token/secret,全脱敏+服务账号白名单)',
  mask_rule_code    VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '脱敏规则引用(field_registry->mask_rule.policy_code;脱敏值不可逆且同值稳定支撑人工比对)',
  plain_access_mode VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '明文访问模式(field_registry用):perm_point=字段权限点(L2,{entity}.field.{f}.plain+留痕),service_whitelist=服务账号白名单(L3,申报组装账号逐次审计),forbidden=禁止',
  blind_index_flag  TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '盲索引开关(field_registry用:HMAC独立索引密钥前缀哈希辅助列,等值/前缀检索;索引密钥与加密密钥分离;加密字段禁like)',
  retention_json    JSON            NULL DEFAULT NULL COMMENT '留存配置(retention用:{"online_years":3,"archive":true,"anonymize_after_months":36,"necessity":"contract"};level_dict用=级别默认策略)',
  necessity         VARCHAR(16)     NOT NULL DEFAULT '' COMMENT '采集必要性(field_registry用):contract=履约必需,legal=法定要求,convenience=业务便利(L2+需合规评审通过,源头控制)',
  policy_version    INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '策略版本(留存期变更走合规评审+登记版本化,变更审计;PIA评审留档)',
  reviewer          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '合规评审人(L2+字段登记必填)',
  status            TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=历史/停用',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted        TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_pipl_policy (policy_type, policy_code, entity_name, field_name, policy_version),
  KEY idx_bas_pipl_policy_entity (policy_type, entity_name, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='PIPL分级/脱敏/留存/字段登记字典(D01.05,P0,级别声明一次六环节自动按级别执行)';

-- 18. PIPL授权留痕（D01.05 · P0，流水类append-only+哈希链，无软删无version）
CREATE TABLE bas_pipl_consent (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id            BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  consent_bn           VARCHAR(32)     NOT NULL COMMENT '授权记录编号,唯一(CS+日期+序列)',
  subject_key          VARCHAR(128)    NOT NULL COMMENT '数据主体标识(open_id+平台/买家标识;密文或盲索引形态,禁明文)',
  subject_platform     VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '主体所属平台(taobao/douyin/pdd等)',
  scene                VARCHAR(64)     NOT NULL COMMENT '授权场景:order_fulfill=平台订单履约默认链路(登记说明性机制),cross_border_declare=跨境申报身份证单独授权(独立勾选/明示用途/不与通用协议合并,D03.12),marketing=营销(P2预留),portal_register=门户注册协议(D10.02),wecom_oauth=企微OAuth授权(D10.02),oidc_consent=OIDC授权(预留)',
  legal_basis          VARCHAR(32)     NOT NULL DEFAULT 'contract' COMMENT '合法性基础:contract=履行合同所必需(PIPL第13条,凯淳=受托处理者,处理范围以履约必需为限),separate_consent=单独授权,legal=法定义务',
  consent_text_version VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '告知/授权文本版本(版本化留档,关联记录可回放当时文本)',
  channel              VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '授权渠道(采集页/客服/门户注册页/企微)',
  consent_time         DATETIME(3)     NOT NULL COMMENT '授权时间',
  revoke_time          DATETIME(3)     NULL DEFAULT NULL COMMENT '撤回时间(撤回后停止新增处理,已处理数据按留存策略;append-only:撤回=新增事件行不改原记录)',
  evidence_json        JSON            NULL DEFAULT NULL COMMENT '授权证据快照{"checked":true,"ip":"","session_ref":"","page_ref":""}(勾选状态/IP/会话引用,不可篡改)',
  row_hash             CHAR(64)        NOT NULL DEFAULT '' COMMENT '记录哈希=SHA256(内容+prev_hash)(append-only哈希链,篡改可检出)',
  prev_hash            CHAR(64)        NOT NULL DEFAULT '' COMMENT '前条哈希(链序)',
  create_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_pipl_consent_bn (consent_bn),
  KEY idx_bas_pipl_consent_subject (subject_key, scene),
  KEY idx_bas_pipl_consent_time (consent_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='PIPL授权留痕(D01.05,P0,append-only哈希链,监管问询与内审响应数据源)';

-- 19. 数据主体权利请求（D01.05 · P0，单据类无软删）
CREATE TABLE bas_pipl_ds_request (
  id                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id         BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  dsr_bn            VARCHAR(32)     NOT NULL COMMENT '请求编号,唯一(DSR+日期+序列)',
  request_type      VARCHAR(16)     NOT NULL COMMENT '请求类型:query=查询,copy=复制,correct=更正(路由域工单如D03.08改单,跟踪闭环),delete=删除(留存期内限制处理+期满匿名化),revoke=撤回授权(同删除逻辑)',
  subject_locator   VARCHAR(255)    NOT NULL COMMENT '主体定位信息(买家open_id/收货手机盲索引/订单号;密文形态;全域扫描数据清单依据)',
  verify_evidence   VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '身份核验依据(平台渠道默认已核验登记依据;直接渠道核验步骤记录)',
  source_channel    VARCHAR(32)     NOT NULL COMMENT '来源渠道:platform_cs=平台客服,email=邮件,phone=电话记录',
  deadline          DATETIME(3)     NOT NULL COMMENT 'SLA截止(15个工作日,PIPL口径,平台渠道时限优先;超期告警D01.07)',
  scan_result_ref   VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '数据清单引用(FR-05b扫描产物OSS:域/实体/记录数/敏感级别;依赖字段登记完整性)',
  restricted_flag   TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '限制处理打标:0=否,1=是(restricted主体:封锁营销触达/画像/推荐/BI明细层,保留履约必需存量查询与法定留存司法调取;解除需合规负责人+双人复核+审计)',
  handle_status     TINYINT         NOT NULL DEFAULT 0 COMMENT '处置状态:0=待受理,1=扫描中,2=处置中,3=已办结,4=已拒绝(双人复核),5=超期升级',
  handle_result     VARCHAR(1024)   NOT NULL DEFAULT '' COMMENT '处理结果摘要(查询=脱敏副本输出,明文副本需合规审批逐次审计;响应内容/时间供渠道答复消费者)',
  handler           VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '经办人(客服/合规专员)',
  reject_reason     VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '拒绝理由(留存义务/司法要求/公共利益)',
  approver          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '合规负责人确认(拒绝决定双人复核必填)',
  finish_time       DATETIME(3)     NULL DEFAULT NULL COMMENT '办结时间',
  create_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '登记时间',
  update_time       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version           INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_pipl_ds_request_bn (dsr_bn),
  KEY idx_bas_pipl_ds_request_status (handle_status, deadline),
  KEY idx_bas_pipl_ds_request_subject (subject_locator)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='数据主体权利请求(D01.05,P0,DSR工作台,15工作日SLA)';

-- ============================================================================
-- 六、导入导出中心（D01.06）
-- ============================================================================

-- 20. 导入模板（D01.06 · P0，辅助配置表 owner_id 免填）
CREATE TABLE bas_ie_template (
  id                      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id               BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  template_code           VARCHAR(64)     NOT NULL COMMENT '模板编码(全局唯一,如material_import/order_import/purchase_request_import)',
  template_name           VARCHAR(128)    NOT NULL COMMENT '模板名称',
  domain_code             VARCHAR(16)     NOT NULL COMMENT '归属域:D03/D04/D06/D08/D09等(任务中心按模板类型筛选)',
  entity_ref              VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '元数据实体引用 LFK->bas_entity_meta(列集默认元数据驱动生成:表头=中文标签/必填标记/枚举说明自动出,可人工增删如货主编码映射列)',
  importer_ref            VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '导入器实现引用(ImporterInterface DI定位,templateCode绑定;rowValidate业务校验+commitBatch批次提交+crossRowCheck勾稽钩子+supportMode断点/重跑声明)',
  columns_json            JSON            NOT NULL COMMENT '列定义[{col_name,field_map,required,value_type,enum_dict,example,desc}]',
  validate_rules_json     JSON            NULL DEFAULT NULL COMMENT '框架层校验规则(格式/值域,零业务代码;业务校验在导入器rowValidate)',
  sensitive_columns_json  JSON            NULL DEFAULT NULL COMMENT '敏感列清单["receiver_mobile"](L2+:模板下载按权限裁剪列+导入落库即经D01.05加密,导入通道不豁免)',
  template_version        INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '模板版本(变更生成新版本,列diff登记;文件内嵌版本标识/表头指纹自动识别)',
  compat_until            DATE            NULL DEFAULT NULL COMMENT '旧版兼容截止(默认发布+30天,窗口后拒绝导入提示下载新模板)',
  header_fingerprint      CHAR(64)        NOT NULL DEFAULT '' COMMENT '表头指纹(版本自动识别辅助)',
  perm_point              VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '使用权限点(D10.03注册)',
  status                  TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=停用',
  create_time             DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time             DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted              TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_ie_template (template_code, template_version),
  KEY idx_bas_ie_template_domain (domain_code, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='导入模板(D01.06,P0,辅助,元数据同源生成+版本化+兼容窗口)';

-- 21. 导入任务（D01.06 · P0，单据类无软删）
CREATE TABLE bas_import_task (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(数据权限维度,可空=0)',
  task_bn          VARCHAR(32)     NOT NULL COMMENT '任务号,唯一(IM+日期+序列,用户可见;bas_seq发号)',
  template_code    VARCHAR(64)     NOT NULL COMMENT '模板编码 LFK->bas_ie_template',
  template_version INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '模板版本快照(文件解析按版本列映射)',
  entity_ref       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '目标实体',
  source_file_ref  VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '源文件OSS引用(分片上传>5MB/MD5完整性/上限200MB或100万行/病毒宏安检xlsm拒绝;留存90天,含L2+数据下载需权限点)',
  file_md5         CHAR(32)        NOT NULL DEFAULT '' COMMENT '文件指纹(同MD5 24h内重复创建任务警告确认)',
  row_count_total  INT             NOT NULL DEFAULT 0 COMMENT '总行数',
  status           TINYINT         NOT NULL DEFAULT 0 COMMENT '状态机:0=待执行,1=执行中(worker认领),2=成功(全部行),3=部分成功(有错误行报告可下载,合法终态:错误行不阻塞正确行D04.01 AC-10全系统口径),4=失败(系统级:解析失败/导入器异常),5=已取消(协作式:当前批完成后停,已提交批保留)',
  progress_json    JSON            NULL DEFAULT NULL COMMENT '进度{processed,success,fail,percent,checkpoint_batch,est_remain,batches:[{batch_no,row_range,success,fail,status,error_digest,commit_time}]}(批次粒度更新;checkpoint=断点续跑幂等;批次明细ie_task_batch承载;进度停滞10分钟告警,僵尸30分钟扫描置失败)',
  result_json      JSON            NULL DEFAULT NULL COMMENT '结果{success_rows,fail_rows,error_report_ref,cluster_summary:[{error_code,count,sample_rows}]}(错误聚类摘要TOP:800行失败中600行=货号重复,帮用户批量修表)',
  error_report_ref VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '错误报告OSS引用(标准Excel:sheet1错误明细(原行全列+行号+错误阶段+错误码+人读消息)/sheet2聚类摘要/sheet3成功统计;错误报告可直接作为重导文件,已成功行幂等不重复)',
  retry_count      INT             NOT NULL DEFAULT 0 COMMENT '重试次数(<=3;断点续跑从失败批开始/整任务重跑按导入器supportMode声明)',
  cancel_flag      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '取消请求标记(协作式终止)',
  fail_reason      VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '失败原因摘要',
  creator          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '发起人(数据权限:普通用户见本人任务,域管理员见本域D10.03;同用户并发上限默认3防刷)',
  start_time       DATETIME(3)     NULL DEFAULT NULL COMMENT '开始时间',
  end_time         DATETIME(3)     NULL DEFAULT NULL COMMENT '结束时间',
  cost_ms          INT             NOT NULL DEFAULT 0 COMMENT '耗时毫秒(性能契约:5万行<=10分钟/1万行<=5分钟/10万行<=20分钟,解析+校验>=1000行/秒,业务校验>=300行/秒批量预取)',
  trace_id         VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '全链路追踪ID',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(进度并发更新CAS)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_import_task_bn (task_bn),
  KEY idx_bas_import_task_status (status, create_time),
  KEY idx_bas_import_task_creator (creator, create_time),
  KEY idx_bas_import_task_md5 (file_md5)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='导入任务(D01.06,P0,worker池流式解析+批事务边界+checkpoint断点续跑,单据类无软删)';

-- 22. 导入错误行明细（D01.06 · P0，流水类只增无软删）
CREATE TABLE bas_import_error (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id     BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  task_id       BIGINT UNSIGNED NOT NULL COMMENT '导入任务 LFK->bas_import_task(在线90天随任务归档清理)',
  row_no        INT             NOT NULL COMMENT '源文件行号(幂等键成分:任务+行号,断点续跑/修正重导不重复提交)',
  error_stage   VARCHAR(16)     NOT NULL COMMENT '错误阶段:format=框架格式校验(必填/类型/长度/枚举),business=业务校验(rowValidate逐行独立),commit=批次提交',
  error_code    VARCHAR(64)     NOT NULL COMMENT '错误码(模板级字典登记,可统计可聚类)',
  error_message VARCHAR(512)    NOT NULL COMMENT '人读错误消息(含定位信息:第3列货号BM1001已存在;禁裸异常堆栈)',
  row_snapshot  JSON            NOT NULL COMMENT '原行数据全列快照(错误报告sheet1数据源;敏感列脱敏形态)',
  create_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_import_error (task_id, row_no),
  KEY idx_bas_import_error_code (task_id, error_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='导入错误行明细(D01.06,P0,错误报告数据源+修正重导幂等依据)';

-- 23. 导出任务·含PIPL台账（D01.06 · P0，单据类无软删）
CREATE TABLE bas_export_task (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id        BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  owner_id         BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '货主(数据权限维度,可空=0)',
  task_bn          VARCHAR(32)     NOT NULL COMMENT '任务号,唯一(EX+日期+序列)',
  exporter_ref     VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '导出器引用(ExporterInterface DI定位fetchBatch游标分批;档案类复用D01.04通用列表查询契约框架代理实现零代码)',
  entity_ref       VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '导出实体',
  filter_digest    VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '筛选条件摘要(台账与重跑依据;参数快照脱敏存储)',
  columns_snapshot JSON            NULL DEFAULT NULL COMMENT '导出列快照(用户列配置+修饰口径与列表一致:枚举中文/档案名称/脱敏同源渲染)',
  sensitive_flag   TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '含敏感列:0=否,1=是(L2+触发管控链路,创建任务时判定无法绕过)',
  plain_apply      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '明文导出申请:0=脱敏直通,1=申请明文(需OA审批;L3字段批量明文直接拒绝并提示替代路径)',
  approval_ref     VARCHAR(32)     NOT NULL DEFAULT '' COMMENT 'OA审批单号(明文导出必填,审批通过绑定后任务转可执行;拒绝则终止 LFK->oms_org.org_approval_instance)',
  watermark_params VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '水印参数(明水印=操作人+时间+审批单号平铺;暗水印=文件指纹+追溯码嵌入泄露溯源;不可配置关闭=红线)',
  status           TINYINT         NOT NULL DEFAULT 0 COMMENT '状态机:0=待审批,1=待执行,2=执行中,3=成功,4=失败,5=已取消,6=审批拒绝终止(>10万行自动低优先级队列)',
  progress_json    JSON            NULL DEFAULT NULL COMMENT '进度{exported_rows,total,percent,cursor}(流式内存恒定<=256MB;批间限速只读从库)',
  file_ref         VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '结果文件OSS引用(生命周期7天自动清理;明文文件加密压缩,密码另通道送达:链接站内信/密码企微短信)',
  file_digest      CHAR(64)        NOT NULL DEFAULT '' COMMENT '文件指纹(台账登记+导出完成通知含指纹)',
  row_count        INT             NOT NULL DEFAULT 0 COMMENT '导出行数(10万行<=15分钟/100万行<=2小时)',
  download_token   VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '一次性下载令牌',
  download_expire  DATETIME(3)     NULL DEFAULT NULL COMMENT '链接时效(默认24h,可配1-72h;失效前2h提醒)',
  download_count   INT             NOT NULL DEFAULT 0 COMMENT '下载次数(超限链接失效)',
  applicant        VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '申请人(pipl_export_ledger台账:人/时间/实体/筛选/列/敏感/审批/指纹/下载次数全量登记,供D10.06检索与月度合规复盘)',
  purpose          VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '导出用途(审批要素)',
  fail_reason      VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '失败原因',
  retry_count      INT             NOT NULL DEFAULT 0 COMMENT '重试次数(<=3)',
  start_time       DATETIME(3)     NULL DEFAULT NULL COMMENT '开始时间',
  end_time         DATETIME(3)     NULL DEFAULT NULL COMMENT '结束时间',
  cost_ms          INT             NOT NULL DEFAULT 0 COMMENT '耗时毫秒',
  trace_id         VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '全链路追踪ID',
  create_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version          INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_export_task_bn (task_bn),
  KEY idx_bas_export_task_status (status, create_time),
  KEY idx_bas_export_task_applicant (applicant, create_time),
  KEY idx_bas_export_token (download_token)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='导出任务含PIPL台账(D01.06,P0,管控内置不可绕过:审批+明暗水印+一次性令牌+密码分离通道,单据类无软删)';

-- ============================================================================
-- 七、通知与告警（D01.07）
-- ============================================================================

-- 24. 通知模板（D01.07 · P0，配置表 owner_id 免填）
CREATE TABLE bas_notify_template (
  id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id            BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  template_code        VARCHAR(64)     NOT NULL COMMENT '模板编码,全局唯一({域}.{场景},如d08.settle.pending/d04.stock.red_alert)',
  template_name        VARCHAR(128)    NOT NULL COMMENT '模板名称',
  domain_code          VARCHAR(16)     NOT NULL COMMENT '归属域',
  msg_class            VARCHAR(16)     NOT NULL DEFAULT 'notify' COMMENT '消息类别:alert=告警(P0/P1/P2分级通道),notify=业务通知(内部),consumer=C端消费者(平台通道优先短信兜底,时段8:00-21:00限制),external=外发(供应商/品牌方邮件,退信->短信联系人)',
  channel_contents_json JSON           NOT NULL COMMENT '通道模板集{"wecom_card":{},"sms":"","email_html":"","inbox":""}(多通道同源变量渲染)',
  variables_json       JSON            NOT NULL COMMENT '变量声明[{name,type,required,example,sensitive}](缺必填变量拒发报错不产生null内容;敏感变量D01.05规约:服务商通道明文发送,本地记录与日志脱敏形态留存)',
  template_version     INT UNSIGNED    NOT NULL DEFAULT 1 COMMENT '版本(变更版本化+审计;发送记录关联版本可回放渲染内容)',
  compliance_confirmed TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '合规确认:0=未确认(C端模板无法发布),1=已确认(短信模板报备)',
  owner_name           VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '模板Owner',
  locale               VARCHAR(16)     NOT NULL DEFAULT 'zh-CN' COMMENT '多语言(P2预留)',
  sender_ref           VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '发送主体引用(短信签名/邮件发件人,P2预留)',
  status               TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=停用',
  create_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time          DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted           TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_notify_template (template_code, template_version),
  KEY idx_bas_notify_template_domain (domain_code, msg_class, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='通知模板(D01.07,P0,多通道同源变量+版本化,C端模板合规确认)';

-- 25. 通知路由订阅规则（D01.07 · P0，配置表）
CREATE TABLE bas_notify_route (
  id                      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id               BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  route_name              VARCHAR(128)    NOT NULL COMMENT '规则名称',
  event_pattern           VARCHAR(128)    NOT NULL COMMENT '事件匹配模式(alert_key/事件名,支持通配mq.*/sched.task.*/pipl.*/ie.*/wms.circuit.*/gateway.auth.*等FR-06清单)',
  condition_json          JSON            NULL DEFAULT NULL COMMENT '条件维度{"domain":"D04","level":"P1","shop_ids":[],"owner_ids":[],"branch_ids":[]}',
  receiver_resolvers_json JSON            NOT NULL COMMENT '接收人解析器集[{"type":"role|owner_manager|shop_binder|org_manager_up|fixed|initiator|duty","params":{}}](duty含值班配置{role_code,shift,members,contact_snapshot}=值班表数据承载;解析时点固化联系方式快照)',
  channels_json           JSON            NOT NULL COMMENT '通道集["wecom","sms","inbox","email","voice"](分级通道策略:P0=电话+企微穿透免打扰60s,P1=企微2分钟,P2=日报池次日9:00零条不发;降级矩阵:企微故障->短信,全故障->元告警电话直呼值班)',
  level_override          VARCHAR(8)      NOT NULL DEFAULT '' COMMENT '级别覆写(空=用消息声明级别)',
  silence_json            JSON            NULL DEFAULT NULL COMMENT '静默策略{"silence_minutes":30,"escalate_count":10}(同类合并计数不发送;计数超升级阈值突破静默发摘要重置计数;到期发累计摘要xN;风暴保护:单源1分钟>100条强制收敛+源治理告警)',
  escalate_json           JSON            NULL DEFAULT NULL COMMENT '升级策略{"ack_timeout_minutes":30,"max_level":3,"up_resolvers":[]}(P0/P1未ack持续超阈->接收人up+通道提升<=3级;升级链何时升给谁入审计复盘)',
  denoise_flag            TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '降噪声明:0=正常,1=仅计数进日报/阈值触发即时发(FR-04g)',
  priority                INT             NOT NULL DEFAULT 0 COMMENT '优先级(多条规则命中全执行;缺省规则最低)',
  default_flag            TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '域缺省规则:0=否,1=是(兜底不可删;无规则命中走域缺省值班规则,禁止静默丢弃=触达率100%承诺)',
  status                  TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=启用,2=停用(手工操作全审计)',
  create_time             DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time             DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version                 INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本',
  is_deleted              TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是(缺省规则不可删)',
  PRIMARY KEY (id),
  KEY idx_bas_notify_route_event (event_pattern, status),
  KEY idx_bas_notify_route_default (default_flag, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='通知路由订阅规则(D01.07,P0,7类接收人解析器+收敛升级策略,值班表数据由duty解析器承载)';

-- 26. 发送日志（D01.07 · P0，按月分表 _YYYYMM 结构基线，流水类）
CREATE TABLE bas_notify_log (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id          BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  msg_bn             VARCHAR(32)     NOT NULL COMMENT '消息编号,唯一(NT+日期+序列;受理即落库,发送记录不丢)',
  msg_class          VARCHAR(16)     NOT NULL DEFAULT 'notify' COMMENT '消息类别:alert/notify/consumer/external(同模板msg_class)',
  biz_event          VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '业务事件名(触发源:finance.settle.drafted/stock.shortage等)',
  alert_key          VARCHAR(128)    NOT NULL DEFAULT '' COMMENT '告警键(收敛关联bas_alert_record)',
  template_code      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '模板编码 LFK->bas_notify_template',
  template_version   INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '模板版本快照(历史记录关联旧版本可回放渲染)',
  rendered_content   TEXT            NULL DEFAULT NULL COMMENT '渲染内容(敏感变量脱敏形态留存,本地零明文)',
  receiver_raw       VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '接收人原始声明(角色/解析器)',
  receiver_resolved  VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '接收人解析结果快照(账户ID/手机脱敏形态138****0000)',
  channel            VARCHAR(16)     NOT NULL COMMENT '通道:wecom=企微,sms=短信,email=邮件,inbox=站内信,voice=电话,platform=平台通道',
  send_status        TINYINT         NOT NULL DEFAULT 0 COMMENT '状态:0=受理,1=已提交服务商,2=送达(回执确认),3=失败(通道级令牌桶限流:超限排队削峰不丢弃,优先级P0>P1>通知>P2;同模板同内容多接收人批量合并)',
  receipt            VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '服务商回执(短信状态报告/邮件退信)',
  retry_count        INT             NOT NULL DEFAULT 0 COMMENT '重试次数(失败重试+换通道)',
  fail_reason        VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '失败原因(空号/超限/通道故障)',
  fallback_channel   VARCHAR(16)     NOT NULL DEFAULT '' COMMENT '换通道记录(sms->inbox,email等;催办类送达凭证可查=品牌方声称没收到对账场景)',
  merged_count       INT             NOT NULL DEFAULT 0 COMMENT '合并计数(收敛摘要消息关联的原始条数,可下钻全部明细)',
  silence_ref        VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '静默关联(摘要消息引用的alert_key)',
  biz_ref            VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '关联业务对象(订单/店铺/任务号,按人/事件/业务对象三维检索)',
  link_task_bn       VARCHAR(32)     NOT NULL DEFAULT '' COMMENT '分通道交付关联(D01.06:链接=站内信/密码=企微,双通道关联同任务)',
  trace_id           VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '全链路追踪ID',
  create_time        DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '受理时间',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_notify_log_bn (msg_bn),
  KEY idx_bas_notify_log_receiver (receiver_resolved, create_time),
  KEY idx_bas_notify_log_event (biz_event, alert_key, create_time),
  KEY idx_bas_notify_log_biz (biz_ref),
  KEY idx_bas_notify_log_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='通知发送日志(D01.07,P0,按月分表_YYYYMM,在线90天+归档,触达留痕可查)';
-- 月表示例（调度器滚动创建）：CREATE TABLE bas_notify_log_202611 LIKE bas_notify_log;

-- 27. 告警记录·收敛状态（D01.07 · P0）notify_alert_state 合并承载
CREATE TABLE bas_alert_record (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  alert_key      VARCHAR(128)    NOT NULL COMMENT '告警键,唯一(收敛维度:{域}.{对象}.{类型},如mq.q.finance.order_completed.backlog;活跃key<=1万)',
  alert_level    VARCHAR(8)      NOT NULL DEFAULT 'P1' COMMENT '当前级别:P0=电话+企微穿透免打扰(事件->拨出<=60s),P1=企微(<=2分钟送达),P2=日报池(次日9:00±5分钟聚合,零条不发)',
  first_time     DATETIME(3)     NOT NULL COMMENT '首次告警时间',
  last_time      DATETIME(3)     NOT NULL COMMENT '末次告警时间',
  merged_count   INT             NOT NULL DEFAULT 1 COMMENT '静默期合并计数(收敛状态机:首条即时发送->静默期同类计数不发送->计数超升级阈值突破静默发摘要->到期发累计摘要;风暴保护:单源1分钟>100条强制收敛)',
  silence_until  DATETIME(3)     NULL DEFAULT NULL COMMENT '静默截止(默认30分钟同任务同原因不重复发)',
  ack_by         VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '认领/确认人(企微卡片ack回调/值班台;ack后止升级)',
  ack_time       DATETIME(3)     NULL DEFAULT NULL COMMENT '认领时间',
  escalate_level TINYINT         NOT NULL DEFAULT 0 COMMENT '升级层级(<=3;P0/P1未ack持续超阈->接收人up+通道提升;升级链记录何时升给谁入审计)',
  escalate_time  DATETIME(3)     NULL DEFAULT NULL COMMENT '最后升级时间',
  recovered      TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '恢复状态:0=活跃,1=已恢复(恢复事件->原接收人发恢复通知,静默/升级状态清零解除闭环)',
  recover_time   DATETIME(3)     NULL DEFAULT NULL COMMENT '恢复时间',
  last_vars_json JSON            NULL DEFAULT NULL COMMENT '最近一次告警变量快照(摘要渲染与下钻明细)',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version        INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(收敛计数并发CAS)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_alert_record_key (alert_key),
  KEY idx_bas_alert_record_active (recovered, alert_level, last_time),
  KEY idx_bas_alert_record_escalate (escalate_level, ack_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='告警记录收敛状态(D01.07,P0,per alert_key收敛/升级/认领/恢复闭环运行态)';

-- ============================================================================
-- 八、基础支撑
-- ============================================================================

-- 28. 发号器序列（DB-00 §3 · P0，配置表）
CREATE TABLE bas_seq (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id     BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  seq_domain    VARCHAR(32)     NOT NULL COMMENT '域码(单号前缀:AP=审批单,ST=换货主,DL=死信,SE=调度执行,SB=沙箱,IM=导入,EX=导出,NT=通知,CS=授权,DSR=权利请求,OD=订单等)',
  seq_date      DATE            NOT NULL COMMENT '序列日期(每日重置;单号=前缀+yyyyMMdd+序列,防遍历)',
  current_value BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '当前值(Redis INCR主发号,本表DB兜底与对账修复权威;CAS更新或号段模式)',
  step_size     INT             NOT NULL DEFAULT 100 COMMENT '号段步长(一次取号段减少竞争)',
  max_value     BIGINT UNSIGNED NOT NULL DEFAULT 99999999 COMMENT '序列上限(超限告警)',
  remark        VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '说明',
  create_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  version       INT UNSIGNED    NOT NULL DEFAULT 0 COMMENT '乐观锁版本(CAS发号)',
  PRIMARY KEY (id),
  UNIQUE KEY uk_bas_seq (seq_domain, seq_date, tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='发号器序列(P0,DB-00 §3单号生成:Redis主发号+DB兜底对账)';

-- 29. 迁移字段映射登记（DB-00 §7.3 · P2/M4 预留）
CREATE TABLE bas_migration_mapping (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  tenant_id      BIGINT UNSIGNED NOT NULL DEFAULT 1 COMMENT '租户ID',
  source_module  VARCHAR(64)     NOT NULL COMMENT '商派源模块(ome/material/finance/organization等)',
  source_table   VARCHAR(64)     NOT NULL COMMENT '源表名',
  source_field   VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '源字段(空=表级映射)',
  target_schema  VARCHAR(64)     NOT NULL COMMENT '目标schema(oms_order等)',
  target_table   VARCHAR(64)     NOT NULL COMMENT '目标表',
  target_field   VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '目标字段',
  transform_rule VARCHAR(512)    NOT NULL DEFAULT '' COMMENT '转换规则(枚举值映射/单位换算/拼接拆分表达式;迁移数据保留原单号于业务唯一键,新id重新发号DB-00 §7.4;source=migration标记)',
  mapping_version INT UNSIGNED   NOT NULL DEFAULT 1 COMMENT '映射版本',
  status         TINYINT         NOT NULL DEFAULT 1 COMMENT '状态:1=生效,2=废弃',
  create_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  update_time    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  is_deleted     TINYINT(1)      NOT NULL DEFAULT 0 COMMENT '软删标记:0=否,1=是',
  PRIMARY KEY (id),
  KEY idx_bas_migration_mapping_source (source_module, source_table),
  KEY idx_bas_migration_mapping_target (target_schema, target_table)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='迁移字段映射登记(P2/M4预留,DB-00 §7.3商派->凯淳映射单一事实源)';

-- ============================================================================
-- 九、初始字典数据
-- ============================================================================

-- 9.1 领域事件字典样例（跨域主链核心事件，SRS-00 §4.4 / 各域 SRS 事件清单节选；全量随各域迁移脚本注册）
INSERT INTO bas_event_dict (tenant_id, event_name, event_desc, domain_code, publisher_module, subscribers_json, reliability, partitioned, partition_key_field, blocking_flag, sla_minutes, status) VALUES
(1, 'order.raw.received',      '平台订单报文接收落缓冲',   'D02', 'D02.03', '[{"module":"D03.01","queue":"q.order.create"}]',                          'reliable',    1, 'shop_id',           1, 5,  1),
(1, 'order.delivery.shipped',  '发货单确认出库',           'D03', 'D03.07', '[{"module":"D02.04","queue":"q.gateway.ship_callback"},{"module":"D08.01","queue":"q.finance.ar_register"}]', 'reliable', 1, 'delivery_id', 1, 5, 1),
(1, 'order.completed',         '订单完成(发货后N天自动/确认)', 'D03', 'D03.01', '[{"module":"D08.01","queue":"q.finance.order_completed"},{"module":"D11","queue":"q.report.order_completed"}]', 'reliable', 0, '', 1, 10, 1),
(1, 'stock.change.logged',     '库存口径变动流水',         'D04', 'D04.02', '[{"module":"D04.02","queue":"q.stock.change_log_writer"}]',              'reliable',    1, 'triple_hash',       1, 5,  1),
(1, 'stock.shortage',          '缺货/断货预警',            'D04', 'D04.10', '[{"module":"D10.04","queue":"q.portal.stock_alert"},{"module":"D01.07","queue":"q.notify.stock_shortage"}]', 'best-effort', 0, '', 1, 10, 1),
(1, 'approval.finished',       '审批终态结果分发',         'D10', 'D10.05', '[{"module":"*","queue":"q.{消费域}.approval_finished"}]',                 'reliable',    0, '',                  1, 5,  1),
(1, 'rule.config.changed',     '规则/字典变更缓存失效广播', 'D01', 'D01.03', '[{"module":"D03.02","queue":"q.order.rule_reload"},{"module":"D05.05","queue":"q.aftersale.rule_reload"}]', 'best-effort', 0, '', 0, 1, 1),
(1, 'org.node.moved',          '组织节点移动/新增',        'D10', 'D10.01', '[{"module":"D10.03","queue":"q.perm.scope_recalc"}]',                     'reliable',    0, '',                  1, 5,  1),
(1, 'auth.role_changed',       '账户角色/权限变更',        'D10', 'D10.02', '[{"module":"D10.03","queue":"q.perm.ctx_invalidate"}]',                   'best-effort', 0, '',                  0, 1,  1),
(1, 'finance.settle.drafted',  '结算单生成待确认',         'D08', 'D08.02', '[{"module":"D10.04","queue":"q.portal.settle_notify"}]',                  'reliable',    0, '',                  1, 30, 1),
(1, 'ie.task.completed',       '导入导出任务完成',         'D01', 'D01.06', '[{"module":"D01.07","queue":"q.notify.ie_result"}]',                      'best-effort', 0, '',                  0, 5,  1),
(1, 'mq.deadletter.created',   '死信产生告警',             'D01', 'D01.01', '[{"module":"D01.07","queue":"q.notify.deadletter"}]',                     'best-effort', 0, '',                  0, 1,  1);

-- 9.2 调度任务白名单样例（SRS-D01.02 FR-08 清单节选；全量任务随各域上线注册）
INSERT INTO bas_schedule_task (tenant_id, task_name, task_desc, domain_code, owner_name, schedule_type, expression, thread_num, shard_count, timeout_sec, retry_times, rule_json, alarm_json, exec_mode, status) VALUES
(1, 'gateway.pull_orders',       '拉单增量轮询(分店铺分片)',      'D02', '网关值班',   'fixed_rate', '60',  4, 4, 55,  0, '{"enabled":true,"misfire":"skip"}',                                        '{"level":"P1","continuous_fail_threshold":3}', 'mq',     1),
(1, 'stock.reconcile_sample',    'Redis-DB库存对账(抽样)',        'D04', '库存值班',   'fixed_rate', '300', 1, 1, 240, 1, '{"enabled":true,"misfire":"skip","skip_if_running":true}',                '{"level":"P0","continuous_fail_threshold":3}', 'mq',     1),
(1, 'stock.daily_snapshot',      '库存日终快照',                  'D04', '库存值班',   'cron',       '0 0 * * *', 1, 1, 3600, 1, '{"enabled":true,"misfire":"fire_once"}',                              '{"level":"P0","continuous_fail_threshold":1}', 'mq',     1),
(1, 'finance.settle_daily_check','结算取数台账日校验',            'D08', '财务值班',   'dag',        '',    1, 1, 1800, 1, '{"enabled":true,"misfire":"fire_once"}',                                '{"level":"P1","continuous_fail_threshold":2}', 'mq',     1),
(1, 'bi.wide_table_refresh',     'BI宽表刷新',                    'D11', '数据值班',   'dag',        '',    1, 1, 3600, 1, '{"enabled":true,"misfire":"fire_once"}',                                '{"level":"P2","continuous_fail_threshold":2}', 'mq',     1),
(1, 'order.archive_daily',       '订单归档(凌晨窗口限速分片)',    'D03', '运维值班',   'cron',       '0 2 * * *', 2, 2, 10800, 0, '{"enabled":true,"window":"02:00-05:00","misfire":"fire_once"}',       '{"level":"P1","continuous_fail_threshold":1}', 'mq',     1),
(1, 'base.outbox_heartbeat',     'outbox投递器心跳巡检',          'D01', '底座值班',   'fixed_rate', '60',  1, 1, 30,  0, '{"enabled":true,"misfire":"skip"}',                                        '{"level":"P0","continuous_fail_threshold":3}', 'inline', 1),
(1, 'base.deadletter_escalate',  '死信积压升级检查(>24h)',        'D01', '底座值班',   'cron',       '0 * * * *', 1, 1, 60, 0, '{"enabled":true,"misfire":"skip"}',                                        '{"level":"P1","continuous_fail_threshold":2}', 'inline', 1),
(1, 'base.month_table_create',   '月分表滚动创建(trace/log/audit)', 'D01', '底座值班', 'cron',       '0 3 25 * *', 1, 1, 300, 1, '{"enabled":true,"misfire":"fire_once"}',                               '{"level":"P0","continuous_fail_threshold":1}', 'inline', 1),
(1, 'audit.hash_chain_verify',   '审计hash链校验(抽样)',          'D10', '安全值班',   'cron',       '30 1 * * *', 1, 1, 1800, 1, '{"enabled":true,"misfire":"fire_once"}',                              '{"level":"P0","continuous_fail_threshold":1}', 'mq',     1),
(1, 'pipl.retention_scan',       'PIPL留存扫描与匿名化',          'D01', '合规值班',   'cron',       '0 4 * * *', 1, 1, 3600, 1, '{"enabled":true,"misfire":"fire_once"}',                                '{"level":"P1","continuous_fail_threshold":2}', 'mq',     1),
(1, 'rule.hit_stat_daily',       '规则命中统计日聚合',            'D01', '底座值班',   'cron',       '30 0 * * *', 1, 1, 1800, 1, '{"enabled":true,"misfire":"fire_once"}',                              '{"level":"P2","continuous_fail_threshold":2}', 'mq',     1),
(1, 'fulfill.wms_health_probe',  'WMS健康探活(分账号)',           'D09', '履约值班',   'fixed_rate', '60',  1, 1, 30,  0, '{"enabled":true,"misfire":"skip"}',                                        '{"level":"P0","continuous_fail_threshold":3}', 'inline', 1),
(1, 'notify.daily_report',       'P2告警日报聚合推送',            'D01', '底座值班',   'cron',       '0 9 * * *', 1, 1, 300, 1, '{"enabled":true,"misfire":"fire_once"}',                                 '{"level":"P2","continuous_fail_threshold":2}', 'inline', 1);

-- 9.3 首批 DAG 依赖（SRS-D01.02 FR-06c）
INSERT INTO bas_task_dependency (tenant_id, task_name, after_task_name, plan_date_align, auto_trigger, status) VALUES
(1, 'finance.settle_daily_check', 'stock.daily_snapshot',    1, 1, 1),
(1, 'bi.wide_table_refresh',      'finance.settle_daily_check', 1, 1, 1);

-- 9.4 PIPL 分级字典（L0/L1/L2/L2P/L3）+ 脱敏规则 + 留存策略样例 + 敏感字段登记样例
INSERT INTO bas_pipl_policy (tenant_id, policy_type, policy_code, policy_name, entity_name, field_name, level, mask_rule_code, plain_access_mode, blind_index_flag, retention_json, necessity, policy_version, reviewer, status) VALUES
(1, 'level_dict', 'L0',  '公开级',       '', '', 'L0',  '', '',            0, NULL, '', 1, '', 1),
(1, 'level_dict', 'L1',  '内部级',       '', '', 'L1',  '', '',            0, NULL, '', 1, '', 1),
(1, 'level_dict', 'L2',  '敏感级',       '', '', 'L2',  '', 'perm_point',  0, NULL, '', 1, '', 1),
(1, 'level_dict', 'L2P', '平台密文级',   '', '', 'L2P', '', 'forbidden',   0, NULL, '', 1, '', 1),
(1, 'level_dict', 'L3',  '高敏级',       '', '', 'L3',  '', 'service_whitelist', 0, NULL, '', 1, '', 1),
(1, 'mask_rule', 'phone',     '手机号脱敏',   '', '', '', '', '', 0, NULL, '', 1, '', 1),
(1, 'mask_rule', 'name',      '姓名脱敏',     '', '', '', '', '', 0, NULL, '', 1, '', 1),
(1, 'mask_rule', 'address',   '地址脱敏',     '', '', '', '', '', 0, NULL, '', 1, '', 1),
(1, 'mask_rule', 'id_card',   '身份证脱敏',   '', '', '', '', '', 0, NULL, '', 1, '', 1),
(1, 'mask_rule', 'bank_card', '银行卡脱敏',   '', '', '', '', '', 0, NULL, '', 1, '', 1),
(1, 'mask_rule', 'token',     '凭证脱敏',     '', '', '', '', '', 0, NULL, '', 1, '', 1),
(1, 'mask_rule', 'open_id',   '开放标识脱敏', '', '', '', '', '', 0, NULL, '', 1, '', 1),
(1, 'retention', 'ord_order',          '订单履约数据留存',   'ord_order',      '', '', '', '', 0, '{"online_years":3,"archive":true,"anonymize_after_months":0,"necessity":"contract"}', 'contract', 1, 'compliance', 1),
(1, 'retention', 'cross_border_declare','跨境申报要素留存',  'ord_declare',    '', '', '', '', 0, '{"plaintext_days":90,"cipher_years":3,"anonymize_after_months":3,"necessity":"legal"}', 'legal', 1, 'compliance', 1),
(1, 'retention', 'audit_log',          '审计日志留存',       'aud_operation_log', '', '', '', '', 0, '{"online_months":12,"archive_years":5,"anonymize_after_months":0,"necessity":"legal"}', 'legal', 1, 'compliance', 1),
(1, 'field_registry', 'receiver', '订单收货人手机', 'ord_order', 'receiver_mobile', 'L2', 'phone', 'perm_point', 1, NULL, 'contract', 1, 'compliance', 1),
(1, 'field_registry', 'receiver', '订单收货人姓名', 'ord_order', 'receiver_name',   'L2', 'name',  'perm_point', 0, NULL, 'contract', 1, 'compliance', 1),
(1, 'field_registry', 'receiver', '订单收货地址',   'ord_order', 'receiver_address','L2', 'address','perm_point',0, NULL, 'contract', 1, 'compliance', 1),
(1, 'field_registry', 'decl_id',  '申报身份证号',   'ord_declare', 'id_card_no',    'L3', 'id_card','service_whitelist', 1, NULL, 'legal', 1, 'compliance', 1),
(1, 'field_registry', 'shop_tok', '店铺授权令牌',   'gw_shop_auth', 'access_token', 'L3', 'token', 'service_whitelist', 0, NULL, 'contract', 1, 'compliance', 1),
(1, 'field_registry', 'acct_mob', '账户手机号',     'org_account', 'mobile_enc',    'L2', 'phone', 'perm_point', 1, NULL, 'contract', 1, 'compliance', 1);

-- 9.5 插件/策略注册表样例（D03.02 审单五段链节选 + D03.04 拆单策略节选；全量随各域启动注册同步）
INSERT INTO bas_plugin_registry (tenant_id, registry_type, chain_id, registry_id, item_name, item_desc, phase, phase_order, short_circuit, error_policy, timeout_ms, class_ref, item_version, enabled) VALUES
(1, 'plugin',   'order.audit', '', 'blacklist_check',   '黑名单校验',         'ADMIT',     10, 1, 'dual',   500, 'App\\Order\\Plugin\\BlacklistCheck',   'v1', 1),
(1, 'plugin',   'order.audit', '', 'address_risk_check','地址风险校验',       'ADMIT',     20, 1, 'dual',   500, 'App\\Order\\Plugin\\AddressRiskCheck', 'v1', 1),
(1, 'plugin',   'order.audit', '', 'warehouse_route',   '配货分仓路由',       'WAREHOUSE', 10, 1, 'strict', 800, 'App\\Order\\Plugin\\WarehouseRoute',   'v1', 1),
(1, 'plugin',   'order.audit', '', 'stock_reserve',     '库存预占',           'STOCK',     10, 1, 'strict', 1000,'App\\Order\\Plugin\\StockReserve',     'v1', 1),
(1, 'plugin',   'order.audit', '', 'logistics_route',   '物流分单路由',       'LOGISTICS', 10, 1, 'dual',   500, 'App\\Order\\Plugin\\LogisticsRoute',   'v1', 1),
(1, 'plugin',   'order.audit', '', 'final_check',       '终审校验(全收集)',   'CHECK',     10, 0, 'strict', 500, 'App\\Order\\Plugin\\FinalCheck',       'v1', 1),
(1, 'plugin',   'aftersale.audit', '', 'buyer_risk',    '买家风控(短路)',     'RISK',      10, 1, 'strict', 500, 'App\\Aftersale\\Plugin\\BuyerRisk',    'v1', 1),
(1, 'strategy', '', 'split', 'owner',        '按货主拆单',     '', 0, 1, 'strict', 500, 'App\\Order\\Split\\OwnerStrategy',        'v1', 1),
(1, 'strategy', '', 'split', 'warehouse',    '按仓拆单',       '', 0, 1, 'strict', 500, 'App\\Order\\Split\\WarehouseStrategy',    'v1', 1),
(1, 'strategy', '', 'split', 'logistics',    '按物流拆单',     '', 0, 1, 'strict', 500, 'App\\Order\\Split\\LogisticsStrategy',    'v1', 1),
(1, 'strategy', '', 'split', 'presale',      '预售单独拆',     '', 0, 1, 'strict', 500, 'App\\Order\\Split\\PresaleStrategy',      'v1', 1);

-- 9.6 规则字典样例（操作符按值类型分组预置 + 审单原因码样例；全量随各域注册）
INSERT INTO bas_rule_dict (tenant_id, dict_category, dict_type, item_code, item_name, value_type, value_source, level, ext_json, preset_flag, sort_no, status) VALUES
(1, 'dim',  'order.audit', 'order.amount_paid',      '客户实付金额', 'decimal', '',                            '', NULL, 1, 10, 1),
(1, 'dim',  'order.audit', 'shop_id',                '店铺',         'ref',     'ref:gw_shop',                 '', NULL, 1, 20, 1),
(1, 'dim',  'order.audit', 'order.receiver_province','收货省份',     'string',  'free',                        '', NULL, 1, 30, 1),
(1, 'dim',  'order.audit', 'order.items.category',   '商品类目',     'enum',    'enum:material_category',      '', NULL, 1, 40, 1),
(1, 'enum', 'audit_reason_code', 'BLACKLIST_HIT',    '黑名单命中',   'string',  '', 'BLOCK', '{"default_route":"manual","audit_group":"risk"}', 1, 10, 1),
(1, 'enum', 'audit_reason_code', 'STOCK_SHORTAGE',   '库存不足',     'string',  '', 'BLOCK', '{"default_route":"shortage_hold"}',               1, 20, 1),
(1, 'enum', 'audit_reason_code', 'AMOUNT_OVER',      '大额转人工',   'string',  '', 'WARN',  '{"default_route":"manual","audit_group":"supervisor"}', 1, 30, 1),
(1, 'enum', 'decision_code',     'AUTO_PASS',        '自动通过',     'string',  '', '',      NULL, 1, 10, 1),
(1, 'enum', 'decision_code',     'TO_MANUAL',        '转人工',       'string',  '', '',      NULL, 1, 20, 1),
(1, 'enum', 'decision_code',     'HOLD',             '挂起',         'string',  '', '',      NULL, 1, 30, 1);

-- 9.7 缺省兜底规则（D03.02/D05.05：无命中转人工，不可删不可停）
INSERT INTO bas_rule (tenant_id, rule_name, rule_group, weight, scope_json, actions_json, defaulted, status) VALUES
(1, '审单缺省转人工', 'order.audit',     0, '{"scope_type":"global"}', '{"decision":"TO_MANUAL"}', 1, 1),
(1, '售后缺省转人工', 'aftersale.audit', 0, '{"scope_type":"global"}', '{"decision":"TO_MANUAL"}', 1, 1);

-- 9.8 发号器域码初始行
INSERT INTO bas_seq (tenant_id, seq_domain, seq_date, current_value, step_size, max_value, remark) VALUES
(1, 'AP',  CURDATE(), 0, 100, 99999999, '审批单号(D10.05)'),
(1, 'ST',  CURDATE(), 0, 100, 99999999, '店铺换货主申请单(D10.01)'),
(1, 'DL',  CURDATE(), 0, 100, 99999999, '死信编号(D01.01)'),
(1, 'SE',  CURDATE(), 0, 100, 99999999, '调度执行标识(D01.02)'),
(1, 'SB',  CURDATE(), 0, 100, 99999999, '沙箱试跑编号(D01.03)'),
(1, 'IM',  CURDATE(), 0, 100, 99999999, '导入任务号(D01.06)'),
(1, 'EX',  CURDATE(), 0, 100, 99999999, '导出任务号(D01.06)'),
(1, 'NT',  CURDATE(), 0, 100, 99999999, '通知消息编号(D01.07)'),
(1, 'CS',  CURDATE(), 0, 100, 99999999, 'PIPL授权记录编号(D01.05)'),
(1, 'DSR', CURDATE(), 0, 100, 99999999, '权利请求编号(D01.05)');

-- 9.9 通知模板与路由样例（D10.04 门户结算场景 + 告警兜底规则）
INSERT INTO bas_notify_template (tenant_id, template_code, template_name, domain_code, msg_class, channel_contents_json, variables_json, template_version, compliance_confirmed, owner_name, status) VALUES
(1, 'd08.settle.pending',   '结算单待品牌方确认', 'D08', 'external', '{"sms":"【凯淳】{owner_name}{period}结算单已生成,请登录门户确认。","email_html":"<p>结算单{settle_bn}待确认</p>","inbox":"结算单{settle_bn}待确认"}', '[{"name":"owner_name","type":"string","required":true},{"name":"period","type":"string","required":true},{"name":"settle_bn","type":"string","required":true}]', 1, 1, '财务值班', 1),
(1, 'd04.stock.red_alert',  '缺货红色预警',       'D04', 'notify',   '{"wecom_card":{"title":"红色断货预警","fields":["owner_name","sku_count"]},"sms":"【凯淳】货主{owner_name}断货红色预警{sku_count}个SKU","inbox":"断货红色预警"}', '[{"name":"owner_name","type":"string","required":true},{"name":"sku_count","type":"int","required":true}]', 1, 1, '库存值班', 1),
(1, 'base.task.failed',     '调度任务失败告警',   'D01', 'alert',    '{"wecom_card":{"title":"任务失败:{task_name}","fields":["plan_time","error_digest"]},"voice":"调度任务{task_name}失败"}', '[{"name":"task_name","type":"string","required":true},{"name":"plan_time","type":"string","required":true},{"name":"error_digest","type":"string","required":true,"sensitive":true}]', 1, 0, '底座值班', 1);

INSERT INTO bas_notify_route (tenant_id, route_name, event_pattern, condition_json, receiver_resolvers_json, channels_json, level_override, silence_json, escalate_json, denoise_flag, priority, default_flag, status) VALUES
(1, '结算待确认->品牌方财务', 'finance.settle.drafted', NULL, '[{"type":"owner_manager","params":{"role":"brand_finance"}}]', '["sms","email","inbox"]', '', NULL, NULL, 0, 10, 0, 1),
(1, '红色缺货预警->货主负责人+运营', 'stock.shortage', '{"level":"red"}', '[{"type":"owner_manager","params":{}},{"type":"role","params":{"role_code":"stock_keeper"}}]', '["wecom","sms","inbox"]', 'P1', '{"silence_minutes":30,"escalate_count":10}', NULL, 0, 10, 0, 1),
(1, 'P0告警->值班+升级主管', 'mq.*', '{"level":"P0"}', '[{"type":"duty","params":{"role_code":"ops_duty"}},{"type":"org_manager_up","params":{"levels":1}}]', '["voice","wecom"]', 'P0', '{"silence_minutes":10,"escalate_count":5}', '{"ack_timeout_minutes":30,"max_level":3}', 0, 100, 0, 1),
(1, '域缺省值班兜底', '*', NULL, '[{"type":"duty","params":{"role_code":"domain_duty"}}]', '["wecom","inbox"]', '', '{"silence_minutes":30,"escalate_count":10}', NULL, 0, 0, 1, 1);

-- ============================================================================
-- 脚本结束 · 共 29 张表（24 核心 + 5 辅助）+ 初始字典数据
-- 自查: 括号/逗号/分号配对、COMMENT 内无未转义引号(->代替→,<=代替≤)、
--       JSON 默认值均为 NULL 或显式提供、避开 MySQL8 保留字
--       (groups/rank/system/condition/read 未用作表名列名;
--        rule_group/thread_num/dim_condition 形态规避)
-- ============================================================================
