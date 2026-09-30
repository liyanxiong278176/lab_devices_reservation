import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'

const dashboard = vi.hoisted(() => ({ dashboardMe: vi.fn(), dashboardOverview: vi.fn() }))
const router = vi.hoisted(() => ({ push: vi.fn() }))
const messages = vi.hoisted(() => ({ success: vi.fn() }))
const spa = vi.hoisted(() => ({ readSpaDepth: vi.fn(() => 0) }))
vi.mock('@/api/dashboard', () => dashboard)
vi.mock('vue-router', () => ({ useRouter: () => router }))
vi.mock('@/router', () => spa)
vi.mock('element-plus', () => ({ ElMessage: messages }))
vi.mock('@/composables/useStagger', () => ({ useStagger: () => ({ reveal: vi.fn() }) }))
vi.mock('@/stores/notification', () => ({ useNotificationStore: () => ({ unread: 6 }) }))

import StudentDashboard from '../Student.vue'
import AdminDashboard from '../Admin.vue'

const dashboardStubs = {
  'el-row': { template: '<div class="el-row-stub"><slot /></div>' },
  'el-col': { template: '<div class="el-col-stub"><slot /></div>' },
  'el-radio-group': defineComponent({
    name: 'ElRadioGroupStub',
    props: ['modelValue'],
    emits: ['update:modelValue', 'change'],
    setup(_, { emit }) {
      return {
        handleClick(event: MouseEvent) {
          const button = (event.target as HTMLElement).closest('button')
          if (!button) return
          const rawValue = button.dataset.radioValue ?? ''
          const value = rawValue === '7' || rawValue === '30' ? Number(rawValue) : rawValue
          emit('update:modelValue', value)
          emit('change', value)
        },
      }
    },
    template: '<div class="el-radio-group-stub" @click="handleClick"><slot /></div>',
  }),
  'el-radio-button': {
    props: ['value'],
    template: '<button type="button" :data-radio-value="value"><slot /></button>',
  },
  BaseChart: true,
  PageHeader: { name: 'PageHeaderStub', props: ['title', 'subtitle'], template: '<header>{{ title }}<slot name="actions" /></header>' },
  StatCard: { name: 'StatCardStub', props: ['label', 'value'], template: '<div class="stat-card-stub" :data-label="label" :data-value="value" />' },
  PieWidget: { name: 'PieWidgetStub', props: ['title', 'data'], template: '<div class="pie-widget-stub" :data-title="title" :data-size="data.length" />' },
  BarWidget: { name: 'BarWidgetStub', props: ['title', 'data'], template: '<div class="bar-widget-stub" :data-title="title" :data-size="data.length" />' },
  LineWidget: { name: 'LineWidgetStub', props: ['title', 'data'], template: '<div class="line-widget-stub" :data-title="title" :data-size="data.length" />' },
  HeatmapWidget: { name: 'HeatmapWidgetStub', props: ['title', 'data'], template: '<div class="heatmap-widget-stub" :data-title="title" :data-size="data.length" />' },
  GlowCard: { name: 'GlowCardStub', template: '<div class="glow-card-stub"><slot /></div>' },
  'el-button': {
    inheritAttrs: false,
    template: '<button class="el-button-stub" @click="$emit(\'click\')"><slot /></button>',
  },
}

describe('student and administrator dashboard views', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    router.push.mockResolvedValue(undefined)
  })

  it('loads a student overview, maps chart inputs, and routes to booking actions', async () => {
    dashboard.dashboardMe.mockResolvedValue({
      myReservationsByStatus: { PENDING: 2, APPROVED: 1, UNKNOWN: 9 },
      myTrend30d: [{ date: '2026-09-28', count: 3 }],
      myCategoryDist: [{ categoryId: 1, categoryName: 'Optics', count: 4 }],
      unreadCount: 6,
      myRepairCount: 2,
    })
    const wrapper = mount(StudentDashboard, { global: { stubs: dashboardStubs, directives: { loading: () => {} } } })
    await flushPromises()

    expect(dashboard.dashboardMe).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('我的仪表盘')
    expect(wrapper.find('.stat-card-stub[data-label="未读通知"]').attributes('data-value')).toBe('6')
    expect(wrapper.find('.stat-card-stub[data-label="我的报修单"]').attributes('data-value')).toBe('2')
    expect(wrapper.findComponent({ name: 'PieWidgetStub' }).props('data')).toEqual([
      { name: '待审批', value: 2, color: expect.any(String) },
      { name: '已通过', value: 1, color: expect.any(String) },
    ])
    await wrapper.findAll('.dashboard-intro__actions button').at(0)?.trigger('click')
    await wrapper.findAll('.dashboard-intro__actions button').at(1)?.trigger('click')
    expect(router.push).toHaveBeenNthCalledWith(1, { name: 'devices' })
    expect(router.push).toHaveBeenNthCalledWith(2, { name: 'reservation-mine' })
  })

  it('swallows a student dashboard load error and always clears loading state', async () => {
    dashboard.dashboardMe.mockRejectedValue(new Error('offline'))
    const wrapper = mount(StudentDashboard, { global: { stubs: dashboardStubs, directives: { loading: () => {} } } })
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
  })

  it('loads admin metrics, formats chart values and refreshes', async () => {
    dashboard.dashboardOverview.mockResolvedValue({
      deviceStatus: { IDLE: 2, IN_USE: 1 },
      trend30d: [{ date: '2026-09-28', count: 5 }],
      utilization: [{ key: 'd1', label: 'scope', occupiedSlots: 2, availableSlots: 4, utilizationRate: 0.75 }],
      heatmap: [{ dayOfWeek: 2, hour: 3, count: 1 }],
      categoryDist: [{ categoryId: 1, categoryName: 'Optics', deviceCount: 7 }],
      repairStats: { PENDING: 2, RESOLVED: 1 },
      cards: { todayReservations: 3, pendingApprovals: 2, weeklyViolations: 1 },
    })
    const wrapper = mount(AdminDashboard, { global: { stubs: dashboardStubs, directives: { loading: () => {} } } })
    await flushPromises()

    expect(dashboard.dashboardOverview).toHaveBeenCalledWith({ groupBy: 'device', days: 30 })
    expect(wrapper.findAllComponents({ name: 'BarWidgetStub' })[0].props('data')).toEqual([{ name: 'scope', value: 75 }])
    expect(wrapper.findAllComponents({ name: 'PieWidgetStub' })[1].props('data')).toEqual([
      { name: 'Optics', value: 7 },
    ])
    await wrapper.get('.el-button-stub').trigger('click')
    await flushPromises()
    expect(dashboard.dashboardOverview).toHaveBeenCalledTimes(2)
    expect(messages.success).toHaveBeenCalledWith('已刷新')
    await wrapper.findAll('.dashboard-intro__actions button').at(0)?.trigger('click')
    await wrapper.findAll('.dashboard-intro__actions button').at(1)?.trigger('click')
    expect(router.push).toHaveBeenNthCalledWith(1, { name: 'approvals' })
    expect(router.push).toHaveBeenNthCalledWith(2, { name: 'devices-manage' })
  })

  it('handles admin metric failures and resets request state', async () => {
    dashboard.dashboardOverview.mockRejectedValue(new Error('offline'))
    const wrapper = mount(AdminDashboard, { global: { stubs: dashboardStubs, directives: { loading: () => {} } } })
    await flushPromises()
    expect(wrapper.exists()).toBe(true)
    expect(dashboard.dashboardOverview).toHaveBeenCalledOnce()
  })

  it('reloads admin metrics when aggregation or time range changes', async () => {
    dashboard.dashboardOverview.mockResolvedValue({
      deviceStatus: {},
      trend30d: [],
      utilization: [],
      heatmap: [],
      categoryDist: [],
      repairStats: {},
      cards: { todayReservations: 0, pendingApprovals: 0, weeklyViolations: 0 },
    })
    const wrapper = mount(AdminDashboard, { global: { stubs: dashboardStubs, directives: { loading: () => {} } } })
    await flushPromises()
    const groups = wrapper.findAllComponents({ name: 'ElRadioGroupStub' })

    await groups[0].findAll('button').at(1)?.trigger('click')
    await flushPromises()
    expect(dashboard.dashboardOverview).toHaveBeenLastCalledWith({ groupBy: 'category', days: 30 })

    await groups[1].findAll('button').at(0)?.trigger('click')
    await flushPromises()
    expect(dashboard.dashboardOverview).toHaveBeenLastCalledWith({ groupBy: 'category', days: 7 })
  })
})
