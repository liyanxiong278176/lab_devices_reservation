package com.lab.reservation.ai.exception;

import lombok.Getter;

/**
 * 工具调用参数校验失败时抛出。
 *
 * <p>被 GlobalExceptionHandler / ToolExecutionService 捕获,转成 Result.fail(code, msg)
 * 返回给调用方,LLM 据此重试或提示用户。code 字段是稳定的、可被前端/客户端枚举的
 * 错误码,msg 是面向开发者/用户的可读消息。
 *
 * <p>目前使用的 code:
 * <ul>
 *   <li>MISSING_FIELD — 必填字段缺失</li>
 *   <li>PARAM_INVALID — 字段存在但值不合法(空白/非正数等)</li>
 * </ul>
 */
@Getter
public class ToolArgumentException extends RuntimeException {
    private final String code;

    public ToolArgumentException(String code, String msg) {
        super(msg);
        this.code = code;
    }
}
