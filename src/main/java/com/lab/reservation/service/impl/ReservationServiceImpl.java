package com.lab.reservation.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.dto.reservation.ReservationCreateDTO;
import com.lab.reservation.entity.Device;
import com.lab.reservation.entity.Reservation;
import com.lab.reservation.entity.ReservationItem;
import com.lab.reservation.entity.enums.ReservationStatus;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.mapper.DeviceMapper;
import com.lab.reservation.mapper.ReservationItemMapper;
import com.lab.reservation.mapper.ReservationMapper;
import com.lab.reservation.mq.NotificationProducer;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.ReservationLock;
import com.lab.reservation.service.ReservationService;
import com.lab.reservation.service.SlotCalculatorService;
import com.lab.reservation.service.SlotKey;
import com.lab.reservation.vo.reservation.ReservationVO;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 预约服务实现。
 *
 * 防超约机制：预约 = 1 条 reservation + N 条 reservation_item（每槽一行），
 * reservation_item 上有 UNIQUE(device_id, date, slot_index) 唯一索引。
 * 并发下两个事务抢同一 slot 时，后者的 item 插入命中唯一索引抛 DuplicateKeyException，
 * 此处 catch 转译为 BusinessException(RESERVATION_CONFLICT) 并由 @Transactional 整体回滚。
 * 无需显式行锁，数据库唯一索引即正确性保证。
 *
 * 生命周期状态机（§6.3，状态用 {@link ReservationStatus} 枚举统一，不再硬编码字符串）：
 * <pre>
 * PENDING/APPROVED --cancel(start前)--> CANCELLED
 * APPROVED --checkIn(在时间窗)--> IN_USE  (device -> IN_USE)
 * IN_USE  --checkOut--> COMPLETED          (device -> IDLE, item 释放)
 * APPROVED/IN_USE --markViolated--> VIOLATED (device IN_USE -> IDLE)
 * APPROVED --markNoShow--> NO_SHOW         (device IN_USE -> IDLE)
 * </pre>
 */
@Service
@RequiredArgsConstructor
public class ReservationServiceImpl implements ReservationService {

    private final DeviceMapper deviceMapper;
    private final ReservationMapper reservationMapper;
    private final ReservationItemMapper itemMapper;
    private final SlotCalculatorService slotCalculator;
    private final NotificationProducer notificationProducer;
    private final ReservationLock reservationLock;

    /** 签到宽限分钟（now 早于 startTime − grace 视为未到时间）。默认 0。 */
    @Value("${lab.slot.check-in-grace-minutes:0}")
    private long graceMinutes;

    // ============ 创建 ============

    @Override
    @Transactional
    public Long create(ReservationCreateDTO dto, Long currentUserId) {
        Device d = deviceMapper.selectById(dto.getDeviceId());
        if (d == null || "MAINTENANCE".equals(d.getStatus())) {
            throw new BusinessException(ResultCode.DEVICE_UNAVAILABLE);
        }
        if (!dto.getStartTime().isBefore(dto.getEndTime())) {
            throw new BusinessException(ResultCode.SLOT_NOT_ALIGNED);
        }
        if (dto.getStartTime().isBefore(LocalDateTime.now())) {
            throw new BusinessException(ResultCode.PARAM_INVALID);
        }

        List<SlotKey> slots = slotCalculator.compute(d.getId(), dto.getStartTime(), dto.getEndTime());
        // max_reservation_hours → 槽上限，按 15 分钟槽粒度向下取整
        int maxSlots = (int) Math.floor(d.getMaxReservationHours().doubleValue() * 60.0 / 15.0);
        if (slots.size() > maxSlots) {
            throw new BusinessException(ResultCode.EXCEED_MAX_DURATION);
        }

        Reservation r = new Reservation();
        r.setUserId(currentUserId);
        r.setDeviceId(d.getId());
        r.setPurpose(dto.getPurpose());
        r.setStartTime(dto.getStartTime());
        r.setEndTime(dto.getEndTime());
        r.setSlotCount(slots.size());
        r.setStatus(d.getNeedApproval() != null && d.getNeedApproval() == 1
                ? ReservationStatus.PENDING.name()
                : ReservationStatus.APPROVED.name());

        // 双层防线：Redis 分布式锁串行化同 (deviceId,date) 的并发预约；
        // 锁内仍保留 DB 唯一索引兜底（fail-open 或锁异常时仍正确）。
        Set<LocalDate> dates = slots.stream().map(SlotKey::date).collect(Collectors.toSet());
        try (var ignored = reservationLock.acquire(dto.getDeviceId(), dates)) {
            reservationMapper.insert(r);
            try {
                for (SlotKey s : slots) {
                    ReservationItem it = new ReservationItem();
                    it.setReservationId(r.getId());
                    it.setDeviceId(s.deviceId());
                    it.setDate(s.date());
                    it.setSlotIndex(s.slotIndex());
                    itemMapper.insert(it);
                }
            } catch (DuplicateKeyException e) {
                // 唯一索引命中：该 slot 已被占用（并发或与既有预约冲突）→ 业务冲突
                throw new BusinessException(ResultCode.RESERVATION_CONFLICT);
            }
        }

        // 通知：自动审批 → 预约成功；需审批 → 已提交待审批
        ReservationStatus finalStatus = ReservationStatus.valueOf(r.getStatus());
        String title = finalStatus == ReservationStatus.APPROVED ? "预约成功" : "预约已提交，待审批";
        String content = "设备：" + (d.getName() == null ? d.getId() : d.getName())
                + "，时段：" + r.getStartTime() + " ~ " + r.getEndTime();
        notificationProducer.notify(currentUserId, "RESERVATION", title, content, r.getId(), "RESERVATION");
        return r.getId();
    }

    // ============ 生命周期 ============

    @Override
    @Transactional
    public void cancel(Long id, Long currentUserId) {
        Reservation r = loadOrThrow(id);
        // 归属校验：仅本人可取消（admin 取消留给后续）
        if (!r.getUserId().equals(currentUserId)) {
            throw new BusinessException(ResultCode.FORBIDDEN);
        }
        // 状态校验：PENDING/APPROVED；且须在开始前取消
        ReservationStatus st = ReservationStatus.valueOf(r.getStatus());
        if (st != ReservationStatus.PENDING && st != ReservationStatus.APPROVED) {
            throw new BusinessException(ResultCode.STATUS_TRANSITION_INVALID);
        }
        if (!LocalDateTime.now().isBefore(r.getStartTime())) {
            throw new BusinessException(ResultCode.STATUS_TRANSITION_INVALID);
        }

        r.setStatus(ReservationStatus.CANCELLED.name());
        reservationMapper.updateById(r);
        // 释放槽：删除该预约占用的所有 reservation_item
        itemMapper.delete(new LambdaQueryWrapper<ReservationItem>()
                .eq(ReservationItem::getReservationId, id));
        notificationProducer.notify(currentUserId, "RESERVATION", "预约已取消",
                "预约 " + id + " 已取消", id, "RESERVATION");
    }

    @Override
    @Transactional
    public void checkIn(Long id, SecurityUserDetails ud) {
        Reservation r = loadOrThrow(id);
        assertOwnerOrApprover(r, ud);
        ReservationStatus st = ReservationStatus.valueOf(r.getStatus());
        if (st != ReservationStatus.APPROVED) {
            throw new BusinessException(ResultCode.STATUS_TRANSITION_INVALID);
        }
        LocalDateTime now = LocalDateTime.now();
        LocalDateTime earliest = r.getStartTime().minusMinutes(graceMinutes);
        if (now.isBefore(earliest) || now.isAfter(r.getEndTime())) {
            throw new BusinessException(ResultCode.STATUS_TRANSITION_INVALID);
        }

        r.setStatus(ReservationStatus.IN_USE.name());
        r.setCheckInAt(now);
        reservationMapper.updateById(r);

        Device d = deviceMapper.selectById(r.getDeviceId());
        if (d != null && !"IN_USE".equals(d.getStatus())) {
            d.setStatus("IN_USE");
            deviceMapper.updateById(d);
        }
        notificationProducer.notify(r.getUserId(), "RESERVATION", "已签到",
                "预约 " + r.getId() + " 已签到", r.getId(), "RESERVATION");
    }

    @Override
    @Transactional
    public void checkOut(Long id, SecurityUserDetails ud) {
        Reservation r = loadOrThrow(id);
        assertOwnerOrApprover(r, ud);
        ReservationStatus st = ReservationStatus.valueOf(r.getStatus());
        if (st != ReservationStatus.IN_USE) {
            throw new BusinessException(ResultCode.STATUS_TRANSITION_INVALID);
        }

        r.setStatus(ReservationStatus.COMPLETED.name());
        r.setCheckOutAt(LocalDateTime.now());
        reservationMapper.updateById(r);

        releaseDevice(r.getDeviceId());
        // 归还即清理该预约占用的所有槽（含过期未清理的）
        itemMapper.delete(new LambdaQueryWrapper<ReservationItem>()
                .eq(ReservationItem::getReservationId, id));
        notificationProducer.notify(r.getUserId(), "RESERVATION", "已归还，预约完成",
                "预约 " + r.getId() + " 已归还", r.getId(), "RESERVATION");
    }

    @Override
    @Transactional
    public void markViolated(Long id) {
        Reservation r = loadOrThrow(id);
        ReservationStatus st = ReservationStatus.valueOf(r.getStatus());
        if (st != ReservationStatus.APPROVED && st != ReservationStatus.IN_USE) {
            throw new BusinessException(ResultCode.STATUS_TRANSITION_INVALID);
        }

        r.setStatus(ReservationStatus.VIOLATED.name());
        reservationMapper.updateById(r);

        releaseDevice(r.getDeviceId());
        itemMapper.delete(new LambdaQueryWrapper<ReservationItem>()
                .eq(ReservationItem::getReservationId, id));
    }

    @Override
    @Transactional
    public void markNoShow(Long id) {
        Reservation r = loadOrThrow(id);
        ReservationStatus st = ReservationStatus.valueOf(r.getStatus());
        if (st != ReservationStatus.APPROVED) {
            throw new BusinessException(ResultCode.STATUS_TRANSITION_INVALID);
        }

        r.setStatus(ReservationStatus.NO_SHOW.name());
        reservationMapper.updateById(r);

        releaseDevice(r.getDeviceId());
        itemMapper.delete(new LambdaQueryWrapper<ReservationItem>()
                .eq(ReservationItem::getReservationId, id));
    }

    // ============ 查询 ============

    @Override
    public IPage<ReservationVO> myReservations(Long currentUserId, ReservationStatus status, int page, int size) {
        Page<Reservation> p = new Page<>(page, size);
        LambdaQueryWrapper<Reservation> qw = new LambdaQueryWrapper<Reservation>()
                .eq(Reservation::getUserId, currentUserId);
        if (status != null) {
            qw.eq(Reservation::getStatus, status.name());
        }
        qw.orderByDesc(Reservation::getCreatedAt);

        IPage<Reservation> rp = reservationMapper.selectPage(p, qw);
        return rp.convert(this::toVO);
    }

    @Override
    public ReservationVO detail(Long id, SecurityUserDetails ud) {
        Reservation r = loadOrThrow(id);
        // 权限：本人，或持有 device:approve 的管理员（审批代查），或 SYS_ADMIN
        boolean isOwner = ud != null && ud.getUserId() != null && ud.getUserId().equals(r.getUserId());
        boolean isApprover = ud != null && ud.getAuthorities() != null && ud.getAuthorities().stream()
                .map(GrantedAuthority::getAuthority)
                .anyMatch("device:approve"::equals);
        if (!isOwner && !isApprover) {
            throw new BusinessException(ResultCode.FORBIDDEN);
        }
        return toVO(r);
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
     * 归属校验：允许本人，或持有 device:approve 的管理员（LAB_ADMIN/SYS_ADMIN 代操作）。
     * 否则抛 FORBIDDEN。checkIn/checkOut 共用。
     */
    private void assertOwnerOrApprover(Reservation r, SecurityUserDetails ud) {
        if (ud == null) {
            throw new BusinessException(ResultCode.FORBIDDEN);
        }
        boolean isOwner = ud.getUserId() != null && ud.getUserId().equals(r.getUserId());
        boolean isApprover = ud.getAuthorities() != null && ud.getAuthorities().stream()
                .map(GrantedAuthority::getAuthority)
                .anyMatch("device:approve"::equals);
        if (!isOwner && !isApprover) {
            throw new BusinessException(ResultCode.FORBIDDEN);
        }
    }

    /**
     * 释放设备：若当前 IN_USE 则置 IDLE。幂等（非 IN_USE 不动）。
     * 违规/爽约/归还均共用此逻辑。
     */
    private void releaseDevice(Long deviceId) {
        Device d = deviceMapper.selectById(deviceId);
        if (d != null && "IN_USE".equals(d.getStatus())) {
            d.setStatus("IDLE");
            deviceMapper.updateById(d);
        }
    }

    private ReservationVO toVO(Reservation r) {
        ReservationVO vo = new ReservationVO();
        vo.setId(r.getId());
        vo.setUserId(r.getUserId());
        vo.setDeviceId(r.getDeviceId());
        vo.setPurpose(r.getPurpose());
        vo.setStartTime(r.getStartTime());
        vo.setEndTime(r.getEndTime());
        vo.setSlotCount(r.getSlotCount());
        vo.setStatus(r.getStatus());
        vo.setCreatedAt(r.getCreatedAt());
        return vo;
    }
}
