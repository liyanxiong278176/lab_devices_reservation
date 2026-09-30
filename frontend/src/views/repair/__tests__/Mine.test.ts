import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  myRepairs: vi.fn(),
  confirmRepair: vi.fn(),
  confirm: vi.fn(),
  prompt: vi.fn(),
  success: vi.fn(),
  reveal: vi.fn(),
}))

vi.mock('@/api/repair', () => ({ myRepairs: mocks.myRepairs, confirmRepair: mocks.confirmRepair }))
vi.mock('element-plus', () => ({
  ElMessage: { success: mocks.success },
  ElMessageBox: { confirm: mocks.confirm, prompt: mocks.prompt },
}))
vi.mock('@/composables/useStagger', () => ({ useStagger: () => ({ reveal: mocks.reveal }) }))
vi.mock('@/router', () => ({ readSpaDepth: () => 0 }))

import Mine from '../Mine.vue'

const report = (id: number, status: string, overrides: Record<string, unknown> = {}) => ({
  id,
  deviceId: id + 100,
  deviceName: `设备-${id}`,
  reporterId: 7,
  title: `故障-${id}`,
  description: '运行时有异常声音',
  status,
  createdAt: '2026-09-28T10:30:00',
  ...overrides,
})

const reports = [
  report(1, 'PENDING', { deviceName: '', description: '', createdAt: undefined }),
  report(2, 'PROCESSING'),
  report(3, 'RESOLVED', { resolutionNote: '已更换电源模块', resolvedAt: '2026-09-28T11:00:00' }),
  report(4, 'REJECTED', { resolutionNote: '', resolvedAt: undefined }),
  report(5, 'COMPLETED', { resolutionNote: '校准完成', userConfirmationNote: '确认正常', closedAt: '2026-09-28T12:00:00' }),
  report(6, 'COMPLETED', { resolutionNote: '', userConfirmationNote: '', closedAt: undefined }),
  report(7, 'REJECTED', { resolutionNote: '供电接口损坏' }),
]

const page = (records = reports, extras: Record<string, unknown> = {}) => ({
  records, total: records.length, size: 9, current: 1, pages: 1, truncated: false, ...extras,
})

const stubs = {
  PageHeader: { props: ['title', 'subtitle'], template: '<header><h1>{{ title }}</h1><span>{{ subtitle }}</span></header>' },
  GlowCard: { template: '<article class="card"><slot /></article>' },
  Tag: { props: ['variant'], template: '<span class="tag" :data-variant="variant"><slot /></span>' },
  Timeline: {
    props: ['items'],
    template: '<ol class="timeline"><li v-for="item in items" :key="item.id" :data-status="item.status">{{ item.title }} {{ item.desc }} {{ item.time }}</li></ol>',
  },
  GhostButton: { emits: ['click'], template: '<button class="ghost" @click="$emit(\'click\', $event)"><slot /></button>' },
  TextButton: { emits: ['click'], template: '<button class="text" @click="$emit(\'click\', $event)"><slot /></button>' },
  EmptyState: { props: ['title', 'description'], template: '<div class="empty"><strong>{{ title }}</strong><span>{{ description }}</span></div>' },
  PageDepthNotice: { props: ['total'], template: '<div class="depth">{{ total }}</div>' },
  'el-pagination': {
    props: ['currentPage', 'pageSize', 'total'],
    emits: ['current-change', 'size-change'],
    template: '<div class="pagination"><button @click="$emit(\'current-change\', 3)">3</button><button @click="$emit(\'size-change\', 18)">18</button></div>',
  },
}

function mountPage() {
  return mount(Mine, { global: { stubs, directives: { loading: { mounted() {}, updated() {} } } } })
}

const setupOf = (wrapper: ReturnType<typeof mount>) =>
  (wrapper.vm as unknown as { $: { setupState: Record<string, unknown> } }).$.setupState

describe('my repair reports page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.myRepairs.mockResolvedValue(page())
    mocks.confirmRepair.mockResolvedValue(undefined)
    mocks.confirm.mockResolvedValue(undefined)
    mocks.prompt.mockResolvedValue({ value: '  设备仍无法启动  ' })
  })

  it('renders repair status cards, notes, fallback fields and timeline progress', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(mocks.myRepairs).toHaveBeenCalledWith(1, 9)
    expect(wrapper.text()).toContain('共 7 条报修')
    expect(wrapper.text()).toContain('设备 #101')
    expect(wrapper.text()).toContain('管理员驳回报修')
    expect(wrapper.text()).toContain('已处理')
    expect(wrapper.text()).toContain('确认正常')
    expect(wrapper.findAll('.rmine__cell')).toHaveLength(7)
    expect(wrapper.findAll('.timeline')).toHaveLength(7)
    expect(wrapper.findAll('.tag').map((tag) => tag.attributes('data-variant'))).toEqual([
      'warning', 'accent', 'warning', 'danger', 'success', 'success', 'danger',
    ])
    expect(wrapper.findAll('.rmine__card-actions .ghost')).toHaveLength(1)
    expect(wrapper.findAll('.rmine__card-actions .text')).toHaveLength(1)
    expect(mocks.reveal).toHaveBeenCalled()
  })

  it('covers timeline and label fallbacks and handles empty or failed loads', async () => {
    mocks.myRepairs.mockResolvedValueOnce(page([], { total: 0 }))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('.empty').text()).toContain('暂无报修记录')
    expect(wrapper.find('.rmine__pager').exists()).toBe(false)

    const setup = setupOf(wrapper)
    const statusVariant = setup.statusVariant as (status: string) => string
    const statusLabel = setup.statusLabel as (status: string) => string
    const buildTimeline = setup.buildTimeline as (row: ReturnType<typeof report>) => { title: string; status: string }[]
    expect(statusVariant('UNKNOWN')).toBe('accent')
    expect(statusLabel('UNKNOWN')).toBe('UNKNOWN')
    expect(buildTimeline(report(8, 'REJECTED', { resolutionNote: '原因', resolvedAt: '2026-09-28T14:00:00' }))).toEqual([
      expect.objectContaining({ title: '提交报修', status: 'done' }),
      expect.objectContaining({ title: '已驳回', status: 'done' }),
    ])
    expect(buildTimeline(report(12, 'RESOLVED', { resolutionNote: '', resolvedAt: undefined }))[3]).toMatchObject({
      title: '待用户确认', desc: '故障已修复', time: undefined,
    })
    expect(buildTimeline(report(13, 'COMPLETED', { resolutionNote: '', userConfirmationNote: '', closedAt: undefined }))[3]).toMatchObject({
      title: '已完成', desc: '用户已确认设备恢复正常', time: undefined,
    })
    expect(buildTimeline(report(9, 'PROCESSING'))[2]).toMatchObject({ title: '处理中', status: 'current' })
    expect(buildTimeline(report(10, 'PENDING'))[1]).toMatchObject({ title: '等待受理', status: 'current' })

    mocks.myRepairs.mockRejectedValueOnce(new Error('network unavailable'))
    await (setup.load as () => Promise<void>)()
    expect(mocks.reveal).toHaveBeenCalled()
  })

  it('changes page and size, shows truncated guidance, and uses the page fallback limit', async () => {
    mocks.myRepairs.mockResolvedValueOnce(page([report(11, 'PENDING')], { total: 120, truncated: true, pages: 0 }))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('.depth').text()).toBe('120')

    await wrapper.findAll('.pagination button')[0].trigger('click')
    await flushPromises()
    expect(mocks.myRepairs).toHaveBeenLastCalledWith(3, 9)
    await wrapper.findAll('.pagination button')[1].trigger('click')
    await flushPromises()
    expect(mocks.myRepairs).toHaveBeenLastCalledWith(1, 18)
  })

  it('confirms repair completion, handles dismissal and API failure', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('.rmine__card-actions .text').trigger('click')
    await flushPromises()
    expect(mocks.confirm).toHaveBeenCalledWith('确认设备已经恢复正常并关闭这条报修？', '确认维修结果', expect.any(Object))
    expect(mocks.confirmRepair).toHaveBeenCalledWith(3, true, undefined)
    expect(mocks.success).toHaveBeenCalledWith('报修已完成')

    mocks.confirm.mockRejectedValueOnce(new Error('user chose later'))
    await wrapper.find('.rmine__card-actions .text').trigger('click')
    await flushPromises()
    expect(mocks.confirmRepair).toHaveBeenCalledTimes(1)

    mocks.confirmRepair.mockRejectedValueOnce(new Error('server failure'))
    await wrapper.find('.rmine__card-actions .text').trigger('click')
    await flushPromises()
    expect(mocks.confirmRepair).toHaveBeenCalledTimes(2)
  })

  it('returns resolved repairs with a trimmed issue note and handles prompt cancellation', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('.rmine__card-actions .ghost').trigger('click')
    await flushPromises()
    expect(mocks.prompt).toHaveBeenCalledWith('请说明仍存在的问题，管理员会重新处理。', '退回处理', expect.any(Object))
    expect(mocks.confirmRepair).toHaveBeenCalledWith(3, false, '设备仍无法启动')
    expect(mocks.success).toHaveBeenCalledWith('已退回管理员处理')

    mocks.prompt.mockRejectedValueOnce(new Error('user cancelled prompt'))
    await wrapper.find('.rmine__card-actions .ghost').trigger('click')
    await flushPromises()
    expect(mocks.confirmRepair).toHaveBeenCalledTimes(1)
  })
})
