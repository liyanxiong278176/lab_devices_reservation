package com.lab.reservation.ai.task;

import com.lab.reservation.ai.service.ConversationService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * 每天凌晨 3 点清理超过 90 天的 AI 会话及消息。
 *
 * <p>cron 默认值硬编码(0 0 3 * * ?),与项目风格一致;
 * 阈值 90 天由 {@code ConversationService#cleanupOld} 入参控制。
 *
 * <p>单实例假设:横向扩展需 ShedLock 或分布式 cron。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class AiConversationCleanupScheduler {

    private final ConversationService conversationService;

    @Scheduled(cron = "0 0 3 * * ?")
    public void cleanupOldConversations() {
        int n = conversationService.cleanupOld(90);
        if (n > 0) {
            log.info("AI conversation cleanup removed {} convs older than 90 days", n);
        }
    }
}
