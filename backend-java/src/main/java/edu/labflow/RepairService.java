package edu.labflow;

import java.time.*;
import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class RepairService {
  private final Database db;
  private final ScopeAccess scope;
  private final BusinessEvents events;
  private final Settings settings;
  private final DeviceLifecycle lifecycle;
  private static final String SELECT =
      "SELECT rr.*,d.name device_name,COALESCE(u.real_name,u.username) reporter_name,COALESCE(h.real_name,h.username) handler_name,(SELECT wl.created_at FROM v2_repair_worklog wl WHERE wl.report_id=rr.id AND wl.status='PENDING' ORDER BY wl.id LIMIT 1) creation_event_at FROM v2_repair_report rr JOIN device d ON d.id=rr.device_id JOIN sys_user u ON u.id=rr.reporter_id LEFT JOIN sys_user h ON h.id=rr.handler_id ";

  public RepairService(
      Database db,
      ScopeAccess scope,
      BusinessEvents events,
      Settings settings,
      DeviceLifecycle lifecycle) {
    this.db = db;
    this.scope = scope;
    this.events = events;
    this.settings = settings;
    this.lifecycle = lifecycle;
  }

  private Map<String, Object> view(long id) {
    var row = db.one(SELECT + "WHERE rr.id=?", id);
    if (row == null) throw new ApiError("REPAIR_NOT_FOUND", "报修工单不存在", 404);
    decorate(row);
    return row;
  }

  private void decorate(Map<String, Object> row) {
    row.put("image_urls", db.parse(row.get("image_urls"), null));
    // Creation events were explicitly written in UTC even when a legacy database
    // default wrote the report's created_at in its local session timezone.
    Object created = row.remove("creation_event_at");
    if (created != null) row.put("created_at", created);
    for (String field :
        List.of(
            "created_at",
            "updated_at",
            "taken_at",
            "resolved_at",
            "closed_at",
            "user_confirmed_at",
            "response_due_at",
            "resolve_due_at")) {
      if (row.get(field) instanceof LocalDateTime value)
        row.put(field, value.atOffset(ZoneOffset.UTC));
    }
  }

  private Map<String, Object> load(Principal p, long id, boolean manage) {
    var row = db.one("SELECT * FROM v2_repair_report WHERE id=? FOR UPDATE", id);
    if (row == null) throw new ApiError("REPAIR_NOT_FOUND", "报修工单不存在", 404);
    scope.device(p, Database.id(row, "device_id"), manage);
    if (!manage && Database.id(row, "reporter_id") != p.userId()) throw ApiError.forbidden();
    return row;
  }

  private long log(Principal p, long id, String status, String note, Object images) {
    return db.insert(
        "INSERT INTO v2_repair_worklog (report_id,operator_id,status,content,image_urls,created_at) VALUES (?,?,?,?,?,UTC_TIMESTAMP())",
        id,
        p.userId(),
        status,
        note,
        images == null ? null : db.json(images));
  }

  private void notify(Map<String, Object> report, String title, String content, long event) {
    events.notify(
        Database.id(report, "reporter_id"),
        (Long) report.get("college_id"),
        title,
        content,
        Database.id(report, "id"),
        "REPAIR",
        "repair:" + report.get("id") + ":event:" + event);
  }

  private void deviceStatus(Principal p, Map<String, Object> device, String status, String reason) {
    lifecycle.change(p, Database.id(device, "id"), status, reason);
  }

  @Transactional
  public Map<String, Object> createFault(
      Principal actor,
      long device,
      long reporter,
      Long reservation,
      String title,
      String note,
      Object images) {
    var d = scope.device(actor, device, true);
    if (reservation != null) {
      var existing = db.one("SELECT id FROM v2_repair_report WHERE reservation_id=?", reservation);
      if (existing != null) return view(Database.id(existing, "id"));
    }
    long id =
        db.insert(
            "INSERT INTO v2_repair_report (device_id,reservation_id,college_id,reporter_id,title,description,image_urls,status,priority,response_due_at,resolve_due_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,'PENDING','IMPORTANT',DATE_ADD(UTC_TIMESTAMP(),INTERVAL 1 DAY),DATE_ADD(UTC_TIMESTAMP(),INTERVAL 2 DAY),UTC_TIMESTAMP(),UTC_TIMESTAMP())",
            device,
            reservation,
            d.get("college_id"),
            reporter,
            title,
            note,
            images == null ? null : db.json(images));
    lifecycle.change(actor, device, "MAINTENANCE", title);
    log(actor, id, "PENDING", title, images);
    events.audit(actor, "REPAIR_CREATE_FROM_INSPECTION", "REPAIR", id, Map.of("device_id", device));
    return view(id);
  }

  @Transactional
  public Map<String, Object> create(Principal p, Map<String, Object> data) {
    p.require("repair:create");
    long deviceId = Database.id(data, "device_id");
    var device = scope.device(p, deviceId, false);
    String title = Database.str(data, "title", "").strip(),
        priority = Database.str(data, "priority", "NORMAL");
    if (title.length() < 2
        || title.length() > 200
        || !Set.of("NORMAL", "IMPORTANT", "URGENT").contains(priority))
      throw ApiError.validation("工单标题或优先级无效");
    Object images = data.get("image_urls");
    if (images instanceof List<?> urls) {
      if (urls.size() > 6) throw ApiError.validation("最多上传 6 张照片");
      for (Object url : urls)
        if (!url.toString().startsWith("https://")
            && !url.toString().startsWith("/api/v2/repair-uploads/")
            && !url.toString().startsWith("/uploads/")) throw ApiError.validation("图片地址无效");
    }
    int days =
        switch (priority) {
          case "URGENT" -> 1;
          case "IMPORTANT" -> 2;
          default -> 3;
        };
    long id =
        db.insert(
            "INSERT INTO v2_repair_report (college_id,device_id,reporter_id,title,description,image_urls,status,priority,response_due_at,resolve_due_at,created_at,updated_at) VALUES (?,?,?,?,?,?,'PENDING',?,?,?,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
            device.get("college_id"),
            deviceId,
            p.userId(),
            title,
            data.get("description"),
            images == null ? null : db.json(images),
            priority,
            BusinessTime.utcNow().plusDays(1),
            BusinessTime.utcNow().plusDays(days));
    if (!Set.of("DISABLED", "OFFLINE", "RETIRED").contains(device.get("status")))
      deviceStatus(p, device, "MAINTENANCE", "用户提交设备报修");
    var report = view(id);
    long event = log(p, id, "PENDING", "报修工单已提交", images);
    notify(report, "设备报修已提交", "等待负责人受理", event);
    events.task(
        "repair:" + id + ":sla-response",
        "REPAIR_SLA_REMINDER",
        "repair:" + id,
        (Long) device.get("college_id"),
        Map.of("report_id", id, "kind", "response"),
        BusinessTime.utcNow().plusDays(1));
    events.task(
        "repair:" + id + ":sla-resolve",
        "REPAIR_SLA_REMINDER",
        "repair:" + id,
        (Long) device.get("college_id"),
        Map.of("report_id", id, "kind", "resolve"),
        BusinessTime.utcNow().plusDays(days));
    events.audit(p, "REPAIR_CREATE", "REPAIR", id, Map.of("device_id", deviceId));
    return report;
  }

  public Map<String, Object> list(
      Principal p, Pagination page, boolean mine, String status, String priority, Boolean overdue) {
    if (mine) p.require("repair:read:own");
    else if (!p.has("repair:read:scope") && !p.has("repair:handle")) throw ApiError.forbidden();
    String where =
        scope.devicePredicate(p, "d", !mine) + (mine ? " AND rr.reporter_id=" + p.userId() : "");
    var values = new ArrayList<Object>();
    if (status != null && !status.isBlank()) {
      where += " AND rr.status=?";
      values.add(status);
    }
    if (priority != null && !priority.isBlank()) {
      where += " AND rr.priority=?";
      values.add(priority);
    }
    if (Boolean.TRUE.equals(overdue))
      where +=
          " AND ((rr.status='PENDING' AND rr.response_due_at<UTC_TIMESTAMP()) OR (rr.status IN ('PENDING','PROCESSING') AND rr.resolve_due_at<UTC_TIMESTAMP()))";
    long total =
        db.count(
            "SELECT COUNT(*) FROM v2_repair_report rr JOIN device d ON d.id=rr.device_id WHERE "
                + where,
            values.toArray());
    values.add(page.size());
    values.add(page.offset());
    String ids =
        "SELECT rr.id FROM v2_repair_report rr JOIN device d ON d.id=rr.device_id WHERE "
            + where
            + " ORDER BY rr.id DESC LIMIT ? OFFSET ?";
    var rows =
        db.rows(
            SELECT + "JOIN (" + ids + ") page_ids ON page_ids.id=rr.id ORDER BY rr.id DESC",
            values.toArray());
    rows.forEach(this::decorate);
    return page.result(rows, total);
  }

  @Transactional
  public Map<String, Object> take(Principal p, long id) {
    p.require("repair:handle");
    var report = load(p, id, true);
    if (db.execute(
            "UPDATE v2_repair_report SET status='PROCESSING',handler_id=?,taken_at=UTC_TIMESTAMP(),updated_at=UTC_TIMESTAMP() WHERE id=? AND status='PENDING'",
            p.userId(),
            id)
        != 1) throw new ApiError("INVALID_REPAIR_STATE", "工单已经受理或处理", 409);
    long event = log(p, id, "PROCESSING", "负责人已受理工单", null);
    notify(report, "报修工单已受理", "负责人开始处理设备问题", event);
    events.audit(p, "REPAIR_TAKE", "REPAIR", id, Map.of());
    return view(id);
  }

  @Transactional
  public Map<String, Object> resolve(Principal p, long id, String note, boolean reject) {
    p.require("repair:handle");
    if (note == null || note.strip().length() < 2 || note.length() > 1000)
      throw ApiError.validation("请填写处理说明");
    var report = load(p, id, true);
    String previous = Database.str(report, "status", "");
    if (!(reject ? Set.of("PENDING", "PROCESSING") : Set.of("PROCESSING")).contains(previous))
      throw new ApiError("INVALID_REPAIR_STATE", "当前工单状态不能处理", 409);
    if (report.get("handler_id") != null && Database.id(report, "handler_id") != p.userId())
      throw new ApiError("REPAIR_HANDLER_MISMATCH", "工单已由其他负责人受理", 409);
    String next = reject ? "REJECTED" : "RESOLVED";
    if (db.execute(
            "UPDATE v2_repair_report SET status=?,handler_id=?,resolution_note=?,resolved_at=UTC_TIMESTAMP(),updated_at=UTC_TIMESTAMP() WHERE id=? AND status=?",
            next,
            p.userId(),
            note.strip(),
            id,
            previous)
        != 1) throw new ApiError("REPAIR_STATE_CHANGED", "工单状态已变更", 409);
    long event = log(p, id, next, note.strip(), null);
    notify(report, "报修工单状态已更新", reject ? "工单已驳回" : "处理完成，等待用户确认", event);
    if (!reject) {
      db.execute(
          "INSERT INTO v2_outbox_task (task_key,task_type,aggregate_key,college_id,payload,status,attempts,execute_at) VALUES (?,'REPAIR_AUTO_CLOSE',?,?,?,'PENDING',0,?) ON DUPLICATE KEY UPDATE status='PENDING',attempts=0,execute_at=VALUES(execute_at),claimed_at=NULL,completed_at=NULL,last_error=NULL",
          "repair:" + id + ":auto-close",
          "repair:" + id,
          report.get("college_id"),
          db.json(Map.of("report_id", id, "user_id", report.get("reporter_id"))),
          BusinessTime.utcNow().plusDays(settings.integer("REPAIR_USER_CONFIRMATION_DAYS", 3)));
    } else restore(p, report);
    events.audit(p, "REPAIR_RESOLVE", "REPAIR", id, Map.of("status", next));
    return view(id);
  }

  private void restore(Principal p, Map<String, Object> report) {
    if (db.count(
            "SELECT COUNT(*) FROM v2_repair_report WHERE device_id=? AND status IN ('PENDING','PROCESSING','RESOLVED')",
            report.get("device_id"))
        == 0) {
      var device = scope.device(p, Database.id(report, "device_id"), false);
      if ("MAINTENANCE".equals(device.get("status")))
        deviceStatus(p, device, "IDLE", "报修闭环，恢复设备可用状态");
    }
  }

  @Transactional
  public Map<String, Object> confirm(Principal p, long id, boolean confirmed, String note) {
    p.require("repair:confirm");
    var report = load(p, id, false);
    if (!"RESOLVED".equals(report.get("status")))
      throw new ApiError("INVALID_REPAIR_STATE", "当前工单不在待确认状态", 409);
    if (!confirmed && (note == null || note.strip().isEmpty()))
      throw new ApiError("REOPEN_REASON_REQUIRED", "请填写退回处理的原因", 422);
    String next = confirmed ? "COMPLETED" : "PROCESSING";
    if (db.execute(
            "UPDATE v2_repair_report SET status=?,user_confirmed_at=UTC_TIMESTAMP(),user_confirmation_note=?,closed_at=?,updated_at=UTC_TIMESTAMP() WHERE id=? AND status='RESOLVED'",
            next,
            note,
            confirmed ? BusinessTime.utcNow() : null,
            id)
        != 1) throw new ApiError("REPAIR_STATE_CHANGED", "工单状态已变更", 409);
    db.execute(
        "UPDATE v2_outbox_task SET status='COMPLETED',completed_at=UTC_TIMESTAMP() WHERE task_key=? AND status IN ('PENDING','PROCESSING')",
        "repair:" + id + ":auto-close");
    long event = log(p, id, next, confirmed ? "用户确认维修结果" : note, null);
    if (confirmed) restore(p, report);
    notify(report, "报修确认结果", confirmed ? "工单已完成" : "用户退回继续处理", event);
    events.audit(p, "REPAIR_CONFIRM", "REPAIR", id, Map.of("confirmed", confirmed));
    return view(id);
  }

  public List<Map<String, Object>> worklogs(Principal p, long id) {
    var report = view(id);
    if (Database.id(report, "reporter_id") == p.userId())
      scope.device(p, Database.id(report, "device_id"), false);
    else scope.device(p, Database.id(report, "device_id"), true);
    var rows = db.rows("SELECT * FROM v2_repair_worklog WHERE report_id=? ORDER BY id", id);
    rows.forEach(this::decorate);
    return rows;
  }
}
