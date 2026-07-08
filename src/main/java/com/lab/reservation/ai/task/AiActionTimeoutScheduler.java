package com.lab.reservation.ai.task;

import com.lab.reservation.ai.config.AiProperties;
import com.lab.reservation.ai.service.ConfirmationService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * 扫描超时未确认的 AI 写操作 → 转 {@code expired}。
 *
 * <p>默认每 60s 跑一次;阈值由 {@link AiProperties#getPendingTimeoutMinutes()}
 * (默认 5 分钟) 控制,沿用项目里 {@code fixedDelayString} 风格。
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
    private final AiProperties props;

    @Scheduled(fixedDelayString = "${ai.assistant.pending-timeout-check-ms:60000}")
    public void expireOldPending() {
        int n = confirmationService.expireOldPending(props.getPendingTimeoutMinutes());
        if (n > 0) {
            log.info("AI action timeout scheduler expired {} pending actions", n);
        }
    }
}
