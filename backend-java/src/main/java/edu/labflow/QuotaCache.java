package edu.labflow;

import java.time.*;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import org.springframework.core.io.ClassPathResource;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Component
public class QuotaCache {
  private final Database db;
  private final StringRedisTemplate redis;
  private final Settings settings;
  private final TransactionTemplate tx;
  private final AtomicBoolean ready = new AtomicBoolean();
  private final DefaultRedisScript<List> reserve = new DefaultRedisScript<>();
  private final DefaultRedisScript<Long> finalize = new DefaultRedisScript<>(),
      invalidate = new DefaultRedisScript<>();

  public QuotaCache(
      Database db, StringRedisTemplate redis, Settings settings, PlatformTransactionManager tm) {
    this.db = db;
    this.redis = redis;
    this.settings = settings;
    tx = new TransactionTemplate(tm);
    reserve.setLocation(new ClassPathResource("redis/reserve_quota.lua"));
    reserve.setResultType(List.class);
    finalize.setLocation(new ClassPathResource("redis/finalize_quota.lua"));
    finalize.setResultType(Long.class);
    invalidate.setLocation(new ClassPathResource("redis/refund_invalidate_quota.lua"));
    invalidate.setResultType(Long.class);
  }

  static String quota(long pool, LocalDate day) {
    return "reserve:quota:{" + pool + "}:" + day;
  }

  static String readyKey(long pool, LocalDate day) {
    return "reserve:quota:{" + pool + "}:ready:" + day;
  }

  static String marker(long pool, String token) {
    return "reserve:quota:{" + pool + "}:op:hold:" + token.replaceAll("[^A-Za-z0-9_:-]", "");
  }

  private List<String> keys(long pool, List<LocalDate> days, String token) {
    var keys = new ArrayList<String>();
    days.forEach(d -> keys.add(quota(pool, d)));
    days.forEach(d -> keys.add(readyKey(pool, d)));
    keys.add(marker(pool, token));
    return keys;
  }

  public boolean held(long pool, String token) {
    if (!ready.get()) return false;
    try {
      return "HELD".equals(redis.opsForValue().get(marker(pool, token)));
    } catch (org.springframework.dao.DataAccessException e) {
      ready.set(false);
      return false;
    }
  }

  public boolean hold(long pool, List<Long> devices, List<LocalDate> days, String token) {
    if (!ready.get()) return false;
    var args = new ArrayList<String>();
    args.add("" + devices.size());
    args.add("1800000");
    args.add("" + devices.size());
    devices.forEach(d -> args.add(d.toString()));
    days.forEach(d -> args.add("" + ttl(d).toMillis()));
    try {
      var result = redis.execute(reserve, keys(pool, days, token), args.toArray());
      if (result != null && !result.isEmpty() && Long.parseLong(result.getFirst().toString()) == 1)
        return true;
      invalidate(pool, days, token);
      return false;
    } catch (org.springframework.dao.DataAccessException e) {
      ready.set(false);
      return false;
    }
  }

  public void finalizeHold(long pool, String token) {
    try {
      redis.execute(finalize, List.of(marker(pool, token)), "86400000");
    } catch (org.springframework.dao.DataAccessException e) {
      ready.set(false);
    }
  }

  public void invalidate(long pool, List<LocalDate> days, String token) {
    try {
      redis.execute(invalidate, keys(pool, days, token), "86400000");
    } catch (org.springframework.dao.DataAccessException e) {
      ready.set(false);
    }
  }

  private Duration ttl(LocalDate date) {
    return Duration.ofMillis(
        Math.max(
            60000,
            Duration.between(
                    Instant.now(), date.plusDays(2).atStartOfDay(BusinessTime.ZONE).toInstant())
                .toMillis()));
  }

  @Scheduled(fixedDelayString = "${LAB_RESERVATION_QUOTA_RECONCILE_INTERVAL_SECONDS:60}000")
  public void reconcile() {
    if (!settings.bool("ENABLE_WORKERS", true)) return;
    try {
      for (var pool :
          db.rows(
              "SELECT DISTINCT COALESCE(pool_id,id) pool FROM device WHERE status<>'DELETED'")) {
        reconcile(
            Database.id(pool, "pool"),
            BusinessTime.today().datesUntil(BusinessTime.today().plusDays(91)).toList());
      }
      ready.set(true);
    } catch (org.springframework.dao.DataAccessException e) {
      ready.set(false);
    }
  }

  public void reconcile(long pool, List<LocalDate> days) {
    if (days.isEmpty()) return;
    tx.executeWithoutResult(
        status -> {
          var devices =
              db.rows(
                  "SELECT id,status FROM device WHERE COALESCE(pool_id,id)=? AND status<>'DELETED' ORDER BY id FOR UPDATE",
                  pool);
          if (devices.isEmpty()) return;
          var occupied = new HashSet<String>();
          for (var row :
              db.rows(
                  "SELECT rd.device_id,rd.date FROM v2_reservation_day rd JOIN device d ON d.id=rd.device_id WHERE COALESCE(d.pool_id,d.id)=? AND rd.date BETWEEN ? AND ?",
                  pool,
                  days.getFirst(),
                  days.getLast())) occupied.add(row.get("device_id") + ":" + row.get("date"));
          for (var row :
              db.rows(
                  "SELECT wo.device_id,wo.reservation_date FROM v2_reservation_waitlist_offer wo JOIN device d ON d.id=wo.device_id WHERE COALESCE(d.pool_id,d.id)=? AND wo.expires_at>UTC_TIMESTAMP() AND wo.reservation_date BETWEEN ? AND ?",
                  pool,
                  days.getFirst(),
                  days.getLast()))
            occupied.add(row.get("device_id") + ":" + row.get("reservation_date"));
          for (var day : days) {
            String key = quota(pool, day);
            var values = new HashMap<String, String>();
            for (var device : devices)
              values.put(
                  device.get("id").toString(),
                  "IDLE".equals(device.get("status"))
                          && !occupied.contains(device.get("id") + ":" + day)
                      ? "1"
                      : "0");
            redis.delete(key);
            redis.opsForHash().putAll(key, values);
            redis.expire(key, ttl(day));
            redis.opsForValue().set(readyKey(pool, day), "1", ttl(day));
          }
        });
  }
}
