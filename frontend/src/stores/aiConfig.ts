import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getAiCredential, saveAiCredential, deleteAiCredential } from '@/api/aiCredential'
import type { AiCredentialVO, AiCredentialSaveDTO } from '@/types/aiConfig'

/**
 * AI 凭证配置 store — 个人中心「AI 助手配置」tab 用。
 * 不持久化:凭证随登录态走,每次进设置页 load()。
 */
export const useAiConfigStore = defineStore('aiConfig', () => {
  const credential = ref<AiCredentialVO | null>(null)
  const loading = ref(false)
  const saving = ref(false)

  async function load() {
    loading.value = true
    try {
      credential.value = await getAiCredential()
    } finally {
      loading.value = false
    }
  }

  async function save(dto: AiCredentialSaveDTO) {
    saving.value = true
    try {
      credential.value = await saveAiCredential(dto)
    } finally {
      saving.value = false
    }
  }

  async function remove() {
    await deleteAiCredential()
    credential.value = null
  }

  return { credential, loading, saving, load, save, remove }
})
