package com.lab.reservation.service;

import com.lab.reservation.dto.reservation.ReservationCreateDTO;
import com.lab.reservation.dto.reservation.ReservationQueryDTO;
import com.lab.reservation.entity.enums.ReservationStatus;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.vo.reservation.ReservationVO;
import com.baomidou.mybatisplus.core.metadata.IPage;

/**
 * 预约服务。
 *
 * 创建（含防超约）+ 生命周期状态机（cancel/checkIn/checkOut/markViolated/markNoShow）
 * + 查询（myReservations/detail）。状态机规格见 §6.3。
 */
public interface ReservationService {

    /**
     * 创建预约。并发下若同一设备同一 slot 已被占用，抛 BusinessException(RESERVATION_CONFLICT)。
     *
     * @return 新建预约 id
     */
    Long create(ReservationCreateDTO dto, Long currentUserId);

    /**
     * 取消预约（仅本人；状态须 PENDING/APPROVED 且未到开始时间）。
     */
    void cancel(Long id, Long currentUserId);

    /**
     * 签到（状态须 APPROVED 且 now ∈ [startTime − grace, endTime]）。
     * 归属校验：仅本人或持有 device:approve（管理员代操作）。
     */
    void checkIn(Long id, SecurityUserDetails ud);

    /**
     * 归还（状态须 IN_USE）。
     * 归属校验：仅本人或持有 device:approve（管理员代操作）。
     */
    void checkOut(Long id, SecurityUserDetails ud);

    /**
     * 标记违规（管理员；状态须 APPROVED/IN_USE）。
     */
    void markViolated(Long id);

    /**
     * 标记爽约（管理员；状态须 APPROVED）。
     */
    void markNoShow(Long id);

    /**
     * 我的预约（按 userId 过滤，可叠加 status，按创建时间倒序分页）。
     */
    IPage<ReservationVO> myReservations(Long currentUserId, ReservationStatus status, int page, int size);

    /**
     * 预约详情（本人或 SYS_ADMIN）。
     */
    ReservationVO detail(Long id, Long currentUserId);
}
