package com.lab.reservation.config;
import com.lab.reservation.service.ReservationLock;
import org.redisson.api.RedissonClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.*;
@Configuration
public class LockConfig {
    @Bean
    public ReservationLock reservationLock(RedissonClient c, @Value("${lab.lock.wait-seconds:3}") long wait) {
        return new ReservationLock(c, wait);
    }
}
