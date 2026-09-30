<script setup lang="ts">
const props = defineProps<{
  modelValue: number
  options: number[]
  label: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: number]
  change: [value: number]
}>()

function onChange(event: Event) {
  const target = event.target
  if (!(target instanceof HTMLSelectElement)) return
  const value = Number(target.value)
  emit('update:modelValue', value)
  emit('change', value)
}
</script>

<template>
  <label class="page-size-control">
    <span>每页显示</span>
    <select :aria-label="label" :value="props.modelValue" @change="onChange">
      <option v-for="size in props.options" :key="size" :value="size">{{ size }} 条</option>
    </select>
  </label>
</template>

<style scoped lang="scss">
.page-size-control {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--text-secondary);
  font-size: 12px;

  select {
    min-height: 34px;
    padding: 0 9px;
    color: var(--text-primary);
    background: var(--bg-surface);
    border: 1px solid var(--border-default);
    border-radius: 9px;
    font: inherit;
  }
}
</style>
