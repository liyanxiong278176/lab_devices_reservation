package com.lab.reservation.ai.tool;

import com.lab.reservation.ai.dto.ToolExecutionResult;
import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.dto.reservation.ReservationCreateDTO;
import com.lab.reservation.entity.enums.ReservationStatus;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.ReservationService;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doNothing;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 写操作工具的单元测试：{@code createReservation} 和 {@code cancelReservation}。
 *
 * <p>{@code searchMyReservations} 的测试在 {@link ReservationToolTest} 里。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
class ReservationToolWriteTest {

    private ReservationService reservationService;
    private ReservationTool reservationTool;

    @BeforeEach
    void setUp() {
        reservationService = mock(ReservationService.class);
        reservationTool = new ReservationTool(reservationService);

        SecurityUserDetails user = new SecurityUserDetails(
                42L, "alice", "password", true, "Alice",
                List.of("STUDENT"), List.of());
        var auth = new UsernamePasswordAuthenticationToken(user, "password", user.getAuthorities());
        SecurityContextHolder.getContext().setAuthentication(auth);
    }

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
    }

    // ============ createReservation ============

    @Test
    void createReservation_happy_path() {
        when(reservationService.create(any(ReservationCreateDTO.class), eq(42L))).thenReturn(777L);

        ToolExecutionResult r = reservationTool.createReservation(
                100L, "2026-07-09T09:00:00", "2026-07-09T10:00:00", "实验课");

        assertThat(r.isOk()).isTrue();
        assertThat(r.getData()).isInstanceOf(Map.class);
        @SuppressWarnings("unchecked")
        Map<String, Object> data = (Map<String, Object>) r.getData();
        assertThat(data).containsEntry("reservation_id", 777L);

        ArgumentCaptor<ReservationCreateDTO> captor = ArgumentCaptor.forClass(ReservationCreateDTO.class);
        verify(reservationService).create(captor.capture(), eq(42L));
        ReservationCreateDTO sent = captor.getValue();
        assertThat(sent.getDeviceId()).isEqualTo(100L);
        assertThat(sent.getStartTime()).isEqualTo(java.time.LocalDateTime.parse("2026-07-09T09:00:00"));
        assertThat(sent.getEndTime()).isEqualTo(java.time.LocalDateTime.parse("2026-07-09T10:00:00"));
        assertThat(sent.getPurpose()).isEqualTo("实验课");
    }

    @Test
    void createReservation_blank_purpose_replaced_with_placeholder() {
        when(reservationService.create(any(), anyLong())).thenReturn(1L);

        reservationTool.createReservation(
                100L, "2026-07-09T09:00:00", "2026-07-09T10:00:00", "   ");

        ArgumentCaptor<ReservationCreateDTO> captor = ArgumentCaptor.forClass(ReservationCreateDTO.class);
        verify(reservationService).create(captor.capture(), eq(42L));
        // 服务端 DTO 标了 @NotBlank,空白 purpose 必须替换为非空占位,否则会抛 400
        assertThat(captor.getValue().getPurpose()).isNotBlank();
    }

    @Test
    void createReservation_invalid_device_id_returns_fail() {
        ToolExecutionResult r = reservationTool.createReservation(
                0L, "2026-07-09T09:00:00", "2026-07-09T10:00:00", null);
        assertThat(r.isOk()).isFalse();
        assertThat(r.getCode()).isEqualTo("PARAM_INVALID");
    }

    @Test
    void createReservation_invalid_time_format_returns_fail_envelope() {
        ToolExecutionResult r = reservationTool.createReservation(
                100L, "not-a-time", "2026-07-09T10:00:00", null);
        assertThat(r.isOk()).isFalse();
        assertThat(r.getCode()).isEqualTo("PARAM_INVALID");
        assertThat(r.getMsg()).contains("时间格式错误");
    }

    @Test
    void createReservation_end_before_start_returns_fail_envelope() {
        ToolExecutionResult r = reservationTool.createReservation(
                100L, "2026-07-09T10:00:00", "2026-07-09T09:00:00", null);
        assertThat(r.isOk()).isFalse();
        assertThat(r.getCode()).isEqualTo("PARAM_INVALID");
        assertThat(r.getMsg()).contains("endTime 必须晚于 startTime");
    }

    @Test
    void createReservation_business_exception_returns_fail_envelope() {
        // 时段冲突 / 设备不可用 / 超过最大时长 等都走 BusinessException
        when(reservationService.create(any(), anyLong()))
                .thenThrow(new BusinessException(ResultCode.RESERVATION_CONFLICT));

        ToolExecutionResult r = reservationTool.createReservation(
                100L, "2026-07-09T09:00:00", "2026-07-09T10:00:00", "实验课");

        assertThat(r.isOk()).isFalse();
        assertThat(r.getCode()).isEqualTo(String.valueOf(ResultCode.RESERVATION_CONFLICT.getCode()));
    }

    @Test
    void createReservation_no_security_context_throws() {
        SecurityContextHolder.clearContext();
        org.junit.jupiter.api.Assertions.assertThrows(
                IllegalStateException.class,
                () -> reservationTool.createReservation(
                        100L, "2026-07-09T09:00:00", "2026-07-09T10:00:00", null));
    }

    // ============ cancelReservation ============

    @Test
    void cancelReservation_happy_path() {
        doNothing().when(reservationService).cancel(eq(999L), eq(42L));

        ToolExecutionResult r = reservationTool.cancelReservation(999L);

        assertThat(r.isOk()).isTrue();
        assertThat(r.getData()).isInstanceOf(Map.class);
        @SuppressWarnings("unchecked")
        Map<String, Object> data = (Map<String, Object>) r.getData();
        assertThat(data).containsEntry("cancelled_id", 999L);

        verify(reservationService).cancel(999L, 42L);
    }

    @Test
    void cancelReservation_invalid_id_returns_fail_envelope() {
        ToolExecutionResult r = reservationTool.cancelReservation(0L);
        assertThat(r.isOk()).isFalse();
        assertThat(r.getCode()).isEqualTo("PARAM_INVALID");
    }

    @Test
    void cancelReservation_business_exception_returns_fail_envelope() {
        // 已被取消 / 已开始 / 不属于本人 等都抛 BusinessException
        doThrow(new BusinessException(ResultCode.STATUS_TRANSITION_INVALID))
                .when(reservationService).cancel(eq(999L), eq(42L));

        ToolExecutionResult r = reservationTool.cancelReservation(999L);

        assertThat(r.isOk()).isFalse();
        assertThat(r.getCode()).isEqualTo(
                String.valueOf(ResultCode.STATUS_TRANSITION_INVALID.getCode()));
    }

    @Test
    void cancelReservation_no_security_context_throws() {
        SecurityContextHolder.clearContext();
        org.junit.jupiter.api.Assertions.assertThrows(
                IllegalStateException.class,
                () -> reservationTool.cancelReservation(1L));
    }
}