import request from './request'
import type {
  AiCitation,
  AiConfirmation,
  AiConversation,
  AiModelConfig,
  AiModelConfigPayload,
  AiMessage,
  AiStreamEvent,
} from '@/types/aiWorkbench'
import { useUserStore } from '@/stores/user'

export const listAiConversations = () =>
  request.get<unknown, AiConversation[]>('/ai/conversations')

export const createAiConversation = (title?: string) =>
  request.post<unknown, AiConversation>('/ai/conversations', { title })

export const listAiMessages = (conversationId: number) =>
  request.get<unknown, AiMessage[]>(`/ai/conversations/${conversationId}/messages`)

export const getAiModelConfig = () =>
  request.get<unknown, AiModelConfig>('/ai/config')

export const updateAiModelConfig = (payload: AiModelConfigPayload) =>
  request.put<unknown, AiModelConfig>('/ai/config', payload)

export const confirmAiAction = (confirmationId: number) =>
  request.post<unknown, { confirmation_id: number; status: string; data: unknown }>(
    `/ai/confirmations/${confirmationId}/confirm`,
  )

export const cancelAiAction = (confirmationId: number) =>
  request.post<unknown, { confirmation_id: number; status: string }>(
    `/ai/confirmations/${confirmationId}/cancel`,
  )

export interface AiStreamHandlers {
  onEvent?: (event: AiStreamEvent) => void
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
    headers: {
      Authorization: `Bearer ${user.accessToken}`,
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({ content }),
  })
  if (!response.ok || !response.body) {
    let message = 'AI 服务暂时不可用'
    try {
      const body = await response.json()
      message = body.message || message
    } catch {
      // Preserve the safe fallback message.
    }
    throw new Error(message)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const frames = buffer.split('\n\n')
    buffer = frames.pop() || ''
    for (const frame of frames) {
      const dataLine = frame.split('\n').find((line) => line.startsWith('data:'))
      if (!dataLine) continue
      try {
        const event = JSON.parse(dataLine.slice(5).trim()) as AiStreamEvent
        handlers.onEvent?.(event)
      } catch {
        // Ignore malformed keep-alive frames; the server sends typed JSON frames.
      }
    }
  }
}

export type { AiCitation, AiConfirmation }
