package com.lab.reservation.ai.controller;

import com.lab.reservation.ai.dto.WsClientMsg;
import com.lab.reservation.ai.service.AiAssistantService;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.security.ws.WsUserPrincipal;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.messaging.handler.annotation.MessageMapping;
import org.springframework.stereotype.Controller;

import java.security.Principal;

/**
 * AI 助手 STOMP 入口。
 *
 * <p>5 个 @MessageMapping 端点对应 {@link WsClientMsg} 的 5 个 record 子类型;
 * STOMP 转换器按 destination 后缀反序列化到对应 record。
 *
 * <p>不需要 @PreAuthorize — STOMP 握手已在 {@code WsAuthHandshakeInterceptor}
 * 解析 JWT 并注入 {@link WsUserPrincipal};{@code Principal.getName()} == userId。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Slf4j
@Controller
@RequiredArgsConstructor
public class AiAssistantController {

    private final AiAssistantService service;

    @MessageMapping("/app/assistant/send")
    public void onSend(WsClientMsg.UserMessage msg, Principal principal) {
        service.handleUserMessage(toUser(principal), msg.convId(), msg.text());
    }

    @MessageMapping("/app/assistant/confirm")
    public void onConfirm(WsClientMsg.ConfirmAction msg, Principal principal) {
        service.handleConfirm(toUser(principal), msg.actionId());
    }

    @MessageMapping("/app/assistant/cancel")
    public void onCancel(WsClientMsg.CancelAction msg, Principal principal) {
        service.handleCancel(toUser(principal), msg.actionId());
    }

    @MessageMapping("/app/assistant/resync")
    public void onResync(WsClientMsg.Resync msg, Principal principal) {
        service.handleResync(toUser(principal), msg.convId(), msg.lastSeq());
    }

    @MessageMapping("/app/assistant/cancel_session")
    public void onCancelSession(WsClientMsg.CancelSession msg, Principal principal) {
        service.handleCancelSession(toUser(principal), msg.convId());
    }

    private SecurityUserDetails toUser(Principal p) {
        return ((WsUserPrincipal) p).getUser();
    }
}
