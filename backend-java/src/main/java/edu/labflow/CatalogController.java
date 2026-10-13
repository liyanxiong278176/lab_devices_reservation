package edu.labflow;

import jakarta.servlet.http.HttpServletRequest;
import java.util.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v2")
public class CatalogController {
  private final CatalogService service;

  public CatalogController(CatalogService service) {
    this.service = service;
  }

  @GetMapping("/devices")
  public ApiResponse<?> devices(
      HttpServletRequest req,
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "20") int page_size,
      @RequestParam(required = false) String search,
      @RequestParam(required = false) Long lab_id,
      @RequestParam(required = false) String status,
      @RequestParam(defaultValue = "false") boolean grouped) {
    return ApiResponse.ok(
        service.devices(
            Principal.from(req), new Pagination(page, page_size), search, lab_id, status, grouped));
  }

  @GetMapping("/devices/{id}")
  public ApiResponse<?> device(HttpServletRequest req, @PathVariable long id) {
    return ApiResponse.ok(service.device(Principal.from(req), id));
  }

  @GetMapping("/device-pools/options")
  public ApiResponse<?> pools(HttpServletRequest req) {
    return ApiResponse.ok(service.pools(Principal.from(req)));
  }

  @GetMapping("/device-pools/{id}")
  public ApiResponse<?> pool(HttpServletRequest req, @PathVariable long id) {
    return ApiResponse.ok(service.pool(Principal.from(req), id));
  }

  @PostMapping("/devices")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  public ApiResponse<?> create(HttpServletRequest req, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.write(Principal.from(req), null, data));
  }

  @PutMapping("/devices/{id}")
  public ApiResponse<?> update(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.write(Principal.from(req), id, data));
  }

  @PatchMapping("/devices/{id}/status")
  public ApiResponse<?> status(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    service.status(
        Principal.from(req),
        id,
        Database.str(data, "status", ""),
        Database.str(data, "reason", null));
    return ApiResponse.ok(service.device(Principal.from(req), id));
  }

  @DeleteMapping("/devices/{id}")
  public ApiResponse<?> delete(HttpServletRequest req, @PathVariable long id) {
    service.delete(Principal.from(req), id);
    return ApiResponse.ok(null);
  }
}
