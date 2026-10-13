package edu.labflow;

public class ApiError extends RuntimeException {
  public final String code;
  public final int status;
  public final Object data;
  public final java.util.Map<String, String> headers;

  public ApiError(String code, String message, int status) {
    this(code, message, status, null, java.util.Map.of());
  }

  public ApiError(
      String code, String message, int status, Object data, java.util.Map<String, String> headers) {
    super(message);
    this.code = code;
    this.status = status;
    this.data = data;
    this.headers = headers;
  }

  public static ApiError forbidden() {
    return new ApiError("FORBIDDEN", "当前账号没有执行此操作的权限", 403);
  }

  public static ApiError missing(String resource) {
    return new ApiError("NOT_FOUND", resource + "不存在", 404);
  }

  public static ApiError validation(String message) {
    return new ApiError("VALIDATION_ERROR", message, 422);
  }
}
