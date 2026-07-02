<script setup lang="ts">
// Task 5 theme verification placeholder.
// The next task (routing/layout) replaces this App shell with the real layout.
import { ElButton } from 'element-plus'
</script>

<template>
  <main class="theme-check">
    <div class="lab-card theme-check__card">
      <h1 class="theme-check__title">实验室预约系统</h1>
      <p class="theme-check__subtitle">Cal.com 主题层已加载</p>
      <el-button type="primary">主题测试</el-button>
    </div>
  </main>
</template>

<style scoped lang="scss">
.theme-check {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  padding: 24px; // DESIGN.md spacing.lg

  &__card {
    padding: 32px; // DESIGN.md spacing.xl
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 12px; // DESIGN.md spacing.sm
  }

  &__title {
    margin: 0;
    font-size: 28px; // DESIGN.md display-sm
    font-weight: 600;
    line-height: 1.2;
    letter-spacing: -0.5px;
    color: var(--el-text-color-primary); // #111111
  }

  &__subtitle {
    margin: 0 0 8px;
    font-size: 14px; // DESIGN.md body-sm
    color: var(--el-text-color-secondary); // #6b7280
  }
}
</style>
