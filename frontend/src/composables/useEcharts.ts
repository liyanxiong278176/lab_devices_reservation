import { use, registerTheme } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart, BarChart, LineChart, HeatmapChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  VisualMapComponent,
} from 'echarts/components'
import { labDarkTheme } from '@/styles/echarts-dark-theme'

let registered = false

/**
 * 一次性注册 echarts 按需模块（tree-shakeable）+ 自定义深色主题。
 * 在 main.ts 挂载前调用一次即可；多次调用幂等。
 *
 * 主题 'lab-dark' 由 BaseChart.vue 默认消费(echarts.init(dom, 'lab-dark'))，
 * 颜色与 styles/theme.dark.scss token 对齐(详见 echarts-dark-theme.ts)。
 */
export function setupEcharts() {
  if (registered) return
  use([
    CanvasRenderer,
    PieChart,
    BarChart,
    LineChart,
    HeatmapChart,
    TitleComponent,
    TooltipComponent,
    LegendComponent,
    GridComponent,
    VisualMapComponent,
  ])
  registerTheme('lab-dark', labDarkTheme)
  registered = true
}
