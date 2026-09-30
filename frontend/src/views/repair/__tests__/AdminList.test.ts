import { defineComponent, h, type VNode } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  listRepairs: vi.fn(),
  takeRepair: vi.fn(),
  resolveRepair: vi.fn(),
  rejectRepair: vi.fn(),
  loadUnread: vi.fn(),
  success: vi.fn(),
  warning: vi.fn(),
}))

vi.mock('@/api/repair', () => ({
  listRepairs: mocks.listRepairs,
  takeRepair: mocks.takeRepair,
  resolveRepair: mocks.resolveRepair,
  rejectRepair: mocks.rejectRepair,
}))
vi.mock('@/stores/notification', () => ({ useNotificationStore: () => ({ loadUnread: mocks.loadUnread }) }))
vi.mock('element-plus', () => ({ ElMessage: { success: mocks.success, warning: mocks.warning } }))
vi.mock('@/router', () => ({ readSpaDepth: () => 0 }))

import AdminList from '../AdminList.vue'

const repair = (id: number, status: string, overrides: Record<string, unknown> = {}) => ({
  id,
  deviceId: id + 100,
  deviceName: `设备-${id}`,
  reporterId: 7,
  reporterName: `学生-${id}`,
  title: `故障-${id}`,
  description: `故障描述-${id}`,
  status,
  createdAt: '2026-09-28T10:00:00',
  ...overrides,
})

const repairs = [
  repair(1, 'PENDING'),
  repair(2, 'PROCESSING'),
  repair(3, 'RESOLVED', { resolutionNote: '已更换零件' }),
  repair(4, 'COMPLETED', { resolutionNote: '已完成维修' }),
  repair(5, 'REJECTED', { resolutionNote: '缺少设备编号' }),
]
const page = (records = repairs, extras: Record<string, unknown> = {}) => ({
  records, total: records.length, size: 10, current: 1, pages: 1, truncated: false, ...extras,
})

const TableStub = defineComponent({
  props: ['data'],
  setup(props, { slots }) {
    return () => {
      if (!props.data?.length) return h('div', { class: 'table-empty' }, slots.empty?.() as VNode[] | undefined)
      const columns = (slots.default?.() ?? []) as VNode[]
      return h('div', { class: 'table-stub' }, props.data.map((row: Record<string, unknown>) =>
        h('div', { class: 'table-row', 'data-row-id': row.id, key: String(row.id) }, columns.map((column, index) => {
          const childSlots = column.children as { default?: (slotProps: { row: Record<string, unknown> }) => unknown } | null
          if (typeof childSlots?.default === 'function') {
            return h(
              'div',
              { class: `table-cell table-cell-${index}`, key: index },
              childSlots.default({ row }) as VNode | VNode[] | string | undefined,
            )
          }
          const columnProps = column.props as { prop?: string } | null
          return h('div', { class: `table-cell table-cell-${index}`, key: index }, String(row[columnProps?.prop ?? ''] ?? ''))
        })),
      ))
    }
  },
})

const stubs = {
  PageHeader: { props: ['title', 'subtitle'], template: '<header><h1>{{ title }}</h1><span>{{ subtitle }}</span></header>' },
  SegmentedControl: {
    props: ['modelValue', 'options'],
    emits: ['update:modelValue'],
    template: '<div class="segments"><button v-for="option in options" :key="option.value" @click="$emit(\'update:modelValue\', option.value)">{{ option.label }}</button></div>',
  },
  Tag: { props: ['variant'], template: '<span class="tag" :data-variant="variant"><slot /></span>' },
  TextButton: { emits: ['click'], template: '<button class="text" :class="$attrs.class" @click="$emit(\'click\', $event)"><slot /></button>' },
  GhostButton: { emits: ['click'], template: '<button class="ghost" @click="$emit(\'click\', $event)"><slot /></button>' },
  GradientButton: { props: ['loading'], emits: ['click'], template: '<button class="gradient" :disabled="loading" @click="$emit(\'click\', $event)"><slot /></button>' },
  PageDepthNotice: { props: ['total'], template: '<div class="depth">{{ total }}</div>' },
  'el-table': TableStub,
  'el-table-column': true,
  'el-pagination': {
    emits: ['current-change', 'size-change'],
    template: '<div class="pagination"><button @click="$emit(\'current-change\', 3)">3</button><button @click="$emit(\'size-change\', 20)">20</button></div>',
  },
  'el-drawer': {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template: '<aside v-if="modelValue" class="drawer"><button class="drawer-close" @click="$emit(\'update:modelValue\', false)">close</button><slot /></aside>',
  },
  'el-form': { template: '<form><slot /></form>' },
  'el-form-item': { props: ['label'], template: '<label><span>{{ label }}</span><slot /></label>' },
  'el-input': { props: ['modelValue', 'placeholder'], emits: ['update:modelValue'], template: '<textarea :placeholder="placeholder" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
}

function mountPage() {
  return mount(AdminList, {
    global: { stubs, directives: { loading: { mounted() {}, updated() {} }, permission: { mounted() {}, updated() {} } } },
  })
}

const setupOf = (wrapper: ReturnType<typeof mount>) =>
  (wrapper.vm as unknown as { $: { setupState: Record<string, unknown> } }).$.setupState

describe('repair administration page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.listRepairs.mockResolvedValue(page())
    mocks.takeRepair.mockResolvedValue(undefined)
    mocks.resolveRepair.mockResolvedValue(undefined)
    mocks.rejectRepair.mockResolvedValue(undefined)
    mocks.loadUnread.mockResolvedValue(undefined)
  })

  it('renders status filters, actions and repair details across the status matrix', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(mocks.listRepairs).toHaveBeenCalledWith('', 1, 10)
    expect(wrapper.text()).toContain('共 5 条工单')
    expect(wrapper.findAll('.table-row')).toHaveLength(5)
    expect(wrapper.findAll('.tag').map((tag) => tag.attributes('data-variant'))).toEqual([
      'warning', 'accent', 'warning', 'success', 'danger',
    ])
    expect(wrapper.findAll('.radmin__table .text').map((button) => button.text())).toEqual(['受理', '驳回', '解决'])
    expect(wrapper.text()).toContain('故障-1')

    const setup = setupOf(wrapper)
    expect((setup.statusVariant as (status: string) => string)('UNKNOWN')).toBe('accent')
    expect((setup.statusLabel as (status: string) => string)('UNKNOWN')).toBe('UNKNOWN')
    expect((setup.fmt as (value?: string) => string)()).toBe('—')
  })

  it('filters and paginates, shows truncation guidance, and displays the empty state', async () => {
    mocks.listRepairs.mockResolvedValueOnce(page([repair(8, 'PENDING')], { total: 501, pages: 0, truncated: true }))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('.depth').text()).toBe('501')

    await wrapper.find('.segments').findAll('button').find((button) => button.text() === '处理中')!.trigger('click')
    await flushPromises()
    expect(mocks.listRepairs).toHaveBeenLastCalledWith('PROCESSING', 1, 10)
    await wrapper.findAll('.pagination button')[0].trigger('click')
    await flushPromises()
    expect(mocks.listRepairs).toHaveBeenLastCalledWith('PROCESSING', 3, 10)
    await wrapper.findAll('.pagination button')[1].trigger('click')
    await flushPromises()
    expect(mocks.listRepairs).toHaveBeenLastCalledWith('PROCESSING', 1, 20)

    mocks.listRepairs.mockResolvedValueOnce(page([]))
    await wrapper.find('.segments').findAll('button').find((button) => button.text() === '全部')!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.table-empty').text()).toContain('暂无报修工单')
  })

  it('accepts pending repairs and refreshes unread notifications, with recovery after failure', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.findAll('.table-row')[0].find('.text').trigger('click')
    await flushPromises()
    expect(mocks.takeRepair).toHaveBeenCalledWith(1)
    expect(mocks.success).toHaveBeenCalledWith('已受理')
    expect(mocks.loadUnread).toHaveBeenCalledOnce()

    mocks.takeRepair.mockRejectedValueOnce(new Error('take failed'))
    await wrapper.findAll('.table-row')[0].find('.text').trigger('click')
    await flushPromises()
    expect(mocks.loadUnread).toHaveBeenCalledOnce()
  })

  it('validates and resolves a repair, trims notes, and preserves the drawer after API failure', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.findAll('.table-row')[1].find('.text').trigger('click')
    expect(wrapper.find('.drawer').text()).toContain('解决报修')
    expect(wrapper.find('.drawer').text()).toContain('故障描述-2')
    expect(wrapper.find('textarea').attributes('placeholder')).toContain('处理方式')

    await wrapper.find('.drawer .gradient').trigger('click')
    expect(mocks.warning).toHaveBeenCalledWith('请填写处理说明')
    await wrapper.find('textarea').setValue('  已重启并更换电缆  ')
    await wrapper.find('.drawer .gradient').trigger('click')
    await flushPromises()
    expect(mocks.resolveRepair).toHaveBeenCalledWith(2, '已重启并更换电缆')
    expect(mocks.success).toHaveBeenCalledWith('已标记解决，等待用户确认')
    expect(mocks.loadUnread).toHaveBeenCalledOnce()
    expect(wrapper.find('.drawer').exists()).toBe(false)

    await wrapper.findAll('.table-row')[1].find('.text').trigger('click')
    await wrapper.find('textarea').setValue('已校准')
    mocks.resolveRepair.mockRejectedValueOnce(new Error('resolve failed'))
    await wrapper.find('.drawer .gradient').trigger('click')
    await flushPromises()
    expect(wrapper.find('.drawer').exists()).toBe(true)
  })

  it('rejects with a required reason, closes on cancel and handles failures', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.findAll('.table-row')[0].find('.radmin__reject').trigger('click')
    expect(wrapper.find('.drawer').text()).toContain('驳回报修')
    expect(wrapper.find('.drawer').text()).toContain('驳回理由')
    await wrapper.find('.drawer .gradient').trigger('click')
    expect(mocks.warning).toHaveBeenCalledWith('请填写驳回理由')

    await wrapper.find('textarea').setValue('设备不在本实验室范围内')
    await wrapper.find('.drawer .ghost').trigger('click')
    expect(wrapper.find('.drawer').exists()).toBe(false)
    await wrapper.findAll('.table-row')[0].find('.radmin__reject').trigger('click')
    await wrapper.find('textarea').setValue('设备不在本实验室范围内')
    await wrapper.find('.drawer .gradient').trigger('click')
    await flushPromises()
    expect(mocks.rejectRepair).toHaveBeenCalledWith(1, '设备不在本实验室范围内')
    expect(mocks.success).toHaveBeenCalledWith('已驳回')

    await wrapper.findAll('.table-row')[0].find('.radmin__reject').trigger('click')
    await wrapper.find('.drawer-close').trigger('click')
    expect(wrapper.find('.drawer').exists()).toBe(false)

    await wrapper.findAll('.table-row')[0].find('.radmin__reject').trigger('click')
    await wrapper.find('textarea').setValue('归属不明')
    mocks.rejectRepair.mockRejectedValueOnce(new Error('reject failed'))
    await wrapper.find('.drawer .gradient').trigger('click')
    await flushPromises()
    expect(wrapper.find('.drawer').exists()).toBe(true)
  })

  it('recovers from a failed list load and renders safe fallbacks for incomplete repair details', async () => {
    mocks.listRepairs.mockRejectedValueOnce(new Error('list failed'))
    const wrapper = mountPage()
    await flushPromises()

    const setup = setupOf(wrapper)
    ;(setup.onTabChange as (value: string | number | null) => void)(null)
    await flushPromises()
    expect(mocks.listRepairs).toHaveBeenLastCalledWith('', 1, 10)

    mocks.listRepairs.mockResolvedValueOnce(page([
      repair(9, 'PENDING', { deviceName: '', reporterName: '', description: '', createdAt: undefined }),
    ]))
    ;(setup.onPageChange as (value: number) => void)(2)
    await flushPromises()
    await wrapper.find('.radmin__reject').trigger('click')
    expect(wrapper.find('.drawer').text()).toContain('设备 #109')
    expect(wrapper.find('.drawer').text()).toContain('报修人—')
    expect(wrapper.find('.drawer').text()).toContain('报修人未填写详细描述。')
    expect(wrapper.find('.drawer').text()).toContain('提交时间—')

    await wrapper.find('.radmin__drawer-close').trigger('click')
    expect(wrapper.find('.drawer').exists()).toBe(false)
    setup.handleTarget = null
    await (setup.onHandleConfirm as () => Promise<void>)()
    expect(mocks.rejectRepair).not.toHaveBeenCalled()
  })
})
