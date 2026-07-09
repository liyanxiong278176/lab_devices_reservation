<script setup lang="ts">
import { computed, onMounted, onUnmounted, watch } from 'vue'
import { useAiStore } from '@/stores/ai'
import '@/styles/color-cursor.scss'

/**
 * 彩色光标 — 执行态期间切换 body 的 cursor。
 *
 * <p>AI busy 时(.ai-color-cursor class 挂上)<body> 上所有鼠标变渐变 SVG,
 * 4s 色相漂移动画。
 */
const store = useAiStore()

const active = computed(
  () =>
    store.state === 'step_running' ||
    store.state === 'streaming' ||
    store.state === 'executing',
)

function setBodyClass(on: boolean) {
  if (typeof document === 'undefined') return
  document.body.classList.toggle('ai-color-cursor', on)
}

watch(active, (v) => setBodyClass(v), { immediate: true })
onMounted(() => setBodyClass(active.value))
onUnmounted(() => setBodyClass(false))
</script>

<template><span class="ai-color-cursor-host" /></template>
