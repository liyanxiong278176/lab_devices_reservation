export type AiProvider = 'deepseek' | 'openai' | 'siliconflow' | 'glm' | 'minimax' | 'custom'

export interface AiCredentialVO {
  provider: string
  baseUrl: string
  apiKeyMasked: string
  model: string
  temperature: number | null
  configured: boolean
}

export interface AiCredentialSaveDTO {
  provider: AiProvider
  baseUrl: string
  apiKey: string
  model: string
  temperature?: number | null
}

export const PROVIDER_PRESETS: Record<AiProvider, { baseUrl: string; model: string }> = {
  deepseek:    { baseUrl: 'https://api.deepseek.com',          model: 'deepseek-v4-flash' },
  openai:      { baseUrl: 'https://api.openai.com',            model: 'gpt-4o-mini' },
  siliconflow: { baseUrl: 'https://api.siliconflow.cn',        model: 'deepseek-ai/DeepSeek-V3' },
  glm:         { baseUrl: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-flash' },
  minimax:     { baseUrl: 'https://api.minimaxi.com/v1',       model: 'MiniMax-Text-01' },
  custom:      { baseUrl: '',                                   model: '' },
}
