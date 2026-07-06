package com.lab.reservation.task;

import com.lab.reservation.entity.PendingTimeoutTask;
import com.lab.reservation.entity.Reservation;
import com.lab.reservation.entity.enums.ReservationStatus;
import com.lab.reservation.mapper.PendingTimeoutTaskMapper;
import com.lab.reservation.mapper.ReservationMapper;
import com.lab.reservation.mq.NotificationProducer;
import com.lab.reservation.service.ReservationService;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 本地超时任务扫描器。替代原 {@code ReservationTimeoutConsumer}（RabbitMQ 死信消费者）。
 *
 * <p>原方案：审批通过时发延迟消息到 RabbitMQ TTL 队列 → 到期死信路由到 cancel.queue → 消费者取消预约。
 * <p>本方案：审批通过时 {@link com.lab.reservation.mq.ReservationTimeoutProducer} 落一行到
 * {@code pending_timeout_task} → 本 Bean 每 5s 扫描 {@code execute_at <= NOW()} 的行 → 调
 * {@link ReservationService#markTimeoutCancelled} 取消预约 + 通知。
 *
 * <h3>DB 是真值源</h3>
 * <ul>
 *   <li>正常路径：调度器扫描到 → 执行 → 删除行</li>
 *   <li>重启 / 宕机：{@link #scanOnStartup} 启动扫一次，把启动时已到点的任务立刻跑掉
 *       （错过的宽限期一并兜底）；未到点的等下次 @Scheduled 扫描</li>
 *   <li>执行失败：{@link PendingTimeoutTaskMapper#markFailed} 记录 attempts + last_error，
 *       attempts >= 5 后改 status=FAILED 停止重试</li>
 * </ul>
 *
 * <h3>幂等保证</h3>
 * {@code markTimeoutCancelled} 内部已用 status 校验（必须是 APPROVED 才转 CANCELLED），
 * 重复执行同一行（如重启前已发请求但未删除行）→ 第二次取出来时 status 已是 CANCELLED → skip。
 *
 * <h3>单实例假设</h3>
 * 多实例部署会有"重复扫描 + 重复执行"风险。本期作为单实例项目不做分布式锁；横向扩展时
 * 在本方法入口加 {@code SELECT ... FOR UPDATE SKIP LOCKED}（MySQL 8+）或
 * ShedLock（基于 Redis）即可，扫描逻辑不变。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class LocalTimeoutScheduler {

    private final PendingTimeoutTaskMapper taskMapper;
    private final ReservationMapper reservationMapper;
    private final ReservationService reservationService;
    private final NotificationProducer notificationProducer;

    @Value("${lab.task.timeout.batch-size:100}")
    private int batchSize;

    /** 启动时先扫一轮：把宕机期间错过的任务立刻补跑（execute_at <= now 的行）。 */
    @PostConstruct
    public void scanOnStartup() {
        log.info("LocalTimeoutScheduler startup scan: scanning for due tasks");
        scanAndRun();
    }

    /** 周期扫描：固定间隔 5s 跑一次（前一次跑完才计时，避开执行时长干扰）。 */
    @Scheduled(fixedDelayString = "${lab.task.timeout.scan-interval-ms:5000}")
    public void scheduledScan() {
        scanAndRun();
    }

    private void scanAndRun() {
        List<PendingTimeoutTask> due;
        try {
            due = taskMapper.claimDuePending(LocalDateTime.now(), batchSize);
        } catch (RuntimeException e) {
            // DB 短暂不可用：log warn 等待下次扫描
            log.warn("timeout task scan failed: {}", e.toString());
            return;
        }
        if (due.isEmpty()) {
            return;
        }
        log.info("timeout scan: picked up {} due task(s)", due.size());
        for (PendingTimeoutTask t : due) {
            runOne(t);
        }
    }

    private void runOne(PendingTimeoutTask t) {
        Long id = t.getReservationId();
        try {
            Reservation r = reservationMapper.selectById(id);
            if (r == null) {
                log.warn("timeout: reservation {} not found, dropping task id={}", id, t.getId());
                taskMapper.deleteById(t.getId());
                return;
            }
            if (!ReservationStatus.APPROVED.name().equals(r.getStatus())) {
                // 状态已流转（签到 / 取消 / 完成）：幂等跳过 + 清理任务行
                log.debug("timeout: reservation {} status={}, skip + cleanup task id={}",
                        id, r.getStatus(), t.getId());
                taskMapper.deleteById(t.getId());
                return;
            }
            reservationService.markTimeoutCancelled(id);
            // 已知取舍（与原 Consumer 同）：markTimeoutCancelled 提交后、notify 调用前若进程挂 → 实时通知丢失。
            // DB 行是最终真相（用户列表可见取消状态）；完美解需事务性 outbox。
            notificationProducer.notify(r.getUserId(), "RESERVATION", "预约超时已自动取消",
                    "预约 " + id + " 超时未签到，已自动取消", id, "RESERVATION");
            taskMapper.deleteById(t.getId());
            log.debug("reservation {} auto-cancelled by timeout", id);
        } catch (RuntimeException e) {
            // 失败：attempts +1，5 次后转 FAILED 停重试
            String err = truncate(e.toString(), 500);
            taskMapper.markFailed(t.getId(), err);
            log.warn("timeout task id={} reservationId={} failed: {}", t.getId(), id, err);
        }
    }

    private static String truncate(String s, int max) {
        return s == null || s.length() <= max ? s : s.substring(0, max);
    }
}
