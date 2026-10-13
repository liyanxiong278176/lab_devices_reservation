package edu.labflow;

import jakarta.servlet.http.*;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.util.*;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v2/auth")
public class AuthController {
  private final AuthService auth;
  private final Database db;
  private final Settings settings;
  private final RateLimiter limiter;

  public AuthController(AuthService auth, Database db, Settings settings, RateLimiter limiter) {
    this.auth = auth;
    this.db = db;
    this.settings = settings;
    this.limiter = limiter;
  }

  public record Login(
      @NotBlank @Size(max = 64) String username,
      @NotNull @Size(min = 6, max = 128) String password) {}

  public record Register(
      @NotBlank @Size(min = 3, max = 64) String username,
      @NotNull @Size(min = 8, max = 128) String password,
      @NotBlank @Size(max = 50) String real_name,
      @NotNull @Positive Long college_id) {}

  @GetMapping("/csrf")
  public ApiResponse<?> csrf(HttpServletRequest request, HttpServletResponse response) {
    String sid = "anon", access = auth.cookie(request, "ACCESS_COOKIE_NAME", "lab_access");
    if (access != null) {
      try {
        sid = auth.decode(access, true);
      } catch (ApiError e) {
      }
    }
    if (sid.equals("anon")) {
      String refresh =
          AuthService.refreshSid(auth.cookie(request, "REFRESH_COOKIE_NAME", "lab_refresh"));
      if (refresh != null) sid = refresh;
    }
    String token = auth.csrf(sid);
    auth.setCookie(
        response, settings.get("CSRF_COOKIE_NAME", "lab_csrf"), token, "/api/v2", 604800);
    return ApiResponse.ok(Map.of("csrf_token", token));
  }

  @GetMapping("/colleges")
  public ApiResponse<?> colleges() {
    return ApiResponse.ok(db.rows("SELECT id,code,name FROM college WHERE status=1 ORDER BY id"));
  }

  @PostMapping("/login")
  public ApiResponse<?> login(
      @Valid @RequestBody Login data, HttpServletResponse response, HttpServletRequest request) {
    limiter.login(data.username(), limiter.clientIp(request));
    return ApiResponse.ok(auth.login(data.username(), data.password(), response));
  }

  @PostMapping("/register")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  @Transactional
  public ApiResponse<?> register(
      @Valid @RequestBody Register data, HttpServletResponse response, HttpServletRequest request) {
    limiter.register(data.username(), limiter.clientIp(request));
    if (db.count("SELECT COUNT(*) FROM college WHERE id=? AND status=1", data.college_id()) == 0)
      throw ApiError.validation("学院不存在或已停用");
    long id =
        db.insert(
            "INSERT INTO sys_user (username,password,real_name,user_type,college_id,status,credit_score) VALUES (?,?,?,'STUDENT',?,1,100)",
            data.username(),
            auth.hash(data.password()),
            data.real_name(),
            data.college_id());
    db.execute(
        "INSERT INTO sys_user_role (user_id,role_id) SELECT ?,id FROM sys_role WHERE role_code='STUDENT'",
        id);
    return ApiResponse.ok(auth.issue(id, response));
  }

  @PostMapping("/refresh")
  public ApiResponse<?> refresh(HttpServletRequest request, HttpServletResponse response) {
    return ApiResponse.ok(auth.refresh(request, response));
  }

  @PostMapping("/logout")
  public ApiResponse<?> logout(HttpServletRequest request, HttpServletResponse response) {
    Principal p = Principal.from(request);
    auth.revoke(p.sid());
    auth.setCookie(response, settings.get("ACCESS_COOKIE_NAME", "lab_access"), "", "/api/v2", 0);
    auth.setCookie(
        response, settings.get("REFRESH_COOKIE_NAME", "lab_refresh"), "", "/api/v2/auth", 0);
    auth.setCookie(response, settings.get("CSRF_COOKIE_NAME", "lab_csrf"), "", "/api/v2", 0);
    return ApiResponse.ok(null);
  }

  @GetMapping("/me")
  public ApiResponse<?> me(HttpServletRequest request) {
    Principal p = Principal.from(request);
    var user =
        db.one(
            "SELECT id,username,real_name,college_id,status FROM sys_user WHERE id=?", p.userId());
    user.put("roles", p.roles().stream().sorted().toList());
    user.put("permissions", p.permissions().stream().sorted().toList());
    return ApiResponse.ok(user);
  }
}
