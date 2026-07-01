package com.lab.reservation.security;
import io.jsonwebtoken.Claims;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class JwtUtilsTest {
    private JwtUtils jwt;
    @BeforeEach void setup(){
        JwtProperties p = new JwtProperties();
        p.setSecret("unit-test-secret-key-must-be-at-least-32-bytes-long!!");
        p.setAccessTtl(60L); p.setRefreshTtl(120L);
        jwt = new JwtUtils(p);
    }
    @Test void access_token_roundtrip_keeps_claims(){
        String token = jwt.generateAccess(1L, "alice", java.util.List.of("STUDENT"));
        Claims c = jwt.parse(token);
        assertEquals(1L, Long.parseLong(c.getSubject()));
        assertEquals("alice", c.get("username"));
    }
    @Test void parse_invalid_token_returns_null(){
        assertNull(jwt.parse("not.a.jwt"));
    }
}
