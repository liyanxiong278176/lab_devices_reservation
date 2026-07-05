import axios, { type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import router from '@/router'

const service: AxiosInstance = axios.create({ baseURL: '/api', timeout: 15000 })

service.interceptors.request.use((cfg: InternalAxiosRequestConfig) => {
  const u = useUserStore()
  if (u.accessToken) cfg.headers.set('Authorization', `Bearer ${u.accessToken}`)
  return cfg
})

// 并发安全的 refresh 协调:第一次 401 触发 refresh,其后所有 401 在同一 promise 上等待,
// 避免 N 个并行请求触发 N 次 refresh /auth 同时打爆后端 token 表。
// 完成后清空 promise,下一批 401 重新触发。
let refreshPending: Promise<unknown> | null = null

service.interceptors.response.use(
  (res) => {
    const body = res.data
    // Unwrap the unified Result envelope: { code, msg, data }.
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 200) return body.data
      ElMessage.error(body.msg || '请求失败')
      return Promise.reject(body)
    }
    return body
  },
  async (err) => {
    const u = useUserStore()
    // 非 401 或当前请求已经重试过一次:不再二次刷新,直接抛出
    if (err.response?.status !== 401 || err.config.__retried) {
      ElMessage.error(err.response?.data?.msg || err.message || '网络错误')
      return Promise.reject(err)
    }
    err.config.__retried = true
    try {
      if (!refreshPending) {
        refreshPending = u.refresh().finally(() => {
          refreshPending = null
        })
      }
      await refreshPending
      // refresh 成功:用新 accessToken 重放当前请求(请求拦截器会读到新 token)
      return service(err.config)
    } catch {
      // refresh 失败:所有并发 401 都会走到这里,统一 logout + 跳登录
      u.logout()
      router.push('/login')
      return Promise.reject(err)
    }
  },
)

export default service
