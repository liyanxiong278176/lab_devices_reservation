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

import java.util.HashMap;
import java.util.Map;

/**
 * 管理员相关 AI 工具（只读）。
 *
 * <p>{@link #queryLabReservations} 包装 {@link ReservationService#queryByLab} —
 * 后者由 {@code @PreAuthorize} 限制为 LAB_ADMIN / SYS_ADMIN,且 LAB_ADMIN 还需
 * 校验自辖 lab（{@link com.lab.reservation.service.LabScopeHelper}）。学生身份
 * 调到该工具会被 Spring Security 直接拒绝,所以工具层不再做角色过滤。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class AdminTool {

    private final ReservationService reservationService;

    /**
     * 管理员按实验室 ID 查询最近 N 天的预约。
     *
     * <p>参数语义：
     * <ul>
     *   <li>{@code labId} 必填,目标实验室 ID;</li>
     *   <li>{@code status} 可空;传大小写枚举名(PENDING/APPROVED/IN_USE/COMPLETED /
     *       CANCELLED / VIOLATED / NO_SHOW);非空字符串但拼错则静默忽略(等价"全部"),
     *       与 {@code searchMyReservations} 保持一致;</li>
     *   <li>{@code days} 范围 1-365;非法值(<1 或 >365)自动 clamp 到 [1, 365]。</li>
     * </ul>
     */
    @Tool(name = "queryLabReservations",
          description = "管理员按实验室 ID 查询最近 N 天的预约。status 可选,空表示全部状态;"
                  + "days 范围 1-365,非法值自动 clamp。"
                  + "{roles:LAB_ADMIN,SYS_ADMIN}")
    public ToolExecutionResult queryLabReservations(
            @ToolParam(description = "实验室 ID(>0)") Long labId,
            @ToolParam(description = "状态过滤,大写枚举名,可空") String status,
            @ToolParam(description = "最近 N 天(1-365,默认 7)") Integer days) {

        if (labId == null || labId <= 0) {
            return ToolExecutionResult.fail("PARAM_INVALID", "labId 必须 > 0");
        }

        int actualDays = (days == null || days <= 0) ? 7 : Math.min(days, 365);
        ReservationStatus statusEnum = parseStatus(status);

        SecurityUserDetails user = currentUserOrThrow();
        try {
            IPage<ReservationVO> page = reservationService.queryByLab(
                    labId, statusEnum, actualDays, user);
            log.info("queryLabReservations user={} labId={} status={} days={} total={}",
                    user.getUserId(), labId, statusEnum, actualDays, page.getTotal());

            // 工具返回结构与 raw IPage 解耦:total + records 列表,LLM 解析友好
            Map<String, Object> data = new HashMap<>();
            data.put("total", page.getTotal());
            data.put("items", page.getRecords());
            return ToolExecutionResult.ok(data);
        } catch (BusinessException e) {
            log.warn("queryLabReservations rejected user={} labId={}: code={} msg={}",
                    user.getUserId(), labId, e.getCode(), e.getMessage());
            return ToolExecutionResult.fail(String.valueOf(e.getCode()), e.getMessage());
        }
    }

    // -------- helpers --------

    private static ReservationStatus parseStatus(String s) {
        if (s == null || s.isBlank()) return null;
        try {
            return ReservationStatus.valueOf(s.trim().toUpperCase());
        } catch (IllegalArgumentException e) {
            return null; // 与 ReservationTool.parseStatus 一致:静默忽略 LLM 拼写错误
        }
    }

    private static SecurityUserDetails currentUserOrThrow() {
        var auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth == null || !auth.isAuthenticated()) {
            throw new IllegalStateException("未登录 — AI 入口未注入 SecurityContext");
        }
        Object p = auth.getPrincipal();
        if (!(p instanceof SecurityUserDetails u)) {
            throw new IllegalStateException("principal 类型非 SecurityUserDetails: "
                    + (p == null ? "null" : p.getClass().getName()));
        }
        return u;
    }
}