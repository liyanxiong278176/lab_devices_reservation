import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  cancelAiAction,
  confirmAiAction,
  createAiConversation,
  listAiConversations,
  listAiMessages,
  streamAiMessage,
} from '@/api/aiV2'
import type {
  AiCitation,
  AiConfirmation,
  AiConversation,
  AiMessage,
  AiStep,
  AiStreamEvent,
} from '@/types/aiWorkbench'

export const useAiWorkbenchStore = defineStore('ai-workbench', () => {
  const conversations = ref<AiConversation[]>([])
  const activeConversationId = ref<number | null>(null)
  const messages = ref<AiMessage[]>([])
  const citations = ref<AiCitation[]>([])
  const steps = ref<AiStep[]>([])
  const pendingConfirmation = ref<AiConfirmation | null>(null)
  const loading = ref(false)
  const loadingHistory = ref(false)
  const error = ref('')
  let abortController: AbortController | null = null

  const activeConversation = computed(() =>
    conversations.value.find((item) => item.id === activeConversationId.value) || null,
  )

  async function loadConversations() {
    loadingHistory.value = true
    try {
      conversations.value = await listAiConversations()
      if (activeConversationId.value && conversations.value.some((item) => item.id === activeConversationId.value)) {
        await selectConversation(activeConversationId.value)
      } else if (conversations.value[0]) {
        await selectConversation(conversations.value[0].id)
      } else {
        await createConversation()
      }
    } finally {
      loadingHistory.value = false
    }
  }

  async function createConversation() {
    const conversation = await createAiConversation()
    conversations.value.unshift(conversation)
    activeConversationId.value = conversation.id
    messages.value = []
    citations.value = []
    steps.value = []
    pendingConfirmation.value = null
  }

  async function selectConversation(id: number) {
    activeConversationId.value = id
    messages.value = await listAiMessages(id)
    citations.value = []
    steps.value = []
    const persisted = [...messages.value]
      .reverse()
      .map((message) => message.metadata?.pending_confirmation)
      .find((value): value is Record<string, unknown> => Boolean(value))
    pendingConfirmation.value = persisted
      ? {
          id: Number(persisted.confirmation_id || 0),
          tool_name: String(persisted.tool_name || 'protected_action'),
          reason: String(persisted.reason || '该操作需要确认'),
          risk_summary: String(persisted.risk_summary || '会修改业务数据'),
          estimated_impact: String(persisted.estimated_impact || '仅影响当前学院范围内的数据'),
          preview: (persisted.preview as Record<string, unknown>) || {},
          status: 'PENDING',
        }
      : null
  }

  async function send(content: string) {
    const text = content.trim()
    if (!text || loading.value) return
    if (!activeConversationId.value) await createConversation()
    if (!activeConversationId.value) return
    error.value = ''
    loading.value = true
    pendingConfirmation.value = null
    steps.value = []
    citations.value = []
    messages.value.push({ id: `local-${Date.now()}`, role: 'user', content: text })
    const assistant: AiMessage = { id: `assistant-${Date.now()}`, role: 'assistant', content: '' }
    messages.value.push(assistant)
    abortController = new AbortController()
    try {
      await streamAiMessage(
        activeConversationId.value,
        text,
        { onEvent: (event) => handleEvent(event, assistant) },
        abortController.signal,
      )
      await refreshConversationList()
    } catch (err) {
      if ((err as Error).name !== 'AbortError') {
        error.value = (err as Error).message || 'AI 服务暂时不可用'
        if (!assistant.content) messages.value.pop()
      }
    } finally {
      loading.value = false
      abortController = null
    }
  }

  function handleEvent(event: AiStreamEvent, assistant: AiMessage) {
    if (event.type === 'step' && event.name) {
      steps.value.push({
        name: event.name,
        status: event.status || 'completed',
        intent: event.intent,
        source_count: event.sources?.length,
      })
    } else if (event.type === 'token' && event.text) {
      assistant.content += event.text
    } else if (event.type === 'confirmation_required') {
      pendingConfirmation.value = {
        id: event.confirmation_id || 0,
        tool_name: event.tool_name || 'protected_action',
        reason: event.reason || '该操作需要确认',
        risk_summary: event.risk_summary || '会修改业务数据',
        estimated_impact: event.estimated_impact || '仅影响当前学院范围内的数据',
        preview: event.preview || {},
        status: 'PENDING',
      }
    } else if (event.type === 'sources' || event.type === 'done') {
      citations.value = event.citations || event.sources || citations.value
    } else if (event.type === 'error') {
      error.value = event.message || 'AI 任务执行失败'
    }
  }

  async function confirm(): Promise<boolean> {
    if (!pendingConfirmation.value?.id || loading.value) return false
    const current = pendingConfirmation.value
    loading.value = true
    try {
      await confirmAiAction(current.id)
      current.status = 'EXECUTED'
      messages.value.push({
        id: `confirmation-${Date.now()}`,
        role: 'assistant',
        content: '已按你的确认执行完成。',
      })
      pendingConfirmation.value = null
      await refreshConversationList()
      return true
    } catch (err) {
      // request.ts already surfaces the server's structured message. Avoid a
      // second generic Axios toast ("Request failed with status code 409").
      const typedError = err as {
        response?: { status?: number; data?: { code?: string } }
        code?: string
        status?: number
      }
      const response = typedError.response
      const status = response?.status || typedError.status
      const code = response?.data?.code || typedError.code
      if (status === 409 || status === 404 || code === 'CONFIRMATION_ALREADY_HANDLED') {
        // A terminal/stale confirmation must never keep blocking the composer.
        pendingConfirmation.value = null
      }
      return false
    } finally {
      loading.value = false
    }
  }

  async function cancelConfirmation() {
    if (!pendingConfirmation.value?.id) return
    try {
      await cancelAiAction(pendingConfirmation.value.id)
      pendingConfirmation.value.status = 'CANCELLED'
      pendingConfirmation.value = null
    } catch (err) {
      ElMessage.error((err as Error).message || '取消确认失败')
    }
  }

  function stop() {
    abortController?.abort()
    loading.value = false
  }

  async function refreshConversationList() {
    conversations.value = await listAiConversations()
  }

  return {
    conversations,
    activeConversationId,
    activeConversation,
    messages,
    citations,
    steps,
    pendingConfirmation,
    loading,
    loadingHistory,
    error,
    loadConversations,
    createConversation,
    selectConversation,
    send,
    confirm,
    cancelConfirmation,
    stop,
  }
})
