<script setup lang="ts">
// StatusDot — 状态脉冲点(深色)
// 设备/工单状态可视化:点 + 可选文字。IN_USE 自动脉冲(伪元素 scale/opacity,GPU 友好)。
// 颜色全走 token(--text-tertiary / --accent / --status-warning / --status-danger)。
// 走 prefers-reduced-motion 时脉冲自动关(本组件内本地守卫,不依赖全局 _motion.scss)。
import { computed } from 'vue'

type Status = 'IDLE' | 'IN_USE' | 'MAINTENANCE' | 'BROKEN'

const props = withDefaults(
  defineProps<{
    status: Status
    label?: boolean
    size?: number
    labelText?: string
  }>(),
  {
    label: false,
    size: 8,
    labelText: undefined,
  },
)

const DEFAULT_LABELS: Record<Status, string> = {
  IDLE: '空闲',
  IN_USE: '使用中',
  MAINTENANCE: '维护中',
  BROKEN: '故障',
}

// IDLE → idle,IN_USE → in-use(kebab 以匹配 CSS modifier 约定)
const statusKebab = computed(() => props.status.toLowerCase().replace(/_/g, '-'))

const displayLabel = computed(() => props.labelText ?? DEFAULT_LABELS[props.status])

const dotStyle = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
}))

// 无文字时给 AT 用户提供状态语义;有文字时由可见文本承担可达名称
const ariaLabel = computed(() => (props.label ? undefined : displayLabel.value))
const role = computed(() => (props.label ? undefined : 'img'))
</script>

<template>
  <span
    class="status-dot"
    :class="`status-dot--${statusKebab}`"
    :data-status="status"
    :role="role"
    :aria-label="ariaLabel"
  >
    <span class="status-dot__dot" :style="dotStyle" />
    <span v-if="label" class="status-dot__label">{{ displayLabel }}</span>
  </span>
</template>

<style scoped lang="scss">
// 通过 CSS 变量 --dot-color 把颜色从父 modifier 桥到子 dot/伪元素,
// 状态色全走 token,无硬编码 hex。
.status-dot {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  line-height: 1;
  vertical-align: middle;
}

.status-dot__dot {
  position: relative;
  display: inline-block;
  border-radius: 50%;
  background: var(--dot-color, var(--text-tertiary));
}

.status-dot__label {
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 500;
}

// ---- 状态色映射(只设 --dot-color,真色由 token 决定)----------------------
.status-dot--idle {
  --dot-color: var(--text-tertiary);
}

.status-dot--in-use {
  --dot-color: var(--accent);
}

.status-dot--maintenance {
  --dot-color: var(--status-warning);
}

.status-dot--broken {
  --dot-color: var(--status-danger);
}

// ---- IN_USE 脉冲:伪元素 scale + opacity(GPU 合成层,不触发 layout)------
.status-dot--in-use .status-dot__dot::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 50%;
  background: var(--dot-color);
  animation: status-pulse 1.6s var(--ease-out-expo) infinite;
  will-change: transform, opacity;
}

@keyframes status-pulse {
  0% {
    transform: scale(1);
    opacity: 0.55;
  }
  100% {
    transform: scale(2.4);
    opacity: 0;
  }
}

// ---- 本地 reduced-motion 守卫(全局 _motion.scss 不覆盖本组件 keyframe)---
@media (prefers-reduced-motion: reduce) {
  .status-dot--in-use .status-dot__dot::after {
    animation: none;
  }
}
</style>
