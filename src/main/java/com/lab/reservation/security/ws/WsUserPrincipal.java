package com.lab.reservation.security.ws;

import com.lab.reservation.security.SecurityUserDetails;

import java.security.Principal;
import java.util.Objects;

/**
 * STOMP 握手后的 Principal 包装:让 getName() 返回 userId(而非 username),
 * 与现有 NotificationServiceImpl.notify(..., String.valueOf(userId), ...)
 * 一致 — 这样不破坏现有通知通道(其 user-destination 也是基于 userId 字符串)。
 *
 * <p>AI 助手的所有 STOMP 端点(@MessageMapping("/app/assistant/*"))用
 * 这个 Principal 类型;Controller 通过 {@link #getUser()} 取回完整 SecurityUserDetails。
 */
public class WsUserPrincipal implements Principal {

    private final SecurityUserDetails user;

    public WsUserPrincipal(SecurityUserDetails user) {
        this.user = Objects.requireNonNull(user, "user");
    }

    @Override
    public String getName() {
        return String.valueOf(user.getUserId());
    }

    public SecurityUserDetails getUser() {
        return user;
    }

    public Long getUserId() {
        return user.getUserId();
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof WsUserPrincipal p)) return false;
        return Objects.equals(user.getUserId(), p.user.getUserId());
    }

    @Override
    public int hashCode() {
        return Objects.hash(user.getUserId());
    }

    @Override
    public String toString() {
        return "WsUserPrincipal{userId=" + user.getUserId() + "}";
    }
}
