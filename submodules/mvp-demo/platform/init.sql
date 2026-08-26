-- 财务流水自动入账 · 一期 MVP 演示库表（简化版：支撑"采集→校验→复核→推送→溯源"可演示）
-- 结构示意：独立中间池 midvault

-- 1) 采集批次表：一次采集一个批次，支撑整批召回核对（溯源要素：来源标识/批次号）
CREATE TABLE IF NOT EXISTS batches (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  batch_id VARCHAR(64) NOT NULL UNIQUE,
  bank VARCHAR(32) NOT NULL,
  account VARCHAR(64) NOT NULL,
  source VARCHAR(16) NOT NULL,           -- bank-mock / file-import / api
  raw_count INT NOT NULL DEFAULT 0,
  valid_count INT NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 2) 流水明细表：记录级唯一 record_id，附带校验结果与来源（溯源要素：记录级 ID）
CREATE TABLE IF NOT EXISTS transactions (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  record_id VARCHAR(40) NOT NULL UNIQUE,
  batch_id VARCHAR(64) NOT NULL,
  bank VARCHAR(32) NOT NULL,
  account VARCHAR(64) NOT NULL,
  tran_date DATE NOT NULL,
  amount DECIMAL(14,2) NOT NULL,
  direction VARCHAR(8) NOT NULL,          -- in / out
  counterparty VARCHAR(128) NOT NULL,
  currency VARCHAR(8) NOT NULL,
  memo VARCHAR(255),
  unique_no VARCHAR(64) NOT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'collected', -- collected / valid / abnormal / reviewed / pushed
  check_result VARCHAR(255),              -- 校验通过提示 / 异常原因
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  KEY idx_batch (batch_id),
  KEY idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 3) 复核留痕表（溯源要素：复核人与复核时间）
CREATE TABLE IF NOT EXISTS review_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  batch_id VARCHAR(64) NOT NULL,
  record_id VARCHAR(40) NOT NULL,
  auditor VARCHAR(64) NOT NULL,
  action VARCHAR(16) NOT NULL,            -- pass / reject
  reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 4) 推送留痕表（溯源要素：金蝶凭证号与 record_id 双向绑定）
CREATE TABLE IF NOT EXISTS push_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  batch_id VARCHAR(64) NOT NULL,
  record_id VARCHAR(40) NOT NULL,
  voucher_no VARCHAR(64) NOT NULL,
  pushed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uk_record (record_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 5) 审计日志：独立、只追加（不提供 UPDATE/DELETE API），记录关键操作
CREATE TABLE IF NOT EXISTS audit_log (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  actor VARCHAR(64) NOT NULL,
  action VARCHAR(32) NOT NULL,
  detail TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;