package com.lab.reservation.ai.controller;

import com.lab.reservation.ai.dto.AiCredentialSaveDTO;
import com.lab.reservation.ai.service.AiCredentialService;
import com.lab.reservation.ai.service.UserChatClientProvider;
import com.lab.reservation.ai.vo.AiCredentialVO;
import com.lab.reservation.common.result.Result;
import com.lab.reservation.security.SecurityUserDetails;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.*;

/**
 * 用户 LLM 凭证(本人)。
 *
 * <p>注意:POST 故意不加 @Log —— 请求体含明文 apiKey,不能进 operation_log。
 * 无 @PreAuthorize:按 SecurityUserDetails 限定本人即可(人人可管自己的)。
 *
 * @author AI Assistant
 * @since 2026-07-09
 */
@Tag(name = "AI 凭证")
@RestController
@RequestMapping("/ai/credential")
@RequiredArgsConstructor
public class AiCredentialController {

    private final AiCredentialService credService;
    private final UserChatClientProvider provider;

    @Operation(summary = "查本人当前配置(key masked)")
    @GetMapping
    public Result<AiCredentialVO> get(@AuthenticationPrincipal SecurityUserDetails ud) {
        return Result.ok(credService.get(ud.getUserId()));
    }

    @Operation(summary = "保存/更新(test 失败不落库)")
    @PostMapping
    public Result<AiCredentialVO> save(@AuthenticationPrincipal SecurityUserDetails ud,
                                       @Valid @RequestBody AiCredentialSaveDTO dto) {
        AiCredentialVO vo = credService.save(ud.getUserId(), dto);
        provider.evict(ud.getUserId());   // key 变了,失效缓存
        return Result.ok(vo);
    }

    @Operation(summary = "删除(回到未配置)")
    @DeleteMapping
    public Result<?> delete(@AuthenticationPrincipal SecurityUserDetails ud) {
        credService.delete(ud.getUserId());
        provider.evict(ud.getUserId());
        return Result.ok();
    }
}
