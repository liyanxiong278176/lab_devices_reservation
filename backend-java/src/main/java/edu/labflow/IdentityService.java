package edu.labflow;

import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class IdentityService {
  private final Database db;
  private final AuthService auth;
  private final BusinessEvents events;

  public IdentityService(Database db, AuthService auth, BusinessEvents events) {
    this.db = db;
    this.auth = auth;
    this.events = events;
  }

  private void admin(Principal p, String permission) {
    if (!p.systemAdmin()) throw ApiError.forbidden();
    p.require(permission);
  }

  private void versionLock() {
    db.one("SELECT version FROM v2_authz_version WHERE id=1 FOR UPDATE");
  }

  private void bump() {
    db.execute(
        "UPDATE v2_authz_version SET version=version+1,updated_at=UTC_TIMESTAMP() WHERE id=1");
  }

  private void revokeAfterCommit(long user) {
    org.springframework.transaction.support.TransactionSynchronizationManager
        .registerSynchronization(
            new org.springframework.transaction.support.TransactionSynchronization() {
              @Override
              public void afterCommit() {
                auth.revokeUser(user);
              }
            });
  }

  private Map<String, Object> user(long id) {
    var row =
        db.one(
            "SELECT id,username,real_name,phone,email,user_type,college_id,status,created_at FROM sys_user WHERE id=?",
            id);
    if (row == null) throw new ApiError("USER_NOT_FOUND", "用户不存在", 404);
    row.put("roles", rolesFor(id));
    return row;
  }

  private List<String> rolesFor(long id) {
    return db
        .rows(
            "SELECT r.role_code FROM sys_role r JOIN sys_user_role ur ON ur.role_id=r.id WHERE ur.user_id=? ORDER BY r.id",
            id)
        .stream()
        .map(r -> r.get("role_code").toString())
        .toList();
  }

  public Map<String, Object> users(Principal p, Pagination page, String keyword) {
    admin(p, "user:manage");
    String where = "1=1";
    var values = new ArrayList<Object>();
    if (keyword != null && !keyword.isBlank()) {
      where = "(username LIKE ? OR real_name LIKE ?)";
      values.add("%" + keyword + "%");
      values.add("%" + keyword + "%");
    }
    long total = db.count("SELECT COUNT(*) FROM sys_user WHERE " + where, values.toArray());
    values.add(page.size());
    values.add(page.offset());
    var ids =
        db.rows(
            "SELECT id FROM sys_user WHERE " + where + " ORDER BY id DESC LIMIT ? OFFSET ?",
            values.toArray());
    return page.legacy(ids.stream().map(r -> user(Database.id(r, "id"))).toList(), total);
  }

  private List<String> codes(Object value, String field, int max) {
    if (!(value instanceof List<?> values) || values.size() > max)
      throw ApiError.validation(field + " 列表无效");
    var result = values.stream().map(Object::toString).toList();
    if (new HashSet<>(result).size() != result.size()) throw ApiError.validation(field + " 不能重复");
    return result;
  }

  private void protectLastAdmin(long id, int status, List<String> next) {
    if (!rolesFor(id).contains("SYS_ADMIN") || status == 1 && next.contains("SYS_ADMIN")) return;
    if (db.count(
            "SELECT COUNT(DISTINCT u.id) FROM sys_user u JOIN sys_user_role ur ON ur.user_id=u.id JOIN sys_role r ON r.id=ur.role_id WHERE u.status=1 AND r.role_code='SYS_ADMIN' AND u.id<>?",
            id)
        == 0) throw new ApiError("LAST_ADMIN_PROTECTED", "不能停用或移除最后一个系统管理员", 409);
  }

  @Transactional
  public Map<String, Object> writeUser(Principal p, Long id, Map<String, Object> data) {
    admin(p, "user:manage");
    versionLock();
    var roleCodes = codes(data.getOrDefault("role_codes", List.of("STUDENT")), "角色", 5);
    if (roleCodes.isEmpty()) roleCodes = List.of("STUDENT");
    for (String code : roleCodes)
      if (db.count("SELECT COUNT(*) FROM sys_role WHERE role_code=?", code) != 1)
        throw new ApiError("ROLE_NOT_FOUND", "角色不存在", 422);
    String username = Database.str(data, "username", "").strip();
    if (username.length() < 3 || username.length() > 64)
      throw ApiError.validation("用户名须为 3 至 64 个字符");
    Long college = data.get("college_id") == null ? null : Database.id(data, "college_id");
    if (college == null && !roleCodes.contains("SYS_ADMIN"))
      throw new ApiError("COLLEGE_REQUIRED", "业务用户必须指定学院", 422);
    if (college != null
        && db.count("SELECT COUNT(*) FROM college WHERE id=? AND status=1", college) != 1)
      throw new ApiError("COLLEGE_NOT_FOUND", "学院不存在或未启用", 422);
    String password = Database.str(data, "password", null);
    if (password != null && (password.length() < 6 || password.length() > 128))
      throw ApiError.validation("密码长度无效");
    if (id == null) {
      if (password == null) throw ApiError.validation("新建用户必须填写密码");
      id =
          db.insert(
              "INSERT INTO sys_user (username,password,real_name,phone,email,user_type,college_id,status,credit_score) VALUES (?,?,?,?,?,?,?,1,100)",
              username,
              auth.hash(password),
              data.get("real_name"),
              data.get("phone"),
              data.get("email"),
              data.getOrDefault("user_type", "STUDENT"),
              college);
    } else {
      var previous = user(id);
      protectLastAdmin(id, (int) Database.id(previous, "status"), roleCodes);
      db.execute(
          "UPDATE sys_user SET username=?,real_name=?,phone=?,email=?,user_type=?,college_id=?,updated_at=UTC_TIMESTAMP() WHERE id=?",
          username,
          data.get("real_name"),
          data.get("phone"),
          data.get("email"),
          data.getOrDefault("user_type", "STUDENT"),
          college,
          id);
      if (password != null)
        db.execute("UPDATE sys_user SET password=? WHERE id=?", auth.hash(password), id);
    }
    db.execute("DELETE FROM sys_user_role WHERE user_id=?", id);
    for (String code : roleCodes)
      db.execute(
          "INSERT INTO sys_user_role (user_id,role_id) SELECT ?,id FROM sys_role WHERE role_code=?",
          id,
          code);
    bump();
    revokeAfterCommit(id);
    events.audit(p, "USER_WRITE", "USER", id, Map.of("username", username));
    return user(id);
  }

  @Transactional
  public void status(Principal p, long id, int status) {
    admin(p, "user:manage");
    if (status != 0 && status != 1) throw ApiError.validation("账号状态无效");
    versionLock();
    user(id);
    protectLastAdmin(id, status, rolesFor(id));
    db.execute("UPDATE sys_user SET status=?,updated_at=UTC_TIMESTAMP() WHERE id=?", status, id);
    bump();
    revokeAfterCommit(id);
    events.audit(p, "USER_STATUS", "USER", id, Map.of("status", status));
  }

  public List<Map<String, Object>> permissions(Principal p) {
    admin(p, "rbac:manage");
    return db.rows(
        "SELECT permission_code code,permission_name name,module,description FROM sys_permission ORDER BY module,id");
  }

  private Map<String, Object> role(long id) {
    var row =
        db.one("SELECT id,role_code code,role_name name,is_system FROM sys_role WHERE id=?", id);
    if (row == null) throw new ApiError("ROLE_NOT_FOUND", "角色不存在", 404);
    row.put(
        "permissions",
        db
            .rows(
                "SELECT p.permission_code FROM sys_permission p JOIN sys_role_permission rp ON rp.permission_id=p.id WHERE rp.role_id=? ORDER BY p.permission_code",
                id)
            .stream()
            .map(r -> r.get("permission_code"))
            .toList());
    return row;
  }

  public List<Map<String, Object>> roles(Principal p) {
    admin(p, "rbac:manage");
    return db.rows("SELECT id FROM sys_role ORDER BY id").stream()
        .map(r -> role(Database.id(r, "id")))
        .toList();
  }

  private void permissions(long id, List<String> codes) {
    for (String code : codes) {
      if (Set.of("rbac:manage", "user:manage", "organization:manage").contains(code))
        throw new ApiError("SYSTEM_PERMISSION_RESERVED", "系统专属权限不能分配给其他角色", 409);
      if (db.count("SELECT COUNT(*) FROM sys_permission WHERE permission_code=?", code) != 1)
        throw new ApiError("PERMISSION_NOT_FOUND", "权限不存在", 422);
    }
    db.execute("DELETE FROM sys_role_permission WHERE role_id=?", id);
    for (String code : codes)
      db.execute(
          "INSERT INTO sys_role_permission (role_id,permission_id) SELECT ?,id FROM sys_permission WHERE permission_code=?",
          id,
          code);
  }

  @Transactional
  public Map<String, Object> createRole(Principal p, Map<String, Object> data) {
    admin(p, "rbac:manage");
    versionLock();
    String code = Database.str(data, "role_code", "").strip().toUpperCase(Locale.ROOT),
        name = Database.str(data, "role_name", "").strip();
    if (!code.matches("[A-Z][A-Z0-9_]{1,49}") || name.isEmpty() || name.length() > 50)
      throw ApiError.validation("角色代码或名称无效");
    long id =
        db.insert(
            "INSERT INTO sys_role (role_code,role_name,is_system) VALUES (?,?,0)", code, name);
    permissions(id, codes(data.getOrDefault("permission_codes", List.of()), "权限", 100));
    bump();
    events.audit(p, "RBAC_ROLE_CREATE", "ROLE", id, Map.of("role_code", code));
    return role(id);
  }

  @Transactional
  public Map<String, Object> renameRole(Principal p, long id, String name) {
    admin(p, "rbac:manage");
    var row = role(id);
    if (ReservationPolicy.truth(row.get("is_system")))
      throw new ApiError("SYSTEM_ROLE_PROTECTED", "系统角色名称不可修改", 409);
    if (name == null || name.strip().isEmpty() || name.length() > 50)
      throw ApiError.validation("角色名称无效");
    db.execute("UPDATE sys_role SET role_name=? WHERE id=?", name.strip(), id);
    return role(id);
  }

  @Transactional
  public Map<String, Object> rolePermissions(Principal p, long id, Object values) {
    admin(p, "rbac:manage");
    versionLock();
    var row = role(id);
    if ("SYS_ADMIN".equals(row.get("code")))
      throw new ApiError("SYSTEM_ROLE_PROTECTED", "系统管理员角色权限不可修改", 409);
    permissions(id, codes(values, "权限", 100));
    bump();
    events.audit(p, "RBAC_ROLE_PERMISSIONS_UPDATE", "ROLE", id, Map.of());
    return role(id);
  }

  @Transactional
  public void deleteRole(Principal p, long id) {
    admin(p, "rbac:manage");
    versionLock();
    var row = role(id);
    if (ReservationPolicy.truth(row.get("is_system")))
      throw new ApiError("SYSTEM_ROLE_PROTECTED", "系统角色不可删除", 409);
    if (db.count("SELECT COUNT(*) FROM sys_user_role WHERE role_id=?", id) > 0)
      throw new ApiError("ROLE_IN_USE", "角色仍被用户使用", 409);
    db.execute("DELETE FROM sys_role_permission WHERE role_id=?", id);
    db.execute("DELETE FROM sys_role WHERE id=?", id);
    bump();
  }
}
