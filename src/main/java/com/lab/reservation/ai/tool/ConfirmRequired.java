package com.lab.reservation.ai.tool;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * 标记一个 {@code @Tool} 方法需要用户先在 UI 点"确认"才能真正执行。
 *
 * <p>Plan §6 / B4 修复:避免用硬编码或运行时判断;用显式注解让
 * ToolRegistry 在构造 ToolDefinition 时一次性读取,后续 ConfirmationService
 * 用 confirmReason / confirmRisk / confirmImpact 渲染确认卡。
 *
 * <p>reason:对用户简短说明"为什么需要确认"(默认:"该操作将产生持久影响")
 * <br>riskSummary:风险摘要(可空)
 * <br>estimatedImpact:影响面预估,例如"将创建 1 条预约,占用 09:00-10:00 30 个槽位"
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface ConfirmRequired {
    String reason() default "该操作将产生持久影响";
    String riskSummary() default "";
    String estimatedImpact() default "";
}
