package com.lab.reservation.service;

import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.exception.BusinessException;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;
import java.time.LocalDate;
import java.util.Set;
import java.util.concurrent.TimeUnit;

/** 设备预约 Redis 分布式锁：对 (deviceId, date) 加 Redisson MultiLock，看门狗续期，fail-open。 */
@Slf4j
@RequiredArgsConstructor
public class ReservationLock {
    private final RedissonClient client;
    private final long waitSeconds;

    /** 返回 AutoCloseable holder；持锁时 close 释放；fail-open 时返回 null（调用方判空跳过 unlock）。 */
    public Holder acquire(Long deviceId, Set<LocalDate> dates) {
        RLock[] locks = dates.stream()
            .map(date -> client.getLock("lock:dev:" + deviceId + ":" + date))
            .toArray(RLock[]::new);
        RLock multi = client.getMultiLock(locks);
        // 注意：tryLock 的 RuntimeException（Redis 不可用）才 fail-open；
        // !locked 的冲突异常须在此 try 块外抛出，否则会被 catch(RuntimeException) 误吞。
        boolean locked;
        try {
            locked = multi.tryLock(waitSeconds, -1, TimeUnit.SECONDS); // -1 触发看门狗
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new BusinessException(ResultCode.RESERVATION_CONFLICT);
        } catch (RuntimeException e) {
            log.warn("Redis unavailable, fail-open to DB unique index", e);
            return null;
        }
        if (!locked) throw new BusinessException(ResultCode.RESERVATION_CONFLICT);
        return new Holder(multi);
    }

    public static class Holder implements AutoCloseable {
        private final RLock multi;
        Holder(RLock multi) { this.multi = multi; }
        @Override public void close() {
            try { if (multi.isHeldByCurrentThread()) multi.unlock(); } catch (Exception ignore) {}
        }
    }
}
