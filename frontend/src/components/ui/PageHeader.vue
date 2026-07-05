<script setup lang="ts">
// PageHeader — 页头:展示标题 + 副标题 + 右侧 actions + 可选面包屑
// 标题用 Space Grotesk(--font-display),底部 1px hairline(--border-subtle)
defineProps<{
  title: string
  subtitle?: string
}>()
</script>

<template>
  <header class="page-header">
    <div v-if="$slots.breadcrumb" class="page-header__breadcrumb">
      <slot name="breadcrumb" />
    </div>

    <div class="page-header__main">
      <div class="page-header__heading">
        <h1 class="page-header__title">{{ title }}</h1>
        <div v-if="$slots.actions" class="page-header__actions">
          <slot name="actions" />
        </div>
      </div>
      <p v-if="subtitle" class="page-header__subtitle">{{ subtitle }}</p>
    </div>
  </header>
</template>

<style scoped lang="scss">
.page-header {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--border-subtle);

  &__breadcrumb {
    font-size: 13px;
    color: var(--text-tertiary);
  }

  &__main {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  &__heading {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
  }

  &__title {
    margin: 0;
    font-family: var(--font-display);
    font-weight: 600;
    font-size: 28px;
    line-height: 1.2;
    letter-spacing: -0.5px;
    color: var(--text-primary);
  }

  &__subtitle {
    margin: 0;
    font-size: 14px;
    line-height: 1.5;
    color: var(--text-secondary);
  }

  &__actions {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }
}
</style>
