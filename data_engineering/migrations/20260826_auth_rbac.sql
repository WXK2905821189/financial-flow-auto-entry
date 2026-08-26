-- 本地认证、五角色 RBAC、银行/账户数据范围与可撤销会话迁移。
-- 目标：MySQL 8.0 / InnoDB。执行前请备份；本脚本不会删除既有账号或业务流水。
-- 适用于新库和已由应用早期版本创建 sys_user 的库。

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS sys_user (
  user_id             BIGINT NOT NULL AUTO_INCREMENT,
  username            VARCHAR(64) NOT NULL,
  password_hash       VARCHAR(255) NOT NULL,
  display_name        VARCHAR(64) NOT NULL,
  role                VARCHAR(32) NOT NULL DEFAULT 'REVIEWER',
  is_active           TINYINT(1) NOT NULL DEFAULT 1,
  password_changed_at DATETIME NULL,
  disabled_at         DATETIME NULL,
  failed_login_count  INT NOT NULL DEFAULT 0,
  locked_until        DATETIME NULL,
  created_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id),
  UNIQUE KEY uk_sys_user_username (username),
  KEY idx_sys_user_active_role (is_active, role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='本地认证账号';

-- MySQL 8.0.29+ 支持 IF NOT EXISTS；旧库已具备的列会被安全跳过。
ALTER TABLE sys_user MODIFY COLUMN role VARCHAR(32) NOT NULL DEFAULT 'REVIEWER';
ALTER TABLE sys_user ADD COLUMN IF NOT EXISTS password_changed_at DATETIME NULL AFTER is_active;
ALTER TABLE sys_user ADD COLUMN IF NOT EXISTS disabled_at DATETIME NULL AFTER password_changed_at;
ALTER TABLE sys_user ADD COLUMN IF NOT EXISTS failed_login_count INT NOT NULL DEFAULT 0 AFTER disabled_at;
ALTER TABLE sys_user ADD COLUMN IF NOT EXISTS locked_until DATETIME NULL AFTER failed_login_count;
ALTER TABLE sys_user ADD COLUMN IF NOT EXISTS updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP AFTER created_at;

CREATE TABLE IF NOT EXISTS sys_role_permission (
  permission_id   BIGINT NOT NULL AUTO_INCREMENT,
  role            VARCHAR(32) NOT NULL,
  permission_code VARCHAR(64) NOT NULL,
  created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (permission_id),
  UNIQUE KEY uk_role_permission (role, permission_code),
  KEY idx_role_permission_role (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='固定角色权限矩阵';

CREATE TABLE IF NOT EXISTS sys_user_scope (
  scope_id    BIGINT NOT NULL AUTO_INCREMENT,
  user_id     BIGINT NOT NULL,
  bank_id     BIGINT UNSIGNED NULL,
  account_id  BIGINT UNSIGNED NULL,
  granted_by  VARCHAR(64) NULL,
  created_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (scope_id),
  UNIQUE KEY uk_user_scope (user_id, bank_id, account_id),
  KEY idx_user_scope_user (user_id),
  KEY idx_user_scope_bank (bank_id),
  KEY idx_user_scope_account (account_id),
  CONSTRAINT fk_user_scope_user FOREIGN KEY (user_id) REFERENCES sys_user (user_id),
  CONSTRAINT fk_user_scope_bank FOREIGN KEY (bank_id) REFERENCES dim_bank (bank_id),
  CONSTRAINT fk_user_scope_account FOREIGN KEY (account_id) REFERENCES dim_bank_account (account_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户银行和账户访问范围';

CREATE TABLE IF NOT EXISTS sys_user_session (
  session_id         VARCHAR(64) NOT NULL,
  user_id            BIGINT NOT NULL,
  refresh_token_hash CHAR(64) NOT NULL,
  is_active          TINYINT(1) NOT NULL DEFAULT 1,
  expires_at         DATETIME NOT NULL,
  created_ip         VARCHAR(64) NULL,
  last_seen_at       DATETIME NULL,
  revoked_at         DATETIME NULL,
  created_at         DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (session_id),
  KEY idx_user_session_user (user_id),
  KEY idx_user_session_active_expiry (is_active, expires_at),
  CONSTRAINT fk_user_session_user FOREIGN KEY (user_id) REFERENCES sys_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='轮换刷新会话，仅保存 refresh token 散列';

INSERT INTO sys_role_permission (role, permission_code) VALUES
  ('SYSTEM_ADMIN', 'settings:read'),
  ('SYSTEM_ADMIN', 'user:admin'),
  ('FINANCE_MANAGER', 'review:read'),
  ('FINANCE_MANAGER', 'review:write'),
  ('FINANCE_MANAGER', 'push:write'),
  ('FINANCE_MANAGER', 'dashboard:read'),
  ('FINANCE_MANAGER', 'trace:read'),
  ('REVIEWER', 'review:read'),
  ('REVIEWER', 'review:write'),
  ('REVIEWER', 'dashboard:read'),
  ('REVIEWER', 'trace:read'),
  ('INGEST_OPERATOR', 'ingest:write'),
  ('INGEST_OPERATOR', 'dashboard:read'),
  ('AUDITOR', 'review:read'),
  ('AUDITOR', 'dashboard:read'),
  ('AUDITOR', 'trace:read'),
  ('FINANCE_MANAGER', 'pii:read'),
  ('REVIEWER', 'pii:read')
ON DUPLICATE KEY UPDATE permission_code = VALUES(permission_code);

-- 清理早期版本给系统管理员/兼容 ADMIN 的业务权限，避免旧数据绕过新职责边界。
DELETE FROM sys_role_permission
WHERE role IN ('SYSTEM_ADMIN', 'ADMIN')
  AND permission_code NOT IN ('settings:read', 'user:admin');
