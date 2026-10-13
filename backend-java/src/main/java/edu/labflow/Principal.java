package edu.labflow;

import jakarta.servlet.http.HttpServletRequest;
import java.util.Set;

public record Principal(
    long userId,
    String username,
    Long collegeId,
    Set<String> roles,
    Set<String> permissions,
    String sid) {
  public boolean systemAdmin() {
    return roles.contains("SYS_ADMIN");
  }

  public boolean manager() {
    return systemAdmin() || roles.contains("LAB_ADMIN");
  }

  public boolean has(String permission) {
    return systemAdmin() || permissions.contains(permission);
  }

  public void require(String permission) {
    if (!has(permission)) throw ApiError.forbidden();
  }

  public long tenant() {
    if (collegeId == null) throw new ApiError("COLLEGE_SCOPE_MISSING", "用户尚未绑定学院", 403);
    return collegeId;
  }

  public static Principal from(HttpServletRequest request) {
    var value = request.getAttribute("principal");
    if (value == null) throw new ApiError("AUTH_REQUIRED", "请先登录", 401);
    return (Principal) value;
  }
}
