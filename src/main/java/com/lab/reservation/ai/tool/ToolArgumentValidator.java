package com.lab.reservation.ai.tool;

import com.lab.reservation.ai.exception.ToolArgumentException;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

import java.lang.reflect.Method;
import java.lang.reflect.Parameter;
import java.util.HashMap;
import java.util.Map;

/**
 * 工具参数校验器:启动时构建"方法→参数规则表",运行时校验。
 *
 * <p>校验规则:
 * <ul>
 *   <li>任何参数都不能为 null(MISSING_FIELD)</li>
 *   <li>String 参数不能为空 / 纯空白(PARAM_INVALID)</li>
 *   <li>Long / Integer 参数必须 > 0(PARAM_INVALID)</li>
 * </ul>
 *
 * <p>Spring AI 1.0.6 在 {@code @ToolParam(description="...")} 上提供描述,
 * 这里只关注运行时基本类型校验。
 */
@Component
public class ToolArgumentValidator {

    private final Map<String, ParamRule[]> rules = new HashMap<>();

    /** 启动时由 {@link com.lab.reservation.ai.service.ToolRegistry} 调一次。 */
    public void register(String methodId, Method method) {
        ParamRule[] prs = new ParamRule[method.getParameters().length];
        for (int i = 0; i < prs.length; i++) {
            Parameter p = method.getParameters()[i];
            ToolParam ann = p.getAnnotation(ToolParam.class);
            prs[i] = new ParamRule(
                    p.getName(),
                    p.getType(),
                    ann == null ? null : ann.description()
            );
        }
        rules.put(methodId, prs);
    }

    /** 运行时校验。未注册过的 methodId 直接放行(防御性)。 */
    public void validate(String methodId, Map<String, Object> args) {
        ParamRule[] prs = rules.get(methodId);
        if (prs == null) return;
        for (ParamRule r : prs) {
            Object v = args == null ? null : args.get(r.name);
            if (v == null) {
                throw new ToolArgumentException("MISSING_FIELD", "missing field: " + r.name);
            }
            if (r.type == String.class && ((String) v).isBlank()) {
                throw new ToolArgumentException("PARAM_INVALID", "blank field: " + r.name);
            }
            if ((r.type == Long.class || r.type == Integer.class)
                    && ((Number) v).longValue() <= 0) {
                throw new ToolArgumentException("PARAM_INVALID", "non-positive: " + r.name);
            }
        }
    }

    private record ParamRule(String name, Class<?> type, String description) {}
}
