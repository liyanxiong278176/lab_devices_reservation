package com.lab.reservation.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.entity.Device;
import com.lab.reservation.entity.Reservation;
import com.lab.reservation.entity.ReservationItem;
import com.lab.reservation.entity.SysUser;
import com.lab.reservation.entity.enums.ReservationStatus;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.mapper.DeviceMapper;
import com.lab.reservation.mapper.ReservationItemMapper;
import com.lab.reservation.mapper.ReservationMapper;
import com.lab.reservation.mapper.SysUserMapper;
import com.lab.reservation.mq.NotificationProducer;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.ApprovalService;
import com.lab.reservation.service.LabScopeHelper;
import com.lab.reservation.vo.approval.ApprovalItemVO;
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
 * 审批服务实现。
 *
 * 范围过滤（§8.6）：管理员看到的待审批预约按其可管辖的设备集合过滤。
 * <ul>
 *   <li>SYS_ADMIN（labIds == null）：不加 device 过滤，全量 PENDING。</li>
 *   <li>LAB_ADMIN（labIds 非空）：先查这些 lab 下的 device_id 集合，
 *       再以此集合过滤 reservation.device_id。若 LAB_ADMIN 未辖任何 lab 或
 *       其辖 lab 下无任何设备 → 返回空页。</li>
 * </ul>
 *
 * reject 时删除该预约的 reservation_item 以释放槽（与 cancel/markNoShow 同语义）。
 * approve 保留槽（预约生效，进入设备日历占用）。
 *
 * 通知接入：approve/reject 时通知预约所属用户（NotificationProducer.notify，异步经 MQ）。
 */
@Service
@RequiredArgsConstructor
public class ApprovalServiceImpl implements ApprovalService {

    private final ReservationMapper reservationMapper;
    private final ReservationItemMapper itemMapper;
    private final DeviceMapper deviceMapper;
    private final SysUserMapper sysUserMapper;
    private final LabScopeHelper labScopeHelper;
    private final NotificationProducer notificationProducer;

    // ============ 列表 ============

    @Override
    public IPage<ApprovalItemVO> pendingList(int page, int size, SecurityUserDetails ud) {
        List<Long> labIds = labScopeHelper.managedLabIds(ud);

        // LAB_ADMIN 未辖任何 lab → 空页
        if (labIds != null && labIds.isEmpty()) {
            return emptyPage(page, size);
        }

        // LAB_ADMIN：先解析出自辖 lab 下的 device_id 集合，作为过滤条件
        Set<Long> scopedDeviceIds = null;
        if (labIds != null) {
            List<Device> devices = deviceMapper.selectList(new LambdaQueryWrapper<Device>()
                    .in(Device::getLabId, labIds));
            scopedDeviceIds = devices.stream().map(Device::getId).collect(Collectors.toSet());
            // 自辖 lab 下无任何设备 → 空页
            if (scopedDeviceIds.isEmpty()) {
                return emptyPage(page, size);
            }
        }

        LambdaQueryWrapper<Reservation> qw = new LambdaQueryWrapper<Reservation>()
                .eq(Reservation::getStatus, ReservationStatus.PENDING.name());
        if (scopedDeviceIds != null) {
            qw.in(Reservation::getDeviceId, scopedDeviceIds);
        }
        // 先到期的先审批（ startTime 升序）；同为到期则按创建时间升序
        qw.orderByAsc(Reservation::getStartTime).orderByAsc(Reservation::getCreatedAt);

        Page<Reservation> p = new Page<>(page, size);
        IPage<Reservation> rp = reservationMapper.selectPage(p, qw);

        if (rp.getRecords().isEmpty()) {
            return rp.convert(r -> new ApprovalItemVO());
        }

        // 批量回填 deviceName / username / realName，避免 N+1
        Set<Long> deviceIds = rp.getRecords().stream()
                .map(Reservation::getDeviceId).collect(Collectors.toSet());
        Set<Long> userIds = rp.getRecords().stream()
                .map(Reservation::getUserId).collect(Collectors.toSet());

        Map<Long, String> deviceNameMap = deviceMapper.selectList(new LambdaQueryWrapper<Device>()
                        .in(Device::getId, deviceIds))
                .stream().collect(Collectors.toMap(Device::getId,
                        d -> d.getName() == null ? "" : d.getName(), (a, b) -> a));
        Map<Long, SysUser> userMap = sysUserMapper.selectList(new LambdaQueryWrapper<SysUser>()
                        .in(SysUser::getId, userIds))
                .stream().collect(Collectors.toMap(SysUser::getId, u -> u, (a, b) -> a));

        return rp.convert(r -> toVO(r, deviceNameMap, userMap));
    }

    // ============ 单条通过/拒绝 ============

    @Override
    @Transactional
    public void approve(Long id, SecurityUserDetails ud) {
        Reservation r = loadOrThrow(id);
        assertInScope(r.getDeviceId(), ud);
        ReservationStatus st = ReservationStatus.valueOf(r.getStatus());
        if (st != ReservationStatus.PENDING) {
            throw new BusinessException(ResultCode.STATUS_TRANSITION_INVALID);
        }

        r.setStatus(ReservationStatus.APPROVED.name());
        r.setApproverId(ud.getUserId());
        r.setApprovedAt(LocalDateTime.now());
        r.setRejectReason(null);
        reservationMapper.updateById(r);
        notificationProducer.notify(r.getUserId(), "APPROVAL", "预约已通过",
                "预约 " + r.getId() + " 已通过审批", r.getId(), "RESERVATION");
    }

    @Override
    @Transactional
    public void reject(Long id, String reason, SecurityUserDetails ud) {
        Reservation r = loadOrThrow(id);
        assertInScope(r.getDeviceId(), ud);
        ReservationStatus st = ReservationStatus.valueOf(r.getStatus());
        if (st != ReservationStatus.PENDING) {
            throw new BusinessException(ResultCode.STATUS_TRANSITION_INVALID);
        }

        r.setStatus(ReservationStatus.REJECTED.name());
        r.setRejectReason(reason);
        r.setApproverId(ud.getUserId());
        reservationMapper.updateById(r);

        // 释放槽：删除该预约占用的所有 reservation_item
        itemMapper.delete(new LambdaQueryWrapper<ReservationItem>()
                .eq(ReservationItem::getReservationId, id));
        notificationProducer.notify(r.getUserId(), "APPROVAL", "预约被拒",
                "原因：" + reason, r.getId(), "RESERVATION");
    }

    // ============ 批量通过 ============

    @Override
    @Transactional
    public void batchApprove(List<Long> ids, SecurityUserDetails ud) {
        if (ids == null || ids.isEmpty()) {
            return;
        }
        // 顺序执行；任一非 PENDING 抛错 → @Transactional 回滚整批
        for (Long id : ids) {
            approve(id, ud);
        }
    }

    // ============ 内部工具 ============

    private Reservation loadOrThrow(Long id) {
        Reservation r = reservationMapper.selectById(id);
        if (r == null) {
            throw new BusinessException(ResultCode.NOT_FOUND);
        }
        return r;
    }

    /**
     * 范围校验：LAB_ADMIN 只能审批自辖 lab 下设备的预约；SYS_ADMIN 不受限。
     * 复用 LabScopeHelper（取 labIds 后比对设备的 labId）。
     */
    private void assertInScope(Long deviceId, SecurityUserDetails ud) {
        if (deviceId == null) {
            // 脏数据：预约无设备关联，拒绝以防绕过范围校验
            throw new BusinessException(ResultCode.FORBIDDEN);
        }
        List<Long> labIds = labScopeHelper.managedLabIds(ud);
        if (labIds == null) {
            // SYS_ADMIN：全量
            return;
        }
        if (labIds.isEmpty()) {
            throw new BusinessException(ResultCode.FORBIDDEN);
        }
        Device d = deviceMapper.selectById(deviceId);
        if (d == null || d.getLabId() == null || !labIds.contains(d.getLabId())) {
            throw new BusinessException(ResultCode.FORBIDDEN);
        }
    }

    private ApprovalItemVO toVO(Reservation r, Map<Long, String> deviceNameMap, Map<Long, SysUser> userMap) {
        ApprovalItemVO vo = new ApprovalItemVO();
        vo.setId(r.getId());
        vo.setUserId(r.getUserId());
        vo.setDeviceId(r.getDeviceId());
        vo.setPurpose(r.getPurpose());
        vo.setStartTime(r.getStartTime());
        vo.setEndTime(r.getEndTime());
        vo.setSlotCount(r.getSlotCount());
        vo.setStatus(r.getStatus());
        vo.setCreatedAt(r.getCreatedAt());
        if (r.getDeviceId() != null) {
            vo.setDeviceName(deviceNameMap.get(r.getDeviceId()));
        }
        SysUser u = userMap.get(r.getUserId());
        if (u != null) {
            vo.setUsername(u.getUsername());
            vo.setRealName(u.getRealName());
        }
        return vo;
    }

    private IPage<ApprovalItemVO> emptyPage(int page, int size) {
        Page<ApprovalItemVO> p = new Page<>(page, size);
        p.setRecords(Collections.emptyList());
        p.setTotal(0);
        return p;
    }
}
