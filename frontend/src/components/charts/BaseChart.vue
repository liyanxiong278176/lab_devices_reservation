<script setup lang="ts">
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'

// theme 默认 'lab-dark'(由 setupEcharts 注册);调用方可传主题名或主题对象覆盖。
withDefaults(
  defineProps<{ option: EChartsOption; height?: string; theme?: string | object }>(),
  {
    height: '300px',
    theme: 'lab-dark',
  },
)
</script>

<template>
  <v-chart
    class="base-chart"
    :option="option"
    :theme="theme"
    autoresize
    :style="{ height }"
  />
</template>

<style scoped lang="scss">
.base-chart {
  width: 100%;
}
</style>
