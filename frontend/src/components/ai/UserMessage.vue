<script setup lang="ts">
defineProps<{ text: string }>()
</script>

<template>
  <div class="ai-user-msg">
    <div class="ai-user-bubble">{{ text }}</div>
  </div>
</template>

<style scoped lang="scss">
.ai-user-msg {
  display: flex;
  justify-content: flex-end;
  padding: 6px 12px;
}
.ai-user-bubble {
  max-width: 80%;
  background: linear-gradient(135deg, var(--accent, #6366f1), #8b5cf6);
  color: #fff;
  border-radius: 14px 14px 4px 14px;
  padding: 10px 14px;
  font-size: 14px;
  line-height: 1.5;
  word-break: break-word;
}
</style>
