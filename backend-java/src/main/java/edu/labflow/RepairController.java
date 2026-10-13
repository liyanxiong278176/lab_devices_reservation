package edu.labflow;

import jakarta.servlet.http.HttpServletRequest;
import java.util.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v2/repair-reports")
public class RepairController {
  private final RepairService service;

  public RepairController(RepairService service) {
    this.service = service;
  }

  @PostMapping
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  public ApiResponse<?> create(HttpServletRequest req, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.create(Principal.from(req), data));
  }

  @GetMapping("/mine")
  public ApiResponse<?> mine(
      HttpServletRequest req,
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "20") int page_size,
      @RequestParam(required = false) String status) {
    return ApiResponse.ok(
        service.list(
            Principal.from(req), new Pagination(page, page_size), true, status, null, null));
  }

  @GetMapping
  public ApiResponse<?> list(
      HttpServletRequest req,
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "20") int page_size,
      @RequestParam(required = false) String status,
      @RequestParam(required = false) String priority,
      @RequestParam(required = false) Boolean overdue) {
    return ApiResponse.ok(
        service.list(
            Principal.from(req),
            new Pagination(page, page_size),
            false,
            status,
            priority,
            overdue));
  }

  @PostMapping("/{id}/take")
  public ApiResponse<?> take(HttpServletRequest req, @PathVariable long id) {
    return ApiResponse.ok(service.take(Principal.from(req), id));
  }

  @PostMapping("/{id}/resolve")
  public ApiResponse<?> resolve(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(
        service.resolve(
            Principal.from(req), id, Database.str(data, "resolution_note", null), false));
  }

  @PostMapping("/{id}/reject")
  public ApiResponse<?> reject(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(
        service.resolve(
            Principal.from(req), id, Database.str(data, "resolution_note", null), true));
  }

  @PostMapping("/{id}/confirm")
  public ApiResponse<?> confirm(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    if (!(data.get("confirmed") instanceof Boolean)) throw ApiError.validation("请提供确认结果");
    return ApiResponse.ok(
        service.confirm(
            Principal.from(req),
            id,
            (Boolean) data.get("confirmed"),
            Database.str(data, "note", null)));
  }

  @GetMapping("/{id}/worklogs")
  public ApiResponse<?> logs(HttpServletRequest req, @PathVariable long id) {
    return ApiResponse.ok(service.worklogs(Principal.from(req), id));
  }
}
