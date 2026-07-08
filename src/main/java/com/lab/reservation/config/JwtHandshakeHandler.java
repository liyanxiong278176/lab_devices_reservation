package com.lab.reservation.config;

import com.lab.reservation.security.CustomUserDetailsService;
import com.lab.reservation.security.ws.WsAuthHandshakeInterceptor;
import com.lab.reservation.security.ws.WsUserPrincipal;
import lombok.RequiredArgsConstructor;
import org.springframework.http.server.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.WebSocketHandler;
import org.springframework.web.socket.server.support.DefaultHandshakeHandler;

import java.security.Principal;
import java.util.Map;

/**
 * 从握手 attributes 取 wsUserId，构造 {@link WsUserPrincipal} 设为 WebSocket 会话 Principal。
 *
 * <p>DefaultSimpUserRegistry 据此 Principal 注册用户会话，convertAndSendToUser(userId,...) 才能定位到会话。
 * （覆盖 DefaultHandshakeHandler.determineUser —— 默认返回 Spring Security 的请求 Principal，本项目 WS 端点
 * 在 SecurityConfig 中 permitAll，故需自行决定会话用户。）
 *
 * <p>关键点：{@link WsUserPrincipal#getName()} 返回 userId（而非 username），与
 * {@link com.lab.reservation.service.impl.NotificationServiceImpl#notify} 中
 * <code>convertAndSendToUser(String.valueOf(userId), ...)</code> 一致，确保现有通知通道不受影响。
 */
@Component
@RequiredArgsConstructor
public class JwtHandshakeHandler extends DefaultHandshakeHandler {

    private final CustomUserDetailsService userDetailsService;

    @Override
    protected Principal determineUser(ServerHttpRequest request, WebSocketHandler wsHandler,
                                      Map<String, Object> attributes) {
        Object uid = attributes.get(WsAuthHandshakeInterceptor.WS_USER_ID);
        if (uid instanceof Long userId) {
            return new WsUserPrincipal(userDetailsService.loadSecurityUserById(userId));
        }
        return null; // 无有效 userId → 拒绝握手（由 SecurityConfig 或 STOMP 处理）
    }
}
