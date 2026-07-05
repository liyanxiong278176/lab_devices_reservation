<script setup lang="ts">
// GradientButton — 主 CTA
// 包 el-button,透传 $attrs(type/size/loading/disabled/click 等直达 el-button)
// 青→蓝渐变背景 + 辉光阴影 + hover 增亮 brightness(1.08)+ active scale(.98)
defineOptions({ inheritAttrs: false })
</script>

<template>
  <el-button class="gradient-btn" v-bind="$attrs">
    <slot />
  </el-button>
</template>

<style scoped lang="scss">
.gradient-btn {
  background: var(--grad-accent) !important;
  color: var(--text-on-accent) !important;
  border: none !important;
  border-radius: var(--radius-control);
  font-weight: 600;
  box-shadow: 0 4px 14px rgba(34, 211, 238, 0.25);
  transition:
    filter var(--d-fast) var(--ease-out-expo),
    transform var(--d-fast) var(--ease-out-expo),
    box-shadow var(--d-fast) var(--ease-out-expo);

  &:hover,
  &:focus {
    background: var(--grad-accent) !important;
    color: var(--text-on-accent) !important;
    filter: brightness(1.08);
    box-shadow: 0 6px 20px rgba(34, 211, 238, 0.35);
  }

  &:active {
    transform: scale(0.98);
  }

  &.is-disabled,
  &:disabled {
    filter: grayscale(0.4) brightness(0.7);
    box-shadow: none;
    cursor: not-allowed;
  }
}
</style>
