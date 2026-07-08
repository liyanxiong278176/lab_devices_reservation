package com.lab.reservation.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.time.LocalDateTime;

/**
 * AI 助手会话实体。
 *
 * <p>每个用户每次开启一段对话生成一行;{@code title} 由前端首条 user 消息自动生成,
 * 服务层也可在后续汇总时改写。{@code updated_at} 由 MyBatis-Plus 的
 * {@link com.baomidou.mybatisplus.core.handlers.MetaObjectHandler MetaObjectHandler}
 * 在 insert/update 时自动填充。
 *
 * <p>索引 {@code idx_user_updated} 支持会话列表按 {@code user_id} 过滤后
 * 按最近活跃时间倒序展示。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Data
@TableName("ai_conversation")
public class AiConversation {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long userId;

    private String title;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}