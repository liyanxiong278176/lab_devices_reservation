package edu.labflow;

import java.time.*;
import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class DeadlineService {
  private final Database db;
  private final BusinessEvents events;

  public DeadlineService(Database db, BusinessEvents events) {
    this.db = db;
    this.events = events;
  }

  @Transactional
  public void cancelUnclaimed(long id) {
    var r = db.one("SELECT * FROM reservation WHERE id=? FOR UPDATE", id);
    if (r == null
        || !"APPROVED".equals(r.get("status"))
        || BusinessTime.utcNow().isBefore(BusinessTime.dayEnd((LocalDate) r.get("start_date"))))
      return;
    String next = "CANCELLED";
    if (db.execute(
            "UPDATE reservation SET status=?,handover_status='CANCELLED',reject_reason=?,updated_at=UTC_TIMESTAMP() WHERE id=? AND status='APPROVED'",
            next,
            "未在预约首日领用",
            id)
        != 1) return;
    db.execute("UPDATE v2_device_handover SET status='CANCELLED' WHERE reservation_id=?", id);
    events.release(r);
    events.notify(
        Database.id(r, "user_id"),
        (Long) r.get("college_id"),
        "预约已处理",
        "未在预约首日领用，预约已自动取消",
        id,
        "RESERVATION",
        "notification:reservation:" + id + ":unclaimed-cancel");
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
