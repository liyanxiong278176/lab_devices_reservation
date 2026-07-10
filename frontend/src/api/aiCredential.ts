import request from './request'
import type { AiCredentialVO, AiCredentialSaveDTO } from '@/types/aiConfig'

/** GET /ai/credential — 本人当前配置(key masked,明文永不返回) */
export const getAiCredential = () => request.get<unknown, AiCredentialVO>('/ai/credential')

/** POST /ai/credential — 保存(test 失败后端抛 BusinessException 不落库) */
export const saveAiCredential = (dto: AiCredentialSaveDTO) =>
  request.post<unknown, AiCredentialVO>('/ai/credential', dto)

/** DELETE /ai/credential — 清除(回到未配置) */
export const deleteAiCredential = () => request.delete<unknown, void>('/ai/credential')
