<script setup lang="ts">
// GhostButton — 次级描边按钮
// 包 el-button,透传 $attrs
// 透明底 + hairline-strong 描边;hover 青色字 + 青色边 + 青色 6% 底
defineOptions({ inheritAttrs: false })
</script>

<template>
  <el-button class="ghost-btn" v-bind="$attrs">
    <slot />
  </el-button>
</template>

<style scoped lang="scss">
.ghost-btn {
  background: transparent !important;
  color: var(--text-primary) !important;
  border: 1px solid var(--border-strong) !important;
  border-radius: var(--radius-control);
  transition:
    color var(--d-fast) var(--ease-out-expo),
    border-color var(--d-fast) var(--ease-out-expo),
    background-color var(--d-fast) var(--ease-out-expo);

  &:hover,
  &:focus {
    background: rgba(34, 211, 238, 0.06) !important;
    color: var(--accent) !important;
    border-color: var(--accent) !important;
  }

  &:active {
    background: rgba(34, 211, 238, 0.1) !important;
  }

  &.is-disabled,
  &:disabled {
    color: var(--text-tertiary) !important;
    border-color: var(--border-subtle) !important;
    background: transparent !important;
    cursor: not-allowed;
  }
}
</style>
