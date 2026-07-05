<script setup lang="ts">
// Skeleton — 加载占位(深色 shimmer 扫光,非转圈)
// 复用全局 .shimmer 类(已含深色渐变 + 动画 + reduced-motion 守卫)
// variant: text(多行)/ rect(块)/ circle(头像)
// rows:仅 text variant 多行,末行 80% 宽
withDefaults(
  defineProps<{
    variant?: 'text' | 'rect' | 'circle'
    width?: string
    height?: string
    rows?: number
  }>(),
  {
    variant: 'rect',
    rows: 1,
  },
)
</script>

<template>
  <div class="skeleton-root" :style="{ width: width }">
    <div
      v-for="i in rows"
      :key="i"
      class="skeleton shimmer"
      :class="[`skeleton--${variant}`, { 'skeleton--last': rows > 1 && i === rows }]"
      :style="{ height: height }"
    />
  </div>
</template>

<style scoped lang="scss">
.skeleton-root {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.skeleton {
  display: block;
  width: 100%;
  min-height: 14px;

  &--text {
    height: 14px;
    // 4px 不在 token 圆角尺度:文本骨架比控件更紧致,模拟行高留白,非 --radius-control(8px)
    border-radius: 4px;
  }

  &--rect {
    height: 100%;
    // 64px 不在 token 尺度:rect 块骨架的默认可读块高(卡片/面板占位最小可视高),无对应 spacing token
    min-height: 64px;
    border-radius: var(--radius-control);
  }

  &--circle {
    width: 40px;
    height: 40px;
    min-height: 40px;
    border-radius: 50%;
  }

  // 多行 text 末行收窄(更像真实文本块的尾行)
  &--last.skeleton--text {
    width: 80%;
  }
}
</style>
