package com.lab.reservation.ai.tool;

import com.lab.reservation.ai.dto.ToolExecutionResult;
import com.lab.reservation.dto.repair.RepairCreateDTO;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.RepairReportService;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 报修相关的 AI 工具（写入操作,均带 {@link ConfirmRequired} 需用户确认）。
 *
 * <p>两类方法：
 * <ul>
 *   <li>{@code submitRepairTicket} — 学生 / 管理员提交设备报修工单;</li>
 *   <li>{@code takeRepairTicket} — 管理员接单 / 领取一个 PENDING 工单。</li>
 * </ul>
 *
 * <p>解决 / 驳回工单语义上接近管理员审批流,留给后续 Task;LLM 当前只暴露写入侧动作。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class RepairTool {

    private final RepairReportService repairReportService;

    /**
     * 提交一条设备报修工单（写入操作,需用户确认）。
     *
     * <p>服务端会校验：设备是否存在（不强校验状态,故障设备也可被报修）。
     * 工单创建后状态 PENDING,通知管理员。
     */
    @Tool(name = "submitRepairTicket",
          description = "为当前登录用户提交一条设备报修工单。设备故障、需维修时使用;"
                  + "工单创建后状态 PENDING,等待管理员接单。{roles:STUDENT,LAB_ADMIN}")
    @ConfirmRequired(
            reason = "将在数据库插入一条报修工单,并通知管理员",
            riskSummary = "工单一经创建不可删除,只能由管理员标记解决 / 驳回",
            estimatedImpact = "repair_report 表插入 1 行"
    )
    public ToolExecutionResult submitRepairTicket(
            @ToolParam(description = "设备 ID(>0)") Long deviceId,
            @ToolParam(description = "报修标题(简述,非空)") String title,
            @ToolParam(description = "详细描述(故障现象/重现步骤)") String description) {

        if (deviceId == null || deviceId <= 0) {
            return ToolExecutionResult.fail("PARAM_INVALID", "deviceId 必须 > 0");
        }
        if (title == null || title.isBlank()) {
            return ToolExecutionResult.fail("PARAM_INVALID", "title 不能为空");
        }
        if (description == null || description.isBlank()) {
            return ToolExecutionResult.fail("PARAM_INVALID", "description 不能为空");
        }

        Long currentUserId = requireCurrentUserId();
        RepairCreateDTO dto = new RepairCreateDTO();
        dto.setDeviceId(deviceId);
        dto.setTitle(title.trim());
        dto.setDescription(description.trim());
        // imageUrls 暂不支持(LLM 当前无法上传截图)

        try {
            Long id = repairReportService.create(dto, currentUserId);
            log.info("submitRepairTicket user={} deviceId={} -> id={}",
                    currentUserId, deviceId, id);
            return ToolExecutionResult.ok(Map.of("ticket_id", id));
        } catch (BusinessException e) {
            log.warn("submitRepairTicket rejected user={} deviceId={}: code={} msg={}",
                    currentUserId, deviceId, e.getCode(), e.getMessage());
            return ToolExecutionResult.fail(String.valueOf(e.getCode()), e.getMessage());
        }
    }

    /**
     * 接单 / 领取一条报修工单（写入操作,需用户确认;管理员权限）。
     *
     * <p>服务端会校验：工单必须 PENDING 状态(已分配工单不能再接);调用方需持有
     * {@code repair:handle} 权限(@PreAuthorize 由 {@link com.lab.reservation.service.impl.RepairReportServiceImpl}
     * 间接保证,因为范围校验涉及自辖 lab)。设备状态联动：take → 设备 MAINTENANCE,
     * 阻塞新预约。
     */
    @Tool(name = "takeRepairTicket",
          description = "管理员接单 / 领取一条 PENDING 状态的报修工单。"
                  + "接单后设备置 MAINTENANCE,阻塞新预约。{roles:LAB_ADMIN,SYS_ADMIN}")
    @ConfirmRequired(
            reason = "将工单领取到当前管理员名下,并将设备置为维护中",
            riskSummary = "只有 PENDING 工单可接;LAB_ADMIN 只能接自辖 lab 的工单",
            estimatedImpact = "repair_report.handler_id 改为当前用户;设备状态 MAINTENANCE"
    )
    public ToolExecutionResult takeRepairTicket(
            @ToolParam(description = "工单 ID(>0)") Long ticketId) {

        if (ticketId == null || ticketId <= 0) {
            return ToolExecutionResult.fail("PARAM_INVALID", "ticketId 必须 > 0");
        }

        SecurityUserDetails user = currentUserOrThrow();
        try {
            repairReportService.take(ticketId, user);
            log.info("takeRepairTicket user={} ticketId={} OK", user.getUserId(), ticketId);
            return ToolExecutionResult.ok(Map.of("taken_ticket_id", ticketId));
        } catch (BusinessException e) {
            log.warn("takeRepairTicket rejected user={} ticketId={}: code={} msg={}",
                    user.getUserId(), ticketId, e.getCode(), e.getMessage());
            return ToolExecutionResult.fail(String.valueOf(e.getCode()), e.getMessage());
        }
    }

    // -------- helpers --------

    private static Long requireCurrentUserId() {
        return currentUserOrThrow().getUserId();
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