package edu.labflow;

import java.time.LocalDateTime;
import java.util.*;
import org.springframework.stereotype.Component;

@Component
public class BusinessEvents {
  private final Database db;

  public BusinessEvents(Database db) {
    this.db = db;
  }

  public void task(
      String key,
      String type,
      String aggregate,
      Long college,
      Map<String, Object> payload,
      LocalDateTime at) {
    db.execute(
        "INSERT IGNORE INTO v2_outbox_task (task_key,task_type,aggregate_key,college_id,payload,status,attempts,execute_at) VALUES (?,?,?,?,?,'PENDING',0,?)",
        key,
        type,
        aggregate,
        college,
        db.json(payload),
        at);
  }

  public void notify(
      long userId,
      Long college,
      String title,
      String content,
      long relatedId,
      String relatedType,
      String key) {
    var payload = new HashMap<String, Object>();
    payload.put("user_id", userId);
    payload.put("college_id", college);
    payload.put("title", title);
    payload.put("content", content);
    payload.put("related_id", relatedId);
    payload.put("related_type", relatedType);
    payload.put("type", relatedType);
    task(
        key,
        "NOTIFICATION",
        relatedType + ":" + relatedId,
        college,
        payload,
        BusinessTime.utcNow());
  }

  public void release(Map<String, Object> r) {
    var days =
        db.rows(
            "SELECT date FROM v2_reservation_day WHERE reservation_id=? ORDER BY date",
            r.get("id"));
    db.execute("DELETE FROM v2_reservation_day WHERE reservation_id=?", r.get("id"));
    for (var day : days)
      task(
          "waitlist:released:" + r.get("id") + ":" + day.get("date"),
          "WAITLIST_PROMOTE",
          "waitlist:" + r.get("device_id") + ":" + day.get("date"),
          (Long) r.get("college_id"),
          Map.of("device_id", r.get("device_id"), "reservation_date", day.get("date").toString()),
          BusinessTime.utcNow());
  }

  public void audit(Principal p, String action, String type, long id, Object detail) {
    db.execute(
        "INSERT INTO v2_audit_log (user_id,college_id,action,target_type,target_id,detail,created_at) VALUES (?,?,?,?,?,?,UTC_TIMESTAMP())",
        p.userId(),
        p.collegeId(),
        action,
        type,
        id,
        db.json(detail));
  }
}
