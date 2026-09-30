import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useUserStore } from '@/stores/user'
import { useNotificationStore } from '@/stores/notification'
import { connectEventStream, disconnectEventStream } from '../useEventStream'

vi.mock('@/stores/user', () => ({ useUserStore: vi.fn() }))
vi.mock('@/stores/notification', () => ({ useNotificationStore: vi.fn() }))

class MockEventSource {
  static instances: MockEventSource[] = []
  readonly url: string
  readonly options: EventSourceInit | undefined
  readonly listeners = new Map<string, EventListener>()
  readyState = 1
  lastEventId = ''
  close = vi.fn()

  constructor(url: string | URL, options?: EventSourceInit) {
    this.url = String(url)
    this.options = options
    MockEventSource.instances.push(this)
  }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject | null) {
    if (typeof listener === 'function') this.listeners.set(type, listener)
  }

  dispatch(type: string, event: Event) {
    this.listeners.get(type)?.(event)
  }

  simulateDisconnect() {
    this.readyState = 0
    this.dispatch('error', new Event('error'))
  }

  simulateAutomaticReconnect(sequence: string) {
    // Native EventSource retries on the same object and retains its Last-Event-ID.
    this.readyState = 1
    this.lastEventId = sequence
    this.dispatch('notification', new MessageEvent('notification', {
      data: `{"id":31,"title":"预约结果"}`,
      lastEventId: sequence,
    }))
  }
}

describe('notification EventSource transport', () => {
  const mockedUseUserStore = vi.mocked(useUserStore)
  const mockedUseNotificationStore = vi.mocked(useNotificationStore)
  const notificationStore = {
    beginEventStream: vi.fn(),
    beginDeliveryBatch: vi.fn(),
    onStreamNotification: vi.fn(),
    completeDeliveryBatch: vi.fn(),
    onReadStateChanged: vi.fn(),
    loadUnread: vi.fn(),
  }

  beforeEach(() => {
    MockEventSource.instances = []
    vi.stubGlobal('EventSource', MockEventSource)
    mockedUseUserStore.mockReturnValue({ isAuthenticated: true } as never)
    mockedUseNotificationStore.mockReturnValue(notificationStore as never)
  })

  afterEach(() => {
    disconnectEventStream()
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it('opens a same-origin credentialed stream without exposing a token', () => {
    connectEventStream()
    expect(MockEventSource.instances).toHaveLength(1)
    expect(MockEventSource.instances[0].url).toBe('/api/v2/notifications/stream')
    expect(MockEventSource.instances[0].options).toEqual({ withCredentials: true })
    expect(notificationStore.beginEventStream).toHaveBeenCalledOnce()
  })

  it('routes notification batches, read state, and unread reconciliation', () => {
    connectEventStream()
    const source = MockEventSource.instances[0]
    source.dispatch('batch-start', new MessageEvent('batch-start', { data: '{"replay":true}' }))
    source.dispatch('notification', new MessageEvent('notification', {
      data: '{"id":31,"title":"预约结果"}',
      lastEventId: '17',
    }))
    source.dispatch('batch-complete', new MessageEvent('batch-complete', {
      data: '{"replay":true,"deliveredCount":1}',
      lastEventId: '17',
    }))
    source.dispatch('read-state-changed', new Event('read-state-changed'))
    source.dispatch('stream-ready', new Event('stream-ready'))

    expect(notificationStore.beginDeliveryBatch).toHaveBeenCalledWith(true)
    expect(notificationStore.onStreamNotification).toHaveBeenCalledWith(
      { id: 31, title: '预约结果' },
      '17',
    )
    expect(notificationStore.completeDeliveryBatch).toHaveBeenCalledWith(
      { replay: true, deliveredCount: 1 },
      '17',
    )
    expect(notificationStore.onReadStateChanged).toHaveBeenCalledOnce()
    expect(notificationStore.loadUnread).toHaveBeenCalledOnce()
  })

  it('keeps one EventSource during disconnect/reconnect and forwards replay with its sequence', () => {
    connectEventStream()
    const source = MockEventSource.instances[0]
    source.simulateDisconnect()
    source.simulateAutomaticReconnect('17')

    expect(MockEventSource.instances).toHaveLength(1)
    expect(source.readyState).toBe(1)
    expect(source.lastEventId).toBe('17')
    expect(source.close).not.toHaveBeenCalled()
    expect(notificationStore.onStreamNotification).toHaveBeenCalledWith(
      { id: 31, title: '预约结果' },
      '17',
    )
  })

  it('ignores malformed events and closes on server-side session revocation', () => {
    connectEventStream()
    const source = MockEventSource.instances[0]
    source.dispatch('notification', new MessageEvent('notification', {
      data: '{malformed',
      lastEventId: '3',
    }))
    expect(notificationStore.onStreamNotification).not.toHaveBeenCalled()

    source.dispatch('auth-revoked', new Event('auth-revoked'))
    expect(source.close).toHaveBeenCalledOnce()
  })

  it('does not open a stream for an unauthenticated session', () => {
    mockedUseUserStore.mockReturnValue({ isAuthenticated: false } as never)
    connectEventStream()
    expect(MockEventSource.instances).toHaveLength(0)
  })

  it('does not open duplicate EventSource instances', () => {
    connectEventStream()
    connectEventStream()
    expect(MockEventSource.instances).toHaveLength(1)
  })
})
