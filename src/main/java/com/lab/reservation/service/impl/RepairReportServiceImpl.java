package com.lab.reservation.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.dto.repair.RepairCreateDTO;
import com.lab.reservation.dto.repair.RepairHandleDTO;
import com.lab.reservation.entity.Device;
import com.lab.reservation.entity.RepairReport;
import com.lab.reservation.entity.SysUser;
import com.lab.reservation.entity.enums.DeviceStatus;
import com.lab.reservation.entity.enums.RepairStatus;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.mapper.DeviceMapper;
import com.lab.reservation.mapper.RepairReportMapper;
import com.lab.reservation.mapper.SysUserMapper;
import com.lab.reservation.mq.NotificationProducer;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.LabScopeHelper;
import com.lab.reservation.service.RepairReportService;
import com.lab.reservation.vo.repair.RepairReportVO;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.Collections;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 报修服务实现（最小版）。规格 §6.4 / §8.9。
 *
 * 设备状态联动（与 {@link com.lab.reservation.service.impl.ReservationServiceImpl#create}
 * 的 MAINTENANCE 校验形成闭环）：
 * <ul>
 *   <li>take(PENDING)：报修 → PROCESSING，设备 → MAINTENANCE。此后该设备新预约被
 *       ReservationService.create 拒绝（DEVICE_UNAVAILABLE）。</li>
 *   <li>resolve(PROCESSING)：报修 → RESOLVED，设备 → IDLE，恢复可预约。</li>
 *   <li>reject(PENDING)：报修 → REJECTED，设备不变（非真实故障，不影响可用性）。</li>
 * </ul>
 *
 * 范围隔离（LAB_ADMIN 仅处理自辖 lab 下设备的报修；SYS_ADMIN 全量）复用
 * {@link LabScopeHelper}，与 ApprovalServiceImpl 同语义。
 */
@Service
@RequiredArgsConstructor
public class RepairReportServiceImpl implements RepairReportService {

    private final RepairReportMapper repairReportMapper;
    private final DeviceMapper deviceMapper;
    private final SysUserMapper sysUserMapper;
    private final LabScopeHelper labScopeHelper;
    private final NotificationProducer notificationProducer;

    // ============ 创建 ============

    @Override
    @Transactional
    public Long create(RepairCreateDTO dto, Long userId) {
        // 设备须存在（不强校验状态：故障设备也可被报修，且 IDLE/IN_USE 均允许）
        Device d = deviceMapper.selectById(dto.getDeviceId());
        if (d == null) {
            throw new BusinessException(ResultCode.NOT_FOUND);
        }
        RepairReport r = new RepairReport();
        r.setDeviceId(d.getId());
        r.setReporterId(userId);
        r.setTitle(dto.getTitle());
        r.setDescription(dto.getDescription());
        r.setImageUrls(dto.getImageUrls());
        r.setStatus(RepairStatus.PENDING.name());
        repairReportMapper.insert(r);
        return r.getId();
    }

    // ============ 查询 ============

    @Override
    public IPage<RepairReportVO> mine(Long userId, int page, int size) {
        Page<RepairReport> p = new Page<>(page, size);
        LambdaQueryWrapper<RepairReport> qw = new LambdaQueryWrapper<RepairReport>()
                .eq(RepairReport::getReporterId, userId)
                .orderByDesc(RepairReport::getCreatedAt);
        IPage<RepairReport> rp = repairReportMapper.selectPage(p, qw);
        return rp.convert(this::toVO);
    }

    @Override
    public IPage<RepairReportVO> list(RepairStatus status, int page, int size, SecurityUserDetails ud) {
        List<Long> labIds = labScopeHelper.managedLabIds(ud);

        // LAB_ADMIN 未辖任何 lab → 空页
        if (labIds != null && labIds.isEmpty()) {
            return emptyPage(page, size);
        }

        // LAB_ADMIN：先解析自辖 lab 下的 device_id 集合，作为过滤条件
        Set<Long> scopedDeviceIds = null;
        if (labIds != null) {
            List<Device> devices = deviceMapper.selectList(new LambdaQueryWrapper<Device>()
                    .in(Device::getLabId, labIds));
            scopedDeviceIds = devices.stream().map(Device::getId).collect(Collectors.toSet());
            if (scopedDeviceIds.isEmpty()) {
                return emptyPage(page, size);
            }
        }

        LambdaQueryWrapper<RepairReport> qw = new LambdaQueryWrapper<RepairReport>();
        if (status != null) {
            qw.eq(RepairReport::getStatus, status.name());
        }
        if (scopedDeviceIds != null) {
            qw.in(RepairReport::getDeviceId, scopedDeviceIds);
        }
        qw.orderByDesc(RepairReport::getCreatedAt);

        Page<RepairReport> p = new Page<>(page, size);
        IPage<RepairReport> rp = repairReportMapper.selectPage(p, qw);

        if (rp.getRecords().isEmpty()) {
            return rp.convert(r -> new RepairReportVO());
        }

        // 批量回填 deviceName / reporterName，避免 N+1
        Set<Long> deviceIds = rp.getRecords().stream()
                .map(RepairReport::getDeviceId).collect(Collectors.toSet());
        Set<Long> userIds = rp.getRecords().stream()
                .map(RepairReport::getReporterId).filter(java.util.Objects::nonNull)
                .collect(Collectors.toSet());
        Map<Long, String> deviceNameMap = deviceMapper.selectList(new LambdaQueryWrapper<Device>()
                        .in(Device::getId, deviceIds))
                .stream().collect(Collectors.toMap(Device::getId,
                        d -> d.getName() == null ? "" : d.getName(), (a, b) -> a));
        Map<Long, SysUser> userMap = userIds.isEmpty() ? Collections.emptyMap()
                : sysUserMapper.selectList(new LambdaQueryWrapper<SysUser>().in(SysUser::getId, userIds))
                .stream().collect(Collectors.toMap(SysUser::getId, u -> u, (a, b) -> a));

        return rp.convert(r -> toVO(r, deviceNameMap, userMap));
    }

    // ============ 状态机 ============

    @Override
    @Transactional
    public void take(Long id, SecurityUserDetails ud) {
        RepairReport r = loadOrThrow(id);
        assertInScope(r.getDeviceId(), ud);
        RepairStatus st = RepairStatus.valueOf(r.getStatus());
        if (st != RepairStatus.PENDING) {
            throw new BusinessException(ResultCode.STATUS_TRANSITION_INVALID);
        }
        r.setStatus(RepairStatus.PROCESSING.name());
        r.setHandlerId(ud.getUserId());
        repairReportMapper.updateById(r);

        // 设备联动：置 MAINTENANCE（take 不校验设备当前状态，即使 IN_USE 也覆盖；
        // 进行中预约由管理员手动 cancel+通知，阶段1 不自动取消）
        Device d = deviceMapper.selectById(r.getDeviceId());
        if (d != null) {
            d.setStatus(DeviceStatus.MAINTENANCE.name());
            deviceMapper.updateById(d);
        }
        notificationProducer.notify(r.getReporterId(), "REPAIR", "报修已受理",
                "报修 " + r.getId() + " 已受理", r.getId(), "REPAIR");
    }

    @Override
    @Transactional
    public void resolve(Long id, RepairHandleDTO dto, SecurityUserDetails ud) {
        RepairReport r = loadOrThrow(id);
        assertInScope(r.getDeviceId(), ud);
        RepairStatus st = RepairStatus.valueOf(r.getStatus());
        if (st != RepairStatus.PROCESSING) {
            throw new BusinessException(ResultCode.STATUS_TRANSITION_INVALID);
        }
        r.setStatus(RepairStatus.RESOLVED.name());
        r.setResolutionNote(dto.getResolutionNote());
        r.setResolvedAt(LocalDateTime.now());
        repairReportMapper.updateById(r);

        // 设备联动：置回 IDLE，恢复可预约
        Device d = deviceMapper.selectById(r.getDeviceId());
        if (d != null) {
            d.setStatus(DeviceStatus.IDLE.name());
            deviceMapper.updateById(d);
        }
        notificationProducer.notify(r.getReporterId(), "REPAIR", "报修已解决",
                dto.getResolutionNote(), r.getId(), "REPAIR");
    }

    @Override
    @Transactional
    public void reject(Long id, RepairHandleDTO dto, SecurityUserDetails ud) {
        RepairReport r = loadOrThrow(id);
        assertInScope(r.getDeviceId(), ud);
        RepairStatus st = RepairStatus.valueOf(r.getStatus());
        if (st != RepairStatus.PENDING) {
            throw new BusinessException(ResultCode.STATUS_TRANSITION_INVALID);
        }
        r.setStatus(RepairStatus.REJECTED.name());
        r.setResolutionNote(dto.getResolutionNote());
        repairReportMapper.updateById(r);
        // 设备状态不变（非真实故障）
        notificationProducer.notify(r.getReporterId(), "REPAIR", "报修已驳回",
                dto.getResolutionNote(), r.getId(), "REPAIR");
    }

    // ============ 内部工具 ============

    private RepairReport loadOrThrow(Long id) {
        RepairReport r = repairReportMapper.selectById(id);
        if (r == null) {
            throw new BusinessException(ResultCode.NOT_FOUND);
        }
        return r;
    }

    /**
     * 范围校验：LAB_ADMIN 只能处理自辖 lab 下设备的报修；SYS_ADMIN 不受限。
     * 与 ApprovalServiceImpl.assertInScope 同语义。
     */
    private void assertInScope(Long deviceId, SecurityUserDetails ud) {
        if (deviceId == null) {
            throw new BusinessException(ResultCode.FORBIDDEN);
        }
        List<Long> labIds = labScopeHelper.managedLabIds(ud);
        if (labIds == null) {
            return; // SYS_ADMIN：全量
        }
        if (labIds.isEmpty()) {
            throw new BusinessException(ResultCode.FORBIDDEN);
        }
        Device d = deviceMapper.selectById(deviceId);
        if (d == null || d.getLabId() == null || !labIds.contains(d.getLabId())) {
            throw new BusinessException(ResultCode.FORBIDDEN);
        }
    }

    private RepairReportVO toVO(RepairReport r) {
        return toVO(r, Collections.emptyMap(), Collections.emptyMap());
    }

    private RepairReportVO toVO(RepairReport r, Map<Long, String> deviceNameMap, Map<Long, SysUser> userMap) {
        RepairReportVO vo = new RepairReportVO();
        vo.setId(r.getId());
        vo.setDeviceId(r.getDeviceId());
        vo.setReporterId(r.getReporterId());
        vo.setTitle(r.getTitle());
        vo.setDescription(r.getDescription());
        vo.setImageUrls(r.getImageUrls());
        vo.setStatus(r.getStatus());
        vo.setHandlerId(r.getHandlerId());
        vo.setResolutionNote(r.getResolutionNote());
        vo.setCreatedAt(r.getCreatedAt());
        vo.setResolvedAt(r.getResolvedAt());
        if (r.getDeviceId() != null) {
            vo.setDeviceName(deviceNameMap.get(r.getDeviceId()));
        }
        SysUser u = userMap.get(r.getReporterId());
        if (u != null) {
            vo.setReporterName(u.getRealName());
        }
        return vo;
    }

    private IPage<RepairReportVO> emptyPage(int page, int size) {
        Page<RepairReportVO> p = new Page<>(page, size);
        p.setRecords(Collections.emptyList());
        p.setTotal(0);
        return p;
    }
}
