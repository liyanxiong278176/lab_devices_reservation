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
     * 超时未签到自动取消（延迟队列触发；标记 CANCELLED + TIMEOUT 原因，释放槽）。
     */
    void markTimeoutCancelled(Long id);

    /**
     * 我的预约（按 userId 过滤，可叠加 status，按创建时间倒序分页）。
     */
    IPage<ReservationVO> myReservations(Long currentUserId, ReservationStatus status, int page, int size);

    /**
     * 按实验室查询预约（管理员 / 实验室负责人）。
     *
     * <p>服务端通过 {@code @PreAuthorize} 限制调用方角色；LAB_ADMIN 还需通过
     * {@link com.lab.reservation.service.LabScopeHelper} 校验自辖范围,SYS_ADMIN 全局可见。
     * labId 必传;status 可空(为空则全部状态);days 范围 [1, 365],超过按 365 截断并 clamp。
     *
     * <p>实现细节:预约行本身不带 lab_id(只通过 device_id 间接关联),所以会先取该 lab 下
     * 全部 device.id,再对 reservation 做 device_id IN (...) 过滤;最后按 start_time 倒序分页。
     *
     * @param labId  实验室 ID
     * @param status 状态过滤(null = 全部)
     * @param days   最近 N 天
     * @param ud     当前用户 — 必须是 LAB_ADMIN 或 SYS_ADMIN;否则被 @PreAuthorize 拒绝
     * @return 预约列表(按开始时间倒序)
     */
    IPage<ReservationVO> queryByLab(Long labId, ReservationStatus status, int days, SecurityUserDetails ud);

    /**
     * 预约详情（本人，或持有 device:approve 的管理员代查，或 SYS_ADMIN）。
     */
    ReservationVO detail(Long id, SecurityUserDetails ud);
}
