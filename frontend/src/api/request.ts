import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import router from '@/router'

const service: AxiosInstance = axios.create({ baseURL: '/api/v2', timeout: 15000 })

service.interceptors.request.use((cfg: InternalAxiosRequestConfig) => {
  const u = useUserStore()
  if (u.accessToken) cfg.headers.set('Authorization', `Bearer ${u.accessToken}`)
  return cfg
})

type RetryableRequestConfig = InternalAxiosRequestConfig & { __retried?: boolean }

function isAuthEndpoint(url?: string) {
  const path = (url || '').split('?')[0]
  return path.endsWith('/auth/login') || path.endsWith('/auth/refresh')
}

function showRequestError(err: any) {
  const responseBody = err.response?.data as
    | { message?: string; msg?: string }
    | undefined
  ElMessage.error(responseBody?.message || responseBody?.msg || err.message || '网络错误')
  return Promise.reject(err)
}

// 并发安全的 refresh 协调:第一次 401 触发 refresh,其后所有 401 在同一 promise 上等待,
// 避免 N 个并行请求触发 N 次 refresh /auth 同时打爆后端 token 表。
// 完成后清空 promise,下一批 401 重新触发。
let refreshPending: Promise<unknown> | null = null

service.interceptors.response.use(
  (res) => {
    const body = res.data
    // Unwrap the v2 envelope: { code: 'OK', message, data }.
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 'OK') return body.data
      ElMessage.error(body.message || '请求失败')
      return Promise.reject(body)
    }
    return body
  },
  async (err) => {
    const u = useUserStore()
    const config = err.config as RetryableRequestConfig | undefined

    // refresh/login 本身失败时不能再次走 refresh。否则 refresh 请求会等待
    // 它自己持有的 refreshPending，最终表现为启动阶段页面一直空白。
    // 登录接口 401 也只应把错误交给登录页，不应拿旧会话去刷新。
    if (err.response?.status !== 401 || !config || config.__retried || isAuthEndpoint(config.url)) {
      return showRequestError(err)
    }

    // 没有 refresh token 时直接结束旧会话，避免向 /auth/refresh 发送无效请求。
    if (!u.refreshToken) {
      u.logout()
      void router.push('/login')
      return Promise.reject(err)
    }

    config.__retried = true
    try {
      if (!refreshPending) {
        refreshPending = u.refresh().finally(() => {
          refreshPending = null
        })
      }
      await refreshPending
      // refresh 成功:用新 accessToken 重放当前请求(请求拦截器会读到新 token)
      return service(config)
    } catch {
      // refresh 失败:所有并发 401 都会走到这里,统一 logout + 跳登录
      u.logout()
      void router.push('/login')
      return Promise.reject(err)
    }
  },
)

export default service
