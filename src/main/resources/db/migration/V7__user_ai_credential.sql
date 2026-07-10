-- 每用户自带 LLM chat 配置(BYO-key)。api_key 只存 AES-GCM 密文。
-- user_id 唯一:一用户一套 chat 配置。
CREATE TABLE IF NOT EXISTS user_ai_credential (
  id              BIGINT       NOT NULL AUTO_INCREMENT,
  user_id         BIGINT       NOT NULL,
  provider        VARCHAR(32)  NOT NULL COMMENT 'deepseek/openai/siliconflow/custom',
  base_url        VARCHAR(255) NOT NULL,
  api_key_cipher  TEXT         NOT NULL COMMENT 'AES-GCM 密文(IV 前置),明文永不落库',
  model           VARCHAR(64)  NOT NULL,
  temperature     DOUBLE       NULL     COMMENT '可空,代码默认 0.3',
  validated       TINYINT      NOT NULL DEFAULT 1 COMMENT 'test-before-persist 决定恒为 1',
  created_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_user_ai_credential (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户 LLM 凭证(BYO-key)';
