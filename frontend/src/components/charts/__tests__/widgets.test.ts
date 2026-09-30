import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import BaseChart from '../BaseChart.vue'
import BarWidget from '../BarWidget.vue'
import HeatmapWidget from '../HeatmapWidget.vue'
import LineWidget from '../LineWidget.vue'
import PieWidget from '../PieWidget.vue'

vi.mock('vue-echarts', () => ({
  default: {
    name: 'VChartStub',
    props: ['option', 'theme', 'autoresize', 'style'],
    template: '<div class="v-chart-stub" :style="style"></div>',
  },
}))

const global = { stubs: { 'v-chart': true } }

describe('dashboard chart widgets', () => {
  it('renders line-chart empty and populated states with date labels and counts', () => {
    const empty = mount(LineWidget, { props: { data: [] }, global })
    expect(empty.text()).toContain('暂无数据')
    expect(empty.find('.chart-card__title').exists()).toBe(false)

    const wrapper = mount(LineWidget, {
      props: { title: 'Usage', data: [{ date: '2026-09-28', count: 3 }, { date: '2026-09-29', count: 5 }] },
      global,
    })
    const option = wrapper.findComponent(BaseChart).props('option') as any
    expect(wrapper.text()).toContain('Usage')
    expect(option.xAxis.data).toEqual(['09-28', '09-29'])
    expect(option.series[0].data).toEqual([3, 5])
  })

  it('covers vertical and horizontal bars with and without percentage formatting', () => {
    const empty = mount(BarWidget, { props: { data: [] }, global })
    expect(empty.text()).toContain('暂无数据')

    const vertical = mount(BarWidget, {
      props: { title: 'Vertical', data: [{ name: 'scope', value: 2 }, { name: 'laser', value: 4, color: '#123' }] },
      global,
    })
    const verticalOption = vertical.findComponent(BaseChart).props('option') as any
    expect(verticalOption.xAxis).toMatchObject({ type: 'category', data: ['scope', 'laser'] })
    expect(verticalOption.yAxis.type).toBe('value')
    expect(verticalOption.series[0].data).toEqual([{ value: 2 }, { value: 4, itemStyle: { color: '#123' } }])
    expect(verticalOption.tooltip.valueFormatter).toBeUndefined()
    expect(verticalOption.series[0].itemStyle.borderRadius).toEqual([4, 4, 0, 0])

    const horizontal = mount(BarWidget, {
      props: { data: [{ name: 'utilization', value: 75 }], horizontal: true, percent: true },
      global,
    })
    const horizontalOption = horizontal.findComponent(BaseChart).props('option') as any
    expect(horizontalOption.xAxis.type).toBe('value')
    expect(horizontalOption.yAxis).toMatchObject({ type: 'category', data: ['utilization'] })
    expect(horizontalOption.xAxis.axisLabel.formatter).toBe('{value}%')
    expect(horizontalOption.tooltip.valueFormatter(75)).toBe('75%')
    expect(horizontalOption.series[0].itemStyle.borderRadius).toEqual([0, 4, 4, 0])

    const verticalPercent = mount(BarWidget, {
      props: { data: [{ name: 'completion', value: 80 }], percent: true }, global,
    }).findComponent(BaseChart).props('option') as any
    expect(verticalPercent.yAxis.axisLabel.formatter).toBe('{value}%')
    expect(verticalPercent.tooltip.valueFormatter(80)).toBe('80%')
  })

  it('uses doughnut defaults, solid-pie overrides and the empty/all-zero states', () => {
    expect(mount(PieWidget, { props: { data: [] }, global }).text()).toContain('暂无数据')
    expect(mount(PieWidget, { props: { data: [{ name: 'empty', value: 0 }] }, global }).text())
      .toContain('暂无数据')

    const doughnut = mount(PieWidget, {
      props: { title: 'Statuses', data: [{ name: 'ready', value: 2 }, { name: 'busy', value: 1, color: '#f00' }] },
      global,
    })
    const doughnutSeries = (doughnut.findComponent(BaseChart).props('option') as any).series[0]
    expect(doughnut.text()).toContain('Statuses')
    expect(doughnutSeries.radius).toEqual(['45%', '70%'])
    expect(doughnutSeries.label.show).toBe(false)
    expect(doughnutSeries.data).toEqual([
      { name: 'ready', value: 2 }, { name: 'busy', value: 1, itemStyle: { color: '#f00' } },
    ])

    const solid = mount(PieWidget, {
      props: { data: [{ name: 'ready', value: 1 }], doughnut: false }, global,
    })
    const solidSeries = (solid.findComponent(BaseChart).props('option') as any).series[0]
    expect(solidSeries.radius).toBe('65%')
    expect(solidSeries.label.show).toBe(true)
    expect(solidSeries.labelLine.show).toBe(true)
  })

  it('builds a full heatmap grid, formats tooltips, and scales zero or positive maxima', () => {
    expect(mount(HeatmapWidget, { props: { data: [] }, global }).text()).toContain('暂无数据')

    const zero = mount(HeatmapWidget, {
      props: { data: [{ dayOfWeek: 1, hour: 0, count: 0 }] }, global,
    })
    const zeroOption = zero.findComponent(BaseChart).props('option') as any
    expect(zeroOption.visualMap.max).toBe(1)
    expect(zeroOption.series[0].data).toHaveLength(98)
    expect(zeroOption.series[0].data[0]).toEqual([0, 0, 0])
    expect(zeroOption.tooltip.formatter({ value: [0, 0, 0] })).toContain('周日 08:00')

    const populated = mount(HeatmapWidget, {
      props: { title: 'Density', data: [{ dayOfWeek: 7, hour: 13, count: 8 }] }, global,
    })
    const option = populated.findComponent(BaseChart).props('option') as any
    expect(option.visualMap.max).toBe(8)
    expect(option.series[0].data[97]).toEqual([13, 6, 8])
    expect(option.tooltip.formatter({ value: [13, 6, 8] })).toContain('周六 21:00')
  })

  it('passes default and caller overrides through the base chart', () => {
    const defaults = mount(BaseChart, { props: { option: {} as any }, global })
    expect(defaults.find('.base-chart').attributes('style')).toContain('height: 300px')
    const custom = mount(BaseChart, {
      props: { option: {} as any, height: '240px', theme: 'custom-theme' }, global,
    })
    expect(custom.find('.base-chart').attributes('style')).toContain('height: 240px')
    expect(custom.find('.v-chart-stub').exists()).toBe(true)
  })
})
