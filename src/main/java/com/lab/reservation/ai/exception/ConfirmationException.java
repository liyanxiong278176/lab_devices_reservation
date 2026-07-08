package com.lab.reservation.ai.exception;

import lombok.Getter;

/**
 * 工具确认流程异常 — 由 {@link com.lab.reservation.ai.service.ConfirmationService}
 * 在状态机非法转换或记录缺失时抛出。带 {@link #code} 字段以便上层枚举错误类型。
 *
 * <p>目前使用的 code:
 * <ul>
 *   <li>ACTION_NOT_FOUND — 待操作的 ai_tool_execution 行不存在</li>
 *   <li>INVALID_STATE — 当前 status 不允许目标转换(例:已 executed 再 confirm)</li>
 * </ul>
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Getter
public class ConfirmationException extends RuntimeException {
    private final String code;

    public ConfirmationException(String code, String msg) {
        super(msg);
        this.code = code;
    }
}
