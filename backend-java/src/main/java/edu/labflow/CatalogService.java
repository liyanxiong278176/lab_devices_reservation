package edu.labflow;

import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class CatalogService {
  private final Database db;
  private final ScopeAccess scope;
  private final DeviceLifecycle lifecycle;
  static final String DEVICE_SELECT =
      "SELECT d.*,l.name lab_name,c.name college_name,cat.name category_name FROM device d LEFT JOIN lab l ON l.id=d.lab_id LEFT JOIN college c ON c.id=d.college_id LEFT JOIN device_category cat ON cat.id=d.category_id ";

  public CatalogService(Database db, ScopeAccess scope, DeviceLifecycle lifecycle) {
    this.db = db;
    this.scope = scope;
    this.lifecycle = lifecycle;
  }

  public Map<String, Object> device(Principal p, long id) {
    p.require("device:read");
    var row = scope.device(p, id, false);
    if ("DELETED".equals(row.get("status"))) throw new ApiError("DEVICE_NOT_FOUND", "设备不存在", 404);
    return decorate(row);
  }

  public Map<String, Object> decorate(Map<String, Object> row) {
    row.remove("lab_manager");
    row.remove("college_manager");
    row.put("tags", db.parse(row.get("tags"), null));
    row.put("accessory_checklist", db.parse(row.get("accessory_checklist"), List.of()));
    row.put("pool_quantity", 1);
    row.put("pool_idle_quantity", Database.str(row, "status", "").equals("IDLE") ? 1 : 0);
    row.put("maintenance_warning", null);
    return row;
  }

  public Map<String, Object> devices(
      Principal p,
      Pagination pagination,
      String search,
      Long labId,
      String status,
      boolean grouped) {
    return devices(p, pagination, search, labId, status, grouped, false);
  }

  public Map<String, Object> devices(
      Principal p,
      Pagination pagination,
      String search,
      Long labId,
      String status,
      boolean grouped,
      boolean manage) {
    p.require(manage ? "maintenance:manage" : "device:read");
    String where = scope.devicePredicate(p, "d", manage) + " AND d.status<>'DELETED'";
    var params = new ArrayList<Object>();
    if (search != null && !search.isBlank()) {
      where += " AND (d.name LIKE ? OR d.brand LIKE ? OR d.model LIKE ? OR d.asset_code LIKE ?)";
      for (int i = 0; i < 4; i++) params.add("%" + search + "%");
    }
    if (labId != null) {
      where += " AND d.lab_id=?";
      params.add(labId);
    }
    if (status != null && !status.isBlank()) {
      where += " AND d.status=?";
      params.add(status);
    }
    String key = grouped ? "COALESCE(d.pool_id,d.id)" : "d.id";
    long total =
        db.count(
            "SELECT COUNT(DISTINCT " + key + ") FROM device d WHERE " + where, params.toArray());
    var pageParams = new ArrayList<>(params);
    pageParams.add(pagination.size());
    pageParams.add(pagination.offset());
    String ids =
        "SELECT MIN(d.id) id FROM device d WHERE "
            + where
            + " GROUP BY "
            + key
            + " ORDER BY MIN(d.id) DESC LIMIT ? OFFSET ?";
    var rows =
        db.rows(
            DEVICE_SELECT + " JOIN (" + ids + ") page_ids ON page_ids.id=d.id ORDER BY d.id DESC",
            pageParams.toArray());
    for (var row : rows) {
      decorate(row);
      if (grouped && row.get("pool_id") != null) poolCounts(row);
    }
    return pagination.result(rows, total);
  }

  private void poolCounts(Map<String, Object> row) {
    var counts =
        db.one(
            "SELECT COUNT(*) total,SUM(status='IDLE') idle FROM device WHERE pool_id=? AND status<>'DELETED'",
            row.get("pool_id"));
    row.put("pool_quantity", Database.id(counts, "total"));
    row.put("pool_idle_quantity", Database.id(counts, "idle"));
  }

  public Map<String, Object> pool(Principal p, long poolId) {
    p.require("device:read");
    var row =
        db.one(
            DEVICE_SELECT
                + "WHERE d.pool_id=? AND "
                + scope.devicePredicate(p, "d", false)
                + " AND d.status<>'DELETED' ORDER BY d.id LIMIT 1",
            poolId);
    if (row == null) throw new ApiError("DEVICE_POOL_NOT_FOUND", "设备资源池不存在", 404);
    decorate(row);
    poolCounts(row);
    return row;
  }

  public List<Map<String, Object>> pools(Principal p) {
    p.require("device:read");
    return db.rows(
        "SELECT dp.id,dp.name,dp.college_id,dp.lab_id,l.name lab_name,COUNT(d.id) unit_count FROM v2_device_pool dp JOIN device d ON d.pool_id=dp.id LEFT JOIN lab l ON l.id=dp.lab_id WHERE "
            + scope.devicePredicate(p, "d", false)
            + " AND d.status<>'DELETED' GROUP BY dp.id,dp.name,dp.college_id,dp.lab_id,l.name ORDER BY dp.id DESC");
  }

  static final List<String> WRITABLE =
      List.of(
          "name",
          "lab_id",
          "category_id",
          "brand",
          "model",
          "specs",
          "image_url",
          "description",
          "need_approval",
          "max_reservation_days",
          "tags",
          "accessory_checklist",
          "asset_code",
          "serial_number",
          "purchase_date",
          "warranty_until",
          "allow_external_loan",
          "risk_level",
          "requires_safety_ack",
          "requires_qualification",
          "max_advance_days",
          "pool_id");

  @Transactional
  public Map<String, Object> write(Principal p, Long id, Map<String, Object> data) {
    p.require("device:manage");
    if (id != null) scope.device(p, id, true);
    String name = Database.str(data, "name", "").strip();
    if (name.isEmpty() || name.length() > 100) throw ApiError.validation("请填写设备名称");
    long lab = Database.id(data, "lab_id");
    if (!scope.manages(p, "LAB", lab)) throw ApiError.forbidden();
    var laboratory = db.one("SELECT * FROM lab WHERE id=? AND status=1", lab);
    if (laboratory == null) throw ApiError.validation("实验室不存在");
    Long pool = data.get("pool_id") == null ? null : Database.id(data, "pool_id");
    if (pool == null && id != null) {
      var previous = scope.device(p, id, true);
      pool = previous.get("pool_id") == null ? null : Database.id(previous, "pool_id");
    }
    if (pool != null
        && db.count(
                "SELECT COUNT(*) FROM v2_device_pool WHERE id=? AND lab_id=? AND college_id=?",
                pool,
                lab,
                laboratory.get("college_id"))
            != 1) throw ApiError.validation("资源池与实验室不匹配");
    int days = ((Number) data.getOrDefault("max_reservation_days", 8)).intValue();
    if (days < 1 || days > 31) throw ApiError.validation("预约天数须为 1 至 31");
    data = new HashMap<>(data);
    data.put("name", name);
    data.put("max_reservation_days", days);
    data.putIfAbsent("need_approval", false);
    data.putIfAbsent("risk_level", "STANDARD");
    data.putIfAbsent("allow_external_loan", false);
    data.putIfAbsent("requires_safety_ack", false);
    data.putIfAbsent("requires_qualification", false);
    data.putIfAbsent("accessory_checklist", List.of());
    for (String column : WRITABLE) data.putIfAbsent(column, null);
    data.put("pool_id", pool);
    for (String field : List.of("tags", "accessory_checklist"))
      if (data.containsKey(field)) data.put(field, db.json(data.get(field)));
    var columns = new ArrayList<String>();
    var params = new ArrayList<Object>();
    for (String column : WRITABLE)
      if (data.containsKey(column)) {
        columns.add(column);
        params.add(data.get(column));
      }
    columns.add("college_id");
    params.add(laboratory.get("college_id"));
    if (id == null) {
      id =
          db.insert(
              "INSERT INTO device ("
                  + String.join(",", columns)
                  + ") VALUES ("
                  + String.join(",", Collections.nCopies(columns.size(), "?"))
                  + ")",
              params.toArray());
      if (pool == null) {
        pool =
            db.insert(
                "INSERT INTO v2_device_pool (name,college_id,lab_id) VALUES (?,?,?)",
                name,
                laboratory.get("college_id"),
                lab);
        db.execute("UPDATE device SET pool_id=? WHERE id=?", pool, id);
      }
      if (data.get("asset_code") == null)
        db.execute("UPDATE device SET asset_code=? WHERE id=?", String.format("LAB-%06d", id), id);
    } else {
      params.add(id);
      db.execute(
          "UPDATE device SET "
              + String.join(",", columns.stream().map(c -> c + "=?").toList())
              + ",updated_at=CURRENT_TIMESTAMP WHERE id=?",
          params.toArray());
    }
    db.execute(
        "INSERT INTO v2_reservation_rule (scope_type,scope_id,user_category,max_booking_days,max_advance_days,approval_required,created_by,updated_by) VALUES ('DEVICE',?,'ALL',?,?,?,?,?) ON DUPLICATE KEY UPDATE max_booking_days=VALUES(max_booking_days),max_advance_days=VALUES(max_advance_days),approval_required=VALUES(approval_required),updated_by=VALUES(updated_by)",
        id,
        days,
        data.get("max_advance_days"),
        data.get("need_approval"),
        p.userId(),
        p.userId());
    if (pool != null) {
      var shared =
          WRITABLE.stream()
              .filter(
                  c ->
                      !Set.of(
                              "asset_code",
                              "serial_number",
                              "purchase_date",
                              "warranty_until",
                              "pool_id")
                          .contains(c))
              .toList();
      var sharedParams = new ArrayList<Object>();
      for (String field : shared) sharedParams.add(data.get(field));
      sharedParams.add(laboratory.get("college_id"));
      sharedParams.add(pool);
      db.execute(
          "UPDATE device SET "
              + String.join(",", shared.stream().map(c -> c + "=?").toList())
              + ",college_id=?,updated_at=UTC_TIMESTAMP() WHERE pool_id=? AND status<>'DELETED'",
          sharedParams.toArray());
      db.execute(
          "UPDATE v2_device_pool SET name=?,lab_id=?,college_id=?,updated_at=UTC_TIMESTAMP() WHERE id=?",
          name,
          lab,
          laboratory.get("college_id"),
          pool);
      db.execute(
          "INSERT INTO v2_reservation_rule (scope_type,scope_id,user_category,max_booking_days,max_advance_days,approval_required,created_by,updated_by) SELECT 'DEVICE',id,'ALL',max_reservation_days,max_advance_days,need_approval,?,? FROM device WHERE pool_id=? ON DUPLICATE KEY UPDATE max_booking_days=VALUES(max_booking_days),max_advance_days=VALUES(max_advance_days),approval_required=VALUES(approval_required),updated_by=VALUES(updated_by)",
          p.userId(),
          p.userId(),
          pool);
    }
    var result = decorate(scope.device(p, id, false));
    if (pool != null) poolCounts(result);
    return result;
  }

  @Transactional
  public void status(Principal p, long id, String status, String reason) {
    p.require("device:manage");
    scope.device(p, id, true);
    if (!Set.of("IDLE", "MAINTENANCE", "DISABLED", "OFFLINE", "RETIRED").contains(status))
      throw ApiError.validation("设备状态无效");
    if (status.equals("IDLE")
        && db.count(
                "SELECT COUNT(*) FROM v2_repair_report WHERE device_id=? AND status IN ('PENDING','PROCESSING','RESOLVED')",
                id)
            > 0) throw new ApiError("DEVICE_HAS_OPEN_REPAIR", "存在未完成报修，不能恢复为空闲", 409);
    lifecycle.change(p, id, status, reason);
  }

  @Transactional
  public void delete(Principal p, long id) {
    p.require("device:manage");
    scope.device(p, id, true);
    if (db.count(
            "SELECT COUNT(*) FROM reservation WHERE device_id=? AND status IN ('PENDING','APPROVED','IN_USE')",
            id)
        > 0) throw new ApiError("DEVICE_HAS_ACTIVE_RESERVATIONS", "设备仍有有效预约，不能删除", 409);
    lifecycle.change(p, id, "DELETED", "负责人删除设备");
  }
}
