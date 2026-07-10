package com.lab.reservation.ai.service;

import com.lab.reservation.ai.config.CryptoUtil;
import com.lab.reservation.entity.UserAiCredential;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.mockito.junit.jupiter.MockitoSettings;
import org.mockito.quality.Strictness;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.core.env.Environment;
import org.springframework.core.env.Profiles;

import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
@MockitoSettings(strictness = Strictness.LENIENT)
class UserChatClientProviderTest {

    @Mock AiCredentialService credService;
    @Mock CryptoUtil crypto;
    @Mock ObjectProvider<ChatClient> defaultClientProvider;
    @Mock Environment env;

    private UserAiCredential row(String cipher) {
        UserAiCredential r = new UserAiCredential();
        r.setUserId(1L);
        r.setBaseUrl("https://api.deepseek.com");
        r.setApiKeyCipher(cipher);
        r.setModel("deepseek-chat");
        r.setTemperature(0.3);
        return r;
    }

    @Test
    void noKeyInProdReturnsEmpty() {
        when(credService.getRow(1L)).thenReturn(null);
        when(env.acceptsProfiles(any(Profiles.class))).thenReturn(false);
        UserChatClientProvider p = new UserChatClientProvider(credService, crypto, defaultClientProvider, env);
        assertEquals(Optional.empty(), p.resolve(1L));
    }

    @Test
    void noKeyInDevFallsBackToDefaultClient() {
        ChatClient def = mock(ChatClient.class);
        when(credService.getRow(1L)).thenReturn(null);
        when(env.acceptsProfiles(any(Profiles.class))).thenReturn(true);
        when(defaultClientProvider.getIfAvailable()).thenReturn(def);
        UserChatClientProvider p = new UserChatClientProvider(credService, crypto, defaultClientProvider, env);
        Optional<ChatClient> cc = p.resolve(1L);
        assertTrue(cc.isPresent());
        assertSame(def, cc.get());
    }

    @Test
    void withKeyBuildsAndCaches() {
        when(credService.getRow(1L)).thenReturn(row("C"));
        when(crypto.decrypt("C")).thenReturn("sk-real");
        when(crypto.keyHash("sk-real")).thenReturn("h1");
        UserChatClientProvider p = new UserChatClientProvider(credService, crypto, defaultClientProvider, env);
        Optional<ChatClient> a = p.resolve(1L);
        Optional<ChatClient> b = p.resolve(1L);
        assertTrue(a.isPresent());
        assertSame(a.get(), b.get());                  // cached → same instance
        verify(credService, times(2)).getRow(1L);      // re-read each resolve to detect key change
    }

    @Test
    void keyChangeTriggersRebuild() {
        when(credService.getRow(1L)).thenReturn(row("C"));
        when(crypto.decrypt("C")).thenReturn("sk-real");
        when(crypto.keyHash("sk-real")).thenReturn("h1", "h2");  // simulate key change between calls
        UserChatClientProvider p = new UserChatClientProvider(credService, crypto, defaultClientProvider, env);
        ChatClient a = p.resolve(1L).orElseThrow();
        ChatClient b = p.resolve(1L).orElseThrow();
        assertNotSame(a, b);                           // rebuilt because keyHash differs
    }
}
