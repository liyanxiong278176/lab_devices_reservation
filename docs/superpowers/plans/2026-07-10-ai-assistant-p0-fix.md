# AI 助手 P0 修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 AI 助手真正能"代预约"——显式 agent 循环执行工具,写操作经用户二次确认后落库,两阶段真流式输出,限流按对话轮次不误伤。

**Architecture:** 从 `AiAssistantService` 抽出 `ToolLoopOrchestrator`。用 Spring AI 1.0.6 `OpenAiChatOptions.internalToolExecutionEnabled(false)` 让模型只返回 toolCalls 不自动执行 → 编排器手动 dispatch → 写工具挂起推确认卡 → 用户确认后 resume 续循环 → 无 toolCall 时 `.stream()` 真流式收尾。

**Tech Stack:** Spring Boot 3.2.5 / Spring AI 1.0.6 / MyBatis-Plus / Resilience4j / Vue 3 + Pinia + STOMP

**Spec:** `docs/superpowers/specs/2026-07-10-ai-assistant-p0-fix-design.md`

---

## Task Dependency Order(实现顺序)

任务有交叉依赖,按此序执行(非严格编号序):
1 → 2 → 3 → 4(骨架)→ 5(suspend)→ **8(confirmAndLoad owner 校验)** → 6(resume)→ 7(cancel/busy)→ 9(scheduler expire)→ 10(AiAssistantService 接线)→ 11(前端)→ 12(e2e)

> 即:**confirmAndLoad(Task 8)必须在 resume(Task 6)之前**。下面任务编号保留不动,但 Task 6 顶部标 PREREQ。

---

---

## File Structure

**Create (后端):**
- `src/main/java/com/lab/reservation/ai/service/ToolLoopOrchestrator.java` — 显式 agent 循环 + 挂起/恢复 + 两阶段。核心新组件。
- `src/main/java/com/lab/reservation/ai/service/ToolCallbackResolver.java` — **测试缝**:把 user → `Map<String,ToolCallback>` 的解析隔离成接口。真 impl 用 `ToolRegistry` + `MethodToolCallbackProvider`;测试提供 stub 返回 mock ToolCallback(可控 `.call()` 返回)。让 Orchestrator 测试不碰 Spring AI 反射。
- `src/test/java/com/lab/reservation/ai/service/ToolLoopOrchestratorTest.java`
- `src/test/java/com/lab/reservation/ai/service/LlmClientTest.java`

**Modify (后端):**
- `ai/service/LlmClient.java` — 拆 `callOnce`(internalToolExecutionEnabled=false)+ `streamFinal` + `callOnceFallback`,删伪流式 12 字切片
- `ai/service/AiAssistantService.java` — 瘦身,循环委托 Orchestrator;`handleConfirm/handleCancel` 转 Orchestrator
- `ai/service/ConversationService.java` — `buildPrompt` 重建含 assistant + tool 消息
- `ai/service/ConfirmationService.java` — `confirm(actionId, userId)` 加 owner 校验
- `ai/task/AiActionTimeoutScheduler.java` — expire 后清挂起态 + 推 `confirmation_expired` 帧
- `ai/config/AiProperties.java` — rate-limit capacity/refill 20→30
- `pom.xml` — maven-compiler `<parameters>true</parameters>`

**Modify (前端):**
- `frontend/src/stores/ai.ts` — `execution_result.ok=false` 关卡片回 idle(基本已有,补 state)
- `frontend/src/components/ai/AiAssistant.vue` — BUSY 错误不弹设置面板

**Seam (testability):** Orchestrator 依赖 `LlmClient`(可 mock),不直接碰 `ChatClient`。Orchestrator 测试 mock LlmClient 返回构造的 `ChatResponse`(含 toolCalls),无需真 LLM。

---

## Task 1: 机械改动 — pom -parameters + AiProperties 限流调高

**Files:**
- Modify: `pom.xml`(`<build><plugins>` 的 maven-compiler-plugin)
- Modify: `src/main/java/com/lab/reservation/ai/config/AiProperties.java`

- [ ] **Step 1: pom.xml 加 -parameters**

在 `maven-compiler-plugin`(或 spring-boot-starter-parent 继承的 compiler)的 `<configuration>` 加:
```xml
<configuration>
    <parameters>true</parameters>
    <release>17</release>
</configuration>
```
若 pom 无显式 maven-compiler-plugin,加一个:
```xml
<plugin>
    <groupId>org.apache.maven.plugins</groupId>
    <artifactId>maven-compiler-plugin</artifactId>
    <configuration>
        <parameters>true</parameters>
    </configuration>
</plugin>
```
目的:`ToolArgumentValidator.register` 里 `p.getName()` 才返回真参数名而非 `arg0`。

- [ ] **Step 2: AiProperties 限流调高**

```java
@Data
public static class RateLimit {
    private int capacity = 30;        // 20 → 30
    private int refillPerMinute = 30; // 20 → 30
}
```

- [ ] **Step 3: 编译验证**

Run: `mvn -q compile`
Expected: BUILD SUCCESS

- [ ] **Step 4: Commit**

```bash
git add pom.xml src/main/java/com/lab/reservation/ai/config/AiProperties.java
git commit -m "chore(ai): enable -parameters compiler flag, bump rate-limit to 30/min"
```

---

## Task 2: LlmClient — callOnce + streamFinal + fallback

**Files:**
- Modify: `src/main/java/com/lab/reservation/ai/service/LlmClient.java`
- Test: `src/test/java/com/lab/reservation/ai/service/LlmClientTest.java`

**关键设计:** `callOnce` 用 `OpenAiChatOptions.internalToolExecutionEnabled(false)` 让模型返回 toolCalls 不自动执行。`streamFinal` 无 tools 真流式。

- [ ] **Step 1: 写失败测试 LlmClientTest**

```java
package com.lab.reservation.ai.service;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.ai.chat.messages.AssistantMessage;
import reactor.core.publisher.Flux;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class LlmClientTest {

    @Mock ChatClient chatClient;
    @Mock ChatClient.ChatClientRequestSpec reqSpec;
    @Mock ChatClient.CallResponseSpec callSpec;
    @Mock ChatClient.StreamResponseSpec streamSpec;

    LlmClient llm;

    @BeforeEach
    void setup() {
        llm = new LlmClient();
    }

    @Test
    void callOnce_returns_chatResponse_from_chain() {
        AssistantMessage am = new AssistantMessage("hello");
        ChatResponse resp = new ChatResponse(List.of(new Generation(am)));
        when(chatClient.prompt(any(ChatClient.PromptSpec.class))).thenAnswer(inv -> {
            // PromptSpec 是嵌套接口;用 lenient deep-stubs 或手动 stub
            return reqSpec;
        });
        // 因 fluent 链 mocked,简化:用 deep stub
        // 见 Step 1b 换 RETURNS_DEEP_STUBS 方案
        // 此处占位,实际用 Step 1b
    }
}
```

> 注:Spring AI fluent API mock 痛苦。Step 1b 给可跑方案。

- [ ] **Step 1b: 改用 RETURNS_DEEP_STUBS(可跑版)**

```java
@ExtendWith(MockitoExtension.class)
class LlmClientTest {

    @Mock(answer = Answers.RETURNS_DEEP_STUBS) ChatClient chatClient;

    LlmClient llm = new LlmClient();

    @Test
    void callOnce_returns_chatResponse() {
        AssistantMessage am = new AssistantMessage("hi");
        ChatResponse expected = new ChatResponse(List.of(new Generation(am)));
        // 注意:实现调 cc.prompt() 无参;deep-stubs 需匹配无参重载
        when(chatClient.prompt().system(any()).messages(anyList()).options(any()).call().chatResponse())
                .thenReturn(expected);

        ChatResponse got = llm.callOnce("sys", List.of(new UserMessage("hi")), chatClient, List.of());

        assertThat(got).isSameAs(expected);
    }

    @Test
    void streamFinal_returns_flux_content() {
        when(chatClient.prompt().system(any()).messages(anyList()).stream().content())
                .thenReturn(Flux.just("a", "b", "c"));

        List<String> out = llm.streamFinal("sys", List.of(new UserMessage("hi")), chatClient).collectList().block();

        assertThat(out).containsExactly("a", "b", "c");
    }
}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `mvn -q test -Dtest=LlmClientTest`
Expected: FAIL(方法 callOnce/streamFinal 不存在)

- [ ] **Step 3: 实现 LlmClient**

```java
package com.lab.reservation.ai.service;

import com.lab.reservation.common.result.ResultCode;
import com.lab.reservation.exception.BusinessException;
import io.github.resilience4j.circuitbreaker.annotation.CircuitBreaker;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.ai.openai.api.OpenAiApi;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Flux;

import java.util.List;

/**
 * LLM 调用出口 — callOnce(工具决策,非流,internalToolExecution 关闭)
 * + streamFinal(真流式收尾)+ testConnection(credential 验 key)。
 */
@Slf4j
@Service
public class LlmClient {

    /**
     * 阶段1:工具决策。internalToolExecutionEnabled=false 让模型只返回 toolCalls 不自动执行,
     * 编排器手动 dispatch + 拦截写工具确认。
     */
    @CircuitBreaker(name = "llm", fallbackMethod = "callOnceFallback")
    public ChatResponse callOnce(String sys, List<Message> history,
                                 ChatClient cc, List<ToolCallback> tools) {
        OpenAiChatOptions opts = OpenAiChatOptions.builder()
                .toolCallbacks(tools)
                .internalToolExecutionEnabled(false)
                .build();
        return cc.prompt()
                .system(sys)
                .messages(history)
                .options(opts)
                .call()
                .chatResponse();
    }

    /** 熔断 fallback:返合成空 ChatResponse(content=null,无 toolCalls),编排器走 EMPTY_RESPONSE。 */
    @SuppressWarnings("unused")
    public ChatResponse callOnceFallback(String sys, List<Message> history,
                                         ChatClient cc, List<ToolCallback> tools, Throwable t) {
        log.warn("LLM callOnce fallback: {}", t.getMessage());
        return new ChatResponse(List.of());
    }

    /**
     * 阶段2:最终回答。真流式,无 tools。
     */
    public Flux<String> streamFinal(String sys, List<Message> history, ChatClient cc) {
        return cc.prompt()
                .system(sys)
                .messages(history)
                .stream()
                .content();
    }

    /** 保存前真连一次验 key/model/base-url。失败不抛,返回 false。 */
    public boolean testConnection(String baseUrl, String apiKey, String model) {
        try {
            OpenAiApi api = OpenAiApi.builder().baseUrl(baseUrl).apiKey(apiKey).build();
            OpenAiChatOptions opt = OpenAiChatOptions.builder().model(model).build();
            org.springframework.ai.openai.OpenAiChatModel m =
                    org.springframework.ai.openai.OpenAiChatModel.builder().openAiApi(api).defaultOptions(opt).build();
            String reply = ChatClient.create(m).prompt().user("hi").call().content();
            return reply != null && !reply.isBlank();
        } catch (Exception e) {
            log.warn("LLM testConnection failed for base={} model={}: {}", baseUrl, model, e.toString());
            return false;
        }
    }
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `mvn -q test -Dtest=LlmClientTest`
Expected: PASS(2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/lab/reservation/ai/service/LlmClient.java src/test/java/com/lab/reservation/ai/service/LlmClientTest.java
git commit -m "feat(ai): LlmClient callOnce (internalToolExecution=false) + streamFinal"
```

---

## Task 3: ConversationService.buildPrompt — 重建 assistant + tool 消息(含无 currentText 重载)

**Files:**
- Modify: `src/main/java/com/lab/reservation/ai/service/ConversationService.java`(`buildPrompt` 方法)
- Test: `src/test/java/com/lab/reservation/ai/service/ConversationServiceTest.java`(新建)

**问题:** 现状只重建 user 消息,多轮上下文断裂。改:assistant 段也重建。**另:加无 `currentText` 重载** — 因 `AiAssistantService` 在调 `runLoop` 前已把 user 消息持久化,DB 查询已含它;若 runLoop 再传 `currentText` 追加 → 用户请求重复。故 runLoop 用 `buildPrompt(convId)` 重载(只从 DB 重建,不追加 currentText)。tool 段(role=tool)当前 appendMessage 不写,跳过。

- [ ] **Step 1: 写失败测试**

```java
package com.lab.reservation.ai.service;

import com.lab.reservation.ai.config.AiProperties;
import com.lab.reservation.entity.AiMessage;
import com.lab.reservation.mapper.AiConversationMapper;
import com.lab.reservation.mapper.AiMessageMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.UserMessage;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class ConversationServiceTest {

    @Mock AiConversationMapper convMapper;
    @Mock AiMessageMapper msgMapper;
    AiProperties props = new AiProperties();
    @InjectMocks ConversationService svc;

    @BeforeEach void setup() { props.setContextWindowTurns(10); }

    @Test
    void buildPrompt_includes_assistant_turns_not_just_user() {
        // 历史含 1 user + 1 assistant + 当前 user
        AiMessage u = msg("user", "我要预约显微镜");
        AiMessage a = msg("assistant", "好的,我帮您查");
        when(msgMapper.selectList(any())).thenReturn(List.of(a, u)); // DESC → 旧在后

        List<Message> out = svc.buildPrompt(1L, "明天下午");

        assertThat(out).hasSize(3); // assistant u + assistant a + 当前 user
        assertThat(out.get(0)).isInstanceOf(UserMessage.class);
        assertThat(out.get(1)).isInstanceOf(AssistantMessage.class);
        assertThat(out.get(2)).isInstanceOf(UserMessage.class);
    }

    private AiMessage msg(String role, String content) {
        AiMessage m = new AiMessage();
        m.setRole(role);
        m.setContent(content);
        return m;
    }
}
```

- [ ] **Step 2: 运行确认失败**

Run: `mvn -q test -Dtest=ConversationServiceTest`
Expected: FAIL(当前只重建 user → out 大小不对)

- [ ] **Step 3: 实现 buildPrompt(两版本)**

替换 `ConversationService.buildPrompt`,保留带 currentText 的旧版 + 加无 currentText 重载:
```java
/** 从 DB 重建最近窗口消息(user + assistant)。runLoop 用此版(currentText 已在 DB)。 */
public List<Message> buildPrompt(Long convId) {
    return buildPromptInternal(convId, false, null);
}

/** 旧版兼容:重建 + 追加 currentText(仅未提前持久化时用)。 */
public List<Message> buildPrompt(Long convId, String currentText) {
    return buildPromptInternal(convId, true, currentText);
}

private List<Message> buildPromptInternal(Long convId, boolean appendCurrent, String currentText) {
    int window = props.getContextWindowTurns();
    int fetch = Math.max(1, window * 2);
    List<AiMessage> recent = msgMapper.selectList(
            new QueryWrapper<AiMessage>()
                    .eq("conversation_id", convId)
                    .orderByDesc("created_at")
                    .last("LIMIT " + fetch)
    );
    Collections.reverse(recent); // 旧 → 新

    List<Message> out = new ArrayList<>();
    for (AiMessage m : recent) {
        String c = m.getContent() == null ? "" : m.getContent();
        switch (m.getRole()) {
            case "user" -> out.add(new UserMessage(c));
            case "assistant" -> out.add(new AssistantMessage(c));
            default -> { /* tool 段:appendMessage 当前不写 "tool" 角色,跳过 */ }
        }
    }
    if (appendCurrent && currentText != null) {
        out.add(new UserMessage(currentText));
    }
    return out;
}
```
import:`org.springframework.ai.chat.messages.AssistantMessage`

> **防重复:** `AiAssistantService` 在 runLoop 前 `appendMessage(convId,"user",text,...)` 已入库;runLoop 调 `buildPrompt(convId)`(无 currentText)→ DB 已含该 user 消息 → 不再追加。

- [ ] **Step 4: 运行确认通过**

Run: `mvn -q test -Dtest=ConversationServiceTest`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/lab/reservation/ai/service/ConversationService.java src/test/java/com/lab/reservation/ai/service/ConversationServiceTest.java
git commit -m "feat(ai): buildPrompt reconstructs assistant turns for multi-turn context"
```

---

## Task 4: ToolLoopOrchestrator — 骨架 + SuspendState + 读工具循环 + 阶段2

**Files:**
- Create: `src/main/java/com/lab/reservation/ai/service/ToolLoopOrchestrator.java`
- Test: `src/test/java/com/lab/reservation/ai/service/ToolLoopOrchestratorTest.java`

**核心:** 读工具(无 @ConfirmRequired)走完整循环;无 toolCall 进阶段2 真流式。

- [ ] **Step 1: 写失败测试(读工具路径)**

```java
package com.lab.reservation.ai.service;

import com.lab.reservation.ai.tool.ToolRegistry;
import com.lab.reservation.security.SecurityUserDetails;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import reactor.core.publisher.Flux;

import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class ToolLoopOrchestratorTest {

    @Mock LlmClient llm;
    @Mock ToolRegistry registry;
    @Mock ToolCallbackResolver resolver;
    @Mock ConversationService conversationService;
    @Mock ConfirmationService confirmationService;
    @Mock AiFrameService frameService;
    @Mock SystemPromptBuilder promptBuilder;
    @Mock ChatClient chatClient;
    @Mock SecurityUserDetails user;

    ToolLoopOrchestrator orch;

    @BeforeEach
    void setup() {
        orch = new ToolLoopOrchestrator(llm, registry, resolver, conversationService,
                confirmationService, frameService, promptBuilder);
        when(user.getUserId()).thenReturn(1L);
        when(promptBuilder.build(any(), anyLong())).thenReturn("sys");
    }

    @Test
    void no_tool_calls_runs_phase2_streaming_and_pushes_done() {
        // callOnce 返回无 toolCall 的纯文本回复
        ChatResponse resp = resp("好的,这是我的回答");
        when(llm.callOnce(any(), anyList(), any(), anyList())).thenReturn(resp);
        when(llm.streamFinal(any(), anyList(), any())).thenReturn(Flux.just("好的", "这是"));
        when(conversationService.buildPrompt(anyLong())).thenReturn(java.util.List.of(new UserMessage("hi")));

        orch.runLoop(chatClient, user, 1L, "你好");

        verify(frameService).push(eq(1L), eq(user), eq("delta"), anyMap());
        verify(frameService).push(eq(1L), eq(user), eq("assistant_done"), anyMap());
        verify(conversationService).appendMessage(eq(1L), eq("assistant"), anyString(), any(), anyInt());
    }

    private ChatResponse resp(String text) {
        return new ChatResponse(List.of(new Generation(new AssistantMessage(text))));
    }
}
```

- [ ] **Step 2: 运行确认失败**

Run: `mvn -q test -Dtest=ToolLoopOrchestratorTest`
Expected: FAIL(ToolLoopOrchestrator 不存在)

- [ ] **Step 3: 实现 Orchestrator 骨架 + 读路径 + 阶段2**

**关键设计(plan review 修):**
- **测试缝 `ToolCallbackResolver`**:把 `callbacksFor` 抽成接口注入。真 impl 做 Spring AI 反射;测试 stub 返回 mock ToolCallback。Orchestrator 不直接碰 MethodToolCallbackProvider → 可单测。
- **dispatch 用 `ToolCallback.call(String toolInput)`**(不手撸反射)。Spring AI 的 ToolCallback 自动处理参数名绑定、类型转换(Integer→Long)、JSON 序列化 → 修掉类型错配 + 非 JSON 两个问题。
- runLoop 用 `buildPrompt(convId)` 无 currentText 重载(防 user 消息重复)。
- runLoop 与 resume 共用 `runTurns(...)`(DRY)。

**先建 resolver 接口 + 真 impl:**

```java
// ToolCallbackResolver.java(接口)
public interface ToolCallbackResolver {
    /** 按用户角色返回 name→ToolCallback。 */
    Map<String, ToolCallback> resolve(SecurityUserDetails user);
}
```
```java
// ToolCallbackResolverImpl.java(@Service,真 impl)
@Service
@RequiredArgsConstructor
public class ToolCallbackResolverImpl implements ToolCallbackResolver {
    private final ToolRegistry registry;
    @Override
    public Map<String, ToolCallback> resolve(SecurityUserDetails user) {
        Object[] beans = registry.availableFor(user).stream()
                .map(ToolRegistry.ToolDefinition::bean).distinct().toArray();
        ToolCallback[] arr = MethodToolCallbackProvider.builder()
                .toolObjects(beans).build().getToolCallbacks();
        Map<String, ToolCallback> map = new LinkedHashMap<>();
        for (ToolCallback cb : arr) map.put(cb.getToolDefinition().name(), cb);
        return map;
    }
}
```

```java
package com.lab.reservation.ai.service;

import com.lab.reservation.ai.tool.ToolRegistry;
import com.lab.reservation.entity.AiToolExecution;
import com.lab.reservation.security.SecurityUserDetails;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.ToolResponseMessage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.method.MethodToolCallbackProvider;
import org.springframework.stereotype.Service;
import reactor.core.publisher.Flux;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicBoolean;

@Slf4j
@Service
@RequiredArgsConstructor
public class ToolLoopOrchestrator {

    static final int MAX_TURNS = 10;

    final LlmClient llm;
    final ToolRegistry registry;
    final ToolCallbackResolver resolver;
    final ConversationService conversationService;
    final ConfirmationService confirmationService;
    final AiFrameService frameService;
    final SystemPromptBuilder promptBuilder;

    final Map<Long, SuspendState> suspended = new ConcurrentHashMap<>();
    final Map<Long, AtomicBoolean> cancelFlags = new ConcurrentHashMap<>();

    public void runLoop(ChatClient cc, SecurityUserDetails user, Long convId, String text) {
        // text 已由 AiAssistantService 持久化;这里只从 DB 重建(防重复)
        List<Message> history = conversationService.buildPrompt(convId);
        runTurns(cc, user, convId, history, 0);
    }

    /** runLoop 与 continueLoop 共用的循环体(DRY)。 */
    void runTurns(ChatClient cc, SecurityUserDetails user, Long convId,
                  List<Message> history, int startTurn) {
        AtomicBoolean cancelled = cancelFlags.computeIfAbsent(convId, k -> new AtomicBoolean(false));
        if (startTurn == 0) cancelled.set(false);
        String sys = promptBuilder.build(SystemPromptBuilder.extractRole(user), user.getUserId());

        try {
            for (int turn = startTurn; turn < MAX_TURNS; turn++) {
                if (cancelled.get()) {
                    frameService.push(convId, user, "step_update",
                            Map.of("step_id", -1, "status", "cancelled", "text", "已取消"));
                    return;
                }
                Map<String, ToolCallback> cbMap = callbacksFor(user);
                ChatResponse resp = llm.callOnce(sys, history, cc, new ArrayList<>(cbMap.values()));
                AssistantMessage am = resp.getResult().getOutput();
                List<AssistantMessage.ToolCall> calls = am.getToolCalls() == null
                        ? List.of() : am.getToolCalls();

                if (calls.isEmpty()) {
                    String content = am.getText();
                    if (content == null || content.isBlank()) {
                        frameService.push(convId, user, "error",
                                Map.of("code", "EMPTY_RESPONSE", "msg", "AI 未返回内容"));
                        return;
                    }
                    phase2(cc, convId, user, sys, history, cancelled);
                    return;
                }
                if (turn == MAX_TURNS - 1 && !cancelled.get()) {
                    frameService.push(convId, user, "error",
                            Map.of("code", "TOO_MANY_TURNS", "msg", "工具调用轮次过多"));
                    return;
                }
                history.add(am); // 本轮 assistant(tool-calling)入 history

                for (AssistantMessage.ToolCall call : calls) {
                    ToolCallback cb = cbMap.get(call.name());
                    ToolRegistry.ToolDefinition def = registry.findById(call.name()).orElse(null);
                    if (cb == null || def == null) {
                        history.add(toolResp(call.id(), call.name(), "{\"error\":\"unknown tool\"}"));
                        continue;
                    }
                    if (def.confirmRequired()) {
                        suspendForConfirm(convId, user, call, def, history, turn);
                        return;
                    }
                    frameService.push(convId, user, "step_update",
                            Map.of("step_id", turn, "status", "running", "text", "执行 " + call.name()));
                    String result = dispatch(cb, call.arguments());
                    history.add(toolResp(call.id(), call.name(), result));
                }
            }
        } finally {
            cancelFlags.remove(convId);
        }
    }

    /** 阶段2 真流式收尾。 */
    void phase2(ChatClient cc, Long convId, SecurityUserDetails user, String sys,
                List<Message> history, AtomicBoolean cancelled) {
        frameService.push(convId, user, "step_update",
                Map.of("step_id", 0, "status", "started", "text", "正在生成回复"));
        StringBuilder reply = new StringBuilder();
        llm.streamFinal(sys, history, cc)
                .doOnNext(chunk -> {
                    if (cancelled.get()) return;
                    reply.append(chunk);
                    frameService.push(convId, user, "delta", Map.of("text", chunk));
                })
                .onErrorResume(err -> {
                    log.warn("streamFinal failed conv={}: {}", convId, err.getMessage());
                    frameService.push(convId, user, "error",
                            Map.of("code", "AI_UNAVAILABLE", "msg", "AI 助手暂时不可用"));
                    return Flux.empty();
                })
                .blockLast();
        String finalReply = reply.toString();
        if (!finalReply.isBlank()) {
            conversationService.appendMessage(convId, "assistant", finalReply, null, finalReply.length() / 2);
        }
        frameService.push(convId, user, "step_update",
                Map.of("step_id", 0, "status", "completed", "text", "完成"));
        frameService.push(convId, user, "assistant_done",
                Map.of("text", finalReply, "tool_calls", List.of()));
        frameService.push(convId, user, "suggestions",
                Map.of("items", List.of(
                        Map.of("label", "查看我的预约", "value", "查看我的预约"),
                        Map.of("label", "推荐设备", "value", "推荐设备"))));
    }

    /** name → ToolCallback 映射(委托 resolver 测试缝)。 */
    Map<String, ToolCallback> callbacksFor(SecurityUserDetails user) {
        return resolver.resolve(user);
    }

    /** 用 Spring AI ToolCallback.call 执行 — 自动处理类型转换 + JSON 序列化。 */
    String dispatch(ToolCallback cb, String argsJson) {
        try {
            return cb.call(argsJson);   // 返回 JSON String(ToolExecutionResult 序列化)
        } catch (Exception e) {
            log.warn("dispatch {} failed: {}", cb.getToolDefinition().name(), e.toString());
            return "{\"ok\":false,\"code\":\"TOOL_EXECUTION_FAILED\",\"msg\":\"" + e.getMessage() + "\"}";
        }
    }

    // Task 5 补:suspendForConfirm
    void suspendForConfirm(Long convId, SecurityUserDetails user,
                           AssistantMessage.ToolCall call, ToolRegistry.ToolDefinition def,
                           List<Message> history, int turn) {
        // Task 5 实现
    }

    static ToolResponseMessage toolResp(String id, String name, String data) {
        return new ToolResponseMessage(List.of(new ToolResponseMessage.ToolResponse(id, name, data)));
    }

    static String sha256(String s) {
        if (s == null) s = "";
        try {
            var md = java.security.MessageDigest.getInstance("SHA-256");
            byte[] h = md.digest(s.getBytes(java.nio.charset.StandardCharsets.UTF_8));
            var sb = new StringBuilder();
            for (byte b : h) sb.append(String.format("%02x", b));
            return sb.toString();
        } catch (Exception e) {
            return String.valueOf(s.hashCode());
        }
    }

    static final class SuspendState {
        final int turn;
        final List<Message> history;
        final String pendingCallId;
        final String pendingArgsHash;
        final SecurityUserDetails user;
        SuspendState(int turn, List<Message> history, String pendingCallId,
                     String pendingArgsHash, SecurityUserDetails user) {
            this.turn = turn; this.history = history;
            this.pendingCallId = pendingCallId; this.pendingArgsHash = pendingArgsHash;
            this.user = user;
        }
    }
}
```

> **`ToolCallback.call(String)` 签名** 以实际 API 为准(spike 验证:`ToolCallback`/`FunctionCallback` 有 `call(String toolInput)` 返 String)。若 1.0.6 签名为 `call(String, ToolContext)`,传 `null` context。

- [ ] **Step 4: 运行测试确认通过**

Run: `mvn -q test -Dtest=ToolLoopOrchestratorTest#no_tool_calls_runs_phase2_streaming_and_pushes_done`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/lab/reservation/ai/service/ToolLoopOrchestrator.java src/test/java/com/lab/reservation/ai/service/ToolLoopOrchestratorTest.java
git commit -m "feat(ai): ToolLoopOrchestrator skeleton — ToolCallback.call dispatch + phase2 streaming"
```

---

## Task 5: Orchestrator — 写工具挂起 + confirmation_required

**Files:**
- Modify: `ToolLoopOrchestrator.java`(实现 `suspendForConfirm`)
- Test: `ToolLoopOrchestratorTest.java`(加用例)

- [ ] **Step 1: 写失败测试(写工具挂起,不执行业务)**

```java
@Test
void write_tool_suspends_and_pushes_confirmation_required_without_executing() throws Exception {
    // LLM 第一轮决定调 createReservation(需确认)
    AssistantMessage am = new AssistantMessage("",
            Map.of(), // metadata
            List.of(new AssistantMessage.ToolCall("call_1", "function", "createReservation",
                    "{\"deviceId\":1,\"startTime\":\"2026-07-11T14:00:00\",\"endTime\":\"2026-07-11T16:00:00\"}")));
    when(llm.callOnce(any(), anyList(), any(), anyList()))
            .thenReturn(new ChatResponse(List.of(new Generation(am))));
    when(registry.findById("createReservation"))
            .thenReturn(Optional.of(confirmDef("createReservation")));
    // resolver 返回含 createReservation 的 mock callback(不会被 dispatch,因 confirmRequired)
    when(resolver.resolve(user))
            .thenReturn(Map.of("createReservation", mock(org.springframework.ai.tool.ToolCallback.class)));
    when(conversationService.buildPrompt(anyLong())).thenReturn(List.of(new UserMessage("hi")));

    orch.runLoop(chatClient, user, 1L, "帮我预约");

    // 关键:confirmationService.create 被调,推送 confirmation_required 帧
    verify(confirmationService).create(eq(1L), any(), eq("createReservation"), anyMap());
    verify(frameService).push(eq(1L), eq(user), eq("confirmation_required"), anyMap());
    // 写工具业务方法未被调用(挂起,dispatch 未触发)
    assertThat(orch.suspended).containsKey(1L);
}

private ToolRegistry.ToolDefinition confirmDef(String name) {
    // 构造 confirmRequired=true 的 ToolDefinition mock
    ToolRegistry.ToolDefinition d = mock(ToolRegistry.ToolDefinition.class);
    when(d.confirmRequired()).thenReturn(true);
    when(d.id()).thenReturn(name);
    when(d.confirmReason()).thenReturn("reason");
    when(d.confirmRisk()).thenReturn("risk");
    when(d.confirmImpact()).thenReturn("impact");
    return d;
}

private ToolRegistry.ToolDefinition executableDef() {
    // confirmRequired=false(可执行,不挂起)
    ToolRegistry.ToolDefinition d = mock(ToolRegistry.ToolDefinition.class);
    when(d.confirmRequired()).thenReturn(false);
    when(d.id()).thenReturn("createReservation");
    return d;
}
```

> 注:`AssistantMessage` 带 toolCalls 的构造器签名以实际 API 为准(Step 3 验证);若构造困难,用反射或 `AssistantMessage.builder()`。

- [ ] **Step 2: 运行确认失败**

Run: `mvn -q test -Dtest=ToolLoopOrchestratorTest#write_tool_suspends_and_pushes_confirmation_required_without_executing`
Expected: FAIL(suspendForConfirm 空实现)

- [ ] **Step 3: 实现 suspendForConfirm**

```java
void suspendForConfirm(Long convId, SecurityUserDetails user,
                       AssistantMessage.ToolCall call, ToolRegistry.ToolDefinition def,
                       List<Message> history, int turn) {
    Map<String, Object> args = parseArgs(call.arguments());
    Long actionId = confirmationService.create(convId, null, call.name(), args);
    String argsHash = sha256(call.arguments());

    suspended.put(convId, new SuspendState(turn, new ArrayList<>(history), call.id(), argsHash, user));

    frameService.push(convId, user, "step_update",
            Map.of("step_id", turn, "status", "awaiting_confirmation",
                    "text", "等待确认 " + call.name()));
    frameService.push(convId, user, "confirmation_required", Map.of(
            "action_id", actionId,
            "tool_name", call.name(),
            "reason", def.confirmReason(),
            "risk_summary", def.confirmRisk(),
            "estimated_impact", def.confirmImpact(),
            "args", args
    ));
    log.info("write tool {} suspended for conv={} actionId={}", call.name(), convId, actionId);
}

/** 把 LLM 返的 tool arguments JSON 解成 Map(给 confirmationService.create 存参)。 */
@SuppressWarnings("unchecked")
static Map<String, Object> parseArgs(String json) {
    if (json == null || json.isBlank()) return Map.of();
    try {
        return new com.fasterxml.jackson.databind.ObjectMapper().readValue(json, Map.class);
    } catch (Exception e) {
        return Map.of();
    }
}
```

> `sha256(...)` 已在 Task 4 定义,不重复。

- [ ] **Step 4: 运行确认通过**

Run: `mvn -q test -Dtest=ToolLoopOrchestratorTest#write_tool_suspends_and_pushes_confirmation_required_without_executing`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/lab/reservation/ai/service/ToolLoopOrchestrator.java src/test/java/com/lab/reservation/ai/service/ToolLoopOrchestratorTest.java
git commit -m "feat(ai): write tools suspend + push confirmation_required frame"
```

---

## Task 6: Orchestrator — handleConfirm resume + ToolResponseMessage + 续循环

> **PREREQ:** 先做 Task 8(confirmAndLoad owner 校验)。本 Task 的 resumeFromConfirm 调它。

**Files:**
- Modify: `ToolLoopOrchestrator.java`(加 `resumeFromConfirm`)
- Test: `ToolLoopOrchestratorTest.java`

**关键(spec review round 1 修):** resume 须把确认的工具结果入 history(ToolResponseMessage),LLM 续循环时才能准确复述写操作结果。

- [ ] **Step 1: 写失败测试**

```java
@Test
void confirm_resumes_appends_tool_response_and_continues_to_phase2() throws Exception {
    // 预置挂起态(argsHash 用真实 row.arguments 的 sha256,免 ARGS_CHANGED 误判)
    String argsJson = "{\"deviceId\":1,\"startTime\":\"2026-07-11T14:00:00\",\"endTime\":\"2026-07-11T16:00:00\"}";
    orch.suspended.put(1L, new ToolLoopOrchestrator.SuspendState(
            0, new ArrayList<>(List.of(new UserMessage("hi"))), "call_1",
            ToolLoopOrchestrator.sha256(argsJson), user));

    // confirmAndLoad(mock,owner 校验在 Task 8 单测里验;此处返 row)
    AiToolExecution row = new AiToolExecution();
    row.setId(77L); row.setConversationId(1L);
    row.setToolName("createReservation");
    row.setArguments(argsJson);
    row.setStatus("pending");
    when(confirmationService.confirmAndLoad(77L, 1L)).thenReturn(row);

    // 续循环第二轮 callOnce → 无 toolCall → phase2
    when(llm.callOnce(any(), anyList(), any(), anyList()))
            .thenReturn(resp("已为您预约成功,预约号 123"));
    when(llm.streamFinal(any(), anyList(), any())).thenReturn(Flux.just("已预约"));
    // resolver 返回 mock callback,.call 返成功 JSON
    org.springframework.ai.tool.ToolCallback cb = mock(org.springframework.ai.tool.ToolCallback.class);
    when(cb.call(anyString())).thenReturn("{\"ok\":true,\"data\":{\"reservation_id\":123}}");
    when(resolver.resolve(user)).thenReturn(Map.of("createReservation", cb));

    orch.resumeFromConfirm(chatClient, user, 77L);

    verify(confirmationService).execute(eq(77L), any());
    verify(frameService).push(eq(1L), eq(user), eq("execution_result"), anyMap());
    verify(frameService).push(eq(1L), eq(user), eq("assistant_done"), anyMap());
    assertThat(orch.suspended).doesNotContainKey(1L);
}
```

- [ ] **Step 2: 运行确认失败**

Run: `mvn -q test -Dtest=ToolLoopOrchestratorTest#confirm_resumes_appends_tool_response_and_continues_to_phase2`
Expected: FAIL(resumeFromConfirm 不存在)

- [ ] **Step 3: 实现 resumeFromConfirm(复用 runTurns)**

```java
public void resumeFromConfirm(ChatClient cc, SecurityUserDetails user, Long actionId) {
    AiToolExecution row = confirmationService.confirmAndLoad(actionId, user.getUserId());
    if (row == null) {
        frameService.push(null, user, "error",
                Map.of("code", "FORBIDDEN", "msg", "无权操作或状态非法"));
        return;
    }
    SuspendState st = suspended.get(row.getConversationId());
    if (st == null) {
        fallbackSingleExec(cc, user, actionId, row);
        return;
    }
    if (!st.pendingArgsHash.equals(sha256(row.getArguments()))) {
        frameService.push(row.getConversationId(), user, "error",
                Map.of("code", "ARGS_CHANGED", "msg", "确认参数已变化,请重新发起"));
        suspended.remove(row.getConversationId());
        return;
    }
    Map<String, ToolCallback> cbMap = callbacksFor(user);
    ToolCallback cb = cbMap.get(row.getToolName());
    if (cb == null) {
        confirmationService.error(actionId, "tool vanished");
        frameService.push(row.getConversationId(), user, "error",
                Map.of("code", "TOOL_EXECUTION_FAILED", "msg", "工具已失效"));
        suspended.remove(row.getConversationId());
        return;
    }
    frameService.push(row.getConversationId(), user, "step_update",
            Map.of("status", "running", "text", "执行 " + row.getToolName()));
    String result = dispatch(cb, row.getArguments());
    confirmationService.execute(actionId, result);
    frameService.push(row.getConversationId(), user, "execution_result",
            Map.of("action_id", actionId, "ok", true, "result", result));

    // 关键:把确认的工具结果入 history,续循环时 LLM 才能准确复述(spec review round1 修)
    st.history.add(toolResp(st.pendingCallId, row.getToolName(), result));
    suspended.remove(row.getConversationId());

    // 复用 runTurns 续跑(DRY):从 st.turn 起,history 已含 tool 结果
    runTurns(cc, user, row.getConversationId(), st.history, st.turn);
}

void fallbackSingleExec(ChatClient cc, SecurityUserDetails user, Long actionId, AiToolExecution row) {
    Map<String, ToolCallback> cbMap = callbacksFor(user);
    ToolCallback cb = cbMap.get(row.getToolName());
    boolean ok = cb != null;
    String result = ok ? dispatch(cb, row.getArguments()) : "{\"error\":\"tool vanished\"}";
    confirmationService.execute(actionId, result);
    frameService.push(row.getConversationId(), user, "execution_result",
            Map.of("action_id", actionId, "ok", ok, "result", result));
    // 终态帧,否则前端卡 executing(spec review round1 修)
    frameService.push(row.getConversationId(), user, "step_update",
            Map.of("status", "completed", "text", "完成"));
    frameService.push(row.getConversationId(), user, "assistant_done",
            Map.of("text", "操作已完成(会话上下文已失效,无法续答)", "tool_calls", List.of()));
}
```

> runTurns 已在 Task 4 实现,runLoop 与 resume 共用,无需 continueLoop(DRY)。

- [ ] **Step 4: 运行确认通过**

Run: `mvn -q test -Dtest=ToolLoopOrchestratorTest`
Expected: PASS(所有用例)

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/lab/reservation/ai/service/ToolLoopOrchestrator.java src/test/java/com/lab/reservation/ai/service/ToolLoopOrchestratorTest.java
git commit -m "feat(ai): confirm resume — append ToolResponseMessage + continue loop to phase2"
```

---

## Task 7: Orchestrator — handleCancel + BUSY 并发 + owner/argsHash 已覆盖

**Files:**
- Modify: `ToolLoopOrchestrator.java`(加 `cancelAction`、`isSuspended`)
- Test: `ToolLoopOrchestratorTest.java`

- [ ] **Step 1: 写失败测试**

```java
@Test
void cancel_action_removes_suspend_and_cancels_row() {
    orch.suspended.put(1L, new ToolLoopOrchestrator.SuspendState(0, new ArrayList<>(), "c1", "h", user));
    orch.cancelAction(user, 77L, 1L);
    assertThat(orch.suspended).doesNotContainKey(1L);
    verify(confirmationService).cancel(77L);
    verify(frameService).push(eq(1L), eq(user), eq("execution_result"), anyMap());
}

@Test
void is_suspended_true_means_busy() {
    orch.suspended.put(1L, new ToolLoopOrchestrator.SuspendState(0, new ArrayList<>(), "c1", "h", user));
    assertThat(orch.isSuspended(1L)).isTrue();
}
```

- [ ] **Step 2: 运行确认失败**

Run: `mvn -q test -Dtest=ToolLoopOrchestratorTest#cancel_action_removes_suspend_and_cancels_row+is_suspended_true_means_busy`
Expected: FAIL

- [ ] **Step 3: 实现**

```java
public boolean isSuspended(Long convId) {
    return suspended.containsKey(convId);
}

public void cancelAction(SecurityUserDetails user, Long actionId, Long convId) {
    confirmationService.cancel(actionId);
    suspended.remove(convId);
    cancelFlags.computeIfAbsent(convId, k -> new AtomicBoolean(false)).set(true);
    frameService.push(convId, user, "execution_result",
            Map.of("action_id", actionId, "ok", false, "cancelled", true));
}
```

- [ ] **Step 4: 运行确认通过**

Run: `mvn -q test -Dtest=ToolLoopOrchestratorTest`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/lab/reservation/ai/service/ToolLoopOrchestrator.java src/test/java/com/lab/reservation/ai/service/ToolLoopOrchestratorTest.java
git commit -m "feat(ai): cancel action + isSuspended busy check"
```

---

## Task 8: ConfirmationService — confirm owner 校验(经 conversation,**零 schema 变更**)

> **放在 resume(Task 6/7)之前做**(见 Task Dependency Order)。

**Files:**
- Modify: `src/main/java/com/lab/reservation/ai/service/ConfirmationService.java`
- Modify: `src/test/java/com/lab/reservation/ai/service/ConfirmationServiceTest.java`

**设计(plan review 修):** `AiToolExecution` **无 userId 列**(已验证 entity)。为遵守 spec"零 schema 变更",owner 校验经 `conversationId → AiConversation.userId` 解析:**不**给 ai_tool_execution 加列。加 `confirmAndLoad(actionId, requesterUserId)`:load row → `conversationService.getOrThrow(convId).getUserId()` 比对 requester。不符或状态非法返 null(调用方推 FORBIDDEN)。

> 依赖:`ConfirmationService` 注入 `ConversationService`(当前未注,加构造参 / `@RequiredArgsConstructor` 字段)。

- [ ] **Step 1: 写失败测试**

```java
@ExtendWith(MockitoExtension.class)
class ConfirmationServiceTest {
    @Mock AiToolExecutionMapper mapper;
    @Mock ConversationService conversationService;
    @Mock ObjectMapper objectMapper;
    ConfirmationService svc;

    @BeforeEach void setup() {
        svc = new ConfirmationService(mapper, objectMapper, conversationService);
    }

    @Test
    void confirmAndLoad_returns_null_when_not_owner() {
        AiToolExecution row = pendingRow(77L, 1L);     // 属 conv 1
        AiConversation conv = new AiConversation(); conv.setUserId(1L);
        when(mapper.selectById(77L)).thenReturn(row);
        when(conversationService.getOrThrow(1L)).thenReturn(conv);

        AiToolExecution got = svc.confirmAndLoad(77L, 999L);   // requester 999

        assertThat(got).isNull();
        verify(mapper, never()).updateById(any());
    }

    @Test
    void confirmAndLoad_confirms_when_owner() {
        AiToolExecution row = pendingRow(77L, 1L);
        AiConversation conv = new AiConversation(); conv.setUserId(1L);
        when(mapper.selectById(77L)).thenReturn(row);
        when(conversationService.getOrThrow(1L)).thenReturn(conv);

        AiToolExecution got = svc.confirmAndLoad(77L, 1L);

        assertThat(got).isNotNull();
        assertThat(got.getStatus()).isEqualTo("confirmed");
    }

    private AiToolExecution pendingRow(Long id, Long convId) {
        AiToolExecution e = new AiToolExecution();
        e.setId(id); e.setConversationId(convId); e.setStatus("pending");
        e.setToolName("createReservation"); e.setArguments("{}");
        return e;
    }
}
```

- [ ] **Step 2: 运行确认失败**

Run: `mvn -q test -Dtest=ConfirmationServiceTest`
Expected: FAIL(confirmAndLoad 不存在 / 构造器不符)

- [ ] **Step 3: 实现 confirmAndLoad**

`ConfirmationService` 加 `ConversationService` 依赖 + 方法:
```java
@RequiredArgsConstructor  // 现有;新字段自动入构造
public class ConfirmationService {
    private final AiToolExecutionMapper mapper;
    private final ObjectMapper objectMapper;
    private final ConversationService conversationService;   // 新增

    /**
     * owner 校验(actionId → convId → AiConversation.userId vs requester)+ pending→confirmed。
     * 不符 / 状态非法返 null(调用方推 FORBIDDEN)。零 schema 变更。
     */
    public AiToolExecution confirmAndLoad(Long actionId, Long requesterUserId) {
        AiToolExecution e = mapper.selectById(actionId);
        if (e == null) return null;
        if (!STATUS_PENDING.equals(e.getStatus())) return null;
        AiConversation conv = conversationService.getOrThrow(e.getConversationId());
        if (conv.getUserId() == null || !conv.getUserId().equals(requesterUserId)) return null;
        e.setStatus(STATUS_CONFIRMED);
        e.setUserConfirmedAt(LocalDateTime.now());
        mapper.updateById(e);
        return e;
    }

    /** 按 id 取 row(onExpire 等无 user 上下文路径用)。 */
    public AiToolExecution getRow(Long actionId) {
        return mapper.selectById(actionId);
    }
    // ... 既有 create/execute/cancel/error/expireOldPending 不变
}
```

- [ ] **Step 4: 运行确认通过**

Run: `mvn -q test -Dtest=ConfirmationServiceTest`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/lab/reservation/ai/service/ConfirmationService.java src/test/java/com/lab/reservation/ai/service/ConfirmationServiceTest.java
git commit -m "feat(ai): confirmAndLoad with owner check via conversation (zero schema change)"
```

---

## Task 9: AiActionTimeoutScheduler — expire 清挂起态 + confirmation_expired 帧

**Files:**
- Modify: `src/main/java/com/lab/reservation/ai/task/AiActionTimeoutScheduler.java`
- Test: `src/test/java/com/lab/reservation/ai/task/`(若无 scheduler 测试则新建)

**设计:** `expireOldPending` 后,对每个 expired 的 actionId 调 `orchestrator.onExpire(convId, actionId, user)` → `suspended.remove(convId)` + 推 `confirmation_expired` 帧。但 scheduler 无 user 上下文。简化:orchestrator 暴露 `onExpire(Long convId, Long actionId)`,内部 load row 拿 userId 造 SecurityUserDetails(或 frameService.push 改造接受 userId 而非 user)。

- [ ] **Step 1: 读现有 scheduler + AiToolExecution 字段确认**

Run: `cat src/main/java/com/lab/reservation/ai/task/AiActionTimeoutScheduler.java`
确认 `expireOldPending` 签名 + 返回的行含 convId。

- [ ] **Step 2: 写失败测试**

```java
@Test
void on_expire_removes_suspend_and_pushes_expired_frame() {
    orch.suspended.put(1L, new ToolLoopOrchestrator.SuspendState(0, new ArrayList<>(), "c1", "h", user));
    // onExpire 经 confirmationService.getRow + conversationService.getOrThrow 取 userId
    AiToolExecution row = new AiToolExecution();
    row.setId(77L); row.setConversationId(1L);
    when(confirmationService.getRow(77L)).thenReturn(row);
    AiConversation conv = new AiConversation(); conv.setUserId(1L);
    when(conversationService.getOrThrow(1L)).thenReturn(conv);

    orch.onExpire(1L, 77L);

    assertThat(orch.suspended).doesNotContainKey(1L);
    verify(frameService).pushByUser(eq(1L), eq(1L), eq("confirmation_expired"), anyMap());
}
```

- [ ] **Step 3: 实现 onExpire + 接线 scheduler**

`ToolLoopOrchestrator.onExpire`(经 confirmationService 拿 row → userId):
```java
public void onExpire(Long convId, Long actionId) {
    suspended.remove(convId);
    // 经 confirmationService 拿 row 的 convId → conversationService 拿 owner userId
    AiToolExecution row = confirmationService.getRow(actionId);
    Long userId = null;
    if (row != null && row.getConversationId() != null) {
        try { userId = conversationService.getOrThrow(row.getConversationId()).getUserId(); }
        catch (Exception ignore) {}
    }
    frameService.pushByUser(convId, userId, "confirmation_expired",
            Map.of("action_id", actionId, "reason", "PENDING_TIMEOUT"));
    log.info("expired action {} conv {} suspended cleared", actionId, convId);
}
```
> 注:`ConfirmationService` 需暴露 `getRow(actionId)`(= `mapper.selectById`,加 public 方法);`AiToolExecution` 已有 getConversationId。

`AiFrameService` 加 `pushByUser(Long convId, Long userId, String type, Map payload)` —— 把现有 `push` 的 seq+持久化+推送逻辑抽出,接受 userId 而非 SecurityUserDetails:
```java
/** 现有 push(convId, user, type, payload) 委托此版。 */
public void push(Long convId, SecurityUserDetails user, String type, Map<String, Object> payload) {
    pushByUser(convId, user.getUserId(), type, payload);
}

/** userId 版:scheduler 等无 user 上下文的路径用。 */
public void pushByUser(Long convId, Long userId, String type, Map<String, Object> payload) {
    Long seq = null;
    try { seq = redis.opsForValue().increment("ai:ws:seq:" + convId); }
    catch (RuntimeException e) { log.warn("seq INCR failed conv={}: {}", convId, e.toString()); }
    if (seq == null) seq = 1L;

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
```
(原 `push` 内联实现替换为委托 `pushByUser`;`toJson` 既有。)

`AiActionTimeoutScheduler.expireOldPending` 调用处补:
```java
old.forEach(e -> {
    e.setStatus(STATUS_EXPIRED);
    e.setErrorMessage("PENDING_TIMEOUT");
    mapper.updateById(e);
    orchestrator.onExpire(e.getConversationId(), e.getId());
});
```

- [ ] **Step 4: 运行确认通过**

Run: `mvn -q test -Dtest=ToolLoopOrchestratorTest#on_expire_removes_suspend_and_pushes_expired_frame`
Expected: PASS

> 测试里 `onExpire` 调 `confirmationService.getRow(anyLong)` + `conversationService.getOrThrow(anyLong)` 需 stub 返回 row/conv(含 userId);frameService 用 `pushByUser` 重载,verify 它。

- [ ] **Step 5: Commit**

```bash
git add src/main/java/com/lab/reservation/ai/service/ToolLoopOrchestrator.java \
        src/main/java/com/lab/reservation/ai/service/AiFrameService.java \
        src/main/java/com/lab/reservation/ai/task/AiActionTimeoutScheduler.java \
        src/test/java/com/lab/reservation/ai/service/ToolLoopOrchestratorTest.java
git commit -m "feat(ai): expire clears suspended + pushes confirmation_expired frame"
```

---

## Task 10: AiAssistantService — 瘦身委托 + wire orchestrator

**Files:**
- Modify: `src/main/java/com/lab/reservation/ai/service/AiAssistantService.java`
- Modify: `src/test/java/com/lab/reservation/ai/service/AiAssistantServiceTest.java`

**设计:** AiAssistantService 保留:限流 / 会话创建校验 / SecurityContext 注入 / per-user ChatClient resolve / BUSY 守卫。循环委托 `orchestrator.runLoop`。handleConfirm/handleCancel 转 `resumeFromConfirm`/`cancelAction`。

- [ ] **Step 1: 改 AiAssistantService.handleUserMessage 主路径**

```java
public void handleUserMessage(SecurityUserDetails user, Long convIdIn, String text) {
    // 1. 限流(按对话轮次)
    if (!rateLimitService.tryConsume(user.getUserId())) {
        frameService.push(null, user, "error", Map.of("code", "RATE_LIMIT", "msg", "AI 正在处理上一条消息,请稍候再发"));
        return;
    }
    // 2. SecurityContext 注入(保留现有 prev/finally 逻辑)
    Authentication prev = SecurityContextHolder.getContext().getAuthentication();
    UsernamePasswordAuthenticationToken auth =
            new UsernamePasswordAuthenticationToken(user, null, user.getAuthorities());
    // 3. 会话
    final Long convId;
    if (convIdIn == null) {
        convId = conversationService.create(user.getUserId()).getId();
    } else {
        try { conversationService.getOrThrow(convIdIn); }
        catch (Exception e) {
            frameService.push(convIdIn, user, "error", Map.of("code", "CONV_NOT_FOUND", "msg", "会话不存在"));
            return;
        }
        convId = convIdIn;
    }
    try {
        SecurityContextHolder.getContext().setAuthentication(auth);
        // 4. BUSY 守卫:挂起中或发送/流式中再发 → 拒
        if (orchestrator.isSuspended(convId)) {
            frameService.push(convId, user, "error", Map.of("code", "BUSY", "msg", "有待确认操作,请先处理"));
            return;
        }
        // 5. per-user ChatClient
        ChatClient cc = userChatClientProvider.resolve(user.getUserId()).orElse(null);
        if (cc == null) {
            frameService.push(convId, user, "error", Map.of("code", "AI_NOT_CONFIGURED",
                    "msg", "请先配置你的 AI API Key", "action", "open_settings"));
            return;
        }
        // 6. 持久化 user 消息
        conversationService.appendMessage(convId, "user", text, null, text.length() / 2);
        frameService.push(convId, user, "step_update",
                Map.of("step_id", 0, "status", "started", "text", "正在处理您的请求"));
        // 7. 委托循环
        orchestrator.runLoop(cc, user, convId, text);
    } finally {
        SecurityContextHolder.getContext().setAuthentication(prev);
    }
}

public void handleConfirm(SecurityUserDetails user, Long actionId) {
    Authentication prev = SecurityContextHolder.getContext().getAuthentication();
    try {
        SecurityContextHolder.getContext().setAuthentication(
                new UsernamePasswordAuthenticationToken(user, null, user.getAuthorities()));
        ChatClient cc = userChatClientProvider.resolve(user.getUserId()).orElse(null);
        if (cc == null) {
            frameService.push(null, user, "error", Map.of("code", "AI_NOT_CONFIGURED", "msg", "AI 未配置"));
            return;
        }
        orchestrator.resumeFromConfirm(cc, user, actionId);
    } finally {
        SecurityContextHolder.getContext().setAuthentication(prev);
    }
}

public void handleCancel(SecurityUserDetails user, Long actionId, Long convId) {
    orchestrator.cancelAction(user, actionId, convId);
}
```

> `WsClientMsg.CancelAction` 需含 convId — 检查 dto,若无补字段 + 前端 sendAiMsg 补。

- [ ] **Step 2: 更新 AiAssistantServiceTest 适配新签名**

把现有 mock 循环的用例改为验证 `orchestrator.runLoop` 被调 + 限流/会话/守卫分支。删掉测内部循环的用例(已移到 OrchestratorTest)。

- [ ] **Step 3: 运行确认通过**

Run: `mvn -q test -Dtest=AiAssistantServiceTest`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/main/java/com/lab/reservation/ai/service/AiAssistantService.java \
        src/main/java/com/lab/reservation/ai/dto/WsClientMsg.java \
        src/test/java/com/lab/reservation/ai/service/AiAssistantServiceTest.java
git commit -m "refactor(ai): AiAssistantService thins to delegations + BUSY guard"
```

---

## Task 11: 前端 — ai.ts execution_result 失败态 + AiAssistant BUSY

**Files:**
- Modify: `frontend/src/stores/ai.ts`
- Modify: `frontend/src/components/ai/AiAssistant.vue`

- [ ] **Step 1: ai.ts handleFrame execution_result 补 state idle**

现有(L88-92):
```ts
case 'execution_result':
  markConfirmation(frame.action_id, frame.ok ? 'executed' : 'error')
  if (frame.ok) state.value = 'done'
  else state.value = 'error'
  break
```
改:`ok=false` 且 `cancelled=true` → state 回 idle(用户主动取消不算错误):
```ts
case 'execution_result':
  markConfirmation(frame.action_id, frame.ok ? 'executed' : 'error')
  state.value = frame.ok ? 'done' : (frame.cancelled ? 'idle' : 'error')
  break
```

- [ ] **Step 2: AiAssistant.vue — BUSY 错误不弹设置面板**

`needsConfig` computed 只在 `AI_NOT_CONFIGURED` 为 true。BUSY 不命中,无需改。确认即可。

- [ ] **Step 3: sendAiMsg cancel_action 补 convId**

`useAiWebSocket.ts` 的 `sendAiMsg` switch 里 `cancel_action` 已转发 body。确认 `WsClientMsg.CancelAction` 含 convId 并在 `cancelAction()` 传:
```ts
function cancelAction(actionId: number) {
  markConfirmation(actionId, 'cancelled')
  state.value = 'idle'
  sendAiMsg({ kind: 'cancel_action', actionId, convId: convId.value })
}
```

- [ ] **Step 4: 类型检查**

Run: `cd frontend && pnpm build`
Expected: vue-tsc 通过

- [ ] **Step 5: Commit**

```bash
cd frontend && git add src/stores/ai.ts src/components/ai/AiAssistant.vue src/composables/useAiWebSocket.ts
git commit -m "feat(ai-fe): cancelled confirmation returns idle; cancel_action carries convId"
```

---

## Task 12: e2e 联调验证

**Files:** 无(手动验证)

- [ ] **Step 1: 起依赖**

```bash
docker compose up -d   # mysql + redis
mvn spring-boot:run    # dev profile, siliconflow 默认 key
cd frontend && pnpm dev
```

- [ ] **Step 2: 登录学生账号,开 AI 球**

确认无 AI_NOT_CONFIGURED(dev 兜底生效)。

- [ ] **Step 3: 读场景**

输入:"我有哪些预约?"
预期:step_update(started)→(若 LLM 调 searchMyReservations)step_update(执行)→ delta 真流式逐字 → assistant_done。
验证:首字延迟 < 3s(真流式生效);回复含真实预约数据。

- [ ] **Step 4: 写场景(核心)**

输入:"帮我预约设备 #1 明天 14:00 到 16:00"
预期:
- LLM 决定调 createReservation(需确认)
- ConfirmationCard 弹出,显示 {reason, risk, impact, args:{deviceId:1,start,end}}
- 数据库 reservation 表**此时无新行**(未确认不执行)
- 点"确认" → step_update(执行)→ execution_result{ok:true, reservation_id:N}
- 续回答:delta 流式 "已为您预约成功..." → assistant_done
- 数据库 reservation 表**此时有新行**,status=PENDING/APPROVED

- [ ] **Step 5: 取消场景**

重新触发确认卡 → 点"取消"
预期:execution_result{ok:false, cancelled:true} → 卡片关闭 → state idle → DB 无新行、ai_tool_execution.status=CANCELLED。

- [ ] **Step 6: 失败回放**

输入:"帮我预约设备 #999999(不存在)明天 14-16 点"
预期:LLM 调 → 确认卡 → 点确认 → dispatch 抛 → execution_result{ok:false} → LLM 续循环解释"设备不存在"。

- [ ] **Step 7: 限流不误伤**

连续问 5 个读问题,确认不被 RATE_LIMIT(原 4 个就触发的误伤消除)。

- [ ] **Step 8: 记录结果**

把联调结果(截图/日志)记入 commit message 或 PR 描述。

---

## 全量回归

- [ ] **Step 9: 后端全测**

Run: `mvn -q test`
Expected: 全绿(含原有 18 个 AI 测 + 新增)

- [ ] **Step 10: 前端全测**

Run: `cd frontend && pnpm test`
Expected: 全绿

- [ ] **Step 11: 最终 commit(若有零散改动)**

```bash
git add -A
git commit -m "test(ai): e2e verification — tool loop + confirmation + streaming confirmed"
```

---

## 风险提示(实现时)

1. **Spring AI fluent API mock 痛苦** → LlmClientTest 用 `RETURNS_DEEP_STUBS`,Orchestrator 测试 mock LlmClient(不碰 ChatClient)。
2. **internalToolExecutionEnabled(false) 行为** → e2e Step 4 验证模型真返 toolCalls 不自动执行。若失效(工具仍自动跑),回退方案:不用 `.options()`,改用低层 `OpenAiChatModel.call(Prompt)` 直接构造。
3. **AssistantMessage 带 toolCalls 构造** → 测试里若构造器不可用,用 `AssistantMessage.builder()` 或反射设字段。
4. **DRY** → runLoop 与 continueLoop 的 for 体重复,抽 `runTurns(...)` 私有方法复用,避免维护两份。
5. **owner 校验零 schema** → `AiToolExecution` 无 userId 列(已验证)。owner 经 `conversationId → AiConversation.userId` 解析(Task 8 confirmAndLoad),**不需 V7 迁移**。若实测发现 `AiConversation.userId` 为空(异常数据),owner 校验返 null → 推 FORBIDDEN,不推进状态(安全失败)。
