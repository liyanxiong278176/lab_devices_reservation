package com.lab.reservation.aspect;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * 标注在 Controller 写接口上，由 {@link OperationLogAspect} 环绕记录操作日志。
 * value 即动作描述（如 "创建预约"、"登录"），原样写入 operation_log.action。
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface Log {
    String value() default "";
}
