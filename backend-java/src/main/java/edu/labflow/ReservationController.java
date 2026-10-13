package edu.labflow;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.time.LocalDate;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v2")
public class ReservationController {
  private final ReservationService service;

  public ReservationController(ReservationService service) {
    this.service = service;
  }

  @PostMapping("/reservations/preflight")
  public ApiResponse<?> preflight(
      HttpServletRequest req, @Valid @RequestBody ReservationPlan plan) {
    return ApiResponse.ok(service.preflight(Principal.from(req), plan));
  }

  @PostMapping("/reservations")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  public ApiResponse<?> create(
      HttpServletRequest req,
      @Valid @RequestBody ReservationPlan plan,
      @RequestHeader("Idempotency-Key") String key) {
    return ApiResponse.ok(service.create(Principal.from(req), plan, key));
  }

  @GetMapping("/reservations/{id}")
  public ApiResponse<?> get(HttpServletRequest req, @PathVariable long id) {
    return ApiResponse.ok(service.get(Principal.from(req), id));
  }

  @GetMapping("/reservations/mine")
  public ApiResponse<?> mine(
      HttpServletRequest req,
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "20") int page_size,
      @RequestParam(required = false) String status,
      @RequestParam(required = false) String handover_status) {
    return ApiResponse.ok(
        service.list(
            Principal.from(req), new Pagination(page, page_size), "mine", status, handover_status));
  }

  @GetMapping("/approvals/pending")
  public ApiResponse<?> pending(
      HttpServletRequest req,
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "20") int page_size) {
    return ApiResponse.ok(
        service.list(
            Principal.from(req), new Pagination(page, page_size), "approvals", null, null));
  }

  @GetMapping("/reservations/handovers")
  public ApiResponse<?> handovers(
      HttpServletRequest req,
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "20") int page_size,
      @RequestParam(defaultValue = "PENDING") String status) {
    return ApiResponse.ok(
        service.list(
            Principal.from(req), new Pagination(page, page_size), "handovers", null, status));
  }

  @GetMapping("/devices/{id}/availability")
  public ApiResponse<?> availability(
      HttpServletRequest req,
      @PathVariable long id,
      @RequestParam LocalDate start_date,
      @RequestParam LocalDate end_date) {
    return ApiResponse.ok(
        service.availability(Principal.from(req), id, false, start_date, end_date));
  }

  @GetMapping("/device-pools/{id}/availability")
  public ApiResponse<?> poolAvailability(
      HttpServletRequest req,
      @PathVariable long id,
      @RequestParam LocalDate start_date,
      @RequestParam LocalDate end_date) {
    return ApiResponse.ok(
        service.availability(Principal.from(req), id, true, start_date, end_date));
  }
}
