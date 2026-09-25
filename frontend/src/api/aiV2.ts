import request from './request'
import type {
  AiCitation,
  AiConfirmation,
  AiConversation,
  AiModelConfig,
  AiMessage,
  AiStreamEvent,
  AiUsageReport,
  AiEmbeddingRebuildJob,
  AiReadiness,
  KnowledgeDocument,
  KnowledgeChunkPreview,
} from '@/types/aiWorkbench'
import { useUserStore } from '@/stores/user'

export const listAiConversations = () =>
  request.get<unknown, AiConversation[]>('/ai/conversations')

export const getAiReadiness = () => request.get<unknown, AiReadiness>('/ai/status')

export const createAiConversation = (title?: string) =>
  request.post<unknown, AiConversation>('/ai/conversations', { title })

export const listAiMessages = (conversationId: number) =>
  request.get<unknown, AiMessage[]>(`/ai/conversations/${conversationId}/messages`)

export const getActiveAiRun = (conversationId: number) =>
  request.get<unknown, { run_id: number; status: string } | null>(
    `/ai/conversations/${conversationId}/active-run`,
  )

export const deleteAiConversation = (conversationId: number) =>
  request.delete<unknown, { conversation_id: number; deleted: boolean }>(
    `/ai/conversations/${conversationId}`,
  )

export const getAiModelConfig = () =>
  request.get<unknown, AiModelConfig>('/ai/config')

export const getAiModelConfigs = () =>
  request.get<unknown, AiModelConfig[]>('/ai/config/components')

export const testAiModelConfig = (component: AiModelConfig['component']) =>
  request.post<unknown, { component: string; success: boolean; message: string; model: string; latency_ms: number }>(
    `/ai/config/${component}/test`,
    {},
  )

export const getAiUsage = () => request.get<unknown, AiUsageReport>('/ai/usage')

export const getLatestAiEmbeddingRebuild = () =>
  request.get<unknown, AiEmbeddingRebuildJob | null>('/ai/embedding/rebuild/latest')

export const startAiEmbeddingRebuild = () =>
  request.post<unknown, AiEmbeddingRebuildJob>('/ai/embedding/rebuild', {})

export const rollbackAiEmbeddingRebuild = (jobId: number) =>
  request.post<unknown, AiEmbeddingRebuildJob>(`/ai/embedding/rebuild/${jobId}/rollback`)

export const listKnowledgeDocuments = () =>
  request.get<unknown, KnowledgeDocument[]>('/ai/knowledge')

export const createKnowledgeDocument = (payload: {
  title: string
  source_type: string
  college_id?: number
  body: string
}) => request.post<unknown, KnowledgeDocument>('/ai/knowledge', payload)

export const getKnowledgeDocument = (documentId: number) =>
  request.get<unknown, KnowledgeDocument & {
    body: string
    extracted_text: string | null
    reviewed_text: string | null
    checksum: string
  }>(`/ai/knowledge/${documentId}`)

export const uploadKnowledgeDocument = (payload: {
  title: string
  source_type: string
  college_id?: number
  file: File
}) => {
  const form = new FormData()
  form.set('title', payload.title)
  form.set('source_type', payload.source_type)
  if (payload.college_id) form.set('college_id', String(payload.college_id))
  form.set('file', payload.file)
  return request.post<unknown, KnowledgeDocument>('/ai/knowledge/upload', form)
}

export const requestKnowledgeParse = (documentId: number) =>
  request.post<unknown, KnowledgeDocument>(`/ai/knowledge/${documentId}/parse`)

export const reviewKnowledgeDocument = (documentId: number, reviewed_text: string) =>
  request.put<unknown, KnowledgeDocument>(`/ai/knowledge/${documentId}/review`, { reviewed_text })

export const previewKnowledgeChunks = (documentId: number) =>
  request.get<unknown, KnowledgeChunkPreview[]>(`/ai/knowledge/${documentId}/chunks/preview`)

export const publishKnowledgeDocument = (documentId: number) =>
  request.post<unknown, KnowledgeDocument>(`/ai/knowledge/${documentId}/publish`)

export const deleteKnowledgeDocument = (documentId: number) =>
  request.delete<unknown, { document_id: number; deleted: boolean }>(`/ai/knowledge/${documentId}`)

export const confirmAiAction = (confirmationId: number) =>
  request.post<unknown, { confirmation_id: number; status: string; data: unknown }>(
    `/ai/confirmations/${confirmationId}/confirm`,
  )

export const cancelAiAction = (confirmationId: number) =>
  request.post<unknown, { confirmation_id: number; status: string }>(
    `/ai/confirmations/${confirmationId}/cancel`,
  )

export const stopAiRun = (runId: number) =>
  request.post<unknown, { run_id: number; status: string }>(`/ai/runs/${runId}/stop`)

export interface AiStreamHandlers {
  onEvent?: (event: AiStreamEvent) => void
  onRunId?: (runId: number) => void
}

function authHeaders(token: string): HeadersInit {
  return { Authorization: `Bearer ${token}`, Accept: 'text/event-stream' }
}

async function readError(response: Response) {
  try {
    const body = await response.json()
    return body.message || 'AI 服务暂时不可用'
  } catch {
    return 'AI 服务暂时不可用'
  }
}

async function consumeRunEvents(
  initialResponse: Response,
  runId: number | null,
  handlers: AiStreamHandlers,
  signal?: AbortSignal,
) {
  const user = useUserStore()
  let response = initialResponse
  let cursor = 0
  let knownRunId = runId
  let retryDelay = 500

  while (!signal?.aborted) {
    if (!response.ok || !response.body) throw new Error(await readError(response))
    const headerRunId = Number(response.headers.get('X-AI-Run-ID'))
    if (Number.isSafeInteger(headerRunId) && headerRunId > 0) knownRunId = headerRunId
    if (knownRunId) handlers.onRunId?.(knownRunId)

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let receivedTerminal = false
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const frames = buffer.split(/\r?\n\r?\n/)
        buffer = frames.pop() || ''
        for (const frame of frames) {
          let eventId: number | undefined
          const data: string[] = []
          for (const line of frame.split(/\r?\n/)) {
            if (line.startsWith('id:')) eventId = Number(line.slice(3).trim())
            else if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
          }
          if (Number.isSafeInteger(eventId) && eventId! > cursor) cursor = eventId!
          if (!data.length) continue
          try {
            const event = JSON.parse(data.join('\n')) as AiStreamEvent
            if (!knownRunId && event.run_id) {
              knownRunId = event.run_id
              handlers.onRunId?.(knownRunId)
            }
            handlers.onEvent?.(event)
            if (event.type === 'done' || event.type === 'error') receivedTerminal = true
          } catch {
            // Keep-alives and malformed frames are ignored; the persisted event
            // cursor ensures the next read can replay anything valid.
          }
        }
      }
    } catch (error) {
      try { await reader.cancel() } catch { /* connection already closed */ }
      if (signal?.aborted || (error as Error).name === 'AbortError') throw error
    }
    if (receivedTerminal) return
    if (signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    if (!knownRunId) throw new Error('连接中断，暂时无法恢复任务；请刷新对话重试')

    await new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(resolve, retryDelay)
      signal?.addEventListener('abort', () => {
        window.clearTimeout(timer)
        reject(new DOMException('Aborted', 'AbortError'))
      }, { once: true })
    })
    retryDelay = Math.min(Math.round(retryDelay * 1.7), 8000)
    response = await fetch(`/api/v2/ai/runs/${knownRunId}/events?after_event_id=${cursor}`, {
      headers: { ...authHeaders(user.accessToken), 'Last-Event-ID': String(cursor) },
      signal,
    })
  }
  throw new DOMException('Aborted', 'AbortError')
}

export async function streamAiMessage(
  conversationId: number,
  content: string,
  handlers: AiStreamHandlers,
  signal?: AbortSignal,
) {
  const user = useUserStore()
  const response = await fetch(`/api/v2/ai/conversations/${conversationId}/stream`, {
    method: 'POST',
    signal,
    headers: { ...authHeaders(user.accessToken), 'Content-Type': 'application/json' },
    body: JSON.stringify({ content }),
  })
  const runId = Number(response.headers.get('X-AI-Run-ID')) || null
  await consumeRunEvents(response, runId, handlers, signal)
}

export async function resumeAiRun(
  runId: number,
  handlers: AiStreamHandlers,
  signal?: AbortSignal,
) {
  const user = useUserStore()
  const response = await fetch(`/api/v2/ai/runs/${runId}/events`, {
    headers: authHeaders(user.accessToken),
    signal,
  })
  await consumeRunEvents(response, runId, handlers, signal)
}

export type { AiCitation, AiConfirmation }
