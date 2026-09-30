import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import router from '@/router'

const API_BASE = '/api/v2'
const CSRF_HEADER = 'X-CSRF-Token'
const LAST_REFRESH_KEY = 'lab-auth-refreshed-at'
const CSRF_TOKEN_KEY = 'lab-auth-csrf-token'
const service: AxiosInstance = axios.create({
  baseURL: API_BASE,
  timeout: 15000,
  withCredentials: true,
})

let csrfToken = ''
let csrfPending: Promise<string> | null = null

if (typeof window !== 'undefined') {
  window.addEventListener('storage', (event) => {
    if (event.key === CSRF_TOKEN_KEY) csrfToken = event.newValue || ''
  })
}

function expireBrowserSession() {
  useUserStore().clearProfile()
  if (router.currentRoute.value.path !== '/login' && router.currentRoute.value.path !== '/register') {
    void router.push({ path: '/login', query: { redirect: router.currentRoute.value.fullPath } })
  }
}

type RetryableRequestConfig = InternalAxiosRequestConfig & {
  __retried?: boolean
  __csrfRetried?: boolean
  __sentAt?: number
}

function pathOf(url?: string) {
  return (url || '').split('?')[0]
}

function isAuthEndpoint(url?: string) {
  const path = pathOf(url)
  return ['/auth/login', '/auth/register', '/auth/refresh', '/auth/logout'].some((suffix) =>
    path.endsWith(suffix),
  )
}

function isWriteMethod(method?: string) {
  return !['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes((method || 'GET').toUpperCase())
}

function readSharedCsrfToken() {
  try {
    const sharedToken = localStorage.getItem(CSRF_TOKEN_KEY)
    if (sharedToken) csrfToken = sharedToken
    return sharedToken || ''
  } catch {
    return csrfToken
  }
}

function storeSharedCsrfToken(token: string) {
  csrfToken = token
  try {
    localStorage.setItem(CSRF_TOKEN_KEY, token)
  } catch {
    // The active tab can continue with its in-memory token.
  }
}

async function requestCsrfToken() {
  const response = await axios.get(`${API_BASE}/auth/csrf`, {
    withCredentials: true,
    timeout: 10000,
  })
  const token = response.data?.data?.csrf_token
  if (typeof token !== 'string' || !token) throw new Error('无法初始化安全令牌，请刷新页面')
  storeSharedCsrfToken(token)
  return token
}

async function ensureCsrfToken(forceRefresh = false) {
  if (!forceRefresh) {
    const sharedToken = readSharedCsrfToken()
    if (sharedToken) return sharedToken
    if (csrfToken) return csrfToken
  }
  if (!csrfPending) {
    const locks = (navigator as Navigator & {
      locks?: { request: (name: string, callback: () => Promise<string>) => Promise<string> }
    }).locks
    const loadToken = async () => {
      const sharedToken = readSharedCsrfToken()
      if (sharedToken && !forceRefresh) return sharedToken
      return requestCsrfToken()
    }
    csrfPending = (locks
      ? locks.request('labflow-csrf-token', loadToken)
      : loadToken())
      .finally(() => {
        csrfPending = null
      })
  }
  return csrfPending
}

function captureSessionCsrf(body: any) {
  const next = body?.data?.csrf_token
  if (typeof next === 'string' && next) {
    storeSharedCsrfToken(next)
    try {
      localStorage.setItem(LAST_REFRESH_KEY, String(Date.now()))
    } catch {
      // Storage may be unavailable in private browsing; the current tab remains usable.
    }
  }
}

export async function csrfHeaders(): Promise<Record<string, string>> {
  return { [CSRF_HEADER]: await ensureCsrfToken() }
}

service.interceptors.request.use(async (rawConfig: InternalAxiosRequestConfig) => {
  const config = rawConfig as RetryableRequestConfig
  config.withCredentials = true
  config.__sentAt ??= Date.now()
  if (isWriteMethod(config.method)) {
    config.headers.set(CSRF_HEADER, await ensureCsrfToken())
  }
  return config
})

function showRequestError(err: any) {
  const path = pathOf(err.config?.url)
  if (
    err.response?.status === 401 &&
    (path.endsWith('/auth/me') || path.endsWith('/auth/refresh'))
  ) return Promise.reject(err)
  const responseBody = err.response?.data as
    | { message?: string; msg?: string }
    | undefined
  ElMessage.error(responseBody?.message || responseBody?.msg || err.message || '网络错误')
  return Promise.reject(err)
}

function isCsrfFailure(err: any) {
  const code = err.response?.data?.code
  return code === 'CSRF_TOKEN_INVALID' || code === 'CSRF_SESSION_MISMATCH'
}

async function isCsrfResponse(response: Response) {
  if (response.status !== 403) return false
  try {
    const body = await response.clone().json()
    return body?.code === 'CSRF_TOKEN_INVALID' || body?.code === 'CSRF_SESSION_MISMATCH'
  } catch {
    return false
  }
}

async function retryWithFreshCsrf(config: RetryableRequestConfig) {
  try {
    await ensureCsrfToken(true)
  } catch {
    return Promise.reject(new Error('安全令牌已失效，请刷新页面后重试'))
  }
  config.headers.set(CSRF_HEADER, csrfToken)
  return service(config)
}

async function refreshAcrossTabs(sentAt: number) {
  const user = useUserStore()
  const perform = async () => {
    try {
      const refreshedAt = Number(localStorage.getItem(LAST_REFRESH_KEY) || 0)
      if (refreshedAt > sentAt) return
    } catch {
      // Continue with a refresh when local storage is disabled.
    }
    await user.refresh()
    try {
      localStorage.setItem(LAST_REFRESH_KEY, String(Date.now()))
    } catch {
      // The cookie session does not depend on browser storage.
    }
  }

  const locks = (navigator as Navigator & {
    locks?: { request: (name: string, callback: () => Promise<void>) => Promise<void> }
  }).locks
  if (locks) {
    await locks.request('labflow-auth-refresh', perform)
  } else {
    await perform()
  }
}

let refreshPending: Promise<void> | null = null

async function ensureFreshSession(sentAt: number) {
  if (!refreshPending) {
    refreshPending = refreshAcrossTabs(sentAt).finally(() => {
      refreshPending = null
    })
  }
  await refreshPending
}

export async function fetchWithSession(input: RequestInfo | URL, init: RequestInit = {}) {
  const sentAt = Date.now()
  const headers = new Headers(init.headers)
  if (isWriteMethod(init.method)) headers.set(CSRF_HEADER, await ensureCsrfToken())
  const requestInit: RequestInit = { ...init, credentials: 'include', headers }
  let response = await fetch(input, requestInit)
  if (response.status === 401) {
    try {
      await ensureFreshSession(sentAt)
    } catch {
      expireBrowserSession()
      return response
    }
    if (isWriteMethod(init.method)) headers.set(CSRF_HEADER, await ensureCsrfToken())
    response = await fetch(input, requestInit)
    if (response.status === 401) expireBrowserSession()
  }
  if (await isCsrfResponse(response)) {
    await ensureCsrfToken(true)
    if (isWriteMethod(init.method)) headers.set(CSRF_HEADER, csrfToken)
    response = await fetch(input, requestInit)
  }
  return response
}

service.interceptors.response.use(
  (res) => {
    const body = res.data
    if (pathOf(res.config.url).endsWith('/auth/logout')) {
      csrfToken = ''
      try {
        localStorage.removeItem(CSRF_TOKEN_KEY)
      } catch {
        // Logout still clears the in-memory token if storage is unavailable.
      }
    }
    captureSessionCsrf(body)
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 'OK') return body.data
      ElMessage.error(body.message || '请求失败')
      return Promise.reject(body)
    }
    return body
  },
  async (err) => {
    const config = err.config as RetryableRequestConfig | undefined
    const path = pathOf(config?.url)

    // A missing access cookie is the expected anonymous state on login and
    // registration pages; refreshing without a refresh cookie only creates a
    // misleading CSRF error. Expired/invalid access sessions still refresh.
    if (
      err.response?.status === 401 &&
      path.endsWith('/auth/me') &&
      err.response?.data?.code === 'AUTH_REQUIRED'
    ) {
      return showRequestError(err)
    }

    if (
      err.response?.status === 403 &&
      isCsrfFailure(err) &&
      config &&
      isWriteMethod(config.method) &&
      !config.__csrfRetried &&
      !isAuthEndpoint(path)
    ) {
      config.__csrfRetried = true
      return retryWithFreshCsrf(config)
    }

    if (err.response?.status !== 401 || !config || config.__retried || isAuthEndpoint(path)) {
      return showRequestError(err)
    }

    config.__retried = true
    try {
      await ensureFreshSession(config.__sentAt ?? Date.now())
      return service(config)
    } catch {
      expireBrowserSession()
      return Promise.reject(err)
    }
  },
)

export default service
