package edu.labflow;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.time.*;
import java.time.temporal.ChronoUnit;
import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ReportService {
  private final Database db;
  private final ScopeAccess scope;
  private final Settings settings;
  private final BusinessEvents events;

  public ReportService(Database db, ScopeAccess scope, Settings settings, BusinessEvents events) {
    this.db = db;
    this.scope = scope;
    this.settings = settings;
    this.events = events;
  }

  private String predicate(Principal p, Long college) {
    if (!p.manager()) throw ApiError.forbidden();
    if (college != null && !p.systemAdmin() && p.tenant() != college) throw ApiError.forbidden();
    return scope.devicePredicate(p, "d", true)
        + (college == null ? "" : " AND d.college_id=" + college);
  }

  public Map<String, Object> summary(Principal p, LocalDate start, LocalDate end, Long college) {
    p.require("report:read");
    if (end == null) end = BusinessTime.today();
    if (start == null) start = end.withDayOfMonth(1);
    if (end.isBefore(start) || ChronoUnit.DAYS.between(start, end) > 1825)
      throw ApiError.validation("运营报表日期范围应在 5 年以内");
    String where = predicate(p, college);
    var devices = db.rows("SELECT d.* FROM device d WHERE " + where);
    var reservations =
        db.rows(
            "SELECT r.* FROM reservation r JOIN device d ON d.id=r.device_id WHERE "
                + where
                + " AND r.end_date>=? AND r.start_date<=?",
            start,
            end);
    var repairs =
        db.rows(
            "SELECT rr.* FROM v2_repair_report rr JOIN device d ON d.id=rr.device_id WHERE "
                + where
                + " AND rr.created_at>=? AND rr.created_at<?",
            start.atStartOfDay(),
            end.plusDays(1).atStartOfDay());
    var bookable = new HashSet<String>();
    long maintenance = 0;
    var dates = start.datesUntil(end.plusDays(1)).toList();
    for (var device : devices) {
      long id = Database.id(device, "id");
      var prior =
          db.one(
              "SELECT new_status FROM v2_device_status_history WHERE device_id=? AND created_at<? ORDER BY created_at DESC,id DESC LIMIT 1",
              id,
              start.atStartOfDay());
      var history =
          db.rows(
              "SELECT * FROM v2_device_status_history WHERE device_id=? AND created_at>=? AND created_at<? ORDER BY created_at,id",
              id,
              start.atStartOfDay(),
              end.plusDays(1).atStartOfDay());
      var following =
          db.one(
              "SELECT old_status FROM v2_device_status_history WHERE device_id=? AND created_at>=? ORDER BY created_at,id LIMIT 1",
              id,
              end.plusDays(1).atStartOfDay());
      String state =
          prior != null
              ? prior.get("new_status").toString()
              : !history.isEmpty()
                  ? history.getFirst().get("old_status").toString()
                  : following != null
                      ? following.get("old_status").toString()
                      : device.get("status").toString();
      int index = 0;
      var blocked = new HashSet<LocalDate>();
      for (var row :
          db.rows(
              "SELECT blocked_date FROM v2_reservation_blackout WHERE active=1 AND blocked_date BETWEEN ? AND ? AND ((scope_type='DEVICE' AND scope_id=?) OR (scope_type='LAB' AND scope_id=?) OR (scope_type='COLLEGE' AND scope_id=?))",
              start,
              end,
              id,
              device.get("lab_id"),
              device.get("college_id"))) blocked.add((LocalDate) row.get("blocked_date"));
      for (var day : dates) {
        boolean good = Set.of("IDLE", "IN_USE").contains(state), down = state.equals("MAINTENANCE");
        while (index < history.size()
            && ((LocalDateTime) history.get(index).get("created_at"))
                .isBefore(day.plusDays(1).atStartOfDay())) {
          state = history.get(index++).get("new_status").toString();
          good &= Set.of("IDLE", "IN_USE").contains(state);
          down |= state.equals("MAINTENANCE");
        }
        if (down) maintenance++;
        if (good && !blocked.contains(day)) bookable.add(id + ":" + day);
      }
    }
    var occupied = new HashSet<String>();
    var actual = new HashSet<String>();
    var approvalHours = new ArrayList<Double>();
    for (var r : reservations) {
      if (!Set.of("APPROVED", "IN_USE", "COMPLETED", "NO_SHOW").contains(r.get("status"))) continue;
      LocalDate
          first =
              ((LocalDate) r.get("start_date")).isBefore(start)
                  ? start
                  : (LocalDate) r.get("start_date"),
          last = ((LocalDate) r.get("end_date")).isAfter(end) ? end : (LocalDate) r.get("end_date");
      for (var day : first.datesUntil(last.plusDays(1)).toList()) {
        String key = r.get("device_id") + ":" + day;
        if (bookable.contains(key)) {
          occupied.add(key);
          if (Set.of("IN_USE", "COMPLETED").contains(r.get("status"))
              && r.get("check_in_at") != null) actual.add(key);
        }
      }
      if (r.get("approved_at") instanceof LocalDateTime approved
          && r.get("created_at") instanceof LocalDateTime created)
        approvalHours.add(Math.max(0, Duration.between(created, approved).toSeconds() / 3600.0));
    }
    var waits =
        db.rows(
            "SELECT w.status FROM v2_reservation_waitlist w JOIN device d ON d.id=w.device_id WHERE "
                + where
                + " AND w.created_at>=? AND w.created_at<?",
            start.atStartOfDay(),
            end.plusDays(1).atStartOfDay());
    long converted = waits.stream().filter(w -> "CONFIRMED".equals(w.get("status"))).count();
    var reservationCounts = counts(reservations);
    var repairCounts = counts(repairs);
    var result = new HashMap<String, Object>();
    result.put("range", Map.of("startDate", start, "endDate", end));
    result.put("deviceCount", devices.size());
    result.put("reservationCount", reservations.size());
    result.put("reservationStatus", reservationCounts);
    result.put("repairCount", repairs.size());
    result.put("repairStatus", repairCounts);
    result.put("utilizationRate", ratio(occupied.size(), bookable.size()));
    result.put("occupancyRate", ratio(occupied.size(), bookable.size()));
    result.put("actualUsageRate", ratio(actual.size(), bookable.size()));
    result.put("bookableDeviceDays", bookable.size());
    result.put("occupiedDeviceDays", occupied.size());
    result.put("actualUsageDeviceDays", actual.size());
    result.put("maintenanceDowntimeDays", maintenance);
    result.put(
        "averageApprovalHours",
        approvalHours.stream().mapToDouble(Double::doubleValue).average().orElse(0));
    result.put("waitlistRequests", waits.size());
    result.put("waitlistConverted", converted);
    result.put("waitlistConversionRate", ratio(converted, waits.size()));
    return result;
  }

  static Map<String, Long> counts(List<Map<String, Object>> rows) {
    var result = new HashMap<String, Long>();
    for (var row : rows) result.merge(row.get("status").toString(), 1L, Long::sum);
    return result;
  }

  static double ratio(long numerator, long denominator) {
    return denominator == 0 ? 0 : Math.round((double) numerator / denominator * 10000) / 10000.0;
  }

  private String fingerprint(Principal p, Long college) {
    String where = predicate(p, college);
    var payload = new TreeMap<String, Object>();
    payload.put("college_id", p.systemAdmin() ? college : p.collegeId());
    payload.put(
        "device_ids",
        p.systemAdmin() && college == null
            ? null
            : db.rows("SELECT d.id FROM device d WHERE " + where + " ORDER BY d.id").stream()
                .map(r -> r.get("id"))
                .toList());
    return AuthService.sha256(db.json(payload));
  }

  private record Query(String sql, List<Object> values, String idColumn) {}

  private Query exportQuery(
      Principal p, String type, Map<String, Object> filters, long cursor, int limit) {
    if (!Set.of("devices", "reservations", "repairs").contains(type))
      throw new ApiError("EXPORT_TYPE_INVALID", "不支持的导出类型", 422);
    Long college = filters.get("college_id") == null ? null : Database.id(filters, "college_id");
    String where = predicate(p, college),
        alias = type.equals("devices") ? "d" : type.equals("reservations") ? "r" : "rr";
    var params = new ArrayList<Object>();
    where += " AND " + alias + ".id>?";
    params.add(cursor);
    if (filters.get("status") != null) {
      where += " AND " + alias + ".status=?";
      params.add(filters.get("status"));
    }
    if (!type.equals("devices")) {
      if (filters.get("start_date") != null) {
        where +=
            " AND " + alias + (type.equals("reservations") ? ".end_date>=?" : ".created_at>=?");
        params.add(
            type.equals("reservations")
                ? LocalDate.parse(filters.get("start_date").toString())
                : LocalDate.parse(filters.get("start_date").toString()).atStartOfDay());
      }
      if (filters.get("end_date") != null) {
        where +=
            " AND " + alias + (type.equals("reservations") ? ".start_date<=?" : ".created_at<?");
        params.add(
            type.equals("reservations")
                ? LocalDate.parse(filters.get("end_date").toString())
                : LocalDate.parse(filters.get("end_date").toString()).plusDays(1).atStartOfDay());
      }
    }
    String select =
        switch (type) {
          case "devices" ->
              "SELECT d.id _cursor,d.id `设备ID`,d.asset_code `资产编号`,d.serial_number `序列号`,d.name `设备名称`,d.brand `品牌`,d.model `型号`,d.status `状态`,d.risk_level `风险等级`,IF(d.allow_external_loan,'是','否') `允许外借`,d.purchase_date `购置日期`,d.warranty_until `保修截止`,l.name `实验室`,c.name `学院` FROM device d LEFT JOIN lab l ON l.id=d.lab_id LEFT JOIN college c ON c.id=d.college_id ";
          case "reservations" ->
              "SELECT r.id _cursor,r.id `预约ID`,d.id `设备ID`,d.asset_code `资产编号`,d.name `设备名称`,l.name `实验室`,COALESCE(u.real_name,u.username) `预约人`,c.name `学院`,r.start_date `开始日期`,r.end_date `结束日期`,r.status `状态`,r.purpose `用途`,r.purpose_category `用途类别`,r.project_reference `课程科研项目`,r.created_at `提交时间` FROM reservation r JOIN device d ON d.id=r.device_id LEFT JOIN lab l ON l.id=d.lab_id LEFT JOIN sys_user u ON u.id=r.user_id LEFT JOIN college c ON c.id=d.college_id ";
          default ->
              "SELECT rr.id _cursor,rr.id `报修ID`,d.id `设备ID`,d.asset_code `资产编号`,d.name `设备名称`,COALESCE(u.real_name,u.username) `报修人`,c.name `学院`,rr.priority `优先级`,rr.status `状态`,rr.created_at `提交时间`,rr.taken_at `受理时间`,rr.resolved_at `解决时间`,rr.closed_at `关闭时间`,TIMESTAMPDIFF(DAY,rr.created_at,rr.closed_at) `处理时长(天)` FROM v2_repair_report rr JOIN device d ON d.id=rr.device_id LEFT JOIN sys_user u ON u.id=rr.reporter_id LEFT JOIN college c ON c.id=d.college_id ";
        };
    params.add(limit);
    return new Query(
        select + "WHERE " + where + " ORDER BY " + alias + ".id LIMIT ?", params, "_cursor");
  }

  public byte[] direct(Principal p, String type, Map<String, Object> filters) {
    p.require("report:read");
    int max = settings.integer("EXPORT_SYNC_ROW_LIMIT", 1000);
    var query = exportQuery(p, type, filters, 0, max + 1);
    var rows = db.rows(query.sql(), query.values().toArray());
    if (rows.size() > max) throw new ApiError("EXPORT_ASYNC_REQUIRED", "本次导出超过同步上限，请使用异步导出", 413);
    var writer = new StringWriter();
    try {
      writeRows(writer, rows, true);
    } catch (IOException e) {
      throw new IllegalStateException(e);
    }
    return ("\uFEFF" + writer).getBytes(StandardCharsets.UTF_8);
  }

  private List<String> columns(Map<String, Object> row) {
    return row.keySet().stream().filter(k -> !k.equals("_cursor")).sorted().toList();
  }

  private void writeRows(Writer writer, List<Map<String, Object>> rows, boolean header)
      throws IOException {
    if (rows.isEmpty()) {
      if (header) writer.write("暂无数据\n");
      return;
    }
    var columns = columns(rows.getFirst());
    if (header) writer.write(String.join(",", columns) + "\r\n");
    for (var row : rows) {
      var values = new ArrayList<String>();
      for (String column : columns) {
        Object raw = row.get(column);
        String value =
            raw == null
                ? ""
                : raw instanceof LocalDateTime t ? t.toString().replace('T', ' ') : raw.toString();
        if (raw instanceof String && value.matches("(?s)^[\\s\\x00-\\x1f]*[=+@-].*"))
          value = "'" + value;
        values.add("\"" + value.replace("\"", "\"\"") + "\"");
      }
      writer.write(String.join(",", values) + "\r\n");
    }
  }

  @Transactional
  public Object request(Principal p, Map<String, Object> data) {
    p.require("report:read");
    String type = Database.str(data, "export_type", "");
    exportQuery(p, type, data, 0, 1);
    var filters = new HashMap<>(data);
    filters.remove("export_type");
    Long college = data.get("college_id") == null ? null : Database.id(data, "college_id");
    filters.put("_scope_fingerprint", fingerprint(p, college));
    long id =
        db.insert(
            "INSERT INTO v2_export_task (requester_id,college_id,export_type,filters,status,row_count) VALUES (?,?,?,?,'PENDING',0)",
            p.userId(),
            p.systemAdmin() ? college : p.collegeId(),
            type,
            db.json(filters));
    events.task(
        "export:" + id,
        "EXPORT_GENERATE",
        "export:" + id,
        p.collegeId(),
        Map.of("export_id", id),
        BusinessTime.utcNow());
    return status(p, id);
  }

  @SuppressWarnings("unchecked")
  private Map<String, Object> authorized(Principal p, long id) {
    p.require("report:read");
    var task = db.one("SELECT * FROM v2_export_task WHERE id=?", id);
    if (task == null) throw new ApiError("EXPORT_NOT_FOUND", "导出任务不存在或无权访问", 404);
    if (p.systemAdmin()) return task;
    if (Database.id(task, "requester_id") != p.userId()
        || !p.manager()
        || !Objects.equals(task.get("college_id"), p.collegeId()))
      throw new ApiError("EXPORT_NOT_FOUND", "导出任务不存在或无权访问", 404);
    var filters = (Map<String, Object>) db.parse(task.get("filters"), Map.of());
    Long college = filters.get("college_id") == null ? null : Database.id(filters, "college_id");
    if (filters.get("_scope_fingerprint") != null
        && !filters.get("_scope_fingerprint").equals(fingerprint(p, college)))
      throw new ApiError("EXPORT_NOT_FOUND", "管理范围已变更，无法访问旧导出", 404);
    return task;
  }

  public Object status(Principal p, long id) {
    var task = authorized(p, id);
    var result = new HashMap<String, Object>();
    for (String key :
        List.of("id", "export_type", "status", "row_count", "error", "created_at", "completed_at"))
      result.put(key, task.get(key));
    result.put(
        "download_url",
        "COMPLETED".equals(task.get("status")) && task.get("file_token") != null
            ? "/api/v2/reports/exports/" + id + "/download"
            : null);
    return result;
  }

  public Path download(Principal p, long id) {
    var task = authorized(p, id);
    if (!"COMPLETED".equals(task.get("status")) || task.get("file_path") == null)
      throw new ApiError("EXPORT_NOT_READY", "导出尚未完成", 409);
    Path root = settings.uploads().resolve("exports");
    Path path = Path.of(task.get("file_path").toString());
    if (!path.normalize().startsWith(root)) path = root.resolve(path.getFileName());
    try {
      if (!path.toRealPath().startsWith(root.toRealPath())) throw ApiError.forbidden();
      return path.toRealPath();
    } catch (IOException e) {
      throw ApiError.missing("导出文件");
    }
  }

  @SuppressWarnings("unchecked")
  public void generate(long id) {
    var task = db.one("SELECT * FROM v2_export_task WHERE id=?", id);
    if (task == null || "COMPLETED".equals(task.get("status"))) return;
    var user = db.one("SELECT * FROM sys_user WHERE id=? AND status=1", task.get("requester_id"));
    if (user == null) throw ApiError.forbidden();
    var roles = new HashSet<String>();
    for (var row :
        db.rows(
            "SELECT r.role_code FROM sys_role r JOIN sys_user_role ur ON ur.role_id=r.id WHERE ur.user_id=?",
            user.get("id"))) roles.add(row.get("role_code").toString());
    var permissions = new HashSet<String>();
    for (var row :
        db.rows(
            "SELECT DISTINCT perm.permission_code FROM sys_permission perm JOIN sys_role_permission rp ON rp.permission_id=perm.id JOIN sys_user_role ur ON ur.role_id=rp.role_id WHERE ur.user_id=?",
            user.get("id"))) permissions.add(row.get("permission_code").toString());
    var actor =
        new Principal(
            Database.id(user, "id"),
            user.get("username").toString(),
            user.get("college_id") == null ? null : Database.id(user, "college_id"),
            roles,
            permissions,
            "");
    actor.require("report:read");
    authorized(actor, id);
    var filters = (Map<String, Object>) db.parse(task.get("filters"), Map.of());
    String token = AuthService.random(48);
    Path root = settings.uploads().resolve("exports"), file = root.resolve(token + ".csv");
    try {
      Files.createDirectories(root);
      long cursor = 0, total = 0;
      boolean header = true;
      try (var writer =
          Files.newBufferedWriter(file, StandardCharsets.UTF_8, StandardOpenOption.CREATE_NEW)) {
        writer.write('\uFEFF');
        while (true) {
          if (Thread.currentThread().isInterrupted())
            throw new IllegalStateException("Export task cancelled");
          var query = exportQuery(actor, task.get("export_type").toString(), filters, cursor, 500);
          var rows = db.rows(query.sql(), query.values().toArray());
          writeRows(writer, rows, header);
          header = false;
          if (rows.isEmpty()) break;
          total += rows.size();
          cursor = Database.id(rows.getLast(), "_cursor");
          if (rows.size() < 500) break;
        }
      }
      authorized(actor, id);
      db.execute(
          "UPDATE v2_export_task SET status='COMPLETED',file_token=?,file_path=?,row_count=?,error=NULL,completed_at=UTC_TIMESTAMP() WHERE id=? AND status<>'COMPLETED'",
          token,
          file.toString(),
          total,
          id);
    } catch (IOException | RuntimeException e) {
      try {
        Files.deleteIfExists(file);
      } catch (IOException ignored) {
      }
      db.execute(
          "UPDATE v2_export_task SET status='FAILED',error=? WHERE id=? AND status<>'COMPLETED'",
          e.getClass().getSimpleName(),
          id);
      throw new IllegalStateException("Export generation failed", e);
    }
  }
}
