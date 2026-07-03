package com.lab.reservation.controller;

import com.lab.reservation.common.result.Result;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.RecommendationService;
import com.lab.reservation.vo.recommendation.RecommendationItemVO;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 智能推荐接口（面向任意已登录用户，典型为 STUDENT）。
 */
@Tag(name = "推荐")
@RestController
@RequestMapping("/recommendations")
@RequiredArgsConstructor
public class RecommendationController {

    private static final int DEFAULT_LIMIT = 10;
    private static final int MAX_LIMIT = 50;

    private final RecommendationService recommendationService;

    @Operation(summary = "智能推荐设备（混合启发式打分 + 理由 + 冷启动 + 缓存）")
    @GetMapping
    @PreAuthorize("isAuthenticated()")
    public Result<List<RecommendationItemVO>> recommend(
            @RequestParam(defaultValue = "10") int limit,
            @AuthenticationPrincipal SecurityUserDetails ud) {
        if (limit <= 0) {
            limit = DEFAULT_LIMIT;
        }
        if (limit > MAX_LIMIT) {
            limit = MAX_LIMIT;
        }
        return Result.ok(recommendationService.recommend(ud.getUserId(), limit));
    }
}
