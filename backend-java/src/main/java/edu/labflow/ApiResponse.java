package edu.labflow;

public record ApiResponse<T>(String code, String message, T data, String request_id) {
  public static <T> ApiResponse<T> ok(T data) {
    return new ApiResponse<>("OK", "success", data, null);
  }
}
