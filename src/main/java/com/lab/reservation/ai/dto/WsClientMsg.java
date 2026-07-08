package com.lab.reservation.ai.dto;

/**
 * 客户端发往 /app/assistant/* 的消息 union。
 *
 * <p>sealed interface + 5 个 record,Jackson + Spring Messaging 自动反序列化到
 * 对应 record(STOMP 转换器看到 {@code "type"} 字段后 dispatch,这里简化为
 * 多 endpoint 路由,所以用 Jackson 默认的多态/类型解析)。
 */
public sealed interface WsClientMsg {

    /** 普通对话消息;convId 为 null 表示新建会话。 */
    record UserMessage(Long convId, String text) implements WsClientMsg {}

    /** 确认执行某个待确认动作(由 confirmation_required 帧触发)。 */
    record ConfirmAction(Long actionId) implements WsClientMsg {}

    /** 取消某个待确认动作。 */
    record CancelAction(Long actionId) implements WsClientMsg {}

    /** 客户端断线重连后按 lastSeq 重新拉取历史帧。 */
    record Resync(Long convId, Long lastSeq) implements WsClientMsg {}

    /** 取消当前正在进行的流式生成(设置 cancel flag)。 */
    record CancelSession(Long convId) implements WsClientMsg {}
}
