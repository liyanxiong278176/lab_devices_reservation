package edu.labflow;

import jakarta.annotation.PreDestroy;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.slf4j.*;
import org.springframework.data.redis.connection.stream.*;
import org.springframework.data.redis.core.RedisCallback;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@Component
public class NotificationRelay {
  public static final String STREAM = "lab:v2:notification:events";
  private static final Logger log = LoggerFactory.getLogger(NotificationRelay.class);
  private final StringRedisTemplate redis;
  private final Database db;
  private final Settings settings;
  private final NotificationService notifications;
  private final ConcurrentMap<Long, CopyOnWriteArrayList<Client>> clients =
      new ConcurrentHashMap<>();
  private final AtomicInteger count = new AtomicInteger();
  private final String group, consumer = UUID.randomUUID().toString();
  private boolean groupReady;
  private final ExecutorService writers = Executors.newVirtualThreadPerTaskExecutor();

  public NotificationRelay(
      StringRedisTemplate redis,
      Database db,
      Settings settings,
      NotificationService notifications) {
    this.redis = redis;
    this.db = db;
    this.settings = settings;
    this.notifications = notifications;
    group =
        "lab:v2:notification:process:"
            + settings.get("NOTIFICATION_STREAM_GROUP_ID", UUID.randomUUID().toString());
  }

  private record Event(String name, Object data, Long id) {}

  private static final class Client {
    final Principal principal;
    final SseEmitter emitter;
    final BlockingQueue<Event> queue;
    final AtomicBoolean closed = new AtomicBoolean();
    long cursor;

    Client(Principal p, int pending) {
      principal = p;
      emitter = new SseEmitter(0L);
      queue = new ArrayBlockingQueue<>(pending);
    }
  }

  public SseEmitter connect(Principal p, String lastEventId) {
    p.require("notification:read:own");
    Long last = null;
    if (lastEventId != null) {
      if (!lastEventId.matches("[0-9]{1,19}"))
        throw new ApiError("INVALID_EVENT_CURSOR", "通知游标无效", 422);
      try {
        last = Long.parseLong(lastEventId);
      } catch (NumberFormatException e) {
        throw new ApiError("INVALID_EVENT_CURSOR", "通知游标无效", 422);
      }
    }
    Client client = new Client(p, settings.integer("NOTIFICATION_SSE_MAX_PENDING", 100));
    synchronized (clients) {
      var perUser = clients.computeIfAbsent(p.userId(), k -> new CopyOnWriteArrayList<>());
      if (count.get() >= settings.integer("NOTIFICATION_SSE_MAX_CONNECTIONS", 500)
          || perUser.size() >= settings.integer("NOTIFICATION_SSE_MAX_PER_USER", 5))
        throw new ApiError("STREAM_CAPACITY", "实时通知连接数已满，请稍后重试", 503);
      perUser.add(client);
      count.incrementAndGet();
    }
    client.emitter.onCompletion(() -> close(client));
    client.emitter.onTimeout(() -> close(client));
    client.emitter.onError(error -> close(client));
    long head = notifications.head(p);
    client.cursor = last == null ? head : Math.min(head, last);
    Long cursor = last;
    writers.submit(
        () -> {
          try {
            send(
                client, new Event("stream-ready", Map.of("replay", cursor != null), client.cursor));
            if (cursor != null) {
              var rows = notifications.replay(p, client.cursor);
              long pending = notifications.pending(p, client.cursor);
              send(client, new Event("batch-start", Map.of("replay", true), null));
              for (var row : rows) {
                long sequence = Database.id(row, "delivery_sequence");
                var data = notifications.publicRow(row);
                data.put("deliverySequence", sequence);
                send(client, new Event("notification", data, sequence));
                client.cursor = sequence;
              }
              boolean overflow = pending > rows.size();
              if (overflow) client.cursor = head;
              send(
                  client,
                  new Event(
                      "batch-complete",
                      Map.of(
                          "replay",
                          true,
                          "deliveredCount",
                          rows.size(),
                          "omittedCount",
                          overflow ? pending - rows.size() : 0,
                          "historySyncRequired",
                          overflow),
                      overflow ? head : null));
            }
            while (!client.closed.get()) {
              var event =
                  client.queue.poll(
                      settings.integer("NOTIFICATION_SSE_HEARTBEAT_SECONDS", 20), TimeUnit.SECONDS);
              if (!authorized(p)) {
                send(client, new Event("auth-revoked", Map.of("reconnect", false), null));
                break;
              }
              if (event == null) {
                client.emitter.send(SseEmitter.event().comment("heartbeat"));
                continue;
              }
              if (event.id() != null && event.id() <= client.cursor) continue;
              if (event.name().equals("notification")) {
                if (event.id() > client.cursor + 1) {
                  var missing = notifications.between(p, client.cursor, event.id());
                  send(client, new Event("batch-start", Map.of("replay", false), null));
                  for (var row : missing) {
                    long seq = Database.id(row, "delivery_sequence");
                    var data = notifications.publicRow(row);
                    data.put("deliverySequence", seq);
                    send(client, new Event("notification", data, seq));
                    client.cursor = seq;
                  }
                  boolean overflow = client.cursor < event.id();
                  if (overflow) {
                    send(client, event);
                    client.cursor = event.id();
                  }
                  send(
                      client,
                      new Event(
                          "batch-complete",
                          Map.of(
                              "replay",
                              false,
                              "deliveredCount",
                              missing.size(),
                              "historySyncRequired",
                              overflow),
                          null));
                  continue;
                }
                send(client, new Event("batch-start", Map.of("replay", false), null));
                send(client, event);
                client.cursor = event.id();
                send(
                    client,
                    new Event(
                        "batch-complete",
                        Map.of(
                            "replay",
                            false,
                            "deliveredCount",
                            1,
                            "omittedCount",
                            0,
                            "historySyncRequired",
                            false),
                        null));
              } else send(client, event);
            }
          } catch (IOException | InterruptedException | IllegalStateException e) {
            if (e instanceof InterruptedException) Thread.currentThread().interrupt();
          } finally {
            close(client);
            client.emitter.complete();
          }
        });
    return client.emitter;
  }

  private boolean authorized(Principal p) {
    try {
      var session = redis.opsForHash().entries(AuthService.SESSION_PREFIX + p.sid());
      if (session.isEmpty()
          || Long.parseLong(session.get("expires_at").toString())
              <= java.time.Instant.now().getEpochSecond()) return false;
      var user = db.one("SELECT status,college_id FROM sys_user WHERE id=?", p.userId());
      if (user == null
          || Database.id(user, "status") != 1
          || !Objects.equals(user.get("college_id"), p.collegeId())) return false;
      boolean currentAdmin =
          db.count(
                  "SELECT COUNT(*) FROM sys_user_role ur JOIN sys_role r ON r.id=ur.role_id WHERE ur.user_id=? AND r.role_code='SYS_ADMIN'",
                  p.userId())
              > 0;
      if (currentAdmin != p.systemAdmin()) return false;
      return db.count(
              "SELECT COUNT(*) FROM sys_user_role ur JOIN sys_role r ON r.id=ur.role_id LEFT JOIN sys_role_permission rp ON rp.role_id=r.id LEFT JOIN sys_permission perm ON perm.id=rp.permission_id WHERE ur.user_id=? AND (r.role_code='SYS_ADMIN' OR perm.permission_code='notification:read:own')",
              p.userId())
          > 0;
    } catch (RuntimeException e) {
      return false;
    }
  }

  private void send(Client client, Event event) throws IOException {
    var builder = SseEmitter.event().name(event.name()).data(event.data());
    if (event.id() != null) builder.id(event.id().toString());
    client.emitter.send(builder);
  }

  private void close(Client client) {
    if (client.closed.compareAndSet(false, true)) {
      var perUser = clients.get(client.principal.userId());
      synchronized (clients) {
        if (perUser != null) {
          perUser.remove(client);
          if (perUser.isEmpty()) clients.remove(client.principal.userId(), perUser);
        }
        count.decrementAndGet();
      }
    }
  }

  public void bumpCatalogVersion(String scope) {
    if (!scope.matches("(college:[0-9]+|all)"))
      throw new IllegalArgumentException("Invalid catalog scope");
    redis.opsForValue().increment("lab:v2:cache:catalog:version:" + scope);
  }

  public void publish(long userId, Map<String, Object> payload, String taskKey) {
    redis
        .opsForStream()
        .add(
            STREAM,
            Map.of(
                "user_id", "" + userId, "payload", db.json(payload), "source_task_key", taskKey));
  }

  @Scheduled(fixedDelay = 250)
  public void poll() {
    if (!settings.bool("ENABLE_NOTIFICATION_RELAY", true)) return;
    pollOnce();
  }

  public void pollOnce() {
    try {
      if (!groupReady) {
        try {
          redis.execute(
              (RedisCallback<Object>)
                  connection ->
                      connection.execute(
                          "XGROUP",
                          bytes("CREATE"),
                          bytes(STREAM),
                          bytes(group),
                          bytes("$"),
                          bytes("MKSTREAM")));
        } catch (org.springframework.dao.DataAccessException e) {
          boolean exists = false;
          for (Throwable cause = e; cause != null; cause = cause.getCause())
            if (cause.getMessage() != null && cause.getMessage().contains("BUSYGROUP")) {
              exists = true;
              break;
            }
          if (!exists) throw e;
        }
        groupReady = true;
      }
      var records =
          redis
              .opsForStream()
              .read(
                  Consumer.from(group, consumer),
                  StreamReadOptions.empty().count(50),
                  StreamOffset.create(STREAM, ReadOffset.from("0")));
      if (records == null || records.isEmpty()) {
        var pending =
            redis
                .opsForStream()
                .pending(STREAM, group, org.springframework.data.domain.Range.unbounded(), 50);
        if (pending != null) {
          var ids = new ArrayList<RecordId>();
          for (var entry : pending)
            if (entry.getElapsedTimeSinceLastDelivery().compareTo(Duration.ofSeconds(30)) >= 0)
              ids.add(entry.getId());
          if (!ids.isEmpty())
            records =
                redis
                    .opsForStream()
                    .claim(
                        STREAM,
                        group,
                        consumer,
                        Duration.ofSeconds(30),
                        ids.toArray(RecordId[]::new));
        }
      }
      if (records == null || records.isEmpty())
        records =
            redis
                .opsForStream()
                .read(
                    Consumer.from(group, consumer),
                    StreamReadOptions.empty().count(50),
                    StreamOffset.create(STREAM, ReadOffset.lastConsumed()));
      if (records == null) return;
      for (var record : records) {
        String retryKey = "lab:v2:notification:retry:" + group + ":" + record.getId();
        try {
          String next =
              redis.opsForHash().get(retryKey, "next_at") == null
                  ? "0"
                  : redis.opsForHash().get(retryKey, "next_at").toString();
          if (Long.parseLong(next) > System.currentTimeMillis()) continue;
          long user = Long.parseLong(record.getValue().get("user_id").toString());
          Object payload = db.parse(record.getValue().get("payload"), null);
          if (!(payload instanceof Map<?, ?> data))
            throw new IllegalArgumentException("Invalid notification event");
          String type = String.valueOf(data.get("eventType"));
          if (settings.bool("NOTIFICATION_TEST_FAULTS", false)
              && settings.get("ENVIRONMENT", "").equals("test")
              && settings.get("REDIS_URL", "").matches("redis://127\\.0\\.0\\.1:[0-9]+/14")
              && String.valueOf(data.get("title")).startsWith("E2E_HUB_FAIL:"))
            throw new IllegalStateException("Isolated Hub fault");
          Event event;
          if (type.equals("notification")) {
            Object value = data.containsKey("notification") ? data.get("notification") : data;
            if (!(value instanceof Map<?, ?> notification))
              throw new IllegalArgumentException("Missing notification");
            Object sequence = notification.get("deliverySequence");
            if (!(sequence instanceof Number number))
              throw new IllegalArgumentException("Missing sequence");
            event = new Event("notification", notification, number.longValue());
          } else if (type.equals("read_state_changed"))
            event = new Event("read-state-changed", Map.of("scope", "current-user"), null);
          else throw new IllegalArgumentException("Unsupported event type");
          var list = clients.get(user);
          if (list != null)
            for (var client : list) {
              if (type.equals("notification")) {
                var canonical =
                    db.one(
                        "SELECT user_id,college_id FROM notification WHERE id=?",
                        ((Map<?, ?>) event.data()).get("id"));
                if (canonical == null
                    || Database.id(canonical, "user_id") != user
                    || (!client.principal.systemAdmin()
                        && !Objects.equals(
                            canonical.get("college_id"), client.principal.collegeId()))) continue;
              }
              if (!client.queue.offer(event)) {
                close(client);
                client.emitter.complete();
              }
            }
          redis.opsForStream().acknowledge(STREAM, group, record.getId());
          redis.delete(retryKey);
        } catch (RuntimeException e) {
          long attempts =
              Optional.ofNullable(redis.opsForHash().increment(retryKey, "attempts", 1)).orElse(1L);
          int maximum = settings.integer("NOTIFICATION_STREAM_MAX_ATTEMPTS", 5);
          if (!(e instanceof IllegalArgumentException) && attempts < maximum) {
            long delay =
                (long)
                        (Double.parseDouble(
                                settings.get("NOTIFICATION_STREAM_RETRY_BASE_SECONDS", "5"))
                            * 1000)
                    * (1L << Math.min(attempts - 1, 10));
            redis
                .opsForHash()
                .put(retryKey, "next_at", Long.toString(System.currentTimeMillis() + delay));
            redis.expire(retryKey, Duration.ofDays(7));
            continue;
          }
          redis.execute(
              new org.springframework.data.redis.core.script.DefaultRedisScript<String>(
                  "local pending=redis.call('XPENDING',KEYS[1],ARGV[1],ARGV[2],ARGV[2],1);if #pending==0 then return '' end;local id=redis.call('XADD',KEYS[2],'*','source_group',ARGV[1],'source_id',ARGV[2],'user_id',ARGV[3],'source_task_key',ARGV[4],'payload',ARGV[5],'error',ARGV[6],'attempts',ARGV[7]);redis.call('XACK',KEYS[1],ARGV[1],ARGV[2]);redis.call('DEL',KEYS[3]);return id",
                  String.class),
              List.of(STREAM, "lab:v2:notification:dead-letter", retryKey),
              group,
              record.getId().toString(),
              String.valueOf(record.getValue().get("user_id")),
              String.valueOf(record.getValue().get("source_task_key")),
              String.valueOf(record.getValue().get("payload")),
              String.valueOf(e.getMessage()),
              Long.toString(attempts));
        }
      }
    } catch (org.springframework.dao.DataAccessException e) {
      groupReady = false;
    }
  }

  private byte[] bytes(String value) {
    return value.getBytes(StandardCharsets.UTF_8);
  }

  @PreDestroy
  public void shutdown() {
    clients
        .values()
        .forEach(
            list ->
                list.forEach(
                    client -> {
                      close(client);
                      client.emitter.complete();
                    }));
    writers.shutdownNow();
  }
}
