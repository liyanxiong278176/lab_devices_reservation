import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElNotification } from 'element-plus'
import * as notifApi from '@/api/notification'

/** WebSocket 推送的消息体（NotificationVO 的子集，字段均可缺省）。 */
interface WsNotificationBody {
  title?: string
  content?: string
}

/**
 * 通知 store。
 *
 * S1：30s 轮询拉取未读数（mainlayout 启动定时器）。
 * S3：WebSocket 推送消息时 onMessage 弹 toast 并累加未读。
 */
export const useNotificationStore = defineStore('notification', () => {
  const unread = ref(0)

  async function loadUnread() {
    try {
      unread.value = await notifApi.unreadCount()
    } catch {
      // 轮询失败静默忽略，不打扰用户
    }
  }

  /** S3 WebSocket 推送回调：弹通知 toast + 未读 +1。 */
  function onMessage(body: WsNotificationBody = {}) {
    unread.value++
    ElNotification({
      title: body.title || '通知',
      message: body.content || '',
      type: 'info',
      position: 'top-right',
      duration: 4500,
    })
  }

  return { unread, loadUnread, onMessage }
})
