package com.lab.reservation.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * AI 助手对话消息实体。
 *
 * <p>三种角色: {@code user} (用户输入) / {@code assistant} (LLM 回复) / {@code tool} (工具结果回填)。
 * {@code content} 在 DB 中是 MEDIUMTEXT(最大 16MB),可承载长 LLM 回复或工具返回的大段 JSON。
 *
 * <p>{@code toolCalls} 是 JSON 字符串(数组: {@code [{name, args, result}, ...]});
 * 服务层在读写时手动 JSON 序列化/反序列化。{@code tokenCount} 由上游调用方在落库前
 * 估算后写入,用于后续按会话统计消耗。
 *
 * <p>索引 {@code idx_conv_created} 支持按会话内消息顺序回放;本表无
 * {@code updated_at} 列,创建后不再变更。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Data
@TableName("ai_message")
public class AiMessage {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long conversationId;

    /** user / assistant / tool */
    private String role;

    private String content;

    /** JSON 字符串;由服务层 Jackson 序列化/反序列化。 */
    private String toolCalls;

    private Integer tokenCount;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;
}