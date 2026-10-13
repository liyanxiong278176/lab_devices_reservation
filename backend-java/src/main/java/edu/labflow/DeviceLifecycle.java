package edu.labflow;

import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** Device state effects shared by catalog, repairs and fulfillment application services. */
@Service
public class DeviceLifecycle {
  private final Database db;
  private final BusinessEvents events;

  public DeviceLifecycle(Database db, BusinessEvents events) {
    this.db = db;
    this.events = events;
  }

  @Transactional
  public void change(Principal actor, long id, String next, String reason) {
    var device = db.one("SELECT * FROM device WHERE id=? FOR UPDATE", id);
    if (device == null) throw new ApiError("DEVICE_NOT_FOUND", "设备不存在", 404);
    String old = Database.str(device, "status", "");
    if (old.equals(next)) return;
    if (db.execute(
            "UPDATE device SET status=?,updated_at=UTC_TIMESTAMP() WHERE id=? AND status=?",
            next,
            id,
            old)
        != 1) throw new ApiError("DEVICE_STATE_CONFLICT", "设备状态已变更", 409);
    db.execute(
        "INSERT INTO v2_device_status_history (device_id,college_id,old_status,new_status,reason,operator_id,created_at) VALUES (?,?,?,?,?,?,UTC_TIMESTAMP())",
        id,
        device.get("college_id"),
        old,
        next,
        reason,
        actor.userId());
    events.audit(
        actor,
        "DEVICE_STATUS_CHANGE",
        "DEVICE",
        id,
        Map.of("old_status", old, "new_status", next, "reason", reason == null ? "" : reason));
    if (Set.of("MAINTENANCE", "DISABLED", "OFFLINE", "RETIRED").contains(next)) {
      for (var reservation :
          db.rows(
              "SELECT * FROM reservation WHERE device_id=? AND status IN ('PENDING','APPROVED') ORDER BY id FOR UPDATE",
              id)) {
        long reservationId = Database.id(reservation, "id");
        if ("PENDING".equals(reservation.get("status"))) {
          if (db.execute(
                  "UPDATE reservation SET status='REJECTED',reject_reason=?,updated_at=UTC_TIMESTAMP() WHERE id=? AND status='PENDING'",
                  "设备已进入 " + next + " 状态，暂不可预约",
                  reservationId)
              == 1)
            db.execute("DELETE FROM v2_reservation_day WHERE reservation_id=?", reservationId);
        }
        events.notify(
            Database.id(reservation, "user_id"),
            (Long) reservation.get("college_id"),
            "PENDING".equals(reservation.get("status")) ? "预约已驳回" : "预约需要调整",
            "设备状态变化，请联系负责人处理预约",
            reservationId,
            "RESERVATION",
            "notification:reservation:"
                + reservationId
                + ":device-status-"
                + next.toLowerCase(Locale.ROOT));
      }
    }
    if (device.get("college_id") != null)
      events.task(
          "cache-bump:college:" + device.get("college_id") + ":" + UUID.randomUUID(),
          "CACHE_BUMP",
          "college:" + device.get("college_id"),
          (Long) device.get("college_id"),
          Map.of("scope", "college:" + device.get("college_id")),
          BusinessTime.utcNow());
    long pool = device.get("pool_id") == null ? id : Database.id(device, "pool_id");
    events.task(
        "reservation-quota:reconcile:status:" + id + ":" + UUID.randomUUID(),
        "RESERVATION_QUOTA_RECONCILE",
        "reservation-quota:" + pool,
        (Long) device.get("college_id"),
        Map.of(
            "pool_id",
            pool,
            "dates",
            BusinessTime.today()
                .datesUntil(BusinessTime.today().plusDays(91))
                .map(java.time.LocalDate::toString)
                .toList()),
        BusinessTime.utcNow());
  }
}
