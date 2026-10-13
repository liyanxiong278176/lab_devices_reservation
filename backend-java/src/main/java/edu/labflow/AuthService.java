package edu.labflow;

import com.auth0.jwt.JWT;
import com.auth0.jwt.algorithms.Algorithm;
import com.auth0.jwt.interfaces.DecodedJWT;
import jakarta.servlet.http.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.time.*;
import java.util.*;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.http.ResponseCookie;
import org.springframework.security.crypto.argon2.Argon2PasswordEncoder;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

@Service
public class AuthService {
  static final String SESSION_PREFIX = "lab:v2:auth:session:";
  private final Database db;
  private final Settings settings;
  private final StringRedisTemplate redis;
  private final Algorithm algorithm;
  // pwdlib.recommended(): Argon2id, m=65536, t=3, p=4, 16-byte salt, 32-byte hash.
  private final Argon2PasswordEncoder passwords = new Argon2PasswordEncoder(16, 32, 4, 65536, 3);
  private final String dummy;

  public AuthService(Database db, Settings settings, StringRedisTemplate redis) {
    this.db = db;
    this.settings = settings;
    this.redis = redis;
    this.algorithm = Algorithm.HMAC256(settings.get("JWT_SECRET", ""));
    dummy = passwords.encode("labflow-invalid-user-password-never-valid");
  }

  public boolean matches(String plain, String hash) {
    try {
      return hash.startsWith("$2")
          ? new BCryptPasswordEncoder().matches(plain, hash)
          : passwords.matches(plain, hash);
    } catch (IllegalArgumentException e) {
      return false;
    }
  }

  public String hash(String password) {
    return passwords.encode(password);
  }

  public Map<String, Object> login(String username, String password, HttpServletResponse response) {
    var user = db.one("SELECT * FROM sys_user WHERE username=?", username);
    boolean valid = matches(password, user == null ? dummy : Database.str(user, "password", ""));
    if (!valid || user == null) throw new ApiError("LOGIN_FAILED", "用户名或密码错误", 401);
    if (Database.id(user, "status") != 1) throw new ApiError("USER_DISABLED", "用户已禁用", 403);
    return issue(Database.id(user, "id"), response);
  }

  public Map<String, Object> issue(long userId, HttpServletResponse response) {
    String sid = random(32), refresh = sid + "." + random(32);
    long expires = Instant.now().plus(Duration.ofDays(7)).getEpochSecond();
    var script =
        new DefaultRedisScript<Long>(
            "if redis.call('EXISTS',KEYS[1])==1 then return 0 end redis.call('HSET',KEYS[1],'user_id',ARGV[1],'refresh_hash',ARGV[2],'expires_at',ARGV[3]); redis.call('EXPIREAT',KEYS[1],ARGV[3]); redis.call('SADD',KEYS[2],ARGV[4]); redis.call('EXPIREAT',KEYS[2],ARGV[3]); return 1",
            Long.class);
    try {
      Long result =
          redis.execute(
              script,
              List.of(SESSION_PREFIX + sid, "lab:v2:auth:user-sessions:" + userId),
              "" + userId,
              sha256(refresh),
              "" + expires,
              sid);
      if (!Long.valueOf(1).equals(result)) throw unavailable();
    } catch (org.springframework.dao.DataAccessException e) {
      throw unavailable();
    }
    return cookies(sid, refresh, expires, response);
  }

  public Map<String, Object> refresh(HttpServletRequest request, HttpServletResponse response) {
    String token = cookie(request, "REFRESH_COOKIE_NAME", "lab_refresh");
    String sid = refreshSid(token);
    if (sid == null) throw new ApiError("REFRESH_TOKEN_INVALID", "刷新令牌无效", 401);
    String next = sid + "." + random(32);
    var script =
        new DefaultRedisScript<String>(
            "local u=redis.call('HGET',KEYS[1],'user_id'); local x=redis.call('HGET',KEYS[1],'expires_at'); if not u or not x then return '' end if tonumber(x)<=tonumber(ARGV[3]) or redis.call('HGET',KEYS[1],'refresh_hash')~=ARGV[1] then redis.call('DEL',KEYS[1]); redis.call('SREM','lab:v2:auth:user-sessions:'..u,ARGV[4]); return '' end redis.call('HSET',KEYS[1],'refresh_hash',ARGV[2]); return u..':'..x",
            String.class);
    String result;
    try {
      result =
          redis.execute(
              script,
              List.of(SESSION_PREFIX + sid),
              sha256(token),
              sha256(next),
              "" + Instant.now().getEpochSecond(),
              sid);
    } catch (org.springframework.dao.DataAccessException e) {
      throw unavailable();
    }
    if (result == null || result.isEmpty())
      throw new ApiError("REFRESH_TOKEN_INVALID", "登录已失效，请重新登录", 401);
    String[] values = result.split(":");
    if (db.count("SELECT COUNT(*) FROM sys_user WHERE id=? AND status=1", Long.parseLong(values[0]))
        != 1) {
      revoke(sid);
      throw new ApiError("USER_NOT_FOUND", "用户不存在或已禁用", 401);
    }
    return cookies(sid, next, Long.parseLong(values[1]), response);
  }

  private Map<String, Object> cookies(
      String sid, String refresh, long expires, HttpServletResponse response) {
    Instant now = Instant.now();
    int age = settings.integer("ACCESS_TOKEN_MINUTES", 15) * 60;
    String access =
        JWT.create()
            .withClaim("sid", sid)
            .withClaim("type", "access")
            .withJWTId(UUID.randomUUID().toString().replace("-", ""))
            .withIssuer(settings.get("JWT_ISSUER", "lab-reservation"))
            .withAudience(settings.get("JWT_AUDIENCE", "lab-reservation-web"))
            .withIssuedAt(now)
            .withExpiresAt(now.plusSeconds(age))
            .sign(algorithm);
    String csrf = csrf(sid);
    setCookie(
        response,
        settings.get("ACCESS_COOKIE_NAME", "lab_access"),
        access,
        "/api/v2",
        Math.min(age, expires - now.getEpochSecond()));
    setCookie(
        response,
        settings.get("REFRESH_COOKIE_NAME", "lab_refresh"),
        refresh,
        "/api/v2/auth",
        expires - now.getEpochSecond());
    setCookie(
        response,
        settings.get("CSRF_COOKIE_NAME", "lab_csrf"),
        csrf,
        "/api/v2",
        expires - now.getEpochSecond());
    return Map.of("authenticated", true, "expires_in", age, "csrf_token", csrf);
  }

  public Principal principal(HttpServletRequest req) {
    String access = cookie(req, "ACCESS_COOKIE_NAME", "lab_access");
    if (access == null) throw new ApiError("AUTH_REQUIRED", "请先登录", 401);
    String sid = decode(access, false);
    Map<Object, Object> session;
    try {
      session = redis.opsForHash().entries(SESSION_PREFIX + sid);
    } catch (org.springframework.dao.DataAccessException e) {
      throw unavailable();
    }
    if (session.isEmpty()) throw new ApiError("AUTH_SESSION_INVALID", "登录已失效，请重新登录", 401);
    long uid, expires;
    try {
      uid = Long.parseLong(session.get("user_id").toString());
      expires = Long.parseLong(session.get("expires_at").toString());
    } catch (RuntimeException e) {
      throw new ApiError("AUTH_SESSION_INVALID", "登录会话无效", 401);
    }
    if (expires <= Instant.now().getEpochSecond())
      throw new ApiError("AUTH_SESSION_INVALID", "登录已失效", 401);
    var user =
        db.one("SELECT id,username,college_id,status FROM sys_user WHERE id=? AND status=1", uid);
    if (user == null) throw new ApiError("USER_NOT_FOUND", "用户不存在或已禁用", 401);
    long version = db.count("SELECT version FROM v2_authz_version WHERE id=1");
    String key = "lab:v2:auth:snapshot:" + sid + ":" + version;
    Map<String, Object> snapshot = null;
    try {
      String value = redis.opsForValue().get(key);
      if (value != null) {
        @SuppressWarnings("unchecked")
        var parsed = (Map<String, Object>) db.parse(value, null);
        snapshot = parsed;
      }
    } catch (org.springframework.dao.DataAccessException e) {
      /* Permission cache may fall back to MySQL. */
    }
    if (snapshot == null) {
      var roles =
          db
              .rows(
                  "SELECT r.role_code FROM sys_role r JOIN sys_user_role ur ON ur.role_id=r.id WHERE ur.user_id=?",
                  uid)
              .stream()
              .map(r -> r.get("role_code").toString())
              .toList();
      var permissions =
          db
              .rows(
                  "SELECT DISTINCT p.permission_code FROM sys_permission p JOIN sys_role_permission rp ON rp.permission_id=p.id JOIN sys_user_role ur ON ur.role_id=rp.role_id WHERE ur.user_id=?",
                  uid)
              .stream()
              .map(r -> r.get("permission_code").toString())
              .toList();
      snapshot = Map.of("roles", roles, "permissions", permissions);
      try {
        redis
            .opsForValue()
            .set(
                key,
                db.json(snapshot),
                Duration.ofSeconds(
                    Math.max(1, Math.min(300, expires - Instant.now().getEpochSecond()))));
      } catch (org.springframework.dao.DataAccessException e) {
        /* Cache is optional. */
      }
    }
    return new Principal(
        uid,
        user.get("username").toString(),
        user.get("college_id") == null ? null : Database.id(user, "college_id"),
        strings(snapshot.get("roles")),
        strings(snapshot.get("permissions")),
        sid);
  }

  private Set<String> strings(Object v) {
    var out = new HashSet<String>();
    if (v instanceof Collection<?> values) values.forEach(x -> out.add(x.toString()));
    return Set.copyOf(out);
  }

  public String decode(String token, boolean expiredAllowed) {
    try {
      var verifier =
          JWT.require(algorithm)
              .withIssuer(settings.get("JWT_ISSUER", "lab-reservation"))
              .withAudience(settings.get("JWT_AUDIENCE", "lab-reservation-web"))
              .withClaim("type", "access")
              .withClaimPresence("sid")
              .withClaimPresence("jti")
              .withClaimPresence("iat")
              .withClaimPresence("exp");
      DecodedJWT jwt;
      if (expiredAllowed) {
        jwt = JWT.decode(token);
        algorithm.verify(jwt);
        if (!jwt.getIssuer().equals(settings.get("JWT_ISSUER", "lab-reservation"))
            || !jwt.getAudience().contains(settings.get("JWT_AUDIENCE", "lab-reservation-web"))
            || !"access".equals(jwt.getClaim("type").asString()))
          throw new IllegalArgumentException();
      } else jwt = verifier.build().verify(token);
      String sid = jwt.getClaim("sid").asString();
      if (sid == null || !sid.matches("[A-Za-z0-9_-]{40,64}")) throw new IllegalArgumentException();
      return sid;
    } catch (RuntimeException e) {
      throw new ApiError("TOKEN_INVALID", "令牌无效或已过期", 401);
    }
  }

  public String csrf(String sid) {
    String message = sid + "." + random(24) + "." + Instant.now().getEpochSecond();
    return message
        + "."
        + HexFormat.of()
            .formatHex(
                hmac(
                    hmac(
                        settings.get("JWT_SECRET", "").getBytes(StandardCharsets.UTF_8),
                        "labflow:csrf-token:v1"),
                    message));
  }

  public String csrfSid(String value) {
    if (value == null) return null;
    String[] parts = value.split("\\.");
    if (parts.length != 4 || parts[1].length() < 20) return null;
    try {
      long issued = Long.parseLong(parts[2]), now = Instant.now().getEpochSecond();
      if (issued > now + 60 || now - issued > 604800) return null;
      String message = parts[0] + "." + parts[1] + "." + parts[2];
      byte[] expected =
          hmac(
              hmac(
                  settings.get("JWT_SECRET", "").getBytes(StandardCharsets.UTF_8),
                  "labflow:csrf-token:v1"),
              message);
      return MessageDigest.isEqual(expected, HexFormat.of().parseHex(parts[3])) ? parts[0] : null;
    } catch (RuntimeException e) {
      return null;
    }
  }

  public String cookie(HttpServletRequest request, String key, String fallback) {
    if (request.getCookies() == null) return null;
    for (var cookie : request.getCookies())
      if (cookie.getName().equals(settings.get(key, fallback))) return cookie.getValue();
    return null;
  }

  public void setCookie(
      HttpServletResponse response, String name, String value, String path, long age) {
    var cookie =
        ResponseCookie.from(name, value)
            .path(path)
            .httpOnly(true)
            .secure(settings.bool("COOKIE_SECURE", settings.prod()))
            .sameSite("Lax")
            .maxAge(Math.max(0, age));
    String domain = settings.get("COOKIE_DOMAIN", "");
    if (!domain.isBlank()) cookie.domain(domain);
    response.addHeader("Set-Cookie", cookie.build().toString());
  }

  public void revoke(String sid) {
    try {
      Object uid = redis.opsForHash().get(SESSION_PREFIX + sid, "user_id");
      redis.delete(SESSION_PREFIX + sid);
      if (uid != null) redis.opsForSet().remove("lab:v2:auth:user-sessions:" + uid, sid);
    } catch (org.springframework.dao.DataAccessException e) {
      throw unavailable();
    }
  }

  public void revokeUser(long user) {
    try {
      redis.execute(
          new DefaultRedisScript<Long>(
              "local sessions=redis.call('SMEMBERS',KEYS[1]);for _,sid in ipairs(sessions) do redis.call('DEL',ARGV[1]..sid) end;redis.call('DEL',KEYS[1]);return #sessions",
              Long.class),
          List.of("lab:v2:auth:user-sessions:" + user),
          SESSION_PREFIX);
    } catch (org.springframework.dao.DataAccessException e) {
      throw unavailable();
    }
  }

  public static String refreshSid(String token) {
    if (token == null || !token.matches("[A-Za-z0-9_-]{40,64}\\.[A-Za-z0-9_-]{40,64}")) return null;
    return token.substring(0, token.indexOf('.'));
  }

  public static String random(int bytes) {
    var data = new byte[bytes];
    new SecureRandom().nextBytes(data);
    return Base64.getUrlEncoder().withoutPadding().encodeToString(data);
  }

  public static String sha256(String value) {
    try {
      return HexFormat.of()
          .formatHex(
              MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8)));
    } catch (GeneralSecurityException e) {
      throw new IllegalStateException(e);
    }
  }

  private static byte[] hmac(byte[] key, String message) {
    try {
      Mac mac = Mac.getInstance("HmacSHA256");
      mac.init(new SecretKeySpec(key, "HmacSHA256"));
      return mac.doFinal(message.getBytes(StandardCharsets.UTF_8));
    } catch (GeneralSecurityException e) {
      throw new IllegalStateException(e);
    }
  }

  private static ApiError unavailable() {
    return new ApiError("AUTH_SESSION_UNAVAILABLE", "登录服务暂时不可用，请稍后重试", 503);
  }
}
