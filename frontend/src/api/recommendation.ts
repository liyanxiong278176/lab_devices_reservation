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

interface V2RecommendationItem {
  device_id: number
  name: string
  category_id?: number | null
  category_name?: string | null
  lab_id?: number | null
  lab_name?: string | null
  score: number
  reason: string
  brand?: string | null
  model?: string | null
  status?: string | null
}

function mapRecommendation(item: V2RecommendationItem): RecommendationItem {
  return {
    deviceId: item.device_id,
    name: item.name,
    categoryId: item.category_id ?? undefined,
    categoryName: item.category_name ?? undefined,
    labId: item.lab_id ?? undefined,
    labName: item.lab_name ?? undefined,
    score: item.score,
    reason: item.reason,
    brand: item.brand ?? undefined,
    model: item.model ?? undefined,
    status: item.status ?? undefined,
  }
}

/**
 * GET /recommendations?limit=<n>
 * 任意已认证用户可调用；冷启动 → 热门 + "近30天热门设备"；有历史 → 个性化亲和理由。
 */
export const getRecommendations = (limit = 10) =>
  request.get<unknown, V2RecommendationItem[]>('/recommendations', {
    params: { limit },
  }).then((items) => items.map(mapRecommendation))
