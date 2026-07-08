package com.lab.reservation.security.ws;

import com.lab.reservation.security.SecurityUserDetails;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class WsUserPrincipalTest {

    @Test
    void getName_returns_userId_as_string() {
        SecurityUserDetails user = new SecurityUserDetails(
                42L, "alice", "password", true, "Alice",
                List.of("STUDENT"), List.of()
        );
        WsUserPrincipal p = new WsUserPrincipal(user);

        assertThat(p.getName()).isEqualTo("42");
        assertThat(p.getUserId()).isEqualTo(42L);
        assertThat(p.getUser()).isSameAs(user);
    }

    @Test
    void equals_and_hashCode_compare_by_userId() {
        SecurityUserDetails u1 = new SecurityUserDetails(7L, "x", "p", true, "X", List.of(), List.of());
        SecurityUserDetails u2 = new SecurityUserDetails(7L, "y", "p", true, "Y", List.of(), List.of());
        SecurityUserDetails u3 = new SecurityUserDetails(8L, "x", "p", true, "X", List.of(), List.of());

        WsUserPrincipal p1 = new WsUserPrincipal(u1);
        WsUserPrincipal p2 = new WsUserPrincipal(u2);
        WsUserPrincipal p3 = new WsUserPrincipal(u3);

        assertThat(p1).isEqualTo(p2);
        assertThat(p1.hashCode()).isEqualTo(p2.hashCode());
        assertThat(p1).isNotEqualTo(p3);
    }

    @Test
    void toString_includes_userId() {
        SecurityUserDetails u = new SecurityUserDetails(99L, "z", "p", true, "Z", List.of(), List.of());
        assertThat(new WsUserPrincipal(u).toString()).contains("99");
    }
}
