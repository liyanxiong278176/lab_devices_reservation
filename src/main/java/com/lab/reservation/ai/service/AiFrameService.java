package com.lab.reservation.ai.service;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.lab.reservation.entity.AiWsFrame;
import com.lab.reservation.mapper.AiWsFrameMapper;
import com.lab.reservation.security.SecurityUserDetails;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.messaging.simp.SimpMessagingTemplate;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * WS 帧分配 seq + 持久化 + STOMP 推送。
 *
 * <p>每条外发的 STOMP 帧在推送前先写一行到 {@code ai_ws_frame} — 这样客户端断线
 * 重连时按 {@code last_seq} 重放,服务端从 DB 按 {@code frame_seq > last_seq}
 * 重推回去。
 *
 * <p>seq 分配走 Redis {@code INCR} (key: {@code ai:ws:seq:{convId}}) 保证
 * 同一会话单调自增,且多实例部署下仍有序。Redis 不可用时降级为 1,日志告警
 * (上层 AiAssistantService 应在 seq 异常时主动 disable resync)。
 *
 * @author AI Assistant
 * @since 2026-07-08
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AiFrameService {

    private final AiWsFrameMapper mapper;
    private final SimpMessagingTemplate ws;
    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper;

    /**
     * 分配 seq + 持久化 + 推送。
     *
     * <p>{@code payload} 会被原地 put 进 {@code seq} 和 {@code conv_id} 两个字段;
     * 持久化列与推送 payload 内容一致(同一 JSON 字符串)。
     */
    public void push(Long convId, SecurityUserDetails user, String type, Map<String, Object> payload) {
        pushByUser(convId, user.getUserId(), type, payload);
    }

    /**
     * 同 {@link #push} 但以 userId 直传 — 给无 SecurityUserDetails 上下文的路径
     * (如 {@code AiActionTimeoutScheduler} 超时清挂起态)用。
     *
     * <p>{@code payload} 会被 copy 一份 mutable 后写 {@code seq} / {@code conv_id} / {@code type};
     * 持久化列与推送 payload 内容一致(同一 JSON 字符串)。{@code userId} 为 null 时
     * 仍落库但不推 STOMP(避免 Scheduled 路径造不出合法 user topic)。
     */
    public void pushByUser(Long convId, Long userId, String type, Map<String, Object> payload) {
        Long seq = null;
        try {
            seq = redis.opsForValue().increment("ai:ws:seq:" + convId);
        } catch (RuntimeException e) {
            log.warn("ai frame seq Redis INCR failed for conv={}, falling back to 1: {}", convId, e.toString());
        }
        if (seq == null) {
            seq = 1L;
        }
        // 调用方常传 Map.of(...) 不可变 map;copy 一份 mutable 后再写 seq/conv_id + type。
        // type 字段是前端 WsServerFrame union 的 discriminator,必须放在 payload 里,前端
        // switch (frame.type) 才能正确路由;frame_type 只用来落 ai_ws_frame 表不参与推送。
        Map<String, Object> mutable = new HashMap<>(payload);
        mutable.put("type", type);
        mutable.put("seq", seq);
        mutable.put("conv_id", convId);

        AiWsFrame f = new AiWsFrame();
        f.setConversationId(convId);
        f.setUserId(userId);
        f.setFrameSeq(seq);
        f.setFrameType(type);
        f.setPayload(toJson(mutable));
        f.setCreatedAt(LocalDateTime.now());
        mapper.insert(f);

        if (userId != null) {
            ws.convertAndSendToUser(String.valueOf(userId), "/queue/assistant-stream", mutable);
        }
    }

    /**
     * 客户端 resync 帧:从 {@code lastSeq} 之后重推。
     *
     * @param convId  会话 id
     * @param lastSeq 客户端已经收到的最大 seq(传 0 / null 表示全量)
     */
    public List<Map<String, Object>> resync(SecurityUserDetails user, Long convId, Long lastSeq) {
        List<AiWsFrame> frames = mapper.selectList(
                new QueryWrapper<AiWsFrame>()
                        .eq("conversation_id", convId)
                        .gt("frame_seq", lastSeq == null ? 0L : lastSeq)
                        .orderByAsc("frame_seq")
        );
        return frames.stream().map(f -> {
            Map<String, Object> m = fromJson(f.getPayload());
            if (m == null) {
                m = new HashMap<>();
            }
            return m;
        }).toList();
    }

    private String toJson(Object o) {
        try {
            return objectMapper.writeValueAsString(o);
        } catch (Exception e) {
            log.warn("AiFrameService toJson failed: {}", e.toString());
            return "{}";
        }
    }

    private Map<String, Object> fromJson(String s) {
        try {
            return objectMapper.readValue(s, new TypeReference<Map<String, Object>>() {});
        } catch (Exception e) {
            log.warn("AiFrameService fromJson failed: {}", e.toString());
            return Collections.emptyMap();
        }
    }
}
