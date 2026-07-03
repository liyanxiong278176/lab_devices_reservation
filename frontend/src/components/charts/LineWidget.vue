<script setup lang="ts">
import { computed } from 'vue'
import type { EChartsOption } from 'echarts'
import BaseChart from './BaseChart.vue'
import { BLUE, HAIRLINE, MUTED } from './palette'

const props = defineProps<{
  /** [{date:'YYYY-MM-DD', count}] */
  data: { date: string; count: number }[]
  title?: string
}>()

const hasData = computed(() => props.data.length > 0)

const option = computed<EChartsOption>(() => ({
  color: [BLUE],
  tooltip: { trigger: 'axis' },
  grid: { left: 8, right: 24, top: 16, bottom: 8, containLabel: true },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    // 仅展示 MM-DD，避免 30 天轴标签拥挤
    data: props.data.map((d) => d.date.slice(5)),
    axisLine: { lineStyle: { color: HAIRLINE } },
    axisTick: { show: false },
    axisLabel: { color: MUTED, fontSize: 11 },
  },
  yAxis: {
    type: 'value',
    minInterval: 1,
    axisLine: { show: false },
    axisTick: { show: false },
    splitLine: { lineStyle: { color: HAIRLINE } },
    axisLabel: { color: MUTED, fontSize: 12 },
  },
  series: [
    {
      type: 'line',
      smooth: true,
      showSymbol: false,
      data: props.data.map((d) => d.count),
      areaStyle: { opacity: 0.08 },
      lineStyle: { width: 2 },
    },
  ],
}))
</script>

<template>
  <div class="lab-card chart-card">
    <div v-if="title" class="chart-card__title">{{ title }}</div>
    <BaseChart v-if="hasData" :option="option" />
    <div v-else class="chart-card__empty">暂无数据</div>
  </div>
</template>

<style scoped lang="scss">
.chart-card {
  padding: 16px 20px 8px;
  height: 100%;
  box-sizing: border-box;

  &__title {
    font-size: 15px;
    font-weight: 600;
    color: var(--el-text-color-primary);
    margin-bottom: 8px;
  }

  &__empty {
    height: 300px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--el-text-color-secondary);
    font-size: 14px;
  }
}
</style>
