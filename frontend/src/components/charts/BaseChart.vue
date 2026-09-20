<script setup lang="ts">
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'
import { setupEcharts } from '@/composables/useEcharts'

// 图表只在仪表盘路由加载；把 ECharts 初始化放在图表组件内，避免它进入登录/主布局首屏包。
setupEcharts()

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
