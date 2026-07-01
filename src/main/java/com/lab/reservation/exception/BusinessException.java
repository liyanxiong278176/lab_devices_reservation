package com.lab.reservation.exception;

import com.lab.reservation.common.result.ResultCode;
import lombok.Getter;

@Getter
public class BusinessException extends RuntimeException {
    private final int code;

    public BusinessException(ResultCode rc) {
        super(rc.getMsg());
        this.code = rc.getCode();
    }

    public BusinessException(int code, String msg) {
        super(msg);
        this.code = code;
    }
}
