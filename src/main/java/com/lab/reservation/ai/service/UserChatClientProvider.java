package com.lab.reservation.ai.service;

import com.lab.reservation.ai.config.CryptoUtil;
import com.lab.reservation.entity.UserAiCredential;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.openai.OpenAiChatModel;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.ai.openai.api.OpenAiApi;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.core.env.Environment;
import org.springframework.core.env.Profiles;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/**
 * per-user ChatClient 缓存工厂。
 *
 * <p>resolve(userId):DB 有 key → decrypt + 按 userId 缓存(keyHash 变或超 30min 则重建);
 * 无 key + dev → 返回默认单例 ChatClient(yml 兜底);无 key + prod → empty。
 *
 * <p>cache:ConcurrentHashMap,每用户 1 条(用户数天然有界);save/delete 调
 * {@link #evict(Long)} 主动失效。每次 resolve 重读 row 以检测 key 变更(避免缓存陈旧)。
 *
 * @author AI Assistant
 * @since 2026-07-09
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class UserChatClientProvider {

    private static final long TTL_MS = Duration.ofMinutes(30).toMillis();

    private final AiCredentialService credService;
    private final CryptoUtil crypto;
    private final ObjectProvider<ChatClient> defaultClientProvider;
    private final Environment env;
    private final OpenAiApiFactory apiFactory;

    /** userId → 缓存条目。final + 内联初始化 → 不进 RequiredArgsConstructor 参数。 */
    private final ConcurrentHashMap<Long, Entry> cache = new ConcurrentHashMap<>();

    public Optional<ChatClient> resolve(Long userId) {
        UserAiCredential row = credService.getRow(userId);
        if (row == null) {
            return devFallback();
        }
        String plain = crypto.decrypt(row.getApiKeyCipher());
        if (plain == null) {
            log.warn("user {} api_key decrypt failed, falling back", userId);
            return devFallback();
        }
        String hash = crypto.keyHash(plain);

        Entry e = cache.get(userId);
        if (e != null && !e.isExpired() && e.keyHash.equals(hash)) {
            return Optional.of(e.client);
        }
        ChatClient cc = build(row.getBaseUrl(), plain, row.getModel(), row.getTemperature());
        cache.put(userId, new Entry(cc, hash));
        return Optional.of(cc);
    }

    public void evict(Long userId) {
        cache.remove(userId);
    }

    private Optional<ChatClient> devFallback() {
        if (env.acceptsProfiles(Profiles.of("dev"))) {
            ChatClient def = defaultClientProvider.getIfAvailable();
            if (def != null) {
                return Optional.of(def);
            }
        }
        return Optional.empty();
    }

    private ChatClient build(String baseUrl, String apiKey, String model, Double temperature) {
        OpenAiApi api = apiFactory.build(baseUrl, apiKey);
        OpenAiChatOptions.Builder ob = OpenAiChatOptions.builder().model(model);
        if (temperature != null) {
            ob.temperature(temperature);   // null → 不设,用模型默认(别把 null 塞进 builder)
        }
        OpenAiChatModel m = OpenAiChatModel.builder().openAiApi(api).defaultOptions(ob.build()).build();
        return ChatClient.create(m);
    }

    /** 缓存条目:client + keyHash(失效判定)+ 创建时间(TTL)。 */
    private static final class Entry {
        final ChatClient client;
        final String keyHash;
        final long createdAt;
        Entry(ChatClient client, String keyHash) {
            this.client = client;
            this.keyHash = keyHash;
            this.createdAt = System.currentTimeMillis();
        }
        boolean isExpired() {
            return System.currentTimeMillis() - createdAt > TTL_MS;
        }
    }
}
