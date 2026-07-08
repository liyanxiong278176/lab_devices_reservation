package com.lab.reservation.ai.tool;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.lab.reservation.ai.dto.ToolExecutionResult;
import com.lab.reservation.dto.reservation.ReservationCreateDTO;
import com.lab.reservation.entity.enums.ReservationStatus;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.ReservationService;
import com.lab.reservation.vo.reservation.ReservationVO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;

import java.time.LocalDateTime;
import java.time.format.DateTimeParseException;
import java.util.Map;

/**
 * 预约相关的 AI 工具。
 *
 * <p>Task 3b.i:只读 {@code searchMyReservations};Task 3b.ii 引入写操作
 * {@code createReservation} 和 {@code cancelReservation}，两者带
 * {@link ConfirmRequired} 注解要求用户二次确认。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class ReservationTool {

    private final ReservationService reservationService;

    /**
     * 查询"我"的预约（按状态过滤、按创建时间倒序分页）。
     */
    @Tool(name = "searchMyReservations",
          description = "查询我的预约记录,可按状态过滤(PENDING/APPROVED/IN_USE/COMPLETED/CANCELLED 等),"
                  + "按创建时间倒序分页。{roles:STUDENT,LAB_ADMIN,SYS_ADMIN}")
    public ToolExecutionResult searchMyReservations(
            @ToolParam(description = "状态过滤,大写枚举名;为空则查全部") String status,
            @ToolParam(description = "页码(>=1)") Integer page,
            @ToolParam(description = "每页大小(>=1)") Integer size) {

        // status 必填但允许空字符串(null/blank 当作"全部");page/size 必填且 > 0
        if (page == null || page < 1) {
            return ToolExecutionResult.fail("PARAM_INVALID", "page 必须 >= 1");
        }
        if (size == null || size < 1) {
            return ToolExecutionResult.fail("PARAM_INVALID", "size 必须 >= 1");
        }

        Long currentUserId = requireCurrentUserId();
        ReservationStatus st = parseStatus(status);

        try {
            IPage<ReservationVO> result = reservationService.myReservations(
                    currentUserId, st, page, size);
            log.info("searchMyReservations user={} status={} page={} size={} total={}",
                    currentUserId, st, page, size, result.getTotal());
            return ToolExecutionResult.ok(result);
        } catch (BusinessException e) {
            return ToolExecutionResult.fail(String.valueOf(e.getCode()), e.getMessage());
        }
    }

    /**
     * 创建设备预约（写入操作,需用户确认）。
     *
     * <p>服务端会校验：设备是否存在 / 时段冲突 / 设备是否需要审批(自动审批 → APPROVED,否则 PENDING)
     * / 单次时长上限(取 device.max_reservation_hours)。被拒绝时抛 BusinessException
     * (RESERVATION_CONFLICT / DEVICE_UNAVAILABLE / SLOT_NOT_ALIGNED / EXCEED_MAX_DURATION)。
     *
     * <p>时间字符串必须为 ISO-8601 本地时间(无时区),形如 {@code "2026-07-09T09:00:00"}。
     */
    @Tool(name = "createReservation",
          description = "为当前登录用户创建设备预约。deviceId/startTime/endTime 必填;purpose 可空。"
                  + "时段冲突 / 设备 MAINTENANCE / 超过最大预约时长 / 起止时间未对齐 15 分钟"
                  + "都会被服务端拒绝。需审批设备返回 PENDING,免审批返回 APPROVED。"
                  + "{roles:STUDENT,LAB_ADMIN}")
    @ConfirmRequired(
            reason = "将在数据库插入一条预约记录",
            riskSummary = "时段冲突 / 设备维护中 / 超过最大可预约时长 都会被服务端拒绝",
            estimatedImpact = "reservation 表插入 1 行 + reservation_item 插入 N 行(按 15 分钟槽位)"
    )
    public ToolExecutionResult createReservation(
            @ToolParam(description = "设备 ID(>0)") Long deviceId,
            @ToolParam(description = "起始时间,ISO-8601 本地时间 yyyy-MM-ddTHH:mm:ss") String startTime,
            @ToolParam(description = "结束时间,ISO-8601 本地时间 yyyy-MM-ddTHH:mm:ss") String endTime,
            @ToolParam(description = "用途/备注,可空") String purpose) {

        if (deviceId == null || deviceId <= 0) {
            return ToolExecutionResult.fail("PARAM_INVALID", "deviceId 必须 > 0");
        }
        if (startTime == null || startTime.isBlank()) {
            return ToolExecutionResult.fail("PARAM_INVALID", "startTime 不能为空");
        }
        if (endTime == null || endTime.isBlank()) {
            return ToolExecutionResult.fail("PARAM_INVALID", "endTime 不能为空");
        }

        LocalDateTime start;
        LocalDateTime end;
        try {
            start = LocalDateTime.parse(startTime.trim());
            end = LocalDateTime.parse(endTime.trim());
        } catch (DateTimeParseException e) {
            return ToolExecutionResult.fail("PARAM_INVALID",
                    "时间格式错误,需 ISO-8601 yyyy-MM-ddTHH:mm:ss: " + e.getMessage());
        }
        if (!end.isAfter(start)) {
            return ToolExecutionResult.fail("PARAM_INVALID", "endTime 必须晚于 startTime");
        }

        Long currentUserId = requireCurrentUserId();
        ReservationCreateDTO dto = new ReservationCreateDTO();
        dto.setDeviceId(deviceId);
        dto.setStartTime(start);
        dto.setEndTime(end);
        // purpose 可空;服务端 DTO 标了 @NotBlank,但 ReservationServiceImpl.create 不读
        // 该字段 — 仅用于通知文本生成。这里用空白字符串占位,服务端不依赖。
        dto.setPurpose(purpose == null || purpose.isBlank() ? "(无)" : purpose.trim());

        try {
            Long id = reservationService.create(dto, currentUserId);
            log.info("createReservation user={} deviceId={} start={} end={} -> id={}",
                    currentUserId, deviceId, start, end, id);
            return ToolExecutionResult.ok(Map.of("reservation_id", id));
        } catch (BusinessException e) {
            log.warn("createReservation rejected user={} deviceId={}: code={} msg={}",
                    currentUserId, deviceId, e.getCode(), e.getMessage());
            return ToolExecutionResult.fail(String.valueOf(e.getCode()), e.getMessage());
        }
    }

    /**
     * 取消当前用户的一条预约（写入操作,需用户确认）。
     *
     * <p>限制（服务端校验）：仅本人可取消;状态须 PENDING/APPROVED;且当前时间须早于 startTime
     * （已开始 / 已签到 / 已完成的不可取消）。被拒绝时抛 BusinessException
     * (FORBIDDEN / STATUS_TRANSITION_INVALID / NOT_FOUND)。
     */
    @Tool(name = "cancelReservation",
          description = "取消当前登录用户的一条预约。须 PENDING 或 APPROVED 状态且尚未开始;"
                  + "已开始(IN_USE/COMPLETED)不可取消。{roles:STUDENT,LAB_ADMIN}")
    @ConfirmRequired(
            reason = "将取消一条已存在的预约",
            riskSummary = "仅本人可取消;已开始(IN_USE/COMPLETED)的预约不可取消",
            estimatedImpact = "reservation.status 改为 CANCELLED,释放占用的所有 slot"
    )
    public ToolExecutionResult cancelReservation(
            @ToolParam(description = "预约 ID(>0)") Long reservationId) {

        if (reservationId == null || reservationId <= 0) {
            return ToolExecutionResult.fail("PARAM_INVALID", "reservationId 必须 > 0");
        }

        Long currentUserId = requireCurrentUserId();
        try {
            reservationService.cancel(reservationId, currentUserId);
            log.info("cancelReservation user={} id={} OK", currentUserId, reservationId);
            return ToolExecutionResult.ok(Map.of("cancelled_id", reservationId));
        } catch (BusinessException e) {
            log.warn("cancelReservation rejected user={} id={}: code={} msg={}",
                    currentUserId, reservationId, e.getCode(), e.getMessage());
            return ToolExecutionResult.fail(String.valueOf(e.getCode()), e.getMessage());
        }
    }

    // -------- helpers --------

    private static Long requireCurrentUserId() {
        var auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth == null || !auth.isAuthenticated()) {
            throw new IllegalStateException("未登录 — AI 入口未注入 SecurityContext");
        }
        Object p = auth.getPrincipal();
        if (!(p instanceof SecurityUserDetails u)) {
            throw new IllegalStateException("principal 类型非 SecurityUserDetails: "
                    + (p == null ? "null" : p.getClass().getName()));
        }
        return u.getUserId();
    }

    private static ReservationStatus parseStatus(String s) {
        if (s == null || s.isBlank()) return null;
        try {
            return ReservationStatus.valueOf(s.trim().toUpperCase());
        } catch (IllegalArgumentException e) {
            return null; // 静默忽略,LLM 可能给错大小写或拼写;等价于"全部"
        }
    }
}
