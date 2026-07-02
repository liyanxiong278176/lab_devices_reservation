package com.lab.reservation.controller;

import com.lab.reservation.common.result.Result;
import com.lab.reservation.dto.reservation.ReservationCreateDTO;
import com.lab.reservation.dto.reservation.ReservationQueryDTO;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.ReservationService;
import com.lab.reservation.vo.reservation.ReservationVO;
import com.baomidou.mybatisplus.core.metadata.IPage;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

/**
 * 预约接口：创建 + 生命周期状态机（cancel/checkIn/checkOut/violate/noShow）+ 查询（mine/detail）。
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

    @Operation(summary = "取消预约（本人，须在开始前且 PENDING/APPROVED）")
    @PostMapping("/{id}/cancel")
    public Result<Void> cancel(@PathVariable Long id,
                               @AuthenticationPrincipal SecurityUserDetails ud) {
        reservationService.cancel(id, ud.getUserId());
        return Result.ok();
    }

    @Operation(summary = "签到（APPROVED 且在时间窗内，本人或管理员）")
    @PostMapping("/{id}/check-in")
    public Result<Void> checkIn(@PathVariable Long id,
                                @AuthenticationPrincipal SecurityUserDetails ud) {
        reservationService.checkIn(id, ud);
        return Result.ok();
    }

    @Operation(summary = "归还（IN_USE → COMPLETED，本人或管理员）")
    @PostMapping("/{id}/check-out")
    public Result<Void> checkOut(@PathVariable Long id,
                                 @AuthenticationPrincipal SecurityUserDetails ud) {
        reservationService.checkOut(id, ud);
        return Result.ok();
    }

    @Operation(summary = "标记违规（管理员）")
    @PostMapping("/{id}/violate")
    @PreAuthorize("hasAuthority('device:approve')")
    public Result<Void> violate(@PathVariable Long id) {
        reservationService.markViolated(id);
        return Result.ok();
    }

    @Operation(summary = "标记爽约（管理员）")
    @PostMapping("/{id}/no-show")
    @PreAuthorize("hasAuthority('device:approve')")
    public Result<Void> noShow(@PathVariable Long id) {
        reservationService.markNoShow(id);
        return Result.ok();
    }

    @Operation(summary = "我的预约（按 status/分页过滤）")
    @GetMapping("/mine")
    public Result<IPage<ReservationVO>> mine(ReservationQueryDTO query,
                                             @AuthenticationPrincipal SecurityUserDetails ud) {
        int page = query.getPage() == null ? 1 : query.getPage();
        int size = query.getSize() == null ? 10 : query.getSize();
        return Result.ok(reservationService.myReservations(ud.getUserId(), query.getStatus(), page, size));
    }

    @Operation(summary = "预约详情（本人或管理员）")
    @GetMapping("/{id}")
    public Result<ReservationVO> detail(@PathVariable Long id,
                                        @AuthenticationPrincipal SecurityUserDetails ud) {
        return Result.ok(reservationService.detail(id, ud));
    }
}
