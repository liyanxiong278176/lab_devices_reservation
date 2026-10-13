package edu.labflow;

import jakarta.servlet.http.HttpServletRequest;
import java.util.*;
import org.springframework.core.io.FileSystemResource;
import org.springframework.http.*;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/api/v2")
public class DeviceAccessController {
  private final DeviceAccessService service;
  private final StorageService storage;
  private final ScopeAccess scope;

  public DeviceAccessController(
      DeviceAccessService service, StorageService storage, ScopeAccess scope) {
    this.service = service;
    this.storage = storage;
    this.scope = scope;
  }

  @GetMapping("/devices/{id}/documents")
  public ApiResponse<?> documents(HttpServletRequest req, @PathVariable long id) {
    return ApiResponse.ok(service.documents(Principal.from(req), id, false));
  }

  @GetMapping("/devices/{id}/safety-documents")
  public ApiResponse<?> safety(HttpServletRequest req, @PathVariable long id) {
    return ApiResponse.ok(service.documents(Principal.from(req), id, true));
  }

  @PostMapping("/devices/{id}/documents")
  @ResponseStatus(HttpStatus.CREATED)
  public ApiResponse<?> publish(
      HttpServletRequest req,
      @PathVariable long id,
      @RequestParam MultipartFile file,
      @RequestParam String document_type,
      @RequestParam String title,
      @RequestParam(defaultValue = "1.0") String version,
      @RequestParam(defaultValue = "false") boolean requires_ack) {
    var p = Principal.from(req);
    p.require("device:documents:manage");
    scope.device(p, id, true);
    var asset = storage.upload(p, file, false, "/api/v2/device-documents/");
    return ApiResponse.ok(
        service.publish(p, id, asset, document_type, title, version, requires_ack));
  }

  @DeleteMapping("/devices/{id}/documents/{documentId}")
  public ApiResponse<?> archive(
      HttpServletRequest req, @PathVariable long id, @PathVariable long documentId) {
    service.archive(Principal.from(req), id, documentId);
    return ApiResponse.ok(null);
  }

  @GetMapping("/devices/{id}/access")
  public ApiResponse<?> access(HttpServletRequest req, @PathVariable long id) {
    return ApiResponse.ok(service.access(Principal.from(req), id));
  }

  @PostMapping("/devices/{id}/safety-ack")
  public ApiResponse<?> acknowledge(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(
        service.acknowledge(
            Principal.from(req),
            id,
            data.get("reservation_id") == null ? null : Database.id(data, "reservation_id")));
  }

  @PostMapping("/devices/{id}/qualification-uploads")
  @ResponseStatus(HttpStatus.CREATED)
  public ApiResponse<?> qualificationUpload(
      HttpServletRequest req, @PathVariable long id, @RequestParam MultipartFile file) {
    var p = Principal.from(req);
    scope.device(p, id, false);
    return ApiResponse.ok(storage.upload(p, file, false, "/api/v2/repair-uploads/"));
  }

  @GetMapping("/devices/{id}/qualifications/mine")
  public ApiResponse<?> mine(HttpServletRequest req, @PathVariable long id) {
    return ApiResponse.ok(service.myQualification(Principal.from(req), id));
  }

  @PostMapping("/devices/{id}/qualifications")
  public ApiResponse<?> submit(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.submit(Principal.from(req), id, data));
  }

  @GetMapping("/devices/{id}/qualifications")
  public ApiResponse<?> qualifications(HttpServletRequest req, @PathVariable long id) {
    return ApiResponse.ok(service.qualifications(Principal.from(req), id));
  }

  @PatchMapping("/devices/{id}/qualifications/{qualificationId}")
  public ApiResponse<?> review(
      HttpServletRequest req,
      @PathVariable long id,
      @PathVariable long qualificationId,
      @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.review(Principal.from(req), id, qualificationId, data));
  }

  @PostMapping("/repair-uploads")
  @ResponseStatus(HttpStatus.CREATED)
  public ApiResponse<?> upload(HttpServletRequest req, @RequestParam MultipartFile file) {
    return ApiResponse.ok(
        storage.upload(Principal.from(req), file, true, "/api/v2/repair-uploads/"));
  }

  @GetMapping({"/device-documents/{token}", "/repair-uploads/{token}"})
  public ResponseEntity<?> download(HttpServletRequest req, @PathVariable String token) {
    var row = storage.asset(Principal.from(req), token);
    return ResponseEntity.ok()
        .contentType(MediaType.parseMediaType(row.get("content_type").toString()))
        .header("X-Content-Type-Options", "nosniff")
        .header("Cache-Control", "private, no-store")
        .header(
            "Content-Disposition",
            ContentDisposition.attachment()
                .filename(
                    row.get("original_name").toString(), java.nio.charset.StandardCharsets.UTF_8)
                .build()
                .toString())
        .body(new FileSystemResource(storage.file(row)));
  }

  @PostMapping("/reservations/{id}/feedback")
  @ResponseStatus(HttpStatus.CREATED)
  public ApiResponse<?> feedback(
      HttpServletRequest req, @PathVariable long id, @RequestBody Map<String, Object> data) {
    return ApiResponse.ok(service.feedback(Principal.from(req), id, data));
  }

  @GetMapping("/reservations/{id}/feedback")
  public ApiResponse<?> feedback(HttpServletRequest req, @PathVariable long id) {
    return ApiResponse.ok(service.feedback(Principal.from(req), id));
  }
}
