import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { PieChart, BarChart, LineChart, HeatmapChart } from 'echarts/charts'
import {
  TitleComponent,
  TooltipComponent,
  LegendComponent,
  GridComponent,
  VisualMapComponent,
} from 'echarts/components'

let registered = false

/**
 * 一次性注册 echarts 按需模块（tree-shakeable）。
 * 在 main.ts 挂载前调用一次即可；多次调用幂等。
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
  registered = true
}
