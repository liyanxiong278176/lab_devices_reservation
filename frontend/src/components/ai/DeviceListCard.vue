<script setup lang="ts">
interface Device {
  id: number
  name: string
  category?: string
  location?: string
  status?: string
}

defineProps<{ devices: Device[] }>()
</script>

<template>
  <div class="ai-device-grid">
    <div v-for="d in devices" :key="d.id" class="ai-device-cell">
      <div class="ai-device-name">{{ d.name }}</div>
      <div v-if="d.category" class="ai-device-meta">{{ d.category }}</div>
      <div v-if="d.location" class="ai-device-meta">{{ d.location }}</div>
      <el-tag
        v-if="d.status"
        :type="d.status === 'AVAILABLE' ? 'success' : 'warning'"
        size="small"
        effect="dark"
      >
        {{ d.status }}
      </el-tag>
    </div>
  </div>
</template>

<style scoped lang="scss">
.ai-device-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 8px;
  margin: 6px 12px;
}
.ai-device-cell {
  background: var(--bg-elev-1, #111827);
  border: 1px solid var(--border-subtle, #1f2937);
  border-radius: 8px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.ai-device-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--fg-primary, #e5e7eb);
}
.ai-device-meta {
  font-size: 11px;
  color: var(--fg-muted, #9ca3af);
}
</style>
