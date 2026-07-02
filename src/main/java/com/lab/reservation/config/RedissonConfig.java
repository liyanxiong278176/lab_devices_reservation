package com.lab.reservation.config;

import org.redisson.Redisson;
import org.redisson.api.RedissonClient;
import org.redisson.config.Config;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** 显式构建 RedissonClient（避免 starter 自动配置读错 redis 前缀）。 */
@Configuration
public class RedissonConfig {
    @Value("${spring.data.redis.host:localhost}") private String host;
    @Value("${spring.data.redis.port:6379}") private int port;
    @Value("${spring.data.redis.password:}") private String password;
    @Value("${spring.data.redis.database:0}") private int database;

    @Bean(destroyMethod = "shutdown")
    public RedissonClient redissonClient() {
        Config cfg = new Config();
        var single = cfg.useSingleServer()
                .setAddress("redis://" + host + ":" + port)
                .setDatabase(database);
        if (password != null && !password.isBlank()) single.setPassword(password);
        return Redisson.create(cfg);
    }
}
