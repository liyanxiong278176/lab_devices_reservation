package com.lab.reservation.controller;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.lab.reservation.aspect.Log;
import com.lab.reservation.common.result.Result;
import com.lab.reservation.dto.user.UserCreateDTO;
import com.lab.reservation.dto.user.UserQueryDTO;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.UserService;
import com.lab.reservation.vo.user.UserVO;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
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

/**
 * 用户管理（仅 SYS_ADMIN，通过 user:manage 权限隔离）。
 */
@Tag(name = "用户管理")
@RestController
@RequestMapping("/users")
@RequiredArgsConstructor
@PreAuthorize("hasAuthority('user:manage')")
public class UserController {

    private final UserService userService;

    @Operation(summary = "用户分页检索（username/realName 模糊 + status 等值）")
    @GetMapping
    public Result<IPage<UserVO>> list(UserQueryDTO query) {
        return Result.ok(userService.list(query));
    }

    @Operation(summary = "创建用户（username 查重 + BCrypt + 绑角色）")
    @PostMapping
    @Log("创建用户")
    public Result<UserVO> create(@Valid @RequestBody UserCreateDTO dto) {
        return Result.ok(userService.create(dto));
    }

    @Operation(summary = "更新用户（改资料/可选改密码/重绑角色）")
    @PutMapping("/{id}")
    @Log("更新用户")
    public Result<UserVO> update(@PathVariable Long id,
                                 @Valid @RequestBody UserCreateDTO dto) {
        return Result.ok(userService.update(id, dto));
    }

    @Operation(summary = "删除用户（禁止删自己）")
    @DeleteMapping("/{id}")
    @Log("删除用户")
    public Result<?> delete(@PathVariable Long id,
                            @AuthenticationPrincipal SecurityUserDetails ud) {
        userService.delete(id, ud.getUserId());
        return Result.ok();
    }

    @Operation(summary = "封禁/解封（status 0 禁用 / 1 启用）")
    @PatchMapping("/{id}/status")
    @Log("更新用户状态")
    public Result<?> updateStatus(@PathVariable Long id,
                                  @RequestParam Integer status) {
        userService.updateStatus(id, status);
        return Result.ok();
    }
}
