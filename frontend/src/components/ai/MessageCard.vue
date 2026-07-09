<script setup lang="ts">
import type { ChatMessage } from '@/types/ai'
import UserMessage from './UserMessage.vue'
import AssistantMessage from './AssistantMessage.vue'
import ErrorCard from './ErrorCard.vue'
import ResultCard from './ResultCard.vue'

defineProps<{ message: ChatMessage }>()
</script>

<template>
  <UserMessage v-if="message.role === 'user'" :text="message.text" />
  <AssistantMessage v-else-if="message.role === 'assistant'" :message="message" />
  <ResultCard
    v-else-if="message.role === 'tool' && (message.toolCalls?.length ?? 0) > 0"
    :msg="'操作完成'"
    :data="message.toolCalls?.[0]"
  />
  <ErrorCard
    v-else-if="message.role === 'system'"
    :code="'SYSTEM'"
    :msg="message.text"
  />
</template>
