package com.lab.reservation.ai.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.lab.reservation.ai.config.CryptoUtil;
import com.lab.reservation.ai.dto.AiCredentialSaveDTO;
import com.lab.reservation.ai.vo.AiCredentialVO;
import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.entity.UserAiCredential;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.mapper.UserAiCredentialMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 用户 LLM 凭证 CRUD:test-before-persist(失败抛 BusinessException 不落库)、
 * base-url 去 /v1、GET 时 key mask(明文永不外泄)。
 *
 * <p>异常类型选择:必须抛 {@link BusinessException}(GlobalExceptionHandler 保留 message
 * 透传前端);若抛 IllegalArgumentException 会被兜底吞成通用 BUSINESS_ERROR,丢掉提示。
 *
 * @author AI Assistant
 * @since 2026-07-09
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AiCredentialService {

    private final UserAiCredentialMapper mapper;
    private final CryptoUtil crypto;
    private final LlmClient llmClient;

    @Transactional
    public AiCredentialVO save(Long userId, AiCredentialSaveDTO dto) {
        String baseUrl = stripTrailingV1(dto.getBaseUrl().trim());

        // test-before-persist:失败不落库
        if (!llmClient.testConnection(baseUrl, dto.getApiKey(), dto.getModel())) {
            throw new BusinessException(ResultCode.BUSINESS_ERROR.getCode(),
                    "连接测试失败:检查 base-url / api-key / model");
        }

        UserAiCredential row = mapper.selectOne(
                new QueryWrapper<UserAiCredential>().eq("user_id", userId));
        boolean insert = (row == null);
        if (insert) {
            row = new UserAiCredential();
            row.setUserId(userId);
        }
        row.setProvider(dto.getProvider());
        row.setBaseUrl(baseUrl);
        row.setApiKeyCipher(crypto.encrypt(dto.getApiKey()));
        row.setModel(dto.getModel());
        row.setTemperature(dto.getTemperature());
        row.setValidated(1);
        if (insert) mapper.insert(row); else mapper.updateById(row);
        return toVo(row);
    }

    public AiCredentialVO get(Long userId) {
        UserAiCredential row = mapper.selectOne(
                new QueryWrapper<UserAiCredential>().eq("user_id", userId));
        return row == null ? unconfigured() : toVo(row);
    }

    public void delete(Long userId) {
        mapper.delete(new QueryWrapper<UserAiCredential>().eq("user_id", userId));
    }

    /** 供 UserChatClientProvider 用:取该用户凭证行(含密文)。 */
    public UserAiCredential getRow(Long userId) {
        return mapper.selectOne(
                new QueryWrapper<UserAiCredential>().eq("user_id", userId));
    }

    private AiCredentialVO toVo(UserAiCredential row) {
        AiCredentialVO vo = new AiCredentialVO();
        vo.setProvider(row.getProvider());
        vo.setBaseUrl(row.getBaseUrl());
        vo.setModel(row.getModel());
        vo.setTemperature(row.getTemperature());
        vo.setConfigured(true);
        vo.setApiKeyMasked(mask(crypto.decrypt(row.getApiKeyCipher())));
        return vo;
    }

    private AiCredentialVO unconfigured() {
        AiCredentialVO vo = new AiCredentialVO();
        vo.setConfigured(false);
        return vo;
    }

    /** sk-****末4位。短 key 兜底全 ****。 */
    static String mask(String plain) {
        if (plain == null || plain.length() < 4) return "****";
        return plain.substring(0, Math.min(3, plain.length())) + "****"
                + plain.substring(plain.length() - 4);
    }

    static String stripTrailingV1(String url) {
        return url.replaceAll("/+$", "").replaceAll("(?i)/v1$", "");
    }
}
