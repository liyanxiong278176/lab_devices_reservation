package com.lab.reservation.reservation;

import org.junit.jupiter.api.*;
import org.redisson.Redisson;
import org.redisson.api.RedissonClient;
import org.redisson.config.Config;
import com.lab.reservation.service.ReservationLock;
import java.time.LocalDate;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import static org.assertj.core.api.Assertions.assertThat;

/**
 * Redis 锁并发实证（防超约亮点）：8 线程抢同一设备同日 → 恰好 1 获锁；不同日不互斥。
 *
 * 注：spec 原要求 Testcontainers-redis，但本机 Docker Desktop 4.60 的引擎 npipe
 * 对 Testcontainers 依赖的 docker-java HTTP-over-npipe 客户端返 400 BadRequest
 * （响应体仅含 com.docker.desktop.address=npipe://....\docker_cli 标签，无 ServerVersion），
 * EnvironmentAndSystemPropertyClientProviderStrategy 与 NpipeSocketClientProviderStrategy
 * 均以此失败 —— 与 Phase1 ReservationConcurrencyIT 改用本地 MySQL 同一根因（见其 javadoc）。
 *
 * 此处改用本地 compose Redis（localhost:6379，docker-compose 已起且健康，redis-cli PING→PONG）实测：
 * 走真实 Redisson MultiLock + 看门狗续期，锁行为与 Testcontainers 隔离 redis 完全等价，断言不变。
 * 用越界 deviceId(99/998) 避免与运行中后端真实设备锁键冲突，并在每例前清理自身键。
 */
class RedisLockConcurrencyIT {

    RedissonClient client; ReservationLock lock;
    @BeforeEach void up() {
        Config cfg = new Config();
        cfg.useSingleServer().setAddress("redis://localhost:6379");
        client = Redisson.create(cfg);
        lock = new ReservationLock(client, 3);
    }
    @AfterEach void down() { client.shutdown(); }

    @Test void multi_thread_same_device_day_exactly_one_lock() throws Exception {
        int n = 8;
        Set<LocalDate> day = Set.of(LocalDate.now());
        // 清理上次运行可能残留的锁键（看门狗在持有 JVM 死后会自动过期，此处仅保险）
        day.forEach(d -> client.getKeys().delete("lock:dev:99:" + d));

        ExecutorService pool = Executors.newFixedThreadPool(n);
        CountDownLatch start = new CountDownLatch(1);
        CountDownLatch release = new CountDownLatch(1);
        AtomicInteger acquired = new AtomicInteger();
        List<Future<Boolean>> futs = new ArrayList<>();
        for (int i = 0; i < n; i++) {
            futs.add(pool.submit(() -> {
                start.await();
                try (var h = lock.acquire(99L, day)) {
                    if (h == null) return false;
                    acquired.incrementAndGet();
                    release.await();
                    return true;
                } catch (com.lab.reservation.exception.BusinessException e) { return false; }
            }));
        }
        start.countDown();
        Thread.sleep(4500);
        assertThat(acquired.get()).isEqualTo(1);
        release.countDown();
        pool.shutdown();
        try (var h = lock.acquire(99L, day)) { assertThat(h).isNotNull(); }
    }

    @Test void different_days_no_blocking() throws Exception {
        LocalDate today = LocalDate.now();
        client.getKeys().delete("lock:dev:998:" + today, "lock:dev:998:" + today.plusDays(1));
        try (var a = lock.acquire(998L, Set.of(today))) {
            long t = System.currentTimeMillis();
            try (var b = lock.acquire(998L, Set.of(today.plusDays(1)))) {
                assertThat(System.currentTimeMillis() - t).isLessThan(2000L);
            }
        }
    }
}
