package com.lab.reservation.ai.service;

import com.lab.reservation.ai.config.CryptoUtil;
import com.lab.reservation.ai.dto.AiCredentialSaveDTO;
import com.lab.reservation.ai.vo.AiCredentialVO;
import com.lab.reservation.entity.UserAiCredential;
import com.lab.reservation.exception.BusinessException;
import com.lab.reservation.mapper.UserAiCredentialMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class AiCredentialServiceTest {

    @Mock UserAiCredentialMapper mapper;
    @Mock CryptoUtil crypto;
    @Mock LlmClient llmClient;
    @InjectMocks AiCredentialService service;

    private AiCredentialSaveDTO dto(String baseUrl) {
        AiCredentialSaveDTO d = new AiCredentialSaveDTO();
        d.setProvider("deepseek");
        d.setBaseUrl(baseUrl);
        d.setApiKey("sk-1234567890");
        d.setModel("deepseek-chat");
        d.setTemperature(0.3);
        return d;
    }

    @Test
    void saveStripsTrailingV1() {
        when(llmClient.testConnection(eq("https://api.deepseek.com"), anyString(), anyString())).thenReturn(true);
        when(mapper.selectOne(any())).thenReturn(null);
        when(crypto.encrypt(any())).thenReturn("CIPHER");

        service.save(1L, dto("https://api.deepseek.com/v1"));

        ArgumentCaptor<UserAiCredential> cap = ArgumentCaptor.forClass(UserAiCredential.class);
        verify(mapper).insert(cap.capture());
        assertEquals("https://api.deepseek.com", cap.getValue().getBaseUrl());
        assertEquals("CIPHER", cap.getValue().getApiKeyCipher());
    }

    @Test
    void saveRollsBackWhenTestFails() {
        when(llmClient.testConnection(anyString(), anyString(), anyString())).thenReturn(false);

        assertThrows(BusinessException.class, () -> service.save(1L, dto("https://api.deepseek.com")));
        verify(mapper, never()).insert(any());
        verify(crypto, never()).encrypt(any());
    }

    @Test
    void getMasksApiKey() {
        UserAiCredential row = new UserAiCredential();
        row.setProvider("deepseek");
        row.setBaseUrl("https://api.deepseek.com");
        row.setApiKeyCipher("CIPHER");
        row.setModel("deepseek-chat");
        row.setTemperature(0.3);
        when(mapper.selectOne(any())).thenReturn(row);
        when(crypto.decrypt("CIPHER")).thenReturn("sk-deadbeefcafebabe123456789abcd3756");

        AiCredentialVO vo = service.get(1L);
        assertTrue(vo.isConfigured());
        assertTrue(vo.getApiKeyMasked().startsWith("sk-"));
        assertTrue(vo.getApiKeyMasked().endsWith("3756"));
        assertFalse(vo.getApiKeyMasked().contains("deadbeefcafebabe"));
    }
}
