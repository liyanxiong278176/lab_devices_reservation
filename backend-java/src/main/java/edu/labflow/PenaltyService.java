package edu.labflow;

import java.time.*;
import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PenaltyService {
  private final Database db;
  private final ScopeAccess scope;
  private final BusinessEvents events;
  private static final String CASES =
      "SELECT pc.*,d.name device_name,l.name lab_name,COALESCE(u.real_name,u.username) user_name FROM v2_penalty_case pc JOIN device d ON d.id=pc.device_id LEFT JOIN lab l ON l.id=pc.lab_id JOIN sys_user u ON u.id=pc.user_id ";

  public PenaltyService(Database db, ScopeAccess scope, BusinessEvents events) {
    this.db = db;
    this.scope = scope;
    this.events = events;
  }

  private boolean head(Principal p, long college) {
    return db.count("SELECT COUNT(*) FROM college WHERE id=? AND manager_id=?", college, p.userId())
        == 1;
  }

  private void collegeAdmin(Principal p, long college) {
    if (p.systemAdmin()
        || p.collegeId() == null
        || p.tenant() != college
        || !head(p, college) && !p.roles().contains("LAB_ADMIN")) throw ApiError.forbidden();
  }

  public Map<String, Object> bounds(Principal p) {
    if (!p.systemAdmin()) throw ApiError.forbidden();
    return bounds();
  }

  private Map<String, Object> bounds() {
    var row = db.one("SELECT minimum_days,maximum_days FROM v2_penalty_grace_bounds WHERE id=1");
    return row == null ? new HashMap<>(Map.of("minimum_days", 0, "maximum_days", 30)) : row;
  }

  @Transactional
  public Object bounds(Principal p, int min, int max) {
    if (!p.systemAdmin()) throw ApiError.forbidden();
    if (min < 0 || max < min || max > 365) throw ApiError.validation("宽限期范围无效");
    db.execute(
        "INSERT INTO v2_penalty_grace_bounds (id,minimum_days,maximum_days,updated_by) VALUES (1,?,?,?) ON DUPLICATE KEY UPDATE minimum_days=VALUES(minimum_days),maximum_days=VALUES(maximum_days),updated_by=VALUES(updated_by),updated_at=UTC_TIMESTAMP()",
        min,
        max,
        p.userId());
    events.audit(
        p, "PENALTY_GRACE_BOUNDS", "SYSTEM", 1, Map.of("minimum_days", min, "maximum_days", max));
    return bounds();
  }

  public Map<String, Object> policy(Principal p) {
    long college = p.tenant();
    var row =
        db.one(
            "SELECT * FROM v2_penalty_rule_version WHERE college_id=? ORDER BY version DESC LIMIT 1",
            college);
    var result = new HashMap<String, Object>();
    result.put("college_id", college);
    result.put("version", row == null ? null : row.get("version"));
    result.put("effective_at", row == null ? null : row.get("effective_at"));
    result.put("grace_days", row == null ? null : row.get("grace_days"));
    result.put(
        "tiers",
        row == null
            ? Map.of(
                "NO_SHOW", List.of(), "OVERDUE_RETURN", List.of(), "MANUAL_VIOLATION", List.of())
            : db.parse(row.get("tiers"), Map.of()));
    result.put("can_manage", !p.systemAdmin() && head(p, college));
    result.put(
        "can_review", !p.systemAdmin() && (head(p, college) || p.roles().contains("LAB_ADMIN")));
    var bounds = bounds();
    result.put("minimum_grace_days", bounds.get("minimum_days"));
    result.put("maximum_grace_days", bounds.get("maximum_days"));
    return result;
  }

  @Transactional
  public Object policy(Principal p, Map<String, Object> data) {
    long college = p.tenant();
    if (p.systemAdmin() || !head(p, college)) throw ApiError.forbidden();
    int grace = (int) Database.id(data, "grace_days");
    var bounds = bounds();
    if (grace < Database.id(bounds, "minimum_days") || grace > Database.id(bounds, "maximum_days"))
      throw new ApiError("GRACE_PERIOD_OUT_OF_RANGE", "逾期宽限期超出全校允许范围", 422);
    if (!(data.get("tiers") instanceof Map<?, ?> values)) throw ApiError.validation("处罚阶梯格式无效");
    var normalized = new HashMap<String, Object>();
    for (Object key : values.keySet())
      if (!Set.of("NO_SHOW", "OVERDUE_RETURN", "MANUAL_VIOLATION").contains(key))
        throw ApiError.validation("违规类型无效");
    for (String type : List.of("NO_SHOW", "OVERDUE_RETURN", "MANUAL_VIOLATION")) {
      Object raw = values.get(type);
      if (raw == null) raw = List.of();
      if (!(raw instanceof List<?> tiers)
          || tiers.size() > 20
          || !type.equals("MANUAL_VIOLATION") && tiers.isEmpty())
        throw ApiError.validation("处罚阶梯无效");
      var rows = new ArrayList<Map<String, Object>>();
      int index = 0;
      for (Object tier : tiers) {
        index++;
        if (!(tier instanceof Map<?, ?> item)
            || !(item.get("points") instanceof Number points)
            || !(item.get("block_days") instanceof Number block)
            || points.intValue() < 0
            || points.intValue() > 100
            || block.intValue() < 0
            || block.intValue() > 365
            || item.get("occurrence") != null
                && ((Number) item.get("occurrence")).intValue() != index)
          throw ApiError.validation("处罚阶梯数值无效");
        rows.add(
            Map.of(
                "occurrence", index, "points", points.intValue(), "block_days", block.intValue()));
      }
      normalized.put(type, rows);
    }
    db.one("SELECT id FROM college WHERE id=? FOR UPDATE", college);
    long version =
        db.count(
            "SELECT COALESCE(MAX(version),0)+1 FROM v2_penalty_rule_version WHERE college_id=?",
            college);
    long id =
        db.insert(
            "INSERT INTO v2_penalty_rule_version (college_id,version,effective_at,grace_days,tiers,created_by) VALUES (?,?,UTC_TIMESTAMP(),?,?,?)",
            college,
            version,
            grace,
            db.json(normalized),
            p.userId());
    events.audit(p, "PENALTY_POLICY_CREATE", "PENALTY_RULE", id, Map.of("version", version));
    return policy(p);
  }

  private Map<String, Object> caseView(long id) {
    var row = db.one(CASES + "WHERE pc.id=?", id);
    if (row == null) throw new ApiError("PENALTY_NOT_FOUND", "处罚不存在", 404);
    var appeals =
        db.rows(
            "SELECT * FROM v2_penalty_appeal WHERE penalty_case_id=? ORDER BY attempt_number", id);
    row.put("appeals", appeals);
    row.put("appeal_count", appeals.size());
    return row;
  }

  public List<Map<String, Object>> mine(Principal p) {
    return db
        .rows(
            "SELECT id FROM v2_penalty_case WHERE user_id=? AND college_id=? ORDER BY applied_at DESC,id DESC",
            p.userId(),
            p.tenant())
        .stream()
        .map(r -> caseView(Database.id(r, "id")))
        .toList();
  }

  public Object balance(Principal p) {
    var account =
        db.one(
            "SELECT points FROM v2_college_credit_account WHERE user_id=? AND college_id=?",
            p.userId(),
            p.tenant());
    if (account == null)
      account = db.one("SELECT credit_score points FROM sys_user WHERE id=?", p.userId());
    return Map.of(
        "college_id", p.tenant(), "points", account == null ? 100 : account.get("points"));
  }

  public Object cases(Principal p, Pagination page) {
    collegeAdmin(p, p.tenant());
    long total = db.count("SELECT COUNT(*) FROM v2_penalty_case WHERE college_id=?", p.tenant());
    var ids =
        db.rows(
            "SELECT id FROM v2_penalty_case WHERE college_id=? ORDER BY applied_at DESC,id DESC LIMIT ? OFFSET ?",
            p.tenant(),
            page.size(),
            page.offset());
    return page.result(ids.stream().map(r -> caseView(Database.id(r, "id"))).toList(), total);
  }

  public Object appeals(Principal p, Pagination page, boolean pending) {
    collegeAdmin(p, p.tenant());
    String where = "a.college_id=" + p.tenant() + (pending ? " AND a.status='PENDING'" : "");
    long total = db.count("SELECT COUNT(*) FROM v2_penalty_appeal a WHERE " + where);
    var ids =
        db.rows(
            "SELECT a.id FROM v2_penalty_appeal a WHERE "
                + where
                + " ORDER BY a.submitted_at,a.id LIMIT ? OFFSET ?",
            page.size(),
            page.offset());
    var items = new ArrayList<Map<String, Object>>();
    for (var id : ids) {
      var row =
          db.one(
              "SELECT a.*,COALESCE(u.real_name,u.username) user_name,pc.violation_type,pc.points_delta penalty_points_delta,pc.reservation_block_days penalty_block_days,pc.status penalty_status FROM v2_penalty_appeal a JOIN sys_user u ON u.id=a.user_id JOIN v2_penalty_case pc ON pc.id=a.penalty_case_id WHERE a.id=?",
              id.get("id"));
      items.add(row);
    }
    return page.result(items, total);
  }

  @Transactional
  public Object appeal(Principal p, long id, String reason, String evidence) {
    if (reason == null
        || reason.strip().isEmpty()
        || reason.length() > 2000
        || evidence != null && evidence.length() > 2000) throw ApiError.validation("申诉理由或证据无效");
    var penalty = db.one("SELECT * FROM v2_penalty_case WHERE id=? FOR UPDATE", id);
    if (penalty == null
        || Database.id(penalty, "user_id") != p.userId()
        || Database.id(penalty, "college_id") != p.tenant())
      throw new ApiError("PENALTY_NOT_FOUND", "处罚不存在", 404);
    if ("REVOKED".equals(penalty.get("status")))
      throw new ApiError("PENALTY_NOT_ACTIVE", "处罚已撤销", 409);
    var previous =
        db.rows(
            "SELECT * FROM v2_penalty_appeal WHERE penalty_case_id=? ORDER BY attempt_number", id);
    if (!previous.isEmpty() && "PENDING".equals(previous.getLast().get("status")))
      throw new ApiError("APPEAL_PENDING", "当前申诉尚未复核", 409);
    if (previous.size() >= 3) throw new ApiError("APPEAL_LIMIT_REACHED", "同一处罚最多申诉三次", 409);
    long appeal =
        db.insert(
            "INSERT INTO v2_penalty_appeal (penalty_case_id,user_id,college_id,attempt_number,reason,evidence,status,submitted_at) VALUES (?,?,?,?,?,?,'PENDING',UTC_TIMESTAMP())",
            id,
            p.userId(),
            p.tenant(),
            previous.size() + 1,
            reason.strip(),
            evidence);
    events.task(
        "timeout:penalty-appeal:" + appeal + ":reminder",
        "PENALTY_APPEAL_REMINDER",
        "penalty-appeal:" + appeal,
        p.collegeId(),
        Map.of("appeal_id", appeal),
        BusinessTime.utcNow().plusDays(3));
    events.audit(p, "PENALTY_APPEAL_SUBMIT", "PENALTY_APPEAL", appeal, Map.of());
    return db.one("SELECT * FROM v2_penalty_appeal WHERE id=?", appeal);
  }

  @Transactional
  public Object review(Principal p, long id, Map<String, Object> data) {
    var initial = db.one("SELECT * FROM v2_penalty_appeal WHERE id=?", id);
    if (initial == null) throw new ApiError("APPEAL_NOT_FOUND", "申诉不存在", 404);
    collegeAdmin(p, Database.id(initial, "college_id"));
    db.one("SELECT id FROM sys_user WHERE id=? FOR UPDATE", initial.get("user_id"));
    var penalty =
        db.one(
            "SELECT * FROM v2_penalty_case WHERE id=? FOR UPDATE", initial.get("penalty_case_id"));
    var appeal = db.one("SELECT * FROM v2_penalty_appeal WHERE id=? FOR UPDATE", id);
    if (!"PENDING".equals(appeal.get("status")))
      throw new ApiError("APPEAL_ALREADY_REVIEWED", "申诉已复核", 409);
    if (Database.id(appeal, "user_id") == p.userId()
        || Database.id(penalty, "confirmed_by") == p.userId())
      throw new ApiError("APPEAL_REVIEW_CONFLICT", "不能复核自己提交或确认的处罚申诉", 403);
    if (Database.id(appeal, "attempt_number") > 1
        && db.count(
                "SELECT COUNT(*) FROM v2_penalty_appeal WHERE penalty_case_id=? AND attempt_number=1 AND reviewer_id=?",
                penalty.get("id"),
                p.userId())
            != 1) throw new ApiError("APPEAL_REVIEWER_FIXED", "后续申诉须由首次负责人复核", 403);
    String result = Database.str(data, "result", ""),
        reason = Database.str(data, "result_reason", "").strip();
    if (!Set.of("MAINTAIN", "ADJUST", "REVOKE").contains(result)
        || reason.isEmpty()
        || reason.length() > 2000) throw ApiError.validation("复核结果或理由无效");
    int old = (int) Database.id(penalty, "points_delta"),
        oldDays = (int) Database.id(penalty, "reservation_block_days"),
        points = old,
        days = oldDays;
    if (result.equals("REVOKE")) {
      points = 0;
      days = 0;
    }
    if (result.equals("ADJUST")) {
      if (data.get("points_deduction") == null || data.get("block_days") == null)
        throw new ApiError("APPEAL_ADJUSTMENT_REQUIRED", "调整时须明确扣分和暂停天数", 422);
      points = -(int) Database.id(data, "points_deduction");
      days = (int) Database.id(data, "block_days");
      if (points > 0
          || points < -100
          || days < 0
          || days > 365
          || days > 0 && penalty.get("lab_id") == null) throw ApiError.validation("调整数值无效");
    }
    if (!result.equals("MAINTAIN")) {
      credit(
          Database.id(penalty, "user_id"),
          Database.id(penalty, "college_id"),
          Database.id(penalty, "reservation_id"),
          points - old,
          "处罚申诉复核",
          p.userId());
      db.execute(
          "UPDATE v2_penalty_case SET points_delta=?,reservation_block_days=?,status=?,revoked_at=? WHERE id=?",
          points,
          days,
          result.equals("REVOKE") ? "REVOKED" : "ACTIVE",
          result.equals("REVOKE") ? BusinessTime.utcNow() : null,
          penalty.get("id"));
      if (days == 0)
        db.execute(
            "UPDATE v2_reservation_booking_restriction SET released_at=UTC_TIMESTAMP(),release_reason='申诉复核' WHERE penalty_case_id=?",
            penalty.get("id"));
      else {
        LocalDateTime applied = (LocalDateTime) penalty.get("applied_at");
        db.execute(
            "INSERT INTO v2_reservation_booking_restriction (user_id,college_id,scope_type,scope_id,reason,penalty_case_id,starts_at,ends_at) VALUES (?,?,'LAB',?,'处罚申诉复核',?,?,?) ON DUPLICATE KEY UPDATE ends_at=VALUES(ends_at),released_at=NULL,release_reason=NULL",
            penalty.get("user_id"),
            penalty.get("college_id"),
            penalty.get("lab_id"),
            penalty.get("id"),
            applied,
            applied.plusDays(days));
        if (days > oldDays) cancelFuture(penalty);
      }
    }
    db.execute(
        "UPDATE v2_penalty_appeal SET status='REVIEWED',reviewer_id=?,result=?,result_reason=?,adjusted_points_delta=?,adjusted_block_days=?,reviewed_at=UTC_TIMESTAMP() WHERE id=? AND status='PENDING'",
        p.userId(),
        result,
        reason,
        points,
        days,
        id);
    events.notify(
        Database.id(penalty, "user_id"),
        (Long) penalty.get("college_id"),
        "处罚申诉已复核",
        reason,
        id,
        "PENALTY_APPEAL",
        "notification:penalty-appeal:" + id + ":reviewed");
    events.audit(p, "PENALTY_APPEAL_REVIEW", "PENALTY_APPEAL", id, Map.of("result", result));
    return db.one("SELECT * FROM v2_penalty_appeal WHERE id=?", id);
  }

  private int credit(
      long user, long college, long reservation, int delta, String reason, Long operator) {
    var account =
        db.one(
            "SELECT * FROM v2_college_credit_account WHERE user_id=? AND college_id=? FOR UPDATE",
            user,
            college);
    if (account == null) {
      db.execute(
          "INSERT INTO v2_college_credit_account (user_id,college_id,points) SELECT id,?,IF(college_id=?,credit_score,100) FROM sys_user WHERE id=?",
          college,
          college,
          user);
      account =
          db.one(
              "SELECT * FROM v2_college_credit_account WHERE user_id=? AND college_id=? FOR UPDATE",
              user,
              college);
    }
    int old = (int) Database.id(account, "points"), next = Math.min(100, Math.max(0, old + delta));
    db.execute(
        "UPDATE v2_college_credit_account SET points=?,updated_at=UTC_TIMESTAMP() WHERE id=?",
        next,
        account.get("id"));
    db.execute(
        "UPDATE sys_user SET credit_score=? WHERE id=? AND college_id=?", next, user, college);
    db.execute(
        "INSERT INTO v2_credit_event (user_id,college_id,reservation_id,event_type,points,reason,operator_id,created_at) VALUES (?,?,?,'PENALTY',?,?,?,UTC_TIMESTAMP())",
        user,
        college,
        reservation,
        next - old,
        reason,
        operator);
    return next - old;
  }

  @Transactional
  public Long apply(
      long reservation, String type, String reason, LocalDateTime eventAt, Long operator) {
    var r =
        db.one(
            "SELECT r.*,d.lab_id FROM reservation r JOIN device d ON d.id=r.device_id WHERE r.id=?",
            reservation);
    if (r == null || r.get("college_id") == null) return null;
    db.one("SELECT id FROM sys_user WHERE id=? FOR UPDATE", r.get("user_id"));
    var existing =
        db.one(
            "SELECT id FROM v2_penalty_case WHERE reservation_id=? AND violation_type=?",
            reservation,
            type);
    if (existing != null) return Database.id(existing, "id");
    var policy =
        db.one(
            "SELECT * FROM v2_penalty_rule_version WHERE college_id=? AND effective_at<=? ORDER BY effective_at DESC,version DESC LIMIT 1",
            r.get("college_id"),
            eventAt);
    long occurrence =
        db.count(
                "SELECT COUNT(*) FROM v2_penalty_case WHERE user_id=? AND college_id=? AND violation_type=? AND status<>'REVOKED' AND event_at BETWEEN ? AND ?",
                r.get("user_id"),
                r.get("college_id"),
                type,
                eventAt.minusMonths(3),
                eventAt)
            + 1;
    int points = 0, days = 0;
    if (policy != null
        && db.parse(policy.get("tiers"), Map.of()) instanceof Map<?, ?> tiers
        && tiers.get(type) instanceof List<?> values) {
      for (Object value : values)
        if (value instanceof Map<?, ?> tier
            && ((Number) tier.get("occurrence")).longValue() <= occurrence) {
          points = ((Number) tier.get("points")).intValue();
          days = r.get("lab_id") == null ? 0 : ((Number) tier.get("block_days")).intValue();
        }
    }
    int delta =
        credit(
            Database.id(r, "user_id"),
            Database.id(r, "college_id"),
            reservation,
            -points,
            reason,
            operator);
    long id =
        db.insert(
            "INSERT INTO v2_penalty_case (reservation_id,user_id,college_id,lab_id,device_id,violation_type,reason,event_at,rule_version_id,occurrence_number,points_delta,reservation_block_days,status,confirmed_by,applied_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'ACTIVE',?,UTC_TIMESTAMP())",
            reservation,
            r.get("user_id"),
            r.get("college_id"),
            r.get("lab_id"),
            r.get("device_id"),
            type,
            reason,
            eventAt,
            policy == null ? null : policy.get("id"),
            occurrence,
            delta,
            days,
            operator);
    var penalty = db.one("SELECT * FROM v2_penalty_case WHERE id=?", id);
    if (days > 0) {
      db.execute(
          "INSERT INTO v2_reservation_booking_restriction (user_id,college_id,scope_type,scope_id,reason,penalty_case_id,starts_at,ends_at) VALUES (?,?,'LAB',?,?,?,UTC_TIMESTAMP(),?)",
          r.get("user_id"),
          r.get("college_id"),
          r.get("lab_id"),
          reason,
          id,
          BusinessTime.utcNow().plusDays(days));
      cancelFuture(penalty);
    }
    events.notify(
        Database.id(r, "user_id"),
        (Long) r.get("college_id"),
        "预约违规处罚",
        reason,
        id,
        "PENALTY",
        "notification:penalty:" + id);
    return id;
  }

  private void cancelFuture(Map<String, Object> penalty) {
    if (penalty.get("lab_id") == null) return;
    for (var r :
        db.rows(
            "SELECT r.* FROM reservation r JOIN device d ON d.id=r.device_id WHERE r.user_id=? AND r.college_id=? AND d.lab_id=? AND r.id<>? AND r.status IN ('PENDING','APPROVED') AND r.start_date>=? FOR UPDATE",
            penalty.get("user_id"),
            penalty.get("college_id"),
            penalty.get("lab_id"),
            penalty.get("reservation_id"),
            BusinessTime.today())) {
      String next = "PENDING".equals(r.get("status")) ? "REJECTED" : "CANCELLED";
      if (db.execute(
              "UPDATE reservation SET status=?,handover_status='CANCELLED',reject_reason='预约因违规处罚已处理',updated_at=UTC_TIMESTAMP() WHERE id=? AND status=?",
              next,
              r.get("id"),
              r.get("status"))
          == 1) {
        events.release(r);
        db.execute(
            "UPDATE v2_device_handover SET status='CANCELLED' WHERE reservation_id=?", r.get("id"));
        events.notify(
            Database.id(r, "user_id"),
            (Long) r.get("college_id"),
            "预约因违规处罚已处理",
            "请在处罚结束后重新预约",
            Database.id(r, "id"),
            "RESERVATION",
            "notification:penalty:" + penalty.get("id") + ":reservation:" + r.get("id"));
      }
    }
  }

  private Map<String, Object> overdueView(long id) {
    var row =
        db.one(
            "SELECT ro.*,d.name device_name,l.name lab_name,COALESCE(u.real_name,u.username) user_name FROM v2_reservation_overdue ro JOIN device d ON d.id=ro.device_id LEFT JOIN lab l ON l.id=ro.lab_id JOIN sys_user u ON u.id=ro.user_id WHERE ro.id=?",
            id);
    if (row == null) throw new ApiError("OVERDUE_NOT_FOUND", "逾期案件不存在", 404);
    row.put(
        "followups",
        db.rows(
            "SELECT f.id,f.contacted_at,f.result,COALESCE(u.real_name,u.username) operator_name FROM v2_reservation_overdue_followup f JOIN sys_user u ON u.id=f.operator_id WHERE f.overdue_id=? ORDER BY f.contacted_at,f.id",
            id));
    return row;
  }

  public Object overdue(Principal p, Pagination page) {
    collegeAdmin(p, p.tenant());
    String where = "ro.resolved_at IS NULL AND " + scope.devicePredicate(p, "d", true);
    long total =
        db.count(
            "SELECT COUNT(*) FROM v2_reservation_overdue ro JOIN device d ON d.id=ro.device_id WHERE "
                + where);
    var ids =
        db.rows(
            "SELECT ro.id FROM v2_reservation_overdue ro JOIN device d ON d.id=ro.device_id WHERE "
                + where
                + " ORDER BY ro.started_at,ro.id LIMIT ? OFFSET ?",
            page.size(),
            page.offset());
    return page.result(ids.stream().map(r -> overdueView(Database.id(r, "id"))).toList(), total);
  }

  @Transactional
  public Object followup(Principal p, long id, String result, LocalDateTime at) {
    var row = overdueView(id);
    collegeAdmin(p, Database.id(row, "college_id"));
    scope.device(p, Database.id(row, "device_id"), true);
    if (row.get("resolved_at") != null) throw new ApiError("OVERDUE_NOT_FOUND", "逾期案件已结案", 404);
    if (result == null || result.isBlank() || result.length() > 1000)
      throw ApiError.validation("请填写跟进结果");
    long event =
        db.insert(
            "INSERT INTO v2_reservation_overdue_followup (overdue_id,operator_id,contacted_at,result) VALUES (?,?,?,?)",
            id,
            p.userId(),
            at == null ? BusinessTime.utcNow() : at,
            result.strip());
    events.audit(
        p, "RESERVATION_OVERDUE_FOLLOWUP", "RESERVATION_OVERDUE", id, Map.of("result", result));
    return db.one("SELECT * FROM v2_reservation_overdue_followup WHERE id=?", event);
  }

  @Transactional
  public Object escalate(Principal p, long id, String reason) {
    var row = overdueView(id);
    collegeAdmin(p, Database.id(row, "college_id"));
    scope.device(p, Database.id(row, "device_id"), true);
    if (reason == null || reason.isBlank() || reason.length() > 1000)
      throw ApiError.validation("请填写升级原因");
    if (row.get("resolved_at") != null) throw new ApiError("OVERDUE_NOT_FOUND", "逾期案件已结案", 404);
    if (row.get("escalated_at") != null)
      throw new ApiError("OVERDUE_ALREADY_ESCALATED", "案件已经升级", 409);
    if (db.count("SELECT COUNT(*) FROM v2_reservation_overdue_followup WHERE overdue_id=?", id)
        == 0) throw new ApiError("OVERDUE_FOLLOWUP_REQUIRED", "请先记录至少一次联系跟进", 409);
    db.one("SELECT id FROM sys_user WHERE id=? FOR UPDATE", row.get("user_id"));
    if (db.execute(
            "UPDATE v2_reservation_overdue SET status='ESCALATED',escalated_at=UTC_TIMESTAMP(),escalated_by=?,escalation_reason=? WHERE id=? AND escalated_at IS NULL AND resolved_at IS NULL",
            p.userId(),
            reason,
            id)
        != 1) throw new ApiError("OVERDUE_ALREADY_ESCALATED", "案件状态已变更", 409);
    db.execute(
        "INSERT INTO v2_reservation_booking_restriction (user_id,college_id,scope_type,scope_id,reason,overdue_id,starts_at) VALUES (?,?,'COLLEGE',?,?,?,UTC_TIMESTAMP())",
        row.get("user_id"),
        row.get("college_id"),
        row.get("college_id"),
        reason,
        id);
    events.audit(
        p, "RESERVATION_OVERDUE_ESCALATE", "RESERVATION_OVERDUE", id, Map.of("reason", reason));
    return overdueView(id);
  }
}
