<script setup lang="ts">
defineProps<{
  items: Array<{ label: string; value: string }>
}>()

const emit = defineEmits<{
  pick: [value: string]
}>()
</script>

<template>
  <div class="ai-suggestions">
    <button
      v-for="(s, i) in items"
      :key="i"
      class="ai-suggestion-chip"
      type="button"
      @click="emit('pick', s.value)"
    >
      {{ s.label }}
    </button>
  </div>
</template>

<style scoped lang="scss">
.ai-suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px 12px;
  border-top: 1px solid var(--border-subtle, #1f2937);
}
.ai-suggestion-chip {
  background: var(--bg-elev-1, #111827);
  border: 1px solid var(--border-subtle, #1f2937);
  color: var(--fg-secondary, #d1d5db);
  border-radius: 14px;
  padding: 4px 12px;
  font-size: 12px;
  font-family: inherit;
  cursor: pointer;
  transition: all 0.15s ease;
  &:hover {
    border-color: var(--accent, #6366f1);
    color: var(--accent, #6366f1);
  }
}
</style>
