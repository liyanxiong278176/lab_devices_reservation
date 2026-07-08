package com.lab.reservation.config;

import com.lab.reservation.security.ws.WsAuthHandshakeInterceptor;
import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Configuration;
import org.springframework.messaging.simp.config.MessageBrokerRegistry;
import org.springframework.web.socket.config.annotation.*;

@Configuration
@EnableWebSocketMessageBroker
@RequiredArgsConstructor
public class WebSocketConfig implements WebSocketMessageBrokerConfigurer {

    private final JwtHandshakeHandler handshakeHandler;
    private final WsAuthHandshakeInterceptor wsAuthHandshakeInterceptor;

    @Override public void registerStompEndpoints(StompEndpointRegistry r) {
        // STOMP 端点相对 servlet context（context-path=/api）→ 注册 "/ws"，实际对外 URL=/api/ws
        // 握手期鉴权(从 query token 取 userId 设为会话 Principal)→ 注册到 SimpUserRegistry → convertAndSendToUser 可达
        // 注意:handshakeHandler 必须是 @Component 注入的实例(由 Spring 注入 userDetailsService),
        //      不能用 new JwtHandshakeHandler()(无 Spring 上下文,userDetailsService 为 null)
        r.addEndpoint("/ws")
                .addInterceptors(wsAuthHandshakeInterceptor)
                .setHandshakeHandler(handshakeHandler)
                .setAllowedOriginPatterns("*")
                .withSockJS();
    }

    @Override public void configureMessageBroker(MessageBrokerRegistry r) {
        r.setApplicationDestinationPrefixes("/app");
        r.setUserDestinationPrefix("/user");
        r.enableSimpleBroker("/queue");
    }
}
