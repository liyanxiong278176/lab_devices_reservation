package com.lab.reservation.config;

import com.lab.reservation.common.result.Result;
import com.lab.reservation.security.JwtAuthenticationFilter;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.config.annotation.authentication.configuration.AuthenticationConfiguration;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.AuthenticationEntryPoint;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

/**
 * Spring Security 配置。
 *
 * 由于 application.yml 设置了 server.servlet.context-path=/api，
 * 这里 requestMatchers 的路径不带 /api 前缀（Spring 会自动剥离 context-path 后再匹配）。
 */
@Configuration
@EnableMethodSecurity
@RequiredArgsConstructor
@Slf4j
public class SecurityConfig {

    private final JwtAuthenticationFilter jwtFilter;
    private final ObjectMapper objectMapper;

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Bean
    public AuthenticationManager authenticationManager(AuthenticationConfiguration cfg) throws Exception {
        return cfg.getAuthenticationManager();
    }

    /**
     * 未认证入口：STATELESS JWT 场景下，缺 token / token 过期 / 非法 token 时
     * JwtAuthenticationFilter 不写认证 → 走匿名 → 命中 anyRequest().authenticated()。
     * Spring 6 默认 Http403ForbiddenEntryPoint 会返 403（语义错：403 应表"已认证但越权"），
     * 未认证应返 401，前端 401 拦截器才能触发 refresh / 登出跳登录。此处覆盖为 401 JSON。
     *
     * 防御式写法：
     *   - writeValueAsString 抛 JsonProcessingException 会让前端拿到空 body 401,
     *     丢失 msg、code,前端无法触发 refresh/跳登录;此处 try/catch 降级为 text/plain。
     *   - setStatus 放在序列化/写入成功之后:任一异常抛出都不会让状态头先被提交,
     *     servlet 容器后续有空间走默认错误处理(返回 500),而不是 fake 401。
     *   - 显式 flush():SSE / chunked / Tomcat recycle 等场景下,response writer
     *     未必在 lambda 返回前自动 flush,显式调用防止极端情况下 body 延迟或截断。
     */
    @Bean
    public AuthenticationEntryPoint authenticationEntryPoint() {
        return (req, res, ex) -> {
            String body;
            try {
                body = objectMapper.writeValueAsString(Result.fail(401, "未登录或登录已过期"));
            } catch (Exception serializeErr) {
                log.error("auth entry point serialize Result failed, fallback text/plain", serializeErr);
                res.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
                res.setContentType("text/plain;charset=UTF-8");
                res.getWriter().write("Unauthorized");
                res.getWriter().flush();
                return;
            }
            res.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
            res.setContentType("application/json;charset=UTF-8");
            res.getWriter().write(body);
            res.getWriter().flush();
        };
    }

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
                .csrf(c -> c.disable())
                .cors(c -> {
                })
                .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .authorizeHttpRequests(a -> a
                        .requestMatchers(
                                "/auth/login",
                                "/auth/register",
                                "/auth/refresh",
                                "/ws/**",
                                "/actuator/**",
                                "/doc.html",
                                "/doc.html/**",
                                "/webjars/**",
                                "/v3/api-docs/**",
                                "/swagger-resources/**",
                                "/favicon.ico"
                        ).permitAll()
                        .anyRequest().authenticated())
                .exceptionHandling(e -> e.authenticationEntryPoint(authenticationEntryPoint()))
                .addFilterBefore(jwtFilter, UsernamePasswordAuthenticationFilter.class);
        return http.build();
    }
}
