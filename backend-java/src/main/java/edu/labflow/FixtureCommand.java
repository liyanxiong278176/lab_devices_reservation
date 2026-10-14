package edu.labflow;

import java.nio.file.*;
import java.util.*;
import org.springframework.boot.*;
import org.springframework.core.env.Environment;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;

/** Tenant-scoped browser fixtures. Never resets a database or disables foreign keys. */
@Component
public class FixtureCommand implements ApplicationRunner {
  private final Database db;
  private final AuthService auth;
  private final Environment env;
  private final TransactionTemplate tx;
  private final Settings settings;
  private final StringRedisTemplate redis;
  private final BusinessEvents events;

  FixtureCommand(
      Database db,
      AuthService auth,
      Environment env,
      org.springframework.transaction.PlatformTransactionManager tm,
      Settings settings,
      StringRedisTemplate redis,
      BusinessEvents events) {
    this.db = db;
    this.auth = auth;
    this.env = env;
    this.tx = new TransactionTemplate(tm);
    this.settings = settings;
    this.redis = redis;
    this.events = events;
  }

  public void run(ApplicationArguments args) {
    String action = env.getProperty("labflow.fixture", "none");
    if (action.equals("none")) return;
    String prefix = env.getRequiredProperty("prefix");
    if (!prefix.matches("e2e-[a-z0-9-]{6,40}")
        || !List.of("local", "test").contains(settings.get("ENVIRONMENT", "local")))
      throw new IllegalArgumentException(
          "Fixtures require a local/test environment and an isolated e2e prefix");
    if (!env.getProperty("spring.datasource.url", "")
        .matches("jdbc:mysql://[^/]+/[A-Za-z0-9_]*(test|e2e)[A-Za-z0-9_]*(\\?.*)?"))
      throw new IllegalArgumentException("Fixtures require a database named for test or e2e use");
    Object result =
        tx.execute(
            status ->
                switch (action) {
                  case "seed" -> seed(prefix);
                  case "cleanup" -> cleanup(prefix);
                  case "notification" -> notification(prefix, title());
                  default -> stream(action, prefix);
                });
    System.out.println("LABFLOW_RESULT=" + db.json(result));
  }

  String title() {
    String value = env.getRequiredProperty("title");
    if (value.isBlank() || value.length() > 200)
      throw new IllegalArgumentException("Invalid notification title");
    return value;
  }

  int number(String key, int fallback) {
    return Integer.parseInt(env.getProperty(key, "" + fallback));
  }

  long user(String prefix, String suffix, String name, String role, Long college, String hash) {
    var r = db.one("SELECT id FROM sys_role WHERE role_code=?", role);
    if (r == null) throw new IllegalStateException("Missing fixture role: " + role);
    long id =
        db.insert(
            "INSERT INTO sys_user (username,password,real_name,user_type,status,college_id) VALUES (?,?,?,?,1,?)",
            prefix + suffix,
            hash,
            name,
            role.equals("STUDENT") ? "STUDENT" : "STAFF",
            college);
    db.execute("INSERT INTO sys_user_role (user_id,role_id) VALUES (?,?)", id, r.get("id"));
    return id;
  }

  long device(String name, long college, long lab, long category, long pool, String asset) {
    return db.insert(
        "INSERT INTO device (name,college_id,lab_id,category_id,pool_id,brand,model,specs,status,need_approval,max_reservation_days,accessory_checklist,asset_code) VALUES (?,?,?,?,?,'E2E',?,'E2E regression fixture','IDLE',1,8,?,?)",
        name,
        college,
        lab,
        category,
        pool,
        name,
        db.json(List.of("电源线")),
        asset);
  }

  Object seed(String p) {
    int units = number("pool-units", 1);
    if (units < 1 || units > 20) throw new IllegalArgumentException("pool-units must be 1..20");
    long c =
        db.insert(
            "INSERT INTO college (code,name,status) VALUES (?,?,1)",
            p.toUpperCase(Locale.ROOT),
            "E2E 测试学院 " + p);
    long category =
        db.insert(
            "INSERT INTO device_category (name,parent_id,sort) VALUES (?,0,0)", p + "-category");
    String hash = auth.hash("E2e-123456");
    long manager = user(p, "-manager", "E2E负责人", "LAB_ADMIN", c, hash);
    user(p, "-admin", "E2E系统管理员", "SYS_ADMIN", null, hash);
    long student = user(p, "-user", "E2E普通用户", "STUDENT", c, hash);
    user(p, "-user2", "E2E候补用户", "STUDENT", c, hash);
    long lab =
        db.insert(
            "INSERT INTO lab (college_id,name,location,description,manager_id,status) VALUES (?,?,'E2E测试楼','E2E regression fixture',?,1)",
            c,
            p + "-lab",
            manager);
    long pool =
        db.insert(
            "INSERT INTO v2_device_pool (college_id,lab_id,name) VALUES (?,?,?)",
            c,
            lab,
            p + "-device");
    long pool2 =
        db.insert(
            "INSERT INTO v2_device_pool (college_id,lab_id,name) VALUES (?,?,?)",
            c,
            lab,
            p + "-device-2");
    long d = device(p + "-device", c, lab, category, pool, null);
    long d2 = device(p + "-device-2", c, lab, category, pool2, null);
    for (int i = 2; i <= units; i++)
      device(p + "-device", c, lab, category, pool, p + "-pool-unit-" + i);
    db.execute("UPDATE college SET manager_id=? WHERE id=?", manager, c);
    var out = new LinkedHashMap<String, Object>();
    out.put("prefix", p);
    out.put("username", p + "-user");
    out.put("user_id", student);
    out.put("password", "E2e-123456");
    out.put("alternate_username", p + "-user2");
    out.put("manager_username", p + "-manager");
    out.put("admin_username", p + "-admin");
    out.put("device_id", d);
    out.put("device_name", p + "-device");
    out.put("pool_id", pool);
    out.put("pool_units", units);
    out.put("second_device_id", d2);
    out.put("second_device_name", p + "-device-2");
    out.put("college_id", c);
    out.put("created_at", java.time.Instant.now().toString());
    return out;
  }

  Map<String, Object> student(String p) {
    var u = db.one("SELECT * FROM sys_user WHERE username=?", p + "-user");
    if (u == null) throw new IllegalArgumentException("Fixture student does not exist");
    return u;
  }

  Object notification(String p, String title) {
    var u = student(p);
    long id = insertNotification(u, title);
    return Map.of("id", id);
  }

  long insertNotification(Map<String, Object> u, String title) {
    db.one("SELECT id FROM sys_user WHERE id=? FOR UPDATE", u.get("id"));
    long sequence =
        db.count(
            "SELECT COALESCE(MAX(delivery_sequence),0)+1 FROM notification WHERE user_id=?",
            u.get("id"));
    return db.insert(
        "INSERT INTO notification (user_id,college_id,type,title,content,delivery_sequence) VALUES (?,?,'SYSTEM',?,'此通知在 SSE 断线期间创建。',?)",
        u.get("id"),
        u.get("college_id"),
        title,
        sequence);
  }

  Object cleanup(String p) {
    var college = db.one("SELECT id FROM college WHERE code=?", p.toUpperCase(Locale.ROOT));
    if (college == null) return Map.of("cleaned", false);
    Object c = college.get("id");
    String users = "SELECT id FROM sys_user WHERE college_id=? OR username IN (?,?,?,?)";
    Object[] names = {c, p + "-manager", p + "-admin", p + "-user", p + "-user2"};
    var assets =
        db.rows("SELECT storage_path FROM v2_upload_asset WHERE user_id IN (" + users + ")", names);
    var exports =
        db.rows(
            "SELECT file_path AS storage_path FROM v2_export_task WHERE requester_id IN ("
                + users
                + ")",
            names);
    var userRows = db.rows(users, names);
    String devices = "SELECT id FROM device WHERE college_id=?";
    String reservations = "SELECT id FROM reservation WHERE college_id=?";
    // Delete dependents before parents. Every predicate is confined to this fixture.
    for (String t :
        List.of(
            "v2_device_document_ack",
            "v2_device_qualification",
            "v2_device_handover",
            "v2_device_status_history",
            "v2_reservation_waitlist_offer",
            "v2_reservation_waitlist",
            "v2_device_document",
            "v2_repair_report"))
      db.execute("DELETE FROM " + t + " WHERE device_id IN (" + devices + ")", c);
    for (String t :
        List.of("v2_reservation_feedback", "v2_reservation_inspection", "v2_reservation_day"))
      db.execute("DELETE FROM " + t + " WHERE reservation_id IN (" + reservations + ")", c);
    db.execute(
        "DELETE FROM v2_reservation_rule WHERE (scope_type='COLLEGE' AND scope_id=?) OR (scope_type='LAB' AND scope_id IN (SELECT id FROM lab WHERE college_id=?)) OR (scope_type='DEVICE' AND scope_id IN ("
            + devices
            + "))",
        c,
        c,
        c);
    db.execute("DELETE FROM v2_reservation_blackout WHERE created_by IN (" + users + ")", names);
    for (String t :
        List.of(
            "notification",
            "v2_audit_log",
            "v2_refresh_session",
            "v2_idempotency_key",
            "v2_upload_asset",
            "sys_user_role"))
      db.execute("DELETE FROM " + t + " WHERE user_id IN (" + users + ")", names);
    db.execute("DELETE FROM v2_export_task WHERE requester_id IN (" + users + ")", names);
    for (String t :
        List.of(
            "reservation",
            "notification",
            "v2_outbox_task",
            "v2_export_task",
            "device",
            "v2_device_pool",
            "lab")) db.execute("DELETE FROM " + t + " WHERE college_id=?", c);
    db.execute("UPDATE college SET manager_id=NULL WHERE id=?", c);
    db.execute(
        "DELETE FROM sys_user WHERE id IN (SELECT id FROM (" + users + ") fixture_users)", names);
    db.execute("DELETE FROM college WHERE id=?", c);
    db.execute(
        "DELETE FROM device_category WHERE name=? AND id NOT IN (SELECT category_id FROM device WHERE category_id IS NOT NULL)",
        p + "-category");
    org.springframework.transaction.support.TransactionSynchronizationManager
        .registerSynchronization(
            new org.springframework.transaction.support.TransactionSynchronization() {
              public void afterCommit() {
                Path root = settings.uploads().toAbsolutePath().normalize();
                for (var rows : List.of(assets, exports))
                  for (var row : rows)
                    if (row.get("storage_path") != null) {
                      Path path =
                          Path.of(row.get("storage_path").toString()).toAbsolutePath().normalize();
                      if (path.startsWith(root))
                        try {
                          Files.deleteIfExists(path);
                        } catch (java.io.IOException e) {
                          throw new IllegalStateException("Could not remove fixture file", e);
                        }
                    }
                for (var row : userRows) {
                  String key = "lab:v2:auth:user-sessions:" + row.get("id");
                  var sessions = redis.opsForSet().members(key);
                  if (sessions != null)
                    for (String sid : sessions) redis.delete("lab:v2:auth:session:" + sid);
                  redis.delete(key);
                }
              }
            });
    return Map.of("cleaned", true);
  }

  Object stream(String action, String p) {
    var u = student(p);
    if (action.equals("rows"))
      return db.rows(
          "SELECT id,user_id AS userId,delivery_sequence AS deliverySequence,title,is_read AS isRead FROM notification WHERE user_id=? ORDER BY delivery_sequence",
          u.get("id"));
    if (action.equals("enqueue") || action.equals("enqueue-batch")) {
      int count = action.equals("enqueue") ? 1 : number("count", 100);
      if (count < 1 || count > 100) throw new IllegalArgumentException("count must be 1..100");
      String title = title();
      if (count > 1 && title.length() > 180)
        throw new IllegalArgumentException("Batch title too long");
      var titles = new ArrayList<String>();
      String key = "";
      for (int i = 1; i <= count; i++) {
        String t = count == 1 ? title : title + String.format(Locale.ROOT, " %03d", i);
        titles.add(t);
        key = "e2e:" + p + ":notification:" + UUID.randomUUID();
        events.task(
            key,
            "NOTIFICATION",
            "user:" + u.get("id"),
            (Long) u.get("college_id"),
            Map.of(
                "user_id",
                u.get("id"),
                "college_id",
                u.get("college_id"),
                "title",
                t,
                "content",
                "Outbox 实时通知 " + p),
            BusinessTime.utcNow());
      }
      return Map.of(
          "count", count, "userId", u.get("id"), "titles", titles, "title", title, "taskKey", key);
    }
    requireIsolatedRedis();
    return redisAction(action, p, u);
  }

  void requireIsolatedRedis() {
    if (!env.getProperty("spring.data.redis.host", "").equals("127.0.0.1")
        || !env.getProperty("spring.data.redis.database", "").equals("14"))
      throw new IllegalStateException("Stream fixtures require isolated local Redis database 14");
  }

  Object redisAction(String action, String p, Map<String, Object> u) {
    String stream = NotificationRelay.STREAM, hold = "e2e:notification:" + p + ":backlog-hold";
    switch (action) {
      case "duplicate":
        {
          var n =
              db.one(
                  "SELECT * FROM notification WHERE user_id=? AND title=? ORDER BY delivery_sequence DESC LIMIT 1",
                  u.get("id"),
                  title());
          if (n == null) throw new IllegalArgumentException("Notification does not exist");
          return Map.of(
              "notificationId",
              n.get("id"),
              "deliverySequence",
              n.get("delivery_sequence"),
              "title",
              title(),
              "streamId",
              publish(n, "e2e:" + p + ":duplicate:" + n.get("id")));
        }
      case "gap":
        {
          long missing = insertNotification(u, "序号缺口补齐 " + p + " · 缺失"),
              later = insertNotification(u, "序号缺口补齐 " + p + " · 后续");
          // Publish only after commit, so consumers can fetch both committed rows.
          var n = db.one("SELECT * FROM notification WHERE id=?", later);
          org.springframework.transaction.support.TransactionSynchronizationManager
              .registerSynchronization(
                  new org.springframework.transaction.support.TransactionSynchronization() {
                    public void afterCommit() {
                      publish(n, "e2e:" + p + ":gap-trigger:" + later);
                    }
                  });
          return Map.of(
              "missingNotificationId",
              missing,
              "missingSequence",
              ((Number) n.get("delivery_sequence")).longValue() - 1,
              "laterNotificationId",
              later,
              "laterSequence",
              n.get("delivery_sequence"));
        }
      case "release-backlog":
        return Map.of("released", Boolean.TRUE.equals(redis.delete(hold)));
      case "backlog":
      case "publish-read-state":
        {
          long user = Long.parseLong(env.getRequiredProperty("user-id"));
          if (user != ((Number) u.get("id")).longValue())
            throw new IllegalArgumentException("Wrong fixture user");
          int count = action.equals("backlog") ? number("count", 1105) : 1;
          if (count < 1 || count > 5000)
            throw new IllegalArgumentException("Invalid backlog count");
          boolean held =
              action.equals("backlog") || Boolean.parseBoolean(env.getProperty("hold", "false"));
          if (held) redis.opsForValue().set(hold, "1");
          String first = "", last = "", source = "";
          var event = new HashMap<String, Object>();
          event.put("eventType", "read_state_changed");
          event.put("userId", user);
          event.put("notificationId", null);
          event.put("all", false);
          for (int i = 1; i <= count; i++) {
            source = (held ? "e2e-backlog:" : "e2e:") + p + ":" + i;
            last =
                text(
                    command(
                        "XADD",
                        stream,
                        "*",
                        "user_id",
                        "" + user,
                        "payload",
                        db.json(event),
                        "source_task_key",
                        source));
            if (first.isEmpty()) first = last;
          }
          return Map.of(
              "stream",
              stream,
              "holdKey",
              hold,
              "count",
              count,
              "firstId",
              first,
              "lastId",
              last,
              "streamId",
              last,
              "sourceTaskKey",
              source);
        }
      case "create-stale-group":
        {
          String group = "e2e:stale:" + p;
          command("XGROUP", "CREATE", stream, group, "$", "MKSTREAM");
          return Map.of("created", true, "groupName", group);
        }
      case "destroy-group":
        {
          String group = env.getRequiredProperty("group-name");
          if (!group.equals("e2e:stale:" + p)
              || !Boolean.parseBoolean(env.getProperty("confirm", "false")))
            throw new IllegalArgumentException("Only confirmed fixture groups may be destroyed");
          command("XGROUP", "DESTROY", stream, group);
          return Map.of("destroyedGroup", group, "stream", stream);
        }
      case "inspect":
        {
          var out = new ArrayList<Map<String, Object>>();
          for (Object entry :
              list(
                  command(
                      "XREVRANGE",
                      "lab:v2:notification:dead-letter",
                      "+",
                      "-",
                      "COUNT",
                      "" + number("limit", 50)))) {
            var parts = list(entry);
            var row = fields(parts.get(1));
            row.put("id", text(parts.get(0)));
            row.computeIfPresent("payload", (k, v) -> db.parse(v, v));
            out.add(row);
          }
          return out;
        }
      case "inspect-stream":
      case "stats":
      case "trim-acked":
        {
          var groups = new ArrayList<Map<String, Object>>();
          long length = ((Number) command("XLEN", stream)).longValue();
          if (length > 0)
            for (Object raw : list(command("XINFO", "GROUPS", stream))) {
              var g = fields(raw);
              for (String key : List.of("consumers", "pending", "lag"))
                g.put(key, g.get(key) == null ? 0L : Long.parseLong(text(g.get(key))));
              g.put("lastDeliveredId", g.get("last-delivered-id"));
              groups.add(g);
            }
          var entries = new ArrayList<Map<String, Object>>();
          int deleted = 0, examined = 0;
          for (Object entry :
              list(command("XRANGE", stream, "-", "+", "COUNT", "" + number("limit", 5000)))) {
            var parts = list(entry);
            String id = text(parts.get(0));
            var f = fields(parts.get(1));
            examined++;
            if (action.equals("trim-acked")) {
              boolean safe = !groups.isEmpty();
              for (var g : groups)
                if (compareIds(text(g.get("lastDeliveredId")), id) < 0
                    || !list(command("XPENDING", stream, text(g.get("name")), id, id, "1"))
                        .isEmpty()) safe = false;
              if (safe) deleted += ((Number) command("XDEL", stream, id)).intValue();
            } else {
              if (!(db.parse(f.get("payload"), Map.of()) instanceof Map<?, ?> payload)) continue;
              if (env.getProperty("notification-id") != null
                  && String.valueOf(payload.get("id")).equals(env.getProperty("notification-id"))) {
                var match = new HashMap<String, Object>();
                match.put("streamId", id);
                match.put("notificationId", payload.get("id"));
                match.put("deliverySequence", payload.get("deliverySequence"));
                match.put("title", payload.get("title"));
                entries.add(match);
              }
            }
          }
          if (action.equals("trim-acked"))
            return Map.of("examined", examined, "deleted", deleted, "stream", stream);
          return Map.of(
              "stream",
              stream,
              "streamLength",
              length,
              "groups",
              groups,
              "deadLetterLength",
              command("XLEN", "lab:v2:notification:dead-letter"),
              "matchingNotificationEntries",
              entries);
        }
      default:
        throw new IllegalArgumentException("Unsupported fixture action: " + action);
    }
  }

  int compareIds(String a, String b) {
    String[] x = a.split("-"), y = b.split("-");
    int c = Long.compare(Long.parseLong(x[0]), Long.parseLong(y[0]));
    return c != 0 ? c : Long.compare(Long.parseLong(x[1]), Long.parseLong(y[1]));
  }

  String publish(Map<String, Object> n, String source) {
    var event = new HashMap<String, Object>();
    event.put("eventType", "notification");
    for (var pair :
        Map.of(
                "id",
                "id",
                "userId",
                "user_id",
                "deliverySequence",
                "delivery_sequence",
                "title",
                "title",
                "type",
                "type",
                "content",
                "content",
                "relatedId",
                "related_id",
                "relatedType",
                "related_type",
                "isRead",
                "is_read",
                "createdAt",
                "created_at")
            .entrySet()) event.put(pair.getKey(), n.get(pair.getValue()));
    return text(
        command(
            "XADD",
            NotificationRelay.STREAM,
            "*",
            "user_id",
            "" + n.get("user_id"),
            "payload",
            db.json(event),
            "source_task_key",
            source));
  }

  Object command(String name, String... args) {
    try (var connection = redis.getConnectionFactory().getConnection()) {
      var lettuce =
          (org.springframework.data.redis.connection.lettuce.LettuceConnection) connection;
      byte[][] encoded =
          Arrays.stream(args)
              .map(a -> a.getBytes(java.nio.charset.StandardCharsets.UTF_8))
              .toArray(byte[][]::new);
      // Explicit decoders preserve nested integer fields in Streams command replies.
      if (Set.of("XINFO", "XRANGE", "XREVRANGE", "XPENDING").contains(name))
        return lettuce.execute(
            name,
            new io.lettuce.core.output.NestedMultiOutput<>(
                io.lettuce.core.codec.ByteArrayCodec.INSTANCE),
            encoded);
      if (name.equals("XGROUP") && args[0].equals("DESTROY"))
        return lettuce.execute(
            name,
            new io.lettuce.core.output.IntegerOutput<>(
                io.lettuce.core.codec.ByteArrayCodec.INSTANCE),
            encoded);
      return lettuce.execute(name, encoded);
    }
  }

  String text(Object value) {
    return value instanceof byte[] b
        ? new String(b, java.nio.charset.StandardCharsets.UTF_8)
        : String.valueOf(value);
  }

  List<?> list(Object value) {
    return value instanceof List<?> l ? l : List.of();
  }

  Map<String, Object> fields(Object value) {
    var parts = list(value);
    var out = new HashMap<String, Object>();
    for (int i = 0; i + 1 < parts.size(); i += 2)
      out.put(
          text(parts.get(i)),
          parts.get(i + 1) instanceof byte[] ? text(parts.get(i + 1)) : parts.get(i + 1));
    return out;
  }
}
