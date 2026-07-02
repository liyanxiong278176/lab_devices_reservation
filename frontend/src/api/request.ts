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

// Module-level flag to prevent refresh storms when multiple requests hit 401 together.
let refreshing = false

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
    if (err.response?.status === 401 && !err.config.__retried) {
      err.config.__retried = true
      if (!refreshing) {
        refreshing = true
        try {
          await u.refresh()
          refreshing = false
          return service(err.config)
        } catch {
          refreshing = false
          u.logout()
          router.push('/login')
          return Promise.reject(err)
        }
      }
    }
    ElMessage.error(err.response?.data?.msg || err.message || '网络错误')
    return Promise.reject(err)
  },
)

export default service
