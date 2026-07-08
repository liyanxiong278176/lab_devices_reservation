package com.lab.reservation.ai.tool;

import com.lab.reservation.ai.dto.ToolExecutionResult;
import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.dto.repair.RepairCreateDTO;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.RepairReportService;
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
 * {@link RepairTool} 的单元测试：覆盖 {@code submitRepairTicket} 和 {@code takeRepairTicket}
 * 两个写入工具,以及入参校验和服务端 BusinessException 的转译。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
class RepairToolTest {

    private RepairReportService repairReportService;
    private RepairTool repairTool;

    @BeforeEach
    void setUp() {
        repairReportService = mock(RepairReportService.class);
        repairTool = new RepairTool(repairReportService);

        SecurityUserDetails user = new SecurityUserDetails(
                100L, "alice", "password", true, "Alice",
                List.of("STUDENT"), List.of());
        var auth = new UsernamePasswordAuthenticationToken(user, "password", user.getAuthorities());
        SecurityContextHolder.getContext().setAuthentication(auth);
    }

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
    }

    // ============ submitRepairTicket ============

    @Test
    void submitRepairTicket_happy_path() {
        when(repairReportService.create(any(RepairCreateDTO.class), eq(100L))).thenReturn(555L);

        ToolExecutionResult r = repairTool.submitRepairTicket(
                42L, "示波器无显示", "开机后屏幕全黑,无信号");

        assertThat(r.isOk()).isTrue();
        @SuppressWarnings("unchecked")
        Map<String, Object> data = (Map<String, Object>) r.getData();
        assertThat(data).containsEntry("ticket_id", 555L);

        ArgumentCaptor<RepairCreateDTO> captor = ArgumentCaptor.forClass(RepairCreateDTO.class);
        verify(repairReportService).create(captor.capture(), eq(100L));
        RepairCreateDTO sent = captor.getValue();
        assertThat(sent.getDeviceId()).isEqualTo(42L);
        assertThat(sent.getTitle()).isEqualTo("示波器无显示");
        assertThat(sent.getDescription()).isEqualTo("开机后屏幕全黑,无信号");
        // imageUrls 当前不通过工具传入,服务端 DTO 字段保持 null
        assertThat(sent.getImageUrls()).isNull();
    }

    @Test
    void submitRepairTicket_blank_title_returns_fail() {
        ToolExecutionResult r = repairTool.submitRepairTicket(42L, "  ", "描述");
        assertThat(r.isOk()).isFalse();
        assertThat(r.getCode()).isEqualTo("PARAM_INVALID");
        assertThat(r.getMsg()).contains("title");
    }

    @Test
    void submitRepairTicket_blank_description_returns_fail() {
        ToolExecutionResult r = repairTool.submitRepairTicket(42L, "标题", "");
        assertThat(r.isOk()).isFalse();
        assertThat(r.getCode()).isEqualTo("PARAM_INVALID");
        assertThat(r.getMsg()).contains("description");
    }

    @Test
    void submitRepairTicket_invalid_device_id_returns_fail() {
        ToolExecutionResult r = repairTool.submitRepairTicket(0L, "标题", "描述");
        assertThat(r.isOk()).isFalse();
        assertThat(r.getCode()).isEqualTo("PARAM_INVALID");
    }

    @Test
    void submitRepairTicket_business_exception_returns_fail_envelope() {
        // 设备不存在 → NOT_FOUND
        when(repairReportService.create(any(), anyLong()))
                .thenThrow(new BusinessException(ResultCode.NOT_FOUND));

        ToolExecutionResult r = repairTool.submitRepairTicket(42L, "标题", "描述");

        assertThat(r.isOk()).isFalse();
        assertThat(r.getCode()).isEqualTo(String.valueOf(ResultCode.NOT_FOUND.getCode()));
    }

    // ============ takeRepairTicket ============

    @Test
    void takeRepairTicket_happy_path() {
        doNothing().when(repairReportService).take(eq(555L), any(SecurityUserDetails.class));

        ToolExecutionResult r = repairTool.takeRepairTicket(555L);

        assertThat(r.isOk()).isTrue();
        @SuppressWarnings("unchecked")
        Map<String, Object> data = (Map<String, Object>) r.getData();
        assertThat(data).containsEntry("taken_ticket_id", 555L);

        verify(repairReportService).take(eq(555L), any(SecurityUserDetails.class));
    }

    @Test
    void takeRepairTicket_invalid_ticket_id_returns_fail() {
        ToolExecutionResult r = repairTool.takeRepairTicket(0L);
        assertThat(r.isOk()).isFalse();
        assertThat(r.getCode()).isEqualTo("PARAM_INVALID");
    }

    @Test
    void takeRepairTicket_business_exception_returns_fail_envelope() {
        // 工单已分配 / 非 PENDING → STATUS_TRANSITION_INVALID
        doThrow(new BusinessException(ResultCode.STATUS_TRANSITION_INVALID))
                .when(repairReportService).take(eq(555L), any(SecurityUserDetails.class));

        ToolExecutionResult r = repairTool.takeRepairTicket(555L);

        assertThat(r.isOk()).isFalse();
        assertThat(r.getCode()).isEqualTo(
                String.valueOf(ResultCode.STATUS_TRANSITION_INVALID.getCode()));
    }

    @Test
    void takeRepairTicket_no_security_context_throws() {
        SecurityContextHolder.clearContext();
        org.junit.jupiter.api.Assertions.assertThrows(
                IllegalStateException.class,
                () -> repairTool.takeRepairTicket(1L));
    }
}