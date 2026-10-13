package edu.labflow;

import jakarta.servlet.http.HttpServletRequest;
import java.util.*;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/v2")
public class OrganizationController {
  private final OrganizationService service;

  public OrganizationController(OrganizationService service) {
    this.service = service;
  }

  @GetMapping("/colleges")
  public ApiResponse<?> colleges(HttpServletRequest req) {
    return ApiResponse.ok(service.colleges(Principal.from(req)));
  }

  @GetMapping("/organization/managers")
  public ApiResponse<?> managers(HttpServletRequest req, @RequestParam long college_id) {
    return ApiResponse.ok(service.managers(Principal.from(req), college_id));
  }

  @PostMapping("/colleges")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  public ApiResponse<?> createCollege(
      HttpServletRequest req, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.college(Principal.from(req), null, data));
  }

  @PutMapping("/colleges/{id}")
  public ApiResponse<?> updateCollege(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.college(Principal.from(req), id, data));
  }

  @GetMapping("/labs")
  public ApiResponse<?> labs(
      HttpServletRequest req,
      @RequestParam(defaultValue = "1") int page,
      @RequestParam(defaultValue = "100") int size) {
    return ApiResponse.ok(service.labs(Principal.from(req), new Pagination(page, size)));
  }

  @PostMapping("/labs")
  @ResponseStatus(org.springframework.http.HttpStatus.CREATED)
  public ApiResponse<?> createLab(HttpServletRequest req, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.lab(Principal.from(req), null, data));
  }

  @PutMapping("/labs/{id}")
  public ApiResponse<?> updateLab(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.lab(Principal.from(req), id, data));
  }

  @GetMapping("/device-categories")
  public ApiResponse<?> categories(HttpServletRequest req) {
    return ApiResponse.ok(service.categories(Principal.from(req)));
  }
}
