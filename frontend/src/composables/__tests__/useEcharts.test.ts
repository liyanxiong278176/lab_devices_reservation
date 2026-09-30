import { describe, expect, it, vi } from 'vitest'

const echarts = vi.hoisted(() => ({ use: vi.fn(), registerTheme: vi.fn() }))
vi.mock('echarts/core', () => echarts)
vi.mock('echarts/renderers', () => ({ CanvasRenderer: 'canvas-renderer' }))
vi.mock('echarts/charts', () => ({
  PieChart: 'pie', BarChart: 'bar', LineChart: 'line', HeatmapChart: 'heatmap',
}))
vi.mock('echarts/components', () => ({
  TitleComponent: 'title', TooltipComponent: 'tooltip', LegendComponent: 'legend',
  GridComponent: 'grid', VisualMapComponent: 'visual-map',
}))
vi.mock('@/styles/echarts-dark-theme', () => ({ labDarkTheme: { backgroundColor: '#000' } }))

describe('setupEcharts', () => {
  it('registers only required chart modules and the dark theme once', async () => {
    const { setupEcharts } = await import('../useEcharts')

    setupEcharts()
    setupEcharts()

    expect(echarts.use).toHaveBeenCalledOnce()
    expect(echarts.use).toHaveBeenCalledWith([
      'canvas-renderer', 'pie', 'bar', 'line', 'heatmap',
      'title', 'tooltip', 'legend', 'grid', 'visual-map',
    ])
    expect(echarts.registerTheme).toHaveBeenCalledOnce()
    expect(echarts.registerTheme).toHaveBeenCalledWith('lab-dark', { backgroundColor: '#000' })
  })
})
