package com.lab.reservation.ai.service;

import com.lab.reservation.ai.security.SecurityUserDetailsForTests;
import com.lab.reservation.ai.tool.FakeToolSet;
import com.lab.reservation.ai.tool.ToolArgumentValidator;
import org.junit.jupiter.api.Test;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.context.ApplicationContext;

import java.util.Collections;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class ToolRegistryTest {

    private ToolRegistry newRegistry(ApplicationContext ctx) {
        return new ToolRegistry(ctx, new ToolArgumentValidator());
    }

    @Test
    void scan_with_empty_context_finds_no_tools() {
        ApplicationContext ctx = mock(ApplicationContext.class);
        when(ctx.getBeansOfType(Object.class)).thenReturn(Collections.emptyMap());

        ToolRegistry registry = newRegistry(ctx);
        registry.scan();

        assertThat(registry.all()).isEmpty();
    }

    @Test
    void availableFor_student_returns_only_student_tools() {
        // Construct a fake bean with @Tool and verify filtering
        ApplicationContext ctx = mock(ApplicationContext.class);
        FakeToolSet tools = new FakeToolSet();
        when(ctx.getBeansOfType(Object.class)).thenReturn(Map.of("tools", tools));

        ToolRegistry registry = newRegistry(ctx);
        registry.scan();

        var available = registry.availableFor(SecurityUserDetailsForTests.student());
        assertThat(available)
                .extracting(ToolRegistry.ToolDefinition::name)
                .contains("studentVisibleTool")
                .doesNotContain("adminOnlyTool");
    }

    @Test
    void parseRoles_handles_inline_role_list() {
        // 通过 FakeToolSet 暴露一个 description 含 {roles:STUDENT,LAB_ADMIN} 的工具
        // 并确认 availableFor(STUDENT) 能看到
        ApplicationContext ctx = mock(ApplicationContext.class);
        when(ctx.getBeansOfType(Object.class)).thenReturn(Map.of("tools", new FakeToolSet()));

        ToolRegistry registry = newRegistry(ctx);
        registry.scan();

        assertThat(registry.availableFor(SecurityUserDetailsForTests.student()))
                .extracting(ToolRegistry.ToolDefinition::name)
                .contains("studentToolFromDescription");
    }

    @Test
    void confirmRequired_drives_by_annotation() {
        ApplicationContext ctx = mock(ApplicationContext.class);
        when(ctx.getBeansOfType(Object.class)).thenReturn(Map.of("tools", new FakeToolSet()));

        ToolRegistry registry = newRegistry(ctx);
        registry.scan();

        assertThat(registry.all())
                .filteredOn(t -> t.name().equals("writeTool"))
                .allMatch(ToolRegistry.ToolDefinition::confirmRequired);
    }

    /** 包路径扫描边界 — ai.tool 包外的工具不会被纳入注册表。 */
    @Test
    void scan_ignores_beans_outside_ai_tool_package() {
        ApplicationContext ctx = mock(ApplicationContext.class);
        when(ctx.getBeansOfType(Object.class))
                .thenReturn(Map.of("outside", new NonAiToolBean()));

        ToolRegistry registry = newRegistry(ctx);
        registry.scan();

        assertThat(registry.all()).isEmpty();
    }

    /** 包路径不在 ai.tool — 用来验证扫描范围。 */
    static class NonAiToolBean {
        @Tool(name = "shouldNotAppear", description = "在外面包的工具")
        public String shouldNotAppear() { return "ok"; }
    }
}
