import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useUserStore } from '@/stores/user'
import { connectWs, disconnectWs } from '../useWebSocket'

vi.mock('@/stores/user', () => ({ useUserStore: vi.fn() }))
vi.mock('@/stores/notification', () => ({ useNotificationStore: vi.fn() }))

class MockWebSocket {
  static OPEN = 1
  static instances: MockWebSocket[] = []

  readyState = 0
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  send = vi.fn()
  close = vi.fn()
  readonly url: string

  constructor(url: string) {
    this.url = url
    MockWebSocket.instances.push(this)
  }
}

describe('notification WebSocket authentication', () => {
  const mockedUseUserStore = vi.mocked(useUserStore)

  beforeEach(() => {
    MockWebSocket.instances = []
    vi.stubGlobal('WebSocket', MockWebSocket)
    mockedUseUserStore.mockReturnValue({ accessToken: 'secret-access-token' } as never)
  })

  afterEach(() => {
    disconnectWs()
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it('does not put the bearer token in the URL and sends it only in the auth frame', () => {
    connectWs()
    const socket = MockWebSocket.instances[0]
    expect(socket.url).toMatch(/\/api\/v2\/ws$/)
    expect(socket.url).not.toContain('secret-access-token')
    expect(socket.url).not.toContain('?token=')

    socket.readyState = MockWebSocket.OPEN
    socket.onopen?.(new Event('open'))

    expect(socket.send).toHaveBeenCalledWith(
      JSON.stringify({ type: 'auth', token: 'secret-access-token' }),
    )
  })
})
