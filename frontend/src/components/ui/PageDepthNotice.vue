<script setup lang="ts">
defineProps<{ total: number }>()
</script>

<template>
  <p class="page-depth-notice" role="status">
    共 {{ total.toLocaleString() }} 条记录；深页最多跳过 100,000 条，页码已限制在可访问范围。请缩小筛选范围以查询更深的结果。
  </p>
</template>

<style scoped>
.page-depth-notice {
  margin: 0 0 10px;
  padding: 9px 12px;
  color: var(--text-secondary);
  background: color-mix(in srgb, var(--accent) 7%, var(--bg-elevated));
  border-left: 2px solid var(--accent);
  font-size: 12px;
  line-height: 1.5;
}
</style>
