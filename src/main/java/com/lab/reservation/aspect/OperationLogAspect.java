package com.lab.reservation.aspect;

import com.lab.reservation.security.SecurityUserDetails;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.aspectj.lang.ProceedingJoinPoint;
import org.aspectj.lang.annotation.Around;
import org.aspectj.lang.annotation.Aspect;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

/**
 * 操作日志切面。环绕标注 {@link Log} 的 Controller 方法，
 * 异步记录 username/userId/action/method/params/ip/cost_ms 到 operation_log。
 *
 * 设计要点：
 * - 异常也记录 cost（finally 写日志），异常继续抛出，不吞。
 * - 登录等未认证场景：SecurityContext 无 principal，username 记 unknown。
 * - 同步只取轻量上下文（username/userId/ip/cost），序列化+脱敏+insert 全部交由
 *   {@link OperationLogWriter#write} 异步执行。
 * - @Async 生效保证：write 在独立 bean（OperationLogWriter）中，经本切面注入并调用 →
 *   走 Spring 代理，@Async 真正异步化；不再用类内 this 调用（那样会绕过代理失效）。
 */
@Slf4j
@Aspect
@Component
@RequiredArgsConstructor
public class OperationLogAspect {

    private final OperationLogWriter operationLogWriter;

    @Around("@annotation(logAnno)")
    public Object around(ProceedingJoinPoint joinPoint, Log logAnno) throws Throwable {
        long start = System.currentTimeMillis();
        try {
            return joinPoint.proceed();
        } finally {
            long cost = System.currentTimeMillis() - start;
            try {
                // 同步只取轻量数据：SecurityContext/RequestContext 必须在请求线程取，
                // 否则异步线程无上下文。组装/序列化/insert 全交给 writer。
                String username = "unknown";
                Long userId = null;
                Authentication auth = SecurityContextHolder.getContext().getAuthentication();
                if (auth != null && auth.getPrincipal() instanceof SecurityUserDetails ud) {
                    userId = ud.getUserId();
                    username = ud.getUsername();
                }
                String ip = resolveIp();
                operationLogWriter.write(logAnno, joinPoint, cost, username, userId, ip);
            } catch (Exception e) {
                // 日志记录失败绝不能影响主流程
                log.warn("写入操作日志失败: action={}, err={}", logAnno.value(), e.getMessage());
            }
        }
    }

    /** 取客户端 IP，优先 X-Forwarded-For。 */
    private String resolveIp() {
        try {
            ServletRequestAttributes attrs = (ServletRequestAttributes) RequestContextHolder.getRequestAttributes();
            if (attrs == null) {
                return null;
            }
            HttpServletRequest request = attrs.getRequest();
            String xff = request.getHeader("X-Forwarded-For");
            if (xff != null && !xff.isBlank()) {
                return xff.split(",")[0].trim();
            }
            return request.getRemoteAddr();
        } catch (Exception e) {
            return null;
        }
    }
}
