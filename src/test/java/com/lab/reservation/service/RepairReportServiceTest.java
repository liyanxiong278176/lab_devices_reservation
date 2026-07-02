package com.lab.reservation.service;

import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.entity.Device;
import com.lab.reservation.entity.RepairReport;
import com.lab.reservation.entity.enums.DeviceStatus;
import com.lab.reservation.entity.enums.RepairStatus;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.mapper.DeviceMapper;
import com.lab.reservation.mapper.RepairReportMapper;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.impl.RepairReportServiceImpl;
import com.lab.reservation.dto.repair.RepairHandleDTO;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.authority.SimpleGrantedAuthority;

import java.util.List;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

/**
 * 报修最小版 TDD 测试（mock mapper，纯单测，不起 Spring 容器）。
 *
 * 核心断言：报修状态机（PENDING → PROCESSING → RESOLVED / REJECTED）与设备状态联动：
 * <pre>
 * take(PENDING)   -> PROCESSING, device -> MAINTENANCE
 * resolve(PROCESSING) -> RESOLVED, device -> IDLE
 * reject(PENDING) -> REJECTED, device 不变
 * </pre>
 * 联动后 ReservationService.create 的 status != MAINTENANCE 校验即可拒绝故障设备的预约。
 */
@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class RepairReportServiceTest {

    @Mock private RepairReportMapper repairReportMapper;
    @Mock private DeviceMapper deviceMapper;
    @Mock private LabScopeHelper labScopeHelper;

    @InjectMocks
    private RepairReportServiceImpl service;

    private static final long REPORT_ID = 10L;
    private static final long DEVICE_ID = 7L;
    private static final long HANDLER_ID = 99L;

    // ---------- 工具 ----------

    private RepairReport report(RepairStatus status) {
        RepairReport r = new RepairReport();
        r.setId(REPORT_ID);
        r.setDeviceId(DEVICE_ID);
        r.setStatus(status.name());
        return r;
    }

    private Device device(DeviceStatus status) {
        Device d = new Device();
        d.setId(DEVICE_ID);
        d.setStatus(status.name());
        return d;
    }

    /** SYS_ADMIN：labScopeHelper 返回 null（不受范围限制）。 */
    private SecurityUserDetails sysAdmin() {
        SecurityUserDetails ud = mock(SecurityUserDetails.class);
        when(ud.getUserId()).thenReturn(HANDLER_ID);
        when(ud.getAuthorities()).thenReturn(List.<GrantedAuthority>of());
        when(labScopeHelper.managedLabIds(ud)).thenReturn(null);
        return ud;
    }

    // ---------- take ----------

    @Test
    void take_pending_sets_device_maintenance() {
        RepairReport r = report(RepairStatus.PENDING);
        Device d = device(DeviceStatus.IDLE);
        when(repairReportMapper.selectById(REPORT_ID)).thenReturn(r);
        when(deviceMapper.selectById(DEVICE_ID)).thenReturn(d);

        service.take(REPORT_ID, sysAdmin());

        ArgumentCaptor<RepairReport> rc = ArgumentCaptor.forClass(RepairReport.class);
        verify(repairReportMapper).updateById(rc.capture());
        assertEquals(RepairStatus.PROCESSING.name(), rc.getValue().getStatus());
        assertEquals(HANDLER_ID, rc.getValue().getHandlerId());

        ArgumentCaptor<Device> dc = ArgumentCaptor.forClass(Device.class);
        verify(deviceMapper).updateById(dc.capture());
        assertEquals(DeviceStatus.MAINTENANCE.name(), dc.getValue().getStatus());
    }

    @Test
    void take_not_pending_rejected() {
        // 已 RESOLVED 的报修不能被 take
        RepairReport r = report(RepairStatus.RESOLVED);
        when(repairReportMapper.selectById(REPORT_ID)).thenReturn(r);

        BusinessException e = assertThrows(BusinessException.class,
                () -> service.take(REPORT_ID, sysAdmin()));
        assertEquals(ResultCode.STATUS_TRANSITION_INVALID.getCode(), e.getCode());
        verify(deviceMapper, never()).updateById(any());
    }

    // ---------- resolve ----------

    @Test
    void resolve_processing_sets_device_idle() {
        RepairReport r = report(RepairStatus.PROCESSING);
        Device d = device(DeviceStatus.MAINTENANCE);
        when(repairReportMapper.selectById(REPORT_ID)).thenReturn(r);
        when(deviceMapper.selectById(DEVICE_ID)).thenReturn(d);

        RepairHandleDTO dto = new RepairHandleDTO();
        dto.setResolutionNote("校准完成");
        service.resolve(REPORT_ID, dto, sysAdmin());

        ArgumentCaptor<RepairReport> rc = ArgumentCaptor.forClass(RepairReport.class);
        verify(repairReportMapper).updateById(rc.capture());
        assertEquals(RepairStatus.RESOLVED.name(), rc.getValue().getStatus());
        assertEquals("校准完成", rc.getValue().getResolutionNote());
        assertNotNull(rc.getValue().getResolvedAt());

        ArgumentCaptor<Device> dc = ArgumentCaptor.forClass(Device.class);
        verify(deviceMapper).updateById(dc.capture());
        assertEquals(DeviceStatus.IDLE.name(), dc.getValue().getStatus());
    }

    @Test
    void resolve_not_processing_rejected() {
        // PENDING 报修必须先 take 才能 resolve
        RepairReport r = report(RepairStatus.PENDING);
        when(repairReportMapper.selectById(REPORT_ID)).thenReturn(r);

        RepairHandleDTO dto = new RepairHandleDTO();
        dto.setResolutionNote("x");
        BusinessException e = assertThrows(BusinessException.class,
                () -> service.resolve(REPORT_ID, dto, sysAdmin()));
        assertEquals(ResultCode.STATUS_TRANSITION_INVALID.getCode(), e.getCode());
        verify(deviceMapper, never()).updateById(any());
    }

    // ---------- reject ----------

    @Test
    void reject_pending_device_unchanged() {
        RepairReport r = report(RepairStatus.PENDING);
        when(repairReportMapper.selectById(REPORT_ID)).thenReturn(r);

        RepairHandleDTO dto = new RepairHandleDTO();
        dto.setResolutionNote("非真实故障");
        service.reject(REPORT_ID, dto, sysAdmin());

        ArgumentCaptor<RepairReport> rc = ArgumentCaptor.forClass(RepairReport.class);
        verify(repairReportMapper).updateById(rc.capture());
        assertEquals(RepairStatus.REJECTED.name(), rc.getValue().getStatus());
        assertEquals("非真实故障", rc.getValue().getResolutionNote());

        // 设备状态不被改动（reject 为非真实故障，不影响设备可用性）
        verify(deviceMapper, never()).updateById(any());
    }
}
