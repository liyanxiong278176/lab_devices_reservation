package edu.labflow;

import java.io.IOException;
import java.nio.file.*;
import java.util.*;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.multipart.MultipartFile;

@Service
public class StorageService {
  private final Database db;
  private final Settings settings;
  private final ScopeAccess scope;
  private final TransactionTemplate tx;

  public StorageService(
      Database db, Settings settings, ScopeAccess scope, PlatformTransactionManager tm) {
    this.db = db;
    this.settings = settings;
    this.scope = scope;
    tx = new TransactionTemplate(tm);
  }

  public Map<String, Object> upload(
      Principal p, MultipartFile file, boolean imagesOnly, String urlPrefix) {
    if (file.getSize() > settings.integer("UPLOAD_MAX_BYTES", 5 * 1024 * 1024))
      throw new ApiError("UPLOAD_TOO_LARGE", "文件大小不能超过 5 MB", 413);
    String mime = Objects.requireNonNullElse(file.getContentType(), "").toLowerCase(Locale.ROOT);
    byte[] data;
    try {
      data = file.getBytes();
    } catch (IOException e) {
      throw new ApiError("UPLOAD_FAILED", "无法读取文件", 422);
    }
    String suffix = validate(mime, data, imagesOnly);
    String token = AuthService.random(32);
    Path root = settings.uploads(), path = root.resolve(token + suffix);
    try {
      Files.createDirectories(root);
      Files.write(path, data, StandardOpenOption.CREATE_NEW);
    } catch (IOException e) {
      throw new ApiError("UPLOAD_FAILED", "无法保存文件", 503);
    }
    try {
      return tx.execute(
          status -> {
            var scopes = new ArrayList<Map.Entry<String, Long>>();
            scopes.add(Map.entry("global", 0L));
            if (p.collegeId() != null) scopes.add(Map.entry("college", p.collegeId()));
            scopes.add(Map.entry("user", p.userId()));
            for (var entry : scopes) {
              db.execute(
                  "INSERT IGNORE INTO v2_upload_quota_bucket (scope_type,scope_id,used_bytes) VALUES (?,?,0)",
                  entry.getKey(),
                  entry.getValue());
              var row =
                  db.one(
                      "SELECT used_bytes FROM v2_upload_quota_bucket WHERE scope_type=? AND scope_id=? FOR UPDATE",
                      entry.getKey(),
                      entry.getValue());
              long limit =
                  switch (entry.getKey()) {
                    case "global" ->
                        settings.longInteger("UPLOAD_TOTAL_QUOTA_BYTES", 2L * 1024 * 1024 * 1024);
                    case "college" ->
                        settings.longInteger("UPLOAD_COLLEGE_QUOTA_BYTES", 1024L * 1024 * 1024);
                    default -> settings.longInteger("UPLOAD_USER_QUOTA_BYTES", 100L * 1024 * 1024);
                  };
              if (Database.id(row, "used_bytes") + data.length > limit)
                throw new ApiError("UPLOAD_QUOTA_EXCEEDED", "附件存储配额已满", 409);
              db.execute(
                  "UPDATE v2_upload_quota_bucket SET used_bytes=used_bytes+? WHERE scope_type=? AND scope_id=?",
                  data.length,
                  entry.getKey(),
                  entry.getValue());
            }
            String name =
                Objects.requireNonNullElse(file.getOriginalFilename(), "attachment")
                    .replace('\\', '/');
            name = name.substring(name.lastIndexOf('/') + 1).replace("\r", "").replace("\n", "");
            if (name.length() > 255) name = name.substring(0, 255);
            long id =
                db.insert(
                    "INSERT INTO v2_upload_asset (asset_token,user_id,college_id,original_name,content_type,size_bytes,storage_path) VALUES (?,?,?,?,?,?,?)",
                    token,
                    p.userId(),
                    p.collegeId(),
                    name,
                    mime,
                    data.length,
                    path.toString());
            return Map.of(
                "asset_id",
                id,
                "asset_token",
                token,
                "url",
                urlPrefix + token,
                "name",
                name,
                "content_type",
                mime,
                "size_bytes",
                data.length);
          });
    } catch (RuntimeException e) {
      try {
        Files.deleteIfExists(path);
      } catch (IOException ignored) {
      }
      throw e;
    }
  }

  private String validate(String mime, byte[] data, boolean imagesOnly) {
    if (mime.equals("image/jpeg")
        && data.length > 3
        && (data[0] & 255) == 255
        && (data[1] & 255) == 216
        && (data[2] & 255) == 255) return ".jpg";
    if (mime.equals("image/png")
        && data.length > 8
        && Arrays.equals(
            Arrays.copyOf(data, 8), new byte[] {(byte) 137, 80, 78, 71, 13, 10, 26, 10}))
      return ".png";
    if (mime.equals("image/webp")
        && data.length > 12
        && new String(data, 0, 4, java.nio.charset.StandardCharsets.US_ASCII).equals("RIFF")
        && new String(data, 8, 4, java.nio.charset.StandardCharsets.US_ASCII).equals("WEBP"))
      return ".webp";
    if (!imagesOnly) {
      if (mime.equals("application/pdf")
          && data.length > 5
          && new String(data, 0, 5, java.nio.charset.StandardCharsets.US_ASCII).equals("%PDF-"))
        return ".pdf";
      if (Set.of("text/plain", "text/markdown").contains(mime)
          && data.length > 0
          && !new String(data, java.nio.charset.StandardCharsets.UTF_8).contains("\u0000"))
        return ".txt";
    }
    throw new ApiError("UPLOAD_CONTENT_INVALID", "文件类型或内容不符合要求", 422);
  }

  public void evidence(Principal p, Object urls, long college) {
    if (!(urls instanceof List<?> list)
        || list.isEmpty()
        || list.size() > 6
        || new HashSet<>(list).size() != list.size())
      throw new ApiError("EVIDENCE_REQUIRED", "必须上传 1 至 6 张不重复现场照片", 422);
    for (Object value : list) {
      String url = value.toString();
      String prefix = "/api/v2/repair-uploads/";
      if (!url.startsWith(prefix)) throw new ApiError("EVIDENCE_INVALID", "现场照片必须先上传到本系统", 422);
      var asset =
          db.one(
              "SELECT * FROM v2_upload_asset WHERE asset_token=?", url.substring(prefix.length()));
      if (asset == null
          || Database.id(asset, "user_id") != p.userId()
          || !(Objects.equals(asset.get("college_id"), college)
              || (p.systemAdmin() && asset.get("college_id") == null)))
        throw new ApiError("EVIDENCE_FORBIDDEN", "现场照片非本人上传或不属于本学院", 403);
      if (!Set.of("image/jpeg", "image/png", "image/webp").contains(asset.get("content_type"))
          || Database.id(asset, "size_bytes") > 5 * 1024 * 1024)
        throw new ApiError("EVIDENCE_INVALID", "照片类型或大小不符合要求", 422);
    }
  }

  public Map<String, Object> asset(Principal p, String token) {
    if (!token.matches("[A-Za-z0-9_-]{20,64}")) throw ApiError.missing("附件");
    var row = db.one("SELECT * FROM v2_upload_asset WHERE asset_token=?", token);
    if (row == null) throw ApiError.missing("附件");
    if (!p.systemAdmin() && Database.id(row, "college_id") != p.tenant())
      throw ApiError.forbidden();
    if (Database.id(row, "user_id") == p.userId() || p.systemAdmin()) return row;
    var doc =
        db.one(
            "SELECT device_id FROM v2_device_document WHERE asset_id=? AND active=1",
            row.get("id"));
    if (doc != null) {
      scope.device(p, Database.id(doc, "device_id"), false);
      return row;
    }
    if (!p.manager()) throw ApiError.forbidden();
    var devices =
        db.rows(
            "SELECT device_id FROM v2_device_qualification WHERE asset_id=? UNION SELECT device_id FROM v2_repair_report WHERE JSON_SEARCH(image_urls,'one',?) IS NOT NULL UNION SELECT device_id FROM v2_device_handover WHERE JSON_SEARCH(handover_image_urls,'one',?) IS NOT NULL OR JSON_SEARCH(return_image_urls,'one',?) IS NOT NULL",
            row.get("id"),
            "%" + token + "%",
            "%" + token + "%",
            "%" + token + "%");
    for (var device : devices) {
      try {
        scope.device(p, Database.id(device, "device_id"), true);
        return row;
      } catch (ApiError e) {
      }
    }
    throw ApiError.forbidden();
  }

  public Path file(Map<String, Object> asset) {
    Path root = settings.uploads();
    Path stored = Path.of(asset.get("storage_path").toString());
    Path candidate = stored.isAbsolute() ? stored : root.resolve(stored.getFileName());
    if (!candidate.normalize().startsWith(root)) {
      candidate = root.resolve(stored.getFileName());
    }
    try {
      Path realRoot = root.toRealPath(), real = candidate.toRealPath();
      if (!real.startsWith(realRoot)) throw ApiError.forbidden();
      return real;
    } catch (IOException e) {
      throw ApiError.missing("附件");
    }
  }
}
