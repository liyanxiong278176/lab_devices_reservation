package com.lab.reservation.ai.tool;

import org.springframework.ai.tool.annotation.Tool;

/**
 * 工具定义集合 — 给测试用的几种 {@code @Tool} 模式。
 *
 * <p>放在 {@code com.lab.reservation.ai.tool} 包下,这样
 * {@link com.lab.reservation.ai.service.ToolRegistry} 扫描包时能识别到。
 * 它本身不需要被 Spring 注册为 bean,测试时通过 {@code ApplicationContext.getBeansOfType}
 * 模拟"放进去",由 {@code ToolRegistry.scan()} 自己反射发现 @Tool 方法。
 */
public class FakeToolSet {

    @Tool(name = "studentVisibleTool",
          description = "学生也能用的工具")
    public String studentVisibleTool() { return "ok"; }

    @Tool(name = "adminOnlyTool",
          description = "管理员专用 {roles:LAB_ADMIN,SYS_ADMIN}")
    public String adminOnlyTool() { return "ok"; }

    @Tool(name = "studentToolFromDescription",
          description = "通过描述解析角色 {roles:STUDENT}")
    public String studentToolFromDescription() { return "ok"; }

    @Tool(name = "writeTool", description = "一个写操作")
    @ConfirmRequired(reason = "将写数据库")
    public String writeTool() { return "ok"; }
}
