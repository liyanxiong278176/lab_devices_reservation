package edu.labflow;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v2/notifications")
public class NotificationController {
  private final NotificationService service;
  private final NotificationRelay relay;

  public NotificationController(NotificationService service, NotificationRelay relay) {
    this.service = service;
    this.relay = relay;
  }

  @GetMapping("/mine")
  public ApiResponse<?> list(
      HttpServletRequest req,
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "10") int size,
      @RequestParam(defaultValue = "false") boolean onlyUnread) {
    return ApiResponse.ok(
        service.list(Principal.from(req), new Pagination(page, size), onlyUnread));
  }

  @PatchMapping("/{id}/read")
  public ApiResponse<?> read(HttpServletRequest req, @PathVariable long id) {
    service.read(Principal.from(req), id);
    return ApiResponse.ok(null);
  }

  @PatchMapping("/read-all")
  public ApiResponse<?> all(HttpServletRequest req) {
    service.read(Principal.from(req), null);
    return ApiResponse.ok(null);
  }

  @GetMapping(value = "/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
  public ResponseEntity<?> stream(
      HttpServletRequest req,
      @RequestHeader(value = "Last-Event-ID", required = false) String last) {
    return ResponseEntity.ok()
        .header("Cache-Control", "no-cache, no-transform")
        .header("X-Accel-Buffering", "no")
        .body(relay.connect(Principal.from(req), last));
  }
}
