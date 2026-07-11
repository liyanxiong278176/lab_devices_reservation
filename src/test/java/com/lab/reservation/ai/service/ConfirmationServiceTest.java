package com.lab.reservation.ai.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.lab.reservation.ai.exception.ConfirmationException;
import com.lab.reservation.entity.AiConversation;
import com.lab.reservation.entity.AiToolExecution;
import com.lab.reservation.mapper.AiToolExecutionMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ConfirmationServiceTest {

    private AiToolExecutionMapper mapper;
    private ConversationService conversationService;
    private ConfirmationService svc;

    @BeforeEach
    void setUp() {
        mapper = mock(AiToolExecutionMapper.class);
        conversationService = mock(ConversationService.class);
        svc = new ConfirmationService(mapper, new ObjectMapper(), conversationService);
    }

    @Test
    void create_writes_pending_status() {
        when(mapper.insert(any(AiToolExecution.class))).thenAnswer(inv -> {
            AiToolExecution e = inv.getArgument(0);
            e.setId(42L);
            return 1;
        });

        Long id = svc.create(1L, 2L, "createReservation", Map.of("deviceId", 5L));

        assertThat(id).isEqualTo(42L);
        ArgumentCaptor<AiToolExecution> cap = ArgumentCaptor.forClass(AiToolExecution.class);
        verify(mapper).insert(cap.capture());
        assertThat(cap.getValue().getStatus()).isEqualTo(ConfirmationService.STATUS_PENDING);
        assertThat(cap.getValue().getToolName()).isEqualTo("createReservation");
        assertThat(cap.getValue().getArguments()).contains("deviceId");
        assertThat(cap.getValue().getConversationId()).isEqualTo(1L);
        assertThat(cap.getValue().getMessageId()).isEqualTo(2L);
    }

    @Test
    void confirm_transitions_pending_to_confirmed() {
        AiToolExecution e = newPending(1L);
        when(mapper.selectById(1L)).thenReturn(e);

        svc.confirm(1L);

        assertThat(e.getStatus()).isEqualTo(ConfirmationService.STATUS_CONFIRMED);
        assertThat(e.getUserConfirmedAt()).isNotNull();
        verify(mapper).updateById(e);
    }

    @Test
    void confirm_throws_when_action_missing() {
        when(mapper.selectById(99L)).thenReturn(null);

        assertThatThrownBy(() -> svc.confirm(99L))
                .isInstanceOf(ConfirmationException.class)
                .extracting("code").isEqualTo("ACTION_NOT_FOUND");
    }

    @Test
    void confirm_throws_when_status_not_pending() {
        AiToolExecution e = newPending(1L);
        e.setStatus(ConfirmationService.STATUS_CONFIRMED);
        when(mapper.selectById(1L)).thenReturn(e);

        assertThatThrownBy(() -> svc.confirm(1L))
                .isInstanceOf(ConfirmationException.class)
                .extracting("code").isEqualTo("INVALID_STATE");
    }

    @Test
    void execute_transitions_confirmed_to_executed() {
        AiToolExecution e = newPending(1L);
        e.setStatus(ConfirmationService.STATUS_CONFIRMED);
        when(mapper.selectById(1L)).thenReturn(e);

        svc.execute(1L, Map.of("reservation_id", 99L));

        assertThat(e.getStatus()).isEqualTo(ConfirmationService.STATUS_EXECUTED);
        assertThat(e.getResult()).contains("reservation_id");
        assertThat(e.getExecutedAt()).isNotNull();
    }

    @Test
    void cancel_is_idempotent_on_non_pending() {
        AiToolExecution e = newPending(1L);
        e.setStatus(ConfirmationService.STATUS_EXECUTED);
        when(mapper.selectById(1L)).thenReturn(e);

        svc.cancel(1L);

        assertThat(e.getStatus()).isEqualTo(ConfirmationService.STATUS_EXECUTED);
        verify(mapper, never()).updateById(any());
    }

    @Test
    void cancel_transitions_pending_to_cancelled() {
        AiToolExecution e = newPending(1L);
        when(mapper.selectById(1L)).thenReturn(e);

        svc.cancel(1L);

        assertThat(e.getStatus()).isEqualTo(ConfirmationService.STATUS_CANCELLED);
        verify(mapper).updateById(e);
    }

    @Test
    void error_writes_error_message() {
        AiToolExecution e = newPending(1L);
        when(mapper.selectById(1L)).thenReturn(e);

        svc.error(1L, "RESERVATION_CONFLICT");

        assertThat(e.getStatus()).isEqualTo(ConfirmationService.STATUS_ERROR);
        assertThat(e.getErrorMessage()).isEqualTo("RESERVATION_CONFLICT");
        assertThat(e.getExecutedAt()).isNotNull();
    }

    @Test
    void error_silently_skips_missing_record() {
        when(mapper.selectById(99L)).thenReturn(null);

        // Should not throw
        svc.error(99L, "any");

        verify(mapper, never()).updateById(any());
    }

    @Test
    void expireOldPending_only_affects_old_pending() {
        AiToolExecution old = newPending(1L);
        old.setCreatedAt(java.time.LocalDateTime.now().minusMinutes(10));
        when(mapper.selectList(any())).thenReturn(java.util.List.of(old));

        int n = svc.expireOldPending(5);

        assertThat(n).isEqualTo(1);
        assertThat(old.getStatus()).isEqualTo(ConfirmationService.STATUS_EXPIRED);
        assertThat(old.getErrorMessage()).isEqualTo("PENDING_TIMEOUT");
        verify(mapper).updateById(old);
    }

    @Test
    void confirmAndLoad_returns_null_when_not_owner() {
        AiToolExecution row = pendingRow(77L, 1L);
        AiConversation conv = new AiConversation();
        conv.setUserId(1L);
        when(mapper.selectById(77L)).thenReturn(row);
        when(conversationService.getOrThrow(1L)).thenReturn(conv);

        AiToolExecution got = svc.confirmAndLoad(77L, 999L);

        assertThat(got).isNull();
        verify(mapper, never()).updateById(any());
    }

    @Test
    void confirmAndLoad_confirms_when_owner() {
        AiToolExecution row = pendingRow(77L, 1L);
        AiConversation conv = new AiConversation();
        conv.setUserId(1L);
        when(mapper.selectById(77L)).thenReturn(row);
        when(conversationService.getOrThrow(1L)).thenReturn(conv);

        AiToolExecution got = svc.confirmAndLoad(77L, 1L);

        assertThat(got).isNotNull();
        assertThat(got.getStatus()).isEqualTo(ConfirmationService.STATUS_CONFIRMED);
    }

    private AiToolExecution pendingRow(Long id, Long convId) {
        AiToolExecution e = new AiToolExecution();
        e.setId(id);
        e.setConversationId(convId);
        e.setStatus(ConfirmationService.STATUS_PENDING);
        e.setToolName("createReservation");
        e.setArguments("{}");
        return e;
    }

    private AiToolExecution newPending(Long id) {
        AiToolExecution e = new AiToolExecution();
        e.setId(id);
        e.setConversationId(1L);
        e.setMessageId(2L);
        e.setToolName("test_tool");
        e.setStatus(ConfirmationService.STATUS_PENDING);
        e.setArguments("{}");
        e.setCreatedAt(java.time.LocalDateTime.now());
        return e;
    }
}
