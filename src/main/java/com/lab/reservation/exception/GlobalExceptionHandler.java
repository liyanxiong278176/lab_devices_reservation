package com.lab.reservation.exception;

import com.lab.reservation.common.result.Result;
import com.lab.reservation.common.result.ResultCode;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.AuthenticationException;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(BusinessException.class)
    public Result<?> biz(BusinessException e) {
        return Result.fail(e.getCode(), e.getMessage());
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public Result<?> invalid(MethodArgumentNotValidException e) {
        FieldError fe = e.getBindingResult().getFieldError();
        return Result.fail(ResultCode.PARAM_INVALID.getCode(),
                fe != null ? fe.getDefaultMessage() : ResultCode.PARAM_INVALID.getMsg());
    }

    @ExceptionHandler(DuplicateKeyException.class)
    public Result<?> dup(DuplicateKeyException e) {
        return Result.fail(ResultCode.RESERVATION_CONFLICT);
    }

    @ExceptionHandler(AuthenticationException.class)
    public Result<?> auth(AuthenticationException e) {
        return Result.fail(ResultCode.UNAUTHORIZED);
    }

    @ExceptionHandler(AccessDeniedException.class)
    public Result<?> denied(AccessDeniedException e) {
        return Result.fail(ResultCode.FORBIDDEN);
    }

    @ExceptionHandler(Exception.class)
    public Result<?> all(Exception e) {
        e.printStackTrace();
        return Result.fail(ResultCode.BUSINESS_ERROR);
    }
}
