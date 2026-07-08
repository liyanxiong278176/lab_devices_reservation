package com.lab.reservation.ai.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.lab.reservation.ai.config.AiProperties;
import com.lab.reservation.entity.AiConversation;
import com.lab.reservation.entity.AiMessage;
import com.lab.reservation.mapper.AiConversationMapper;
import com.lab.reservation.mapper.AiMessageMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * 对话会话 + 消息管理:CRUD + 90 天滚动清理 + 滑动窗口(给 ChatClient prompt 用)。
 *
 * <p>{@link #buildPrompt(Long, String)} 只把历史 user 消息重建为 Spring AI 的
 * {@link UserMessage} 注入 prompt;assistant 段暂不显式重建(后续 Phase
 * 可加 {@code MessageConverter});tool 段同理。这样做可以保持 prompt 体积
 * 由 {@link AiProperties#getContextWindowTurns()} 控制,token 不会爆。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ConversationService {

    private final AiConversationMapper convMapper;
    private final AiMessageMapper msgMapper;
    private final AiProperties props;

    /** 新建空会话(标题由前端在首条 user 消息上覆写)。 */
    public AiConversation create(Long userId) {
        AiConversation c = new AiConversation();
        c.setUserId(userId);
        c.setCreatedAt(LocalDateTime.now());
        c.setUpdatedAt(LocalDateTime.now());
        convMapper.insert(c);
        return c;
    }

    /** 查不到会话抛 {@code BusinessException(NOT_FOUND)};由 GlobalExceptionHandler 转 404。 */
    public AiConversation getOrThrow(Long convId) {
        AiConversation c = convMapper.selectById(convId);
        if (c == null) {
            throw new com.lab.reservation.exception.BusinessException(
                    com.lab.reservation.common.result.ResultCode.NOT_FOUND);
        }
        return c;
    }

    /** 追加一条消息,并刷新会话的 {@code updatedAt}。 */
    public void appendMessage(Long convId, String role, String content, String toolCallsJson, int tokenCount) {
        AiMessage m = new AiMessage();
        m.setConversationId(convId);
        m.setRole(role);
        m.setContent(content);
        m.setToolCalls(toolCallsJson);
        m.setTokenCount(tokenCount);
        m.setCreatedAt(LocalDateTime.now());
        msgMapper.insert(m);

        // 顺便刷 conv.updated_at
        AiConversation c = convMapper.selectById(convId);
        if (c != null) {
            c.setUpdatedAt(LocalDateTime.now());
            convMapper.updateById(c);
        }
    }

    /**
     * 滑动窗口:从最近 {@code contextWindowTurns * 2} 条消息中挑出所有 user 消息,
     * 按时间正序拼接,最后追加当前输入,组成 ChatClient 的 messages 列表。
     */
    public List<Message> buildPrompt(Long convId, String currentText) {
        int window = props.getContextWindowTurns();
        int fetch = Math.max(1, window * 2);
        List<AiMessage> recent = msgMapper.selectList(
                new QueryWrapper<AiMessage>()
                        .eq("conversation_id", convId)
                        .orderByDesc("created_at")
                        .last("LIMIT " + fetch)
        );
        Collections.reverse(recent); // 旧 → 新

        List<Message> out = new ArrayList<>();
        for (AiMessage m : recent) {
            if ("user".equals(m.getRole())) {
                out.add(new UserMessage(m.getContent() == null ? "" : m.getContent()));
            }
            // assistant/tool 暂不显式重建
        }
        out.add(new UserMessage(currentText));
        return out;
    }

    /**
     * 滚动清理:删掉 {@code updated_at < now - retentionDays} 的会话,级联删消息。
     *
     * @return 被删除的会话数
     */
    public int cleanupOld(int retentionDays) {
        LocalDateTime threshold = LocalDateTime.now().minusDays(retentionDays);
        List<AiConversation> oldConvs = convMapper.selectList(
                new QueryWrapper<AiConversation>().lt("updated_at", threshold)
        );
        if (oldConvs.isEmpty()) {
            return 0;
        }
        List<Long> convIds = oldConvs.stream().map(AiConversation::getId).toList();
        int messages = msgMapper.delete(new QueryWrapper<AiMessage>().in("conversation_id", convIds));
        int convs = convMapper.delete(new QueryWrapper<AiConversation>().in("id", convIds));
        log.info("AI cleanup: deleted {} conversations, {} messages older than {} days",
                convs, messages, retentionDays);
        return convs;
    }
}
