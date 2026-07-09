<script setup lang="ts">
import { CircleCheck } from '@element-plus/icons-vue'

defineProps<{ code?: string; msg?: string; data?: unknown }>()
</script>

<template>
  <div class="ai-result-card">
    <el-icon class="ai-result-icon"><CircleCheck /></el-icon>
    <div class="ai-result-body">
      <div v-if="msg" class="ai-result-msg">{{ msg }}</div>
      <pre v-if="data" class="ai-result-data">{{ JSON.stringify(data, null, 2) }}</pre>
    </div>
  </div>
</template>

<style scoped lang="scss">
.ai-result-card {
  display: flex;
  gap: 10px;
  margin: 6px 12px;
  padding: 12px;
  border: 1px solid var(--el-color-success, #10b981);
  border-radius: 10px;
  background: rgba(16, 185, 129, 0.08);
  color: var(--el-color-success, #10b981);
}
.ai-result-icon {
  font-size: 22px;
  flex: 0 0 22px;
}
.ai-result-body {
  flex: 1;
  min-width: 0;
}
.ai-result-msg {
  font-size: 14px;
  color: var(--fg-primary, #e5e7eb);
}
.ai-result-data {
  margin-top: 6px;
  padding: 8px;
  background: rgba(0, 0, 0, 0.3);
  border-radius: 6px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: var(--fg-primary, #e5e7eb);
  overflow-x: auto;
  max-height: 240px;
  overflow-y: auto;
}
</style>
