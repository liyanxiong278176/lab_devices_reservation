/** 通知返回视图。 */
export interface NotificationVO {
  id: number
  userId: number
  type: string
  title: string
  content?: string
  relatedId?: number
  relatedType?: string
  /** 0 未读 / 1 已读 */
  isRead: number
  createdAt?: string
}
