package edu.labflow;

import java.time.*;
import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class WaitlistService {
  private final Database db;
  private final ScopeAccess scope;
  private final ReservationService reservations;
  private final BusinessEvents events;

  public WaitlistService(
      Database db, ScopeAccess scope, ReservationService reservations, BusinessEvents events) {
    this.db = db;
    this.scope = scope;
    this.reservations = reservations;
    this.events = events;
  }

  private Map<String, Object> view(long id) {
    return db.one(
        "SELECT w.*,d.name device_name,wo.expires_at offered_until FROM v2_reservation_waitlist w JOIN device d ON d.id=w.device_id LEFT JOIN v2_reservation_waitlist_offer wo ON wo.waitlist_id=w.id WHERE w.id=?",
        id);
  }

  @Transactional
  public Object join(Principal p, Map<String, Object> data) {
    p.require("reservation:create");
    long deviceId = Database.id(data, "device_id");
    LocalDate day = LocalDate.parse(Database.str(data, "reservation_date", ""));
    var device = scope.device(p, deviceId, false);
    if (day.isBefore(BusinessTime.today())) throw new ApiError("DATE_IN_PAST", "不能候补过去的日期", 422);
    if (!"IDLE".equals(device.get("status")))
      throw new ApiError("DEVICE_UNAVAILABLE", "当前设备不能候补", 409);
    if (Boolean.TRUE.equals(
        reservations.availability(p, deviceId, false, day, day).getFirst().get("available")))
      throw new ApiError("WAITLIST_NOT_NEEDED", "该日期当前可以直接预约", 409);
    String purpose = Database.str(data, "purpose", "").strip();
    if (purpose.length() < 2 || purpose.length() > 500) throw ApiError.validation("请填写预约用途");
    var existing =
        db.one(
            "SELECT * FROM v2_reservation_waitlist WHERE device_id=? AND reservation_date=? AND user_id=? FOR UPDATE",
            deviceId,
            day,
            p.userId());
    if (existing != null) {
      if (Set.of("WAITING", "OFFERED").contains(existing.get("status")))
        throw new ApiError("WAITLIST_ALREADY_JOINED", "已在候补队列中", 409);
      db.execute(
          "UPDATE v2_reservation_waitlist SET status='WAITING',purpose=?,purpose_category=?,project_reference=?,notified_at=NULL,created_at=UTC_TIMESTAMP() WHERE id=?",
          purpose,
          data.getOrDefault("purpose_category", "OTHER"),
          data.get("project_reference"),
          existing.get("id"));
      return view(Database.id(existing, "id"));
    }
    long id =
        db.insert(
            "INSERT INTO v2_reservation_waitlist (device_id,college_id,user_id,reservation_date,purpose,purpose_category,project_reference,status) VALUES (?,?,?,?,?,?,?,'WAITING')",
            deviceId,
            device.get("college_id"),
            p.userId(),
            day,
            purpose,
            data.getOrDefault("purpose_category", "OTHER"),
            data.get("project_reference"));
    return view(id);
  }

  public Object mine(Principal p) {
    p.require("reservation:read:own");
    return db.rows(
        "SELECT w.*,d.name device_name,wo.expires_at offered_until FROM v2_reservation_waitlist w JOIN device d ON d.id=w.device_id LEFT JOIN v2_reservation_waitlist_offer wo ON wo.waitlist_id=w.id WHERE w.user_id=? AND "
            + scope.devicePredicate(p, "d", false)
            + " ORDER BY w.id DESC",
        p.userId());
  }

  @Transactional
  public void cancel(Principal p, long id) {
    p.require("reservation:cancel");
    var row =
        db.one(
            "SELECT * FROM v2_reservation_waitlist WHERE id=? AND user_id=? FOR UPDATE",
            id,
            p.userId());
    if (row == null || !Set.of("WAITING", "OFFERED").contains(row.get("status")))
      throw new ApiError("WAITLIST_NOT_FOUND", "候补申请不存在或已处理", 404);
    scope.device(p, Database.id(row, "device_id"), false);
    db.execute(
        "UPDATE v2_reservation_waitlist SET status='CANCELLED' WHERE id=? AND status=?",
        id,
        row.get("status"));
    db.execute("DELETE FROM v2_reservation_waitlist_offer WHERE waitlist_id=?", id);
    promotion(row, "cancelled-" + id);
  }

  private static class ExpiredOffer extends ApiError {
    ExpiredOffer() {
      super("WAITLIST_OFFER_EXPIRED", "候补保留已过期，系统将递补下一位", 409);
    }
  }

  @Transactional(noRollbackFor = ExpiredOffer.class)
  public Object confirm(Principal p, long id) {
    p.require("reservation:create");
    db.one("SELECT id FROM sys_user WHERE id=? FOR UPDATE", p.userId());
    var row =
        db.one(
            "SELECT * FROM v2_reservation_waitlist WHERE id=? AND user_id=? FOR UPDATE",
            id,
            p.userId());
    var offer =
        db.one("SELECT * FROM v2_reservation_waitlist_offer WHERE waitlist_id=? FOR UPDATE", id);
    if (row == null || offer == null || !"OFFERED".equals(row.get("status")))
      throw new ApiError("WAITLIST_OFFER_NOT_FOUND", "候补保留已失效", 409);
    scope.device(p, Database.id(row, "device_id"), false);
    if (!((LocalDateTime) offer.get("expires_at")).isAfter(BusinessTime.utcNow())
        || ((LocalDate) row.get("reservation_date")).isBefore(BusinessTime.today())) {
      db.execute("DELETE FROM v2_reservation_waitlist_offer WHERE waitlist_id=?", id);
      db.execute("UPDATE v2_reservation_waitlist SET status='EXPIRED' WHERE id=?", id);
      promotion(row, "expired-" + id);
      throw new ExpiredOffer();
    }
    db.execute("DELETE FROM v2_reservation_waitlist_offer WHERE waitlist_id=?", id);
    db.execute(
        "UPDATE v2_reservation_waitlist SET status='CONFIRMED' WHERE id=? AND status='OFFERED'",
        id);
    LocalDate day = (LocalDate) row.get("reservation_date");
    var plan =
        new ReservationPlan(
            Database.id(row, "device_id"),
            null,
            null,
            1,
            row.get("purpose").toString(),
            row.get("purpose_category").toString(),
            (String) row.get("project_reference"),
            day,
            day,
            null,
            null,
            null);
    var result = (Map<?, ?>) reservations.create(p, plan, "waitlist-confirm:" + id);
    var created = (List<?>) result.get("created");
    return Map.of("waitlist_id", id, "reservation", created.getFirst());
  }

  private void promotion(Map<String, Object> row, String source) {
    events.task(
        "waitlist:promote:"
            + row.get("device_id")
            + ":"
            + row.get("reservation_date")
            + ":"
            + source,
        "WAITLIST_PROMOTE",
        "waitlist:" + row.get("device_id") + ":" + row.get("reservation_date"),
        (Long) row.get("college_id"),
        Map.of(
            "device_id",
            row.get("device_id"),
            "reservation_date",
            row.get("reservation_date").toString()),
        BusinessTime.utcNow());
  }

  private Principal actor(long id) {
    var user = db.one("SELECT * FROM sys_user WHERE id=? AND status=1", id);
    if (user == null) return null;
    var roles = new HashSet<String>();
    for (var row :
        db.rows(
            "SELECT r.role_code FROM sys_role r JOIN sys_user_role ur ON ur.role_id=r.id WHERE ur.user_id=?",
            id)) roles.add(row.get("role_code").toString());
    var permissions = new HashSet<String>();
    for (var row :
        db.rows(
            "SELECT DISTINCT p.permission_code FROM sys_permission p JOIN sys_role_permission rp ON rp.permission_id=p.id JOIN sys_user_role ur ON ur.role_id=rp.role_id WHERE ur.user_id=?",
            id)) permissions.add(row.get("permission_code").toString());
    return new Principal(
        id,
        user.get("username").toString(),
        user.get("college_id") == null ? null : Database.id(user, "college_id"),
        Set.copyOf(roles),
        Set.copyOf(permissions),
        "");
  }

  @Transactional
  public void promote(long device, LocalDate day) {
    var d = db.one("SELECT * FROM device WHERE id=? FOR UPDATE", device);
    if (d == null
        || !"IDLE".equals(d.get("status"))
        || day.isBefore(BusinessTime.today())
        || db.count(
                "SELECT COUNT(*) FROM v2_reservation_day WHERE device_id=? AND date=?", device, day)
            > 0
        || db.count(
                "SELECT COUNT(*) FROM v2_reservation_waitlist_offer WHERE device_id=? AND reservation_date=?",
                device,
                day)
            > 0) return;
    for (var entry :
        db.rows(
            "SELECT * FROM v2_reservation_waitlist WHERE device_id=? AND reservation_date=? AND status='WAITING' ORDER BY id FOR UPDATE",
            device,
            day)) {
      var actor = actor(Database.id(entry, "user_id"));
      boolean eligible = false;
      if (actor != null) {
        try {
          var plan =
              new ReservationPlan(
                  device,
                  null,
                  null,
                  1,
                  entry.get("purpose").toString(),
                  entry.get("purpose_category").toString(),
                  (String) entry.get("project_reference"),
                  day,
                  day,
                  null,
                  null,
                  null);
          var check = reservations.preflight(actor, plan);
          eligible =
              Boolean.TRUE.equals(check.get("all_available"))
                  && (!Boolean.TRUE.equals(check.get("safety_required"))
                      || Boolean.TRUE.equals(check.get("safety_acknowledged")))
                  && (!Boolean.TRUE.equals(check.get("qualification_required"))
                      || Boolean.TRUE.equals(check.get("qualification_approved")));
        } catch (ApiError ignored) {
        }
      }
      if (!eligible) {
        db.execute(
            "UPDATE v2_reservation_waitlist SET status='SKIPPED',notified_at=UTC_TIMESTAMP() WHERE id=?",
            entry.get("id"));
        continue;
      }
      LocalDateTime expiry = BusinessTime.utcNow().plusHours(24);
      db.execute(
          "INSERT INTO v2_reservation_waitlist_offer (waitlist_id,device_id,college_id,user_id,reservation_date,expires_at) VALUES (?,?,?,?,?,?)",
          entry.get("id"),
          device,
          entry.get("college_id"),
          entry.get("user_id"),
          day,
          expiry);
      db.execute(
          "UPDATE v2_reservation_waitlist SET status='OFFERED',notified_at=UTC_TIMESTAMP() WHERE id=? AND status='WAITING'",
          entry.get("id"));
      events.task(
          "waitlist:offer-expire:" + entry.get("id") + ":" + expiry,
          "WAITLIST_OFFER_EXPIRE",
          "waitlist:" + device + ":" + day,
          (Long) entry.get("college_id"),
          Map.of("waitlist_id", entry.get("id")),
          expiry);
      events.notify(
          Database.id(entry, "user_id"),
          (Long) entry.get("college_id"),
          "候补日期已为你保留",
          "请在 24 小时内确认候补预约",
          Database.id(entry, "id"),
          "WAITLIST",
          "notification:waitlist:" + entry.get("id") + ":offer");
      return;
    }
  }

  @Transactional
  public void expire(long id) {
    var entry = db.one("SELECT * FROM v2_reservation_waitlist WHERE id=? FOR UPDATE", id);
    var offer =
        db.one("SELECT * FROM v2_reservation_waitlist_offer WHERE waitlist_id=? FOR UPDATE", id);
    if (entry == null
        || offer == null
        || !"OFFERED".equals(entry.get("status"))
        || ((LocalDateTime) offer.get("expires_at")).isAfter(BusinessTime.utcNow())) return;
    db.execute("DELETE FROM v2_reservation_waitlist_offer WHERE waitlist_id=?", id);
    db.execute(
        "UPDATE v2_reservation_waitlist SET status='EXPIRED' WHERE id=? AND status='OFFERED'", id);
    promotion(entry, "expired-" + id);
  }
}
