package com.lab.reservation.config;

import com.lab.reservation.security.ws.WsAuthHandshakeInterceptor;
import org.springframework.http.server.ServerHttpRequest;
import org.springframework.web.socket.WebSocketHandler;
import org.springframework.web.socket.server.support.DefaultHandshakeHandler;

import java.security.Principal;
import java.util.Map;

/**
 * 从握手 attributes 取 wsUserId，设为 WebSocket 会话 Principal。
 *
 * <p>DefaultSimpUserRegistry 据此 Principal 注册用户会话，convertAndSendToUser(userId,...) 才能定位到会话。
 * （覆盖 DefaultHandshakeHandler.determineUser —— 默认返回 Spring Security 的请求 Principal，本项目 WS 端点
 * 在 SecurityConfig 中 permitAll，故需自行决定会话用户。）
 */
public class JwtHandshakeHandler extends DefaultHandshakeHandler {

    @Override
    protected Principal determineUser(ServerHttpRequest request, WebSocketHandler wsHandler,
                                      Map<String, Object> attributes) {
        Object uid = attributes.get(WsAuthHandshakeInterceptor.WS_USER_ID);
        if (uid instanceof Long id) {
            final long userId = id;
            return () -> String.valueOf(userId);
        }
        return () -> "anonymous";
    }
}
