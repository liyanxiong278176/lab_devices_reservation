package edu.labflow;

import java.time.*;
import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class MaintenanceService {
  private final Database db;
  private final ScopeAccess scope;
  private final BusinessEvents events;
  private final RepairService repairs;
  private static final String PLANS =
      "SELECT mp.*,d.name device_name,d.asset_code device_asset_code FROM v2_device_maintenance_plan mp JOIN device d ON d.id=mp.device_id ";
  private static final String RECORDS =
      "SELECT mr.*,COALESCE(u.real_name,u.username) performed_by_name,a.asset_token evidence_asset_token,a.original_name evidence_name,a.content_type evidence_content_type,a.size_bytes evidence_size_bytes FROM v2_device_maintenance_record mr LEFT JOIN sys_user u ON u.id=mr.performed_by LEFT JOIN v2_upload_asset a ON a.id=mr.evidence_asset_id ";

  public MaintenanceService(
      Database db, ScopeAccess scope, BusinessEvents events, RepairService repairs) {
    this.db = db;
    this.scope = scope;
    this.events = events;
    this.repairs = repairs;
  }

  private Map<String, Object> plan(long id) {
    var p = db.one(PLANS + "WHERE mp.id=?", id);
    if (p == null) throw new ApiError("MAINTENANCE_PLAN_NOT_FOUND", "维护计划不存在", 404);
    boolean blocked =
        ReservationPolicy.truth(p.get("active"))
            && !"ROUTINE".equals(p.get("plan_type"))
            && ((LocalDate) p.get("due_date")).isBefore(BusinessTime.today());
    p.put("temporarily_unbookable", blocked);
    p.put("unbookable_reason", blocked ? "必需校准或安全检查已逾期" : null);
    return p;
  }

  private Map<String, Object> managed(Principal p, long id) {
    p.require("maintenance:manage");
    var plan = plan(id);
    scope.device(p, Database.id(plan, "device_id"), true);
    return plan;
  }

  private Map<String, Object> record(long id) {
    var row = db.one(RECORDS + "WHERE mr.id=?", id);
    row.put(
        "evidence_url",
        row.get("evidence_asset_token") == null
            ? null
            : "/api/v2/maintenance-evidence/" + row.get("evidence_asset_token"));
    return row;
  }

  public Map<String, Object> plans(Principal p, Pagination page, Long device, Boolean active) {
    p.require("maintenance:manage");
    String where = scope.devicePredicate(p, "d", true);
    var params = new ArrayList<Object>();
    if (device != null) {
      where += " AND mp.device_id=?";
      params.add(device);
    }
    if (active != null) {
      where += " AND mp.active=?";
      params.add(active);
    }
    long total =
        db.count(
            "SELECT COUNT(*) FROM v2_device_maintenance_plan mp JOIN device d ON d.id=mp.device_id WHERE "
                + where,
            params.toArray());
    params.add(page.size());
    params.add(page.offset());
    var ids =
        db.rows(
            "SELECT mp.id FROM v2_device_maintenance_plan mp JOIN device d ON d.id=mp.device_id WHERE "
                + where
                + " ORDER BY mp.id DESC LIMIT ? OFFSET ?",
            params.toArray());
    return page.result(ids.stream().map(r -> plan(Database.id(r, "id"))).toList(), total);
  }

  private LocalDate date(Map<String, Object> data, String key, boolean required) {
    var value = data.get(key);
    if (value == null) {
      if (required) throw ApiError.validation("缺少日期 " + key);
      return null;
    }
    return LocalDate.parse(value.toString());
  }

  @Transactional
  public Object write(Principal p, Long id, long deviceId, Map<String, Object> data) {
    p.require("maintenance:manage");
    if (id != null) deviceId = Database.id(managed(p, id), "device_id");
    var device = scope.device(p, deviceId, true);
    db.one("SELECT id FROM device WHERE id=? FOR UPDATE", deviceId);
    String type = Database.str(data, "plan_type", ""),
        title = Database.str(data, "title", "").strip(),
        unit = Database.str(data, "interval_unit", "");
    int amount = (int) Database.id(data, "interval_value");
    if (!Set.of("ROUTINE", "CALIBRATION", "SAFETY_CHECK").contains(type)
        || !Set.of("DAY", "MONTH", "YEAR").contains(unit)
        || amount < 1
        || amount > 365
        || title.length() < 2
        || title.length() > 160) throw ApiError.validation("维护计划参数无效");
    LocalDate due = date(data, "due_date", true),
        start = date(data, "downtime_start", false),
        end = date(data, "downtime_end", false);
    if ((start == null) != (end == null) || start != null && end.isBefore(start))
      throw ApiError.validation("停机日期范围无效");
    boolean active = ReservationPolicy.truth(data.getOrDefault("active", true));
    if (active
        && start != null
        && db.count(
                "SELECT COUNT(*) FROM v2_reservation_day WHERE device_id=? AND date BETWEEN ? AND ?",
                deviceId,
                start,
                end)
            > 0) throw new ApiError("MAINTENANCE_DOWNTIME_CONFLICT", "计划停机日期存在预约，请先处理预约", 409);
    if (id == null)
      id =
          db.insert(
              "INSERT INTO v2_device_maintenance_plan (device_id,college_id,plan_type,title,interval_value,interval_unit,due_date,downtime_start,downtime_end,active,created_by,updated_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
              deviceId,
              device.get("college_id"),
              type,
              title,
              amount,
              unit,
              due,
              start,
              end,
              active,
              p.userId(),
              p.userId());
    else
      db.execute(
          "UPDATE v2_device_maintenance_plan SET plan_type=?,title=?,interval_value=?,interval_unit=?,due_date=?,downtime_start=?,downtime_end=?,active=?,updated_by=?,updated_at=UTC_TIMESTAMP(),due_notice_sent_at=NULL WHERE id=?",
          type,
          title,
          amount,
          unit,
          due,
          start,
          end,
          active,
          p.userId(),
          id);
    if (active) schedule(plan(id));
    events.audit(p, "MAINTENANCE_PLAN_WRITE", "MAINTENANCE_PLAN", id, Map.of());
    return plan(id);
  }

  private void schedule(Map<String, Object> plan) {
    events.task(
        "maintenance:" + plan.get("id") + ":due:" + plan.get("due_date"),
        "MAINTENANCE_DUE",
        "device:" + plan.get("device_id"),
        (Long) plan.get("college_id"),
        Map.of("plan_id", plan.get("id"), "due_date", plan.get("due_date").toString()),
        ((LocalDate) plan.get("due_date"))
            .atStartOfDay(BusinessTime.ZONE)
            .withZoneSameInstant(ZoneOffset.UTC)
            .toLocalDateTime());
  }

  public Map<String, Object> records(Principal p, long id, Pagination page) {
    managed(p, id);
    long total = db.count("SELECT COUNT(*) FROM v2_device_maintenance_record WHERE plan_id=?", id);
    var ids =
        db.rows(
            "SELECT id FROM v2_device_maintenance_record WHERE plan_id=? ORDER BY id DESC LIMIT ? OFFSET ?",
            id,
            page.size(),
            page.offset());
    return page.result(ids.stream().map(r -> record(Database.id(r, "id"))).toList(), total);
  }

  @Transactional
  public Object complete(Principal p, long id, Map<String, Object> data, String key) {
    if (key == null || key.isBlank() || key.length() > 128) throw ApiError.validation("需要有效幂等键");
    var plan = managed(p, id);
    db.one("SELECT id FROM device WHERE id=? FOR UPDATE", plan.get("device_id"));
    plan = db.one("SELECT * FROM v2_device_maintenance_plan WHERE id=? FOR UPDATE", id);
    if (!ReservationPolicy.truth(plan.get("active")))
      throw new ApiError("MAINTENANCE_PLAN_INACTIVE", "维护计划已停用", 409);
    var evidence =
        data.get("evidence_asset_token") == null
            ? null
            : db.one(
                "SELECT * FROM v2_upload_asset WHERE asset_token=? AND user_id=? AND (college_id=? OR (college_id IS NULL AND "
                    + (p.systemAdmin() ? "1=1" : "1=0")
                    + "))",
                data.get("evidence_asset_token"),
                p.userId(),
                plan.get("college_id"));
    if (data.get("evidence_asset_token") != null && evidence == null) throw ApiError.forbidden();
    var normalized = new TreeMap<String, Object>();
    for (String field :
        List.of("cycle_due_date", "completed_date", "result", "notes", "evidence_asset_token"))
      normalized.put(field, data.get(field));
    String note = Database.str(data, "notes", "").strip();
    normalized.put("notes", note.isEmpty() ? null : note);
    normalized.put("evidence_asset_id", evidence == null ? null : evidence.get("id"));
    String digest =
        AuthService.sha256(
            "{"
                + String.join(
                    ", ",
                    normalized.entrySet().stream()
                        .map(e -> db.json(e.getKey()) + ": " + db.json(e.getValue()))
                        .toList())
                + "}");
    var replay =
        db.one(
            "SELECT * FROM v2_device_maintenance_record WHERE plan_id=? AND idempotency_key=?",
            id,
            key);
    if (replay != null) {
      if (!digest.equals(replay.get("request_hash")))
        throw new ApiError("IDEMPOTENCY_REUSED", "幂等键已用于其他请求", 409);
      return record(Database.id(replay, "id"));
    }
    LocalDate cycle = date(data, "cycle_due_date", true),
        completed = date(data, "completed_date", true);
    String result = Database.str(data, "result", "");
    if (!cycle.equals(plan.get("due_date")))
      throw new ApiError("MAINTENANCE_CYCLE_CHANGED", "维护周期已变更，请刷新", 409);
    if (completed.isAfter(BusinessTime.today()) || !Set.of("PASSED", "FAILED").contains(result))
      throw ApiError.validation("完成日期或结果无效");
    String notes = Database.str(data, "notes", null);
    if (result.equals("FAILED") && (notes == null || notes.isBlank()))
      throw ApiError.validation("检查不合格时请填写原因");
    var previous =
        db.one(
            "SELECT * FROM v2_device_maintenance_record WHERE plan_id=? AND cycle_due_date=? ORDER BY id DESC LIMIT 1",
            id,
            cycle);
    if (previous != null
        && (!"FAILED".equals(previous.get("result"))
            || previous.get("repair_report_id") == null
            || db.count(
                    "SELECT COUNT(*) FROM v2_repair_report WHERE id=? AND status='COMPLETED'",
                    previous.get("repair_report_id"))
                != 1))
      throw new ApiError("MAINTENANCE_REPAIR_NOT_COMPLETED", "本周期已记录或关联报修尚未完成", 409);
    if (!"ROUTINE".equals(plan.get("plan_type")) && evidence == null)
      throw new ApiError("MAINTENANCE_EVIDENCE_REQUIRED", "校准与安全检查必须上传凭证", 422);
    long record =
        db.insert(
            "INSERT INTO v2_device_maintenance_record (plan_id,device_id,college_id,cycle_due_date,completed_date,downtime_start,downtime_end,result,notes,performed_by,evidence_asset_id,idempotency_key,request_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            id,
            plan.get("device_id"),
            plan.get("college_id"),
            cycle,
            completed,
            plan.get("downtime_start"),
            plan.get("downtime_end"),
            result,
            notes,
            p.userId(),
            evidence == null ? null : evidence.get("id"),
            key,
            digest);
    if (result.equals("PASSED")) {
      int amount = (int) Database.id(plan, "interval_value");
      LocalDate next =
          switch (plan.get("interval_unit").toString()) {
            case "DAY" -> completed.plusDays(amount);
            case "MONTH" -> completed.plusMonths(amount);
            default -> completed.plusYears(amount);
          };
      db.execute(
          "UPDATE v2_device_maintenance_plan SET due_date=?,downtime_start=NULL,downtime_end=NULL,due_notice_sent_at=NULL,updated_by=?,updated_at=UTC_TIMESTAMP() WHERE id=? AND due_date=?",
          next,
          p.userId(),
          id,
          cycle);
      schedule(plan(id));
    } else {
      var request = new HashMap<String, Object>();
      request.put("device_id", plan.get("device_id"));
      request.put("title", plan.get("title") + "检查不合格");
      request.put("description", notes);
      request.put("priority", "IMPORTANT");
      var fault =
          repairs.createFault(
              p,
              Database.id(plan, "device_id"),
              p.userId(),
              null,
              plan.get("title") + "检查不合格",
              notes,
              null);
      db.execute(
          "UPDATE v2_device_maintenance_record SET repair_report_id=? WHERE id=?",
          fault.get("id"),
          record);
    }
    events.audit(p, "MAINTENANCE_COMPLETE", "MAINTENANCE_RECORD", record, Map.of("result", result));
    return record(record);
  }
}
