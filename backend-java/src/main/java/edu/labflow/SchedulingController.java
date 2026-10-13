package edu.labflow;

import jakarta.servlet.http.HttpServletRequest;
import java.time.LocalDate;
import java.util.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v2")
public class SchedulingController {
  private final SchedulingService service;

  public SchedulingController(SchedulingService service) {
    this.service = service;
  }

  @GetMapping("/reservation-rules")
  public ApiResponse<?> rules(
      HttpServletRequest req,
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "20") int page_size,
      @RequestParam(required = false) String scope_type,
      @RequestParam(required = false) Long scope_id,
      @RequestParam(required = false) String user_category) {
    return ApiResponse.ok(
        service.rules(
            Principal.from(req),
            new Pagination(page, page_size),
            scope_type,
            scope_id,
            user_category));
  }

  @PutMapping("/reservation-rules")
  public ApiResponse<?> rule(HttpServletRequest req, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.rule(Principal.from(req), data));
  }

  @DeleteMapping("/reservation-rules/{id}")
  public ApiResponse<?> deleteRule(HttpServletRequest req, @PathVariable long id) {
    service.deleteRule(Principal.from(req), id);
    return ApiResponse.ok(null);
  }

  @GetMapping("/blackouts")
  public ApiResponse<?> blackouts(
      HttpServletRequest req,
      @RequestParam(required = false) LocalDate start_date,
      @RequestParam(required = false) LocalDate end_date) {
    return ApiResponse.ok(service.blackouts(Principal.from(req), start_date, end_date));
  }

  @PostMapping("/blackouts")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  public ApiResponse<?> blackout(HttpServletRequest req, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.blackout(Principal.from(req), data));
  }

  @DeleteMapping("/blackouts/{id}")
  public ApiResponse<?> deleteBlackout(HttpServletRequest req, @PathVariable long id) {
    service.deleteBlackout(Principal.from(req), id);
    return ApiResponse.ok(null);
  }
}
