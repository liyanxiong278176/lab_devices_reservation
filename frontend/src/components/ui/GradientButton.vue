<script setup lang="ts">
// GradientButton — 主 CTA
// 包 el-button,透传 $attrs(type/size/loading/disabled/click 等直达 el-button)
// Signal-blue primary action with a quiet lift; the visual system avoids
// large gradients so the action remains clear in both appearances.
defineOptions({ inheritAttrs: false })
</script>

<template>
  <el-button class="gradient-btn" v-bind="$attrs">
    <slot />
  </el-button>
</template>

<style scoped lang="scss">
.gradient-btn {
  background: var(--accent) !important;
  color: var(--text-on-accent) !important;
  border: none !important;
  border-radius: var(--radius-control);
  font-weight: 600;
  box-shadow: 0 8px 18px color-mix(in srgb, var(--accent) 18%, transparent);
  transition:
    filter var(--d-fast) var(--ease-out-expo),
    transform var(--d-fast) var(--ease-out-expo),
    box-shadow var(--d-fast) var(--ease-out-expo);

  &:hover,
  &:focus {
    background: var(--accent-bright) !important;
    color: var(--text-on-accent) !important;
    filter: none;
    box-shadow: 0 11px 24px color-mix(in srgb, var(--accent) 25%, transparent);
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
