package edu.labflow;

import jakarta.servlet.http.HttpServletRequest;
import java.time.LocalDate;
import java.util.*;
import org.springframework.core.io.FileSystemResource;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v2/reports")
public class ReportController {
  private final ReportService service;

  public ReportController(ReportService service) {
    this.service = service;
  }

  @GetMapping("/summary")
  public ApiResponse<?> summary(
      HttpServletRequest req,
      @RequestParam(required = false) LocalDate start_date,
      @RequestParam(required = false) LocalDate end_date,
      @RequestParam(required = false) Long college_id) {
    return ApiResponse.ok(service.summary(Principal.from(req), start_date, end_date, college_id));
  }

  @GetMapping("/export/{type}")
  public ResponseEntity<?> direct(
      HttpServletRequest req,
      @PathVariable String type,
      @RequestParam(required = false) String start_date,
      @RequestParam(required = false) String end_date,
      @RequestParam(required = false) String status,
      @RequestParam(required = false) Long college_id) {
    var filters = new HashMap<String, Object>();
    filters.put("start_date", start_date);
    filters.put("end_date", end_date);
    filters.put("status", status);
    filters.put("college_id", college_id);
    return ResponseEntity.ok()
        .contentType(MediaType.parseMediaType("text/csv;charset=utf-8"))
        .header("Content-Disposition", "attachment; filename=\"lab-" + type + ".csv\"")
        .body(service.direct(Principal.from(req), type, filters));
  }

  @PostMapping("/exports")
  @ResponseStatus(HttpStatus.CREATED)
  public ApiResponse<?> request(HttpServletRequest req, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.request(Principal.from(req), data));
  }

  @GetMapping("/exports/{id}")
  public ApiResponse<?> status(HttpServletRequest req, @PathVariable long id) {
    return ApiResponse.ok(service.status(Principal.from(req), id));
  }

  @GetMapping("/exports/{id}/download")
  public ResponseEntity<?> download(HttpServletRequest req, @PathVariable long id) {
    return ResponseEntity.ok()
        .contentType(MediaType.parseMediaType("text/csv;charset=utf-8"))
        .header("Cache-Control", "private, no-store")
        .header("Content-Disposition", "attachment; filename=\"lab-export.csv\"")
        .body(new FileSystemResource(service.download(Principal.from(req), id)));
  }
}
