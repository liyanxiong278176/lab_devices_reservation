package com.lab.reservation.ai.service;

import com.lab.reservation.entity.UserAiCredential;
import com.lab.reservation.security.SecurityUserDetails;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.Set;
import java.util.stream.Collectors;

/**
 * 生成 AI 助手的 system prompt — 根据用户角色 + 用户自配模型动态调整。
 *
 * <p>注入用户在 BYO-key 设置里配的模型名,让 AI 被问「你是什么模型」时如实回答,
 * 而不是凭训练数据瞎编(GPT-4o 等)。
 *
 * <p>注意:这里 hardcode 字符串而不是从 yml 读,是因为 yml 多行字符串
 * 难以维护;后续 Phase 可改用 {@code messages.properties} 国际化。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Service
@RequiredArgsConstructor
public class SystemPromptBuilder {

    private final AiCredentialService credService;

    /** dev 兜底模型名(用户未配 BYO key 时用,从 siliconflow yml 读)。 */
    @Value("${spring.ai.openai.chat.options.model:默认模型}")
    private String devFallbackModel;

    private static final String TEMPLATE = """
            你是实验室预约系统的 AI 助手,服务于 [%s] 角色。当前用户 ID: %d。

            ## 身份(重要)
            当前对话由用户自行配置的模型 [%s] 提供(用户自己的 API Key)。若被问及
            "你是什么模型 / 用什么大模型 / 是哪家公司的模型",必须如实回答:你是运行在
            [%s] 上的 AI 助手。禁止编造或冒充其他模型名(如 GPT-4 / GPT-4o / Claude /
            文心一言 / GLM / Gemini 等)——用户能看到自己配的模型,撒谎会失去信任。

            ## 工具调用规则
            1. 时间参数必须是 ISO-8601 local datetime 格式,例如 "2026-07-08T14:00:00"
               禁止输出中文时间表述(如"周三 14 点"、"下午两点")。
            2. 设备 ID 必须是 Long 整数,从 search_devices 工具返回结果中获取,
               禁止猜测或编造 ID。
            3. 写工具(create_reservation / cancel_reservation / submit_repair_ticket /
               take_repair_ticket)只是"提议",用户未点确认前不要假定执行成功。
            4. 工具不可用时(如越权),明确告诉用户"该操作需要 X 权限",不要伪造结果。

            ## 回答风格
            - 中文,简洁,准确
            - 涉及设备/时间/数字时给出具体值,不要模糊
            - 检索到文档时引用来源
            - 检索不到时明确说"暂无相关文档",不要编造
            """;

    /**
     * 根据角色 + userId + 用户自配模型拼装最终 prompt。
     *
     * @param role   主角色字符串(如 {@code "STUDENT"} / {@code "LAB_ADMIN"} / {@code "SYS_ADMIN"})
     * @param userId 当前登录用户 ID
     */
    public String build(String role, Long userId) {
        String model = resolveModel(userId);
        return TEMPLATE.formatted(
                role == null ? "STUDENT" : role,
                userId == null ? 0L : userId,
                model,
                model);
    }

    /** 取用户自配模型名;未配(dev 兜底)则读 siliconflow yml 的 chat model。 */
    private String resolveModel(Long userId) {
        if (userId == null) {
            return devFallbackModel;
        }
        UserAiCredential row = credService.getRow(userId);
        if (row != null && row.getModel() != null && !row.getModel().isBlank()) {
            return row.getModel();
        }
        return devFallbackModel;
    }

    /**
     * 从 {@link SecurityUserDetails#getAuthorities()} 里取最高优先级角色。
     * 优先级:SYS_ADMIN > LAB_ADMIN > STUDENT,默认为 STUDENT。
     */
    public static String extractRole(SecurityUserDetails user) {
        if (user == null || user.getAuthorities() == null) return "STUDENT";
        Set<String> roles = user.getAuthorities().stream()
                .map(a -> a.getAuthority())
                .map(s -> s.replace("ROLE_", ""))
                .collect(Collectors.toSet());
        if (roles.contains("SYS_ADMIN")) return "SYS_ADMIN";
        if (roles.contains("LAB_ADMIN")) return "LAB_ADMIN";
        return "STUDENT";
    }
}
