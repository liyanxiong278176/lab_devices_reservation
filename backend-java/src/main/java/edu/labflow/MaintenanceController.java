package edu.labflow;

import jakarta.servlet.http.HttpServletRequest;
import java.util.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/api/v2")
public class MaintenanceController {
  private final MaintenanceService service;
  private final StorageService storage;
  private final ScopeAccess scope;
  private final CatalogService catalog;

  public MaintenanceController(
      MaintenanceService service,
      StorageService storage,
      ScopeAccess scope,
      CatalogService catalog) {
    this.service = service;
    this.storage = storage;
    this.scope = scope;
    this.catalog = catalog;
  }

  @GetMapping("/maintenance-devices")
  public ApiResponse<?> devices(
      HttpServletRequest req,
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "20") int page_size,
      @RequestParam(required = false) String search) {
    var p = Principal.from(req);
    p.require("maintenance:manage");
    return ApiResponse.ok(
        catalog.devices(p, new Pagination(page, page_size), search, null, null, false, true));
  }

  @GetMapping("/maintenance-plans")
  public ApiResponse<?> plans(
      HttpServletRequest req,
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "20") int page_size,
      @RequestParam(required = false) Long device_id,
      @RequestParam(required = false) Boolean active) {
    return ApiResponse.ok(
        service.plans(Principal.from(req), new Pagination(page, page_size), device_id, active));
  }

  @PostMapping("/devices/{id}/maintenance-plans")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  public ApiResponse<?> create(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.write(Principal.from(req), null, id, data));
  }

  @PutMapping("/maintenance-plans/{id}")
  public ApiResponse<?> update(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.write(Principal.from(req), id, 0, data));
  }

  @GetMapping("/maintenance-plans/{id}/records")
  public ApiResponse<?> records(
      HttpServletRequest req,
      @PathVariable long id,
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "20") int page_size) {
    return ApiResponse.ok(
        service.records(Principal.from(req), id, new Pagination(page, page_size)));
  }

  @PostMapping("/maintenance-plans/{id}/records")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  public ApiResponse<?> complete(
      HttpServletRequest req,
      @PathVariable long id,
      @RequestBody Map<String, Object> data,
      @RequestHeader("Idempotency-Key") String key) {
    return ApiResponse.ok(service.complete(Principal.from(req), id, data, key));
  }

  @PostMapping("/devices/{id}/maintenance-evidence")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  public ApiResponse<?> evidence(
      HttpServletRequest req, @PathVariable long id, @RequestParam MultipartFile file) {
    var p = Principal.from(req);
    p.require("maintenance:manage");
    scope.device(p, id, true);
    return ApiResponse.ok(storage.upload(p, file, false, "/api/v2/maintenance-evidence/"));
  }
}
