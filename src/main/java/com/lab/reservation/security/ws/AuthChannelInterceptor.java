package com.lab.reservation.security.ws;

import com.lab.reservation.security.JwtUtils;
import lombok.RequiredArgsConstructor;
import org.springframework.messaging.Message;
import org.springframework.messaging.MessageChannel;
import org.springframework.messaging.MessagingException;
import org.springframework.messaging.simp.stomp.StompCommand;
import org.springframework.messaging.simp.stomp.StompHeaderAccessor;
import org.springframework.messaging.support.ChannelInterceptor;
import org.springframework.stereotype.Component;

import java.security.Principal;
import java.util.List;

/** 拦截 STOMP CONNECT 帧，从 Authorization 头取 JWT，校验后把 userId 设为会话 Principal。 */
@Component
@RequiredArgsConstructor
public class AuthChannelInterceptor implements ChannelInterceptor {
    private final JwtUtils jwtUtils;

    @Override
    public Message<?> preSend(Message<?> message, MessageChannel channel) {
        StompHeaderAccessor acc = StompHeaderAccessor.wrap(message);
        if (StompCommand.CONNECT.equals(acc.getCommand())) {
            List<String> auth = acc.getNativeHeader("Authorization");
            if (auth == null || auth.isEmpty()) throw new MessagingException("Missing Authorization");
            String token = auth.get(0).replace("Bearer ", "").trim();
            Long userId = jwtUtils.parseUserId(token);
            if (userId == null) throw new MessagingException("Invalid token");
            final long uid = userId;
            acc.setUser((Principal) () -> String.valueOf(uid));
        }
        return message;
    }
}
