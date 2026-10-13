package edu.labflow;

import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class ErrorHandler {
  private static final Logger log = LoggerFactory.getLogger(ErrorHandler.class);

  @ExceptionHandler(
      org.springframework.web.context.request.async.AsyncRequestNotUsableException.class)
  public void disconnected() {}

  @ExceptionHandler(ApiError.class)
  public ResponseEntity<ApiResponse<Object>> domain(ApiError e, HttpServletRequest req) {
    var response = ResponseEntity.status(e.status);
    e.headers.forEach(response::header);
    return response.body(
        new ApiResponse<>(e.code, e.getMessage(), e.data, (String) req.getAttribute("request_id")));
  }

  @ExceptionHandler(DuplicateKeyException.class)
  public ResponseEntity<ApiResponse<Object>> duplicate(
      DuplicateKeyException e, HttpServletRequest req) {
    return domain(new ApiError("CONFLICT", "记录已存在或设备日期已被占用", 409), req);
  }

  @ExceptionHandler({
    org.springframework.web.bind.MethodArgumentNotValidException.class,
    org.springframework.http.converter.HttpMessageNotReadableException.class,
    org.springframework.web.method.annotation.MethodArgumentTypeMismatchException.class
  })
  public ResponseEntity<ApiResponse<Object>> validation(Exception e, HttpServletRequest req) {
    return domain(ApiError.validation("请求参数不符合要求"), req);
  }

  @ExceptionHandler(Exception.class)
  public ResponseEntity<ApiResponse<Object>> unexpected(Exception e, HttpServletRequest req) {
    log.error("Request failed, request_id={}", req.getAttribute("request_id"), e);
    return domain(new ApiError("INTERNAL_ERROR", "服务器暂时无法处理请求", 500), req);
  }

  @ExceptionHandler({
    org.springframework.web.servlet.resource.NoResourceFoundException.class,
    org.springframework.web.servlet.NoHandlerFoundException.class
  })
  public ResponseEntity<ApiResponse<Object>> notFound(Exception e, HttpServletRequest req) {
    return domain(new ApiError("NOT_FOUND", "资源不存在", 404), req);
  }

  @ExceptionHandler({
    org.springframework.dao.TransientDataAccessException.class,
    org.springframework.jdbc.CannotGetJdbcConnectionException.class
  })
  public ResponseEntity<ApiResponse<Object>> dependency(Exception e, HttpServletRequest req) {
    return domain(new ApiError("DEPENDENCY_UNAVAILABLE", "数据库或基础依赖暂时不可用，请稍后重试", 503), req);
  }

  @ExceptionHandler({
    java.time.format.DateTimeParseException.class,
    NumberFormatException.class,
    org.springframework.dao.DataIntegrityViolationException.class
  })
  public ResponseEntity<ApiResponse<Object>> badData(Exception e, HttpServletRequest req) {
    return domain(ApiError.validation("输入字段或关联数据不符合要求"), req);
  }
}
