import request from './request'

/**
 * 推荐单个设备项（对齐 RecommendationItemVO）。
 *
 * 关键字段：
 *  - score    综合得分（0~1，保留 4 位小数；冷启动热门场景可能为 0）
 *  - reason   可解释推荐理由（"近30天热门设备" / 个性化亲和理由）
 */
export interface RecommendationItem {
  deviceId: number
  name: string
  categoryId?: number
  categoryName?: string
  labId?: number
  labName?: string
  score: number
  reason: string
  brand?: string
  model?: string
  status?: string
  pricePerHour?: number
}

/**
 * GET /recommendations?limit=<n>
 * 任意已认证用户可调用；冷启动 → 热门 + "近30天热门设备"；有历史 → 个性化亲和理由。
 */
export const getRecommendations = (limit = 10) =>
  request.get<unknown, RecommendationItem[]>('/recommendations', {
    params: { limit },
  })
