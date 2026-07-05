<script setup lang="ts">
// GlowCard — 强调卡片
// 结构同 Panel(--bg-surface + hairline + radius),hover 时 box-shadow = --glow-accent
// 青色辉光 + 抬升 -4px;accent = 顶部 1px 青条(沿用 Panel 视觉契约)
// 独立实现(不嵌套 Panel)以避免 hover transform 规则在跨 scoped 文件间的源序歧义
withDefaults(
  defineProps<{
    accent?: boolean
    as?: string
  }>(),
  {
    accent: false,
    as: 'div',
  },
)
</script>

<template>
  <component :is="as" class="glow-card" :class="{ 'glow-card--accent': accent }">
    <slot />
  </component>
</template>

<style scoped lang="scss">
.glow-card {
  position: relative;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-card);
  padding: 20px;
  box-shadow: var(--shadow-soft-light);
  transition:
    transform var(--d-med) var(--ease-out-expo),
    box-shadow var(--d-med) var(--ease-out-expo),
    border-color var(--d-med) var(--ease-out-expo);

  &:hover {
    transform: translateY(-4px);
    border-color: var(--accent);
    box-shadow: var(--glow-accent);
  }

  &--accent {
    box-shadow:
      inset 0 1px 0 var(--accent),
      var(--shadow-soft-light);

    &:hover {
      box-shadow:
        inset 0 1px 0 var(--accent),
        var(--glow-accent);
    }
  }
}
</style>
