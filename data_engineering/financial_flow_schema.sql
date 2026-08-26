-- ============================================================================
-- 财务流水自动入账一期 · 数据中间池建表脚本
-- 文档版本：v0.3（补 dwd_flow_batch 批次统计回流四列 loaded/duplicated/failed/warned · 对齐 v_recon_balance 对账口径）
-- 目标库  ：MySQL 8.0（决策 D7 = A 轻量关系库；可平替 PostgreSQL，见文末说明）
-- 设计原则：可扩展分层 ——
--   ods  原始层（原样归档，非必需字段留痕）
--   dwd  标准化中间层（统一流水契约最小结构化，决策 D5 = B）
--   dim  维度层（银行 / 账户 / 校验规则字典）
--   biz  业务状态层（复核留痕 / 推送与凭证关联）
--   aud  审计层（操作日志，只追加 + 哈希链防篡改）
-- 说明    ：主表之间建立物理外键保证账务完整性；字段注释以「→ 表.列」标注逻辑关系
-- ============================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------------------------------------------------------
-- 一、维度层 dim
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS dim_bank (
  bank_id     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '银行主键',
  bank_code   VARCHAR(32)   NOT NULL               COMMENT '银行编码 CMB=招商 / CITIC=中信 / CITI=花旗(二期) / SUNRATE(二期)',
  bank_name   VARCHAR(128)  NOT NULL               COMMENT '银行名称',
  is_active   TINYINT(1)    NOT NULL DEFAULT 1     COMMENT '是否启用 1=是 0=否',
  created_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (bank_id),
  UNIQUE KEY uk_bank_code (bank_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='银行维度表';

CREATE TABLE IF NOT EXISTS dim_bank_account (
  account_id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '账户主键',
  bank_id          BIGINT UNSIGNED NOT NULL               COMMENT '→ dim_bank.bank_id',
  account_no       VARCHAR(64)   NOT NULL                 COMMENT '银行账号',
  account_name     VARCHAR(128)  NOT NULL                 COMMENT '账户户名',
  account_type     VARCHAR(32)   NULL                     COMMENT '账户类型（基本户/一般户，一期可空）',
  default_currency CHAR(3)       NOT NULL DEFAULT 'CNY'   COMMENT '默认币种 ISO4217',
  is_active        TINYINT(1)    NOT NULL DEFAULT 1       COMMENT '是否启用',
  created_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (account_id),
  UNIQUE KEY uk_account (bank_id, account_no),
  CONSTRAINT fk_account_bank FOREIGN KEY (bank_id) REFERENCES dim_bank (bank_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='银行账户维度表';

CREATE TABLE IF NOT EXISTS dim_validation_rule (
  rule_code      VARCHAR(32)  NOT NULL COMMENT '规则编码（R001 重复 / R002 负金额 / R003 缺字段 / R004 超阈值 / R005 币种非法 ...）',
  rule_name      VARCHAR(128) NOT NULL COMMENT '规则名称',
  rule_level     VARCHAR(8)   NOT NULL DEFAULT 'ERROR' COMMENT 'ERROR=硬校验拦截 / WARN=预警提示',
  is_enabled     TINYINT(1)   NOT NULL DEFAULT 1   COMMENT '是否启用',
  threshold_json JSON         NULL                  COMMENT '可配置阈值参数（如单笔金额上限），规则钩子扩展点',
  description    VARCHAR(512) NULL                  COMMENT '规则说明',
  created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (rule_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='校验规则字典（可扩展新增规则）';

-- ----------------------------------------------------------------------------
-- 二、原始层 ods（原样归档 + 溯源）
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ods_bank_raw_flow (
  raw_id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '原始记录主键',
  batch_id         BIGINT UNSIGNED NOT NULL               COMMENT '→ dwd_flow_batch.batch_id',
  record_id        BIGINT UNSIGNED NULL                   COMMENT '标准化落库后回填 → dwd_trans_flow.record_id',
  source_file_name VARCHAR(255)    NULL                   COMMENT '来源文件名（FILE 导入时）',
  source_uri       VARCHAR(512)    NULL                   COMMENT '来源标识（文件路径 / 接口 URI）',
  raw_content      JSON            NOT NULL               COMMENT '原始流水原样归档（含非必需字段，JSON）',
  raw_hash         CHAR(64)        NULL                   COMMENT 'raw_content 的 SHA256，用于幂等与防篡改',
  created_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (raw_id),
  KEY idx_raw_batch (batch_id),
  KEY idx_raw_hash (raw_hash),
  KEY idx_raw_record (record_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='银行原始流水归档（ODS 原始层）';

-- ----------------------------------------------------------------------------
-- 三、标准化中间层 dwd（统一流水契约）
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS dwd_flow_batch (
  batch_id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '批次主键（每次采集生成的唯一批号）',
  batch_no         VARCHAR(64)   NOT NULL                 COMMENT '业务批次号（人类可读，如 B20260824-0001）',
  source_type      VARCHAR(16)   NOT NULL                 COMMENT '数据源类型 MOCK / FILE / API',
  bank_id          BIGINT UNSIGNED NOT NULL               COMMENT '→ dim_bank.bank_id',
  account_id       BIGINT UNSIGNED NOT NULL               COMMENT '→ dim_bank_account.account_id',
  source_ref       VARCHAR(512)  NULL                     COMMENT '来源引用（文件路径 / 接口标识 / 文件名）',
  contract_version VARCHAR(16)   NOT NULL DEFAULT 'v1'    COMMENT '流水契约版本（契约版本化，向后兼容）',
  flow_date_start  DATE          NULL                     COMMENT '本批流水日期起始',
  flow_date_end    DATE          NULL                     COMMENT '本批流水日期截止',
  total_count      INT UNSIGNED  NOT NULL DEFAULT 0       COMMENT '采集适配层上报总笔数（导入/预期口径）',
  total_amount     DECIMAL(20,2) NOT NULL DEFAULT 0       COMMENT '采集适配层上报总金额（导入/预期口径）',
  loaded_count     INT UNSIGNED  NOT NULL DEFAULT 0       COMMENT '实际落库笔数（dwd_trans_flow 非重复行）',
  duplicated_count INT UNSIGNED  NOT NULL DEFAULT 0       COMMENT '重复笔数（R001）',
  failed_count     INT UNSIGNED  NOT NULL DEFAULT 0       COMMENT '校验失败笔数（R002/R003/R005）',
  warned_count     INT UNSIGNED  NOT NULL DEFAULT 0       COMMENT '校验警告笔数（R004 超阈值 / R006 批次勾稽）',
  status           VARCHAR(16)   NOT NULL DEFAULT 'IMPORTING' COMMENT '批次状态 IMPORTING/LOADED/VALIDATED/RECONCILED',
  imported_by      VARCHAR(64)   NULL                     COMMENT '导入人',
  imported_at      DATETIME      NULL                     COMMENT '导入时间',
  created_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (batch_id),
  UNIQUE KEY uk_batch_no (batch_no),
  KEY idx_batch_account (bank_id, account_id),
  CONSTRAINT fk_batch_bank FOREIGN KEY (bank_id) REFERENCES dim_bank (bank_id),
  CONSTRAINT fk_batch_account FOREIGN KEY (account_id) REFERENCES dim_bank_account (account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='采集批次表（批次级溯源 + 对账口径）';

CREATE TABLE IF NOT EXISTS dwd_trans_flow (
  record_id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '记录级唯一 ID（逐条定位溯源）',
  dedup_key           CHAR(64)      NOT NULL                COMMENT '幂等去重键 = SHA256(bank_id|account_id|txn_no|txn_date|amount|dc_flag)',
  batch_id            BIGINT UNSIGNED NOT NULL               COMMENT '→ dwd_flow_batch.batch_id',
  bank_id             BIGINT UNSIGNED NOT NULL               COMMENT '→ dim_bank.bank_id',
  account_id          BIGINT UNSIGNED NOT NULL               COMMENT '→ dim_bank_account.account_id',
  raw_id              BIGINT UNSIGNED NULL                   COMMENT '→ ods_bank_raw_flow.raw_id（回链原始归档）',
  contract_version    VARCHAR(16)   NOT NULL DEFAULT 'v1'    COMMENT '契约版本',
  -- 统一流水契约核心八字段 --
  txn_no              VARCHAR(64)   NOT NULL                 COMMENT '银行唯一流水号',
  txn_date            DATE          NOT NULL                 COMMENT '交易日期',
  txn_time            TIME          NULL                     COMMENT '交易时间',
  currency            CHAR(3)       NOT NULL DEFAULT 'CNY'   COMMENT '币种 ISO4217',
  amount              DECIMAL(20,2) NOT NULL                 COMMENT '金额（恒正，方向见 dc_flag）',
  dc_flag             CHAR(1)       NOT NULL                 COMMENT '借贷方向 D=借方/支出 C=贷方/收入',
  counterparty_name   VARCHAR(255)  NULL                     COMMENT '对方户名',
  counterparty_account VARCHAR(64)  NULL                     COMMENT '对方账号',
  summary             VARCHAR(512)  NULL                     COMMENT '摘要',
  -- 状态与校验 --
  process_status      VARCHAR(32)   NOT NULL DEFAULT 'LOADED' COMMENT '业务阶段 LOADED/VALIDATING/REVIEW_READY/REVIEW_PASSED/PUSHED/KINGDEE_POSTED/REJECTED',
  validation_status   VARCHAR(16)   NOT NULL DEFAULT 'PENDING' COMMENT '校验结论 PENDING/PASS/WARN/FAIL',
  exception_type      VARCHAR(64)   NULL                     COMMENT '异常类型摘要（对应维表 rule_code，逗号分隔）',
  -- 扩展字段 --
  ext_json            JSON          NULL                     COMMENT '预留扩展字段（未来智能匹配/发票联动等不重建表）',
  created_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (record_id),
  UNIQUE KEY uk_dedup (dedup_key),
  KEY idx_flow_batch (batch_id),
  KEY idx_flow_account_date (bank_id, account_id, txn_date),
  KEY idx_flow_txn_no (txn_no),
  KEY idx_flow_process (process_status),
  CONSTRAINT fk_flow_batch FOREIGN KEY (batch_id) REFERENCES dwd_flow_batch (batch_id),
  CONSTRAINT fk_flow_bank FOREIGN KEY (bank_id) REFERENCES dim_bank (bank_id),
  CONSTRAINT fk_flow_account FOREIGN KEY (account_id) REFERENCES dim_bank_account (account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='统一流水结构化中间表（DWD 核心，决策 D5=B）';

CREATE TABLE IF NOT EXISTS dwd_flow_validation (
  validation_id  BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '校验记录主键',
  record_id      BIGINT UNSIGNED NOT NULL               COMMENT '→ dwd_trans_flow.record_id',
  batch_id       BIGINT UNSIGNED NOT NULL               COMMENT '→ dwd_flow_batch.batch_id',
  rule_code      VARCHAR(32)   NOT NULL                 COMMENT '→ dim_validation_rule.rule_code',
  rule_result    VARCHAR(8)    NOT NULL                 COMMENT 'PASS / FAIL / WARN',
  error_detail   VARCHAR(1024) NULL                     COMMENT '错误详情（缺哪些字段/重复对哪个键/阈值多少）',
  created_at     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (validation_id),
  KEY idx_val_record (record_id),
  KEY idx_val_batch_rule (batch_id, rule_code),
  CONSTRAINT fk_val_record FOREIGN KEY (record_id) REFERENCES dwd_trans_flow (record_id),
  CONSTRAINT fk_val_rule FOREIGN KEY (rule_code) REFERENCES dim_validation_rule (rule_code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='流水校验结果留痕表（逐规则审计）';

-- ----------------------------------------------------------------------------
-- 四、业务状态层 biz（复核留痕 / 推送与凭证关联）
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS biz_flow_review (
  review_id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '复核记录主键',
  record_id       BIGINT UNSIGNED NOT NULL               COMMENT '→ dwd_trans_flow.record_id（同一流水可多次复审，保留历史）',
  batch_id        BIGINT UNSIGNED NOT NULL               COMMENT '→ dwd_flow_batch.batch_id',
  review_result   VARCHAR(16)   NOT NULL                 COMMENT 'PASS 通过 / REJECT 驳回 / ADJUST 调整',
  reviewer        VARCHAR(64)   NOT NULL                 COMMENT '复核人',
  review_time     DATETIME      NOT NULL                 COMMENT '复核时间',
  matched_subject VARCHAR(255)  NULL                     COMMENT '人工匹配科目/往来（一期低置信流水由财务填入）',
  comment         VARCHAR(512)  NULL                     COMMENT '复核备注',
  created_at      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (review_id),
  KEY idx_review_record (record_id),
  KEY idx_review_batch (batch_id),
  CONSTRAINT fk_review_record FOREIGN KEY (record_id) REFERENCES dwd_trans_flow (record_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='人工复核留痕表';

CREATE TABLE IF NOT EXISTS biz_push_record (
  push_id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '推送记录主键',
  record_id        BIGINT UNSIGNED NOT NULL               COMMENT '→ dwd_trans_flow.record_id',
  batch_id         BIGINT UNSIGNED NOT NULL               COMMENT '→ dwd_flow_batch.batch_id',
  push_status      VARCHAR(16)   NOT NULL DEFAULT 'PENDING' COMMENT 'PENDING/SUCCESS/FAILED/UNCERTAIN（远端结果待查）',
  voucher_no       VARCHAR(64)   NULL                     COMMENT '金蝶凭证号（账→单、单→账 双向绑定）',
  kingdee_doc_no   VARCHAR(64)   NULL                     COMMENT '金蝶单据号',
  pushed_by        VARCHAR(64)   NULL                     COMMENT '推送人',
  pushed_at        DATETIME      NULL                     COMMENT '推送时间',
  retry_count      INT UNSIGNED  NOT NULL DEFAULT 0       COMMENT '重试次数',
  error_msg        VARCHAR(1024) NULL                     COMMENT '推送失败原因',
  response_payload JSON          NULL                     COMMENT '金蝶响应原文留痕',
  created_at       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (push_id),
  UNIQUE KEY uk_push_record (record_id),
  KEY idx_push_voucher (voucher_no),
  KEY idx_push_batch (batch_id),
  KEY idx_push_status (push_status),
  CONSTRAINT fk_push_record FOREIGN KEY (record_id) REFERENCES dwd_trans_flow (record_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='金蝶推送与凭证关联表（凭证号 ↔ 流水号双向绑定）';

-- ----------------------------------------------------------------------------
-- 五、审计层 aud（操作日志，只追加 + 哈希链防篡改）
-- ----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS aud_audit_log (
  log_id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '日志主键',
  actor       VARCHAR(64)   NOT NULL                 COMMENT '操作人',
  action      VARCHAR(32)   NOT NULL                 COMMENT '动作 LOGIN/IMPORT/VALIDATE/REVIEW/PUSH/MODIFY/REJECT ...',
  entity_type VARCHAR(32)   NOT NULL                 COMMENT '对象类型 batch/record/review/push ...',
  entity_id   VARCHAR(64)   NOT NULL                 COMMENT '对象 ID',
  detail      JSON          NULL                     COMMENT '操作详情',
  ip_address  VARCHAR(64)   NULL                     COMMENT '来源 IP',
  row_hash    CHAR(64)      NOT NULL                 COMMENT '本行 SHA256（含 prev_hash），哈希链防篡改',
  prev_hash   CHAR(64)      NULL                     COMMENT '前一行 row_hash，构成只追加链',
  created_at  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (log_id),
  KEY idx_audit_entity (entity_type, entity_id),
  KEY idx_audit_actor (actor, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='操作审计日志（只追加、防篡改，合规审计证据）';

-- ============================================================================
-- 六、可视化取数视图（MVP 四看板，取数与展示解耦，统一走标准数据模型）
-- ============================================================================

-- 6.1 流水总览：收/支金额、笔数、趋势（按账户/日聚合）
CREATE OR REPLACE VIEW v_flow_overview AS
SELECT
  t.txn_date,
  t.bank_id,
  b.bank_name,
  t.account_id,
  a.account_name,
  t.dc_flag,
  COUNT(*)                            AS txn_cnt,
  ROUND(SUM(t.amount), 2)             AS total_amount
FROM dwd_trans_flow t
LEFT JOIN dim_bank b        ON b.bank_id = t.bank_id
LEFT JOIN dim_bank_account a ON a.account_id = t.account_id
GROUP BY t.txn_date, t.bank_id, b.bank_name, t.account_id, a.account_name, t.dc_flag;

-- 6.2 银行分布：各银行/账户流水占比
CREATE OR REPLACE VIEW v_bank_distribution AS
SELECT
  b.bank_id,
  b.bank_name,
  a.account_id,
  a.account_name,
  COUNT(*)                                                              AS txn_cnt,
  ROUND(SUM(CASE WHEN t.dc_flag = 'C' THEN t.amount ELSE 0 END), 2)     AS credit_amount,
  ROUND(SUM(CASE WHEN t.dc_flag = 'D' THEN t.amount ELSE 0 END), 2)     AS debit_amount
FROM dwd_trans_flow t
JOIN dim_bank b        ON b.bank_id = t.bank_id
JOIN dim_bank_account a ON a.account_id = t.account_id
GROUP BY b.bank_id, b.bank_name, a.account_id, a.account_name;

-- 6.3 异常预警：超阈值、重复、负金额、缺字段（采集校验结果）
CREATE OR REPLACE VIEW v_exception_alert AS
SELECT
  t.record_id,
  t.batch_id,
  t.bank_id,
  b.bank_name,
  t.account_id,
  a.account_name,
  t.txn_no,
  t.txn_date,
  t.amount,
  t.dc_flag,
  t.counterparty_name,
  t.summary,
  v.rule_code,
  v.rule_result,
  v.error_detail,
  v.created_at                        AS validated_at
FROM dwd_flow_validation v
JOIN dwd_trans_flow t        ON t.record_id = v.record_id
LEFT JOIN dim_bank b          ON b.bank_id = t.bank_id
LEFT JOIN dim_bank_account a  ON a.account_id = t.account_id
WHERE v.rule_result IN ('FAIL', 'WARN');

-- 6.4 对账钩稽：导入(预期) vs 实际落库 勾稽差异（批次级统计回流，读批次统计列）
CREATE OR REPLACE VIEW v_recon_balance AS
SELECT
  fb.batch_id,
  fb.batch_no,
  fb.bank_id,
  b.bank_name,
  fb.account_id,
  a.account_name,
  fb.source_type,
  fb.source_ref,
  fb.contract_version,
  fb.total_count                                   AS expected_count,
  fb.total_amount                                  AS expected_amount,
  fb.loaded_count                                  AS loaded_count,
  fb.duplicated_count                              AS duplicated_count,
  fb.failed_count                                  AS failed_count,
  fb.warned_count                                  AS warned_count,
  COALESCE(t.loaded_amount, 0)                     AS loaded_amount,
  (fb.total_count - fb.loaded_count)               AS count_diff,
  (fb.total_amount - COALESCE(t.loaded_amount, 0)) AS amount_diff
FROM dwd_flow_batch fb
LEFT JOIN dim_bank b        ON b.bank_id = fb.bank_id
LEFT JOIN dim_bank_account a ON a.account_id = fb.account_id
LEFT JOIN (
  SELECT batch_id, ROUND(SUM(amount), 2) AS loaded_amount
  FROM dwd_trans_flow
  GROUP BY batch_id
) t ON t.batch_id = fb.batch_id;

-- ============================================================================
-- 七、种子数据
-- ============================================================================

INSERT INTO dim_bank (bank_code, bank_name) VALUES
  ('CMB',   '招商银行'),
  ('CITIC', '中信银行')
ON DUPLICATE KEY UPDATE bank_name = VALUES(bank_name);

INSERT INTO dim_validation_rule (rule_code, rule_name, rule_level, is_enabled, description) VALUES
  ('R001', '重复流水',       'ERROR', 1, '同银行同账号同流水号同日期同金额重复导入'),
  ('R002', '负金额/方向非法', 'ERROR', 1, '金额为负或 dc_flag 不在 D/C 取值'),
  ('R003', '必填字段缺失',   'ERROR', 1, '契约核心字段（日期/金额/方向/对方户名/流水号）缺失'),
  ('R004', '单笔金额超阈值', 'WARN',  1, '单笔金额超过可配置阈值，需人工复核'),
  ('R005', '币种非法',       'ERROR', 1, '币种不在 ISO4217 合法取值')
ON DUPLICATE KEY UPDATE rule_name = VALUES(rule_name);

SET FOREIGN_KEY_CHECKS = 1;

-- ============================================================================
-- PostgreSQL 平替说明（D7 未绑定具体引擎时的可移植性）：
--   1) TINYINT(1)        → BOOLEAN
--   2) BIGINT UNSIGNED AUTO_INCREMENT → BIGSERIAL 或 BIGINT GENERATED ALWAYS AS IDENTITY
--   3) DATETIME          → TIMESTAMP
--   4) JSON              → JSONB
--   5) ENGINE/CHARSET 子句删除；utf8mb4 → 默认 UTF8
--   6) ON DUPLICATE KEY UPDATE → ON CONFLICT (…) DO UPDATE
-- ============================================================================
