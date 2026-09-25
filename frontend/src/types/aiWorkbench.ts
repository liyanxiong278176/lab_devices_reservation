export interface AiConversation {
  id: number
  title: string
  status: string
  created_at?: string
  updated_at?: string
}

export interface AiReadiness {
  available: boolean
  chat_configured: boolean
  embedding_configured: boolean
  message: string
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
  component: 'chat' | 'embedding' | 'mineru'
  scope: string
  source: 'environment' | 'missing'
  provider: string | null
  model: string | null
  base_url: string | null
  configured: boolean
  enabled: boolean
  daily_quota: number
  user_daily_token_cap: number
  college_daily_token_cap: number
  global_daily_token_cap: number
  last_tested_at: string | null
}

export interface AiUsageReport {
  mine: { date: string; used_tokens: number; reserved_tokens: number; daily_cap: number }
  auxiliary?: Array<{
    component: 'embedding' | 'mineru' | string
    operation: string
    request_count: number
    item_count: number
    input_units: number
  }>
  college?: { date: string; used_tokens: number; reserved_tokens: number; daily_cap: number }
  global?: { date: string; used_tokens: number; reserved_tokens: number; daily_cap: number }
  colleges?: Array<{
    college_id: number
    college_name: string
    used_tokens: number
    reserved_tokens: number
    daily_cap: number
  }>
}

export interface AiEmbeddingRebuildJob {
  id: number
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'ROLLED_BACK' | 'FAILED' | string
  source_collection: string
  target_collection: string
  model: string
  total_points: number
  indexed_points: number
  error_code?: string | null
  created_at?: string | null
  completed_at?: string | null
}

export interface KnowledgeDocument {
  id: number
  title: string
  source_type: string
  college_id: number | null
  status: string
  version: number
  chunk_count: number
  created_at?: string | null
  published_at?: string | null
  source_file_name?: string | null
  parse_status: string
  parse_error?: string | null
}

export interface KnowledgeChunkPreview {
  index: number
  content: string
  characters: number
}

export interface AiStreamEvent {
  type: string
  status?: string
  run_id?: number
  text?: string
  message?: string
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
