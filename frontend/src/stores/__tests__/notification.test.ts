import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { ElNotification } from 'element-plus'

const notificationApi = vi.hoisted(() => ({ unreadCount: vi.fn() }))
vi.mock('@/api/notification', () => notificationApi)
vi.mock('element-plus', () => ({ ElNotification: vi.fn() }))

import { useNotificationStore } from '../notification'

describe('notification SSE state', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    notificationApi.unreadCount.mockResolvedValue(0)
    vi.clearAllMocks()
  })

  afterEach(() => vi.useRealTimers())

  it('marks one notification as read without going below zero', () => {
    const store = useNotificationStore()
    store.unread = 2
    store.decreaseUnread()
    expect(store.unread).toBe(1)
    store.decreaseUnread(5)
    expect(store.unread).toBe(0)
  })

  it('can immediately clear the badge after marking all notifications as read', () => {
    const store = useNotificationStore()
    store.unread = 16
    store.clearUnread()
    expect(store.unread).toBe(0)
  })

  it('deduplicates by the per-user SSE event ID and shows one reconnect summary', async () => {
    const store = useNotificationStore()
    store.beginEventStream()
    store.beginDeliveryBatch(true)
    store.onStreamNotification({ id: 91, title: '预约已通过' }, '12')
    store.onStreamNotification({ id: 92, title: '设备交接提醒' }, '13')
    store.onStreamNotification({ id: 92, title: '重复事件' }, '13')

    expect(ElNotification).not.toHaveBeenCalled()
    store.completeDeliveryBatch({ replay: true, deliveredCount: 2 }, '13')

    expect(ElNotification).toHaveBeenCalledOnce()
    expect(ElNotification).toHaveBeenCalledWith(expect.objectContaining({
      title: '断线通知已同步',
      message: '断线期间有 2 条新通知，已同步到通知中心',
    }))
    expect(store.historyRevision).toBe(1)
    await Promise.resolve()
    expect(notificationApi.unreadCount).toHaveBeenCalledOnce()
  })

  it('does not notify twice when automatic reconnect replays the last event ID', () => {
    const store = useNotificationStore()
    store.beginEventStream()
    store.beginDeliveryBatch(false)
    store.onStreamNotification({ id: 91, title: '预约已通过' }, '12')
    store.completeDeliveryBatch({ replay: false, deliveredCount: 1 }, '12')

    // The same EventSource keeps its cursor across a transient network failure.
    store.beginDeliveryBatch(true)
    store.onStreamNotification({ id: 91, title: '重连重复事件' }, '12')
    store.completeDeliveryBatch({ replay: true, deliveredCount: 1 }, '12')

    expect(ElNotification).toHaveBeenCalledOnce()
    expect(store.historyRevision).toBe(2)
  })

  it('uses HTTP history for events omitted by the 100-event replay cap', () => {
    const store = useNotificationStore()
    store.beginEventStream()
    store.beginDeliveryBatch(true)
    store.onStreamNotification({ id: 1, title: '补发' }, '1')
    store.completeDeliveryBatch({
      replay: true,
      deliveredCount: 1,
      omittedCount: 104,
      historySyncRequired: true,
    }, '106')

    expect(ElNotification).toHaveBeenCalledWith(expect.objectContaining({
      message: '断线期间有 105 条新通知，已同步到通知中心',
    }))
    expect(store.historyRevision).toBe(1)
  })

  it('shows a detailed toast for a single live notification after its batch completes', () => {
    const store = useNotificationStore()
    store.beginEventStream()
    store.beginDeliveryBatch(false)
    store.onStreamNotification({ id: 8, title: '预约结果', content: '已通过' }, '20')
    store.completeDeliveryBatch({ replay: false, deliveredCount: 1 }, '20')

    expect(ElNotification).toHaveBeenCalledWith(expect.objectContaining({
      title: '预约结果',
      message: '已通过',
    }))
  })

  it('coalesces multiple live notifications into one summary', () => {
    const store = useNotificationStore()
    store.beginEventStream()
    store.beginDeliveryBatch(false)
    store.onStreamNotification({ id: 8, title: 'A' }, '30')
    store.onStreamNotification({ id: 9, title: 'B' }, '31')
    store.completeDeliveryBatch({ replay: false, deliveredCount: 2 }, '31')

    expect(ElNotification).toHaveBeenCalledOnce()
    expect(ElNotification).toHaveBeenCalledWith(expect.objectContaining({
      message: '收到 2 条新通知，已同步到通知中心',
    }))
  })

  it('refreshes unread count and active history after another tab changes read state', async () => {
    const store = useNotificationStore()
    store.onReadStateChanged()
    await Promise.resolve()
    expect(store.historyRevision).toBe(1)
    expect(notificationApi.unreadCount).toHaveBeenCalledOnce()
  })

  it('ignores invalid and non-increasing sequence IDs', () => {
    const store = useNotificationStore()
    store.beginEventStream()
    store.beginDeliveryBatch(false)
    store.onStreamNotification({ id: 1 }, 'bad')
    store.onStreamNotification({ id: 2 }, '42')
    store.onStreamNotification({ id: 1 }, '41')
    store.completeDeliveryBatch({ deliveredCount: 1 }, '42')

    expect(ElNotification).toHaveBeenCalledOnce()
    expect(ElNotification).toHaveBeenCalledWith(expect.objectContaining({ title: '通知' }))
  })

  it('does not let a slower stale unread request overwrite a newer snapshot', async () => {
    const store = useNotificationStore()
    let resolveFirst!: (count: number) => void
    let resolveSecond!: (count: number) => void
    notificationApi.unreadCount
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirst = resolve }))
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve }))

    const first = store.loadUnread()
    const second = store.loadUnread()
    resolveSecond(12)
    await second
    resolveFirst(11)
    await first
    expect(store.unread).toBe(12)
  })
})
