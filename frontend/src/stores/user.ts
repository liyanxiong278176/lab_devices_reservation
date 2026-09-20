import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as authApi from '@/api/auth'

// v2 后端以角色做接口鉴权，/auth/me 当前只返回角色，不返回旧版权限表。
// 前端操作按钮需要和后端的实际角色能力保持一致，避免管理员能进入页面却看不到操作按钮。
const ROLE_PERMISSIONS: Record<string, readonly string[]> = {
  SYS_ADMIN: ['device:approve', 'device:manage', 'repair:handle'],
  LAB_ADMIN: ['device:approve', 'device:manage', 'repair:handle'],
}

export const useUserStore = defineStore(
  'user',
  () => {
    const accessToken = ref('')
    const refreshToken = ref('')
    const userId = ref<number | null>(null)
    const username = ref('')
    const realName = ref('')
    const roles = ref<string[]>([])
    const permissions = ref<string[]>([])

  function applyUserInfo(info: authApi.UserInfoVO | undefined) {
    if (!info) return
    userId.value = info.id
    username.value = info.username
    realName.value = info.real_name || info.username
    roles.value = info.roles || []
    permissions.value = []
    }

    async function login(payload: { username: string; password: string }) {
      const data = await authApi.login(payload)
      accessToken.value = data.access_token
      refreshToken.value = data.refresh_token
      await fetchMe()
    }

    async function refresh() {
      const d = await authApi.refresh(refreshToken.value)
      accessToken.value = d.access_token
      refreshToken.value = d.refresh_token
    }

    async function fetchMe() {
      const info = await authApi.getMe()
      applyUserInfo(info)
    }

    function logout() {
      accessToken.value = ''
      refreshToken.value = ''
      userId.value = null
      username.value = ''
      realName.value = ''
      roles.value = []
      permissions.value = []
    }

    /**
     * 只清档案不清 token:供 main.ts boot IIFE 在 fetchMe 失败时调用。
     * 失败闭环:路由 guard 看到 roles=[],立即拒绝进入需要角色的路由——防止
     * 上一次会话 persist 的陈旧角色让 UI 短暂露出越权界面。
     * token 保留,axios 401 拦截器负责后续 refresh / 跳 /login 流程。
     */
    function clearProfile() {
      userId.value = null
      username.value = ''
      realName.value = ''
      roles.value = []
      permissions.value = []
    }

    const hasPerm = (code: string) =>
      permissions.value.includes(code) ||
      roles.value.some((role) => ROLE_PERMISSIONS[role]?.includes(code) ?? false)
    const hasRole = (r: string) => roles.value.includes(r)

    return {
      accessToken,
      refreshToken,
      userId,
      username,
      realName,
      roles,
      permissions,
      login,
      refresh,
      fetchMe,
      logout,
      clearProfile,
      hasPerm,
      hasRole,
    }
  },
  // 只持久化 token;user profile 由 mount 时 fetchMe 单源填充(401 失败时调
  // clearProfile 清空,路由 guard 即拒绝角色路由,防陈旧角色越权)。
  // token 过期由 axios 401 拦截器 → refresh / logout 兜底。
  { persist: { key: 'lab-user', pick: ['accessToken', 'refreshToken'] } },
)
