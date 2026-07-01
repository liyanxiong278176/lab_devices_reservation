package com.lab.reservation.common.result;

import lombok.Getter;

@Getter
public enum ResultCode {
    SUCCESS(200, "成功"),
    PARAM_INVALID(400, "参数校验失败"),
    UNAUTHORIZED(401, "未认证或登录失效"),
    FORBIDDEN(403, "无权限"),
    NOT_FOUND(404, "资源不存在"),
    RESERVATION_CONFLICT(409, "该时段已被占用"),
    USERNAME_OR_PASSWORD_ERROR(1001, "用户名或密码错误"),
    ACCOUNT_DISABLED(1002, "账号已禁用"),
    USERNAME_EXISTS(1003, "用户名已存在"),
    SLOT_OUT_OF_WORK_WINDOW(2001, "不在可预约工作时段内"),
    SLOT_NOT_ALIGNED(2002, "起止时间须以15分钟为单位"),
    EXCEED_MAX_DURATION(2003, "超过单次最大可预约时长"),
    DEVICE_UNAVAILABLE(2004, "设备当前不可预约"),
    STATUS_TRANSITION_INVALID(2005, "预约状态不允许该操作"),
    BUSINESS_ERROR(5000, "业务异常");

    private final int code;
    private final String msg;

    ResultCode(int code, String msg) {
        this.code = code;
        this.msg = msg;
    }
}
