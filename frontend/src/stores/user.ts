import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import * as authApi from '@/api/auth'

export const useUserStore = defineStore('user', () => {
  const userId = ref<number | null>(null)
  const username = ref('')
  const realName = ref('')
  const collegeId = ref<number | null>(null)
  const roles = ref<string[]>([])
  const permissions = ref<string[]>([])
  const initialized = ref(false)
  const isAuthenticated = computed(() => userId.value !== null)
  let initialization: Promise<void> | null = null

  function applyUserInfo(info: authApi.UserInfoVO) {
    userId.value = info.id
    username.value = info.username
    realName.value = info.real_name || info.username
    collegeId.value = info.college_id
    roles.value = [...info.roles]
    permissions.value = [...info.permissions]
  }

  function clearProfile() {
    userId.value = null
    username.value = ''
    realName.value = ''
    collegeId.value = null
    roles.value = []
    permissions.value = []
  }

  async function fetchMe() {
    applyUserInfo(await authApi.getMe())
  }

  async function initialize() {
    if (!initialization) {
      initialization = (async () => {
        try {
          await fetchMe()
        } catch {
          clearProfile()
        } finally {
          initialized.value = true
        }
      })().finally(() => {
        initialization = null
      })
    }
    await initialization
  }

  async function login(payload: authApi.LoginPayload) {
    await authApi.login(payload)
    await fetchMe()
    initialized.value = true
  }

  async function register(payload: authApi.RegisterPayload) {
    await authApi.register(payload)
    await fetchMe()
    initialized.value = true
  }

  async function refresh() {
    await authApi.refresh()
  }

  async function logout() {
    try {
      if (isAuthenticated.value) await authApi.logout()
    } finally {
      clearProfile()
      initialized.value = true
    }
  }

  const hasPerm = (code: string) => permissions.value.includes(code)
  const hasAnyPerm = (codes: string[]) => codes.some(hasPerm)
  const hasRole = (code: string) => roles.value.includes(code)

  return {
    userId,
    username,
    realName,
    collegeId,
    roles,
    permissions,
    initialized,
    isAuthenticated,
    login,
    register,
    refresh,
    fetchMe,
    initialize,
    logout,
    clearProfile,
    hasPerm,
    hasAnyPerm,
    hasRole,
  }
})
