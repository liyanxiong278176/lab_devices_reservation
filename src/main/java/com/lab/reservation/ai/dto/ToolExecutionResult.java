package com.lab.reservation.ai.dto;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * 工具调用的返回信封,刻意与 common.result.Result 区分:
 * AI 工具调用失败不应该触发全局业务异常,因为可能源于 LLM 编造参数或权限不足,
 * 而非业务侧逻辑错误。
 *
 * <p>与 {@code com.lab.reservation.common.result.Result} 形态对齐但放在 ai 包内,
 * 因为 Tool 调用失败的处理策略和业务 API 略有差异(工具失败一般只记日志,
 * 由 LLM 决定是否重试或改换工具)。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class ToolExecutionResult {

    /** 是否成功 */
    private boolean ok;
    /** 业务错误码,SUCCESS 表示成功 */
    private String code;
    /** 中文错误描述 */
    private String msg;
    /** 任意返回数据(Map / List / POJO) */
    private Object data;

    public static ToolExecutionResult ok(Object data) {
        return new ToolExecutionResult(true, "SUCCESS", "成功", data);
    }

    public static ToolExecutionResult fail(String code, String msg) {
        return new ToolExecutionResult(false, code, msg, null);
    }
}