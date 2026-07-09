/**
 * AI 助手 — 服务端推送帧 union (按 type 字段 router)。
 * 与后端 WsServerMsg sealed interface 一一对应。
 */
export type WsServerFrame =
  | { type: 'delta'; seq: number; conv_id: number; text: string }
  | {
      type: 'step_update'
      seq: number
      conv_id: number
      step_id: number
      status: 'started' | 'completed' | 'cancelled' | 'failed'
      text: string
      duration_ms?: number
    }
  | { type: 'suggestions'; seq: number; conv_id: number; items: Array<{ label: string; value: string }> }
  | { type: 'assistant_done'; seq: number; conv_id: number; text: string; tool_calls: unknown[] }
  | {
      type: 'confirmation_required'
      seq: number
      conv_id: number
      action_id: number
      tool_name: string
      reason: string
      risk_summary: string
      estimated_impact: string
    }
  | { type: 'confirmation_expired'; seq: number; conv_id: number; action_id: number }
  | {
      type: 'execution_result'
      seq: number
      conv_id: number
      action_id: number
      ok: boolean
      code: string
      msg: string
      data: unknown
    }
  | { type: 'error'; seq: number; conv_id: number; code: string; msg: string }
  | { type: 'ping'; seq: number; conv_id: number; ts: number }

/** 客户端发送 union — backend 走 /app/assistant/{send,confirm,cancel,resync,cancel_session} */
export type WsClientMsg =
  | { kind: 'user_message'; convId: number | null; text: string }
  | { kind: 'confirm_action'; actionId: number }
  | { kind: 'cancel_action'; actionId: number }
  | { kind: 'resync'; convId: number; lastSeq: number }
  | { kind: 'cancel_session'; convId: number }

/** 商店里的消息条目 */
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant' | 'tool' | 'system'
  text: string
  toolCalls?: unknown[]
  confirmation?: ConfirmationState
  stepUpdates?: StepUpdateItem[]
  suggestions?: Array<{ label: string; value: string }>
  timestamp: number
}

export interface ConfirmationState {
  actionId: number
  toolName: string
  reason: string
  riskSummary: string
  estimatedImpact: string
  status: 'pending' | 'confirmed' | 'cancelled' | 'expired' | 'executed' | 'error'
}

export interface StepUpdateItem {
  stepId: number
  status: 'started' | 'completed' | 'cancelled' | 'failed'
  text: string
  durationMs?: number
  timestamp: number
}

export type AiAssistantState =
  | 'idle'
  | 'sending'
  | 'streaming'
  | 'step_running'
  | 'awaiting_confirmation'
  | 'executing'
  | 'done'
  | 'error'
