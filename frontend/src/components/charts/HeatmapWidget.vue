<script setup lang="ts">
import { computed } from 'vue'
import type { EChartsOption } from 'echarts'
import BaseChart from './BaseChart.vue'
import { BLUE, HAIRLINE, INK, MUTED, SURFACE_SOFT } from './palette'

const props = defineProps<{
  /** 稀疏单元格：dayOfWeek 1=周日..7=周六；hour 0..13 对应 08:00..21:00 */
  data: { dayOfWeek: number; hour: number; count: number }[]
  title?: string
}>()

const hasData = computed(() => props.data.length > 0)

// hour 0..13 → "08:00".."21:00"
const HOUR_LABELS = Array.from({ length: 14 }, (_, i) => `${String(i + 8).padStart(2, '0')}:00`)
// dayOfWeek 1..7 → 周日..周六
const DAY_LABELS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六']

const option = computed<EChartsOption>(() => {
  // 用稀疏查询结果铺满 7×14 全网格，缺失项记 0。
  const lookup = new Map<string, number>()
  let max = 0
  for (const cell of props.data) {
    lookup.set(`${cell.dayOfWeek}-${cell.hour}`, cell.count)
    if (cell.count > max) max = cell.count
  }
  const cells: [number, number, number][] = []
  for (let day = 1; day <= 7; day++) {
    for (let hour = 0; hour < 14; hour++) {
      const count = lookup.get(`${day}-${hour}`) ?? 0
      // x = hour 下标，y = day 下标（0..6）
      cells.push([hour, day - 1, count])
    }
  }
  return {
    tooltip: {
      position: 'top',
      formatter: (p: unknown) => {
        const param = p as { value: [number, number, number] }
        const [hIdx, dIdx, count] = param.value
        return `${DAY_LABELS[dIdx]} ${HOUR_LABELS[hIdx]}<br/>预约数：<b>${count}</b>`
      },
    },
    grid: { left: 8, right: 24, top: 16, bottom: 56, containLabel: true },
    xAxis: {
      type: 'category',
      data: HOUR_LABELS,
      splitArea: { show: false },
      axisLine: { lineStyle: { color: HAIRLINE } },
      axisTick: { show: false },
      axisLabel: { color: MUTED, fontSize: 11 },
    },
    yAxis: {
      type: 'category',
      data: DAY_LABELS,
      splitArea: { show: false },
      axisLine: { lineStyle: { color: HAIRLINE } },
      axisTick: { show: false },
      axisLabel: { color: MUTED, fontSize: 12 },
    },
    visualMap: {
      min: 0,
      max: max < 1 ? 1 : max,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 4,
      textStyle: { color: MUTED, fontSize: 11 },
      inRange: { color: [SURFACE_SOFT, BLUE, INK] },
    },
    series: [
      {
        type: 'heatmap',
        data: cells,
        label: { show: false },
        emphasis: { itemStyle: { borderColor: '#fff', borderWidth: 1 } },
      },
    ],
  }
})
</script>

<template>
  <div class="lab-card chart-card">
    <div v-if="title" class="chart-card__title">{{ title }}</div>
    <BaseChart v-if="hasData" :option="option" height="340px" />
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
    height: 340px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--el-text-color-secondary);
    font-size: 14px;
  }
}
</style>
