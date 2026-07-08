package com.lab.reservation.ai.service;

import com.lab.reservation.ai.tool.ConfirmRequired;
import com.lab.reservation.ai.tool.ToolArgumentValidator;
import com.lab.reservation.security.SecurityUserDetails;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.context.ApplicationContext;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.stereotype.Service;

import java.lang.reflect.Method;
import java.util.Arrays;
import java.util.Collection;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 工具注册表 — 启动时扫描 ai.tool 包里所有带 @Tool 的方法,
 * 构建 ToolDefinition;运行时按用户角色过滤。
 *
 * <p>设计:
 * <ul>
 *   <li>M4 修复:只扫 {@code com.lab.reservation.ai.tool} 包,避免给所有 @Component
 *       都做反射扫描。</li>
 *   <li>M4 修复:用 {@code getDeclaredMethods()} 而不是 {@code getMethods()},
 *       避免继承自 Object 的 equals/hashCode/toString 被列入。</li>
 *   <li>B4 修复:确认需求从 {@link ConfirmRequired} 注解读,不硬编码。</li>
 *   <li>角色解析从 {@code @Tool(description = "..." {roles:STUDENT,LAB_ADMIN})}
 *       末尾一段解析出来 — 这样 LLM 看到的工具 description 和我们用的角色限制共用一个字段。</li>
 * </ul>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ToolRegistry {

    private static final String AI_TOOL_PACKAGE = "com.lab.reservation.ai.tool";
    private static final String ROLES_MARKER = "{roles:";
    private static final String ROLES_MARKER_END = "}";

    private final ApplicationContext ctx;
    private final ToolArgumentValidator validator;
    private final Map<String, ToolDefinition> tools = new HashMap<>();

    @PostConstruct
    public void scan() {
        Map<String, Object> beans = ctx.getBeansOfType(Object.class);
        for (Object bean : beans.values()) {
            // 只扫 ai.tool 包
            if (!bean.getClass().getPackageName().startsWith(AI_TOOL_PACKAGE)) continue;
            for (Method m : bean.getClass().getDeclaredMethods()) {
                Tool t = m.getAnnotation(Tool.class);
                if (t == null) continue;
                ConfirmRequired cr = m.getAnnotation(ConfirmRequired.class);
                String id = bean.getClass().getSimpleName() + "." + m.getName();
                ToolDefinition def = new ToolDefinition(
                        id,
                        bean,
                        m,
                        t.name(),
                        t.description(),
                        parseRoles(t),
                        cr != null,
                        cr == null ? null : cr.reason(),
                        cr == null ? null : cr.riskSummary(),
                        cr == null ? null : cr.estimatedImpact()
                );
                tools.put(id, def);
                validator.register(id, m);
            }
        }
        long needConfirm = tools.values().stream().filter(ToolDefinition::confirmRequired).count();
        log.info("scanned {} AI tools ({} require confirmation)", tools.size(), needConfirm);
    }

    /** 给当前用户返回能用的工具集。role 解析自 {@code SecurityUserDetails.getAuthorities()}。 */
    public List<ToolDefinition> availableFor(SecurityUserDetails user) {
        Set<String> userRoles = user.getAuthorities().stream()
                .map(GrantedAuthority::getAuthority)
                .map(s -> s.replace("ROLE_", ""))
                .collect(Collectors.toSet());
        return tools.values().stream()
                .filter(t -> t.roles().isEmpty()
                        || userRoles.stream().anyMatch(t.roles()::contains))
                .toList();
    }

    public Collection<ToolDefinition> all() {
        return tools.values();
    }

    public Optional<ToolDefinition> findById(String id) {
        return Optional.ofNullable(tools.get(id));
    }

    /**
     * 角色声明被嵌在 @Tool(description = "...") 末尾:
     * <pre>"查询空闲设备 {roles:STUDENT,LAB_ADMIN}"</pre>
     * 没有 {roles:...} 就视为开放给所有角色。
     */
    private Set<String> parseRoles(Tool t) {
        String d = t.description();
        if (d == null || !d.contains(ROLES_MARKER)) return Set.of();
        int start = d.indexOf(ROLES_MARKER) + ROLES_MARKER.length();
        int end = d.indexOf(ROLES_MARKER_END, start);
        if (end < 0) return Set.of();
        return Arrays.stream(d.substring(start, end).split(","))
                .map(String::trim)
                .filter(s -> !s.isEmpty())
                .collect(Collectors.toSet());
    }

    public record ToolDefinition(
            String id,
            Object bean,
            Method method,
            String name,
            String description,
            Set<String> roles,
            boolean confirmRequired,
            String confirmReason,
            String confirmRisk,
            String confirmImpact
    ) {}
}
