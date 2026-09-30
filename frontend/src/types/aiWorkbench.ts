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

export interface AiMemoryCandidate {
  id: number
  scenario: string
  content: string
  status?: string
}

export interface AiDomainTerm {
  id: number
  college_id: number | null
  term: string
  canonical: string | null
  kind: 'SYNONYM' | 'IGNORE'
  status: string
}

export interface AiCitation {
  citation_id?: string
  point_id?: string
  document_id?: number
  title: string
  content: string
  score?: number
  source_type?: string
  college_id?: number | null
  section?: string
}

export interface AiCitationDetail {
  citation_id: string
  document_id?: number
  document_version: number
  title: string
  source_type: string
  section: string
  content: string
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

export interface KnowledgeBuildJob {
  job_id: string
  task_id: string
  document_id: number
  version: number
  status: 'QUEUED' | 'PROCESSING' | 'RETRYING' | 'COMPLETED' | 'FAILED' | 'CANCELLED' | 'SKIPPED' | string
  stage: string
  progress_percent: number | null
  completed_units: number
  total_units: number | null
  unit: string | null
  attempts: number
  redeliveries: number
  dispatch_recoveries: number
  skipped_by?: number | null
  skipped_at?: string | null
  skip_reason?: string | null
  blocking_job_id?: string | null
  blocking_job_version?: number | null
  blocking_job_status?: string | null
  blocking_job_error_summary?: string | null
  error_summary?: string | null
  created_at?: string | null
  queued_at?: string | null
  started_at?: string | null
  updated_at?: string | null
  completed_at?: string | null
}

export interface KnowledgeBuildAccepted {
  document_id: number
  job_id: string
  task_id: string
  status: string
  build_job: KnowledgeBuildJob
}

export interface KnowledgeDocument {
  id: number
  title: string
  source_type: string
  college_id: number | null
  lab_id?: number | null
  device_id?: number | null
  allowed_roles?: string[]
  status: string
  version: number
  chunk_count: number
  created_at?: string | null
  published_at?: string | null
  source_file_name?: string | null
  parse_status: string
  parse_error?: string | null
  build_job?: KnowledgeBuildJob | null
}

export interface KnowledgeChunkPreview {
  index: number
  section_path?: string
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
  categories?: string[]
  redacted_content?: string
  items?: AiMemoryCandidate[]
}
