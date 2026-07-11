package com.lab.reservation.ai.service;

import com.lab.reservation.ai.config.AiProperties;
import com.lab.reservation.entity.AiMessage;
import com.lab.reservation.mapper.AiConversationMapper;
import com.lab.reservation.mapper.AiMessageMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.UserMessage;

import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

/**
 * ConversationService 单元测试 — 聚焦 buildPrompt 的多轮重建行为。
 *
 * <p>验证两件事:
 * <ol>
 *   <li>buildPrompt(convId, currentText) 必须把历史 assistant 段也重建进 prompt(不只 user)。</li>
 *   <li>buildPrompt(convId)(无 currentText 重载)只从 DB 重建,不追加 currentText,
 *       供 ToolLoopOrchestrator runLoop 使用(user 消息已提前持久化进 DB,再追加会重复)。</li>
 * </ol>
 *
 * <p>构造方式用手工 new(与 AiAssistantServiceTest 一致):@InjectMocks 对非 mock 的
 * {@link AiProperties} 参数会传 null(Mockito 构造注入只认 @Mock/@Spy),故显式注入。
 *
 * @author AI Assistant
 * @since 2026-07-11
 */
@ExtendWith(MockitoExtension.class)
class ConversationServiceTest {

    @Mock AiConversationMapper convMapper;
    @Mock AiMessageMapper msgMapper;
    AiProperties props;
    ConversationService svc;

    @BeforeEach
    void setup() {
        props = new AiProperties();
        props.setContextWindowTurns(10);
        svc = new ConversationService(convMapper, msgMapper, props);
    }

    @Test
    void buildPrompt_includes_assistant_turns_not_just_user() {
        AiMessage u = msg("user", "我要预约显微镜");
        AiMessage a = msg("assistant", "好的,我帮您查");
        // DESC → 旧在后;用 ArrayList 模拟 MyBatis selectList 返回的可变 list
        when(msgMapper.selectList(any())).thenReturn(new ArrayList<>(List.of(a, u)));

        List<Message> out = svc.buildPrompt(1L, "明天下午");

        assertThat(out).hasSize(3);
        assertThat(out.get(0)).isInstanceOf(UserMessage.class);
        assertThat(out.get(1)).isInstanceOf(AssistantMessage.class);
        assertThat(out.get(2)).isInstanceOf(UserMessage.class);
    }

    @Test
    void buildPrompt_one_arg_overload_does_not_append_current_text() {
        AiMessage u = msg("user", "hi");
        when(msgMapper.selectList(any())).thenReturn(new ArrayList<>(List.of(u)));

        List<Message> out = svc.buildPrompt(1L);

        assertThat(out).hasSize(1); // 只 DB 里的 user,不追加
        assertThat(out.get(0)).isInstanceOf(UserMessage.class);
    }

    private AiMessage msg(String role, String content) {
        AiMessage m = new AiMessage();
        m.setRole(role);
        m.setContent(content);
        return m;
    }
}
