<script setup lang="ts">
import type { ChatMessage } from '@/types/ai'

defineProps<{ message: ChatMessage }>()
</script>

<template>
  <div class="ai-asst-msg">
    <div class="ai-asst-avatar">AI</div>
    <div class="ai-asst-body">
      <div v-if="message.text" class="ai-asst-bubble" v-text="message.text" />
      <div v-else class="ai-asst-typing"><span /><span /><span /></div>
    </div>
  </div>
</template>

<style scoped lang="scss">
.ai-asst-msg {
  display: flex;
  gap: 10px;
  padding: 6px 12px;
}
.ai-asst-avatar {
  flex: 0 0 28px;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--bg-elev-2, #1f2937);
  color: var(--accent, #6366f1);
  font-size: 11px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}
.ai-asst-body {
  flex: 1;
  min-width: 0;
}
.ai-asst-bubble {
  background: var(--bg-elev-1, #111827);
  border: 1px solid var(--border-subtle, #1f2937);
  color: var(--fg-primary, #e5e7eb);
  border-radius: 14px 14px 14px 4px;
  padding: 10px 14px;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.ai-asst-typing {
  display: flex;
  gap: 4px;
  padding: 12px 14px;
  align-items: center;
  background: var(--bg-elev-1, #111827);
  border: 1px solid var(--border-subtle, #1f2937);
  border-radius: 14px 14px 14px 4px;
  width: fit-content;
  span {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--fg-muted, #6b7280);
    animation: ai-typing 1.2s infinite;
    &:nth-child(2) { animation-delay: 0.2s; }
    &:nth-child(3) { animation-delay: 0.4s; }
  }
}
@keyframes ai-typing {
  0%, 60%, 100% { opacity: 0.3; transform: translateY(0); }
  30% { opacity: 1; transform: translateY(-2px); }
}
</style>
