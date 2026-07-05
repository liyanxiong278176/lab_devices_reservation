<script setup lang="ts">
// Badge — 深色调徽标
// 包 el-badge,透传 $attrs(value/is-dot/hidden/type/max 等直达)
// 覆盖 EP badge CSS 变量:默认 dot = 青强调 + --text-on-accent 深字(对比 WCAG)
// 带 type 时由 theme.dark.scss 的 --el-color-* 映射兜底(primary→accent,状态色已桥接)
defineOptions({ inheritAttrs: false })
</script>

<template>
  <el-badge class="lab-badge" v-bind="$attrs">
    <slot />
  </el-badge>
</template>

<style scoped lang="scss">
.lab-badge {
  // 默认(无 type)dot 用青强调,字用 --text-on-accent 保 WCAG 对比
  --el-badge-bg-color: var(--accent);
  --el-badge-text-color: var(--text-on-accent);
  --el-badge-radius: 10px;
  --el-badge-font-size: 12px;
  --el-badge-border: none;
  --el-badge-padding: 2px 6px;
}
</style>
