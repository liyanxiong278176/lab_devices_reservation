package com.lab.reservation.config;

import com.lab.reservation.security.ws.AuthChannelInterceptor;
import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Configuration;
import org.springframework.messaging.simp.config.ChannelRegistration;
import org.springframework.messaging.simp.config.MessageBrokerRegistry;
import org.springframework.web.socket.config.annotation.*;

@Configuration
@EnableWebSocketMessageBroker
@RequiredArgsConstructor
public class WebSocketConfig implements WebSocketMessageBrokerConfigurer {
    private final AuthChannelInterceptor authInterceptor;

    @Override public void registerStompEndpoints(StompEndpointRegistry r) {
        // STOMP 端点相对 servlet context（context-path=/api）→ 注册 "/ws"，实际对外 URL=/api/ws
        r.addEndpoint("/ws").setAllowedOriginPatterns("*").withSockJS();
    }
    @Override public void configureMessageBroker(MessageBrokerRegistry r) {
        r.setApplicationDestinationPrefixes("/app");
        r.setUserDestinationPrefix("/user");
        r.enableSimpleBroker("/queue");
    }
    @Override public void configureClientInboundChannel(ChannelRegistration r) {
        r.interceptors(authInterceptor);
    }
}
