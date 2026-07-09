import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  connectAiWs,
  disconnectAiWs,
  reconnectAiWs,
  sendAiMsg,
} from '@/composables/useAiWebSocket'
import type {
  AiAssistantState,
  ChatMessage,
  ConfirmationState,
  StepUpdateItem,
  WsServerFrame,
} from '@/types/ai'

/**
 * AI 助手 Pinia store — state + 消息历史 + 确认队列 + step timeline。
 *
 * <p>WS 客户端模块级单例 (useAiWebSocket 持有);本 store 只管 state。
 * 组件 mount 时调 ensureConnected() 即可。
 *
 * <p>不持久化:WS state 不应在 reload 后存活;重连靠 resync() 拉历史。
 */
export const useAiStore = defineStore('ai', () => {
  const state = ref<AiAssistantState>('idle')
  const convId = ref<number | null>(null)
  const messages = ref<ChatMessage[]>([])
  const confirmations = ref<ConfirmationState[]>([])
  const currentStepUpdates = ref<StepUpdateItem[]>([])
  const currentSuggestions = ref<Array<{ label: string; value: string }>>([])
  const lastError = ref<{ code: string; msg: string } | null>(null)
  const lastSeq = ref(0)
  const expanded = ref(false) // 抽屉开关

  function handleFrame(frame: WsServerFrame) {
    if (typeof frame.seq === 'number' && frame.seq > lastSeq.value) {
      lastSeq.value = frame.seq
    }
    if (frame.conv_id && !convId.value) convId.value = frame.conv_id

    switch (frame.type) {
      case 'delta':
        appendToCurrentAssistant(frame.text)
        if (state.value === 'sending') state.value = 'streaming'
        break
      case 'step_update':
        currentStepUpdates.value.push({
          stepId: frame.step_id,
          status: frame.status,
          text: frame.text,
          durationMs: frame.duration_ms,
          timestamp: Date.now(),
        })
        if (frame.status === 'started') state.value = 'step_running'
        else if (frame.status === 'completed') state.value = 'streaming'
        else if (frame.status === 'cancelled' || frame.status === 'failed') state.value = 'idle'
        break
      case 'suggestions': {
        const last = messages.value[messages.value.length - 1]
        if (last && last.role === 'assistant') {
          last.suggestions = frame.items
        } else {
          currentSuggestions.value = frame.items
        }
        break
      }
      case 'assistant_done':
        finalizeCurrentAssistant(frame.text, frame.tool_calls)
        state.value = 'done'
        currentStepUpdates.value = []
        break
      case 'confirmation_required':
        confirmations.value.push({
          actionId: frame.action_id,
          toolName: frame.tool_name,
          reason: frame.reason,
          riskSummary: frame.risk_summary,
          estimatedImpact: frame.estimated_impact,
          status: 'pending',
        })
        state.value = 'awaiting_confirmation'
        break
      case 'confirmation_expired':
        markConfirmation(frame.action_id, 'expired')
        break
      case 'execution_result':
        markConfirmation(frame.action_id, frame.ok ? 'executed' : 'error')
        if (frame.ok) state.value = 'done'
        else state.value = 'error'
        break
      case 'error':
        lastError.value = { code: frame.code, msg: frame.msg }
        state.value = 'error'
        break
      case 'ping':
        // heartbeat, no-op
        break
    }
  }

  function appendToCurrentAssistant(text: string) {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant') {
      last.text += text
    } else {
      messages.value.push({
        id: crypto.randomUUID(),
        role: 'assistant',
        text,
        timestamp: Date.now(),
      })
    }
  }

  function finalizeCurrentAssistant(text: string, toolCalls: unknown[]) {
    const last = messages.value[messages.value.length - 1]
    if (last && last.role === 'assistant') {
      if (text) last.text = text
      last.toolCalls = toolCalls
      if (last.stepUpdates === undefined) last.stepUpdates = [...currentStepUpdates.value]
    }
  }

  function markConfirmation(actionId: number, status: ConfirmationState['status']) {
    const idx = confirmations.value.findIndex((c) => c.actionId === actionId)
    if (idx >= 0) confirmations.value[idx].status = status
  }

  function ensureConnected() {
    connectAiWs(handleFrame)
  }

  function open() {
    expanded.value = true
    ensureConnected()
  }

  function close() {
    expanded.value = false
  }

  function toggle() {
    if (expanded.value) close()
    else open()
  }

  function send(text: string) {
    if (!text.trim()) return
    if (state.value === 'sending' || state.value === 'streaming') return
    state.value = 'sending'
    lastError.value = null
    currentStepUpdates.value = []
    currentSuggestions.value = []
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'user',
      text,
      timestamp: Date.now(),
    })
    messages.value.push({
      id: crypto.randomUUID(),
      role: 'assistant',
      text: '',
      timestamp: Date.now(),
    })
    sendAiMsg({ kind: 'user_message', convId: convId.value, text })
  }

  function confirmAction(actionId: number) {
    markConfirmation(actionId, 'confirmed')
    state.value = 'executing'
    sendAiMsg({ kind: 'confirm_action', actionId })
  }

  function cancelAction(actionId: number) {
    markConfirmation(actionId, 'cancelled')
    sendAiMsg({ kind: 'cancel_action', actionId })
  }

  function cancelSession() {
    if (!convId.value) return
    sendAiMsg({ kind: 'cancel_session', convId: convId.value })
  }

  function resync() {
    if (!convId.value) return
    sendAiMsg({ kind: 'resync', convId: convId.value, lastSeq: lastSeq.value })
  }

  function clear() {
    messages.value = []
    confirmations.value = []
    currentStepUpdates.value = []
    currentSuggestions.value = []
    lastError.value = null
    convId.value = null
    lastSeq.value = 0
    state.value = 'idle'
  }

  function reconnectWs(newToken?: string) {
    reconnectAiWs(newToken)
  }

  function teardown() {
    disconnectAiWs()
  }

  const hasConfirmationPending = computed(() =>
    confirmations.value.some((c) => c.status === 'pending'),
  )

  return {
    state,
    convId,
    messages,
    confirmations,
    currentStepUpdates,
    currentSuggestions,
    lastError,
    lastSeq,
    expanded,
    hasConfirmationPending,
    open,
    close,
    toggle,
    send,
    confirmAction,
    cancelAction,
    cancelSession,
    resync,
    clear,
    reconnectWs,
    teardown,
    ensureConnected,
  }
})
