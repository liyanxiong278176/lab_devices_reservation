package edu.labflow;

import java.time.*;
import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class ReservationLifecycle {
  private final Database db;
  private final ScopeAccess scope;
  private final ReservationService reservations;
  private final CatalogService catalog;
  private final StorageService storage;
  private final BusinessEvents events;
  private final RepairService repairs;

  public ReservationLifecycle(
      Database db,
      ScopeAccess scope,
      ReservationService reservations,
      CatalogService catalog,
      StorageService storage,
      BusinessEvents events,
      RepairService repairs) {
    this.db = db;
    this.scope = scope;
    this.reservations = reservations;
    this.catalog = catalog;
    this.storage = storage;
    this.events = events;
    this.repairs = repairs;
  }

  private Map<String, Object> load(Principal p, long id, boolean manage, String permission) {
    p.require(permission);
    var row = db.one("SELECT * FROM reservation WHERE id=? FOR UPDATE", id);
    if (row == null) throw new ApiError("RESERVATION_NOT_FOUND", "预约不存在", 404);
    scope.device(p, Database.id(row, "device_id"), manage);
    if (!manage && Database.id(row, "user_id") != p.userId()) throw ApiError.forbidden();
    return row;
  }

  @Transactional
  public void checkin(Principal p, long id) {
    load(p, id, false, "reservation:check-in");
  }

  private void update(
      Map<String, Object> r, String expected, String next, String extra, Object... params) {
    var args = new ArrayList<>(Arrays.asList(params));
    args.add(next);
    args.add(Database.id(r, "id"));
    args.add(expected);
    if (db.execute(
            "UPDATE reservation SET "
                + (extra.isEmpty() ? "" : extra + ",")
                + "status=?,updated_at=UTC_TIMESTAMP() WHERE id=? AND status=?",
            args.toArray())
        != 1) throw new ApiError("INVALID_RESERVATION_STATE", "预约状态已变更", 409);
  }

  private void release(Map<String, Object> r) {
    long id = Database.id(r, "id");
    db.execute("DELETE FROM v2_reservation_day WHERE reservation_id=?", id);
    events.task(
        "waitlist:release:" + id,
        "WAITLIST_PROMOTE",
        "device:" + r.get("device_id"),
        (Long) r.get("college_id"),
        Map.of(
            "device_id",
            r.get("device_id"),
            "dates",
            ((LocalDate) r.get("start_date"))
                .datesUntil(((LocalDate) r.get("end_date")).plusDays(1))
                .map(LocalDate::toString)
                .toList()),
        BusinessTime.utcNow());
  }

  @Transactional
  public int batchApproval(Principal p, List<Long> ids) {
    p.require("reservation:approve");
    if (ids.isEmpty() || ids.size() > 100 || ids.stream().anyMatch(id -> id == null || id <= 0))
      throw ApiError.validation("请选择 1 至 100 条待审批预约");
    var unique = ids.stream().distinct().sorted().toList();
    for (long id : unique) {
      var row = load(p, id, true, "reservation:approve");
      if (!"PENDING".equals(row.get("status")))
        throw new ApiError("INVALID_RESERVATION_STATE", "部分预约不在待审批状态", 409);
    }
    for (long id : unique) approval(p, id, true, null);
    return unique.size();
  }

  @Transactional
  public Map<String, Object> approval(Principal p, long id, boolean approve, String reason) {
    var r = load(p, id, true, "reservation:approve");
    if (!"PENDING".equals(r.get("status")))
      throw new ApiError("INVALID_RESERVATION_STATE", "只有待审批预约可以处理", 409);
    if (!approve && (reason == null || reason.strip().isEmpty()))
      throw ApiError.validation("请填写驳回原因");
    if (approve) {
      var device = scope.device(p, Database.id(r, "device_id"), true);
      reservations.validateLifecycleDates(r, device);
      if (!"IDLE".equals(device.get("status")))
        throw new ApiError("DEVICE_UNAVAILABLE", "设备当前不可用", 409);
    }
    update(
        r,
        "PENDING",
        approve ? "APPROVED" : "REJECTED",
        "approver_id=?,approved_at=UTC_TIMESTAMP(),reject_reason=?",
        p.userId(),
        approve ? null : reason);
    if (!approve) release(r);
    else
      events.task(
          "reservation:unclaimed-cancel:" + id,
          "RESERVATION_UNCLAIMED_CANCEL",
          "reservation:" + id,
          (Long) r.get("college_id"),
          Map.of("reservation_id", id),
          BusinessTime.dayEnd((LocalDate) r.get("start_date")));
    events.notify(
        Database.id(r, "user_id"),
        (Long) r.get("college_id"),
        approve ? "预约已批准" : "预约已驳回",
        approve ? "请于预约首日办理设备交接" : reason,
        id,
        "RESERVATION",
        "reservation:approval:" + id);
    events.audit(p, "RESERVATION_APPROVAL", "RESERVATION", id, Map.of("approved", approve));
    return reservations.get(p, id);
  }

  @Transactional
  public Map<String, Object> cancel(Principal p, long id, boolean exception, String reason) {
    var r = load(p, id, exception, exception ? "reservation:handover" : "reservation:cancel");
    String status = r.get("status").toString();
    if (!Set.of("PENDING", "APPROVED").contains(status)
        || exception && !"EXCEPTION".equals(r.get("handover_status")))
      throw new ApiError("INVALID_RESERVATION_STATE", "当前预约不能取消", 409);
    update(r, status, "CANCELLED", "handover_status='CANCELLED',reject_reason=?", reason);
    release(r);
    db.execute("UPDATE v2_device_handover SET status='CANCELLED' WHERE reservation_id=?", id);
    events.audit(p, "RESERVATION_CANCEL", "RESERVATION", id, Map.of());
    return reservations.get(p, id);
  }

  private void checklist(Map<String, Object> device, Object checks) {
    var expected = db.parse(device.get("accessory_checklist"), List.of());
    if (!(checks instanceof List<?> actual)
        || !(expected instanceof List<?> names)
        || actual.size() != names.size())
      throw new ApiError("CHECKLIST_MISMATCH", "必须逐项核对设备配件清单", 422);
    var seen = new HashSet<String>();
    for (Object item : actual) {
      if (!(item instanceof Map<?, ?> check)
          || !names.contains(check.get("name"))
          || !seen.add(String.valueOf(check.get("name")))
          || !Set.of("NORMAL", "DAMAGED", "MISSING").contains(check.get("condition")))
        throw new ApiError("CHECKLIST_MISMATCH", "配件清单或状态无效", 422);
    }
  }

  private String condition(Map<String, Object> data) {
    String c = Database.str(data, "condition", "NORMAL");
    if (!Set.of("NORMAL", "DAMAGED", "MISSING").contains(c)) throw ApiError.validation("验收状态无效");
    Object checks = data.get("checklist");
    if (checks instanceof List<?> values)
      for (Object item : values)
        if (item instanceof Map<?, ?> row
            && Set.of("DAMAGED", "MISSING").contains(row.get("condition")))
          c = row.get("condition").toString();
    return c;
  }

  @Transactional
  public Map<String, Object> handover(Principal p, long id, Map<String, Object> data) {
    var r = load(p, id, true, "reservation:handover");
    if (!"APPROVED".equals(r.get("status")) || !"PENDING".equals(r.get("handover_status")))
      throw new ApiError("INVALID_RESERVATION_STATE", "预约未批准或已经交接", 409);
    if (!BusinessTime.today().equals(r.get("start_date")))
      throw new ApiError("HANDOVER_DAY_INVALID", "预约首日才能办理设备交接", 409);
    var device = scope.device(p, Database.id(r, "device_id"), true);
    reservations.validateLifecycleDates(r, device);
    if (db.count(
            "SELECT COUNT(*) FROM reservation WHERE device_id=? AND status='IN_USE' AND id<>?",
            r.get("device_id"),
            id)
        > 0) throw new ApiError("DEVICE_UNAVAILABLE", "设备尚未归还验收", 409);
    if (!"IDLE".equals(device.get("status")))
      throw new ApiError("DEVICE_UNAVAILABLE", "设备当前不可用", 409);
    storage.evidence(p, data.get("image_urls"), Database.id(r, "college_id"));
    checklist(device, data.getOrDefault("checklist", List.of()));
    String condition = condition(data);
    boolean normal = condition.equals("NORMAL");
    update(
        r,
        "APPROVED",
        normal ? "IN_USE" : "APPROVED",
        "handover_status=?,check_in_at=?",
        normal ? "HANDED_OVER" : "EXCEPTION",
        normal ? BusinessTime.utcNow() : null);
    db.execute(
        "UPDATE v2_device_handover SET status=?,handover_by=?,handover_at=UTC_TIMESTAMP(),handover_condition=?,handover_note=?,accessory_snapshot=?,handover_checklist=?,handover_image_urls=? WHERE reservation_id=?",
        normal ? "HANDED_OVER" : "EXCEPTION",
        p.userId(),
        condition,
        data.get("note"),
        db.json(db.parse(device.get("accessory_checklist"), List.of())),
        db.json(data.getOrDefault("checklist", List.of())),
        db.json(data.getOrDefault("image_urls", List.of())),
        id);
    if (!normal) fault(p, r, data, "交接发现设备损坏或配件缺失");
    events.audit(p, "DEVICE_HANDOVER", "RESERVATION", id, Map.of("condition", condition));
    return reservations.get(p, id);
  }

  @Transactional
  public Map<String, Object> requestReturn(Principal p, long id, Map<String, Object> data) {
    var r = load(p, id, false, "reservation:return");
    if (!"IN_USE".equals(r.get("status"))
        || !Set.of("HANDED_OVER", "LEGACY_IN_USE", "NOT_REQUIRED")
            .contains(r.get("handover_status")))
      throw new ApiError("INVALID_RESERVATION_STATE", "当前预约不能提交归还", 409);
    if (BusinessTime.today().isBefore((LocalDate) r.get("end_date")))
      throw new ApiError("RETURN_DAY_INVALID", "预约结束日及之后才能归还", 409);
    storage.evidence(p, data.get("image_urls"), Database.id(r, "college_id"));
    String c = condition(data);
    if (db.execute(
            "UPDATE reservation SET handover_status='RETURN_PENDING',updated_at=UTC_TIMESTAMP() WHERE id=? AND status='IN_USE' AND handover_status=?",
            id,
            r.get("handover_status"))
        != 1) throw new ApiError("INVALID_RESERVATION_STATE", "预约状态已变更", 409);
    db.execute(
        "UPDATE v2_device_handover SET status='RETURN_PENDING',returned_by=?,returned_at=UTC_TIMESTAMP(),return_condition=?,return_note=?,return_image_urls=? WHERE reservation_id=?",
        p.userId(),
        c,
        data.get("note"),
        db.json(data.getOrDefault("image_urls", List.of())),
        id);
    events.audit(p, "RESERVATION_RETURN_REQUEST", "RESERVATION", id, Map.of("condition", c));
    return reservations.get(p, id);
  }

  @Transactional
  public Map<String, Object> acceptReturn(Principal p, long id, Map<String, Object> data) {
    var r = load(p, id, true, "reservation:accept-return");
    if (!"IN_USE".equals(r.get("status")) || !"RETURN_PENDING".equals(r.get("handover_status")))
      throw new ApiError("INVALID_RESERVATION_STATE", "预约尚未提交归还", 409);
    var device = scope.device(p, Database.id(r, "device_id"), true);
    reservations.validateLifecycleDates(r, device);
    checklist(device, data.getOrDefault("checklist", List.of()));
    var handover = db.one("SELECT * FROM v2_device_handover WHERE reservation_id=?", id);
    if (handover == null) throw new ApiError("HANDOVER_NOT_FOUND", "交接记录缺失", 409);
    String c = condition(data);
    update(r, "IN_USE", "COMPLETED", "handover_status='COMPLETED',check_out_at=UTC_TIMESTAMP()");
    db.execute(
        "UPDATE v2_device_handover SET status='COMPLETED',return_condition=?,return_note=?,return_checklist=? WHERE reservation_id=?",
        c,
        data.get("note"),
        db.json(data.getOrDefault("checklist", List.of())),
        id);
    db.execute(
        "INSERT INTO v2_reservation_inspection (reservation_id,device_id,user_id,`condition`,note,image_urls,created_at) VALUES (?,?,?,?,?,?,UTC_TIMESTAMP())",
        id,
        r.get("device_id"),
        r.get("user_id"),
        c,
        data.get("note"),
        handover.get("return_image_urls"));
    release(r);
    if (!c.equals("NORMAL")) {
      var faultData = new HashMap<>(data);
      faultData.put("image_urls", db.parse(handover.get("return_image_urls"), List.of()));
      fault(p, r, faultData, "归还验收发现设备损坏或配件缺失");
    }
    events.audit(p, "DEVICE_RETURN_ACCEPT", "RESERVATION", id, Map.of("condition", c));
    return reservations.get(p, id);
  }

  private void fault(Principal p, Map<String, Object> r, Map<String, Object> data, String title) {
    repairs.createFault(
        p,
        Database.id(r, "device_id"),
        Database.id(r, "user_id"),
        Database.id(r, "id"),
        title,
        Database.str(data, "note", title),
        data.get("image_urls"));
  }
}
