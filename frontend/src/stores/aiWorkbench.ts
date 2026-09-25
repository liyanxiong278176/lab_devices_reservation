import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  cancelAiAction,
  confirmAiAction,
  createAiConversation,
  deleteAiConversation,
  getActiveAiRun,
  listAiConversations,
  listAiMessages,
  resumeAiRun,
  stopAiRun,
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
  const activeRunId = ref<number | null>(null)
  const messages = ref<AiMessage[]>([])
  const citations = ref<AiCitation[]>([])
  const steps = ref<AiStep[]>([])
  const pendingConfirmation = ref<AiConfirmation | null>(null)
  const loading = ref(false)
  const loadingHistory = ref(false)
  const error = ref('')
  let abortController: AbortController | null = null
  let generation = 0

  const activeConversation = computed(() =>
    conversations.value.find((item) => item.id === activeConversationId.value) || null,
  )

  function detach() {
    generation += 1
    abortController?.abort()
    abortController = null
    loading.value = false
  }

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
    detach()
    const conversation = await createAiConversation()
    conversations.value.unshift(conversation)
    activeConversationId.value = conversation.id
    activeRunId.value = null
    messages.value = []
    citations.value = []
    steps.value = []
    pendingConfirmation.value = null
    error.value = ''
  }

  async function selectConversation(id: number) {
    if (activeConversationId.value !== id) detach()
    activeConversationId.value = id
    activeRunId.value = null
    messages.value = await listAiMessages(id)
    citations.value = []
    steps.value = []
    error.value = ''
    const latestAssistant = [...messages.value].reverse().find((message) => message.role === 'assistant')
    const storedCitations = latestAssistant?.metadata?.citations
    if (Array.isArray(storedCitations)) citations.value = storedCitations as AiCitation[]
    const storedSteps = latestAssistant?.metadata?.steps
    if (Array.isArray(storedSteps)) steps.value = storedSteps as AiStep[]
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
    const active = await getActiveAiRun(id)
    if (active) {
      const assistant: AiMessage = { id: `resume-${active.run_id}`, role: 'assistant', content: '' }
      messages.value.push(assistant)
      void attachToRun(active.run_id, assistant)
    }
  }

  async function attachToRun(runId: number, assistant: AiMessage) {
    detach()
    const currentGeneration = generation
    activeRunId.value = runId
    loading.value = true
    abortController = new AbortController()
    try {
      await resumeAiRun(
        runId,
        { onEvent: (event) => handleEvent(event, assistant) },
        abortController.signal,
      )
      if (currentGeneration === generation) await reloadActiveMessages()
    } catch (err) {
      if ((err as Error).name !== 'AbortError' && currentGeneration === generation) {
        error.value = (err as Error).message || 'AI 任务恢复失败'
      }
    } finally {
      if (currentGeneration === generation) {
        loading.value = false
        activeRunId.value = null
        abortController = null
        await refreshConversationList()
      }
    }
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
    const conversationId = activeConversationId.value
    const currentGeneration = ++generation
    abortController = new AbortController()
    try {
      await streamAiMessage(
        conversationId,
        text,
        {
          onRunId: (runId) => { activeRunId.value = runId },
          onEvent: (event) => handleEvent(event, assistant),
        },
        abortController.signal,
      )
      if (currentGeneration === generation) {
        await reloadActiveMessages()
        await refreshConversationList()
      }
    } catch (err) {
      if ((err as Error).name !== 'AbortError' && currentGeneration === generation) {
        error.value = (err as Error).message || 'AI 服务暂时不可用'
        if (!assistant.content) messages.value.pop()
      }
    } finally {
      if (currentGeneration === generation) {
        loading.value = false
        activeRunId.value = null
        abortController = null
      }
    }
  }

  async function reloadActiveMessages() {
    if (!activeConversationId.value) return
    messages.value = await listAiMessages(activeConversationId.value)
    const latestAssistant = [...messages.value].reverse().find((message) => message.role === 'assistant')
    if (Array.isArray(latestAssistant?.metadata?.citations)) {
      citations.value = latestAssistant.metadata.citations as AiCitation[]
    }
    if (Array.isArray(latestAssistant?.metadata?.steps)) {
      steps.value = latestAssistant.metadata.steps as AiStep[]
    }
  }

  function handleEvent(event: AiStreamEvent, assistant: AiMessage) {
    if (event.type === 'step' && event.name) {
      const existing = steps.value.find((step) => step.name === event.name && step.status === 'running')
      if (existing) Object.assign(existing, { status: event.status || 'completed', intent: event.intent })
      else steps.value.push({
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
        estimated_impact: event.estimated_impact || '仅影响你本人可见的数据',
        preview: event.preview || {},
        status: 'PENDING',
      }
    } else if (event.type === 'sources' || event.type === 'done') {
      citations.value = event.citations || event.sources || citations.value
      if (event.status === 'FAILED') {
        error.value = event.message || 'AI 任务执行失败'
      }
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
      messages.value.push({ id: `confirmation-${Date.now()}`, role: 'assistant', content: '已按你的确认执行完成。' })
      pendingConfirmation.value = null
      await reloadActiveMessages()
      await refreshConversationList()
      return true
    } catch (err) {
      const typedError = err as { response?: { status?: number; data?: { code?: string } }; code?: string; status?: number }
      const status = typedError.response?.status || typedError.status
      const code = typedError.response?.data?.code || typedError.code
      if (status === 409 || status === 404 || code === 'CONFIRMATION_ALREADY_HANDLED') {
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

  async function stop() {
    const runId = activeRunId.value
    if (runId) {
      try {
        await stopAiRun(runId)
      } catch (err) {
        ElMessage.error((err as Error).message || '停止任务失败')
      }
    }
    detach()
    activeRunId.value = null
  }

  async function removeConversation(id: number) {
    await deleteAiConversation(id)
    conversations.value = conversations.value.filter((item) => item.id !== id)
    if (activeConversationId.value === id) {
      activeConversationId.value = null
      if (conversations.value[0]) await selectConversation(conversations.value[0].id)
      else await createConversation()
    }
  }

  async function refreshConversationList() {
    conversations.value = await listAiConversations()
  }

  return {
    conversations,
    activeConversationId,
    activeRunId,
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
    detach,
    removeConversation,
  }
})
