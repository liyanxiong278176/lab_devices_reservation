package edu.labflow;

import jakarta.servlet.http.HttpServletRequest;
import java.util.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v2/reservations/waitlist")
public class WaitlistController {
  private final WaitlistService service;

  public WaitlistController(WaitlistService service) {
    this.service = service;
  }

  @PostMapping
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  public ApiResponse<?> join(HttpServletRequest req, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.join(Principal.from(req), data));
  }

  @GetMapping("/mine")
  public ApiResponse<?> mine(HttpServletRequest req) {
    return ApiResponse.ok(service.mine(Principal.from(req)));
  }

  @DeleteMapping("/{id}")
  public ApiResponse<?> cancel(HttpServletRequest req, @PathVariable long id) {
    service.cancel(Principal.from(req), id);
    return ApiResponse.ok(null);
  }

  @PostMapping("/{id}/confirm")
  public ApiResponse<?> confirm(HttpServletRequest req, @PathVariable long id) {
    return ApiResponse.ok(service.confirm(Principal.from(req), id));
  }
}
