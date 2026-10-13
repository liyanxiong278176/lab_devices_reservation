package edu.labflow;

import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class OrganizationService {
  private final Database db;
  private final ScopeAccess scope;

  public OrganizationService(Database db, ScopeAccess scope) {
    this.db = db;
    this.scope = scope;
  }

  private void admin(Principal p) {
    if (!p.systemAdmin()) throw ApiError.forbidden();
    p.require("organization:manage");
  }

  public List<Map<String, Object>> colleges(Principal p) {
    return p.systemAdmin()
        ? db.rows(
            "SELECT c.id,c.code,c.name,c.manager_id,COALESCE(u.real_name,u.username) manager_name FROM college c LEFT JOIN sys_user u ON u.id=c.manager_id ORDER BY c.id")
        : db.rows(
            "SELECT c.id,c.code,c.name,c.manager_id,COALESCE(u.real_name,u.username) manager_name FROM college c LEFT JOIN sys_user u ON u.id=c.manager_id WHERE c.id=?",
            p.tenant());
  }

  public List<Map<String, Object>> managers(Principal p, long college) {
    admin(p);
    return db.rows(
        "SELECT DISTINCT u.id,u.username,u.real_name,u.college_id FROM sys_user u JOIN sys_user_role ur ON ur.user_id=u.id JOIN sys_role r ON r.id=ur.role_id WHERE u.college_id=? AND u.status=1 AND r.role_code IN ('SYS_ADMIN','LAB_ADMIN') ORDER BY u.id",
        college);
  }

  private void manager(Long id, long college) {
    if (id != null
        && db.count(
                "SELECT COUNT(*) FROM sys_user u JOIN sys_user_role ur ON ur.user_id=u.id JOIN sys_role r ON r.id=ur.role_id WHERE u.id=? AND u.college_id=? AND u.status=1 AND r.role_code IN ('SYS_ADMIN','LAB_ADMIN')",
                id,
                college)
            == 0) throw new ApiError("MANAGER_INVALID", "负责人必须是当前学院启用的管理员", 422);
  }

  @Transactional
  public Map<String, Object> college(Principal p, Long id, Map<String, Object> data) {
    admin(p);
    String code = Database.str(data, "code", "").strip(),
        name = Database.str(data, "name", "").strip();
    if (code.length() < 2 || code.length() > 64 || name.length() < 2 || name.length() > 128)
      throw ApiError.validation("学院名称或编码无效");
    Long manager = data.get("manager_id") == null ? null : Database.id(data, "manager_id");
    if (id == null) {
      if (manager != null) throw new ApiError("MANAGER_INVALID", "请先创建学院，再配置负责人", 422);
      id = db.insert("INSERT INTO college (code,name,status) VALUES (?,?,1)", code, name);
    } else {
      manager(manager, id);
      if (db.execute(
              "UPDATE college SET code=?,name=?,manager_id=?,updated_at=UTC_TIMESTAMP() WHERE id=?",
              code,
              name,
              manager,
              id)
          != 1) throw new ApiError("COLLEGE_NOT_FOUND", "学院不存在", 404);
    }
    long resultId = id;
    return colleges(p).stream()
        .filter(r -> Database.id(r, "id") == resultId)
        .findFirst()
        .orElseThrow();
  }

  public Map<String, Object> labs(Principal p, Pagination page) {
    if (!p.systemAdmin() && (!p.manager() || !p.has("organization:read")))
      throw ApiError.forbidden();
    String where =
        p.systemAdmin()
            ? "l.status=1"
            : "l.status=1 AND l.college_id="
                + p.tenant()
                + " AND (l.manager_id="
                + p.userId()
                + " OR c.manager_id="
                + p.userId()
                + ")";
    long total =
        db.count("SELECT COUNT(*) FROM lab l JOIN college c ON c.id=l.college_id WHERE " + where);
    String ids =
        "SELECT l.id FROM lab l JOIN college c ON c.id=l.college_id WHERE "
            + where
            + " ORDER BY l.id DESC LIMIT ? OFFSET ?";
    return page.legacy(
        db.rows(
            "SELECT l.*,c.name college_name,COALESCE(u.real_name,u.username) manager_name FROM lab l JOIN college c ON c.id=l.college_id LEFT JOIN sys_user u ON u.id=l.manager_id JOIN ("
                + ids
                + ") page_ids ON page_ids.id=l.id ORDER BY l.id DESC",
            page.size(),
            page.offset()),
        total);
  }

  @Transactional
  public Map<String, Object> lab(Principal p, Long id, Map<String, Object> data) {
    admin(p);
    long college = Database.id(data, "college_id");
    if (db.count("SELECT COUNT(*) FROM college WHERE id=? AND status=1", college) != 1)
      throw new ApiError("COLLEGE_NOT_FOUND", "学院不存在或已停用", 422);
    String name = Database.str(data, "name", "").strip();
    if (name.length() < 2 || name.length() > 100) throw ApiError.validation("实验室名称无效");
    Long manager = data.get("manager_id") == null ? null : Database.id(data, "manager_id");
    manager(manager, college);
    if (id == null)
      id =
          db.insert(
              "INSERT INTO lab (college_id,name,location,manager_id,description,status) VALUES (?,?,?,?,?,1)",
              college,
              name,
              data.get("location"),
              manager,
              data.get("description"));
    else {
      var previous = db.one("SELECT college_id FROM lab WHERE id=?", id);
      if (previous == null) throw new ApiError("LAB_NOT_FOUND", "实验室不存在", 404);
      if (Database.id(previous, "college_id") != college
          && db.count("SELECT COUNT(*) FROM device WHERE lab_id=?", id) > 0)
        throw new ApiError("LAB_COLLEGE_CONFLICT", "实验室存在设备，不能直接变更学院", 409);
      db.execute(
          "UPDATE lab SET college_id=?,name=?,location=?,manager_id=?,description=?,updated_at=UTC_TIMESTAMP() WHERE id=?",
          college,
          name,
          data.get("location"),
          manager,
          data.get("description"),
          id);
    }
    return db.one(
        "SELECT l.*,c.name college_name,COALESCE(u.real_name,u.username) manager_name FROM lab l JOIN college c ON c.id=l.college_id LEFT JOIN sys_user u ON u.id=l.manager_id WHERE l.id=?",
        id);
  }

  public List<Map<String, Object>> categories(Principal p) {
    p.require("device:read");
    var rows = db.rows("SELECT id,name,parent_id,sort FROM device_category ORDER BY sort,id");
    var result = new ArrayList<Map<String, Object>>();
    for (var row : rows) {
      var children =
          rows.stream().filter(r -> Database.id(r, "parent_id") == Database.id(row, "id")).toList();
      row.put("children", children);
      if (Database.id(row, "parent_id") == 0) result.add(row);
    }
    return result;
  }
}
