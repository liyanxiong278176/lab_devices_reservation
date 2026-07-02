package com.lab.reservation.controller;

import com.lab.reservation.aspect.Log;
import com.lab.reservation.common.result.Result;
import com.lab.reservation.dto.auth.LoginDTO;
import com.lab.reservation.dto.auth.RegisterDTO;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.AuthService;
import com.lab.reservation.vo.auth.LoginVO;
import com.lab.reservation.vo.auth.UserInfoVO;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@Tag(name = "鉴权")
@RestController
@RequestMapping("/auth")
@RequiredArgsConstructor
public class AuthController {

    private final AuthService authService;

    @Operation(summary = "登录")
    @PostMapping("/login")
    @Log("登录")
    public Result<LoginVO> login(@Valid @RequestBody LoginDTO dto) {
        return Result.ok(authService.login(dto));
    }

    @Operation(summary = "注册")
    @PostMapping("/register")
    @Log("注册")
    public Result<?> register(@Valid @RequestBody RegisterDTO dto) {
        authService.register(dto);
        return Result.ok();
    }

    @Operation(summary = "刷新token")
    @PostMapping("/refresh")
    public Result<?> refresh(@RequestParam String refreshToken) {
        return Result.ok(Map.of("accessToken", authService.refresh(refreshToken)));
    }

    @Operation(summary = "登出")
    @PostMapping("/logout")
    @Log("登出")
    public Result<?> logout(@RequestHeader("Authorization") String auth) {
        authService.logout(auth);
        return Result.ok();
    }

    @Operation(summary = "当前用户")
    @GetMapping("/me")
    public Result<UserInfoVO> me(@AuthenticationPrincipal SecurityUserDetails ud) {
        UserInfoVO vo = new UserInfoVO();
        vo.setId(ud.getUserId());
        vo.setUsername(ud.getUsername());
        vo.setRealName(ud.getRealName());
        List<String> auths = ud.getAuthorities().stream()
                .map(GrantedAuthority::getAuthority).toList();
        vo.setRoles(auths.stream()
                .filter(a -> a.startsWith("ROLE_"))
                .map(a -> a.substring(5)).toList());
        vo.setPermissions(auths.stream()
                .filter(a -> !a.startsWith("ROLE_")).toList());
        return Result.ok(vo);
    }
}
