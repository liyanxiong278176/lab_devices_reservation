<script setup lang="ts">
// Tag — 深色 semi-fill 标签
// 包 el-tag,透传 $attrs(closable/effect/size 等直达)
// variant 通过覆盖 EP 的 --el-tag-* CSS 变量实现,无 !important 也能赢特异性
//   (scoped 后 .lab-tag.lab-tag--{v} = 0,3,0,EP 单类 .el-tag--{type} = 0,1,0)
withDefaults(
  defineProps<{
    variant?: 'default' | 'success' | 'warning' | 'danger' | 'info' | 'accent'
  }>(),
  {
    variant: 'default',
  },
)
defineOptions({ inheritAttrs: false })
</script>

<template>
  <el-tag class="lab-tag" :class="`lab-tag--${variant}`" v-bind="$attrs">
    <slot />
  </el-tag>
</template>

<style scoped lang="scss">
// 基础:重置 EP tag 默认色,统一深色 semi-fill 基线
.lab-tag {
  --el-tag-bg-color: var(--bg-elevated);
  --el-tag-border-color: var(--border-default);
  --el-tag-text-color: var(--text-secondary);
  --el-tag-hover-color: var(--text-secondary);
  border-radius: var(--radius-control);
  font-weight: 500;
}

// variant → 状态色 rgba(.12) 底 + 状态色字 + rgba(.3) 边
.lab-tag.lab-tag--default {
  --el-tag-bg-color: var(--bg-elevated);
  --el-tag-border-color: var(--border-default);
  --el-tag-text-color: var(--text-secondary);
  --el-tag-hover-color: var(--text-primary);
}

.lab-tag.lab-tag--success {
  --el-tag-bg-color: rgba(52, 211, 153, 0.12);
  --el-tag-border-color: rgba(52, 211, 153, 0.3);
  --el-tag-text-color: var(--status-success);
  --el-tag-hover-color: var(--status-success);
}

.lab-tag.lab-tag--warning {
  --el-tag-bg-color: rgba(251, 191, 36, 0.12);
  --el-tag-border-color: rgba(251, 191, 36, 0.3);
  --el-tag-text-color: var(--status-warning);
  --el-tag-hover-color: var(--status-warning);
}

.lab-tag.lab-tag--danger {
  --el-tag-bg-color: rgba(248, 113, 113, 0.12);
  --el-tag-border-color: rgba(248, 113, 113, 0.3);
  --el-tag-text-color: var(--status-danger);
  --el-tag-hover-color: var(--status-danger);
}

.lab-tag.lab-tag--info {
  --el-tag-bg-color: rgba(96, 165, 250, 0.12);
  --el-tag-border-color: rgba(96, 165, 250, 0.3);
  --el-tag-text-color: var(--status-info);
  --el-tag-hover-color: var(--status-info);
}

.lab-tag.lab-tag--accent {
  --el-tag-bg-color: rgba(34, 211, 238, 0.12);
  --el-tag-border-color: rgba(34, 211, 238, 0.3);
  --el-tag-text-color: var(--accent);
  --el-tag-hover-color: var(--accent-bright);
}
</style>
