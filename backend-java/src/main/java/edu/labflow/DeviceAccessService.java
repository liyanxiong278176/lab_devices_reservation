package edu.labflow;

import java.time.LocalDate;
import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class DeviceAccessService {
  private final Database db;
  private final ScopeAccess scope;
  private final BusinessEvents events;
  private final ReservationService reservations;

  public DeviceAccessService(
      Database db, ScopeAccess scope, BusinessEvents events, ReservationService reservations) {
    this.db = db;
    this.scope = scope;
    this.events = events;
    this.reservations = reservations;
  }

  private static final String DOCS =
      "SELECT doc.*,a.original_name,a.content_type,a.size_bytes,a.asset_token FROM v2_device_document doc JOIN v2_upload_asset a ON a.id=doc.asset_id ";

  private Map<String, Object> doc(Map<String, Object> row) {
    row.put("url", "/api/v2/device-documents/" + row.remove("asset_token"));
    return row;
  }

  public List<Map<String, Object>> documents(Principal p, long device, boolean safety) {
    p.require("device:read");
    scope.device(p, device, false);
    var rows =
        db.rows(
            DOCS
                + "WHERE doc.device_id=? AND doc.active=1"
                + (safety ? " AND doc.requires_ack=1" : "")
                + " ORDER BY doc.document_type,doc.id DESC",
            device);
    if (safety) {
      var seen = new HashSet<String>();
      rows = rows.stream().filter(r -> seen.add(r.get("document_type").toString())).toList();
    }
    rows.forEach(this::doc);
    return rows;
  }

  @Transactional
  public Map<String, Object> publish(
      Principal p,
      long device,
      Map<String, Object> asset,
      String type,
      String title,
      String version,
      boolean ack) {
    p.require("device:documents:manage");
    var d = scope.device(p, device, true);
    if (!Set.of("MANUAL", "SOP", "SAFETY").contains(type)
        || title == null
        || title.strip().isEmpty()
        || title.length() > 200
        || version == null
        || version.isBlank()
        || version.length() > 40) throw ApiError.validation("文档类型、标题或版本无效");
    long id =
        db.insert(
            "INSERT INTO v2_device_document (device_id,college_id,asset_id,document_type,title,active,created_by,version,requires_ack,published_at) VALUES (?,?,?,?,?,1,?,?,?,UTC_TIMESTAMP())",
            device,
            d.get("college_id"),
            asset.get("asset_id"),
            type,
            title.strip(),
            p.userId(),
            version,
            ack);
    events.audit(p, "DEVICE_DOCUMENT_PUBLISH", "DEVICE_DOCUMENT", id, Map.of("device_id", device));
    return doc(db.one(DOCS + "WHERE doc.id=?", id));
  }

  @Transactional
  public void archive(Principal p, long device, long doc) {
    p.require("device:documents:manage");
    scope.device(p, device, true);
    if (db.execute(
            "UPDATE v2_device_document SET active=0 WHERE id=? AND device_id=? AND active=1",
            doc,
            device)
        != 1) throw new ApiError("DOCUMENT_NOT_FOUND", "文档不存在", 404);
    events.audit(p, "DEVICE_DOCUMENT_ARCHIVE", "DEVICE_DOCUMENT", doc, Map.of());
  }

  public Map<String, Object> access(Principal p, long device) {
    p.require("device:read");
    return reservations.access(p, scope.device(p, device, false), BusinessTime.today());
  }

  @Transactional
  public Map<String, Object> acknowledge(Principal p, long device, Long reservation) {
    var d = scope.device(p, device, false);
    var docs = documents(p, device, true);
    if (docs.isEmpty()) throw new ApiError("SAFETY_DOCUMENT_NOT_FOUND", "该设备尚未发布需要确认的安全文档", 409);
    if (reservation != null) {
      var r = reservations.get(p, reservation);
      if (Database.id(r, "user_id") != p.userId() || Database.id(r, "device_id") != device)
        throw ApiError.forbidden();
    }
    for (var doc : docs)
      db.execute(
          "INSERT INTO v2_device_document_ack (document_id,device_id,user_id,college_id,reservation_id,document_version,acknowledged_at) VALUES (?,?,?,?,?,?,UTC_TIMESTAMP()) ON DUPLICATE KEY UPDATE reservation_id=VALUES(reservation_id),document_version=VALUES(document_version),acknowledged_at=UTC_TIMESTAMP()",
          doc.get("id"),
          device,
          p.userId(),
          d.get("college_id"),
          reservation,
          doc.get("version"));
    events.audit(p, "DEVICE_SAFETY_ACK", "DEVICE", device, Map.of());
    return Map.of(
        "device_id", device, "acknowledged", true, "version", docs.getFirst().get("version"));
  }

  public Object myQualification(Principal p, long device) {
    scope.device(p, device, false);
    return db.one(
        "SELECT * FROM v2_device_qualification WHERE device_id=? AND user_id=?",
        device,
        p.userId());
  }

  public List<Map<String, Object>> qualifications(Principal p, long device) {
    p.require("device:manage");
    scope.device(p, device, true);
    return db.rows(
        "SELECT * FROM v2_device_qualification WHERE device_id=? ORDER BY id DESC", device);
  }

  @Transactional
  public Object submit(Principal p, long device, Map<String, Object> data) {
    var d = scope.device(p, device, false);
    String type = Database.str(data, "qualification_type", "TRAINING");
    if (type.length() < 2 || type.length() > 80) throw ApiError.validation("资质类型无效");
    Long asset = data.get("asset_id") == null ? null : Database.id(data, "asset_id");
    if (asset != null
        && db.count(
                "SELECT COUNT(*) FROM v2_upload_asset WHERE id=? AND user_id=? AND college_id=?",
                asset,
                p.userId(),
                d.get("college_id"))
            != 1) throw ApiError.forbidden();
    db.execute(
        "INSERT INTO v2_device_qualification (device_id,user_id,college_id,status,qualification_type,asset_id,note) VALUES (?,?,?,'PENDING',?,?,?) ON DUPLICATE KEY UPDATE status='PENDING',qualification_type=VALUES(qualification_type),asset_id=VALUES(asset_id),note=VALUES(note),reviewed_by=NULL,reviewed_at=NULL,valid_until=NULL,updated_at=UTC_TIMESTAMP()",
        device,
        p.userId(),
        d.get("college_id"),
        type,
        asset,
        data.get("note"));
    events.audit(p, "DEVICE_QUALIFICATION_SUBMIT", "DEVICE", device, Map.of());
    return myQualification(p, device);
  }

  @Transactional
  public Object review(Principal p, long device, long id, Map<String, Object> data) {
    p.require("device:manage");
    scope.device(p, device, true);
    String status = Database.str(data, "status", "");
    if (!Set.of("APPROVED", "REJECTED").contains(status)) throw ApiError.validation("资质审核状态无效");
    LocalDate until =
        data.get("valid_until") == null
            ? null
            : LocalDate.parse(data.get("valid_until").toString());
    if (until != null && until.isBefore(BusinessTime.today()))
      throw ApiError.validation("资质有效期不能早于今天");
    if (db.execute(
            "UPDATE v2_device_qualification SET status=?,valid_until=?,reviewed_by=?,reviewed_at=UTC_TIMESTAMP(),note=?,updated_at=UTC_TIMESTAMP() WHERE id=? AND device_id=? AND status='PENDING'",
            status,
            until,
            p.userId(),
            data.get("note"),
            id,
            device)
        != 1) throw new ApiError("QUALIFICATION_STATE_CONFLICT", "资质已处理或不存在", 409);
    events.audit(p, "DEVICE_QUALIFICATION_REVIEW", "QUALIFICATION", id, Map.of("status", status));
    return db.one("SELECT * FROM v2_device_qualification WHERE id=?", id);
  }

  @Transactional
  public Object feedback(Principal p, long id, Map<String, Object> data) {
    p.require("feedback:create");
    var r = reservations.get(p, id);
    if (Database.id(r, "user_id") != p.userId()) throw ApiError.forbidden();
    if (!"COMPLETED".equals(r.get("status")))
      throw new ApiError("FEEDBACK_NOT_ALLOWED", "完成预约后才能评价", 409);
    long rating = Database.id(data, "rating");
    if (rating < 1 || rating > 5) throw ApiError.validation("评分须为 1 至 5");
    long result =
        db.insert(
            "INSERT INTO v2_reservation_feedback (reservation_id,device_id,user_id,college_id,rating,comment) VALUES (?,?,?,?,?,?)",
            id,
            r.get("device_id"),
            p.userId(),
            r.get("college_id"),
            rating,
            data.get("comment"));
    return db.one("SELECT * FROM v2_reservation_feedback WHERE id=?", result);
  }

  public Object feedback(Principal p, long id) {
    var r = reservations.get(p, id);
    p.require(
        Database.id(r, "user_id") == p.userId() ? "feedback:read:own" : "feedback:read:scope");
    return db.one("SELECT * FROM v2_reservation_feedback WHERE reservation_id=?", id);
  }
}
