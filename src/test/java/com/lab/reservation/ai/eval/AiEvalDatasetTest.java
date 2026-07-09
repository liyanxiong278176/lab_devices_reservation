package com.lab.reservation.ai.eval;

import com.lab.reservation.ai.tool.ConfirmRequired;
import org.junit.jupiter.api.Test;
import org.springframework.ai.tool.annotation.Tool;

import java.lang.reflect.Method;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * AI 助手数据集评估 — 论文 §11.3 30 用例压缩版。
 *
 * <p>完整 30 用例需在线 LLM 调用,留作运维 follow-up;这里只验证工具层的
 * 反射不变式(无需装配 Spring 上下文,也不用真实 service):
 * <ul>
 *   <li>每个 @Tool 类注册的方法名符合命名预期</li>
 *   <li>写工具方法都带 @ConfirmRequired</li>
 *   <li>工具方法都带 @Tool(description=...) 且描述含 {roles:...} 标记</li>
 * </ul>
 */
class AiEvalDatasetTest {

    private static final String AI_TOOL_PKG = "com.lab.reservation.ai.tool";

    @Test
    void expected_tool_methods_are_present() {
        Map<String, String> expected = Map.of(
                "DeviceTool", "searchDevices,getDeviceDetails",
                "ReservationTool", "searchMyReservations,createReservation,cancelReservation",
                "RecommendTool", "recommendDevices",
                "RepairTool", "submitRepairTicket,takeRepairTicket",
                "AdminTool", "queryLabReservations",
                "RagManualTool", "searchDeviceManuals"
        );
        for (var entry : expected.entrySet()) {
            Class<?> cls = classOrNull(AI_TOOL_PKG + "." + entry.getKey());
            assertThat(cls)
                    .as("class %s must exist", entry.getKey())
                    .isNotNull();
            Set<String> actualMethods = new HashSet<>();
            for (Method m : cls.getDeclaredMethods()) {
                if (m.isAnnotationPresent(Tool.class)) {
                    actualMethods.add(m.getName());
                }
            }
            for (String expectedName : entry.getValue().split(",")) {
                assertThat(actualMethods)
                        .as("%s must declare @Tool %s", entry.getKey(), expectedName)
                        .contains(expectedName.trim());
            }
        }
    }

    @Test
    void write_tools_have_ConfirmRequired() {
        String[] writeTools = {
                "ReservationTool.createReservation",
                "ReservationTool.cancelReservation",
                "RepairTool.submitRepairTicket",
                "RepairTool.takeRepairTicket"
        };
        for (String qualified : writeTools) {
            int dot = qualified.lastIndexOf('.');
            String className = AI_TOOL_PKG + "." + qualified.substring(0, dot);
            String methodName = qualified.substring(dot + 1);
            Class<?> cls = classOrNull(className);
            assertThat(cls).isNotNull();
            Method m = findMethod(cls, methodName);
            assertThat(m)
                    .as("%s method must exist", qualified)
                    .isNotNull();
            assertThat(m.isAnnotationPresent(ConfirmRequired.class))
                    .as("%s must be annotated @ConfirmRequired", qualified)
                    .isTrue();
        }
    }

    @Test
    void read_tools_do_not_have_ConfirmRequired() {
        // 读工具(只看)不应标 @ConfirmRequired,反例 fail-fast 防止误标。
        String[] readTools = {
                "DeviceTool.searchDevices", "DeviceTool.getDeviceDetails",
                "ReservationTool.searchMyReservations",
                "RecommendTool.recommendDevices",
                "AdminTool.queryLabReservations",
                "RagManualTool.searchDeviceManuals"
        };
        for (String qualified : readTools) {
            int dot = qualified.lastIndexOf('.');
            String className = AI_TOOL_PKG + "." + qualified.substring(0, dot);
            String methodName = qualified.substring(dot + 1);
            Class<?> cls = classOrNull(className);
            assertThat(cls).isNotNull();
            Method m = findMethod(cls, methodName);
            assertThat(m).isNotNull();
            assertThat(m.isAnnotationPresent(ConfirmRequired.class))
                    .as("%s must NOT be @ConfirmRequired (read-only)", qualified)
                    .isFalse();
        }
    }

    @Test
    void every_tool_method_has_tool_annotation_and_role_marker() {
        // 每个 @Tool 方法的描述里应有 {roles:X,Y} 标记 — 保证 ToolRegistry 角色解析能跑。
        Set<String> seen = new HashSet<>();
        for (String className : new String[]{
                "DeviceTool", "ReservationTool", "RecommendTool",
                "RepairTool", "AdminTool", "RagManualTool"
        }) {
            Class<?> cls = classOrNull(AI_TOOL_PKG + "." + className);
            assertThat(cls).isNotNull();
            for (Method m : cls.getDeclaredMethods()) {
                Tool t = m.getAnnotation(Tool.class);
                if (t == null) continue;
                seen.add(className + "." + m.getName());
                String desc = t.description();
                assertThat(desc)
                        .as("%s.%s must declare roles marker", className, m.getName())
                        .contains("{roles:");
            }
        }
        assertThat(seen)
                .as("must see at least 10 annotated methods")
                .hasSizeGreaterThanOrEqualTo(10);
    }

    private static Class<?> classOrNull(String name) {
        try {
            return Class.forName(name);
        } catch (ClassNotFoundException e) {
            return null;
        }
    }

    private static Method findMethod(Class<?> cls, String name) {
        for (Method m : cls.getDeclaredMethods()) {
            if (m.getName().equals(name)) return m;
        }
        return null;
    }
}
