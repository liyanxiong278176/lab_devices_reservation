package edu.labflow;

import java.time.*;
import java.util.*;
import org.springframework.stereotype.Service;

@Service
public class DashboardService {
  private final Database db;
  private final ScopeAccess scope;

  public DashboardService(Database db, ScopeAccess scope) {
    this.db = db;
    this.scope = scope;
  }

  private Map<String, Long> status(String sql, Object... params) {
    var out = new HashMap<String, Long>();
    for (var row : db.rows(sql, params))
      out.put(row.get("status").toString(), Database.id(row, "count"));
    return out;
  }

  private List<Map<String, Object>> series(
      LocalDate start, LocalDate end, List<Map<String, Object>> rows) {
    var counts = new HashMap<LocalDate, Long>();
    for (var row : rows) counts.put((LocalDate) row.get("date"), Database.id(row, "count"));
    return start
        .datesUntil(end.plusDays(1))
        .map(d -> Map.<String, Object>of("date", d, "count", counts.getOrDefault(d, 0L)))
        .toList();
  }

  public Object me(Principal p) {
    p.require("dashboard:read");
    String where = "r.user_id=" + p.userId() + " AND " + scope.devicePredicate(p, "d", false);
    LocalDate today = BusinessTime.today(), start = today.minusDays(29);
    var result = new HashMap<String, Object>();
    result.put(
        "myReservationsByStatus",
        status(
            "SELECT r.status,COUNT(*) count FROM reservation r JOIN device d ON d.id=r.device_id WHERE "
                + where
                + " GROUP BY r.status"));
    result.put(
        "myTrend30d",
        series(
            start,
            today,
            db.rows(
                "SELECT r.start_date date,COUNT(*) count FROM reservation r JOIN device d ON d.id=r.device_id WHERE "
                    + where
                    + " AND r.start_date BETWEEN ? AND ? GROUP BY r.start_date",
                start,
                today)));
    result.put(
        "myCategoryDist",
        db.rows(
            "SELECT COALESCE(c.id,0) categoryId,COALESCE(c.name,'未分类') categoryName,COUNT(*) count FROM reservation r JOIN device d ON d.id=r.device_id LEFT JOIN device_category c ON c.id=d.category_id WHERE "
                + where
                + " GROUP BY c.id,c.name"));
    result.put(
        "unreadCount",
        db.count(
            "SELECT COUNT(*) FROM notification WHERE user_id=? AND is_read=0"
                + (p.systemAdmin() ? "" : " AND college_id=" + p.tenant()),
            p.userId()));
    result.put(
        "myRepairCount",
        db.count(
            "SELECT COUNT(*) FROM v2_repair_report rr JOIN device d ON d.id=rr.device_id WHERE rr.reporter_id=? AND "
                + scope.devicePredicate(p, "d", false),
            p.userId()));
    return result;
  }

  public Object overview(Principal p, String group, int days) {
    p.require("dashboard:read");
    if (!p.manager()) throw ApiError.forbidden();
    if (!Set.of("device", "category").contains(group) || days < 1 || days > 365)
      throw ApiError.validation("统计分组或天数无效");
    String where = scope.devicePredicate(p, "d", true);
    LocalDate today = BusinessTime.today(), start = today.minusDays(days - 1);
    var devices =
        db.rows(
            "SELECT d.*,cat.name category_name FROM device d LEFT JOIN device_category cat ON cat.id=d.category_id WHERE "
                + where);
    var result = new HashMap<String, Object>();
    result.put("deviceStatus", ReportService.counts(devices));
    result.put(
        "trend30d",
        series(
            start,
            today,
            db.rows(
                "SELECT r.start_date date,COUNT(*) count FROM reservation r JOIN device d ON d.id=r.device_id WHERE "
                    + where
                    + " AND r.status NOT IN ('CANCELLED','REJECTED') AND r.start_date BETWEEN ? AND ? GROUP BY r.start_date",
                start,
                today)));
    result.put(
        "cards",
        Map.of(
            "todayReservations",
            db.count(
                "SELECT COUNT(*) FROM reservation r JOIN device d ON d.id=r.device_id WHERE "
                    + where
                    + " AND r.status IN ('PENDING','APPROVED','IN_USE') AND ? BETWEEN r.start_date AND r.end_date",
                today),
            "pendingApprovals",
            db.count(
                "SELECT COUNT(*) FROM reservation r JOIN device d ON d.id=r.device_id WHERE "
                    + where
                    + " AND r.status='PENDING'")));
    result.put(
        "categoryDist",
        db.rows(
            "SELECT COALESCE(c.id,0) categoryId,COALESCE(c.name,'未分类') categoryName,COUNT(*) deviceCount FROM device d LEFT JOIN device_category c ON c.id=d.category_id WHERE "
                + where
                + " GROUP BY c.id,c.name"));
    result.put(
        "repairStats",
        status(
            "SELECT rr.status,COUNT(*) count FROM v2_repair_report rr JOIN device d ON d.id=rr.device_id WHERE "
                + where
                + " GROUP BY rr.status"));
    result.put(
        "heatmap",
        db.rows(
            "SELECT DAYOFWEEK(r.start_date) dayOfWeek,0 hour,COUNT(*) count FROM reservation r JOIN device d ON d.id=r.device_id WHERE "
                + where
                + " AND r.start_date BETWEEN ? AND ? GROUP BY r.start_date",
            start,
            today));
    var utilization = new LinkedHashMap<String, Map<String, Object>>();
    for (var d : devices) {
      String key =
          group.equals("category")
              ? "category:" + Database.id(d, "category_id")
              : "device:" + d.get("id");
      var entry =
          utilization.computeIfAbsent(
              key,
              k ->
                  new HashMap<>(
                      Map.of(
                          "key",
                          k,
                          "label",
                          group.equals("category")
                              ? Database.str(d, "category_name", "未分类")
                              : d.get("name"),
                          "occupiedSlots",
                          0L,
                          "availableSlots",
                          0L)));
      long occupied =
          db.count(
              "SELECT COUNT(*) FROM v2_reservation_day rd JOIN reservation r ON r.id=rd.reservation_id WHERE rd.device_id=? AND rd.date BETWEEN ? AND ? AND r.status IN ('PENDING','APPROVED','IN_USE')",
              d.get("id"),
              start,
              today);
      entry.put("occupiedSlots", ((Number) entry.get("occupiedSlots")).longValue() + occupied);
      entry.put(
          "availableSlots",
          ((Number) entry.get("availableSlots")).longValue()
              + (Set.of("MAINTENANCE", "DISABLED", "OFFLINE", "RETIRED").contains(d.get("status"))
                  ? 0
                  : days));
    }
    for (var entry : utilization.values())
      entry.put(
          "utilizationRate",
          ReportService.ratio(
              ((Number) entry.get("occupiedSlots")).longValue(),
              ((Number) entry.get("availableSlots")).longValue()));
    result.put("utilization", utilization.values());
    return result;
  }

  public Object recommendations(Principal p, int limit) {
    p.require("reservation:create");
    if (limit < 1 || limit > 50) throw ApiError.validation("推荐数量须为 1 至 50");
    String where = scope.devicePredicate(p, "d", p.manager());
    var candidates =
        db.rows(
            "SELECT d.*,cat.name category_name,l.name lab_name FROM device d LEFT JOIN device_category cat ON cat.id=d.category_id LEFT JOIN lab l ON l.id=d.lab_id WHERE "
                + where
                + " AND d.status='IDLE' ORDER BY d.id");
    var history =
        db.rows(
            "SELECT DISTINCT d.* FROM device d JOIN reservation r ON r.device_id=d.id WHERE r.user_id=? AND "
                + scope.devicePredicate(p, "d", false)
                + " AND r.status IN ('PENDING','APPROVED','IN_USE','COMPLETED')",
            p.userId());
    var categories = new HashMap<Long, Integer>();
    var labs = new HashMap<Long, Integer>();
    var tags = new HashSet<String>();
    for (var d : history) {
      categories.merge(Database.id(d, "category_id"), 1, Integer::sum);
      labs.merge(Database.id(d, "lab_id"), 1, Integer::sum);
      if (db.parse(d.get("tags"), List.of()) instanceof List<?> values)
        values.forEach(v -> tags.add(v.toString().strip()));
    }
    var popularity = new HashMap<Long, Long>();
    for (var row :
        db.rows(
            "SELECT r.device_id,COUNT(*) count FROM reservation r JOIN device d ON d.id=r.device_id WHERE "
                + scope.devicePredicate(p, "d", false)
                + " AND r.created_at>=DATE_SUB(UTC_TIMESTAMP(),INTERVAL 30 DAY) AND r.status NOT IN ('CANCELLED','REJECTED','NO_SHOW','VIOLATED') GROUP BY r.device_id"))
      popularity.put(Database.id(row, "device_id"), Database.id(row, "count"));
    long maximum = popularity.values().stream().mapToLong(Long::longValue).max().orElse(0);
    var ranked = new ArrayList<Map<String, Object>>();
    for (var d : candidates) {
      long id = Database.id(d, "id");
      double
          category =
              .4
                  * categories.getOrDefault(Database.id(d, "category_id"), 0)
                  / Math.max(1.0, history.size()),
          lab = .2 * labs.getOrDefault(Database.id(d, "lab_id"), 0) / Math.max(1.0, history.size()),
          popular = .25 * popularity.getOrDefault(id, 0L) / Math.max(1.0, maximum),
          tag = 0;
      Object rawTags = db.parse(d.get("tags"), List.of());
      if (rawTags instanceof List<?> values && !tags.isEmpty())
        tag =
            .1
                * values.stream().map(Object::toString).filter(tags::contains).distinct().count()
                / tags.size();
      double active =
          db.count(
                      "SELECT COUNT(*) FROM reservation WHERE device_id=? AND user_id=? AND status IN ('PENDING','APPROVED','IN_USE')",
                      id,
                      p.userId())
                  > 0
              ? .3
              : 0;
      var row = new HashMap<String, Object>();
      for (String field :
          List.of(
              "name",
              "category_id",
              "category_name",
              "lab_id",
              "lab_name",
              "brand",
              "model",
              "status")) row.put(field, d.get(field));
      row.put("device_id", id);
      row.put("score", Math.round((category + lab + popular + tag - active) * 10000) / 10000.0);
      row.put(
          "reason",
          category > 0 && category >= Math.max(Math.max(lab, tag), popular) - .01
              ? "因你常约【" + Database.str(d, "category_name", "该类目") + "】设备"
              : lab > 0 && lab >= Math.max(tag, popular) - .01
                  ? "因你常用【" + Database.str(d, "lab_name", "该实验室") + "】"
                  : tag > 0 && tag >= popular - .01 ? "标签匹配你的偏好" : "近30天热门设备");
      ranked.add(row);
    }
    ranked.sort(
        Comparator.<Map<String, Object>>comparingDouble(
                r -> -((Number) r.get("score")).doubleValue())
            .thenComparingLong(r -> Database.id(r, "device_id")));
    return ranked.stream().limit(limit).toList();
  }
}
