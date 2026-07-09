<script setup lang="ts">
import { Loading, CircleCheck, CircleClose, VideoPlay } from '@element-plus/icons-vue'
import type { StepUpdateItem } from '@/types/ai'

defineProps<{ steps: StepUpdateItem[] }>()

function iconOf(status: StepUpdateItem['status']) {
  switch (status) {
    case 'started':
      return Loading
    case 'completed':
      return CircleCheck
    case 'failed':
      return CircleClose
    case 'cancelled':
      return VideoPlay
    default:
      return Loading
  }
}

function classOf(status: StepUpdateItem['status']) {
  return `ai-step ai-step--${status}`
}
</script>

<template>
  <div class="ai-step-timeline">
    <div v-for="(s, i) in steps" :key="i" :class="classOf(s.status)">
      <el-icon class="ai-step-icon">
        <component :is="iconOf(s.status)" />
      </el-icon>
      <div class="ai-step-text">{{ s.text }}</div>
      <span v-if="s.durationMs" class="ai-step-dur">{{ s.durationMs }}ms</span>
    </div>
  </div>
</template>

<style scoped lang="scss">
.ai-step-timeline {
  margin: 8px 12px;
  padding: 10px;
  background: var(--bg-elev-1, #111827);
  border: 1px solid var(--border-subtle, #1f2937);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ai-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--fg-secondary, #d1d5db);

  &--started {
    color: var(--accent, #6366f1);
  }
  &--completed {
    color: var(--el-color-success, #10b981);
  }
  &--failed {
    color: var(--el-color-danger, #ef4444);
  }
  &--cancelled {
    color: var(--fg-muted, #9ca3af);
  }
}
.ai-step-icon {
  flex: 0 0 16px;
  font-size: 14px;
}
.ai-step-text {
  flex: 1;
}
.ai-step-dur {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: var(--fg-muted, #9ca3af);
}
</style>
