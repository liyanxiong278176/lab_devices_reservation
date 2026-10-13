package edu.labflow;

import io.micrometer.prometheusmetrics.PrometheusMeterRegistry;
import jakarta.servlet.http.HttpServletRequest;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v2")
public class SystemController {
  private final StreamMetrics streamMetrics;
  private final Database db;
  private final StringRedisTemplate redis;
  private final OutboxWorker worker;
  private final Settings settings;
  private final org.springframework.beans.factory.ObjectProvider<PrometheusMeterRegistry> metrics;

  public SystemController(
      StreamMetrics streamMetrics,
      Database db,
      StringRedisTemplate redis,
      OutboxWorker worker,
      Settings settings,
      org.springframework.beans.factory.ObjectProvider<PrometheusMeterRegistry> metrics) {
    this.streamMetrics = streamMetrics;
    this.db = db;
    this.redis = redis;
    this.worker = worker;
    this.settings = settings;
    this.metrics = metrics;
  }

  @GetMapping("/live")
  public ApiResponse<?> live() {
    return ApiResponse.ok(Map.of("status", "alive"));
  }

  @GetMapping("/ready")
  public ApiResponse<?> ready() {
    try {
      db.count("SELECT 1");
      redis.opsForValue().get("lab:v2:ready-probe");
      return ApiResponse.ok(Map.of("status", "ready", "mysql", true, "redis", true));
    } catch (org.springframework.dao.DataAccessException e) {
      throw new ApiError("DEPENDENCY_UNAVAILABLE", "数据库或登录服务暂时不可用", 503);
    }
  }

  @GetMapping("/metrics")
  public ResponseEntity<?> metrics(
      @RequestHeader(value = "Authorization", required = false) String authorization) {
    String token = settings.get("METRICS_TOKEN", "");
    if (token.isBlank()) throw new ApiError("NOT_FOUND", "资源不存在", 404);
    String supplied =
        authorization != null && authorization.startsWith("Bearer ")
            ? authorization.substring(7)
            : "";
    if (!MessageDigest.isEqual(
        token.getBytes(StandardCharsets.UTF_8), supplied.getBytes(StandardCharsets.UTF_8)))
      throw new ApiError("AUTH_REQUIRED", "无权访问监控指标", 401);
    var registry = metrics.getIfAvailable();
    if (registry == null) throw new ApiError("METRICS_UNAVAILABLE", "监控指标未启用", 503);
    return ResponseEntity.ok()
        .contentType(MediaType.parseMediaType("text/plain;version=0.0.4;charset=utf-8"))
        .body(registry.scrape() + streamMetrics.scrape());
  }

  @GetMapping("/system/outbox/failed")
  public ApiResponse<?> failed(HttpServletRequest req) {
    return ApiResponse.ok(worker.failed(Principal.from(req)));
  }

  @PostMapping("/system/outbox/{id}/retry")
  public ApiResponse<?> retry(HttpServletRequest req, @PathVariable long id) {
    return ApiResponse.ok(worker.retry(Principal.from(req), id));
  }
}
