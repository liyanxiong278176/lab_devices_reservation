import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ElNotification } from 'element-plus'
import * as notifApi from '@/api/notification'

interface StreamNotificationBody {
  id?: number
  title?: string
  content?: string
}

interface DeliveryBatchSummary {
  replay?: boolean
  deliveredCount?: number
  omittedCount?: number
  historySyncRequired?: boolean
}

const UNREAD_REFRESH_DEBOUNCE_MS = 200

/** MySQL-backed notification state plus per-EventSource delivery deduplication. */
export const useNotificationStore = defineStore('notification', () => {
  const unread = ref(0)
  const historyRevision = ref(0)
  let unreadRefreshTimer: ReturnType<typeof setTimeout> | null = null
  let unreadRequestVersion = 0
  let highestDeliverySequence = 0
  let batchReplay = false
  const pendingBatch = new Map<number, StreamNotificationBody>()

  async function loadUnread() {
    const requestVersion = ++unreadRequestVersion
    try {
      const count = await notifApi.unreadCount()
      if (requestVersion === unreadRequestVersion) unread.value = count
    } catch {
      // HTTP history remains available for the next read or polling refresh.
    }
  }

  function scheduleUnreadRefresh() {
    if (unreadRefreshTimer) clearTimeout(unreadRefreshTimer)
    unreadRefreshTimer = setTimeout(() => {
      unreadRefreshTimer = null
      void loadUnread()
    }, UNREAD_REFRESH_DEBOUNCE_MS)
  }

  function beginEventStream() {
    highestDeliverySequence = 0
    batchReplay = false
    pendingBatch.clear()
  }

  function beginDeliveryBatch(replay: boolean) {
    batchReplay = batchReplay || replay
  }

  function onStreamNotification(body: StreamNotificationBody, eventId: string) {
    const sequence = Number(eventId)
    if (!Number.isSafeInteger(sequence) || sequence <= 0 || sequence <= highestDeliverySequence) return
    highestDeliverySequence = sequence
    pendingBatch.set(sequence, body)
    scheduleUnreadRefresh()
  }

  function completeDeliveryBatch(summary: DeliveryBatchSummary, eventId: string) {
    const cursor = Number(eventId)
    if (Number.isSafeInteger(cursor) && cursor > highestDeliverySequence) {
      highestDeliverySequence = cursor
    }

    const omittedCount = Number.isSafeInteger(summary.omittedCount)
      ? Math.max(0, Number(summary.omittedCount))
      : 0
    const totalCount = pendingBatch.size + omittedCount
    const replay = batchReplay || summary.replay === true
    if (totalCount > 0) {
      if (replay || totalCount > 1 || summary.historySyncRequired) {
        ElNotification({
          title: replay ? '断线通知已同步' : '收到新通知',
          message: replay
            ? `断线期间有 ${totalCount} 条新通知，已同步到通知中心`
            : `收到 ${totalCount} 条新通知，已同步到通知中心`,
          type: 'info',
          position: 'top-right',
          duration: 4500,
        })
      } else {
        const [notification] = pendingBatch.values()
        ElNotification({
          title: notification?.title || '通知',
          message: notification?.content || '',
          type: 'info',
          position: 'top-right',
          duration: 4500,
        })
      }
    }

    pendingBatch.clear()
    batchReplay = false
    historyRevision.value += 1
    if (unreadRefreshTimer) clearTimeout(unreadRefreshTimer)
    unreadRefreshTimer = null
    void loadUnread()
  }

  function onReadStateChanged() {
    historyRevision.value += 1
    if (unreadRefreshTimer) clearTimeout(unreadRefreshTimer)
    unreadRefreshTimer = null
    void loadUnread()
  }

  function decreaseUnread(amount = 1) {
    unread.value = Math.max(0, unread.value - Math.max(0, amount))
  }

  function clearUnread() {
    unread.value = 0
  }

  return {
    unread,
    historyRevision,
    loadUnread,
    decreaseUnread,
    clearUnread,
    beginEventStream,
    beginDeliveryBatch,
    onStreamNotification,
    completeDeliveryBatch,
    onReadStateChanged,
  }
})
