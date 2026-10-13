package edu.labflow;

import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class NotificationService {
  private final Database db;
  private final BusinessEvents events;

  public NotificationService(Database db, BusinessEvents events) {
    this.db = db;
    this.events = events;
  }

  String predicate(Principal p) {
    return "user_id=" + p.userId() + (p.systemAdmin() ? "" : " AND college_id=" + p.tenant());
  }

  public Map<String, Object> publicRow(Map<String, Object> row) {
    var result = new HashMap<String, Object>();
    result.put("id", row.get("id"));
    result.put("userId", row.get("user_id"));
    result.put("type", row.get("type"));
    result.put("title", row.get("title"));
    result.put("content", row.get("content"));
    result.put("relatedId", row.get("related_id"));
    result.put("relatedType", row.get("related_type"));
    result.put("isRead", ReservationPolicy.truth(row.get("is_read")) ? 1 : 0);
    result.put("createdAt", row.get("created_at"));
    return result;
  }

  public Map<String, Object> list(Principal p, Pagination page, boolean unread) {
    p.require("notification:read:own");
    String where = predicate(p) + (unread ? " AND is_read=0" : "");
    long total = db.count("SELECT COUNT(*) FROM notification WHERE " + where);
    String ids =
        "SELECT id FROM notification WHERE " + where + " ORDER BY id DESC LIMIT ? OFFSET ?";
    var rows =
        db.rows(
            "SELECT n.* FROM notification n JOIN ("
                + ids
                + ") page_ids ON page_ids.id=n.id ORDER BY n.id DESC",
            page.size(),
            page.offset());
    return page.legacy(rows.stream().map(this::publicRow).toList(), total);
  }

  @Transactional
  public void read(Principal p, Long id) {
    p.require("notification:read:own");
    String where = predicate(p) + " AND is_read=0" + (id == null ? "" : " AND id=" + id);
    db.execute("UPDATE notification SET is_read=1,updated_at=UTC_TIMESTAMP() WHERE " + where);
    events.task(
        "notification:read-state:" + p.userId() + ":" + UUID.randomUUID(),
        "NOTIFICATION_READ_STATE",
        "user:" + p.userId(),
        p.collegeId(),
        Map.of("user_id", p.userId()),
        BusinessTime.utcNow());
  }

  public long head(Principal p) {
    return db.count(
        "SELECT COALESCE(MAX(delivery_sequence),0) FROM notification WHERE " + predicate(p));
  }

  public List<Map<String, Object>> replay(Principal p, long cursor) {
    return db.rows(
            "SELECT * FROM notification WHERE "
                + predicate(p)
                + " AND delivery_sequence>? ORDER BY delivery_sequence DESC LIMIT 100",
            cursor)
        .reversed();
  }

  public List<Map<String, Object>> between(Principal p, long cursor, long end) {
    return db.rows(
        "SELECT * FROM notification WHERE "
            + predicate(p)
            + " AND delivery_sequence>? AND delivery_sequence<=? ORDER BY delivery_sequence LIMIT 100",
        cursor,
        end);
  }

  public long pending(Principal p, long cursor) {
    return db.count(
        "SELECT COUNT(*) FROM notification WHERE " + predicate(p) + " AND delivery_sequence>?",
        cursor);
  }
}
