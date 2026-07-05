<script setup lang="ts">
// Badge — 深色调徽标
// 包 el-badge,透传 $attrs(value/is-dot/hidden/type/max 等直达)
// variant:accent/success/warning/danger/info → 覆盖 --el-badge-bg-color(状态色)
//   文字色统一 --text-on-accent(#04141a 深字压状态色底,WCAG 对比足)
//   默认 accent(青强调),对齐 Tag 的 variant 语义
defineOptions({ inheritAttrs: false })

withDefaults(
  defineProps<{
    variant?: 'accent' | 'success' | 'warning' | 'danger' | 'info'
  }>(),
  {
    variant: 'accent',
  },
)
</script>

<template>
  <el-badge class="lab-badge" :class="`lab-badge--${variant}`" v-bind="$attrs">
    <slot />
  </el-badge>
</template>

<style scoped lang="scss">
.lab-badge {
  // 文字色统一深字压状态色(--text-on-accent = #04141a),保 WCAG 对比
  --el-badge-text-color: var(--text-on-accent);
  --el-badge-radius: 10px;
  --el-badge-font-size: 12px;
  --el-badge-border: none;
  --el-badge-padding: 2px 6px;
}

// variant → 状态色底(覆盖 --el-badge-bg-color)
.lab-badge--accent {
  --el-badge-bg-color: var(--accent);
}

.lab-badge--success {
  --el-badge-bg-color: var(--status-success);
}

.lab-badge--warning {
  --el-badge-bg-color: var(--status-warning);
}

.lab-badge--danger {
  --el-badge-bg-color: var(--status-danger);
}

.lab-badge--info {
  --el-badge-bg-color: var(--status-info);
}
</style>
