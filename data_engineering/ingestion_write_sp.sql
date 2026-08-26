-- ============================================================================
-- 财务流水自动入账一期 · 批次落库 + 校验留痕（参考实现）
-- 目标库：MySQL 8.0（决策 D7）   版本：v0.1
-- 职责  ：把采集适配层（Mock/File/API）输出的「批次元数据 + 统一流水契约 JSON 数组」
--         落库 ods/dwd/dim/aud，并逐规则留痕。对应《一期分工表》数据工程师工作包 2「中台落库」。
-- 落库顺序（硬约束）：ods 原始归档 → dwd 标准化 → 回填 ods.record_id（双向溯源，避免循环 FK）
-- 规则引擎：以 dim_validation_rule 为字典；本参考落地确定性规则
--   R001 重复（dedup_key 唯一键命中） / R002 负金额·方向非法 / R003 必填缺失 / R005 币种非法
--   R004 超阈值 为配置型规则，经 threshold_json 在规则钩子扩展点实现（不写死阈值）
-- 说明  ：RUN 前先执行 financial_flow_schema.sql 建表；本脚本为参考实现，供全栈在服务层调用或参照移植
-- ============================================================================

DELIMITER $$

DROP PROCEDURE IF EXISTS sp_ingest_flow $$

CREATE PROCEDURE sp_ingest_flow(
  IN  p_batch_no         VARCHAR(64),
  IN  p_source_type      VARCHAR(16),      -- MOCK / FILE / API
  IN  p_bank_id          BIGINT UNSIGNED,
  IN  p_account_id       BIGINT UNSIGNED,
  IN  p_source_ref       VARCHAR(512),
  IN  p_contract_version VARCHAR(16),
  IN  p_flow_date_start  DATE,
  IN  p_flow_date_end    DATE,
  IN  p_imported_by      VARCHAR(64),
  IN  p_flows            JSON,
  OUT o_batch_id         BIGINT UNSIGNED,
  OUT o_received_count   INT,
  OUT o_loaded_count     INT,
  OUT o_duplicate_count  INT,
  OUT o_failed_count     INT,
  OUT o_warn_count       INT
)
BEGIN
  DECLARE v_txn_no    VARCHAR(64);
  DECLARE v_txn_date  DATE;
  DECLARE v_currency  CHAR(3);
  DECLARE v_amount    DECIMAL(20,2);
  DECLARE v_dc_flag   CHAR(1);
  DECLARE v_counterparty_name    VARCHAR(255);
  DECLARE v_counterparty_account VARCHAR(64);
  DECLARE v_summary   VARCHAR(512);
  DECLARE v_raw_obj   JSON;

  DECLARE v_raw_id       BIGINT UNSIGNED;
  DECLARE v_record_id    BIGINT UNSIGNED;
  DECLARE v_dedup_key    CHAR(64);
  DECLARE v_total_amount DECIMAL(20,2) DEFAULT 0;
  DECLARE v_exc          VARCHAR(255) DEFAULT '';
  DECLARE done           INT DEFAULT 0;

  DECLARE cur CURSOR FOR
    SELECT jt.txn_no, jt.txn_date, jt.currency, jt.amount, jt.dc_flag,
           jt.counterparty_name, jt.counterparty_account, jt.summary, jt.raw_obj
    FROM JSON_TABLE(@flows, '$[*]' COLUMNS (
      txn_no               VARCHAR(64)   PATH '$.txn_no',
      txn_date             DATE          PATH '$.txn_date',
      currency             CHAR(3)       PATH '$.currency',
      amount               DECIMAL(20,2) PATH '$.amount',
      dc_flag              CHAR(1)       PATH '$.dc_flag',
      counterparty_name    VARCHAR(255)  PATH '$.counterparty_name',
      counterparty_account VARCHAR(64)   PATH '$.counterparty_account',
      summary              VARCHAR(512)  PATH '$.summary',
      raw_obj              JSON          PATH '$'
    )) AS jt;

  DECLARE CONTINUE HANDLER FOR NOT FOUND SET done = 1;

  SET @flows = p_flows;
  SET o_received_count = 0;
  SET o_loaded_count   = 0;
  SET o_duplicate_count = 0;
  SET o_failed_count   = 0;
  SET o_warn_count     = 0;
  SET v_total_amount   = 0;

  -- 1) 建批次
  INSERT INTO dwd_flow_batch
    (batch_no, source_type, bank_id, account_id, source_ref, contract_version,
     flow_date_start, flow_date_end, status, imported_by, imported_at)
  VALUES
    (p_batch_no, p_source_type, p_bank_id, p_account_id, p_source_ref, p_contract_version,
     p_flow_date_start, p_flow_date_end, 'IMPORTING', p_imported_by, NOW());
  SET o_batch_id = LAST_INSERT_ID();

  OPEN cur;
  read_loop: LOOP
    FETCH cur INTO v_txn_no, v_txn_date, v_currency, v_amount, v_dc_flag,
                   v_counterparty_name, v_counterparty_account, v_summary, v_raw_obj;
    IF done = 1 THEN
      LEAVE read_loop;
    END IF;

    SET o_received_count = o_received_count + 1;
    SET v_total_amount   = v_total_amount + COALESCE(v_amount, 0);
    SET v_exc            = '';

    -- 2) 原始归档（原样 append-only，先落原始层）
    INSERT INTO ods_bank_raw_flow (batch_id, source_uri, raw_content, raw_hash)
    VALUES (o_batch_id, p_source_ref, v_raw_obj, SHA2(CAST(v_raw_obj AS CHAR), 256));
    SET v_raw_id = LAST_INSERT_ID();

    -- 3) 幂等去重：命中 dedup_key 即重复（R001）；用标量子查询避免触发 NOT FOUND 处理器
    SET v_dedup_key = SHA2(CONCAT_WS('|', p_bank_id, p_account_id, v_txn_no, v_txn_date, v_amount, v_dc_flag), 256);
    SET v_record_id = (SELECT record_id FROM dwd_trans_flow WHERE dedup_key = v_dedup_key LIMIT 1);

    IF v_record_id IS NOT NULL THEN
      INSERT INTO dwd_flow_validation (record_id, batch_id, rule_code, rule_result, error_detail)
      VALUES (v_record_id, o_batch_id, 'R001', 'FAIL', CONCAT('重复流水 dedup_key=', v_dedup_key));
      SET o_duplicate_count = o_duplicate_count + 1;
    ELSE
      -- 4) 标准化落库
      INSERT INTO dwd_trans_flow
        (dedup_key, batch_id, bank_id, account_id, raw_id, contract_version,
         txn_no, txn_date, currency, amount, dc_flag,
         counterparty_name, counterparty_account, summary, process_status, validation_status)
      VALUES
        (v_dedup_key, o_batch_id, p_bank_id, p_account_id, v_raw_id, p_contract_version,
         v_txn_no, v_txn_date, COALESCE(v_currency, 'CNY'), COALESCE(v_amount, 0), v_dc_flag,
         v_counterparty_name, v_counterparty_account, v_summary, 'VALIDATING', 'PENDING');
      SET v_record_id = LAST_INSERT_ID();

      -- 5) 回填 ods.record_id（双向溯源）
      UPDATE ods_bank_raw_flow SET record_id = v_record_id WHERE raw_id = v_raw_id;

      -- 6) 校验留痕（确定性规则）
      IF (v_amount IS NOT NULL AND v_amount < 0) OR (v_dc_flag IS NOT NULL AND v_dc_flag NOT IN ('D','C')) THEN
        INSERT INTO dwd_flow_validation (record_id, batch_id, rule_code, rule_result, error_detail)
        VALUES (v_record_id, o_batch_id, 'R002', 'FAIL', '金额为负或 dc_flag 非法');
        SET v_exc = 'R002';
      END IF;

      IF v_txn_no IS NULL OR CHAR_LENGTH(v_txn_no) = 0 OR v_txn_date IS NULL
         OR v_amount IS NULL OR v_dc_flag IS NULL OR v_counterparty_name IS NULL THEN
        INSERT INTO dwd_flow_validation (record_id, batch_id, rule_code, rule_result, error_detail)
        VALUES (v_record_id, o_batch_id, 'R003', 'FAIL', '必填字段缺失（流水号/日期/金额/方向/对方户名）');
        SET v_exc = IF(v_exc = '', 'R003', CONCAT(v_exc, ',R003'));
      END IF;

      IF v_currency IS NOT NULL AND CHAR_LENGTH(v_currency) <> 3 THEN
        INSERT INTO dwd_flow_validation (record_id, batch_id, rule_code, rule_result, error_detail)
        VALUES (v_record_id, o_batch_id, 'R005', 'FAIL', CONCAT('币种非法 ', v_currency));
        SET v_exc = IF(v_exc = '', 'R005', CONCAT(v_exc, ',R005'));
      END IF;

      -- 7) 回写校验结论与业务阶段（状态机为 provisional，见联调文档）
      IF v_exc <> '' THEN
        UPDATE dwd_trans_flow SET validation_status = 'FAIL', exception_type = v_exc, process_status = 'LOADED'
        WHERE record_id = v_record_id;
        SET o_failed_count = o_failed_count + 1;
      ELSE
        UPDATE dwd_trans_flow SET validation_status = 'PASS', process_status = 'REVIEW_READY'
        WHERE record_id = v_record_id;
      END IF;

      SET o_loaded_count = o_loaded_count + 1;
    END IF;
  END LOOP;
  CLOSE cur;

  -- 8) 回写批次汇总与状态（统计回流：loaded/duplicated/failed/warn 显性落库，对接 v_recon_balance）
  UPDATE dwd_flow_batch
     SET total_count      = o_received_count,
         total_amount     = v_total_amount,
         loaded_count     = o_loaded_count,
         duplicated_count = o_duplicate_count,
         failed_count     = o_failed_count,
         warned_count     = o_warn_count,
         status           = 'VALIDATED'
   WHERE batch_id = o_batch_id;

  -- 9) 审计留痕（哈希链）
  SET @prev_hash = (SELECT row_hash FROM aud_audit_log ORDER BY log_id DESC LIMIT 1);
  INSERT INTO aud_audit_log (actor, action, entity_type, entity_id, detail, row_hash, prev_hash)
  VALUES (
    p_imported_by, 'IMPORT', 'batch', CAST(o_batch_id AS CHAR),
    JSON_OBJECT('batch_no', p_batch_no, 'received', o_received_count, 'loaded', o_loaded_count,
                'duplicate', o_duplicate_count, 'failed', o_failed_count, 'warn', o_warn_count),
    SHA2(CONCAT_WS('|', COALESCE(@prev_hash, ''), p_imported_by, 'IMPORT', 'batch', o_batch_id, o_received_count), 256),
    @prev_hash
  );

END $$

DELIMITER ;

-- ============================================================================
-- 自测示例（联调时在目标库执行）
-- ============================================================================
-- CALL sp_ingest_flow(
--   'B20260824-0001', 'MOCK', 1, 1, 'mock://cmb/2026-08-24', 'v1',
--   '2026-08-24', '2026-08-24', 'system',
--   JSON_ARRAY(
--     JSON_OBJECT('txn_no','CMB202608240001','txn_date','2026-08-24','txn_time','10:23:45',
--                 'currency','CNY','amount',15000.00,'dc_flag','C',
--                 'counterparty_name','某某科技有限公司','counterparty_account','6222','summary','货款'),
--     JSON_OBJECT('txn_no','CMB202608240002','txn_date','2026-08-24','currency','CNY',
--                 'amount',-200.00,'dc_flag','D','counterparty_name','某供应商','summary','付款')
--   ),
--   @b,@r,@l,@d,@f,@w);
-- SELECT @b batch_id, @r received, @l loaded, @d duplicate, @f failed, @w warn;
-- ============================================================================