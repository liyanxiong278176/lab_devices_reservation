import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const notificationApi = vi.hoisted(() => ({
  unreadCount: vi.fn(),
}))

vi.mock('@/api/notification', () => notificationApi)

import { useNotificationStore } from '../notification'

describe('notification unread count', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

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
})
