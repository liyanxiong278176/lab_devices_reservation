export type AiProvider = 'deepseek' | 'openai' | 'siliconflow' | 'glm' | 'minimax' | 'xiaomi' | 'custom'

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
  glm:         { baseUrl: 'https://open.bigmodel.cn/api/paas/v4', model: 'GLM-4.5-Flash' },
  minimax:     { baseUrl: 'https://api.minimaxi.com/v1',       model: 'MiniMax-Text-01' },
  xiaomi:      { baseUrl: 'https://token-plan-cn.xiaomimimo.com/v1', model: 'mimo-v2.5' },
  custom:      { baseUrl: '',                                   model: '' },
}
