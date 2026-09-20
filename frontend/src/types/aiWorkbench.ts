export interface AiConversation {
  id: number
  title: string
  status: string
  created_at?: string
  updated_at?: string
}

export interface AiMessage {
  id: number | string
  role: 'user' | 'assistant' | 'tool' | 'system'
  content: string
  metadata?: Record<string, unknown>
  created_at?: string
}

export interface AiCitation {
  point_id?: string
  document_id?: number
  title: string
  content: string
  score?: number
  source_type?: string
  college_id?: number | null
}

export interface AiStep {
  name: string
  status: string
  intent?: string
  source_count?: number
}

export interface AiConfirmation {
  id: number
  run_id?: number
  tool_name: string
  reason: string
  risk_summary: string
  estimated_impact: string
  preview: Record<string, unknown>
  status: string
  expires_at?: string
}

export interface AiModelConfig {
  scope: string
  provider: string | null
  model: string | null
  base_url: string | null
  configured: boolean
  enabled: boolean
  daily_quota: number
}

export interface AiModelConfigPayload {
  provider: string
  model: string
  api_key?: string
  base_url?: string
  enabled: boolean
  daily_quota: number
}

export interface AiStreamEvent {
  type: string
  run_id?: number
  text?: string
  message?: string
  status?: string
  name?: string
  intent?: string
  sources?: AiCitation[]
  citations?: AiCitation[]
  confirmation_id?: number
  tool_name?: string
  reason?: string
  risk_summary?: string
  estimated_impact?: string
  preview?: Record<string, unknown>
  code?: string
}
