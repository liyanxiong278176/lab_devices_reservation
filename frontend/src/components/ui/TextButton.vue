<script setup lang="ts">
// TextButton — 次级纯文字按钮
// 包 el-button text,透传 $attrs
// 默认 --text-secondary,hover --accent
defineOptions({ inheritAttrs: false })
</script>

<template>
  <el-button class="text-btn" text v-bind="$attrs">
    <slot />
  </el-button>
</template>

<style scoped lang="scss">
.text-btn {
  // 通过 EP button 的 CSS 变量桥接(优先,跟随 EP 内部状态机)
  --el-button-text-color: var(--text-secondary);
  --el-button-hover-text-color: var(--accent);
  --el-button-active-text-color: var(--accent);
  --el-button-disabled-text-color: var(--text-tertiary);
  color: var(--text-secondary) !important;
  border-radius: var(--radius-control);
  transition: color var(--d-fast) var(--ease-out-expo);

  &:hover,
  &:focus {
    color: var(--accent) !important;
    background: transparent !important;
  }

  &.is-disabled,
  &:disabled {
    color: var(--text-tertiary) !important;
  }
}
</style>
