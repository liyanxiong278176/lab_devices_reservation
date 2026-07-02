package com.lab.reservation.service.impl;

import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.dto.reservation.ReservationCreateDTO;
import com.lab.reservation.entity.Device;
import com.lab.reservation.entity.Reservation;
import com.lab.reservation.entity.ReservationItem;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.mapper.DeviceMapper;
import com.lab.reservation.mapper.ReservationItemMapper;
import com.lab.reservation.mapper.ReservationMapper;
import com.lab.reservation.service.ReservationService;
import com.lab.reservation.service.SlotCalculatorService;
import com.lab.reservation.service.SlotKey;
import lombok.RequiredArgsConstructor;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 预约服务实现。本任务仅实现 create（含防超约核心）。
 *
 * 防超约机制：预约 = 1 条 reservation + N 条 reservation_item（每槽一行），
 * reservation_item 上有 UNIQUE(device_id, date, slot_index) 唯一索引。
 * 并发下两个事务抢同一 slot 时，后者的 item 插入命中唯一索引抛 DuplicateKeyException，
 * 此处 catch 转译为 BusinessException(RESERVATION_CONFLICT) 并由 @Transactional 整体回滚。
 * 无需显式行锁，数据库唯一索引即正确性保证。
 */
@Service
@RequiredArgsConstructor
public class ReservationServiceImpl implements ReservationService {

    private final DeviceMapper deviceMapper;
    private final ReservationMapper reservationMapper;
    private final ReservationItemMapper itemMapper;
    private final SlotCalculatorService slotCalculator;

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
        r.setStatus(d.getNeedApproval() != null && d.getNeedApproval() == 1 ? "PENDING" : "APPROVED");
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

        // 通知在 Task14 接入（NotificationService 尚未建），此处暂不调。
        return r.getId();
    }
}
