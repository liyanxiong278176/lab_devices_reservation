package com.lab.reservation.ai.tool;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.lab.reservation.ai.dto.ToolExecutionResult;
import com.lab.reservation.entity.enums.ReservationStatus;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.ReservationService;
import com.lab.reservation.vo.reservation.ReservationVO;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;

import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ReservationToolTest {

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

    @Test
    void searchMyReservations_calls_service_with_current_user() {
        // given
        IPage<ReservationVO> page = new Page<>(1, 10);
        page.setRecords(new ArrayList<>());
        page.setTotal(0L);
        when(reservationService.myReservations(any(), any(), anyInt(), anyInt()))
                .thenReturn(page);

        // when
        ToolExecutionResult result = reservationTool.searchMyReservations("PENDING", 1, 10);

        // then
        assertThat(result.isOk()).isTrue();

        ArgumentCaptor<Long> userCaptor = ArgumentCaptor.forClass(Long.class);
        ArgumentCaptor<ReservationStatus> statusCaptor = ArgumentCaptor.forClass(ReservationStatus.class);
        verify(reservationService).myReservations(
                userCaptor.capture(), statusCaptor.capture(), eq(1), eq(10));
        assertThat(userCaptor.getValue()).isEqualTo(42L);
        assertThat(statusCaptor.getValue()).isEqualTo(ReservationStatus.PENDING);
    }

    @Test
    void searchMyReservations_blank_status_passes_null_to_service() {
        IPage<ReservationVO> page = new Page<>(1, 10);
        page.setRecords(new ArrayList<>());
        page.setTotal(0L);
        when(reservationService.myReservations(any(), any(), anyInt(), anyInt()))
                .thenReturn(page);

        reservationTool.searchMyReservations("   ", 1, 10);

        ArgumentCaptor<ReservationStatus> statusCaptor = ArgumentCaptor.forClass(ReservationStatus.class);
        verify(reservationService).myReservations(any(), statusCaptor.capture(), anyInt(), anyInt());
        assertThat(statusCaptor.getValue()).isNull();
    }

    @Test
    void searchMyReservations_invalid_status_string_treated_as_null() {
        IPage<ReservationVO> page = new Page<>(1, 10);
        page.setRecords(new ArrayList<>());
        page.setTotal(0L);
        when(reservationService.myReservations(any(), any(), anyInt(), anyInt()))
                .thenReturn(page);

        // 不是合法枚举 — 工具静默视为 null（LLM 大小写写错时不抛错）
        ToolExecutionResult r = reservationTool.searchMyReservations("BOGUS", 1, 10);
        assertThat(r.isOk()).isTrue();
    }

    @Test
    void searchMyReservations_no_security_context_throws() {
        SecurityContextHolder.clearContext();
        org.junit.jupiter.api.Assertions.assertThrows(
                IllegalStateException.class,
                () -> reservationTool.searchMyReservations(null, 1, 10));
    }
}
