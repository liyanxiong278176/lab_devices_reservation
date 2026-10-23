package edu.labflow;

import java.time.*;
import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class ReservationService {
  private final Database db;
  private final ScopeAccess scope;
  private final CatalogService catalog;
  private final ReservationPolicy policies;
  private final TransactionTemplate transaction;
  private final QuotaCache quotas;
  private final BusinessEvents events;
  private static final String SELECT =
      "SELECT r.*,d.name device_name,d.asset_code device_asset_code,d.need_approval,d.requires_safety_ack,l.name device_lab_name,u.username,u.real_name,h.accessory_snapshot,h.handover_checklist,h.return_checklist,h.handover_image_urls,h.return_image_urls,h.return_condition inspection_condition,h.return_note inspection_note,rr.id fault_repair_id FROM reservation r JOIN device d ON d.id=r.device_id JOIN sys_user u ON u.id=r.user_id LEFT JOIN lab l ON l.id=d.lab_id LEFT JOIN v2_device_handover h ON h.reservation_id=r.id LEFT JOIN v2_repair_report rr ON rr.reservation_id=r.id ";

  public ReservationService(
      Database db,
      ScopeAccess scope,
      CatalogService catalog,
      ReservationPolicy policies,
      PlatformTransactionManager tm,
      QuotaCache quotas,
      BusinessEvents events) {
    this.db = db;
    this.scope = scope;
    this.catalog = catalog;
    this.policies = policies;
    this.transaction = new TransactionTemplate(tm);
    this.quotas = quotas;
    this.events = events;
  }

  private List<Map<String, Object>> candidates(Principal p, ReservationPlan plan, boolean lock) {
    if (plan.device_id() != null) {
      scope.device(p, plan.device_id(), false);
      return db.rows(
          "SELECT * FROM device WHERE id=?" + (lock ? " FOR UPDATE" : ""), plan.device_id());
    }
    String where =
        "pool_id=? AND status<>'DELETED' AND " + scope.devicePredicate(p, "device", false);
    var params = new ArrayList<Object>();
    params.add(plan.pool_id());
    if (plan.preferred_device_id() != null) {
      where += " AND id=?";
      params.add(plan.preferred_device_id());
    }
    var rows =
        db.rows(
            "SELECT * FROM device WHERE " + where + " ORDER BY id" + (lock ? " FOR UPDATE" : ""),
            params.toArray());
    if (rows.isEmpty())
      throw new ApiError("DEVICE_POOL_NOT_FOUND", "设备资源池不存在或暂时被占用", lock ? 409 : 404);
    return rows;
  }

  public Map<String, Object> access(Principal p, Map<String, Object> device, LocalDate until) {
    long id = Database.id(device, "id");
    var docs =
        db.rows(
            "SELECT id,document_type,version FROM v2_device_document WHERE device_id=? AND active=1 AND requires_ack=1 ORDER BY document_type,id DESC",
            id);
    var latest = new ArrayList<Map<String, Object>>();
    var types = new HashSet<String>();
    for (var doc : docs) if (types.add(doc.get("document_type").toString())) latest.add(doc);
    boolean required = Database.id(device, "requires_safety_ack") == 1 || !latest.isEmpty(),
        ack = !required || !latest.isEmpty();
    for (var doc : latest)
      if (db.count(
              "SELECT COUNT(*) FROM v2_device_document_ack WHERE document_id=? AND user_id=? AND document_version=?",
              doc.get("id"),
              p.userId(),
              doc.get("version"))
          == 0) ack = false;
    boolean qualificationRequired =
        Database.id(device, "requires_qualification") == 1
            || Set.of("HIGH", "CRITICAL").contains(device.get("risk_level"));
    var qualification =
        db.one(
            "SELECT * FROM v2_device_qualification WHERE device_id=? AND user_id=? AND status='APPROVED' ORDER BY reviewed_at DESC,id DESC LIMIT 1",
            id,
            p.userId());
    boolean approved =
        qualification != null
            && (qualification.get("valid_until") == null
                || !((LocalDate) qualification.get("valid_until")).isBefore(until));
    var out = new HashMap<String, Object>();
    out.put("safety_required", required);
    out.put("safety_acknowledged", ack);
    out.put("qualification_required", qualificationRequired);
    out.put("qualification_approved", approved);
    out.put(
        "qualification_valid_until",
        qualification == null ? null : qualification.get("valid_until"));
    out.put("safety_document_version", latest.isEmpty() ? null : latest.getFirst().get("version"));
    return out;
  }

  private String blocked(Map<String, Object> device, LocalDate day) {
    long id = Database.id(device, "id");
    if (Set.of("DELETED", "MAINTENANCE", "DISABLED", "OFFLINE", "RETIRED")
        .contains(device.get("status"))) return "设备当前不可预约";
    if (db.count(
            "SELECT COUNT(*) FROM reservation WHERE device_id=? AND status='IN_USE' AND start_date<=?",
            id,
            day)
        > 0) return "设备尚未归还验收";
    var blackout =
        db.one(
            "SELECT reason FROM v2_reservation_blackout WHERE active=1 AND blocked_date=? AND ((scope_type='DEVICE' AND scope_id=?) OR (scope_type='LAB' AND scope_id=?) OR (scope_type='COLLEGE' AND scope_id=?)) LIMIT 1",
            day,
            id,
            device.get("lab_id"),
            device.get("college_id"));
    if (blackout != null) return Database.str(blackout, "reason", "不可预约日");
    if (db.count("SELECT COUNT(*) FROM v2_reservation_day WHERE device_id=? AND date=?", id, day)
        > 0) return "设备日期已被预约";
    if (db.count(
            "SELECT COUNT(*) FROM v2_reservation_waitlist_offer WHERE device_id=? AND reservation_date=? AND expires_at>UTC_TIMESTAMP()",
            id,
            day)
        > 0) return "候补预约保留中";
    return null;
  }

  public void validateLifecycleDates(Map<String, Object> reservation, Map<String, Object> device) {
    if (db.count(
            "SELECT COUNT(*) FROM v2_reservation_blackout WHERE active=1 AND blocked_date BETWEEN ? AND ? AND ((scope_type='DEVICE' AND scope_id=?) OR (scope_type='LAB' AND scope_id=?) OR (scope_type='COLLEGE' AND scope_id=?))",
            reservation.get("start_date"),
            reservation.get("end_date"),
            device.get("id"),
            device.get("lab_id"),
            device.get("college_id"))
        > 0) throw new ApiError("DEVICE_BLACKOUT_RESTRICTION", "设备在预约日期不可交接或使用，请先处理不可预约规则", 409);
  }

  public Map<String, Object> preflight(Principal p, ReservationPlan plan) {
    p.require("reservation:create");
    var members = candidates(p, plan, false);
    var dates = plan.requestedDates();
    var first = members.getFirst();
    var policy = policies.resolve(p, first);
    validateDates(dates, policy, plan.segments());
    var days = new ArrayList<Map<String, Object>>();
    var available = new ArrayList<LocalDate>();
    var conflicts = new ArrayList<Map<String, Object>>();
    int fullAvailable = 0;
    for (var member : members)
      if (dates.stream().allMatch(d -> blocked(member, d) == null)) fullAvailable++;
    for (var day : dates) {
      int free = 0;
      for (var member : members) if (blocked(member, day) == null) free++;
      boolean can = free >= plan.quantity();
      var item = new HashMap<String, Object>();
      item.put("date", day);
      item.put("available", can);
      item.put("available_units", free);
      item.put("reservation_id", null);
      item.put("status", null);
      item.put("reason", can ? null : "所选日期可用设备数量不足");
      days.add(item);
      if (can) available.add(day);
      else conflicts.add(Map.of("date", day, "reason", "所选日期可用设备数量不足"));
    }
    if (plan.pool_id() != null && fullAvailable < plan.quantity() && conflicts.isEmpty())
      for (var day : dates) conflicts.add(Map.of("date", day, "reason", "没有同一批设备覆盖全部预约日期"));
    var data = new HashMap<String, Object>();
    data.put("device", catalog.device(p, Database.id(first, "id")));
    data.put("requested_dates", dates);
    data.put("available_dates", available);
    data.put("conflicts", conflicts);
    data.put("all_available", conflicts.isEmpty());
    data.put("requested_quantity", plan.quantity());
    data.put("available_units", fullAvailable);
    data.put("available_units_by_date", days);
    data.put("effective_policy", policy);
    data.putAll(access(p, first, dates.getLast()));
    var alternatives =
        conflicts.isEmpty()
            ? Map.of("same_device_suggestions", List.of(), "similar_device_suggestions", List.of())
            : suggestions(p, first, dates, policy.max_advance_days());
    data.putAll(alternatives);
    return data;
  }

  private Map<String, Object> suggestions(
      Principal p, Map<String, Object> device, List<LocalDate> dates, int advance) {
    var windows = new ArrayList<Map<String, Object>>();
    LocalDate horizon = BusinessTime.today().plusDays(advance);
    for (LocalDate cursor = dates.getLast().plusDays(1);
        !cursor.plusDays(dates.size() - 1).isAfter(horizon) && windows.size() < 3;
        cursor = cursor.plusDays(1)) {
      var range = cursor.datesUntil(cursor.plusDays(dates.size())).toList();
      if (range.stream().allMatch(day -> blocked(device, day) == null))
        windows.add(Map.of("start_date", cursor, "end_date", range.getLast()));
    }
    var similar = new ArrayList<Map<String, Object>>();
    for (var candidate :
        db.rows(
            "SELECT d.*,l.name lab_name,c.name category_name FROM device d LEFT JOIN lab l ON l.id=d.lab_id LEFT JOIN device_category c ON c.id=d.category_id WHERE d.id<>? AND d.college_id=? AND d.category_id=? AND d.status='IDLE' AND "
                + scope.devicePredicate(p, "d", false)
                + " ORDER BY d.id LIMIT 30",
            device.get("id"),
            device.get("college_id"),
            device.get("category_id"))) {
      if (dates.stream().anyMatch(day -> blocked(candidate, day) != null)) continue;
      var item = new HashMap<String, Object>();
      for (String key : List.of("name", "lab_name", "category_name"))
        item.put(key, candidate.get(key));
      item.put("device_id", candidate.get("id"));
      similar.add(item);
      if (similar.size() == 4) break;
    }
    return Map.of("same_device_suggestions", windows, "similar_device_suggestions", similar);
  }

  private void validateDates(
      List<LocalDate> dates, ReservationPolicy.Effective policy, List<List<LocalDate>> segments) {
    if (segments.stream().mapToInt(List::size).max().orElse(0) > policy.max_booking_days())
      throw new ApiError("DATE_RANGE_TOO_LARGE", "预约天数超过设备限制", 422);
    if (dates.getFirst().isBefore(BusinessTime.today()))
      throw new ApiError("DATE_IN_PAST", "不能预约过去的日期", 422);
    if (dates.getLast().isAfter(BusinessTime.today().plusDays(policy.max_advance_days())))
      throw new ApiError("DATE_TOO_FAR", "预约日期超过提前期限制", 422);
  }

  private record Outcome(Object value, ApiError error) {}

  public Object create(Principal p, ReservationPlan plan, String key) {
    p.require("reservation:create");
    if (key == null || key.isBlank() || key.length() > 128)
      throw ApiError.validation("需要有效 Idempotency-Key");
    String digest = requestHash(plan);
    var success = new java.util.concurrent.atomic.AtomicBoolean();
    Outcome outcome =
        transaction.execute(
            status -> {
              var user =
                  db.one(
                      "SELECT id,status,college_id FROM sys_user WHERE id=? FOR UPDATE",
                      p.userId());
              if (user == null
                  || Database.id(user, "status") != 1
                  || !Objects.equals(user.get("college_id"), p.collegeId()))
                throw ApiError.forbidden();
              Object savepoint = status.createSavepoint();
              try {
                Object value = createInTransaction(p, plan, key, digest, success);
                status.releaseSavepoint(savepoint);
                return new Outcome(value, null);
              } catch (ApiError | org.springframework.dao.DuplicateKeyException failure) {
                status.rollbackToSavepoint(savepoint);
                status.releaseSavepoint(savepoint);
                success.set(false);
                ApiError error =
                    failure instanceof ApiError api
                        ? api
                        : new ApiError("RESERVATION_CONFLICT", "所选设备日期已被预约", 409);
                if (!Set.of(
                        "IDEMPOTENCY_REUSED",
                        "REQUEST_IN_PROGRESS",
                        "FORBIDDEN",
                        "AUTH_REQUIRED",
                        "USER_NOT_FOUND")
                    .contains(error.code)) {
                  var body = new HashMap<String, Object>();
                  body.put("code", error.code);
                  body.put("message", error.getMessage());
                  body.put("data", error.data);
                  db.execute(
                      "INSERT IGNORE INTO v2_idempotency_key (user_id,`key`,request_hash,response_code,response_body,created_at) VALUES (?,?,?,?,?,UTC_TIMESTAMP())",
                      p.userId(),
                      key,
                      digest,
                      "ERR:" + error.status,
                      db.json(body));
                }
                return new Outcome(null, error);
              }
            });
    if (outcome.error() != null) throw outcome.error();
    return outcome.value();
  }

  private Object createInTransaction(
      Principal p,
      ReservationPlan plan,
      String key,
      String digest,
      java.util.concurrent.atomic.AtomicBoolean success) {
    var user = db.one("SELECT * FROM sys_user WHERE id=? FOR UPDATE", p.userId());
    if (user == null
        || Database.id(user, "status") != 1
        || !Objects.equals(user.get("college_id"), p.collegeId())) throw ApiError.forbidden();
    var existing =
        db.one("SELECT * FROM v2_idempotency_key WHERE user_id=? AND `key`=?", p.userId(), key);
    if (existing != null) {
      if (!digest.equals(existing.get("request_hash")))
        throw new ApiError("IDEMPOTENCY_REUSED", "幂等键已用于另一份请求", 409);
      if (existing.get("response_body") == null)
        throw new ApiError("REQUEST_IN_PROGRESS", "相同请求正在处理中", 409);
      Object body = db.parse(existing.get("response_body"), null);
      String code = Database.str(existing, "response_code", "");
      if (code.startsWith("ERR:") && body instanceof Map<?, ?> error)
        throw new ApiError(
            error.get("code").toString(),
            error.get("message").toString(),
            Integer.parseInt(code.substring(4)),
            error.get("data"),
            Map.of());
      return body;
    }
    if (!p.systemAdmin()
        && user.get("booking_blocked_until") instanceof LocalDateTime expiry
        && expiry.isAfter(BusinessTime.utcNow()))
      throw new ApiError("BOOKING_RESTRICTED", "当前信用状态暂时不能发起预约", 403);
    var members = candidates(p, plan, true);
    var requestedDates = plan.requestedDates();
    var dates = requestedDates;
    boolean partial =
        plan.device_id() != null
            && plan.quantity() == 1
            && plan.dates() != null
            && plan.commit_mode().equals("available_only");
    var skipped = new ArrayList<Map<String, Object>>();
    var selected = new ArrayList<Map<String, Object>>();
    for (var member : members) {
      var policy = policies.resolve(p, member);
      validateDates(requestedDates, policy, plan.segments());
      boolean free =
          partial
              ? requestedDates.stream().anyMatch(d -> blocked(member, d) == null)
              : requestedDates.stream().allMatch(d -> blocked(member, d) == null);
      if (free) selected.add(member);
      if (selected.size() == plan.quantity()) break;
    }
    if (selected.size() != plan.quantity())
      throw new ApiError("RESERVATION_CONFLICT", "所选日期存在冲突，请重新选择", 409);
    if (partial) {
      var chosen = selected.getFirst();
      dates = requestedDates.stream().filter(day -> blocked(chosen, day) == null).toList();
      for (var day : requestedDates)
        if (!dates.contains(day)) {
          var conflict = new HashMap<String, Object>();
          conflict.put("date", day);
          conflict.put("reason", blocked(chosen, day));
          conflict.put("reservation_id", null);
          conflict.put("status", null);
          skipped.add(conflict);
        }
    }
    final List<LocalDate> committedDates = dates;
    long quotaPool =
        plan.pool_id() != null
            ? plan.pool_id()
            : selected.getFirst().get("pool_id") == null
                ? Database.id(selected.getFirst(), "id")
                : Database.id(selected.getFirst(), "pool_id");
    String quotaToken = p.userId() + ":" + key;
    boolean held =
        quotas.hold(
            quotaPool,
            selected.stream().map(d -> Database.id(d, "id")).toList(),
            committedDates,
            quotaToken);
    org.springframework.transaction.support.TransactionSynchronizationManager
        .registerSynchronization(
            new org.springframework.transaction.support.TransactionSynchronization() {
              @Override
              public void afterCompletion(int status) {
                if (status == STATUS_COMMITTED && success.get()) {
                  if (held) quotas.finalizeHold(quotaPool, quotaToken);
                } else quotas.invalidate(quotaPool, committedDates, quotaToken);
              }
            });
    String batch =
        plan.dates() != null || plan.windows() != null || plan.quantity() > 1
            ? UUID.randomUUID().toString().replace("-", "")
            : null;
    var created = new ArrayList<Map<String, Object>>();
    db.insert(
        "INSERT INTO v2_idempotency_key (user_id,`key`,request_hash,created_at) VALUES (?,?,?,UTC_TIMESTAMP())",
        p.userId(),
        key,
        digest);
    for (var member : selected) {
      long deviceId = Database.id(member, "id");
      var policy = policies.resolve(p, member);
      var access = access(p, member, dates.getLast());
      if (Boolean.TRUE.equals(access.get("safety_required"))
          && !Boolean.TRUE.equals(access.get("safety_acknowledged")))
        throw new ApiError("SAFETY_ACK_REQUIRED", "预约前请阅读并确认最新版安全须知", 409);
      if (Boolean.TRUE.equals(access.get("qualification_required"))
          && !Boolean.TRUE.equals(access.get("qualification_approved")))
        throw new ApiError("QUALIFICATION_REQUIRED", "使用资质未通过或不能覆盖预约日期", 403);
      for (var requestedSegment : plan.segments()) {
        var segment = requestedSegment.stream().filter(committedDates::contains).toList();
        if (segment.isEmpty()) continue;
        String status = policy.approval_required() ? "PENDING" : "APPROVED";
        long id =
            db.insert(
                "INSERT INTO reservation (college_id,user_id,device_id,purpose,purpose_category,project_reference,start_date,end_date,start_time,end_time,slot_count,status,batch_id,handover_status,safety_document_version,safety_acknowledged_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'PENDING',?,?,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
                member.get("college_id"),
                p.userId(),
                deviceId,
                plan.purpose().strip(),
                plan.purpose_category(),
                plan.project_reference(),
                segment.getFirst(),
                segment.getLast(),
                segment.getFirst().atStartOfDay(),
                segment.getLast().atTime(23, 59, 59),
                segment.size(),
                status,
                batch,
                access.get("safety_document_version"),
                Boolean.TRUE.equals(access.get("safety_required")) ? BusinessTime.utcNow() : null);
        for (var day : segment)
          db.execute(
              "INSERT INTO v2_reservation_day (reservation_id,device_id,date) VALUES (?,?,?)",
              id,
              deviceId,
              day);
        db.execute(
            "INSERT INTO v2_device_handover (reservation_id,device_id,user_id,college_id,status,accessory_snapshot) VALUES (?,?,?,?,'PENDING',?)",
            id,
            deviceId,
            p.userId(),
            member.get("college_id"),
            db.json(db.parse(member.get("accessory_checklist"), List.of())));
        created.add(get(p, id));
        events.audit(p, "RESERVATION_CREATE", "RESERVATION", id, Map.of("dates", segment));
        if (status.equals("APPROVED"))
          events.task(
              "timeout:reservation:" + id + ":unclaimed-cancel",
              "RESERVATION_UNCLAIMED_CANCEL",
              "reservation:" + id,
              (Long) member.get("college_id"),
              Map.of("reservation_id", id),
              BusinessTime.dayEnd(segment.getFirst()));
      }
    }
    var result = new HashMap<String, Object>();
    result.put("created", created);
    result.put("skipped_conflicts", skipped);
    result.put("batch_id", batch);
    db.execute(
        "UPDATE v2_idempotency_key SET response_code='OK',response_body=? WHERE user_id=? AND `key`=?",
        db.json(result),
        p.userId(),
        key);
    success.set(true);
    return result;
  }

  private String requestHash(ReservationPlan plan) {
    var value = new TreeMap<String, Object>();
    value.put("quantity", plan.quantity());
    value.put("purpose", plan.purpose());
    value.put("purpose_category", plan.purpose_category());
    value.put("commit_mode", plan.commit_mode());
    if (plan.device_id() != null) value.put("device_id", plan.device_id());
    if (plan.pool_id() != null) value.put("pool_id", plan.pool_id());
    if (plan.preferred_device_id() != null)
      value.put("preferred_device_id", plan.preferred_device_id());
    if (plan.project_reference() != null) value.put("project_reference", plan.project_reference());
    if (plan.start_date() != null) value.put("start_date", plan.start_date().toString());
    if (plan.end_date() != null) value.put("end_date", plan.end_date().toString());
    if (plan.dates() != null)
      value.put("dates", plan.dates().stream().map(LocalDate::toString).toList());
    if (plan.windows() != null)
      value.put(
          "windows",
          plan.windows().stream()
              .map(
                  w ->
                      new TreeMap<>(
                          Map.of(
                              "start_date",
                              w.start_date().toString(),
                              "end_date",
                              w.end_date().toString())))
              .toList());
    return AuthService.sha256(pythonJson(value));
  }

  private String pythonJson(Object value) {
    if (value instanceof Map<?, ?> m)
      return "{"
          + String.join(
              ", ",
              m.entrySet().stream()
                  .map(e -> db.json(e.getKey()) + ": " + pythonJson(e.getValue()))
                  .toList())
          + "}";
    if (value instanceof Collection<?> c)
      return "[" + String.join(", ", c.stream().map(this::pythonJson).toList()) + "]";
    return db.json(value);
  }

  public Map<String, Object> get(Principal p, long id) {
    var row = db.one(SELECT + "WHERE r.id=?", id);
    if (row == null) throw new ApiError("RESERVATION_NOT_FOUND", "预约不存在", 404);
    if (Database.id(row, "user_id") != p.userId()) {
      p.require("reservation:read:scope");
      scope.device(p, Database.id(row, "device_id"), true);
    } else if (!p.systemAdmin() && Database.id(row, "college_id") != p.tenant())
      throw ApiError.forbidden();
    return decorate(row);
  }

  private Map<String, Object> decorate(Map<String, Object> row) {
    var start = (LocalDate) row.get("start_date");
    var end = (LocalDate) row.get("end_date");
    row.put("dates", start.datesUntil(end.plusDays(1)).toList());
    for (String field :
        List.of(
            "accessory_snapshot",
            "handover_checklist",
            "return_checklist",
            "handover_image_urls",
            "return_image_urls")) row.put(field, db.parse(row.get(field), List.of()));
    row.put("requires_handover", true);
    row.put("safety_required", Database.id(row, "requires_safety_ack") == 1);
    row.put("safety_acknowledged", row.get("safety_acknowledged_at") != null);
    return row;
  }

  public Map<String, Object> list(
      Principal p, Pagination page, String kind, String status, String handover) {
    String where;
    if (kind.equals("mine")) {
      p.require("reservation:read:own");
      where = "r.user_id=" + p.userId() + " AND " + scope.devicePredicate(p, "d", false);
    } else {
      p.require(kind.equals("approvals") ? "reservation:approve" : "reservation:handover");
      where = scope.devicePredicate(p, "d", true);
      if (kind.equals("approvals")) where += " AND r.status='PENDING'";
      else if (kind.equals("handovers"))
        where +=
            "RETURN_PENDING".equals(handover)
                ? " AND r.status='IN_USE'"
                : " AND r.status='APPROVED'";
    }
    var params = new ArrayList<Object>();
    if (status != null && !status.isBlank()) {
      where += " AND r.status=?";
      params.add(status);
    }
    if (handover != null && !handover.isBlank()) {
      where += " AND r.handover_status=?";
      params.add(handover);
    }
    long total =
        db.count(
            "SELECT COUNT(*) FROM reservation r JOIN device d ON d.id=r.device_id WHERE " + where,
            params.toArray());
    params.add(page.size());
    params.add(page.offset());
    String ids =
        "SELECT r.id FROM reservation r JOIN device d ON d.id=r.device_id WHERE "
            + where
            + " ORDER BY r.id DESC LIMIT ? OFFSET ?";
    var rows =
        db.rows(
            SELECT + "JOIN (" + ids + ") page_ids ON page_ids.id=r.id ORDER BY r.id DESC",
            params.toArray());
    rows.forEach(this::decorate);
    return page.result(rows, total);
  }

  public List<Map<String, Object>> availability(
      Principal p, long id, boolean pool, LocalDate start, LocalDate end) {
    p.require("device:read");
    if (end.isBefore(start) || start.datesUntil(end.plusDays(1)).count() > 31)
      throw ApiError.validation("查询范围应为 1 至 31 天");
    var members =
        pool
            ? db.rows(
                "SELECT * FROM device WHERE pool_id=? AND status<>'DELETED' AND "
                    + scope.devicePredicate(p, "device", false),
                id)
            : List.of(scope.device(p, id, false));
    var out = new ArrayList<Map<String, Object>>();
    for (var day : start.datesUntil(end.plusDays(1)).toList()) {
      long free = members.stream().filter(d -> blocked(d, day) == null).count();
      var item = new HashMap<String, Object>();
      item.put("date", day);
      item.put("available", free > 0);
      item.put("available_units", free);
      item.put("reservation_id", null);
      var occupied =
          members.isEmpty()
              ? null
              : db.one(
                  "SELECT r.id,r.status FROM v2_reservation_day rd JOIN reservation r ON r.id=rd.reservation_id WHERE rd.device_id=? AND rd.date=?",
                  members.getFirst().get("id"),
                  day);
      item.put("reservation_id", occupied == null ? null : occupied.get("id"));
      item.put("status", occupied == null ? null : occupied.get("status"));
      item.put(
          "reason",
          free > 0 ? null : members.isEmpty() ? "不可预约" : blocked(members.getFirst(), day));
      out.add(item);
    }
    return out;
  }
}
