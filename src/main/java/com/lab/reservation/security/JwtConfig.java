package com.lab.reservation.security;
import org.springframework.context.annotation.Bean; import org.springframework.context.annotation.Configuration;
@Configuration
public class JwtConfig {
    @Bean public JwtUtils jwtUtils(JwtProperties p){ return new JwtUtils(p); }
}
