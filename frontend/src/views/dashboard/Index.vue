<script setup lang="ts">
// S0 联调闭环占位：S4 阶段用 ECharts 替换为富指标驾驶舱。
</script>

<template>
  <div class="lab-card dashboard-card">
    <h1 class="dashboard-card__title">驾驶舱</h1>
    <p class="dashboard-card__hint">待 S4 实现 ECharts 指标看板。</p>
  </div>
</template>

<style scoped lang="scss">
.dashboard-card {
  padding: 32px;

  &__title {
    margin: 0 0 8px;
    font-size: 24px;
    font-weight: 600;
    color: var(--el-text-color-primary); // #111111
  }

  &__hint {
    margin: 0;
    font-size: 14px;
    color: var(--el-text-color-secondary); // #6b7280
  }
}
</style>
