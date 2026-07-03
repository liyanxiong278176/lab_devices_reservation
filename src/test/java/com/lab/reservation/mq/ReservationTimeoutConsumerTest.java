package com.lab.reservation.mq;

import com.lab.reservation.entity.Reservation;
import com.lab.reservation.entity.enums.ReservationStatus;
import com.lab.reservation.mapper.ReservationMapper;
import com.lab.reservation.service.ReservationService;
import org.junit.jupiter.api.Test;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

/**
 * 覆盖 consumer 全路径：APPROVED→取消+通知、非 APPROVED→幂等跳过、null reservation→drop、
 * malformed payload→优雅 drop（不抛、不重试）。
 */
class ReservationTimeoutConsumerTest {

    @Test
    void onTimeout_approved_reservation_is_cancelled_and_notified() {
        ReservationMapper mapper = mock(ReservationMapper.class);
        ReservationService svc = mock(ReservationService.class);
        NotificationProducer notify = mock(NotificationProducer.class);

        Reservation r = new Reservation();
        r.setId(42L); r.setUserId(7L);
        r.setStatus(ReservationStatus.APPROVED.name());
        when(mapper.selectById(42L)).thenReturn(r);

        new ReservationTimeoutConsumer(mapper, svc, notify).onTimeout("42");

        verify(svc).markTimeoutCancelled(42L);
        verify(notify).notify(eq(7L), eq("RESERVATION"), contains("超时"), anyString(), eq(42L), eq("RESERVATION"));
    }

    @Test
    void onTimeout_inuse_reservation_is_skipped() {
        ReservationMapper mapper = mock(ReservationMapper.class);
        ReservationService svc = mock(ReservationService.class);
        NotificationProducer notify = mock(NotificationProducer.class);

        Reservation r = new Reservation();
        r.setStatus(ReservationStatus.IN_USE.name());
        when(mapper.selectById(1L)).thenReturn(r);

        new ReservationTimeoutConsumer(mapper, svc, notify).onTimeout("1");

        verify(svc, never()).markTimeoutCancelled(anyLong());
        verify(notify, never()).notify(anyLong(), anyString(), anyString(), anyString(), anyLong(), anyString());
    }

    // ---- C1 回归：malformed payload 优雅 drop（不抛异常、不取消、不通知）----

    @Test
    void onTimeout_prefixed_payload_is_dropped_without_throwing() {
        ReservationMapper mapper = mock(ReservationMapper.class);
        ReservationService svc = mock(ReservationService.class);
        NotificationProducer notify = mock(NotificationProducer.class);

        // 旧 producer 格式 "timeout:42" —— 防御性：即便上游误发也优雅 drop
        new ReservationTimeoutConsumer(mapper, svc, notify).onTimeout("timeout:42");

        verify(mapper, never()).selectById(anyLong());
        verify(svc, never()).markTimeoutCancelled(anyLong());
        verify(notify, never()).notify(anyLong(), anyString(), anyString(), anyString(), anyLong(), anyString());
    }

    @Test
    void onTimeout_non_numeric_payload_is_dropped_without_throwing() {
        ReservationMapper mapper = mock(ReservationMapper.class);
        ReservationService svc = mock(ReservationService.class);
        NotificationProducer notify = mock(NotificationProducer.class);

        new ReservationTimeoutConsumer(mapper, svc, notify).onTimeout("abc");

        verify(mapper, never()).selectById(anyLong());
        verify(svc, never()).markTimeoutCancelled(anyLong());
        verify(notify, never()).notify(anyLong(), anyString(), anyString(), anyString(), anyLong(), anyString());
    }

    // ---- null reservation（已删除）→ log warn、不抛、不取消 ----

    @Test
    void onTimeout_missing_reservation_is_dropped() {
        ReservationMapper mapper = mock(ReservationMapper.class);
        ReservationService svc = mock(ReservationService.class);
        NotificationProducer notify = mock(NotificationProducer.class);

        when(mapper.selectById(999L)).thenReturn(null);

        new ReservationTimeoutConsumer(mapper, svc, notify).onTimeout("999");

        verify(svc, never()).markTimeoutCancelled(anyLong());
        verify(notify, never()).notify(anyLong(), anyString(), anyString(), anyString(), anyLong(), anyString());
    }

    // ---- 幂等：CANCELLED / COMPLETED → skip（含重投场景）----

    @Test
    void onTimeout_cancelled_reservation_is_skipped_idempotent() {
        ReservationMapper mapper = mock(ReservationMapper.class);
        ReservationService svc = mock(ReservationService.class);
        NotificationProducer notify = mock(NotificationProducer.class);

        Reservation r = new Reservation();
        r.setStatus(ReservationStatus.CANCELLED.name()); // 已被取消（首投已处理）
        when(mapper.selectById(5L)).thenReturn(r);

        new ReservationTimeoutConsumer(mapper, svc, notify).onTimeout("5");

        verify(svc, never()).markTimeoutCancelled(anyLong());
        verify(notify, never()).notify(anyLong(), anyString(), anyString(), anyString(), anyLong(), anyString());
    }

    @Test
    void onTimeout_completed_reservation_is_skipped() {
        ReservationMapper mapper = mock(ReservationMapper.class);
        ReservationService svc = mock(ReservationService.class);
        NotificationProducer notify = mock(NotificationProducer.class);

        Reservation r = new Reservation();
        r.setStatus(ReservationStatus.COMPLETED.name());
        when(mapper.selectById(6L)).thenReturn(r);

        new ReservationTimeoutConsumer(mapper, svc, notify).onTimeout("6");

        verify(svc, never()).markTimeoutCancelled(anyLong());
        verify(notify, never()).notify(anyLong(), anyString(), anyString(), anyString(), anyLong(), anyString());
    }
}
