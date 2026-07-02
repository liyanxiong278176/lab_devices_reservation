import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as authApi from '@/api/auth'

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
      realName.value = info.realName
      roles.value = info.roles || []
      permissions.value = info.permissions || []
    }

    async function login(payload: { username: string; password: string }) {
      const data = await authApi.login(payload)
      accessToken.value = data.accessToken
      refreshToken.value = data.refreshToken
      // LoginVO.userInfo carries { id, username, realName, roles, permissions }
      applyUserInfo(data.userInfo)
    }

    async function refresh() {
      const d = await authApi.refresh(refreshToken.value)
      accessToken.value = d.accessToken
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

    const hasPerm = (code: string) => permissions.value.includes(code)
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
      hasPerm,
      hasRole,
    }
  },
  { persist: { key: 'lab-user', pick: ['accessToken', 'refreshToken'] } },
)
