<script setup lang="ts">
import { computed } from 'vue'
import type { EChartsOption } from 'echarts'
import BaseChart from './BaseChart.vue'
import { SERIES_PALETTE, BODY, MUTED, BG_SURFACE, type ChartDatum } from './palette'

const props = withDefaults(
  defineProps<{
    data: ChartDatum[]
    title?: string
    /** true=环形（缺省），false=实心饼 */
    doughnut?: boolean
  }>(),
  { doughnut: true, title: '' },
)

// 全 0 或空数组 → 视为无数据（环形饼无可见切片）。
const hasData = computed(() => props.data.some((d) => d.value > 0))

const option = computed<EChartsOption>(() => ({
  color: SERIES_PALETTE,
  tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
  legend: {
    bottom: 4,
    icon: 'circle',
    itemWidth: 8,
    itemHeight: 8,
    textStyle: { color: MUTED, fontSize: 12 },
  },
  series: [
    {
      type: 'pie',
      radius: props.doughnut ? ['45%', '70%'] : '65%',
      center: ['50%', '46%'],
      avoidLabelOverlap: true,
      itemStyle: { borderColor: BG_SURFACE, borderWidth: 2 }, // 深底融卡分隔(旧 #fff 在深底是硬白线)
      label: { show: !props.doughnut, color: BODY, fontSize: 12 },
      labelLine: { show: !props.doughnut },
      data: props.data.map((d) =>
        d.color
          ? { name: d.name, value: d.value, itemStyle: { color: d.color } }
          : { name: d.name, value: d.value },
      ),
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
    color: var(--el-text-color-primary); // 深色 token(--text-primary)
    margin-bottom: 8px;
  }

  &__empty {
    height: 300px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--el-text-color-secondary); // 深色 token(--text-secondary)
    font-size: 14px;
  }
}
</style>
