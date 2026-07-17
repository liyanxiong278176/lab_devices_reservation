import type { NavigationGuardWithThis } from 'vue-router'
import { useUserStore } from '@/stores/user'

export const guard: NavigationGuardWithThis<undefined> = async (to) => {
  const u = useUserStore()
  if (to.meta.public) return true
  if (!u.accessToken) return { path: '/login', query: { redirect: to.fullPath } }
  // 刷新场景:token 已水合,但 roles/permissions 不持久化、要等 fetchMe 回来才有。
  // 而 main.ts 的 app.use(router) 在 fetchMe 之前就触发初始导航,守卫先跑到这里时
  // roles 还是 [],直接判 meta.roles 会误判无权 → return false → 初始导航被取消 →
  // 首次加载无上一路由、router-view 无可渲染 → 页面空白
  // (待审批/报修处理/设备管理/用户管理 这些带 meta.roles 的路由)。
  // 故 token 在但 roles 空 时先补拉 profile,再判角色。
  if (u.roles.length === 0) {
    try {
      await u.fetchMe()
    } catch {
      // 拉取失败(含 401 token 失效):跳登录重新认证(401 的 refresh/登出由 axios 拦截器兜底)
      return { path: '/login', query: { redirect: to.fullPath } }
    }
  }
  const need = to.meta.roles as string[] | undefined
  if (need && need.length && !need.some((r) => u.roles.includes(r))) return false
  return true
}
