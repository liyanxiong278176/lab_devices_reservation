-- AI 助手数据层 — Task 4a
-- 4 张表:ai_conversation, ai_message, ai_tool_execution, ai_ws_frame
-- 90 天滚动清理策略(由 AiConversationCleanupScheduler 调度,见 Task 4b)

-- ai_conversation 对话会话(每个用户每次开启一条)
CREATE TABLE ai_conversation (
    id BIGINT NOT NULL AUTO_INCREMENT,
    user_id BIGINT NOT NULL,
    title VARCHAR(100),
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    KEY idx_user_updated (user_id, updated_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 助手会话';

-- ai_message 对话消息(user / assistant / tool)
CREATE TABLE ai_message (
    id BIGINT NOT NULL AUTO_INCREMENT,
    conversation_id BIGINT NOT NULL,
    role VARCHAR(20) NOT NULL COMMENT 'user / assistant / tool',
    content MEDIUMTEXT,
    tool_calls JSON COMMENT '工具调用 JSON: [{name, args, result}, ...]',
    token_count INT DEFAULT 0,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    KEY idx_conv_created (conversation_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 助手消息';

-- ai_tool_execution 工具执行审计(状态机:pending→confirmed→executed/cancelled/error/expired)
CREATE TABLE ai_tool_execution (
    id BIGINT NOT NULL AUTO_INCREMENT,
    conversation_id BIGINT NOT NULL,
    message_id BIGINT NOT NULL,
    tool_name VARCHAR(100) NOT NULL,
    arguments JSON NOT NULL,
    result JSON,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    user_confirmed_at DATETIME,
    executed_at DATETIME,
    error_message TEXT,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    KEY idx_conv (conversation_id),
    KEY idx_status_created (status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 工具执行审计';

-- ai_ws_frame WS 帧持久化(用于 resync replay)
CREATE TABLE ai_ws_frame (
    id BIGINT NOT NULL AUTO_INCREMENT,
    conversation_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    frame_seq BIGINT NOT NULL,
    frame_type VARCHAR(30) NOT NULL COMMENT 'delta / step_update / suggestions / assistant_done / confirmation_required / ...',
    payload JSON NOT NULL,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_conv_seq (conversation_id, frame_seq),
    KEY idx_user_created (user_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 助手 WS 帧日志';