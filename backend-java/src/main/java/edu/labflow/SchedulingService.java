package edu.labflow;

import java.time.LocalDate;
import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class SchedulingService {
  private final Database db;
  private final ScopeAccess scope;
  private final BusinessEvents events;

  public SchedulingService(Database db, ScopeAccess scope, BusinessEvents events) {
    this.db = db;
    this.scope = scope;
    this.events = events;
  }

  public String predicate(Principal p, String alias, boolean manage) {
    if (p.systemAdmin()) return "1=1";
    long tenant = p.tenant();
    String college = manage ? " AND manager_id=" + p.userId() : "";
    String lab =
        manage
            ? " AND (manager_id="
                + p.userId()
                + " OR EXISTS(SELECT 1 FROM college mc WHERE mc.id=lab.college_id AND mc.manager_id="
                + p.userId()
                + "))"
            : "";
    return "(("
        + alias
        + ".scope_type='COLLEGE' AND "
        + alias
        + ".scope_id IN (SELECT id FROM college WHERE id="
        + tenant
        + college
        + ")) OR ("
        + alias
        + ".scope_type='LAB' AND "
        + alias
        + ".scope_id IN (SELECT id FROM lab WHERE college_id="
        + tenant
        + lab
        + ")) OR ("
        + alias
        + ".scope_type='DEVICE' AND "
        + alias
        + ".scope_id IN (SELECT d.id FROM device d WHERE "
        + scope.devicePredicate(p, "d", manage)
        + ")))";
  }

  private Map<String, Object> named(Map<String, Object> row) {
    String type = row.get("scope_type").toString();
    String table =
        switch (type) {
          case "COLLEGE" -> "college";
          case "LAB" -> "lab";
          case "DEVICE" -> "device";
          default -> null;
        };
    var resource =
        table == null
            ? null
            : db.one("SELECT name FROM " + table + " WHERE id=?", row.get("scope_id"));
    row.put("scope_name", table == null ? "全校默认" : resource == null ? null : resource.get("name"));
    return row;
  }

  public Map<String, Object> rules(
      Principal p, Pagination page, String type, Long scopeId, String category) {
    p.require("reservation-rule:manage");
    String where = predicate(p, "r", true);
    var values = new ArrayList<Object>();
    if (type != null) {
      where += " AND r.scope_type=?";
      values.add(type);
    }
    if (scopeId != null) {
      where += " AND r.scope_id=?";
      values.add(scopeId);
    }
    if (category != null) {
      where += " AND r.user_category=?";
      values.add(category);
    }
    long total =
        db.count("SELECT COUNT(*) FROM v2_reservation_rule r WHERE " + where, values.toArray());
    values.add(page.size());
    values.add(page.offset());
    String ids =
        "SELECT r.id FROM v2_reservation_rule r WHERE "
            + where
            + " ORDER BY r.id DESC LIMIT ? OFFSET ?";
    var rows =
        db.rows(
            "SELECT r.* FROM v2_reservation_rule r JOIN ("
                + ids
                + ") page_ids ON page_ids.id=r.id ORDER BY r.id DESC",
            values.toArray());
    rows.forEach(this::named);
    return page.result(rows, total);
  }

  @Transactional
  public Object rule(Principal p, Map<String, Object> data) {
    p.require("reservation-rule:manage");
    String type = Database.str(data, "scope_type", "");
    long id = Database.id(data, "scope_id");
    if (!scope.manages(p, type, id)) throw ApiError.forbidden();
    String category = Database.str(data, "user_category", "");
    if (!Set.of("ALL", "STUDENT", "LAB_ADMIN").contains(category))
      throw ApiError.validation("用户类别无效");
    Object days = data.get("max_booking_days"),
        advance = data.get("max_advance_days"),
        approval = data.get("approval_required");
    if (days == null && advance == null && approval == null)
      throw ApiError.validation("至少配置一项预约限制");
    if (days != null && (((Number) days).intValue() < 1 || ((Number) days).intValue() > 31)
        || advance != null
            && (((Number) advance).intValue() < 1 || ((Number) advance).intValue() > 365)
        || approval != null && !(approval instanceof Boolean))
      throw ApiError.validation("预约规则参数无效");
    db.execute(
        "INSERT INTO v2_reservation_rule (scope_type,scope_id,user_category,max_booking_days,max_advance_days,approval_required,created_by,updated_by) VALUES (?,?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE max_booking_days=VALUES(max_booking_days),max_advance_days=VALUES(max_advance_days),approval_required=VALUES(approval_required),updated_by=VALUES(updated_by),updated_at=UTC_TIMESTAMP()",
        type,
        id,
        category,
        days,
        advance,
        approval,
        p.userId(),
        p.userId());
    return named(
        db.one(
            "SELECT * FROM v2_reservation_rule WHERE scope_type=? AND scope_id=? AND user_category=?",
            type,
            id,
            category));
  }

  @Transactional
  public void deleteRule(Principal p, long id) {
    p.require("reservation-rule:manage");
    var row = db.one("SELECT * FROM v2_reservation_rule WHERE id=? FOR UPDATE", id);
    if (row == null) throw ApiError.missing("预约规则");
    if (!scope.manages(p, row.get("scope_type").toString(), Database.id(row, "scope_id")))
      throw ApiError.forbidden();
    db.execute("DELETE FROM v2_reservation_rule WHERE id=?", id);
  }

  public List<Map<String, Object>> blackouts(Principal p, LocalDate start, LocalDate end) {
    String where = "b.active=1 AND " + predicate(p, "b", false);
    var values = new ArrayList<Object>();
    if (start != null) {
      where += " AND b.blocked_date>=?";
      values.add(start);
    }
    if (end != null) {
      where += " AND b.blocked_date<=?";
      values.add(end);
    }
    var rows =
        db.rows(
            "SELECT b.* FROM v2_reservation_blackout b WHERE "
                + where
                + " ORDER BY b.blocked_date,b.id",
            values.toArray());
    rows.forEach(this::named);
    return rows;
  }

  @Transactional
  public Object blackout(Principal p, Map<String, Object> data) {
    p.require("reservation-rule:manage");
    String type = Database.str(data, "scope_type", "");
    long scopeId = Database.id(data, "scope_id");
    if (!Set.of("COLLEGE", "LAB", "DEVICE").contains(type) || !scope.manages(p, type, scopeId))
      throw ApiError.forbidden();
    LocalDate day = LocalDate.parse(Database.str(data, "blocked_date", ""));
    String reason = Database.str(data, "reason", "").strip();
    if (reason.length() < 2 || reason.length() > 500) throw ApiError.validation("请填写不可预约原因");
    String devices =
        switch (type) {
          case "DEVICE" -> "id=" + scopeId;
          case "LAB" -> "lab_id=" + scopeId;
          default -> "college_id=" + scopeId;
        };
    db.rows("SELECT id FROM device WHERE " + devices + " ORDER BY id FOR UPDATE");
    if (db.count(
            "SELECT COUNT(*) FROM v2_reservation_day WHERE date=? AND device_id IN (SELECT id FROM device WHERE "
                + devices
                + ")",
            day)
        > 0) throw new ApiError("BLACKOUT_CONFLICT", "该日期存在预约，请先处理预约", 409);
    long id =
        db.insert(
            "INSERT INTO v2_reservation_blackout (scope_type,scope_id,blocked_date,reason,active,created_by) VALUES (?,?,?,?,1,?)",
            type,
            scopeId,
            day,
            reason,
            p.userId());
    events.audit(p, "BLACKOUT_CREATE", "BLACKOUT", id, Map.of());
    return named(db.one("SELECT * FROM v2_reservation_blackout WHERE id=?", id));
  }

  @Transactional
  public void deleteBlackout(Principal p, long id) {
    p.require("reservation-rule:manage");
    var row = db.one("SELECT * FROM v2_reservation_blackout WHERE id=?", id);
    if (row == null) throw ApiError.missing("不可预约日");
    if (!scope.manages(p, row.get("scope_type").toString(), Database.id(row, "scope_id")))
      throw ApiError.forbidden();
    db.execute("UPDATE v2_reservation_blackout SET active=0 WHERE id=?", id);
  }
}
