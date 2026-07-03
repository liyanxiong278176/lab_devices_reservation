<script setup lang="ts">
defineProps<{ label: string; value: string | number; hint?: string }>()
</script>

<template>
  <div class="lab-card stat-card">
    <div class="stat-card__value">{{ value }}</div>
    <div class="stat-card__label">{{ label }}</div>
    <div v-if="hint" class="stat-card__hint">{{ hint }}</div>
  </div>
</template>

<style scoped lang="scss">
.stat-card {
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 4px;

  &__value {
    font-size: 32px;
    font-weight: 600;
    line-height: 1.1;
    letter-spacing: -0.5px;
    font-variant-numeric: tabular-nums;
    color: var(--el-text-color-primary); // #111111
  }

  &__label {
    font-size: 14px;
    color: var(--el-text-color-secondary); // #6b7280
  }

  &__hint {
    font-size: 12px;
    color: var(--el-text-color-placeholder);
  }
}
</style>
