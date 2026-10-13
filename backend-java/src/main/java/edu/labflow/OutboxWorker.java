package edu.labflow;

import jakarta.annotation.PreDestroy;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Component
public class OutboxWorker {
  private final Database db;
  private final Settings settings;
  private final TransactionTemplate tx;
  private final NotificationRelay relay;
  private final NotificationService notifications;
  private final DeadlineService deadlines;
  private final WaitlistService waitlist;
  private final QuotaCache quotas;
  private final ReportService reports;
  private final ExecutorService executor;
  private final java.util.concurrent.atomic.LongAdder
      claimed = new java.util.concurrent.atomic.LongAdder(),
      failures = new java.util.concurrent.atomic.LongAdder();

  public double activeTasks() {
    return active.size();
  }

  public double claimedTasks() {
    return claimed.sum();
  }

  public double failedTasks() {
    return failures.sum();
  }

  private record Running(Future<?> future, Map<String, Object> task, long deadline) {}

  private final ConcurrentMap<Long, Running> active = new ConcurrentHashMap<>();

  public OutboxWorker(
      Database db,
      Settings settings,
      PlatformTransactionManager tm,
      NotificationRelay relay,
      NotificationService notifications,
      DeadlineService deadlines,
      WaitlistService waitlist,
      QuotaCache quotas,
      ReportService reports) {
    this.db = db;
    this.settings = settings;
    tx = new TransactionTemplate(tm);
    this.relay = relay;
    this.notifications = notifications;
    this.deadlines = deadlines;
    this.waitlist = waitlist;
    this.quotas = quotas;
    this.reports = reports;
    int concurrency = settings.integer("OUTBOX_WORKER_CONCURRENCY", 4);
    executor =
        new ThreadPoolExecutor(
            concurrency,
            concurrency,
            0,
            TimeUnit.SECONDS,
            new ArrayBlockingQueue<>(concurrency),
            new ThreadPoolExecutor.AbortPolicy());
  }

  @Scheduled(fixedDelay = 500)
  public void tick() {
    if (!settings.bool("ENABLE_WORKERS", true)) return;
    active
        .entrySet()
        .removeIf(
            entry -> {
              var running = entry.getValue();
              if (running.future().isDone()) return true;
              if (System.nanoTime() > running.deadline()) {
                running.future().cancel(true);
                failedAttempt(running.task(), "task execution timed out");
                return true;
              }
              return false;
            });
    int available = settings.integer("OUTBOX_WORKER_CONCURRENCY", 4) - active.size();
    for (int i = 0; i < available; i++) {
      var task = claim();
      if (task == null) return;
      long id = Database.id(task, "id");
      try {
        active.put(
            id,
            new Running(
                executor.submit(() -> run(task)),
                task,
                System.nanoTime()
                    + TimeUnit.SECONDS.toNanos(
                        settings.integer("OUTBOX_TASK_TIMEOUT_SECONDS", 240))));
      } catch (RejectedExecutionException e) {
        db.execute(
            "UPDATE v2_outbox_task SET status='PENDING',claimed_at=NULL,attempts=attempts-1 WHERE id=? AND status='PROCESSING' AND claimed_at=?",
            id,
            task.get("claimed_at"));
        return;
      }
    }
  }

  public Map<String, Object> claim() {
    return tx.execute(
        status -> {
          int lease = settings.integer("OUTBOX_CLAIM_TIMEOUT_SECONDS", 300);
          var task =
              db.one(
                  "SELECT t.* FROM v2_outbox_task t WHERE ((t.status='PENDING' AND t.execute_at<=UTC_TIMESTAMP()) OR (t.status='PROCESSING' AND t.claimed_at<DATE_SUB(UTC_TIMESTAMP(),INTERVAL ? SECOND))) AND NOT EXISTS (SELECT 1 FROM v2_outbox_task previous WHERE previous.aggregate_key=t.aggregate_key AND previous.id<t.id AND (previous.status='PROCESSING' OR (previous.status='PENDING' AND previous.execute_at<=UTC_TIMESTAMP()))) ORDER BY t.execute_at,t.id LIMIT 1 FOR UPDATE SKIP LOCKED",
                  lease);
          if (task == null) return null;
          if (Database.id(task, "attempts") >= settings.integer("OUTBOX_MAX_ATTEMPTS", 5)) {
            db.execute(
                "UPDATE v2_outbox_task SET status='FAILED',last_error='lease expired after maximum attempts' WHERE id=?",
                task.get("id"));
            return null;
          }
          db.execute(
              "UPDATE v2_outbox_task SET status='PROCESSING',attempts=attempts+1,claimed_at=UTC_TIMESTAMP() WHERE id=?",
              task.get("id"));
          claimed.increment();
          return db.one("SELECT * FROM v2_outbox_task WHERE id=?", task.get("id"));
        });
  }

  public void run(Map<String, Object> task) {
    try {
      dispatch(task);
      db.execute(
          "UPDATE v2_outbox_task SET status='COMPLETED',completed_at=UTC_TIMESTAMP(),last_error=NULL WHERE id=? AND status='PROCESSING' AND claimed_at=?",
          task.get("id"),
          task.get("claimed_at"));
    } catch (RuntimeException e) {
      failedAttempt(task, e.getClass().getSimpleName());
    }
  }

  private void failedAttempt(Map<String, Object> task, String error) {
    int attempts = (int) Database.id(task, "attempts");
    String status = attempts >= settings.integer("OUTBOX_MAX_ATTEMPTS", 5) ? "FAILED" : "PENDING";
    long seconds =
        Math.min(
            3600,
            (long) settings.integer("OUTBOX_RETRY_BASE_SECONDS", 5)
                * (1L << Math.min(attempts - 1, 10)));
    int changed =
        db.execute(
            "UPDATE v2_outbox_task SET status=?,execute_at=DATE_ADD(UTC_TIMESTAMP(),INTERVAL ? SECOND),last_error=?,claimed_at=NULL WHERE id=? AND status='PROCESSING' AND claimed_at=?",
            status,
            seconds,
            error,
            task.get("id"),
            task.get("claimed_at"));
    if (changed == 1) failures.increment();
  }

  @SuppressWarnings("unchecked")
  private void dispatch(Map<String, Object> task) {
    var payload = (Map<String, Object>) db.parse(task.get("payload"), Map.of());
    String type = task.get("task_type").toString(), key = task.get("task_key").toString();
    switch (type) {
      case "NOTIFICATION" -> {
        var notification =
            tx.execute(
                status -> {
                  long user = Database.id(payload, "user_id");
                  db.one("SELECT id FROM sys_user WHERE id=? FOR UPDATE", user);
                  var existing = db.one("SELECT * FROM notification WHERE source_task_key=?", key);
                  if (existing != null) return existing;
                  long sequence =
                      db.count(
                          "SELECT COALESCE(MAX(delivery_sequence),0)+1 FROM notification WHERE user_id=?",
                          user);
                  long id =
                      db.insert(
                          "INSERT INTO notification (user_id,college_id,type,title,content,related_id,related_type,source_task_key,is_read,delivery_sequence) VALUES (?,?,?,?,?,?,?,?,0,?)",
                          user,
                          payload.get("college_id"),
                          payload.getOrDefault("type", "SYSTEM"),
                          payload.getOrDefault("title", "系统通知"),
                          payload.getOrDefault("content", ""),
                          payload.get("related_id"),
                          payload.get("related_type"),
                          key,
                          sequence);
                  return db.one("SELECT * FROM notification WHERE id=?", id);
                });
        var visible = notifications.publicRow(notification);
        visible.put("deliverySequence", notification.get("delivery_sequence"));
        visible.put("eventType", "notification");
        relay.publish(Database.id(notification, "user_id"), visible, key);
      }
      case "NOTIFICATION_READ_STATE" ->
          relay.publish(
              Database.id(payload, "user_id"),
              Map.of("eventType", "read_state_changed", "userId", payload.get("user_id")),
              key);
      case "RESERVATION_UNCLAIMED_CANCEL" ->
          deadlines.cancelUnclaimed(Database.id(payload, "reservation_id"));
      case "REPAIR_AUTO_CLOSE" -> deadlines.autoCloseRepair(Database.id(payload, "report_id"));
      case "WAITLIST_PROMOTE" -> {
        long device = Database.id(payload, "device_id");
        if (payload.get("reservation_date") != null)
          waitlist.promote(device, LocalDate.parse(payload.get("reservation_date").toString()));
        else if (payload.get("dates") instanceof List<?> days)
          for (Object day : days) waitlist.promote(device, LocalDate.parse(day.toString()));
        else throw new IllegalArgumentException("Missing waitlist date");
      }
      case "WAITLIST_OFFER_EXPIRE" -> waitlist.expire(Database.id(payload, "waitlist_id"));
      case "RESERVATION_QUOTA_RECONCILE" -> {
        if (payload.get("dates") instanceof List<?> values)
          quotas.reconcile(
              Database.id(payload, "pool_id"),
              values.stream().map(v -> LocalDate.parse(v.toString())).sorted().toList());
      }
      case "REPAIR_SLA_REMINDER" -> {
        var report = db.one("SELECT * FROM v2_repair_report WHERE id=?", payload.get("report_id"));
        String kind = Database.str(payload, "kind", "resolve");
        if (report != null
            && (kind.equals("response") && "PENDING".equals(report.get("status"))
                || kind.equals("resolve")
                    && Set.of("PENDING", "PROCESSING").contains(report.get("status"))))
          deadlines.notifyManagers(
              Database.id(report, "device_id"),
              "报修工单已超时",
              report.get("title").toString(),
              Database.id(report, "id"),
              "REPAIR_SLA");
      }
      case "EXPORT_GENERATE" -> reports.generate(Database.id(payload, "export_id"));
      case "CACHE_BUMP" -> relay.bumpCatalogVersion(Database.str(payload, "scope", ""));
      default -> throw new IllegalArgumentException("Unsupported Outbox type: " + type);
    }
  }

  public List<Map<String, Object>> failed(Principal p) {
    if (!p.systemAdmin()) throw ApiError.forbidden();
    return db.rows(
        "SELECT id,task_key,task_type,aggregate_key,attempts,last_error,execute_at FROM v2_outbox_task WHERE status='FAILED' ORDER BY id DESC LIMIT 100");
  }

  public Object retry(Principal p, long id) {
    if (!p.systemAdmin()) throw ApiError.forbidden();
    if (db.execute(
            "UPDATE v2_outbox_task SET status='PENDING',attempts=0,execute_at=UTC_TIMESTAMP(),claimed_at=NULL,completed_at=NULL,last_error=NULL WHERE id=? AND status='FAILED'",
            id)
        != 1) throw new ApiError("OUTBOX_NOT_FOUND", "失败任务不存在或已处理", 404);
    return Map.of("id", id, "status", "PENDING");
  }

  @PreDestroy
  public void shutdown() {
    executor.shutdownNow();
  }
}
