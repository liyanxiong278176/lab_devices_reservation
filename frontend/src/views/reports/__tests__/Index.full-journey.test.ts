import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const api = vi.hoisted(() => ({
  createReportExport: vi.fn(),
  downloadReport: vi.fn(),
  downloadReportExport: vi.fn(),
  getReportExport: vi.fn(),
  getReportSummary: vi.fn(),
}))
const messages = vi.hoisted(() => ({ warning: vi.fn(), success: vi.fn(), error: vi.fn() }))
vi.mock('@/api/reports', () => api)
vi.mock('element-plus', () => ({ ElMessage: messages }))

import ReportsIndex from '../Index.vue'

function summary() {
  return {
    range: { startDate: '2026-09-01', endDate: '2026-09-28' },
    deviceCount: 8,
    reservationCount: 20,
    reservationStatus: {
      PENDING: 1, APPROVED: 2, IN_USE: 3, COMPLETED: 4, CANCELLED: 5,
      REJECTED: 6, NO_SHOW: 7, VIOLATED: 8, CUSTOM_STATE: 9,
    },
    repairCount: 4,
    repairStatus: { PROCESSING: 2, RESOLVED: 1, CUSTOM_REPAIR: 1 },
    utilizationRate: 0.5,
    occupancyRate: 0.375,
    actualUsageRate: 0.25,
    bookableDeviceDays: 100,
    occupiedDeviceDays: 38,
    actualUsageDeviceDays: 25,
    maintenanceDowntimeDays: 6,
    averageApprovalHours: 2.75,
    waitlistRequests: 10,
    waitlistConverted: 4,
    waitlistConversionRate: 0.4,
    noShowRate: 0.05,
    violationRate: 0.025,
  }
}

const stubs = {
  PageHeader: { props: ['title'], template: '<header>{{ title }}<slot /></header>' },
  GlowCard: { template: '<article class="glow-card-stub"><slot /></article>' },
  GradientButton: { props: ['loading'], emits: ['click'], template: '<button class="gradient-button" :disabled="loading" @click="$emit(\'click\')"><slot /></button>' },
  GhostButton: { props: ['loading'], emits: ['click'], template: '<button class="ghost-button" :disabled="loading" @click="$emit(\'click\')"><slot /></button>' },
  TextButton: { emits: ['click'], template: '<button class="text-button" @click="$emit(\'click\')"><slot /></button>' },
  Tag: { template: '<span class="tag-stub"><slot /></span>' },
}

function mountPage(onError?: (error: unknown) => void) {
  return mount(ReportsIndex, {
    global: {
      stubs,
      directives: { loading: () => {} },
      config: { errorHandler: onError },
    },
  })
}

async function settledPage(onError?: (error: unknown) => void) {
  const wrapper = mountPage(onError)
  await flushPromises()
  return wrapper
}

describe('operations report and export full user journeys', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useRealTimers()
    api.getReportSummary.mockResolvedValue(summary())
    api.downloadReport.mockResolvedValue(undefined)
    api.createReportExport.mockResolvedValue({ id: 45, export_type: 'devices', status: 'PENDING', row_count: 0 })
    api.getReportExport.mockResolvedValue({ id: 45, export_type: 'devices', status: 'PROCESSING', row_count: 0 })
    api.downloadReportExport.mockResolvedValue(undefined)
  })

  it('loads and presents summary metrics, known statuses, and unknown status names', async () => {
    const wrapper = await settledPage()
    expect(api.getReportSummary).toHaveBeenCalledWith(expect.objectContaining({ startDate: expect.any(String), endDate: expect.any(String) }))
    expect(wrapper.findAll('.report-metric')).toHaveLength(9)
    expect(wrapper.text()).toContain('预约占用率37.5%')
    expect(wrapper.text()).toContain('实际使用率25.0%')
    expect(wrapper.text()).toContain('平均审批耗时2.8小时')
    expect(wrapper.text()).toContain('待处理')
    expect(wrapper.text()).toContain('已通过')
    expect(wrapper.text()).toContain('使用中')
    expect(wrapper.text()).toContain('已完成')
    expect(wrapper.text()).toContain('已取消')
    expect(wrapper.text()).toContain('已拒绝')
    expect(wrapper.text()).toContain('爽约')
    expect(wrapper.text()).toContain('违规')
    expect(wrapper.text()).toContain('处理中')
    expect(wrapper.text()).toContain('待确认')
    expect(wrapper.text()).toContain('CUSTOM_STATE')
    expect(wrapper.text()).toContain('CUSTOM_REPAIR')
  })

  it('rejects an inverted date interval before requesting refreshed statistics', async () => {
    const wrapper = await settledPage()
    const initialRequestCount = api.getReportSummary.mock.calls.length
    await wrapper.get('#report-start').setValue('2026-09-15')
    await wrapper.get('#report-end').setValue('2026-09-14')
    await wrapper.get('.reports-page__toolbar .gradient-button').trigger('click')

    expect(messages.warning).toHaveBeenCalledWith('请选择有效的日期范围')
    expect(api.getReportSummary).toHaveBeenCalledTimes(initialRequestCount)
  })

  it('shows the empty state after a summary request fails and can recover on refresh', async () => {
    api.getReportSummary.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce(summary())
    const wrapper = await settledPage()
    expect(wrapper.find('.reports-page__empty').exists()).toBe(true)
    await wrapper.get('.reports-page__toolbar .gradient-button').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.report-metric')).toHaveLength(9)
    expect(wrapper.find('.reports-page__empty').exists()).toBe(false)
  })

  it('supports direct CSV export success and falls back silently when the synchronous threshold is exceeded', async () => {
    const wrapper = await settledPage()
    const rows = wrapper.findAll('.reports-page__export-item')
    await rows[0].find('.ghost-button').trigger('click')
    await flushPromises()
    expect(api.downloadReport).toHaveBeenCalledWith('devices', expect.any(Object))
    expect(messages.success).toHaveBeenCalledWith('报表已下载')

    api.downloadReport.mockRejectedValueOnce(new Error('too large'))
    await rows[1].find('.ghost-button').trigger('click')
    await flushPromises()
    expect(api.downloadReport).toHaveBeenLastCalledWith('reservations', expect.any(Object))
    expect(messages.success).toHaveBeenCalledTimes(1)
  })

  it('polls an asynchronous export through completion and downloads the completed file', async () => {
    vi.useFakeTimers()
    api.getReportExport
      .mockResolvedValueOnce({ id: 45, export_type: 'devices', status: 'PROCESSING', row_count: 0 })
      .mockResolvedValueOnce({ id: 45, export_type: 'devices', status: 'COMPLETED', row_count: 28 })
    const wrapper = await settledPage()
    const exportButton = wrapper.findAll('.reports-page__export-item')[0].find('.gradient-button')
    await exportButton.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('处理中')
    expect(api.createReportExport).toHaveBeenCalledWith('devices', expect.any(Object))

    await vi.advanceTimersByTimeAsync(1200)
    await flushPromises()
    expect(wrapper.text()).toContain('任务 #45 · 28 行')
    expect(wrapper.find('.reports-page__task .text-button').exists()).toBe(true)
    await wrapper.get('.reports-page__task .text-button').trigger('click')
    await flushPromises()
    expect(api.downloadReportExport).toHaveBeenCalledWith(45, 'devices')
    expect(messages.success).toHaveBeenCalledWith('异步报表已生成')
    expect(messages.success).toHaveBeenCalledWith('报表已下载')
  })

  it('surfaces failed export messages and uses a fallback when the server omits an error', async () => {
    api.getReportExport.mockResolvedValue({ id: 45, export_type: 'repairs', status: 'FAILED', row_count: 0, error: '' })
    const wrapper = await settledPage()
    await wrapper.findAll('.reports-page__export-item')[2].find('.gradient-button').trigger('click')
    await flushPromises()
    expect(messages.error).toHaveBeenCalledWith('异步报表生成失败')
    expect(wrapper.find('.reports-page__task .text-button').exists()).toBe(false)
  })

  it('stops polling after a status request fails and clears a pending timer on unmount', async () => {
    vi.useFakeTimers()
    api.getReportExport.mockRejectedValueOnce(new Error('poll failed'))
    const wrapper = await settledPage()
    await wrapper.findAll('.reports-page__export-item')[0].find('.gradient-button').trigger('click')
    await flushPromises()
    expect(api.getReportExport).toHaveBeenCalledOnce()
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(5000)
    expect(api.getReportExport).toHaveBeenCalledOnce()

    api.getReportExport.mockResolvedValue({ id: 45, export_type: 'devices', status: 'PROCESSING', row_count: 0 })
    const pending = await settledPage()
    await pending.findAll('.reports-page__export-item')[0].find('.gradient-button').trigger('click')
    await flushPromises()
    pending.unmount()
    await vi.advanceTimersByTimeAsync(5000)
    expect(api.getReportExport).toHaveBeenCalledTimes(2)
  })

  it('always clears the export indicator when task creation fails and ignores ineligible downloads', async () => {
    const errors: unknown[] = []
    const wrapper = await settledPage((error) => errors.push(error))
    const state = (wrapper.vm as any).$.setupState as Record<string, any>
    state.task = null
    await state.downloadTask()
    state.task = { id: 45, export_type: 'devices', status: 'PROCESSING', row_count: 0 }
    await state.downloadTask()
    expect(api.downloadReportExport).not.toHaveBeenCalled()

    api.createReportExport.mockRejectedValueOnce(new Error('create failed'))
    await expect(state.asyncExport('devices')).rejects.toThrow('create failed')
    expect(state.exporting).toBe(null)
    expect(errors).toHaveLength(0)
  })
})
