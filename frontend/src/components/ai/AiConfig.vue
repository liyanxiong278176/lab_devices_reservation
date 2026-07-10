<script setup lang="ts">
import { onMounted, reactive, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useAiConfigStore } from '@/stores/aiConfig'
import { PROVIDER_PRESETS, type AiProvider } from '@/types/aiConfig'

const emit = defineEmits<{ (e: 'saved'): void }>()
const store = useAiConfigStore()

const form = reactive({
  provider: 'deepseek' as AiProvider,
  baseUrl: PROVIDER_PRESETS.deepseek.baseUrl,
  apiKey: '',
  model: PROVIDER_PRESETS.deepseek.model,
  temperature: 0.3,
})

function onProviderChange(p: AiProvider) {
  const preset = PROVIDER_PRESETS[p]
  form.baseUrl = preset.baseUrl
  form.model = preset.model
}

function syncFromStore() {
  const c = store.credential
  if (c?.configured) {
    form.provider = (c.provider as AiProvider) || 'custom'
    form.baseUrl = c.baseUrl
    form.model = c.model
    form.temperature = c.temperature ?? 0.3
  }
}

async function onSave() {
  if (!form.apiKey) {
    ElMessage.warning('请填写 API Key')
    return
  }
  try {
    await store.save({ ...form })
    ElMessage.success('已保存(连接测试通过)')
    form.apiKey = '' // 不留明文在表单
    emit('saved')
  } catch {
    // 响应拦截器已弹出后端「连接测试失败:...」
  }
}

async function onRemove() {
  try {
    await store.remove()
    ElMessage.success('已清除配置')
  } catch {
    // 拦截器已提示
  }
}

onMounted(async () => {
  await store.load()
  syncFromStore()
})
// 保存后 store.credential 变化 → 同步回显
watch(() => store.credential, syncFromStore, { deep: true })
</script>

<template>
  <div class="ai-config">
    <p class="ai-config__hint">
      配置你自己的 AI API Key(加密存于本系统,服务器不保存)。chat 走你自己的额度。
    </p>
    <el-form label-width="72px" size="small">
      <el-form-item label="服务商">
        <el-select v-model="form.provider" style="width: 100%" @change="onProviderChange">
          <el-option label="DeepSeek" value="deepseek" />
          <el-option label="OpenAI" value="openai" />
          <el-option label="硅基流动" value="siliconflow" />
          <el-option label="自定义" value="custom" />
        </el-select>
      </el-form-item>
      <el-form-item label="Base URL">
        <el-input v-model="form.baseUrl" placeholder="https://api.deepseek.com" />
      </el-form-item>
      <el-form-item label="API Key">
        <el-input
          v-model="form.apiKey"
          type="password"
          show-password
          :placeholder="store.credential?.configured ? '已配置(重填则覆盖)' : 'sk-...'"
        />
      </el-form-item>
      <el-form-item label="模型">
        <el-input v-model="form.model" placeholder="deepseek-chat" />
      </el-form-item>
      <el-form-item label="温度">
        <el-slider v-model="form.temperature" :min="0" :max="1" :step="0.1" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="store.saving" @click="onSave">保存(含连接测试)</el-button>
        <el-button v-if="store.credential?.configured" @click="onRemove">清除</el-button>
      </el-form-item>
    </el-form>
  </div>
</template>

<style scoped lang="scss">
.ai-config {
  flex: 1;
  overflow-y: auto;
  padding: 14px;
  color: var(--fg-primary, #e5e7eb);

  &__hint {
    font-size: 12px;
    line-height: 1.5;
    color: var(--fg-muted, #9ca3af);
    margin-bottom: 14px;
  }
}
</style>
