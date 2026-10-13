package edu.labflow;

import java.nio.charset.StandardCharsets;
import java.util.*;
import org.springframework.data.redis.core.RedisCallback;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;

/** Preserves the metric names consumed by the existing notification alerts. */
@Component
public class StreamMetrics {
  private final StringRedisTemplate redis;

  public StreamMetrics(StringRedisTemplate redis) {
    this.redis = redis;
  }

  private Object command(String... args) {
    return redis.execute(
        (RedisCallback<Object>)
            connection -> {
              byte[][] values =
                  Arrays.stream(args)
                      .skip(1)
                      .map(s -> s.getBytes(StandardCharsets.UTF_8))
                      .toArray(byte[][]::new);
              return connection.execute(args[0], values);
            });
  }

  private static String string(Object value) {
    return value instanceof byte[] bytes
        ? new String(bytes, StandardCharsets.UTF_8)
        : String.valueOf(value);
  }

  private static long number(Object value) {
    return value == null ? 0 : Long.parseLong(string(value));
  }

  private static Map<String, Object> fields(Object value) {
    var map = new HashMap<String, Object>();
    if (value instanceof List<?> list)
      for (int i = 0; i + 1 < list.size(); i += 2) map.put(string(list.get(i)), list.get(i + 1));
    return map;
  }

  private static double age(Object id) {
    if (id == null) return 0;
    return Math.max(
        0, (System.currentTimeMillis() - Long.parseLong(string(id).split("-")[0])) / 1000.0);
  }

  private static void metric(StringBuilder result, String name, String labels, double value) {
    result.append(name).append(labels).append(' ').append(value).append('\n');
  }

  public String scrape() {
    var result = new StringBuilder();
    try {
      metric(
          result,
          "notification_stream_length",
          "",
          number(command("XLEN", NotificationRelay.STREAM)));
      metric(
          result,
          "notification_stream_dead_letter_length",
          "",
          number(command("XLEN", "lab:v2:notification:dead-letter")));
      var groups = redis.opsForStream().groups(NotificationRelay.STREAM);
      if (groups != null)
        for (var group : groups) {
          String name = group.groupName();
          String labels = "{group=\"" + name.replace("\\", "\\\\").replace("\"", "\\\"") + "\"}";
          metric(
              result, "notification_stream_group_lag", labels, number(group.getRaw().get("lag")));
          metric(result, "notification_stream_pending", labels, group.pendingCount());
          var range =
              org.springframework.data.domain.Range.<String>from(
                      org.springframework.data.domain.Range.Bound.exclusive(
                          group.lastDeliveredId()))
                  .to(org.springframework.data.domain.Range.Bound.unbounded());
          var queued =
              redis
                  .opsForStream()
                  .range(
                      NotificationRelay.STREAM,
                      range,
                      org.springframework.data.redis.connection.Limit.limit().count(1));
          double oldest =
              queued != null && !queued.isEmpty() ? age(queued.getFirst().getId().getValue()) : 0;
          metric(result, "notification_stream_oldest_queued_seconds", labels, oldest);
          var pending =
              redis
                  .opsForStream()
                  .pending(
                      NotificationRelay.STREAM,
                      name,
                      org.springframework.data.domain.Range.unbounded(),
                      1);
          double idle =
              pending != null && pending.iterator().hasNext()
                  ? pending.iterator().next().getElapsedTimeSinceLastDelivery().toMillis() / 1000.0
                  : 0;
          metric(result, "notification_stream_oldest_pending_seconds", labels, idle);
        }
    } catch (org.springframework.dao.DataAccessException e) {
      metric(result, "notification_stream_metrics_available", "", 0);
    }
    return result.toString();
  }
}
