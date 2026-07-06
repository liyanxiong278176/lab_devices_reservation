package com.lab.reservation.task;

import com.lab.reservation.entity.PendingTimeoutTask;
import com.lab.reservation.entity.Reservation;
import com.lab.reservation.entity.enums.ReservationStatus;
import com.lab.reservation.mapper.PendingTimeoutTaskMapper;
import com.lab.reservation.mapper.ReservationMapper;
import com.lab.reservation.mq.NotificationProducer;
import com.lab.reservation.service.ReservationService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.LocalDateTime;
import java.util.Collections;
import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 锁定 {@link LocalTimeoutScheduler} 行为契约：
 * <ul>
 *   <li>扫描到 PENDING + 到点的任务 → 调 markTimeoutCancelled + 通知 + 删除</li>
 *   <li>状态已流转（非 APPROVED）→ 幂等 skip + 清理任务行（不通知）</li>
 *   <li>预约行已删 → 清理任务行（不通知）</li>
 *   <li>markTimeoutCancelled 抛异常 → markFailed（attempts +1）</li>
 *   <li>scan 返回空 → 不做事</li>
 *   <li>scan 抛异常 → 不崩溃，下次再扫</li>
 * </ul>
 */
class LocalTimeoutSchedulerTest {

    private PendingTimeoutTaskMapper taskMapper;
    private ReservationMapper reservationMapper;
    private ReservationService reservationService;
    private NotificationProducer notificationProducer;
    private LocalTimeoutScheduler scheduler;

    @BeforeEach
    void setUp() {
        taskMapper = mock(PendingTimeoutTaskMapper.class);
        reservationMapper = mock(ReservationMapper.class);
        reservationService = mock(ReservationService.class);
        notificationProducer = mock(NotificationProducer.class);
        scheduler = new LocalTimeoutScheduler(taskMapper, reservationMapper, reservationService, notificationProducer);
        ReflectionTestUtils.setField(scheduler, "batchSize", 100);
    }

    @Test
    void scan_with_no_due_tasks_does_nothing() {
        when(taskMapper.claimDuePending(any(LocalDateTime.class), anyInt())).thenReturn(Collections.emptyList());

        scheduler.scanOnStartup();
        scheduler.scheduledScan();

        verify(reservationService, never()).markTimeoutCancelled(anyLong());
        verify(taskMapper, never()).deleteById(anyLong());
    }

    @Test
    void scan_db_failure_does_not_crash() {
        when(taskMapper.claimDuePending(any(LocalDateTime.class), anyInt()))
                .thenThrow(new RuntimeException("db down"));

        // 启动扫描 / 周期扫描都不能抛
        scheduler.scanOnStartup();
        scheduler.scheduledScan();

        verify(reservationService, never()).markTimeoutCancelled(anyLong());
    }

    @Test
    void due_task_approved_cancels_and_notifies_and_deletes() {
        PendingTimeoutTask t = task(42L);
        when(taskMapper.claimDuePending(any(LocalDateTime.class), anyInt())).thenReturn(List.of(t));
        Reservation r = new Reservation();
        r.setId(42L);
        r.setUserId(7L);
        r.setStatus(ReservationStatus.APPROVED.name());
        when(reservationMapper.selectById(42L)).thenReturn(r);

        scheduler.scheduledScan();

        verify(reservationService, times(1)).markTimeoutCancelled(42L);
        verify(notificationProducer, times(1)).notify(eq(7L), eq("RESERVATION"),
                anyString(), anyString(), eq(42L), eq("RESERVATION"));
        verify(taskMapper, times(1)).deleteById(t.getId());
        verify(taskMapper, never()).markFailed(anyLong(), anyString());
    }

    @Test
    void due_task_already_checked_in_skips_and_cleans_up() {
        PendingTimeoutTask t = task(42L);
        when(taskMapper.claimDuePending(any(LocalDateTime.class), anyInt())).thenReturn(List.of(t));
        Reservation r = new Reservation();
        r.setId(42L);
        r.setStatus(ReservationStatus.IN_USE.name());  // 已签到
        when(reservationMapper.selectById(42L)).thenReturn(r);

        scheduler.scheduledScan();

        verify(reservationService, never()).markTimeoutCancelled(anyLong());
        verify(notificationProducer, never()).notify(anyLong(), anyString(), anyString(), anyString(), anyLong(), anyString());
        verify(taskMapper, times(1)).deleteById(t.getId());  // 幂等：清理任务行
    }

    @Test
    void due_task_reservation_deleted_cleans_up() {
        PendingTimeoutTask t = task(42L);
        when(taskMapper.claimDuePending(any(LocalDateTime.class), anyInt())).thenReturn(List.of(t));
        when(reservationMapper.selectById(42L)).thenReturn(null);

        scheduler.scheduledScan();

        verify(reservationService, never()).markTimeoutCancelled(anyLong());
        verify(notificationProducer, never()).notify(anyLong(), anyString(), anyString(), anyString(), anyLong(), anyString());
        verify(taskMapper, times(1)).deleteById(t.getId());
    }

    @Test
    void due_task_markTimeoutCancelled_throws_marks_failed() {
        PendingTimeoutTask t = task(42L);
        when(taskMapper.claimDuePending(any(LocalDateTime.class), anyInt())).thenReturn(List.of(t));
        Reservation r = new Reservation();
        r.setId(42L);
        r.setUserId(7L);
        r.setStatus(ReservationStatus.APPROVED.name());
        when(reservationMapper.selectById(42L)).thenReturn(r);
        doThrow(new RuntimeException("db locked")).when(reservationService).markTimeoutCancelled(42L);

        scheduler.scheduledScan();

        verify(notificationProducer, never()).notify(anyLong(), anyString(), anyString(), anyString(), anyLong(), anyString());
        verify(taskMapper, times(1)).markFailed(eq(t.getId()), anyString());
        verify(taskMapper, never()).deleteById(anyLong());
    }

    private static PendingTimeoutTask task(long reservationId) {
        PendingTimeoutTask t = new PendingTimeoutTask();
        t.setId(System.nanoTime());  // mock id（实际由 DB AUTO_INCREMENT 生成）
        t.setReservationId(reservationId);
        t.setExecuteAt(LocalDateTime.now().minusMinutes(1));  // 已到期
        t.setStatus(PendingTimeoutTask.Status.PENDING.name());
        t.setAttempts(0);
        return t;
    }
}
