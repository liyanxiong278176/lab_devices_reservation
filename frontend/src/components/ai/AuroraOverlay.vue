<script setup lang="ts">
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { useAiStore } from '@/stores/ai'
import '@/styles/aurora.scss'

/**
 * 极光背景层 — 当 AI 执行(step_running / streaming / executing)时
 * 在 <body> 上加 .ai-aurora-active 激活 CSS keyframes。
 *
 * <p>3 个 blob 圆点用 mix-blend-mode: screen,blur:80px,只在执行态出现。
 */
const store = useAiStore()

const active = computed(() =>
  store.state === 'step_running' ||
  store.state === 'streaming' ||
  store.state === 'awaiting_confirmation' ||
  store.state === 'executing',
)

function setBodyClass(on: boolean) {
  if (typeof document === 'undefined') return
  document.body.classList.toggle('ai-aurora-active', on)
}

watch(active, (v) => setBodyClass(v), { immediate: true })

onMounted(() => setBodyClass(active.value))
onUnmounted(() => setBodyClass(false))
</script>

<template>
  <div v-show="active" class="ai-aurora-layer" aria-hidden="true">
    <div class="ai-aurora-blob ai-aurora-blob--1" />
    <div class="ai-aurora-blob ai-aurora-blob--2" />
    <div class="ai-aurora-blob ai-aurora-blob--3" />
  </div>
</template>
