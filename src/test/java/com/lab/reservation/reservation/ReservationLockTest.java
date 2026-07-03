package com.lab.reservation.reservation;

import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.service.ReservationLock;
import org.junit.jupiter.api.*;
import org.redisson.api.*;
import java.time.LocalDate;
import java.util.*;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class ReservationLockTest {
    RedissonClient client; RLock rlock; RLock multi;
    @BeforeEach void setup() {
        client = mock(RedissonClient.class); rlock = mock(RLock.class); multi = mock(RLock.class);
        when(client.getLock(anyString())).thenReturn(rlock);
        when(client.getMultiLock(any(RLock[].class))).thenReturn(multi);
        // 持锁语义：tryLock 成功后 isHeldByCurrentThread 应为 true（mock 模拟真实行为）
        when(multi.isHeldByCurrentThread()).thenReturn(true);
    }
    @Test void acquire_ok() throws InterruptedException {
        when(multi.tryLock(anyLong(), anyLong(), any())).thenReturn(true);
        ReservationLock lock = new ReservationLock(client, 3);
        try (var g = lock.acquire(1L, Set.of(LocalDate.now()))) { assertThat(g).isNotNull(); }
        verify(multi).unlock();
    }
    @Test void acquire_fail_throws_conflict() throws InterruptedException {
        when(multi.tryLock(anyLong(), anyLong(), any())).thenReturn(false);
        ReservationLock lock = new ReservationLock(client, 3);
        assertThatThrownBy(() -> lock.acquire(1L, Set.of(LocalDate.now())))
            .isInstanceOf(BusinessException.class)
            .extracting("code")
            .isEqualTo(ResultCode.RESERVATION_CONFLICT.getCode());
    }
    @Test void redis_down_fail_open() throws InterruptedException {
        when(multi.tryLock(anyLong(), anyLong(), any())).thenThrow(new RuntimeException("redis down"));
        ReservationLock lock = new ReservationLock(client, 3);
        try (var g = lock.acquire(1L, Set.of(LocalDate.now()))) { assertThat(g).isNull(); }
    }
}
