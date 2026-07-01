package com.lab.reservation.controller;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.lab.reservation.common.result.Result;
import com.lab.reservation.entity.Lab;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.LabService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@Tag(name = "实验室")
@RestController
@RequestMapping("/labs")
@RequiredArgsConstructor
public class LabController {

    private final LabService labService;

    @Operation(summary = "实验室分页")
    @GetMapping
    @PreAuthorize("hasAnyRole('SYS_ADMIN','LAB_ADMIN')")
    public Result<IPage<Lab>> page(@RequestParam(defaultValue = "1") long page,
                                   @RequestParam(defaultValue = "10") long size,
                                   @AuthenticationPrincipal SecurityUserDetails ud) {
        return Result.ok(labService.page(page, size, ud));
    }

    @Operation(summary = "实验室详情")
    @GetMapping("/{id}")
    @PreAuthorize("hasAnyRole('SYS_ADMIN','LAB_ADMIN')")
    public Result<Lab> getById(@PathVariable Long id,
                               @AuthenticationPrincipal SecurityUserDetails ud) {
        return Result.ok(labService.getById(id, ud));
    }

    @Operation(summary = "新建实验室")
    @PostMapping
    @PreAuthorize("hasRole('SYS_ADMIN')")
    public Result<Lab> create(@RequestBody Lab lab) {
        return Result.ok(labService.create(lab));
    }

    @Operation(summary = "更新实验室")
    @PutMapping
    @PreAuthorize("hasAnyRole('SYS_ADMIN','LAB_ADMIN')")
    public Result<Lab> update(@RequestBody Lab lab,
                              @AuthenticationPrincipal SecurityUserDetails ud) {
        return Result.ok(labService.update(lab, ud));
    }

    @Operation(summary = "删除实验室")
    @DeleteMapping("/{id}")
    @PreAuthorize("hasAnyRole('SYS_ADMIN','LAB_ADMIN')")
    public Result<?> delete(@PathVariable Long id,
                            @AuthenticationPrincipal SecurityUserDetails ud) {
        labService.delete(id, ud);
        return Result.ok();
    }
}
