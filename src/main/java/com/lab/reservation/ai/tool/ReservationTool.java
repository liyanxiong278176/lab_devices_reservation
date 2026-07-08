package com.lab.reservation.ai.tool;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.lab.reservation.ai.dto.ToolExecutionResult;
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

import java.util.Map;

/**
 * 预约相关的 AI 工具（只读部分）。
 *
 * <p>本任务只实现 {@code searchMyReservations} — 写操作（创建 / 取消）由 Task 3b.ii 引入，
 * 会带 {@link ConfirmRequired} 注解要求用户二次确认。
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
     *
     * <p>用户身份从 {@link SecurityContextHolder} 取 — Task 5 / 3b.ii
     * 的 AI 调用入口会先注入再 invoke tool 方法,所以这里强制非空。
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
