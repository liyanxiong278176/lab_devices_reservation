<script setup lang="ts">
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'

withDefaults(defineProps<{ option: EChartsOption; height?: string }>(), {
  height: '300px',
})
</script>

<template>
  <v-chart class="base-chart" :option="option" autoresize :style="{ height }" />
</template>

<style scoped lang="scss">
.base-chart {
  width: 100%;
}
</style>
