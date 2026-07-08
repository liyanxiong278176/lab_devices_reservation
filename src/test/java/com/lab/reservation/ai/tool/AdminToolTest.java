package com.lab.reservation.ai.tool;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.lab.reservation.ai.dto.ToolExecutionResult;
import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.entity.enums.ReservationStatus;
import com.lab.reservation.exception.BusinessException;
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
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * {@link AdminTool#queryLabReservations(Long, String, Integer)} 的单元测试。
 *
 * <p>覆盖：
 * <ul>
 *   <li>正常路径:工具把 status 解析、days clamp 等透传给 service,再把 IPage 转成
 *       {@code {total, items}} 形态;</li>
 *   <li>入参校验:labId 非正数、status 拼写错误、days 越界;</li>
 *   <li>服务端 {@link BusinessException} 透传为 fail 信封。</li>
 * </ul>
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
class AdminToolTest {

    private ReservationService reservationService;
    private AdminTool adminTool;

    @BeforeEach
    void setUp() {
        reservationService = mock(ReservationService.class);
        adminTool = new AdminTool(reservationService);

        // LAB_ADMIN 身份(管理员工具,服务端 @PreAuthorize 也会校验)
        SecurityUserDetails user = new SecurityUserDetails(
                7L, "labadmin", "password", true, "管理员",
                List.of("LAB_ADMIN"), List.of("repair:handle"));
        var auth = new UsernamePasswordAuthenticationToken(user, "password", user.getAuthorities());
        SecurityContextHolder.getContext().setAuthentication(auth);
    }

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
    }

    @Test
    void queryLabReservations_returns_page() {
        IPage<ReservationVO> page = new Page<>(1, 100);
        ReservationVO v1 = new ReservationVO();
        v1.setId(101L);
        v1.setStatus(ReservationStatus.APPROVED.name());
        page.setRecords(new ArrayList<>(List.of(v1)));
        page.setTotal(1L);
        when(reservationService.queryByLab(eq(3L), eq(ReservationStatus.APPROVED), eq(7), any()))
                .thenReturn(page);

        ToolExecutionResult r = adminTool.queryLabReservations(3L, "APPROVED", 7);

        assertThat(r.isOk()).isTrue();
        @SuppressWarnings("unchecked")
        Map<String, Object> data = (Map<String, Object>) r.getData();
        assertThat(data).containsEntry("total", 1L);
        assertThat(data.get("items")).isInstanceOf(List.class);
        @SuppressWarnings("unchecked")
        List<ReservationVO> items = (List<ReservationVO>) data.get("items");
        assertThat(items).hasSize(1);
        assertThat(items.get(0).getId()).isEqualTo(101L);

        ArgumentCaptor<Long> labCaptor = ArgumentCaptor.forClass(Long.class);
        ArgumentCaptor<ReservationStatus> stCaptor = ArgumentCaptor.forClass(ReservationStatus.class);
        ArgumentCaptor<Integer> daysCaptor = ArgumentCaptor.forClass(Integer.class);
        verify(reservationService).queryByLab(labCaptor.capture(), stCaptor.capture(),
                daysCaptor.capture(), any(SecurityUserDetails.class));
        assertThat(labCaptor.getValue()).isEqualTo(3L);
        assertThat(stCaptor.getValue()).isEqualTo(ReservationStatus.APPROVED);
        assertThat(daysCaptor.getValue()).isEqualTo(7);
    }

    @Test
    void queryLabReservations_blank_status_passes_null_to_service() {
        IPage<ReservationVO> page = new Page<>(1, 100);
        page.setRecords(new ArrayList<>());
        page.setTotal(0L);
        when(reservationService.queryByLab(anyLong(), any(), anyInt(), any()))
                .thenReturn(page);

        ToolExecutionResult r = adminTool.queryLabReservations(3L, "   ", 7);

        assertThat(r.isOk()).isTrue();
        ArgumentCaptor<ReservationStatus> stCaptor = ArgumentCaptor.forClass(ReservationStatus.class);
        verify(reservationService).queryByLab(anyLong(), stCaptor.capture(), anyInt(), any());
        assertThat(stCaptor.getValue()).isNull();
    }

    @Test
    void queryLabReservations_invalid_status_string_treated_as_null() {
        IPage<ReservationVO> page = new Page<>(1, 100);
        page.setRecords(new ArrayList<>());
        page.setTotal(0L);
        when(reservationService.queryByLab(anyLong(), any(), anyInt(), any()))
                .thenReturn(page);

        // 与 ReservationTool 行为一致:LLM 拼写错时静默视为 null
        ToolExecutionResult r = adminTool.queryLabReservations(3L, "BOGUS_STATUS", 7);
        assertThat(r.isOk()).isTrue();

        ArgumentCaptor<ReservationStatus> stCaptor = ArgumentCaptor.forClass(ReservationStatus.class);
        verify(reservationService).queryByLab(anyLong(), stCaptor.capture(), anyInt(), any());
        assertThat(stCaptor.getValue()).isNull();
    }

    @Test
    void queryLabReservations_invalid_labId_returns_fail() {
        ToolExecutionResult r = adminTool.queryLabReservations(0L, null, 7);
        assertThat(r.isOk()).isFalse();
        assertThat(r.getCode()).isEqualTo("PARAM_INVALID");
    }

    @Test
    void queryLabReservations_days_clamped_to_default_7() {
        IPage<ReservationVO> page = new Page<>(1, 100);
        page.setRecords(new ArrayList<>());
        page.setTotal(0L);
        when(reservationService.queryByLab(anyLong(), any(), anyInt(), any()))
                .thenReturn(page);

        // days=0 应当被 clamp 到默认 7
        adminTool.queryLabReservations(3L, null, 0);

        ArgumentCaptor<Integer> daysCaptor = ArgumentCaptor.forClass(Integer.class);
        verify(reservationService).queryByLab(anyLong(), any(), daysCaptor.capture(), any());
        assertThat(daysCaptor.getValue()).isEqualTo(7);
    }

    @Test
    void queryLabReservations_days_clamped_to_365() {
        IPage<ReservationVO> page = new Page<>(1, 100);
        page.setRecords(new ArrayList<>());
        page.setTotal(0L);
        when(reservationService.queryByLab(anyLong(), any(), anyInt(), any()))
                .thenReturn(page);

        // days=1000 应当被 clamp 到 365
        adminTool.queryLabReservations(3L, null, 1000);

        ArgumentCaptor<Integer> daysCaptor = ArgumentCaptor.forClass(Integer.class);
        verify(reservationService).queryByLab(anyLong(), any(), daysCaptor.capture(), any());
        assertThat(daysCaptor.getValue()).isEqualTo(365);
    }

    @Test
    void queryLabReservations_business_exception_returns_fail_envelope() {
        // LAB_ADMIN 调了非自辖 lab → FORBIDDEN
        when(reservationService.queryByLab(anyLong(), any(), anyInt(), any()))
                .thenThrow(new BusinessException(ResultCode.FORBIDDEN));

        ToolExecutionResult r = adminTool.queryLabReservations(3L, null, 7);

        assertThat(r.isOk()).isFalse();
        assertThat(r.getCode()).isEqualTo(String.valueOf(ResultCode.FORBIDDEN.getCode()));
    }

    @Test
    void queryLabReservations_no_security_context_throws() {
        SecurityContextHolder.clearContext();
        org.junit.jupiter.api.Assertions.assertThrows(
                IllegalStateException.class,
                () -> adminTool.queryLabReservations(3L, null, 7));
    }
}