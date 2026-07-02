import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as notifApi from '@/api/notification'

/**
 * 通知 store。
 *
 * S1：30s 轮询拉取未读数（mainlayout 启动定时器）。
 * S3 将升级为 WebSocket 推送：服务端下发消息时调用 onMessage 累加未读。
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

  /** S3 WebSocket 推送消息回调：收到一条新消息则未读 +1。 */
  function onMessage(_body: unknown) {
    unread.value++
  }

  return { unread, loadUnread, onMessage }
})
