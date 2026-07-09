<script setup lang="ts">
import { Warning, CircleCheck, CircleClose } from '@element-plus/icons-vue'
import type { ConfirmationState } from '@/types/ai'

const props = defineProps<{
  confirmation: ConfirmationState
}>()

const emit = defineEmits<{
  confirm: [actionId: number]
  cancel: [actionId: number]
}>()

function statusLabel(): string {
  switch (props.confirmation.status) {
    case 'pending':
      return '等待确认'
    case 'confirmed':
      return '已确认 — 执行中'
    case 'cancelled':
      return '已取消'
    case 'expired':
      return '已超时'
    case 'executed':
      return '执行成功'
    case 'error':
      return '执行失败'
    default:
      return props.confirmation.status
  }
}

function isPending(): boolean {
  return props.confirmation.status === 'pending'
}
</script>

<template>
  <div class="ai-confirm-card">
    <div class="ai-confirm-header">
      <el-icon class="ai-confirm-icon"><Warning /></el-icon>
      <div class="ai-confirm-title">需要您确认: {{ confirmation.toolName }}</div>
    </div>
    <div class="ai-confirm-reason">{{ confirmation.reason }}</div>
    <div v-if="confirmation.riskSummary" class="ai-confirm-row">
      <span class="ai-confirm-label">风险</span>
      <span>{{ confirmation.riskSummary }}</span>
    </div>
    <div v-if="confirmation.estimatedImpact" class="ai-confirm-row">
      <span class="ai-confirm-label">影响</span>
      <span>{{ confirmation.estimatedImpact }}</span>
    </div>
    <div class="ai-confirm-status">状态: {{ statusLabel() }}</div>
    <div v-if="isPending()" class="ai-confirm-actions">
      <el-button type="danger" plain :icon="CircleClose" @click="emit('cancel', confirmation.actionId)">
        拒绝
      </el-button>
      <el-button type="success" :icon="CircleCheck" @click="emit('confirm', confirmation.actionId)">
        确认执行
      </el-button>
    </div>
  </div>
</template>

<style scoped lang="scss">
.ai-confirm-card {
  margin: 8px 12px;
  border: 1px solid var(--el-color-warning, #f59e0b);
  border-radius: 10px;
  background: rgba(245, 158, 11, 0.08);
  padding: 14px;
}
.ai-confirm-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.ai-confirm-icon {
  font-size: 20px;
  color: var(--el-color-warning, #f59e0b);
}
.ai-confirm-title {
  font-weight: 600;
  font-size: 14px;
  color: var(--fg-primary, #e5e7eb);
}
.ai-confirm-reason {
  font-size: 13px;
  color: var(--fg-primary, #e5e7eb);
  margin-bottom: 10px;
}
.ai-confirm-row {
  display: flex;
  gap: 8px;
  font-size: 12px;
  color: var(--fg-secondary, #d1d5db);
  margin-top: 4px;
}
.ai-confirm-label {
  flex: 0 0 36px;
  color: var(--fg-muted, #9ca3af);
}
.ai-confirm-status {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid rgba(245, 158, 11, 0.25);
  font-size: 12px;
  color: var(--fg-muted, #9ca3af);
}
.ai-confirm-actions {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
