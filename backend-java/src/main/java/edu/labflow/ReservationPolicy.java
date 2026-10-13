package edu.labflow;

import java.util.*;
import org.springframework.stereotype.Component;

@Component
public class ReservationPolicy {
  private final Database db;
  private final Settings settings;

  public ReservationPolicy(Database db, Settings settings) {
    this.db = db;
    this.settings = settings;
  }

  public record Effective(
      String user_category,
      int max_booking_days,
      int max_advance_days,
      boolean approval_required) {}

  public Effective resolve(Principal p, Map<String, Object> device) {
    String category = p.manager() ? "LAB_ADMIN" : "STUDENT";
    var scopes = new ArrayList<Map.Entry<String, Long>>();
    scopes.add(Map.entry("DEVICE", Database.id(device, "id")));
    if (device.get("lab_id") != null) scopes.add(Map.entry("LAB", Database.id(device, "lab_id")));
    if (device.get("college_id") != null)
      scopes.add(Map.entry("COLLEGE", Database.id(device, "college_id")));
    scopes.add(Map.entry("GLOBAL", 0L));
    var rules = new ArrayList<Map<String, Object>>();
    for (var entry : scopes)
      rules.addAll(
          db.rows(
              "SELECT * FROM v2_reservation_rule WHERE scope_type=? AND scope_id=? AND user_category IN (?, 'ALL')",
              entry.getKey(),
              entry.getValue(),
              category));
    Object days = resolve(rules, scopes, category, "max_booking_days", true),
        advance = resolve(rules, scopes, category, "max_advance_days", false),
        approval = resolve(rules, scopes, category, "approval_required", true);
    int defaultAdvance =
        p.manager()
            ? settings.integer("RESERVATION_MANAGER_ADVANCE_DAYS", 90)
            : settings.integer("RESERVATION_ADVANCE_DAYS", 30);
    int maxAdvance;
    if (advance != null) maxAdvance = ((Number) advance).intValue();
    else {
      Object generic = resolve(rules, scopes, "ALL", "max_advance_days", false);
      if (generic == null) generic = device.get("max_advance_days");
      maxAdvance =
          Math.min(
              defaultAdvance, generic == null ? defaultAdvance : ((Number) generic).intValue());
    }
    return new Effective(
        category,
        Math.min(
            31,
            days == null
                ? (int) Database.id(device, "max_reservation_days")
                : ((Number) days).intValue()),
        maxAdvance,
        approval == null ? Database.id(device, "need_approval") == 1 : truth(approval));
  }

  private Object resolve(
      List<Map<String, Object>> rules,
      List<Map.Entry<String, Long>> scopes,
      String category,
      String field,
      boolean fallback) {
    for (String cat : fallback ? List.of(category, "ALL") : List.of(category))
      for (var scope : scopes)
        for (var row : rules)
          if (scope.getKey().equals(row.get("scope_type"))
              && scope.getValue() == Database.id(row, "scope_id")
              && cat.equals(row.get("user_category"))
              && row.get(field) != null) return row.get(field);
    return null;
  }

  public static boolean truth(Object value) {
    return value instanceof Boolean b
        ? b
        : value instanceof Number n
            ? n.intValue() != 0
            : Boolean.parseBoolean(String.valueOf(value));
  }
}
