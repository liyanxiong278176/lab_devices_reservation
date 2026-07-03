package com.lab.reservation.security;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Date; import java.util.List;

public class JwtUtils {
    private final JwtProperties props;
    private final SecretKey key;
    public JwtUtils(JwtProperties props){
        this.props = props;
        this.key = Keys.hmacShaKeyFor(props.getSecret().getBytes(StandardCharsets.UTF_8));
    }
    public String generateAccess(Long userId, String username, List<String> roles){
        return build(userId, username, roles, props.getAccessTtl(), "access");
    }
    public String generateRefresh(Long userId, String username){
        return build(userId, username, null, props.getRefreshTtl(), "refresh");
    }
    private String build(Long userId, String username, List<String> roles, long ttlSec, String type){
        long now = System.currentTimeMillis();
        var b = Jwts.builder().subject(String.valueOf(userId)).issuedAt(new Date(now))
                .expiration(new Date(now + ttlSec*1000)).claim("username", username).claim("type", type);
        if (roles != null) b.claim("roles", roles);
        return b.signWith(key).compact();
    }
    public Claims parse(String token){
        try { return Jwts.parser().verifyWith(key).build().parseSignedClaims(token).getPayload(); }
        catch (Exception e){ return null; }
    }

    /** 从 token 中解析 userId（subject 声明）。无效/过期/非数字时返回 null。 */
    public Long parseUserId(String token){
        Claims c = parse(token);
        if (c == null || c.getSubject() == null) return null;
        try { return Long.valueOf(c.getSubject()); }
        catch (NumberFormatException e){ return null; }
    }
}
