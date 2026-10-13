package edu.labflow;

import jakarta.servlet.http.HttpServletRequest;
import java.util.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v2")
public class IdentityController {
  private final IdentityService service;

  public IdentityController(IdentityService service) {
    this.service = service;
  }

  @GetMapping("/users")
  public ApiResponse<?> users(
      HttpServletRequest req,
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "20") int size,
      @RequestParam(required = false) String keyword) {
    return ApiResponse.ok(service.users(Principal.from(req), new Pagination(page, size), keyword));
  }

  @PostMapping("/users")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  public ApiResponse<?> createUser(HttpServletRequest req, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.writeUser(Principal.from(req), null, data));
  }

  @PutMapping("/users/{id}")
  public ApiResponse<?> updateUser(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.writeUser(Principal.from(req), id, data));
  }

  @PatchMapping("/users/{id}/status")
  public ApiResponse<?> status(
      HttpServletRequest req, @PathVariable long id, @RequestParam int status) {
    service.status(Principal.from(req), id, status);
    return ApiResponse.ok(null);
  }

  @DeleteMapping("/users/{id}")
  public ApiResponse<?> delete(HttpServletRequest req, @PathVariable long id) {
    service.status(Principal.from(req), id, 0);
    return ApiResponse.ok(null);
  }

  @GetMapping("/rbac/permissions")
  public ApiResponse<?> permissions(HttpServletRequest req) {
    return ApiResponse.ok(service.permissions(Principal.from(req)));
  }

  @GetMapping("/rbac/roles")
  public ApiResponse<?> roles(HttpServletRequest req) {
    return ApiResponse.ok(service.roles(Principal.from(req)));
  }

  @PostMapping("/rbac/roles")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  public ApiResponse<?> createRole(HttpServletRequest req, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.createRole(Principal.from(req), data));
  }

  @PatchMapping("/rbac/roles/{id}")
  public ApiResponse<?> rename(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(
        service.renameRole(Principal.from(req), id, Database.str(data, "role_name", null)));
  }

  @PutMapping("/rbac/roles/{id}/permissions")
  public ApiResponse<?> permissions(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(
        service.rolePermissions(Principal.from(req), id, data.get("permission_codes")));
  }

  @DeleteMapping("/rbac/roles/{id}")
  public ApiResponse<?> deleteRole(HttpServletRequest req, @PathVariable long id) {
    service.deleteRole(Principal.from(req), id);
    return ApiResponse.ok(null);
  }
}
