package com.lab.reservation.service;

import com.lab.reservation.dto.reservation.ReservationCreateDTO;

/**
 * 预约服务。本任务仅实现 create（含防超约）；生命周期（cancel/checkIn 等）在 Task10 接入。
 */
public interface ReservationService {

    /**
     * 创建预约。并发下若同一设备同一 slot 已被占用，抛 BusinessException(RESERVATION_CONFLICT)。
     *
     * @return 新建预约 id
     */
    Long create(ReservationCreateDTO dto, Long currentUserId);
}
