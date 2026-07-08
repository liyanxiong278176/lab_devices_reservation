package com.lab.reservation.ai.tool;

import com.lab.reservation.ai.exception.ToolArgumentException;
import org.junit.jupiter.api.Test;
import org.springframework.ai.tool.annotation.ToolParam;

import java.lang.reflect.Method;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class ToolArgumentValidatorTest {

    @Test
    void missing_field_throws_missing_field_code() throws Exception {
        ToolArgumentValidator v = new ToolArgumentValidator();
        v.register("Demo.echo", DemoTool.class.getDeclaredMethod("echo", Long.class, String.class));

        assertThatThrownBy(() -> v.validate("Demo.echo", Map.of("deviceId", 1L)))
                .isInstanceOf(ToolArgumentException.class)
                .extracting("code").isEqualTo("MISSING_FIELD");
    }

    @Test
    void blank_string_throws_param_invalid() throws Exception {
        ToolArgumentValidator v = new ToolArgumentValidator();
        v.register("Demo.echo", DemoTool.class.getDeclaredMethod("echo", Long.class, String.class));

        assertThatThrownBy(() -> v.validate("Demo.echo",
                Map.of("deviceId", 1L, "name", "   ")))
                .isInstanceOf(ToolArgumentException.class)
                .extracting("code").isEqualTo("PARAM_INVALID");
    }

    @Test
    void non_positive_long_throws_param_invalid() throws Exception {
        ToolArgumentValidator v = new ToolArgumentValidator();
        v.register("Demo.echo", DemoTool.class.getDeclaredMethod("echo", Long.class, String.class));

        assertThatThrownBy(() -> v.validate("Demo.echo",
                Map.of("deviceId", -1L, "name", "x")))
                .isInstanceOf(ToolArgumentException.class)
                .extracting("code").isEqualTo("PARAM_INVALID");
    }

    @Test
    void unregistered_method_id_passes_through() {
        ToolArgumentValidator v = new ToolArgumentValidator();
        // 未注册,不抛异常
        assertThatCode(() -> v.validate("Unknown.method", Map.of("foo", "bar"))).doesNotThrowAnyException();
    }

    @Test
    void valid_args_pass_through_without_throw() throws Exception {
        ToolArgumentValidator v = new ToolArgumentValidator();
        v.register("Demo.echo", DemoTool.class.getDeclaredMethod("echo", Long.class, String.class));

        assertThatCode(() -> v.validate("Demo.echo",
                Map.of("deviceId", 5L, "name", "ok"))).doesNotThrowAnyException();
    }

    /** 给测试用的反射目标。 */
    static class DemoTool {
        public String echo(
                @ToolParam(description = "设备 ID") Long deviceId,
                @ToolParam(description = "设备名") String name) {
            return deviceId + ":" + name;
        }
    }
}
