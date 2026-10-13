package edu.labflow;

import java.time.*;
import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class DeadlineService {
  private final Database db;
  private final PenaltyService penalties;
  private final BusinessEvents events;

  public DeadlineService(Database db, PenaltyService penalties, BusinessEvents events) {
    this.db = db;
    this.penalties = penalties;
    this.events = events;
  }

  @Transactional
  public void noShow(long id) {
    var r = db.one("SELECT * FROM reservation WHERE id=? FOR UPDATE", id);
    if (r == null
        || !"APPROVED".equals(r.get("status"))
        || BusinessTime.utcNow().isBefore(BusinessTime.dayEnd((LocalDate) r.get("start_date"))))
      return;
    boolean exception =
        "EXCEPTION".equals(r.get("handover_status"))
            || db.count(
                    "SELECT COUNT(*) FROM v2_reservation_booking_restriction WHERE user_id=? AND college_id=? AND scope_type='COLLEGE' AND scope_id=? AND starts_at<=? AND (ends_at IS NULL OR ends_at>?) AND released_at IS NULL",
                    r.get("user_id"),
                    r.get("college_id"),
                    r.get("college_id"),
                    BusinessTime.dayEnd((LocalDate) r.get("start_date")),
                    BusinessTime.dayEnd((LocalDate) r.get("start_date")))
                > 0;
    String next = exception ? "CANCELLED" : "NO_SHOW";
    if (db.execute(
            "UPDATE reservation SET status=?,handover_status='CANCELLED',reject_reason=?,updated_at=UTC_TIMESTAMP() WHERE id=? AND status='APPROVED'",
            next,
            exception ? "交接异常未启用，系统取消预约" : "预约首日未完成设备交接",
            id)
        != 1) return;
    db.execute("UPDATE v2_device_handover SET status='CANCELLED' WHERE reservation_id=?", id);
    events.release(r);
    if (!exception)
      penalties.apply(
          id, "NO_SHOW", "预约首日未完成设备交接", BusinessTime.dayEnd((LocalDate) r.get("start_date")), null);
    events.notify(
        Database.id(r, "user_id"),
        (Long) r.get("college_id"),
        "预约已处理",
        exception ? "交接异常预约已取消" : "预约已标记爽约",
        id,
        "RESERVATION",
        "notification:reservation:" + id + ":no-show");
  }

  @Transactional
  public Long overdueStart(long id) {
    var r =
        db.one(
            "SELECT r.*,d.lab_id,h.returned_at FROM reservation r JOIN device d ON d.id=r.device_id LEFT JOIN v2_device_handover h ON h.reservation_id=r.id WHERE r.id=? FOR UPDATE",
            id);
    if (r == null || !"IN_USE".equals(r.get("status")) || r.get("college_id") == null) return null;
    LocalDateTime start =
        ((LocalDate) r.get("end_date"))
            .plusDays(1)
            .atStartOfDay(BusinessTime.ZONE)
            .withZoneSameInstant(ZoneOffset.UTC)
            .toLocalDateTime();
    if (BusinessTime.utcNow().isBefore(start)
        || r.get("returned_at") instanceof LocalDateTime returned && !returned.isAfter(start))
      return null;
    var existing = db.one("SELECT id FROM v2_reservation_overdue WHERE reservation_id=?", id);
    if (existing != null) return Database.id(existing, "id");
    var rule =
        db.one(
            "SELECT * FROM v2_penalty_rule_version WHERE college_id=? AND effective_at<=? ORDER BY effective_at DESC,version DESC LIMIT 1",
            r.get("college_id"),
            start);
    int grace = rule == null ? 0 : (int) Database.id(rule, "grace_days");
    LocalDateTime deadline = start.plusDays(grace);
    long overdue =
        db.insert(
            "INSERT INTO v2_reservation_overdue (reservation_id,user_id,college_id,lab_id,device_id,started_at,grace_deadline_at,rule_version_id,status) VALUES (?,?,?,?,?,?,?,?,?)",
            id,
            r.get("user_id"),
            r.get("college_id"),
            r.get("lab_id"),
            r.get("device_id"),
            start,
            deadline,
            rule == null ? null : rule.get("id"),
            r.get("returned_at") == null ? "GRACE" : "RETURN_PENDING");
    events.task(
        "timeout:overdue:" + id + ":penalty",
        "RESERVATION_OVERDUE_PENALTY",
        "reservation:" + id,
        (Long) r.get("college_id"),
        Map.of("reservation_id", id, "overdue_id", overdue),
        deadline.isAfter(BusinessTime.utcNow()) ? deadline : BusinessTime.utcNow());
    events.notify(
        Database.id(r, "user_id"),
        (Long) r.get("college_id"),
        "设备归还已逾期",
        "请尽快办理设备归还",
        overdue,
        "OVERDUE",
        "notification:overdue:" + overdue + ":started");
    return overdue;
  }

  @Transactional
  public void overduePenalty(long id) {
    var row =
        db.one(
            "SELECT ro.*,h.returned_at FROM v2_reservation_overdue ro LEFT JOIN v2_device_handover h ON h.reservation_id=ro.reservation_id WHERE ro.reservation_id=? FOR UPDATE",
            id);
    if (row == null || row.get("resolved_at") != null || row.get("penalty_case_id") != null) return;
    LocalDateTime deadline = (LocalDateTime) row.get("grace_deadline_at");
    if (BusinessTime.utcNow().isBefore(deadline)
        || row.get("returned_at") instanceof LocalDateTime returned && !returned.isAfter(deadline))
      return;
    Long penalty = penalties.apply(id, "OVERDUE_RETURN", "逾期宽限期结束仍未归还设备", deadline, null);
    db.execute(
        "UPDATE v2_reservation_overdue SET status=IF(status='ESCALATED','ESCALATED','PENALIZED'),penalty_case_id=?,updated_at=UTC_TIMESTAMP() WHERE id=? AND penalty_case_id IS NULL",
        penalty,
        row.get("id"));
  }

  @Transactional
  public void acceptReturn(long reservation) {
    var row =
        db.one(
            "SELECT id FROM v2_reservation_overdue WHERE reservation_id=? AND resolved_at IS NULL FOR UPDATE",
            reservation);
    if (row == null) return;
    db.execute(
        "UPDATE v2_reservation_overdue SET status='RESOLVED',resolved_at=UTC_TIMESTAMP(),updated_at=UTC_TIMESTAMP() WHERE id=? AND resolved_at IS NULL",
        row.get("id"));
    db.execute(
        "UPDATE v2_reservation_booking_restriction SET released_at=UTC_TIMESTAMP(),release_reason='逾期设备已归还并验收' WHERE overdue_id=? AND released_at IS NULL",
        row.get("id"));
  }

  @Transactional
  public void autoCloseRepair(long id) {
    var report = db.one("SELECT * FROM v2_repair_report WHERE id=? FOR UPDATE", id);
    if (report == null
        || !"RESOLVED".equals(report.get("status"))
        || report.get("resolved_at") == null
        || ((LocalDateTime) report.get("resolved_at")).plusDays(3).isAfter(BusinessTime.utcNow()))
      return;
    if (db.execute(
            "UPDATE v2_repair_report SET status='COMPLETED',closed_at=UTC_TIMESTAMP(),user_confirmation_note='用户三日未操作，系统自动关闭',updated_at=UTC_TIMESTAMP() WHERE id=? AND status='RESOLVED'",
            id)
        != 1) return;
    db.execute(
        "INSERT INTO v2_repair_worklog (report_id,operator_id,status,content,created_at) VALUES (?,?,'COMPLETED','用户三日未操作，系统自动关闭',UTC_TIMESTAMP())",
        id,
        report.get("handler_id") == null ? report.get("reporter_id") : report.get("handler_id"));
    if (db.count(
            "SELECT COUNT(*) FROM v2_repair_report WHERE device_id=? AND status IN ('PENDING','PROCESSING','RESOLVED')",
            report.get("device_id"))
        == 0) {
      var device = db.one("SELECT * FROM device WHERE id=? FOR UPDATE", report.get("device_id"));
      if (device != null && "MAINTENANCE".equals(device.get("status"))) {
        db.execute(
            "UPDATE device SET status='IDLE' WHERE id=? AND status='MAINTENANCE'",
            device.get("id"));
        db.execute(
            "INSERT INTO v2_device_status_history (device_id,college_id,old_status,new_status,reason,operator_id,created_at) VALUES (?,?,'MAINTENANCE','IDLE','报修自动关闭',?,UTC_TIMESTAMP())",
            device.get("id"),
            device.get("college_id"),
            report.get("handler_id"));
      }
    }
    events.notify(
        Database.id(report, "reporter_id"),
        (Long) report.get("college_id"),
        "报修工单已自动关闭",
        "用户三日未确认，工单自动完成",
        id,
        "REPAIR",
        "notification:repair:" + id + ":auto-close");
  }

  @Transactional
  public void maintenanceDue(long id, String due) {
    var plan = db.one("SELECT * FROM v2_device_maintenance_plan WHERE id=? FOR UPDATE", id);
    if (plan == null
        || !ReservationPolicy.truth(plan.get("active"))
        || plan.get("due_notice_sent_at") != null
        || !plan.get("due_date").toString().equals(due)) return;
    db.execute(
        "UPDATE v2_device_maintenance_plan SET due_notice_sent_at=UTC_TIMESTAMP() WHERE id=? AND due_notice_sent_at IS NULL",
        id);
    notifyManagers(
        Database.id(plan, "device_id"), "设备维护已到期", plan.get("title").toString(), id, "MAINTENANCE");
  }

  public void notifyManagers(long device, String title, String content, long related, String type) {
    var d =
        db.one(
            "SELECT d.college_id,l.manager_id lab_manager,c.manager_id college_manager FROM device d LEFT JOIN lab l ON l.id=d.lab_id LEFT JOIN college c ON c.id=d.college_id WHERE d.id=?",
            device);
    if (d == null) return;
    var recipients = new HashSet<Long>();
    for (String key : List.of("lab_manager", "college_manager"))
      if (d.get(key) != null) recipients.add(Database.id(d, key));
    if (recipients.isEmpty())
      for (var r :
          db.rows(
              "SELECT DISTINCT u.id FROM sys_user u JOIN sys_user_role ur ON ur.user_id=u.id JOIN sys_role role ON role.id=ur.role_id WHERE role.role_code='SYS_ADMIN' AND u.status=1"))
        recipients.add(Database.id(r, "id"));
    for (long user : recipients)
      events.notify(
          user,
          (Long) d.get("college_id"),
          title,
          content,
          related,
          type,
          "notification:"
              + type
              + ":"
              + related
              + ":manager:"
              + user
              + ":"
              + AuthService.sha256(content).substring(0, 12));
  }
}
