package com.lab.reservation.ai.tool;

import com.lab.reservation.ai.dto.ToolExecutionResult;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.RecommendationService;
import com.lab.reservation.vo.recommendation.RecommendationItemVO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 设备推荐 AI 工具。
 *
 * <p>基于 {@link RecommendationService} 的混合启发式打分（类目/实验室亲和 + 热门度 +
 * 标签匹配 - 已约扣分），并附带可解释理由。
 *
 * <p>按 plan B-new-1：<b>不</b>接收 {@code purpose} 参数；历史预约画像已隐含在
 * RecommendationService 的 userId 维度统计中。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Slf4j
@Component
@RequiredArgsConstructor
public class RecommendTool {

    private final RecommendationService recommendationService;
    private final ToolArgumentValidator validator;

    @Tool(name = "recommendDevices",
          description = "为当前登录用户推荐设备(基于其历史预约画像 + 全局热门度),"
                  + "返回的每项带可解释理由 reason。{roles:STUDENT,LAB_ADMIN,SYS_ADMIN}")
    public ToolExecutionResult recommendDevices(
            @ToolParam(description = "返回条数(>0,默认 10)") Integer topN) {

        Map<String, Object> args = new HashMap<>();
        args.put("topN", topN);
        validator.validate("RecommendTool.recommendDevices", args);

        Long currentUserId = requireCurrentUserId();

        try {
            List<RecommendationItemVO> result = recommendationService.recommend(currentUserId, topN);
            log.info("recommendDevices user={} topN={} hits={}",
                    currentUserId, topN, result == null ? 0 : result.size());
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
}
