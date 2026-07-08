package com.lab.reservation.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * AI 工具执行审计实体(确认/审计系统的持久层)。
 *
 * <p>状态机: {@code pending → confirmed → executed / cancelled / error / expired}。
 * 落库时机:
 * <ul>
 *   <li>工具被 LLM 选中且 {@code @ConfirmRequired} 命中 → {@code insert(status='pending')}</li>
 *   <li>用户在 WS 上 confirm/cancel → {@code update(status, userConfirmedAt)}</li>
 *   <li>实际执行完成 → {@code update(status, executedAt, result)} 或 {@code update(status, errorMessage)}</li>
 * </ul>
 *
 * <p>{@code arguments} / {@code result} 是 JSON 字符串,服务层手动序列化;
 * 这两张 JSON 列刻意不放 JacksonTypeHandler,因为前端只看 status / msg,
 * 详情走 {@code ai_message.content} 取。
 *
 * <p>索引 {@code idx_status_created} 给超时扫描器定位 {@code status='pending' AND created_at &lt; now - ttl}
 * 的过期任务。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Data
@TableName("ai_tool_execution")
public class AiToolExecution {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long conversationId;

    private Long messageId;

    private String toolName;

    /** JSON 字符串。 */
    private String arguments;

    /** JSON 字符串(执行完成或错误时回填)。 */
    private String result;

    /** pending / confirmed / executed / cancelled / error / expired */
    private String status;

    private LocalDateTime userConfirmedAt;

    private LocalDateTime executedAt;

    private String errorMessage;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;
}