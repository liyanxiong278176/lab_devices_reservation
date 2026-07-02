import request from './request'
import type { Page } from '@/types/common'
import type { NotificationVO } from '@/types/notification'

/**
 * 通知接口（对齐 NotificationController）。任意已登录用户查/读自己的通知。
 *
 * 关键契约：
 *  - GET   /notifications/mine?onlyUnread&page&size → IPage<NotificationVO>
 *  - PATCH /notifications/{id}/read                 → 标记单条已读
 *  - PATCH /notifications/read-all                  → 全部未读标记已读
 */
export const myNotifications = (params: { onlyUnread?: boolean; page?: number; size?: number } = {}) =>
  request.get<unknown, Page<NotificationVO>>('/notifications/mine', { params })

export const markRead = (id: number) =>
  request.patch<unknown, void>(`/notifications/${id}/read`)

export const markAllRead = () =>
  request.patch<unknown, void>('/notifications/read-all')

/**
 * 未读数（轮询用）。只取 IPage.total，避免拉取整页数据。
 * S3 将升级为 WebSocket 推送；此处为 30s 轮询兜底。
 */
export async function unreadCount(): Promise<number> {
  const page = await request.get<unknown, Page<NotificationVO>>('/notifications/mine', {
    params: { onlyUnread: true, page: 1, size: 1 },
  })
  return page.total
}
