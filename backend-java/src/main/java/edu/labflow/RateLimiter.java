package edu.labflow;

import jakarta.servlet.http.HttpServletRequest;
import java.util.*;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Component;

@Component
public class RateLimiter {
  private final StringRedisTemplate redis;
  private final Settings settings;
  private final ClientAddress addresses;
  private final LinkedHashMap<String, Bucket> local = new LinkedHashMap<>(64, .75f, true);

  private static final class Bucket {
    double tokens;
    long updated;

    Bucket(double tokens, long updated) {
      this.tokens = tokens;
      this.updated = updated;
    }
  }

  private static final DefaultRedisScript<List> SCRIPT =
      new DefaultRedisScript<>(
          "local now=tonumber(ARGV[1]);local capacity=tonumber(ARGV[2]);local refill=tonumber(ARGV[3]);local states={};local retry=0;for i,key in ipairs(KEYS) do local current=tonumber(redis.call('HGET',key,'tokens') or capacity);local updated=tonumber(redis.call('HGET',key,'updated') or now);current=math.min(capacity,current+math.max(0,now-updated)/1000*refill);states[i]=current;if current<1 then retry=math.max(retry,math.ceil((1-current)/refill)) end end;if retry>0 then return {0,retry} end;for i,key in ipairs(KEYS) do redis.call('HSET',key,'tokens',states[i]-1,'updated',now);redis.call('EXPIRE',key,ARGV[4]) end;return {1,0}",
          List.class);

  public RateLimiter(StringRedisTemplate redis, Settings settings, ClientAddress addresses) {
    this.redis = redis;
    this.settings = settings;
    this.addresses = addresses;
  }

  public String clientIp(HttpServletRequest request) {
    return addresses.ip(request);
  }

  public void take(String name, String identifier, int capacity, double refill) {
    takeMany(name, List.of(identifier), capacity, refill);
  }

  void takeMany(String name, List<String> identifiers, int capacity, double refill) {
    if (!settings.bool("RATE_LIMIT_ENABLED", true)) return;
    if (capacity < 1 || refill <= 0)
      throw new IllegalStateException("Rate limits require positive capacity and refill");
    var keys =
        identifiers.stream()
            .map(id -> "lab:v2:rate:" + name + ":" + AuthService.sha256(id))
            .toList();
    long now = System.currentTimeMillis();
    try {
      var result =
          redis.execute(
              SCRIPT,
              keys,
              "" + now,
              "" + capacity,
              "" + refill,
              "" + (long) Math.max(60, Math.ceil(capacity / refill) * 2));
      if (result != null && ((Number) result.getFirst()).intValue() == 0)
        throw denied(((Number) result.get(1)).intValue(), "redis");
    } catch (org.springframework.dao.DataAccessException e) {
      synchronized (local) {
        var states = new ArrayList<Bucket>();
        int retry = 0;
        for (String key : keys) {
          var bucket = local.computeIfAbsent(key, k -> new Bucket(capacity, now));
          bucket.tokens =
              Math.min(
                  capacity, bucket.tokens + Math.max(0, now - bucket.updated) / 1000.0 * refill);
          bucket.updated = now;
          states.add(bucket);
          if (bucket.tokens < 1)
            retry = Math.max(retry, (int) Math.ceil((1 - bucket.tokens) / refill));
        }
        while (local.size() > settings.integer("RATE_LIMIT_LOCAL_MAX_ENTRIES", 10000))
          local.remove(local.keySet().iterator().next());
        if (retry > 0) throw denied(retry, "local");
        states.forEach(bucket -> bucket.tokens--);
      }
    }
  }

  private ApiError denied(int seconds, String source) {
    return new ApiError(
        "RATE_LIMITED",
        "请求过于频繁，请稍后再试",
        429,
        Map.of("retry_after", Math.max(1, seconds), "source", source),
        Map.of("Retry-After", "" + Math.max(1, seconds)));
  }

  private double refill(String name, double fallback) {
    return Double.parseDouble(
        settings.get("RATE_LIMIT_" + name + "_REFILL_PER_SECOND", "" + fallback));
  }

  public void login(String username, String ip) {
    take(
        "login-ip",
        ip,
        settings.integer("RATE_LIMIT_LOGIN_IP_CAPACITY", 30),
        refill("LOGIN_IP", .5));
    take(
        "login-user",
        username.strip().toLowerCase(Locale.ROOT),
        settings.integer("RATE_LIMIT_LOGIN_CAPACITY", 5),
        refill("LOGIN", 5.0 / 60));
  }

  public void register(String username, String ip) {
    take(
        "register-ip",
        ip,
        settings.integer("RATE_LIMIT_REGISTER_IP_CAPACITY", 10),
        refill("REGISTER_IP", 10.0 / 3600));
    take(
        "register-user",
        username.strip().toLowerCase(Locale.ROOT),
        settings.integer("RATE_LIMIT_REGISTER_USERNAME_CAPACITY", 3),
        refill("REGISTER_USERNAME", 3.0 / 86400));
  }

  public void authenticated(Principal p, HttpServletRequest req) {
    String path = req.getRequestURI(), policy = "DEFAULT";
    int capacity = 300;
    double speed = 5;
    if (req.getMethod().equals("POST")) {
      if (path.endsWith("/reservations")) {
        policy = "RESERVATION";
        capacity = 10;
        speed = 10.0 / 60;
      } else if (path.contains("/repair-reports")) {
        policy = "REPAIR";
        capacity = 10;
        speed = 10.0 / 60;
      } else if (List.of(
              "/repair-uploads", "/qualification-uploads", "/documents", "/maintenance-evidence")
          .stream()
          .anyMatch(path::endsWith)) {
        policy = "UPLOAD";
        capacity = 60;
        speed = 1.0 / 60;
      }
    }
    takeMany(
        policy.toLowerCase(Locale.ROOT),
        List.of(
            "ip:" + clientIp(req),
            "user:" + p.userId(),
            "college:" + (p.collegeId() == null ? "global" : p.collegeId())),
        settings.integer("RATE_LIMIT_" + policy + "_CAPACITY", capacity),
        refill(policy, speed));
  }
}
