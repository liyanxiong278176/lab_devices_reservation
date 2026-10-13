package edu.labflow;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v2")
public class DashboardController {
  private final DashboardService service;

  public DashboardController(DashboardService service) {
    this.service = service;
  }

  @GetMapping({"/dashboard/me", "/dashboard/summary"})
  public ApiResponse<?> me(HttpServletRequest req) {
    return ApiResponse.ok(service.me(Principal.from(req)));
  }

  @GetMapping("/dashboard/overview")
  public ApiResponse<?> overview(
      HttpServletRequest req,
      @RequestParam(defaultValue = "device") String groupBy,
      @RequestParam(defaultValue = "30") int days) {
    return ApiResponse.ok(service.overview(Principal.from(req), groupBy, days));
  }

  @GetMapping("/recommendations")
  public ApiResponse<?> recommendations(
      HttpServletRequest req, @RequestParam(defaultValue = "6") int limit) {
    return ApiResponse.ok(service.recommendations(Principal.from(req), limit));
  }
}
