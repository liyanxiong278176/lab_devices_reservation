package edu.labflow;

import jakarta.servlet.http.HttpServletRequest;
import java.time.LocalDateTime;
import java.util.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v2/penalties")
public class PenaltyController {
  private final PenaltyService service;

  public PenaltyController(PenaltyService service) {
    this.service = service;
  }

  @GetMapping("/policy")
  public ApiResponse<?> policy(HttpServletRequest req) {
    return ApiResponse.ok(service.policy(Principal.from(req)));
  }

  @PutMapping("/policy")
  public ApiResponse<?> policy(HttpServletRequest req, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.policy(Principal.from(req), data));
  }

  @GetMapping("/system/grace-bounds")
  public ApiResponse<?> bounds(HttpServletRequest req) {
    return ApiResponse.ok(service.bounds(Principal.from(req)));
  }

  @PutMapping("/system/grace-bounds")
  public ApiResponse<?> bounds(HttpServletRequest req, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(
        service.bounds(
            Principal.from(req),
            (int) Database.id(data, "minimum_days"),
            (int) Database.id(data, "maximum_days")));
  }

  @GetMapping("/mine")
  public ApiResponse<?> mine(HttpServletRequest req) {
    return ApiResponse.ok(service.mine(Principal.from(req)));
  }

  @GetMapping("/balance")
  public ApiResponse<?> balance(HttpServletRequest req) {
    return ApiResponse.ok(service.balance(Principal.from(req)));
  }

  @GetMapping("/cases")
  public ApiResponse<?> cases(
      HttpServletRequest req,
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "20") int page_size) {
    return ApiResponse.ok(service.cases(Principal.from(req), new Pagination(page, page_size)));
  }

  @GetMapping("/appeals")
  public ApiResponse<?> appeals(
      HttpServletRequest req,
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "20") int page_size,
      @RequestParam(defaultValue = "true") boolean pending_only) {
    return ApiResponse.ok(
        service.appeals(Principal.from(req), new Pagination(page, page_size), pending_only));
  }

  @PostMapping("/cases/{id}/appeals")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  public ApiResponse<?> appeal(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(
        service.appeal(
            Principal.from(req),
            id,
            Database.str(data, "reason", null),
            Database.str(data, "evidence", null)));
  }

  @PostMapping("/appeals/{id}/review")
  public ApiResponse<?> review(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.review(Principal.from(req), id, data));
  }

  @GetMapping("/overdue")
  public ApiResponse<?> overdue(
      HttpServletRequest req,
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "20") int page_size) {
    return ApiResponse.ok(service.overdue(Principal.from(req), new Pagination(page, page_size)));
  }

  @PostMapping("/overdue/{id}/followups")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  public ApiResponse<?> followup(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(
        service.followup(
            Principal.from(req),
            id,
            Database.str(data, "result", null),
            data.get("contacted_at") == null
                ? null
                : LocalDateTime.parse(data.get("contacted_at").toString())));
  }

  @PostMapping("/overdue/{id}/escalate")
  public ApiResponse<?> escalate(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(
        service.escalate(Principal.from(req), id, Database.str(data, "reason", null)));
  }
}
