package edu.labflow;

import jakarta.servlet.http.HttpServletRequest;
import java.util.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v2")
public class LifecycleController {
  private final ReservationLifecycle service;

  public LifecycleController(ReservationLifecycle service) {
    this.service = service;
  }

  @PostMapping("/approvals/batch-approve")
  public ApiResponse<?> batch(HttpServletRequest req, @RequestBody Map<String, Object> data) {
    if (!(data.get("ids") instanceof List<?> values)
        || values.stream().anyMatch(v -> !(v instanceof Number)))
      throw ApiError.validation("审批编号列表无效");
    return ApiResponse.ok(
        Map.of(
            "approved",
            service.batchApproval(
                Principal.from(req), values.stream().map(v -> ((Number) v).longValue()).toList())));
  }

  @PostMapping("/approvals/{id}/approve")
  public ApiResponse<?> approve(
      HttpServletRequest req,
      @PathVariable long id,
      @RequestBody(required = false) Map<String, Object> data) {
    return ApiResponse.ok(
        service.approval(
            Principal.from(req),
            id,
            true,
            data == null ? null : Database.str(data, "reason", null)));
  }

  @PostMapping("/approvals/{id}/reject")
  public ApiResponse<?> reject(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(
        service.approval(Principal.from(req), id, false, Database.str(data, "reason", null)));
  }

  @PostMapping("/reservations/{id}/cancel")
  public ApiResponse<?> cancel(HttpServletRequest req, @PathVariable long id) {
    return ApiResponse.ok(service.cancel(Principal.from(req), id, false, null));
  }

  @PostMapping("/reservations/{id}/cancel-handover-exception")
  public ApiResponse<?> cancelException(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(
        service.cancel(Principal.from(req), id, true, Database.str(data, "reason", null)));
  }

  @PostMapping("/reservations/{id}/check-in")
  public ApiResponse<?> checkin(HttpServletRequest req, @PathVariable long id) {
    service.checkin(Principal.from(req), id);
    throw new ApiError("HANDOVER_REQUIRED", "所有预约均由负责人完成交接后才能开始使用", 409);
  }

  @PostMapping("/reservations/{id}/handover")
  public ApiResponse<?> handover(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.handover(Principal.from(req), id, data));
  }

  @PostMapping("/reservations/{id}/return")
  public ApiResponse<?> requestReturn(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.requestReturn(Principal.from(req), id, data));
  }

  @PostMapping("/reservations/{id}/accept-return")
  public ApiResponse<?> accept(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.acceptReturn(Principal.from(req), id, data));
  }

  @PostMapping("/reservations/{id}/violate")
  public ApiResponse<?> violate(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(
        service.violate(Principal.from(req), id, Database.str(data, "reason", null)));
  }
}
