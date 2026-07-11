package com.lab.reservation.ai.task;

import com.lab.reservation.ai.config.AiProperties;
import com.lab.reservation.ai.service.ConfirmationService;
import com.lab.reservation.ai.service.ToolLoopOrchestrator;
import com.lab.reservation.entity.AiToolExecution;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * 扫描超时未确认的 AI 写操作 → 转 {@code expired}。
 *
 * <p>默认每 60s 跑一次;阈值由 {@link AiProperties#getPendingTimeoutMinutes()}
 * (默认 5 分钟) 控制,沿用项目里 {@code fixedDelayString} 风格。
 *
 * <p>过期后逐行调 {@link ToolLoopOrchestrator#onExpire} 清 in-memory 挂起态
 * (否则会话永久卡 BUSY)+ 推 {@code confirmation_expired} 帧给前端。
 *
 * <p>依赖方向:scheduler → orchestrator → confirmationService,无反向依赖
 * (confirmationService 不依赖 orchestrator,避免循环)。
 *
 * <p>单实例假设:多实例部署需 ShedLock 或 MySQL {@code SELECT ... FOR UPDATE SKIP LOCKED}。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class AiActionTimeoutScheduler {

    private final ConfirmationService confirmationService;
    private final ToolLoopOrchestrator orchestrator;
    private final AiProperties props;

    @Scheduled(fixedDelayString = "${ai.assistant.pending-timeout-check-ms:60000}")
    public void expireOldPending() {
        List<AiToolExecution> expired = confirmationService.expireOldPending(props.getPendingTimeoutMinutes());
        if (expired.isEmpty()) {
            return;
        }
        log.info("AI action timeout scheduler expired {} pending actions", expired.size());
        for (AiToolExecution e : expired) {
            try {
                orchestrator.onExpire(e.getConversationId(), e.getId());
            } catch (Exception ex) {
                // 单行 onExpire 失败不应阻断后续行的清理
                log.warn("onExpire failed for action {} conv={}: {}", e.getId(), e.getConversationId(), ex.toString());
            }
        }
    }
}
