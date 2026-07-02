package com.lab.reservation.controller;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.lab.reservation.common.result.Result;
import com.lab.reservation.security.SecurityUserDetails;
import com.lab.reservation.service.NotificationService;
import com.lab.reservation.vo.notification.NotificationVO;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 站内通知接口（§8.7）。任意已登录用户查/读自己的通知，无需特殊权限。
 */
@Tag(name = "通知")
@RestController
@RequestMapping("/notifications")
@RequiredArgsConstructor
public class NotificationController {

    private final NotificationService notificationService;

    @Operation(summary = "我的通知（可 onlyUnread，createdAt 倒序分页）")
    @GetMapping("/mine")
    public Result<IPage<NotificationVO>> mine(@RequestParam(required = false) Boolean onlyUnread,
                                              @RequestParam(defaultValue = "1") int page,
                                              @RequestParam(defaultValue = "10") int size,
                                              @AuthenticationPrincipal SecurityUserDetails ud) {
        return Result.ok(notificationService.mine(ud.getUserId(), onlyUnread, page, size));
    }

    @Operation(summary = "标记单条为已读（校验归属）")
    @PatchMapping("/{id}/read")
    public Result<Void> markRead(@PathVariable Long id,
                                 @AuthenticationPrincipal SecurityUserDetails ud) {
        notificationService.markRead(id, ud.getUserId());
        return Result.ok();
    }

    @Operation(summary = "全部未读标记为已读")
    @PatchMapping("/read-all")
    public Result<Void> markAllRead(@AuthenticationPrincipal SecurityUserDetails ud) {
        notificationService.markAllRead(ud.getUserId());
        return Result.ok();
    }
}
