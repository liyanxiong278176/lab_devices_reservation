package com.lab.reservation.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.lab.reservation.entity.AiConversation;
import org.apache.ibatis.annotations.Mapper;

/**
 * AI 会话 Mapper。
 *
 * <p>基础 CRUD 由 MyBatis-Plus {@link BaseMapper} 提供;按需扩展的自定义查询
 * (例如列表按 {@code user_id} + {@code updated_at} 倒序、单会话的 message 树等)
 * 在 Task 4b 的 Service 层补。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Mapper
public interface AiConversationMapper extends BaseMapper<AiConversation> {
}