package com.lab.reservation.controller;

import com.lab.reservation.common.result.Result;
import com.lab.reservation.service.DeviceCategoryService;
import com.lab.reservation.vo.device.DeviceCategoryNodeVO;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@Tag(name = "设备分类")
@RestController
@RequestMapping("/device-categories")
@RequiredArgsConstructor
public class DeviceCategoryController {

    private final DeviceCategoryService categoryService;

    @Operation(summary = "分类树")
    @GetMapping
    public Result<List<DeviceCategoryNodeVO>> tree() {
        return Result.ok(categoryService.tree());
    }
}
