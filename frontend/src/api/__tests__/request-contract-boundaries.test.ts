import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const browserRouter = vi.hoisted(() => ({
  push: vi.fn(),
  currentRoute: { value: { path: '/devices', fullPath: '/devices?lab=4' } },
}))
const user = vi.hoisted(() => ({ refresh: vi.fn(), clearProfile: vi.fn() }))
const message = vi.hoisted(() => ({ error: vi.fn() }))
vi.mock('@/router', () => ({ default: browserRouter }))
vi.mock('@/stores/user', () => ({ useUserStore: () => user }))
vi.mock('element-plus', () => ({ ElMessage: message }))

import service, { csrfHeaders, fetchWithSession } from '../request'

let values: Map<string, string>
let storage: Storage

function makeStorage() {
  return {
    getItem: vi.fn((key: string) => values.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => { values.set(key, String(value)) }),
    removeItem: vi.fn((key: string) => { values.delete(key) }),
    clear: vi.fn(() => values.clear()),
  } as unknown as Storage
}

function ok(config: InternalAxiosRequestConfig, data: unknown) {
  return { config, data, status: 200, statusText: 'OK', headers: {} }
}

function fail(config: InternalAxiosRequestConfig, status: number, data: unknown) {
  return Promise.reject({ config, response: { status, data }, message: 'adapter failure' })
}

beforeEach(() => {
  vi.clearAllMocks()
  values = new Map()
  storage = makeStorage()
  vi.stubGlobal('localStorage', storage)
  Object.defineProperty(window, 'localStorage', { configurable: true, value: storage })
  Object.defineProperty(navigator, 'locks', { configurable: true, value: undefined })
  window.dispatchEvent(new StorageEvent('storage', { key: 'lab-auth-csrf-token', newValue: null }))
  user.refresh.mockResolvedValue(undefined)
  browserRouter.push.mockResolvedValue(undefined)
  ;(service as AxiosInstance).defaults.adapter = async (config) => ok(config, { data: 'default' })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

describe('HTTP client contract boundaries', () => {
  it('unwraps successful envelopes, captures rotated CSRF tokens and clears logout tokens', async () => {
    values.set('lab-auth-csrf-token', 'old-token')
    const adapter = vi.fn(async (config: InternalAxiosRequestConfig) => {
      if (config.url?.endsWith('/auth/refresh')) {
        return ok(config, { code: 'OK', data: { csrf_token: 'rotated-token', authenticated: true } })
      }
      return ok(config, { code: 'OK', data: { logged_out: true } })
    })
    ;(service as AxiosInstance).defaults.adapter = adapter

    await expect(service.get('/auth/refresh')).resolves.toEqual({ csrf_token: 'rotated-token', authenticated: true })
    expect(values.get('lab-auth-csrf-token')).toBe('rotated-token')
    expect(values.has('lab-auth-refreshed-at')).toBe(true)

    await expect(service.post('/auth/logout', {})).resolves.toEqual({ logged_out: true })
    expect(values.has('lab-auth-csrf-token')).toBe(false)
    expect(adapter).toHaveBeenCalledTimes(2)
  })

  it('returns plain response data and rejects failed API envelopes with the supplied message', async () => {
    const adapter = vi.fn()
      .mockImplementationOnce(async (config: InternalAxiosRequestConfig) => ok(config, { records: [1] }))
      .mockImplementationOnce(async (config: InternalAxiosRequestConfig) => ok(config, {
        code: 'BUSINESS_ERROR', message: 'Not allowed',
      }))
    ;(service as AxiosInstance).defaults.adapter = adapter

    await expect(service.get('/devices')).resolves.toEqual({ records: [1] })
    await expect(service.get('/devices')).rejects.toMatchObject({ code: 'BUSINESS_ERROR' })
    expect(message.error).toHaveBeenCalledWith('Not allowed')
  })

  it('sends cookies without adding CSRF to safe fetches and attaches it to writes', async () => {
    values.set('lab-auth-csrf-token', 'shared-token')
    const fetchMock = vi.fn().mockResolvedValue(new Response('ok', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    await fetchWithSession('/api/v2/devices')
    const safeInit = fetchMock.mock.calls[0][1] as RequestInit
    expect(safeInit.credentials).toBe('include')
    expect(new Headers(safeInit.headers).has('X-CSRF-Token')).toBe(false)

    await fetchWithSession('/api/v2/reservations', { method: 'POST', body: '{}' })
    const writeInit = fetchMock.mock.calls[1][1] as RequestInit
    expect(new Headers(writeInit.headers).get('X-CSRF-Token')).toBe('shared-token')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('refreshes an expired session under the browser lock and retries the original request', async () => {
    const lockRequest = vi.fn(async (_name: string, callback: () => Promise<void>) => callback())
    Object.defineProperty(navigator, 'locks', { configurable: true, value: { request: lockRequest } })
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response('', { status: 401 }))
      .mockResolvedValueOnce(new Response('ok', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const response = await fetchWithSession('/api/v2/reports')
    expect(response.status).toBe(200)
    expect(user.refresh).toHaveBeenCalledOnce()
    expect(lockRequest).toHaveBeenCalledWith('labflow-auth-refresh', expect.any(Function))
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(browserRouter.push).not.toHaveBeenCalled()
  })

  it('expires the browser session after a failed refresh or a second unauthorized response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 401 })))
    user.refresh.mockRejectedValueOnce(new Error('expired'))
    const first = await fetchWithSession('/api/v2/private')
    expect(first.status).toBe(401)
    expect(user.clearProfile).toHaveBeenCalledOnce()
    expect(browserRouter.push).toHaveBeenCalledWith({ path: '/login', query: { redirect: '/devices?lab=4' } })

    vi.clearAllMocks()
    user.refresh.mockResolvedValue(undefined)
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 401 })))
    const second = await fetchWithSession('/api/v2/private')
    expect(second.status).toBe(401)
    expect(user.refresh).toHaveBeenCalledOnce()
    expect(user.clearProfile).toHaveBeenCalledOnce()
  })

  it('ignores non-CSRF forbidden bodies, malformed JSON and avoids retrying safe methods', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response('{"code":"DENIED"}', { status: 403 }))
      .mockResolvedValueOnce(new Response('not json', { status: 403 }))
    vi.stubGlobal('fetch', fetchMock)

    expect((await fetchWithSession('/api/v2/devices')).status).toBe(403)
    expect((await fetchWithSession('/api/v2/devices')).status).toBe(403)
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('falls back to memory storage when browser storage is blocked and shares concurrent CSRF acquisition', async () => {
    const deniedStorage = {
      getItem: vi.fn(() => { throw new Error('blocked') }),
      setItem: vi.fn(() => { throw new Error('blocked') }),
      removeItem: vi.fn(() => { throw new Error('blocked') }),
    }
    vi.stubGlobal('localStorage', deniedStorage)
    Object.defineProperty(window, 'localStorage', { configurable: true, value: deniedStorage })
    const getToken = vi.spyOn(axios, 'get').mockResolvedValue({
      data: { data: { csrf_token: 'memory-token' } },
    } as never)
    const [first, second] = await Promise.all([csrfHeaders(), csrfHeaders()])
    expect(first).toEqual({ 'X-CSRF-Token': 'memory-token' })
    expect(second).toEqual(first)
    expect(getToken).toHaveBeenCalledOnce()
    await expect(csrfHeaders()).resolves.toEqual(first)
  })

  it('rejects a missing CSRF bootstrap token with the explicit safety error', async () => {
    vi.spyOn(axios, 'get').mockResolvedValue({ data: { data: {} } } as never)
    await expect(csrfHeaders()).rejects.toThrow('无法初始化安全令牌，请刷新页面')
  })

  it('does not try to refresh authentication endpoints and shows API error fallbacks', async () => {
    values.set('lab-auth-csrf-token', 'token')
    const adapter = vi.fn((config: InternalAxiosRequestConfig) => fail(config, 401, { msg: 'login required' }))
    ;(service as AxiosInstance).defaults.adapter = adapter
    await expect(service.post('/auth/login?from=page', {})).rejects.toMatchObject({ response: { status: 401 } })
    expect(user.refresh).not.toHaveBeenCalled()
    expect(message.error).toHaveBeenCalledWith('login required')

    vi.clearAllMocks()
    ;(service as AxiosInstance).defaults.adapter = async (config) => fail(config, 500, {})
    await expect(service.get('/devices')).rejects.toMatchObject({ response: { status: 500 } })
    expect(message.error).toHaveBeenCalledWith('adapter failure')
  })
})
