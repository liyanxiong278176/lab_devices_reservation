package com.lab.reservation.aspect;

import cn.hutool.json.JSONConfig;
import cn.hutool.json.JSONUtil;
import com.lab.reservation.entity.OperationLog;
import com.lab.reservation.mapper.OperationLogMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.aspectj.lang.JoinPoint;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Component;

import java.util.regex.Pattern;

/**
 * 操作日志写入器（独立 bean）。
 *
 * 关键设计：把"组装 OperationLog + 序列化参数 + 脱敏 + insert"整体放在 @Async 方法里，
 * 由 {@link OperationLogAspect} 通过注入的本 bean 调用 write(...)。
 * 因为是跨 bean 调用，调用链经过 Spring 代理，{@link Async} 注解才会真正生效
 * （类内 this 调用会绕过代理，@Async 失效为同步）。
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class OperationLogWriter {

    /** 脱敏正则：匹配 "password":"xxx" 形式（含 oldPassword/newPassword，大小写不敏感）。 */
    private static final Pattern SENSITIVE_PATTERN = Pattern.compile(
            "(\"(?:password|oldPassword|newPassword)\"\\s*:\\s*)\"[^\"]*\"",
            Pattern.CASE_INSENSITIVE);

    private final OperationLogMapper operationLogMapper;

    /**
     * 异步组装并写入操作日志（含参数 JSON 序列化 + 脱敏）。
     * 经独立 bean 调用 → 走 Spring 代理 → @Async 生效。
     * 轻量数据（username/userId/ip/cost）已由切面同步取好，避免异步线程丢 SecurityContext。
     */
    @Async
    public void write(Log logAnno, JoinPoint jp, long costMs, String username, Long userId, String ip) {
        try {
            OperationLog entity = new OperationLog();
            entity.setUserId(userId);
            entity.setUsername(username);
            entity.setAction(logAnno.value());
            entity.setMethod(jp.getSignature().getDeclaringType().getSimpleName()
                    + "." + jp.getSignature().getName());
            entity.setParams(desensitize(jp.getArgs()));
            entity.setIp(ip);
            entity.setCostMs(costMs);
            operationLogMapper.insert(entity);
        } catch (Exception e) {
            // 日志写库失败绝不影响主流程
            log.warn("写入操作日志失败: action={}, err={}", logAnno.value(), e.getMessage());
        }
    }

    /** 序列化入参并对敏感字段脱敏。 */
    private String desensitize(Object[] args) {
        if (args == null || args.length == 0) {
            return "[]";
        }
        try {
            String json = JSONUtil.toJsonStr(args,
                    new JSONConfig().setIgnoreNullValue(false).setDateFormat("yyyy-MM-dd HH:mm:ss"));
            return SENSITIVE_PATTERN.matcher(json).replaceAll("$1\"***\"");
        } catch (Exception e) {
            // 序列化失败也不阻断
            return "[serialize_error: " + e.getClass().getSimpleName() + "]";
        }
    }
}
