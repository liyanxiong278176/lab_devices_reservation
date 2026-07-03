<script setup lang="ts">
import { computed } from 'vue'
import type { EChartsOption } from 'echarts'
import BaseChart from './BaseChart.vue'
import { BLUE, HAIRLINE, MUTED, type ChartDatum } from './palette'

const props = withDefaults(
  defineProps<{
    data: ChartDatum[]
    title?: string
    /** true 时 Y/X 轴按百分比显示（数据应已乘 100 取整） */
    percent?: boolean
    /** true 时切换为横向条形（类别落在 Y 轴） */
    horizontal?: boolean
  }>(),
  { percent: false, horizontal: false, title: '' },
)

const hasData = computed(() => props.data.length > 0)

const option = computed<EChartsOption>(() => {
  const cats = props.data.map((d) => d.name)
  const series = props.data.map((d) =>
    d.color
      ? { value: d.value, itemStyle: { color: d.color } }
      : { value: d.value },
  )
  const vertical = !props.horizontal
  return {
    color: [BLUE],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      valueFormatter: props.percent ? (v: unknown) => `${v}%` : undefined,
    },
    grid: { left: 8, right: 24, top: 16, bottom: 8, containLabel: true },
    xAxis: {
      type: vertical ? 'category' : 'value',
      data: vertical ? cats : undefined,
      axisLine: { lineStyle: { color: HAIRLINE } },
      axisTick: { show: false },
      axisLabel: {
        color: MUTED,
        fontSize: 12,
        formatter: !vertical && props.percent ? '{value}%' : undefined,
      },
    },
    yAxis: {
      type: vertical ? 'value' : 'category',
      data: !vertical ? cats : undefined,
      axisLine: { lineStyle: { color: HAIRLINE } },
      axisTick: { show: false },
      splitLine: {
        show: vertical,
        lineStyle: { color: HAIRLINE },
      },
      axisLabel: {
        color: MUTED,
        fontSize: 12,
        formatter: vertical && props.percent ? '{value}%' : undefined,
      },
    },
    series: [
      {
        type: 'bar',
        data: series,
        barMaxWidth: 28,
        itemStyle: {
          borderRadius: vertical ? [4, 4, 0, 0] : [0, 4, 4, 0],
        },
      },
    ],
  }
})
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
