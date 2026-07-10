# AI 助手 P0 修复设计

**日期**: 2026-07-10
**范围**: P0 only — A1 工具循环+确认拦截 / A2 真流式 / B1+B2 工具反馈 / B3 限流误伤
**目标**: 让 AI 助手真正能"代预约"——写操作经用户二次确认后落库,真流式输出,不误伤正常用户。毕设答辩级可用。
**架构路径**: 方案 3 显式 agent 循环(手撸 tool dispatch)
**验证**: 端到端联调(dev profile + siliconflow 默认 key)

---

## 1. 问题陈述

当前 AI 助手是"伪 agent 的 chatbot",4 个 P0 缺陷:

- **A1 工具循环+确认拦截缺失**: `AiAssistantService` 注释自承"没接工具循环,1 轮后退出",`assistant_done` 帧写死 `tool_calls: []`。更严重:Spring AI 1.0.6 `ChatClient.call(toolCallbacks)` 实际会自动跑工具循环,但 `@ConfirmRequired` 注解无任何拦截层 → 写工具(createReservation/cancelReservation/submitRepairTicket/takeRepairTicket)被 LLM 决定调用时**直接执行业务,绕过二次确认**,整条安全设计形同虚设。
- **A2 伪流式**: `LlmClient.stream` 用 `.call().content()` 拿完整文本再按 12 字切片。首字延迟 = 整段生成时长,无打字机效果。
- **B1+B2 工具反馈断裂**: LLM 拿不到结构化工具结果,只能基于训练数据虚构"已为您预约"。用户去"我的预约"找不到 → 信任崩塌。
- **B3 限流误伤**: `RateLimitService` 按 WS 请求扣 token。一次"代预约"含多轮工具 + 流式收尾 = 多次 LLM 调用,用户连问几句即 RATE_LIMIT。

附加(顺带修,服务于 P0):`ConversationService.buildPrompt` 仅重建 user 消息,丢弃 assistant+tool 轮次 → 多轮上下文断裂;`ToolArgumentValidator` 用 `p.getName()` 未加 `-parameters` 编译 → 参数名退化 arg0。

## 2. 架构总览:显式 agent 循环

从 `AiAssistantService` 抽出循环逻辑到新组件 `ToolLoopOrchestrator`。`AiAssistantService` 变薄,保留入口职责(限流/会话/SecurityContext/per-user ChatClient)。

### 主循环 `handleUserMessage`

```
handleUserMessage(user, convId, text):
  限流检查(按对话轮次,见 §4)
  建会话或校验
  注 SecurityContext(保留现状,tool 内 SecurityContextHolder 取用户)
  resolve per-user ChatClient(无 key → AI_NOT_CONFIGURED 帧,保留现状)
  持久化 user 消息
  cancelFlags 重置
  for turn in 0..MAX_TURNS(=10):
    if cancelled: 推 step_update(cancelled), break
    ChatResponse resp = llmClient.callOnce(sys, history, userClient, toolDefs)   // 非流,带 tools
    List<ToolCall> calls = resp.toolCalls()
    // 熔断 fallback / 模型空答:content 空 + 无 toolCalls → EMPTY_RESPONSE,不浪费一次 streamFinal
    if calls.empty && (resp.content() == null || resp.content().isBlank()):
       推 error{EMPTY_RESPONSE}; break
    if calls.empty:
       脱离 for,进入阶段2 真流式收尾
    // 调 callOnce 前先把上轮 assistant(tool-calling)消息入 history,保证 LLM 看得见自己上一轮的 tool 请求
    for call in calls:
       ToolDefinition def = registry.findById(call.name)
       if def.confirmRequired:
          actionId = confirmationService.create(convId, msgId, call.name, call.args)
          argsHash = sha256(json(call.args))
          推 step_update(tool: <name> 等待确认)
          推 confirmation_required 帧 {actionId, tool_name, reason, risk_summary, estimated_impact, args}
          挂起循环: suspended.put(convId, SuspendState{
              turn, history(含本轮 AssistantMessage+其 ToolCall),
              pendingCallId: call.id,
              pendingArgsHash: argsHash,
              user
          })
          return   // 等用户确认
       else:
          推 step_update(tool: <name> 执行中)
          result = dispatch(def, call.args)   // 反射 bean.method
          追加 ToolResponseMessage(history, call.id, result)
    // 一轮 tool 调完,for turn 继续(让 LLM 看 tool 结果再决定)

  // MAX_TURNS 防失控:仍有 toolCall 却超轮数(cancel 早退已 break,不会误触)
  if !calls.empty && turn == MAX_TURNS-1 && !cancelled:
     推 error{TOO_MANY_TURNS}; break

  // 阶段2 真流式收尾:
  // 注意:触发阶段2 的那轮 callOnce 返回的 ChatResponse 其 content **丢弃不入 history**
  // (它带 tools,无法流式);streamFinal 不带 tools **重新生成**最终回答。
  // 故一次对话 LLM 调用数 = toolTurns + 1(收尾),规划估时按此。
  llmClient.streamFinal(sys, history, userClient)
     .doOnNext(chunk -> { if cancelled return; reply.append(chunk); 推 delta 帧 })
     .onErrorResume(err -> { 推 error(AI_UNAVAILABLE); Flux.empty() })
     .blockLast()
  持久化 assistant 回复
  推 step_update(completed) + assistant_done{text, tool_calls} + suggestions
```

### 确认恢复路径 `handleConfirm`(真正干活)

```
handleConfirm(user, actionId):
  row = load(actionId)
  if row.userId != user.userId: 推 error(FORBIDDEN); return   // owner 校验
  SuspendState st = suspended.get(row.convId)
  // argsHash 校验:确认的参数必须与挂起时一致,防旧确认卡重放
  if st != null && st.pendingArgsHash != sha256(json(row.arguments)):
     推 error{ARGS_CHANGED, msg:"确认参数已变化,请重新发起"}; return
  confirmationService.confirm(actionId)   // pending → confirmed
  推 step_update(tool: 执行中)
  result = dispatch(def, row.arguments)
  confirmationService.execute(actionId, result)   // confirmed → executed
  推 execution_result{actionId, ok:true, result}
  if st != null:
     // 关键:把确认的工具结果入 history,LLM 续循环时才能准确复述写操作结果(修 B1/B2)
     // call.id 取自挂起态(ConfirmationService 不持久化 tool_call_id,只能从内存 history 的
     // AssistantMessage 取)
     追加 ToolResponseMessage(st.history, st.pendingCallId, result)
     继续跑完 st 挂起的 for-turn 循环 → 阶段2 流式收尾(推 delta/assistant_done/suggestions)
     suspended.remove(row.convId)
  else:   // 进程重启 / 超时 fallback:无法续循环(SuspendState 丢了)
     // 补终态帧,否则前端卡 executing(前端仅在 ok=false 自动回 idle)
     推 step_update(completed)
     推 assistant_done{text:"操作已完成(会话上下文已失效,无法续答)", tool_calls:[]}
```

### 关键不变量

- 读工具单轮直接跑;写工具首轮即挂起推确认卡,**不执行业务**。
- `MAX_TURNS=10` 防失控;超轮 + 仍有 toolCall → `error{TOO_MANY_TURNS}` break。
- 挂起态 in-memory(`ConcurrentHashMap<convId, SuspendState>`),进程重启走 fallback(单工具重跑 + 终态帧,不续循环)。毕设单实例可接受。
- **argsHash 校验**:挂起时存 `pendingArgsHash`,confirm 时比对 `sha256(row.arguments)`,防旧确认卡重放。仅 `st != null` 路径生效(restart-fallback 无 st,靠 owner+status 校验)。
- **挂起会话并发**:`suspended.containsKey(convId)` 即视为 BUSY,新 `user_message` 推 `error{BUSY, msg:"有待确认操作"}`,不入循环(防覆盖挂起态 orphan pending action)。
- **过期动作清挂起态**:`AiActionTimeoutScheduler.expireOldPending` 把 pending→expired 时,同步 `suspended.remove(convId)` + 推 `confirmation_expired` 帧。否则 5min 后用户无确认卡可点(refresh 丢卡片),会话永久卡 BUSY。`handleCancel`/`handleConfirm` 的早退路径也须 `suspended.remove`。

## 3. 确认流程数据流

### 帧时序(写工具"帮我预约 #42 明天 14-16 点")

```
前端 send ──user_message──▶ 后端
后端  ──step_update(started)──▶ 前端
后端  callOnce → LLM 决定调 createReservation(confirmRequired)
后端  ──step_update(tool: createReservation)──▶ 前端
后端  confirmationService.create → actionId=77, status=pending
后端  ──confirmation_required{actionId:77, tool:"createReservation",
        reason, risk_summary, estimated_impact, args:{deviceId:42,...}}──▶ 前端
后端  挂起循环, return

前端 ConfirmationCard 渲染 {风险, 影响, 参数}, 两按钮

用户点确认 ──confirm_action{actionId:77}──▶ 后端
后端  confirm(77) pending→confirmed
后端  ──step_update(tool: executing)──▶ 前端
后端  dispatch createReservation → reservationId=123
后端  execute(77, result) confirmed→executed
后端  ──execution_result{actionId:77, ok:true, result:{reservation_id:123}}──▶ 前端
后端  继续挂起循环 → LLM 看 tool 结果 → 无更多 toolCall → 阶段2 真流式
后端  ──delta(真流式)──▶ 前端 ×N
后端  ──assistant_done + suggestions──▶ 前端
```

### 状态机(已有,补调用点)

```
pending ──confirm()──▶ confirmed ──execute()──▶ executed
   │                       │
   └──cancel()──▶ cancelled │
   └────────────────────────┴──error()──▶ error
pending(5min)──expireOldPending()──▶ expired   (AiActionTimeoutScheduler 已有)
```

全部状态转换已有代码(`ConfirmationService`),仅缺调用点:`create()` 在挂起时调、`execute()` 在 dispatch 后调。**零 schema 变更**。

### 取消分支

`handleCancel(actionId)` → `cancel()`(idempotent)→ 推 `execution_result{ok:false, cancelled:true}` → 前端关卡片。挂起循环清掉 `suspended.remove(convId)`。

## 4. 两阶段真流式

### LlmClient 拆两方法(替掉单 `stream`)

```java
// 阶段1:工具决策。非流,拿 toolCalls。带熔断。
// 关键:internalToolExecutionEnabled=false — 否则 Spring AI 1.0.6 的 ToolCallingManager
// 会自动执行 toolCallbacks(含写工具),confirmation 拦截不可能。设 false 后模型只返回
// toolCalls 不执行,由编排器手动 dispatch。
@CircuitBreaker(name = "llm", fallbackMethod = "callOnceFallback")
public ChatResponse callOnce(String sys, List<Message> history,
                             ChatClient cc, List<ToolCallback> tools) {
    OpenAiChatOptions opts = OpenAiChatOptions.builder()
            .toolCallbacks(tools)
            .internalToolExecutionEnabled(false)
            .build();
    return cc.prompt().system(sys).messages(history)
            .options(opts).call().chatResponse();
}

// callOnce 的 fallback:签名须匹配(同参 + 末尾 Throwable)。返合成 ChatResponse
// (无 toolCalls、空 content),编排器见空 content 且无 toolCalls → 走 EMPTY_RESPONSE 错误分支。
@SuppressWarnings("unused")
public ChatResponse callOnceFallback(String sys, List<Message> history,
                                     ChatClient cc, ToolCallback[] tools, Throwable t) {
    log.warn("LLM callOnce fallback: {}", t.getMessage());
    return emptyChatResponse();   // content=null, toolCalls=[]
}

// 阶段2:最终回答。真流式,无 tools(决策已做完)。无熔断,Flux 自身 onErrorResume 兜。
public Flux<String> streamFinal(String sys, List<Message> history, ChatClient cc) {
    return cc.prompt().system(sys).messages(history).stream().content();
}
```

### 为什么两阶段

- 阶段1带 tools → `.call()`(非流),因要解 `toolCalls` 结构体;Spring AI 1.0.6 `.stream()` + tools 退化。
- 阶段2无 tools → `.stream()` 真流式,首字延迟 ≈ 模型 TTFT(原 = 整段生成时长)。

### 取消仍生效

`cancelFlags` 每 chunk 检查。阶段2 `.doOnNext` 里 `if (cancelled.get()) return`。阶段1 `.call()` 阻塞单次调用无法中途断,但单次 < 30s 可接受。

### 熔断

`callOnce` 带 `@CircuitBreaker`(替原 `stream` 上的),fallback 返合成空 `ChatResponse`(content=null + 无 toolCalls),编排器见此走 `EMPTY_RESPONSE` 错误分支。`streamFinal` 不带熔断(Flux 自身 onErrorResume 兜)。resilience4j 配置(`application-dev.yml` 的 `resilience4j.circuitbreaker.instances.llm`)沿用不动。

## 5. 限流改造(B3 误伤)

### 问题

现 `RateLimitService.tryConsume` 按 WS 请求扣 1。一次"代预约" = 阶段1 callOnce(可能多轮)+ 阶段2 streamFinal = 多次 LLM 调用,按请求限流把一次业务动作算多次。

### 改法

限流单位从"请求"改"**对话轮次**"(一次 user_message = 1 token),内部 LLM 调用不单独扣:

- `handleUserMessage` 入口 `tryConsume(userId)` 扣 1(保留位置)。
- `callOnce` / `streamFinal` 不扣。
- 桶调高:`capacity=30, refillPerMinute=30`(`AiProperties`),给多轮工具链留余量。
- RATE_LIMIT 帧文案改"AI 正在处理上一条消息,请稍候再发"。

### 防手贱连点(双保险)

后端收到 `sending/streaming` 期间新 `user_message` → 推 `error{BUSY}`,不入循环。前端 textarea 已 disabled(state 检查),这是后端兜底。

## 6. 文件清单 + 边界

### 后端(6 文件)

| 文件 | 动作 |
|---|---|
| `ai/service/ToolLoopOrchestrator.java` | **新建**。显式循环 + 挂起/恢复 + 两阶段。 |
| `ai/service/AiAssistantService.java` | **瘦身**。保留入口/限流/SecurityContext/per-user client,循环委托 Orchestrator。`handleConfirm` 补真 dispatch + 恢复循环。 |
| `ai/service/LlmClient.java` | 拆 `callOnce` + `streamFinal`,删伪流式 12 字切片。 |
| `ai/service/ConversationService.java` | `buildPrompt` 重建含 assistant + tool 消息(现只建 user)。用 Spring AI `AssistantMessage` + `ToolResponseMessage`。 |
| `ai/service/ConfirmationService.java` | 不改(状态机已全)。仅补调用点(在 Orchestrator)。confirm 加 owner 校验。 |
| `ai/task/AiActionTimeoutScheduler.java` | `expireOldPending` 后调 orchestrator 清挂起态(`suspended.remove`)+ 推 `confirmation_expired` 帧。 |
| `ai/tool/ToolArgumentValidator.java` | `p.getName()` → pom 加 `-parameters` 编译。 |

### 前端(2 文件)

| 文件 | 动作 |
|---|---|
| `stores/ai.ts` | `handleFrame` 已处理全部帧类型,几乎不改。仅 `execution_result.ok=false` 关卡片回 idle。 |
| `components/ai/AiAssistant.vue` | 微调:BUSY 错误不弹设置面板。 |

### 不改(YAGNI)

ToolRegistry 角色解析(P1)、seq fallback(P1)、分布式限流 / Caffeine 缓存 / 观测 / 安全(P2/3)、SystemPromptBuilder / suggestion 硬编码(P3)、前端 WS 单例重构(P1)—— 仅必要时碰。

### Schema

**零变更**。`ai_tool_execution` 已有全部列(status/arguments/result/error_message/created_at/user_confirmed_at/executed_at)。`ai_ws_frame` 不变。无需 Flyway 迁移。

## 7. 错误处理

| 场景 | 处理 |
|---|---|
| LLM callOnce 抛(网络/429/5xx) | CircuitBreaker fallback → `error{AI_UNAVAILABLE}` 帧 |
| LLM 返回空 content 且无 toolCalls | `error{EMPTY_RESPONSE}`,break |
| tool dispatch 抛 BusinessException | tool 内部已 catch 转 `ToolExecutionResult.fail`(保留);编排器把 fail 结果塞 ToolResponseMessage 让 LLM 解释 |
| tool dispatch 抛非预期 Exception | `error{TOOL_EXECUTION_FAILED, msg}` + log,不泄露 stack 给前端 |
| 确认的 actionId 不属当前用户 | confirm 加 owner 校验(convId→userId),不符 `FORBIDDEN` |
| 确认时挂起态丢失(重启) | fallback:用 `row.arguments` 重跑单工具,不续循环 |
| MAX_TURNS 超 | `error{TOO_MANY_TURNS}`,break |

## 8. 测试

### 新测

- `ToolLoopOrchestratorTest`: mock LlmClient 返回固定 toolCalls → 验证写工具挂起推 confirmation_required、读工具直接跑、确认后恢复执行。
- `LlmClientTest`: mock ChatClient 验 callOnce 解 toolCalls、streamFinal 返 Flux。
- `AiAssistantServiceTest`: 补 confirm→execute 端到端(mock orchestrator)。

### e2e 联调(选定验证方式)

1. `docker compose up -d`(mysql+redis)
2. `mvn spring-boot:run`(dev,siliconflow 默认 key)
3. 前端 `pnpm dev`
4. 登录学生账号 → AI 球
5. 三场景:
   - 读:"我有哪些预约?" → 验 searchMyReservations 真跑 + 真流式收尾
   - 写:"帮我预约 #1 明天 14-16 点" → 验确认卡弹出 → 点确认 → 验 reservation 表真插入 + execution_result
   - 取消:确认卡点取消 → 验 status=cancelled + 不插入
6. 失败回放:故意填错 deviceId → 验 fail 结果 LLM 解释

## 9. 风险

| 风险 | 缓解 |
|---|---|
| siliconflow key 失效/欠费 | dev 兜底失败 → AI_NOT_CONFIGURED 帧,不阻塞其他场景联调 |
| Spring AI 1.0.6 `.call().chatResponse()` 取 toolCalls 的 API 细节不符 | 实现首步先写 spike 验 API,确认 `getResult().getOutput().getToolCalls()` 路径再铺开 |
| 多轮工具链 token 爆 | `ConversationService.buildPrompt` 滑动窗口已限 turns;阶段2 只带必要 history |
| 挂起态 in-memory 多实例不一致 | 毕设单实例接受;`SuspendState` 留接口,日后换 Redis |
| ToolArgumentValidator `-parameters` 影响全项目编译 | maven-compiler `<parameters>true</parameters>` 标准配置,无副作用 |

## 10. 不做的事(YAGNI)

retry/退避、分布式限流、观测指标、prompt 注入防御、i18n、a11y、前端 WS 单例重构、角色化 prompt、移动端响应式 —— 全 P2/P3,本轮不碰。
