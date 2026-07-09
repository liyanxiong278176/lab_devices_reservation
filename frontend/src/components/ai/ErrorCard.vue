<script setup lang="ts">
import { CircleClose } from '@element-plus/icons-vue'

defineProps<{ code: string; msg: string }>()
</script>

<template>
  <div class="ai-err-card">
    <el-icon class="ai-err-icon"><CircleClose /></el-icon>
    <div class="ai-err-body">
      <div class="ai-err-code">{{ code }}</div>
      <div class="ai-err-msg">{{ msg }}</div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.ai-err-card {
  display: flex;
  gap: 10px;
  margin: 6px 12px;
  padding: 12px;
  border: 1px solid var(--el-color-danger, #ef4444);
  border-radius: 10px;
  background: rgba(239, 68, 68, 0.08);
  color: var(--el-color-danger, #ef4444);
}
.ai-err-icon {
  font-size: 22px;
  flex: 0 0 22px;
}
.ai-err-body {
  flex: 1;
  min-width: 0;
}
.ai-err-code {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.5px;
}
.ai-err-msg {
  margin-top: 4px;
  font-size: 14px;
  color: var(--fg-primary, #e5e7eb);
}
</style>
