package com.lab.reservation.controller;

import com.lab.reservation.common.result.Result;
import com.lab.reservation.dto.reservation.ReservationCreateDTO;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.ReservationService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 预约接口。本任务仅创建预约（含冲突检测/防超约）；生命周期端点（cancel/checkIn/checkOut 等）在 Task10 接入。
 */
@Tag(name = "预约")
@RestController
@RequestMapping("/reservations")
@RequiredArgsConstructor
public class ReservationController {

    private final ReservationService reservationService;

    @Operation(summary = "创建预约（含冲突检测/防超约）")
    @PostMapping
    public Result<Long> create(@Valid @RequestBody ReservationCreateDTO dto,
                               @AuthenticationPrincipal SecurityUserDetails ud) {
        return Result.ok(reservationService.create(dto, ud.getUserId()));
    }
}
