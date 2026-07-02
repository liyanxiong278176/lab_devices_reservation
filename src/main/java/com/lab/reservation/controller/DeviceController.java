package com.lab.reservation.controller;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.lab.reservation.aspect.Log;
import com.lab.reservation.common.result.Result;
import com.lab.reservation.dto.device.DeviceQueryDTO;
import com.lab.reservation.dto.device.DeviceSaveDTO;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.DeviceService;
import com.lab.reservation.vo.device.DeviceCalendarItemVO;
import com.lab.reservation.vo.device.DeviceVO;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;
import java.util.List;

@Tag(name = "设备")
@RestController
@RequestMapping("/devices")
@RequiredArgsConstructor
public class DeviceController {

    private final DeviceService deviceService;

    @Operation(summary = "设备多条件检索（任何已登录用户可浏览）")
    @GetMapping
    public Result<IPage<DeviceVO>> search(DeviceQueryDTO query) {
        return Result.ok(deviceService.search(query));
    }

    @Operation(summary = "设备详情")
    @GetMapping("/{id}")
    public Result<DeviceVO> getById(@PathVariable Long id) {
        return Result.ok(deviceService.getById(id));
    }

    @Operation(summary = "设备日历（某区间内被占用的 slot）")
    @GetMapping("/{id}/calendar")
    public Result<List<DeviceCalendarItemVO>> calendar(@PathVariable Long id,
                                                       @RequestParam @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate from,
                                                       @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE) LocalDate to) {
        return Result.ok(deviceService.calendar(id, from, to));
    }

    @Operation(summary = "新建设备")
    @PostMapping
    @PreAuthorize("hasAuthority('device:manage')")
    @Log("创建设备")
    public Result<DeviceVO> create(@Valid @RequestBody DeviceSaveDTO dto,
                                   @AuthenticationPrincipal SecurityUserDetails ud) {
        return Result.ok(deviceService.create(dto, ud));
    }

    @Operation(summary = "更新设备")
    @PutMapping
    @PreAuthorize("hasAuthority('device:manage')")
    @Log("更新设备")
    public Result<DeviceVO> update(@RequestParam Long id,
                                   @Valid @RequestBody DeviceSaveDTO dto,
                                   @AuthenticationPrincipal SecurityUserDetails ud) {
        return Result.ok(deviceService.update(id, dto, ud));
    }

    @Operation(summary = "删除设备")
    @DeleteMapping("/{id}")
    @PreAuthorize("hasAuthority('device:manage')")
    @Log("删除设备")
    public Result<?> delete(@PathVariable Long id,
                            @AuthenticationPrincipal SecurityUserDetails ud) {
        deviceService.delete(id, ud);
        return Result.ok();
    }

    @Operation(summary = "更新设备状态")
    @PatchMapping("/{id}/status")
    @PreAuthorize("hasAuthority('device:manage')")
    @Log("更新设备状态")
    public Result<?> updateStatus(@PathVariable Long id,
                                  @RequestParam String status,
                                  @AuthenticationPrincipal SecurityUserDetails ud) {
        deviceService.updateStatus(id, status, ud);
        return Result.ok();
    }
}
