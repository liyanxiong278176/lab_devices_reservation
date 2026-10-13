package edu.labflow;

import java.util.Map;
import org.springframework.stereotype.Component;

@Component
public class ScopeAccess {
  private final Database db;

  public ScopeAccess(Database db) {
    this.db = db;
  }

  public Map<String, Object> device(Principal p, long id, boolean manage) {
    var d =
        db.one(
            "SELECT d.*,l.name lab_name,l.manager_id lab_manager,c.name college_name,c.manager_id college_manager,cat.name category_name FROM device d LEFT JOIN lab l ON l.id=d.lab_id LEFT JOIN college c ON c.id=d.college_id LEFT JOIN device_category cat ON cat.id=d.category_id WHERE d.id=?",
            id);
    if (d == null) throw new ApiError("DEVICE_NOT_FOUND", "设备不存在", 404);
    if (!p.systemAdmin() && Database.id(d, "college_id") != p.tenant()) throw ApiError.forbidden();
    if (manage
        && !p.systemAdmin()
        && (!p.manager()
            || (Database.id(d, "lab_manager") != p.userId()
                && Database.id(d, "college_manager") != p.userId()))) throw ApiError.forbidden();
    return d;
  }

  public boolean manages(Principal p, String scope, long id) {
    if (scope.equals("GLOBAL")) return p.systemAdmin() && id == 0;
    if (scope.equals("DEVICE")) {
      try {
        device(p, id, true);
        return true;
      } catch (ApiError e) {
        return false;
      }
    }
    String table =
        switch (scope) {
          case "COLLEGE" -> "college";
          case "LAB" -> "lab";
          default -> null;
        };
    if (table == null) return false;
    var row = db.one("SELECT * FROM " + table + " WHERE id=?", id);
    if (row == null) return false;
    if (p.systemAdmin()) return true;
    if (!p.manager()) return false;
    if (scope.equals("COLLEGE"))
      return id == p.tenant() && Database.id(row, "manager_id") == p.userId();
    if (Database.id(row, "college_id") != p.tenant()) return false;
    return Database.id(row, "manager_id") == p.userId()
        || db.count(
                "SELECT COUNT(*) FROM college WHERE id=? AND manager_id=?", p.tenant(), p.userId())
            > 0;
  }

  public String devicePredicate(Principal p, String alias, boolean manage) {
    if (p.systemAdmin()) return "1=1";
    String tenant = alias + ".college_id=" + p.tenant();
    if (!manage) return tenant;
    if (!p.manager()) return "1=0";
    return tenant
        + " AND (EXISTS (SELECT 1 FROM lab sl WHERE sl.id="
        + alias
        + ".lab_id AND sl.manager_id="
        + p.userId()
        + ") OR EXISTS (SELECT 1 FROM college sc WHERE sc.id="
        + alias
        + ".college_id AND sc.manager_id="
        + p.userId()
        + "))";
  }
}
