package com.lab.reservation.security.ws;

import com.lab.reservation.security.JwtUtils;
import lombok.RequiredArgsConstructor;
import org.springframework.http.server.ServerHttpRequest;
import org.springframework.http.server.ServerHttpResponse;
import org.springframework.http.server.ServletServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.WebSocketHandler;
import org.springframework.web.socket.server.HandshakeInterceptor;

import java.util.Map;

/**
 * WebSocket 握手期鉴权。
 *
 * <p>浏览器原生 WebSocket/SockJS 无法在握手 HTTP 请求上加自定义头（这是 {@code convertAndSendToUser}
 * 依赖的 SimpUserRegistry 需要握手期 Principal 的根因），故 token 经 query 传入（浏览器 WS 鉴权的标准做法）。
 *
 * <p>校验通过后把 userId 放入握手 attributes，由 {@link com.lab.reservation.config.JwtHandshakeHandler}
 * 设为会话 Principal，从而注册到 DefaultSimpUserRegistry，使 convertAndSendToUser(userId,...) 能定位会话。
 */
@Component
@RequiredArgsConstructor
public class WsAuthHandshakeInterceptor implements HandshakeInterceptor {

    public static final String WS_USER_ID = "wsUserId";

    private final JwtUtils jwtUtils;

    @Override
    public boolean beforeHandshake(ServerHttpRequest request, ServerHttpResponse response,
                                   WebSocketHandler wsHandler, Map<String, Object> attributes) {
        if (request instanceof ServletServerHttpRequest servlet) {
            String token = servlet.getServletRequest().getParameter("token");
            if (token != null && !token.isBlank()) {
                token = token.replace("Bearer ", "").trim();
                Long userId = jwtUtils.parseUserId(token);
                if (userId != null) {
                    attributes.put(WS_USER_ID, userId);
                    return true;
                }
            }
        }
        return false; // 无有效 token → 拒绝握手
    }

    @Override
    public void afterHandshake(ServerHttpRequest request, ServerHttpResponse response,
                               WebSocketHandler wsHandler, Exception exception) {
        // no-op
    }
}
