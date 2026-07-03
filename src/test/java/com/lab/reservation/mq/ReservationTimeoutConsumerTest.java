package com.lab.reservation.mq;

import com.lab.reservation.entity.Reservation;
import com.lab.reservation.entity.enums.ReservationStatus;
import com.lab.reservation.mapper.ReservationMapper;
import com.lab.reservation.service.ReservationService;
import org.junit.jupiter.api.Test;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

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
}
