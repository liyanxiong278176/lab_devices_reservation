<script setup lang="ts">
// EmptyState — 空态
// 居中 flex column:弱辉光圆底 + 图标(--text-tertiary)+ 标题 + 描述 + 可选 action
// icon 传 EP 图标组件名(全局已注册,如 "Inbox"/"DocumentRemove")
defineProps<{
  icon?: string
  title?: string
  description?: string
}>()
</script>

<template>
  <div class="empty-state" role="status" aria-live="polite">
    <div class="empty-state__icon-well">
      <slot name="icon">
        <el-icon v-if="icon" :size="32">
          <component :is="icon" />
        </el-icon>
      </slot>
    </div>

    <h3 v-if="title" class="empty-state__title">{{ title }}</h3>
    <p v-if="description" class="empty-state__description">{{ description }}</p>

    <div v-if="$slots.action" class="empty-state__action">
      <slot name="action" />
    </div>
  </div>
</template>

<style scoped lang="scss">
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  gap: 12px;
  padding: 48px 24px;

  &__icon-well {
    width: 64px;
    height: 64px;
    display: grid;
    place-items: center;
    border-radius: 50%;
    color: var(--text-tertiary);
    background: rgba(34, 211, 238, 0.06);
    box-shadow:
      inset 0 0 0 1px rgba(34, 211, 238, 0.14),
      0 0 24px rgba(34, 211, 238, 0.08);
  }

  &__title {
    margin: 0;
    font-family: var(--font-display);
    font-size: 16px;
    font-weight: 600;
    color: var(--text-primary);
  }

  &__description {
    margin: 0;
    max-width: 360px;
    font-size: 13px;
    line-height: 1.5;
    color: var(--text-secondary);
  }

  &__action {
    margin-top: 4px;
  }
}
</style>
