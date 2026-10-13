package edu.labflow;

import static org.assertj.core.api.Assertions.*;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.*;
import java.net.http.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.ContextConfiguration;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@ContextConfiguration(initializers = RuntimeEnvironment.class)
@EnabledIfEnvironmentVariable(
    named = "LAB_JDBC_URL",
    matches = "jdbc:mysql:.*labflow_migration_test_fresh.*")
@TestInstance(TestInstance.Lifecycle.PER_CLASS)
class BusinessIntegrationTest {
  @Autowired Database db;
  @Autowired AuthService auth;
  @Autowired ReservationService reservations;
  @Autowired ReservationLifecycle lifecycle;
  @Autowired CatalogService catalog;
  @Autowired SchemaVerifier schema;
  @Autowired OutboxWorker worker;
  @Autowired DeviceAccessService access;
  @Autowired ObjectMapper json;
  @Autowired org.springframework.data.redis.core.StringRedisTemplate redis;
  @Autowired NotificationService notifications;
  @Autowired NotificationRelay relay;
  @Autowired StreamMetrics streamMetrics;

  @Autowired
  @org.springframework.beans.factory.annotation.Qualifier("requestMappingHandlerMapping")
  org.springframework.web.servlet.mvc.method.annotation.RequestMappingHandlerMapping mappings;

  @LocalServerPort int port;
  long college, lab, device, user, manager;
  Principal student, administrator;
  final String suffix = UUID.randomUUID().toString().substring(0, 8);

  @Test
  void deletedFirstPoolUnitDoesNotPreventBookingSurvivingUnits() {
    long pool =
        db.insert(
            "INSERT INTO v2_device_pool (name,college_id,lab_id) VALUES (?,?,?)",
            "soft-delete-pool-" + suffix,
            college,
            lab);
    db.insert(
        "INSERT INTO device (name,college_id,lab_id,pool_id,status,need_approval,max_reservation_days) VALUES (?,?,?,?,'DELETED',1,31)",
        "deleted-unit-" + suffix,
        college,
        lab,
        pool);
    long surviving =
        db.insert(
            "INSERT INTO device (name,college_id,lab_id,pool_id,status,need_approval,max_reservation_days) VALUES (?,?,?,?,'IDLE',1,31)",
            "surviving-unit-" + suffix,
            college,
            lab,
            pool);
    LocalDate day = BusinessTime.today().plusDays(12);
    var plan =
        new ReservationPlan(
            null, pool, null, 1, "软删除后资源池验证", null, null, day, day, null, null, null);
    var result = reservations.preflight(administrator, plan);
    assertThat(result.get("all_available")).isEqualTo(true);
    assertThat(Database.id((Map<String, Object>) result.get("device"), "id")).isEqualTo(surviving);
    assertThat(
            reservations
                .availability(administrator, pool, true, day, day)
                .getFirst()
                .get("available_units"))
        .isEqualTo(1L);
  }

  @Test
  void redisRateBucketsChargeAllDimensionsOnlyWhenRequestIsAllowed() {
    var env =
        new org.springframework.mock.env.MockEnvironment()
            .withProperty("LAB_JWT_SECRET", "public-integration-test-secret-32-characters");
    var settings = new Settings(env);
    var limiter = new RateLimiter(redis, settings, new ClientAddress(settings));
    String key = "atomic-test-" + suffix;
    limiter.take(key, "blocked", 1, .001);
    assertThatThrownBy(() -> limiter.takeMany(key, List.of("available", "blocked"), 1, .001))
        .isInstanceOfSatisfying(ApiError.class, e -> assertThat(e.status).isEqualTo(429));
    limiter.take(key, "available", 1, .001);
    assertThatThrownBy(() -> limiter.take(key, "available", 1, .001)).isInstanceOf(ApiError.class);
  }

  @Test
  void localRateFallbackPreservesAtomicBucketCharging() {
    var failingRedis =
        new org.springframework.data.redis.core.StringRedisTemplate() {
          @Override
          public <T> T execute(
              org.springframework.data.redis.core.script.RedisScript<T> script,
              List<String> keys,
              Object... args) {
            throw new org.springframework.dao.DataAccessResourceFailureException(
                "isolated dependency failure");
          }
        };
    var env =
        new org.springframework.mock.env.MockEnvironment()
            .withProperty("LAB_JWT_SECRET", "public-integration-test-secret-32-characters");
    var settings = new Settings(env);
    var limiter = new RateLimiter(failingRedis, settings, new ClientAddress(settings));
    limiter.take("fallback", "blocked", 1, .001);
    assertThatThrownBy(() -> limiter.takeMany("fallback", List.of("available", "blocked"), 1, .001))
        .isInstanceOf(ApiError.class);
    limiter.take("fallback", "available", 1, .001);
    assertThatThrownBy(() -> limiter.take("fallback", "available", 1, .001))
        .isInstanceOf(ApiError.class);
  }

  @Test
  void repeatedStreamFailureMovesToDeadLetterAndAcknowledgesAtomically() throws Exception {
    String id = "test-dlq-" + suffix, group = "lab:v2:notification:process:" + id;
    var env =
        new org.springframework.mock.env.MockEnvironment()
            .withProperty("LAB_JWT_SECRET", "public-integration-test-secret-32-characters")
            .withProperty("LAB_NOTIFICATION_STREAM_GROUP_ID", id)
            .withProperty("LAB_ENVIRONMENT", "test")
            .withProperty("LAB_REDIS_URL", "redis://127.0.0.1:36379/14")
            .withProperty("LAB_NOTIFICATION_TEST_FAULTS", "true")
            .withProperty("LAB_NOTIFICATION_STREAM_RETRY_BASE_SECONDS", "0.001");
    var consumer = testRelay(id);
    consumer.shutdown();
    consumer = new NotificationRelay(redis, db, new Settings(env), notifications);
    long before =
        Optional.ofNullable(redis.opsForStream().size("lab:v2:notification:dead-letter"))
            .orElse(0L);
    org.springframework.data.redis.connection.stream.RecordId source = null;
    try {
      consumer.pollOnce();
      source =
          redis
              .opsForStream()
              .add(
                  NotificationRelay.STREAM,
                  Map.of(
                      "user_id",
                      Long.toString(user),
                      "payload",
                      db.json(
                          Map.of(
                              "eventType",
                              "notification",
                              "id",
                              999,
                              "deliverySequence",
                              1,
                              "title",
                              "E2E_HUB_FAIL:" + suffix)),
                      "source_task_key",
                      id));
      for (int i = 0; i < 5; i++) {
        consumer.pollOnce();
        Thread.sleep(15);
      }
      assertThat(redis.opsForStream().size("lab:v2:notification:dead-letter"))
          .isEqualTo(before + 1);
      assertThat(
              redis
                  .opsForStream()
                  .pending(NotificationRelay.STREAM, group)
                  .getTotalPendingMessages())
          .isZero();
      consumer.pollOnce();
      assertThat(redis.opsForStream().size("lab:v2:notification:dead-letter"))
          .isEqualTo(before + 1);
      var entries =
          redis
              .opsForStream()
              .reverseRange(
                  "lab:v2:notification:dead-letter",
                  org.springframework.data.domain.Range.unbounded(),
                  org.springframework.data.redis.connection.Limit.limit().count(1));
      assertThat(entries.getFirst().getValue())
          .containsEntry("attempts", "5")
          .containsEntry("user_id", Long.toString(user))
          .containsEntry("source_task_key", id);
      redis.opsForStream().delete("lab:v2:notification:dead-letter", entries.getFirst().getId());
    } finally {
      consumer.shutdown();
      redis.opsForStream().destroyGroup(NotificationRelay.STREAM, group);
      if (source != null) redis.opsForStream().delete(NotificationRelay.STREAM, source);
    }
  }

  @Test
  void duplicateOutboxExecutionCreatesOnlyOneNotification() {
    String key = "test-notification-" + suffix;
    long id =
        db.insert(
            "INSERT INTO v2_outbox_task (task_key,task_type,aggregate_key,payload,status,attempts,execute_at) VALUES (?,'NOTIFICATION',?,?,'PENDING',0,DATE_SUB(UTC_TIMESTAMP(),INTERVAL 10 YEAR))",
            key,
            key,
            db.json(
                Map.of(
                    "user_id",
                    user,
                    "college_id",
                    college,
                    "title",
                    "duplicate test",
                    "content",
                    "test")));
    try {
      var task = worker.claim();
      assertThat(Database.id(task, "id")).isEqualTo(id);
      worker.run(task);
      worker.run(task);
      assertThat(db.count("SELECT COUNT(*) FROM notification WHERE source_task_key=?", key))
          .isEqualTo(1);
      assertThat(db.one("SELECT status FROM v2_outbox_task WHERE id=?", id).get("status"))
          .isEqualTo("COMPLETED");
    } finally {
      db.execute("DELETE FROM notification WHERE source_task_key=?", key);
      db.execute("DELETE FROM v2_outbox_task WHERE id=?", id);
    }
  }

  @Test
  void outboxRetriesAreBoundedAndFailedTaskCanBeRecovered() {
    String key = "test-failure-" + suffix;
    long id =
        db.insert(
            "INSERT INTO v2_outbox_task (task_key,task_type,aggregate_key,payload,status,attempts,execute_at) VALUES (?,'UNSUPPORTED_TEST',?,'{}','PENDING',0,DATE_SUB(UTC_TIMESTAMP(),INTERVAL 10 YEAR))",
            key,
            key);
    try {
      for (int i = 1; i <= 5; i++) {
        db.execute(
            "UPDATE v2_outbox_task SET execute_at=DATE_SUB(UTC_TIMESTAMP(),INTERVAL 10 YEAR) WHERE id=?",
            id);
        var task = worker.claim();
        assertThat(Database.id(task, "id")).isEqualTo(id);
        worker.run(task);
        var row = db.one("SELECT * FROM v2_outbox_task WHERE id=?", id);
        assertThat(Database.id(row, "attempts")).isEqualTo(i);
        assertThat(row.get("status")).isEqualTo(i == 5 ? "FAILED" : "PENDING");
        assertThat(row.get("claimed_at")).isNull();
      }
      worker.retry(administrator, id);
      var recovered = db.one("SELECT * FROM v2_outbox_task WHERE id=?", id);
      assertThat(recovered.get("status")).isEqualTo("PENDING");
      assertThat(Database.id(recovered, "attempts")).isZero();
    } finally {
      db.execute("DELETE FROM v2_outbox_task WHERE id=?", id);
    }
  }

  @Test
  void allHistoricalNonAiRoutesRemainMapped() throws Exception {
    var root = java.nio.file.Path.of("").toAbsolutePath();
    if (root.getFileName().toString().equals("backend-java")) root = root.getParent();
    var inventory =
        json.readTree(
            java.nio.file.Files.readString(root.resolve("docs/springboot-api-inventory.json")));
    var actual = new HashSet<String>();
    mappings
        .getHandlerMethods()
        .forEach(
            (mapping, handler) -> {
              for (String path : mapping.getPatternValues())
                for (var method : mapping.getMethodsCondition().getMethods())
                  actual.add(method + " " + path.replaceAll("\\{[^}]+}", "{}"));
            });
    var missing = new ArrayList<String>();
    for (var endpoint : inventory) {
      String route =
          endpoint.path("method").asText()
              + " "
              + endpoint.path("path").asText().replaceAll("\\{[^}]+}", "{}");
      if (!actual.contains(route)) missing.add(route);
    }
    assertThat(missing).isEmpty();
  }

  private NotificationRelay testRelay(String group) {
    var env =
        new org.springframework.mock.env.MockEnvironment()
            .withProperty("LAB_JWT_SECRET", "public-integration-test-secret-32-characters")
            .withProperty("LAB_NOTIFICATION_STREAM_GROUP_ID", group);
    return new NotificationRelay(redis, db, new Settings(env), notifications);
  }

  @Test
  void independentStreamGroupsAndRestartRecoverPendingRecords() {
    String first = "test-first-" + suffix, second = "test-second-" + suffix;
    String firstGroup = "lab:v2:notification:process:" + first,
        secondGroup = "lab:v2:notification:process:" + second;
    var one = testRelay(first);
    var two = testRelay(second);
    try {
      one.pollOnce();
      two.pollOnce();
      var id =
          redis
              .opsForStream()
              .add(
                  NotificationRelay.STREAM,
                  Map.of(
                      "user_id",
                      Long.toString(user),
                      "payload",
                      db.json(Map.of("eventType", "read_state_changed", "userId", user)),
                      "source_task_key",
                      "test-" + suffix));
      one.pollOnce();
      two.pollOnce();
      assertThat(
              redis
                  .opsForStream()
                  .pending(NotificationRelay.STREAM, firstGroup)
                  .getTotalPendingMessages())
          .isZero();
      assertThat(
              redis
                  .opsForStream()
                  .pending(NotificationRelay.STREAM, secondGroup)
                  .getTotalPendingMessages())
          .isZero();
      var pendingId =
          redis
              .opsForStream()
              .add(
                  NotificationRelay.STREAM,
                  Map.of(
                      "user_id",
                      Long.toString(user),
                      "payload",
                      db.json(Map.of("eventType", "read_state_changed", "userId", user)),
                      "source_task_key",
                      "restart-" + suffix));
      redis
          .opsForStream()
          .read(
              org.springframework.data.redis.connection.stream.Consumer.from(
                  firstGroup, "old-consumer"),
              org.springframework.data.redis.connection.stream.StreamReadOptions.empty().count(1),
              org.springframework.data.redis.connection.stream.StreamOffset.create(
                  NotificationRelay.STREAM,
                  org.springframework.data.redis.connection.stream.ReadOffset.lastConsumed()));
      assertThat(
              redis
                  .opsForStream()
                  .pending(NotificationRelay.STREAM, firstGroup)
                  .getTotalPendingMessages())
          .isEqualTo(1);
      redis.execute(
          (org.springframework.data.redis.core.RedisCallback<Object>)
              connection ->
                  connection.execute(
                      "XCLAIM",
                      NotificationRelay.STREAM.getBytes(),
                      firstGroup.getBytes(),
                      "old-consumer".getBytes(),
                      "0".getBytes(),
                      pendingId.getValue().getBytes(),
                      "IDLE".getBytes(),
                      "31000".getBytes()));
      var restarted = testRelay(first);
      try {
        restarted.pollOnce();
        assertThat(
                redis
                    .opsForStream()
                    .pending(NotificationRelay.STREAM, firstGroup)
                    .getTotalPendingMessages())
            .isZero();
      } finally {
        restarted.shutdown();
      }
      assertThat(streamMetrics.scrape())
          .contains(
              "notification_stream_group_lag",
              firstGroup,
              "notification_stream_oldest_pending_seconds");
      redis.opsForStream().delete(NotificationRelay.STREAM, id, pendingId);
    } finally {
      one.shutdown();
      two.shutdown();
      redis.opsForStream().destroyGroup(NotificationRelay.STREAM, firstGroup);
      redis.opsForStream().destroyGroup(NotificationRelay.STREAM, secondGroup);
    }
  }

  @Test
  void notificationReplayHasHardLimitAndAscendingSequence() {
    long recipient =
        db.insert(
            "INSERT INTO sys_user (username,password,user_type,college_id,status) VALUES (?,?,'STUDENT',?,1)",
            "replay-" + suffix,
            auth.hash("test-password-123"),
            college);
    var principal =
        new Principal(
            recipient,
            "replay",
            college,
            Set.of("STUDENT"),
            Set.of("notification:read:own"),
            "test");
    try {
      for (int i = 1; i <= 105; i++)
        db.insert(
            "INSERT INTO notification (user_id,college_id,type,title,content,is_read,delivery_sequence) VALUES (?,?,'SYSTEM','replay','test',0,?)",
            recipient,
            college,
            i);
      var rows = notifications.replay(principal, 0);
      assertThat(rows).hasSize(100);
      assertThat(Database.id(rows.getFirst(), "delivery_sequence")).isEqualTo(6);
      assertThat(Database.id(rows.getLast(), "delivery_sequence")).isEqualTo(105);
      assertThat(notifications.pending(principal, 0)).isEqualTo(105);
    } finally {
      db.execute("DELETE FROM notification WHERE user_id=?", recipient);
      db.execute("DELETE FROM sys_user WHERE id=?", recipient);
    }
  }

  @BeforeAll
  void fixtures() {
    college =
        db.insert(
            "INSERT INTO college (code,name,status) VALUES (?,?,1)",
            "TEST-" + suffix,
            "测试学院-" + suffix);
    user =
        db.insert(
            "INSERT INTO sys_user (username,password,real_name,user_type,college_id,status,credit_score) VALUES (?,?,?,'STUDENT',?,1,100)",
            "user-" + suffix,
            auth.hash("test-password-123"),
            "测试用户",
            college);
    manager =
        db.insert(
            "INSERT INTO sys_user (username,password,real_name,user_type,college_id,status,credit_score) VALUES (?,?,?,'STAFF',?,1,100)",
            "manager-" + suffix,
            auth.hash("test-password-123"),
            "测试管理员",
            college);
    db.execute(
        "INSERT INTO sys_user_role (user_id,role_id) SELECT ?,id FROM sys_role WHERE role_code='STUDENT'",
        user);
    db.execute(
        "INSERT INTO sys_user_role (user_id,role_id) SELECT ?,id FROM sys_role WHERE role_code='SYS_ADMIN'",
        manager);
    lab =
        db.insert(
            "INSERT INTO lab (college_id,name,manager_id,status) VALUES (?,?,?,1)",
            college,
            "测试实验室",
            manager);
    device =
        db.insert(
            "INSERT INTO device (name,college_id,lab_id,status,need_approval,max_reservation_days,accessory_checklist) VALUES (?,?,?,'IDLE',1,31,'[]')",
            "测试设备",
            college,
            lab);
    student =
        new Principal(
            user,
            "user-" + suffix,
            college,
            Set.of("STUDENT"),
            Set.of(
                "device:read",
                "reservation:create",
                "reservation:read:own",
                "reservation:cancel",
                "reservation:return"),
            "test");
    administrator =
        new Principal(manager, "manager-" + suffix, college, Set.of("SYS_ADMIN"), Set.of(), "test");
  }

  @Test
  void schemaMatchesSnapshot() {
    assertThat(schema.differences()).isEmpty();
  }

  @Test
  void futureTimerDoesNotBlockDueTaskOnSameAggregate() {
    String aggregate = "test-order-" + suffix;
    long future =
        db.insert(
            "INSERT INTO v2_outbox_task (task_key,task_type,aggregate_key,payload,status,attempts,execute_at) VALUES (?,'CACHE_BUMP',?,'{}','PENDING',0,DATE_ADD(UTC_TIMESTAMP(),INTERVAL 1 DAY))",
            aggregate + "-future",
            aggregate);
    long due =
        db.insert(
            "INSERT INTO v2_outbox_task (task_key,task_type,aggregate_key,payload,status,attempts,execute_at) VALUES (?,'CACHE_BUMP',?,'{}','PENDING',0,DATE_SUB(UTC_TIMESTAMP(),INTERVAL 10 YEAR))",
            aggregate + "-due",
            aggregate);
    try {
      var claimed = worker.claim();
      assertThat(claimed).isNotNull();
      assertThat(Database.id(claimed, "id")).isEqualTo(due);
      assertThat(db.one("SELECT status FROM v2_outbox_task WHERE id=?", future).get("status"))
          .isEqualTo("PENDING");
    } finally {
      db.execute("DELETE FROM v2_outbox_task WHERE aggregate_key=?", aggregate);
    }
  }

  @Test
  void documentPermissionCanBeRevokedIndependently() {
    var restricted =
        new Principal(
            manager, "manager", college, Set.of("LAB_ADMIN"), Set.of("device:manage"), "test");
    assertThatThrownBy(() -> access.archive(restricted, device, 999))
        .isInstanceOfSatisfying(ApiError.class, e -> assertThat(e.status).isEqualTo(403));
  }

  @Test
  void groupedCatalogCountHandlesQualifiedSqlExpressions() {
    var page = catalog.devices(administrator, new Pagination(1, 20), "测试设备", null, null, true);
    assertThat(((Number) page.get("total")).longValue()).isGreaterThanOrEqualTo(1);
    assertThat((List<?>) page.get("items")).isNotEmpty();
  }

  @Test
  void verifiesPythonArgon2HashesWithoutResettingPassword() {
    // Produced by pwdlib with m=65536,t=3,p=4 and a deterministic public test salt.
    String hash = System.getenv("LAB_TEST_PYTHON_ARGON2_HASH");
    assertThat(hash).isNotBlank();
    assertThat(auth.matches("python-compatibility-test", hash)).isTrue();
    assertThat(auth.matches("wrong-password", hash)).isFalse();
  }

  private ReservationPlan plan(LocalDate day) {
    return new ReservationPlan(
        device, null, null, 1, "真实数据库并发验证", null, null, day, day, null, null, null);
  }

  @Test
  void concurrentRequestsCannotOccupySameDeviceDay() throws Exception {
    LocalDate day = BusinessTime.today().plusDays(5);
    var threads = Executors.newFixedThreadPool(6);
    try {
      var barrier = new CyclicBarrier(6);
      var tasks = new ArrayList<Future<Boolean>>();
      for (int i = 0; i < 6; i++) {
        String key = "concurrent-" + suffix + "-" + i;
        tasks.add(
            threads.submit(
                () -> {
                  barrier.await();
                  try {
                    reservations.create(student, plan(day), key);
                    return true;
                  } catch (ApiError error) {
                    assertThat(error.status).isEqualTo(409);
                    return false;
                  }
                }));
      }
      int successful = 0;
      for (var task : tasks) if (task.get(20, TimeUnit.SECONDS)) successful++;
      assertThat(successful).isEqualTo(1);
      assertThat(
              db.count(
                  "SELECT COUNT(*) FROM v2_reservation_day WHERE device_id=? AND date=?",
                  device,
                  day))
          .isEqualTo(1);
    } finally {
      threads.shutdownNow();
    }
  }

  @Test
  void retriesReturnOriginalResultAndRejectChangedPayload() {
    var plan = plan(BusinessTime.today().plusDays(6));
    String key = "idempotency-" + suffix;
    Object first = reservations.create(student, plan, key);
    assertThat(db.parse(db.json(reservations.create(student, plan, key)), null))
        .isEqualTo(db.parse(db.json(first), null));
    assertThatThrownBy(
            () -> reservations.create(student, plan(BusinessTime.today().plusDays(7)), key))
        .isInstanceOfSatisfying(
            ApiError.class, e -> assertThat(e.code).isEqualTo("IDEMPOTENCY_REUSED"));
  }

  @Test
  void tenantCannotReadOtherCollegeDevice() {
    var outsider =
        new Principal(
            user, "outsider", college + 999, Set.of("STUDENT"), Set.of("device:read"), "test");
    assertThatThrownBy(() -> catalog.device(outsider, device))
        .isInstanceOfSatisfying(ApiError.class, e -> assertThat(e.status).isEqualTo(403));
  }

  @Test
  void approvedBookingCannotBeHandedOverBeforeStartDate() {
    var result =
        (Map<?, ?>)
            reservations.create(
                student, plan(BusinessTime.today().plusDays(8)), "handover-" + suffix);
    var created = (List<?>) result.get("created");
    long id = ((Number) ((Map<?, ?>) created.getFirst()).get("id")).longValue();
    lifecycle.approval(administrator, id, true, null);
    assertThatThrownBy(
            () ->
                lifecycle.handover(
                    administrator,
                    id,
                    Map.of(
                        "image_urls",
                        List.of("/api/v2/repair-uploads/not-a-real-token"),
                        "checklist",
                        List.of())))
        .isInstanceOfSatisfying(
            ApiError.class, e -> assertThat(e.code).isEqualTo("HANDOVER_DAY_INVALID"));
  }

  @Test
  void browserCookiesCsrfAndRefreshRotation() throws Exception {
    var cookies = new CookieManager(null, CookiePolicy.ACCEPT_ALL);
    var client = HttpClient.newBuilder().cookieHandler(cookies).build();
    String base = "http://127.0.0.1:" + port + "/api/v2";
    var csrf =
        client.send(
            HttpRequest.newBuilder(URI.create(base + "/auth/csrf")).GET().build(),
            HttpResponse.BodyHandlers.ofString());
    String token = json.readTree(csrf.body()).path("data").path("csrf_token").asText();
    String login =
        json.writeValueAsString(
            Map.of("username", "user-" + suffix, "password", "test-password-123"));
    var denied =
        client.send(
            HttpRequest.newBuilder(URI.create(base + "/auth/login"))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(login))
                .build(),
            HttpResponse.BodyHandlers.ofString());
    assertThat(denied.statusCode()).isEqualTo(403);
    var response =
        client.send(
            HttpRequest.newBuilder(URI.create(base + "/auth/login"))
                .header("Origin", "http://localhost:5173")
                .header("X-CSRF-Token", token)
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(login))
                .build(),
            HttpResponse.BodyHandlers.ofString());
    assertThat(response.statusCode()).withFailMessage(response.body()).isEqualTo(200);
    var me =
        client.send(
            HttpRequest.newBuilder(URI.create(base + "/auth/me")).GET().build(),
            HttpResponse.BodyHandlers.ofString());
    assertThat(me.statusCode()).isEqualTo(200);
    assertThat(json.readTree(me.body()).path("data").path("id").asLong()).isEqualTo(user);
    String nextCsrf = json.readTree(response.body()).path("data").path("csrf_token").asText();
    var refresh =
        client.send(
            HttpRequest.newBuilder(URI.create(base + "/auth/refresh"))
                .header("Origin", "http://localhost:5173")
                .header("X-CSRF-Token", nextCsrf)
                .POST(HttpRequest.BodyPublishers.noBody())
                .build(),
            HttpResponse.BodyHandlers.ofString());
    assertThat(refresh.statusCode()).withFailMessage(refresh.body()).isEqualTo(200);
  }
}
