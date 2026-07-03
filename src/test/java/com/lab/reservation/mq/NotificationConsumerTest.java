package com.lab.reservation.mq;

import com.lab.reservation.service.NotificationService;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import java.time.Duration;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class NotificationConsumerTest {
    private StringRedisTemplate mockRedis() {
        StringRedisTemplate redis = mock(StringRedisTemplate.class);
        ValueOperations<String,String> ops = mock(ValueOperations.class);
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
}
