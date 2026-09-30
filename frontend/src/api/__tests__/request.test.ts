import type { AxiosInstance } from 'axios'
import axios from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import router from '@/router'
import { useUserStore } from '@/stores/user'
import service, { csrfHeaders, fetchWithSession } from '../request'

const messageMocks = vi.hoisted(() => ({ error: vi.fn() }))
vi.mock('element-plus', () => ({ ElMessage: { error: messageMocks.error } }))
vi.mock('@/router', () => ({
  default: {
    push: vi.fn(),
    currentRoute: { value: { path: '/devices', fullPath: '/devices' } },
  },
}))
vi.mock('@/stores/user', () => ({ useUserStore: vi.fn() }))

describe('request authentication recovery', () => {
  const mockedUseUserStore = vi.mocked(useUserStore)
  const mockedRouter = vi.mocked(router)
  let userStore: {
    refresh: ReturnType<typeof vi.fn>
    clearProfile: ReturnType<typeof vi.fn>
  }

  beforeEach(() => {
    vi.clearAllMocks()
    Object.assign(mockedRouter.currentRoute.value, { path: '/devices', fullPath: '/devices' })
    const storedValues = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => storedValues.get(key) ?? null,
      setItem: (key: string, value: string) => storedValues.set(key, String(value)),
      removeItem: (key: string) => storedValues.delete(key),
      clear: () => storedValues.clear(),
    })
    localStorage.clear()
    window.dispatchEvent(new StorageEvent('storage', {
      key: 'lab-auth-csrf-token',
      newValue: null,
    }))
    userStore = {
      refresh: vi.fn().mockRejectedValue(new Error('refresh rejected')),
      clearProfile: vi.fn(),
    }
    mockedUseUserStore.mockReturnValue(userStore as never)
    ;(service as AxiosInstance).defaults.adapter = async (config) =>
      Promise.reject({
        config,
        response: { status: 401, data: { code: 'TOKEN_INVALID', message: 'Unauthorized' } },
      })
  })

  afterEach(() => vi.unstubAllGlobals())

  function responseCallbacks() {
    return (service.interceptors.response as unknown as {
      handlers: Array<{
        fulfilled: (response: any) => unknown
        rejected: (error: any) => Promise<unknown>
      }>
    }).handlers[0]
  }

  it('does not try refresh for an anonymous auth/me request', async () => {
    const adapter = vi.fn(async (config) => Promise.reject({
      config,
      response: { status: 401, data: { code: 'AUTH_REQUIRED', message: '请先登录' } },
    }))
    ;(service as AxiosInstance).defaults.adapter = adapter

    await expect(service.get('/auth/me')).rejects.toMatchObject({
      response: { status: 401, data: { code: 'AUTH_REQUIRED' } },
    })

    expect(adapter).toHaveBeenCalledOnce()
    expect(userStore.refresh).not.toHaveBeenCalled()
    expect(userStore.clearProfile).not.toHaveBeenCalled()
    expect(mockedRouter.push).not.toHaveBeenCalled()
  })

  it('clears the in-memory profile and redirects when cookie refresh is rejected', async () => {
    const outcome = await Promise.race([
      service.get('/auth/me').then(
        () => 'resolved',
        () => 'rejected',
      ),
      new Promise<'timed-out'>((resolve) => {
        setTimeout(() => resolve('timed-out'), 300)
      }),
    ])

    expect(outcome).toBe('rejected')
    expect(userStore.clearProfile).toHaveBeenCalledOnce()
    expect(mockedRouter.push).toHaveBeenCalledWith({
      path: '/login',
      query: { redirect: '/devices' },
    })
  })

  it('applies the same expired-session handling to streaming fetch requests', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 401 })))

    const response = await fetchWithSession('/api/v2/ai/runs/stream')

    expect(response.status).toBe(401)
    expect(userStore.clearProfile).toHaveBeenCalledOnce()
    expect(mockedRouter.push).toHaveBeenCalledWith({
      path: '/login',
      query: { redirect: '/devices' },
    })
  })

  it('uses a CSRF token shared by another browser tab', async () => {
    localStorage.setItem('lab-auth-csrf-token', 'token-from-another-tab')

    await expect(csrfHeaders()).resolves.toEqual({ 'X-CSRF-Token': 'token-from-another-tab' })
  })

  it('uses the in-memory token when storage events contain unrelated keys or storage is empty', async () => {
    window.dispatchEvent(new StorageEvent('storage', { key: 'unrelated-key', newValue: 'ignored' }))
    window.dispatchEvent(new StorageEvent('storage', {
      key: 'lab-auth-csrf-token',
      newValue: 'in-memory-token',
    }))
    localStorage.removeItem('lab-auth-csrf-token')

    await expect(csrfHeaders()).resolves.toEqual({ 'X-CSRF-Token': 'in-memory-token' })
  })

  it('reads a token published by another tab while waiting for the browser lock', async () => {
    const lockRequest = vi.fn(async (_name: string, callback: () => Promise<string>) => {
      localStorage.setItem('lab-auth-csrf-token', 'lock-owner-token')
      return callback()
    })
    vi.stubGlobal('navigator', { locks: { request: lockRequest } })
    const getToken = vi.spyOn(axios, 'get')

    await expect(csrfHeaders()).resolves.toEqual({ 'X-CSRF-Token': 'lock-owner-token' })
    expect(lockRequest).toHaveBeenCalledOnce()
    expect(getToken).not.toHaveBeenCalled()
  })

  it('shares one in-flight CSRF bootstrap request among concurrent callers', async () => {
    let resolveToken!: (response: unknown) => void
    const request = vi.spyOn(axios, 'get').mockImplementation(() => new Promise((resolve) => {
      resolveToken = resolve
    }) as never)

    const first = csrfHeaders()
    const second = csrfHeaders()
    expect(request).toHaveBeenCalledOnce()
    resolveToken({ data: { data: { csrf_token: 'shared-bootstrap-token' } } })

    await expect(Promise.all([first, second])).resolves.toEqual([
      { 'X-CSRF-Token': 'shared-bootstrap-token' },
      { 'X-CSRF-Token': 'shared-bootstrap-token' },
    ])
  })

  it('rejects malformed CSRF responses and keeps working when browser storage throws', async () => {
    vi.spyOn(axios, 'get').mockResolvedValueOnce({ data: { data: { csrf_token: '' } } } as never)
    await expect(csrfHeaders()).rejects.toThrow('无法初始化安全令牌，请刷新页面')

    const storage = {
      getItem: () => { throw new Error('storage read blocked') },
      setItem: () => { throw new Error('storage write blocked') },
      removeItem: () => { throw new Error('storage remove blocked') },
      clear: vi.fn(),
    }
    vi.stubGlobal('localStorage', storage)
    window.dispatchEvent(new StorageEvent('storage', {
      key: 'lab-auth-csrf-token',
      newValue: null,
    }))
    vi.spyOn(axios, 'get').mockResolvedValueOnce({
      data: { data: { csrf_token: 'memory-only-token' } },
    } as never)

    await expect(csrfHeaders()).resolves.toEqual({ 'X-CSRF-Token': 'memory-only-token' })
  })

  it('captures rotated CSRF tokens, unwraps successful envelopes, preserves raw bodies and clears logout state', async () => {
    const { fulfilled } = responseCallbacks()
    const sessionResponse = {
      config: { url: '/auth/refresh' },
      data: { code: 'OK', data: { csrf_token: 'rotated-token' } },
    }
    expect(fulfilled(sessionResponse)).toBe(sessionResponse.data.data)
    expect(localStorage.getItem('lab-auth-csrf-token')).toBe('rotated-token')
    expect(Number(localStorage.getItem('lab-auth-refreshed-at'))).toBeGreaterThan(0)

    const rawBody = { rows: [1, 2] }
    expect(fulfilled({ config: { url: '/devices' }, data: rawBody })).toBe(rawBody)

    localStorage.setItem('lab-auth-csrf-token', 'logout-token')
    expect(fulfilled({
      config: { url: '/auth/logout' },
      data: { code: 'OK', data: { loggedOut: true } },
    })).toEqual({ loggedOut: true })
    expect(localStorage.getItem('lab-auth-csrf-token')).toBeNull()

    const rejectedBody = { code: 'CONFLICT', message: '日期已占用' }
    await expect(fulfilled({ config: { url: '/reservations' }, data: rejectedBody })).rejects.toBe(rejectedBody)
    expect(messageMocks.error).toHaveBeenCalledWith('日期已占用')
    await expect(fulfilled({ config: { url: '/reservations' }, data: { code: 'FAILED' } }))
      .rejects.toMatchObject({ code: 'FAILED' })
    expect(messageMocks.error).toHaveBeenLastCalledWith('请求失败')
  })

  it('formats API failures by message, msg, transport error, and generic fallback', async () => {
    const { rejected } = responseCallbacks()
    const cases = [
      [{ config: { url: '/devices' }, response: { status: 400, data: { message: 'primary', msg: 'secondary' } } }, 'primary'],
      [{ config: { url: '/devices' }, response: { status: 400, data: { msg: 'secondary' } } }, 'secondary'],
      [{ message: 'connection failed' }, 'connection failed'],
      [{}, '网络错误'],
    ] as const

    for (const [error, message] of cases) {
      await expect(rejected(error)).rejects.toBe(error)
      expect(messageMocks.error).toHaveBeenLastCalledWith(message)
    }

    const authRefreshError = {
      config: { url: '/api/v2/auth/refresh' },
      response: { status: 401, data: { message: 'anonymous refresh' } },
    }
    await expect(rejected(authRefreshError)).rejects.toBe(authRefreshError)
    expect(messageMocks.error).toHaveBeenCalledTimes(cases.length)
  })

  it('does not redirect anonymous users already on login or registration pages', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 401 })))
    for (const path of ['/login', '/register']) {
      Object.assign(mockedRouter.currentRoute.value, { path, fullPath: path })
      const response = await fetchWithSession('/api/v2/devices')
      expect(response.status).toBe(401)
    }
    expect(userStore.clearProfile).toHaveBeenCalledTimes(2)
    expect(mockedRouter.push).not.toHaveBeenCalled()
  })

  it('retries a write once with a fresh token after a cross-tab CSRF mismatch', async () => {
    localStorage.setItem('lab-auth-csrf-token', 'stale-token')
    vi.spyOn(axios, 'get').mockResolvedValue({
      data: { data: { csrf_token: 'fresh-token' } },
    } as never)
    const adapter = vi.fn()
      .mockImplementationOnce(async (config) => Promise.reject({
        config,
        response: { status: 403, data: { code: 'CSRF_TOKEN_INVALID' } },
      }))
      .mockImplementationOnce(async (config) => ({
        config,
        data: { code: 'OK', data: { saved: true } },
        status: 200,
        statusText: 'OK',
        headers: {},
      }))
    ;(service as AxiosInstance).defaults.adapter = adapter

    await expect(service.post('/reservations', {})).resolves.toEqual({ saved: true })
    expect(adapter).toHaveBeenCalledTimes(2)
    expect(adapter.mock.calls[1][0].headers.get('X-CSRF-Token')).toBe('fresh-token')
    expect(localStorage.getItem('lab-auth-csrf-token')).toBe('fresh-token')
  })

  it('also retries writes rejected by the server session CSRF binding', async () => {
    localStorage.setItem('lab-auth-csrf-token', 'stale-session-token')
    vi.spyOn(axios, 'get').mockResolvedValue({
      data: { data: { csrf_token: 'rebound-session-token' } },
    } as never)
    const adapter = vi.fn()
      .mockImplementationOnce(async (config) => Promise.reject({
        config,
        response: { status: 403, data: { code: 'CSRF_SESSION_MISMATCH' } },
      }))
      .mockImplementationOnce(async (config) => ({
        config,
        data: { code: 'OK', data: { saved: true } },
        status: 200,
        statusText: 'OK',
        headers: {},
      }))
    ;(service as AxiosInstance).defaults.adapter = adapter

    await expect(service.post('/reservations', {})).resolves.toEqual({ saved: true })
    expect(adapter).toHaveBeenCalledTimes(2)
    expect(adapter.mock.calls[1][0].headers.get('X-CSRF-Token')).toBe('rebound-session-token')
  })

  it('returns a clear failure when the CSRF token cannot be refreshed after a mismatch', async () => {
    localStorage.setItem('lab-auth-csrf-token', 'stale-token')
    vi.spyOn(axios, 'get').mockRejectedValue(new Error('CSRF endpoint unavailable'))
    const adapter = vi.fn(async (config) => Promise.reject({
      config,
      response: { status: 403, data: { code: 'CSRF_TOKEN_INVALID' } },
    }))
    ;(service as AxiosInstance).defaults.adapter = adapter

    await expect(service.post('/reservations', {})).rejects.toThrow(
      '安全令牌已失效，请刷新页面后重试',
    )
    expect(adapter).toHaveBeenCalledOnce()
  })

  it('retries an expired-session request after a successful cross-tab refresh', async () => {
    userStore.refresh.mockResolvedValue(undefined)
    const adapter = vi.fn()
      .mockImplementationOnce(async (config) => Promise.reject({
        config,
        response: { status: 401, data: { code: 'TOKEN_INVALID' } },
      }))
      .mockImplementationOnce(async (config) => ({
        config,
        data: { code: 'OK', data: { id: 9 } },
        status: 200,
        statusText: 'OK',
        headers: {},
      }))
    ;(service as AxiosInstance).defaults.adapter = adapter

    await expect(service.get('/devices/9')).resolves.toEqual({ id: 9 })
    expect(userStore.refresh).toHaveBeenCalledOnce()
    expect(adapter).toHaveBeenCalledTimes(2)
  })

  it('shares one in-flight session refresh across concurrent unauthorized requests', async () => {
    let releaseRefresh!: () => void
    userStore.refresh.mockImplementation(() => new Promise<void>((resolve) => {
      releaseRefresh = resolve
    }))
    let unauthorizedResponses = 0
    const adapter = vi.fn(async (config) => {
      unauthorizedResponses += 1
      if (unauthorizedResponses <= 2) {
        return Promise.reject({
          config,
          response: { status: 401, data: { code: 'TOKEN_INVALID' } },
        })
      }
      return {
        config,
        data: { code: 'OK', data: { authorized: true } },
        status: 200,
        statusText: 'OK',
        headers: {},
      }
    })
    ;(service as AxiosInstance).defaults.adapter = adapter

    const first = service.get('/devices/11')
    const second = service.get('/devices/12')
    await new Promise((resolve) => setTimeout(resolve, 0))
    expect(userStore.refresh).toHaveBeenCalledOnce()
    releaseRefresh()

    await expect(Promise.all([first, second])).resolves.toEqual([
      { authorized: true },
      { authorized: true },
    ])
    expect(adapter).toHaveBeenCalledTimes(4)
  })

  it('reuses a refresh already completed by another tab instead of rotating twice', async () => {
    localStorage.setItem('lab-auth-refreshed-at', String(Date.now() + 60_000))
    const adapter = vi.fn()
      .mockImplementationOnce(async (config) => Promise.reject({
        config,
        response: { status: 401, data: { code: 'TOKEN_INVALID' } },
      }))
      .mockImplementationOnce(async (config) => ({
        config,
        data: { code: 'OK', data: { id: 10 } },
        status: 200,
        statusText: 'OK',
        headers: {},
      }))
    ;(service as AxiosInstance).defaults.adapter = adapter

    await expect(service.get('/devices/10')).resolves.toEqual({ id: 10 })
    expect(userStore.refresh).not.toHaveBeenCalled()
    expect(adapter).toHaveBeenCalledTimes(2)
  })

  it('retries streaming writes with the current CSRF token after session refresh', async () => {
    userStore.refresh.mockResolvedValue(undefined)
    localStorage.setItem('lab-auth-csrf-token', 'stream-session-token')
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response('', { status: 401 }))
      .mockImplementationOnce(async (_input, init) => {
        expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe('stream-session-token')
        return new Response('ok', { status: 200 })
      })
    vi.stubGlobal('fetch', fetchMock)

    const response = await fetchWithSession('/api/v2/exports/stream', { method: 'POST', body: '{}' })

    expect(response.status).toBe(200)
    expect(userStore.refresh).toHaveBeenCalledOnce()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('uses the cross-tab refresh lock and safely returns non-JSON 403 responses', async () => {
    userStore.refresh.mockResolvedValue(undefined)
    const lockRequest = vi.fn(async (_name: string, callback: () => Promise<void>) => callback())
    vi.stubGlobal('navigator', { locks: { request: lockRequest } })
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response('', { status: 401 }))
      .mockResolvedValueOnce(new Response('still forbidden', { status: 403 }))
    vi.stubGlobal('fetch', fetchMock)

    const response = await fetchWithSession('/api/v2/devices')

    expect(response.status).toBe(403)
    expect(lockRequest).toHaveBeenCalledWith('labflow-auth-refresh', expect.any(Function))
    expect(userStore.refresh).toHaveBeenCalledOnce()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('retries streaming writes after a CSRF mismatch', async () => {
    vi.spyOn(axios, 'get').mockResolvedValue({
      data: { data: { csrf_token: 'fresh-stream-token' } },
    } as never)
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ code: 'CSRF_TOKEN_INVALID' }), {
        status: 403,
        headers: { 'Content-Type': 'application/json' },
      }))
      .mockImplementationOnce(async (_input, init) => {
        expect(new Headers(init?.headers).get('X-CSRF-Token')).toBe('fresh-stream-token')
        return new Response('ok', { status: 200 })
      })
    vi.stubGlobal('fetch', fetchMock)

    const response = await fetchWithSession('/api/v2/ai/runs/stream', {
      method: 'POST',
      body: '{}',
    })

    expect(response.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('retries a GET after a CSRF response without attaching a write token', async () => {
    vi.spyOn(axios, 'get').mockResolvedValue({
      data: { data: { csrf_token: 'fresh-get-token' } },
    } as never)
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ code: 'CSRF_SESSION_MISMATCH' }), {
        status: 403,
        headers: { 'Content-Type': 'application/json' },
      }))
      .mockImplementationOnce(async (_input, init) => {
        expect(new Headers(init?.headers).has('X-CSRF-Token')).toBe(false)
        return new Response('ok', { status: 200 })
      })
    vi.stubGlobal('fetch', fetchMock)

    const response = await fetchWithSession('/api/v2/devices')

    expect(response.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('expires the session when the retried stream request remains unauthorized', async () => {
    userStore.refresh.mockResolvedValue(undefined)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 401 })))

    const response = await fetchWithSession('/api/v2/exports/stream')

    expect(response.status).toBe(401)
    expect(userStore.clearProfile).toHaveBeenCalledOnce()
    expect(mockedRouter.push).toHaveBeenCalledOnce()
  })

  it('can refresh without an original send timestamp when called from an adapter boundary', async () => {
    userStore.refresh.mockResolvedValue(undefined)
    const adapter = vi.fn(async (config) => ({
      config,
      data: { code: 'OK', data: { recovered: true } },
      status: 200,
      statusText: 'OK',
      headers: {},
    }))
    ;(service as AxiosInstance).defaults.adapter = adapter
    const { rejected } = responseCallbacks()
    const config = { url: '/devices', method: 'get', headers: {}, __sentAt: undefined }

    await expect(rejected({ config, response: { status: 401, data: { code: 'TOKEN_INVALID' } } }))
      .resolves.toEqual({ recovered: true })
    expect(userStore.refresh).toHaveBeenCalledOnce()
  })

  it('loads safely in a server environment without a window global', async () => {
    vi.stubGlobal('window', undefined)
    vi.resetModules()

    const isolated = await import('../request')
    expect(isolated.default.defaults.baseURL).toBe('/api/v2')
  })
})
