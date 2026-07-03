package com.lab.reservation.mq;

import com.lab.reservation.service.NotificationService;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Duration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class NotificationConsumerTest {
    private StringRedisTemplate mockRedis() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        ValueOperations<String, String> ops = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(ops);
        return redis;
    }

    @Test
    void onMessage_first_time_calls_notifyService() {
        NotificationService svc = mock(NotificationService.class);
        StringRedisTemplate redis = mockRedis();
        when(redis.opsForValue().setIfAbsent(anyString(), anyString(), any(Duration.class))).thenReturn(true);
        NotificationConsumer consumer = new NotificationConsumer(svc, redis);
        consumer.onMessage(new NotificationMessage("msg-1", 7L, "T", "t", "c", 1L, "R"));
        verify(svc).notify(7L, "T", "t", "c", 1L, "R");
    }

    @Test
    void onMessage_duplicate_msgId_skips_notifyService() {
        NotificationService svc = mock(NotificationService.class);
        StringRedisTemplate redis = mockRedis();
        when(redis.opsForValue().setIfAbsent(anyString(), anyString(), any(Duration.class))).thenReturn(false);
        NotificationConsumer consumer = new NotificationConsumer(svc, redis);
        consumer.onMessage(new NotificationMessage("dup", 7L, "T", "t", "c", 1L, "R"));
        verify(svc, never()).notify(anyLong(), anyString(), anyString(), anyString(), anyLong(), anyString());
    }

    @Test
    void onMessage_uses_configured_idempotent_ttl_duration() {
        NotificationService svc = mock(NotificationService.class);
        StringRedisTemplate redis = mockRedis();
        when(redis.opsForValue().setIfAbsent(anyString(), anyString(), any(Duration.class))).thenReturn(true);
        NotificationConsumer consumer = new NotificationConsumer(svc, redis);
        ReflectionTestUtils.setField(consumer, "idempotentTtlHours", 24L);

        consumer.onMessage(new NotificationMessage("ttl-1", 1L, "T", "t", "c", 1L, "R"));

        ArgumentCaptor<Duration> cap = ArgumentCaptor.forClass(Duration.class);
        verify(redis.opsForValue()).setIfAbsent(anyString(), anyString(), cap.capture());
        assertThat(cap.getValue()).isEqualTo(Duration.ofHours(24));
    }

    @Test
    void onMessage_notifyService_throws_deletes_key_and_rethrows() {
        NotificationService svc = mock(NotificationService.class);
        StringRedisTemplate redis = mockRedis();
        when(redis.opsForValue().setIfAbsent(anyString(), anyString(), any(Duration.class))).thenReturn(true);
        doThrow(new RuntimeException("db down")).when(svc)
                .notify(anyLong(), anyString(), anyString(), anyString(), anyLong(), anyString());
        NotificationConsumer consumer = new NotificationConsumer(svc, redis);

        assertThatThrownBy(() -> consumer.onMessage(
                new NotificationMessage("boom", 1L, "T", "t", "c", 1L, "R")))
                .isInstanceOf(RuntimeException.class)
                .hasMessage("db down");

        // 处理失败：幂等键被删除，使 broker 重投可再次处理
        verify(redis).delete(eq("mq:notify:boom"));
    }
}
