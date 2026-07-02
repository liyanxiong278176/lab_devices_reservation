import request from './request'

/**
 * 驾驶舱接口桩。S4 阶段实现 ECharts 富指标看板时补全字段。
 */
export const summary = () => request.get<unknown, unknown>('/dashboard/summary')
