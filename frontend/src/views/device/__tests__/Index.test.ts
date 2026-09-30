import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import type { DeviceVO } from '@/types/device'

const mocks = vi.hoisted(() => ({
  searchDevices: vi.fn(),
  getDevice: vi.fn(),
  push: vi.fn(),
  reveal: vi.fn(),
}))

vi.mock('@/api/device', () => ({
  searchDevices: mocks.searchDevices,
  getDevice: mocks.getDevice,
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: mocks.push }) }))
vi.mock('@/composables/useStagger', () => ({ useStagger: () => ({ reveal: mocks.reveal }) }))
vi.mock('@/components/ui/PageHeader.vue', () => ({
  default: { props: ['title', 'subtitle'], template: '<header>{{ title }} {{ subtitle }}</header>' },
}))

import DeviceIndex from '../Index.vue'

const firstDevice = {
  id: 1,
  name: '工作站 A',
  categoryId: 10,
  brand: 'Maker',
  model: 'X1',
  status: 'IDLE',
  needApproval: 1,
  maxReservationDays: 4,
  imageUrl: '/a.png',
  specs: '32G RAM',
  labName: '一号实验室',
  labId: 1,
  categoryName: '计算设备',
  assetCode: 'ASSET-1',
  maintenanceWarning: '',
} as DeviceVO

const secondDevice = {
  id: 2,
  name: '显微镜 B',
  categoryId: null,
  brand: '',
  model: '',
  status: 'MAINTENANCE',
  needApproval: 0,
  maxReservationDays: undefined,
  imageUrl: '',
  specs: '',
  labName: '',
  labId: null,
  categoryName: '',
  assetCode: '',
  maintenanceWarning: '定期维护中',
} as DeviceVO

const page = (records: DeviceVO[] = [firstDevice, secondDevice], overrides: Record<string, unknown> = {}) => ({
  records,
  total: records.length,
  size: 24,
  current: 1,
  pages: 1,
  truncated: false,
  ...overrides,
})

const stubs = {
  PageHeader: { props: ['title', 'subtitle'], template: '<header>{{ title }} {{ subtitle }}</header>' },
  SegmentedControl: {
    props: ['modelValue', 'options'],
    emits: ['update:modelValue'],
    template: '<div><button v-for="option in options" :key="option.value" @click="$emit(\'update:modelValue\', option.value)">{{ option.label }}</button></div>',
  },
  GlowCard: {
    emits: ['click'],
    template: '<article class="glow-card" @click="$emit(\'click\')"><slot /></article>',
  },
  StatusDot: { template: '<span class="status-dot"><slot /></span>' },
  Tag: { template: '<span class="tag"><slot /></span>' },
  TextButton: {
    props: ['disabled'],
    emits: ['click'],
    template: '<button class="text-button" :disabled="disabled" @click="$emit(\'click\', $event)"><slot /></button>',
  },
  EmptyState: { props: ['title'], template: '<div class="empty-state">{{ title }}</div>' },
  PageDepthNotice: { props: ['total'], template: '<div class="depth-notice">{{ total }}</div>' },
  PageSizeControl: {
    name: 'PageSizeControl',
    props: ['modelValue', 'options'],
    emits: ['change'],
    template: '<button class="page-size" @click="$emit(\'change\', 48)">page size</button>',
  },
  'el-input': {
    props: ['modelValue'],
    emits: ['update:modelValue', 'keyup', 'clear'],
    template: '<input class="keyword" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" @keyup.enter="$emit(\'keyup\', $event)" />',
  },
  'el-pagination': {
    name: 'PaginationStub',
    props: ['currentPage', 'pageSize', 'total'],
    emits: ['current-change', 'size-change'],
    template: '<div class="pagination"><button @click="$emit(\'current-change\', 3)">next</button><button @click="$emit(\'size-change\', 48)">resize</button></div>',
  },
  'el-drawer': {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template: '<aside v-if="modelValue"><button class="drawer-update" @click="$emit(\'update:modelValue\', false)"></button><slot /></aside>',
  },
  'el-alert': { props: ['title'], template: '<div class="alert">{{ title }}</div>' },
  'el-button': {
    props: ['disabled'],
    emits: ['click'],
    template: '<button class="primary-button" :disabled="disabled" @click="$emit(\'click\', $event)"><slot /></button>',
  },
  Cpu: { template: '<span>cpu</span>' },
  Search: { template: '<span>search</span>' },
}

describe('device browse page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.searchDevices.mockResolvedValue(page())
    mocks.getDevice.mockResolvedValue({ ...firstDevice, description: '详细设备说明' })
  })

  it('loads and renders cards, conditional content, filtering controls, and empty state', async () => {
    const wrapper = mount(DeviceIndex, {
      global: {
        stubs,
        directives: { loading: { mounted() {}, updated() {} } },
      },
    })
    await flushPromises()

    expect(mocks.searchDevices).toHaveBeenCalledWith(expect.objectContaining({ page: 1, size: 24 }))
    expect(wrapper.text()).toContain('共 2 台设备')
    expect(wrapper.text()).toContain('工作站 A')
    expect(wrapper.text()).toContain('定期维护中')
    expect(wrapper.findAll('.device-cell')).toHaveLength(2)
    expect(wrapper.findAll('img')).toHaveLength(1)

    await wrapper.find('.device-cell .text-button').trigger('click')
    await flushPromises()
    expect(mocks.push).toHaveBeenCalledWith({ name: 'reservation-create', query: { deviceId: '1' } })

    await wrapper.find('.device-page__filter-right .text-button').trigger('click')
    await flushPromises()
    await wrapper.find('.keyword').setValue('实验')
    await wrapper.find('.keyword').trigger('keyup.enter')
    await wrapper.findAll('button').find((button) => button.text() === '空闲')!.trigger('click')
    await wrapper.find('.page-size').trigger('click')
    await wrapper.find('.pagination button').trigger('click')
    await wrapper.findAll('.pagination button')[1].trigger('click')
    await flushPromises()
    expect(mocks.searchDevices).toHaveBeenCalledWith(expect.objectContaining({ keyword: '实验' }))
    expect(mocks.searchDevices).toHaveBeenCalledWith(expect.objectContaining({ status: 'IDLE' }))

    mocks.searchDevices.mockResolvedValueOnce(page([]))
    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(wrapper.find('.empty-state').text()).toContain('未找到匹配的设备')
  })

  it('opens a selected detail, navigates to full detail, and keeps list data after detail failure', async () => {
    const wrapper = mount(DeviceIndex, {
      global: {
        stubs,
        directives: { loading: { mounted() {}, updated() {} } },
      },
    })
    await flushPromises()
    await wrapper.find('.glow-card').trigger('click')
    await flushPromises()

    expect(mocks.getDevice).toHaveBeenCalledWith(1)
    expect(wrapper.find('aside').text()).toContain('详细设备说明')
    await wrapper.find('aside .text-button').trigger('click')
    expect(mocks.push).toHaveBeenCalledWith({ name: 'device-detail', params: { id: 1 } })
    await wrapper.find('.primary-button').trigger('click')
    expect(mocks.push).toHaveBeenLastCalledWith({ name: 'reservation-create', query: { deviceId: '1' } })

    mocks.getDevice.mockRejectedValueOnce(new Error('network unavailable'))
    await wrapper.findAll('.glow-card')[1].trigger('click')
    await flushPromises()
    expect(wrapper.find('aside').text()).toContain('显微镜 B')
    expect(wrapper.find('aside').text()).toContain('定期维护中')
    await wrapper.find('.drawer-update').trigger('click')
    expect(wrapper.find('aside').exists()).toBe(false)

    await wrapper.findAll('.glow-card')[0].trigger('click')
    await flushPromises()
    await wrapper.find('button[aria-label="关闭设备详情"]').trigger('click')
    expect(wrapper.find('aside').exists()).toBe(false)
  })

  it('shows the empty state when initial load fails and always reveals after loading', async () => {
    mocks.searchDevices.mockRejectedValueOnce(new Error('backend unavailable'))
    mount(DeviceIndex, {
      global: {
        stubs,
        directives: { loading: { mounted() {}, updated() {} } },
      },
    })
    await flushPromises()

    expect(mocks.reveal).toHaveBeenCalled()
    expect(mocks.searchDevices).toHaveBeenCalledTimes(1)
  })

  it('covers missing filters, default page and size, truncated paging, and no-selection drawer fallbacks', async () => {
    const wrapper = mount(DeviceIndex, {
      global: {
        stubs,
        directives: { loading: { mounted() {}, updated() {} } },
      },
    })
    await flushPromises()
    const setup = (wrapper.vm as unknown as { $: { setupState: Record<string, unknown> } }).$.setupState
    const query = setup.query as { page: number; size?: number; status?: string }
    query.page = 0
    query.size = undefined
    query.status = undefined

    mocks.searchDevices.mockResolvedValueOnce(page([firstDevice], { total: 100, pages: 0, truncated: true }))
    await (setup.load as () => Promise<void>)()
    await flushPromises()
    expect(mocks.searchDevices).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, size: undefined }))
    expect(wrapper.find('.depth-notice').text()).toBe('100')
    expect(wrapper.findComponent({ name: 'PaginationStub' }).props('total')).toBe(24)
    expect(wrapper.findComponent({ name: 'PageSizeControl' }).props('modelValue')).toBe(24)

    await (setup.onStatusChange as (value: string) => void)(undefined as unknown as string)
    await flushPromises()
    expect(mocks.searchDevices).toHaveBeenLastCalledWith(expect.objectContaining({ status: '', page: 1 }))

    mocks.push.mockClear()
    setup.selectedDevice = null
    setup.detailVisible = true
    await flushPromises()
    expect(wrapper.find('aside').text()).toContain('设备详情')
    expect(wrapper.find('aside').text()).toContain('实验室设备')
    await (setup.goFullDetail as () => void)()
    await (setup.reserveSelected as () => void)()
    expect(mocks.push).not.toHaveBeenCalled()
  })
})
