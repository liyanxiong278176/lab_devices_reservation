package com.lab.reservation.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * AI 助手 WS 帧持久化实体(resync replay 用)。
 *
 * <p>每条从服务端发往客户端的 WS 帧(增量、步骤更新、确认请求、assistant_done 等)
 * 在 send 前先写一行,失败/丢包时客户端按 {@code frameSeq} 重放;
 * 唯一键 {@code uk_conv_seq} 保证同一会话内帧序号严格自增。
 *
 * <p>{@code payload} 是 JSON 字符串(整体帧体);
 * 服务层发送时同时调 STOMP 和 insert,失败通过事务保证 rollback(见 Task 4b)。
 *
 * <p>索引 {@code idx_user_created} 支持按用户清理过期帧日志。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Data
@TableName("ai_ws_frame")
public class AiWsFrame {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long conversationId;

    private Long userId;

    private Long frameSeq;

    /** delta / step_update / suggestions / assistant_done / confirmation_required / ... */
    private String frameType;

    /** JSON 字符串。 */
    private String payload;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;
}