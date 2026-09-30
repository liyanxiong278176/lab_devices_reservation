import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  approve: vi.fn(),
  batchApprove: vi.fn(),
  pendingApprovals: vi.fn(),
  reject: vi.fn(),
  success: vi.fn(),
  warning: vi.fn(),
  loadUnread: vi.fn(),
  reveal: vi.fn(),
}))

vi.mock('@/api/approval', () => ({
  approve: mocks.approve,
  batchApprove: mocks.batchApprove,
  pendingApprovals: mocks.pendingApprovals,
  reject: mocks.reject,
}))
vi.mock('element-plus', () => ({ ElMessage: { success: mocks.success, warning: mocks.warning } }))
vi.mock('@/stores/notification', () => ({ useNotificationStore: () => ({ loadUnread: mocks.loadUnread }) }))
vi.mock('@/composables/useStagger', () => ({ useStagger: () => ({ reveal: mocks.reveal }) }))

import Pending from '../Pending.vue'

const item = (overrides: Record<string, unknown> = {}) => ({
  id: 11,
  userId: 7,
  username: 'student-seven',
  realName: ' 林同学 ',
  deviceId: 3,
  deviceName: '高速离心机',
  purpose: '样本分离',
  startTime: '2026-10-01T00:00:00',
  endTime: '2026-10-02T23:59:59',
  slotCount: 2,
  status: 'PENDING',
  createdAt: '2026-09-28T10:00:00',
  ...overrides,
})

const page = (records = [item()], overrides: Record<string, unknown> = {}) => ({
  records,
  total: records.length,
  size: 9,
  current: 1,
  pages: 1,
  truncated: false,
  ...overrides,
})

const stubs = {
  PageHeader: { props: ['title', 'subtitle'], template: '<header><h1>{{ title }}</h1><span>{{ subtitle }}</span><slot name="actions" /></header>' },
  Tag: { template: '<span class="tag"><slot /></span>' },
  GradientButton: {
    props: ['disabled', 'loading'],
    emits: ['click'],
    template: '<button class="gradient" :disabled="disabled || loading" @click="$emit(\'click\', $event)"><slot /></button>',
  },
  GhostButton: {
    props: ['disabled'],
    emits: ['click'],
    template: '<button class="ghost" :disabled="disabled" @click="$emit(\'click\', $event)"><slot /></button>',
  },
  EmptyState: { props: ['title', 'description'], template: '<div class="empty"><strong>{{ title }}</strong><span>{{ description }}</span></div>' },
  PageDepthNotice: { props: ['total'], template: '<div class="depth">{{ total }}</div>' },
  'el-checkbox': {
    props: ['modelValue'],
    emits: ['click', 'change'],
    template: '<button class="checkbox" @click="$emit(\'click\', $event); $emit(\'change\', !modelValue)">select</button>',
  },
  'el-pagination': {
    props: ['currentPage', 'pageSize', 'total'],
    emits: ['current-change', 'size-change'],
    template: '<div class="pagination"><button class="next" @click="$emit(\'current-change\', 2)">next</button><button class="resize" @click="$emit(\'size-change\', 18)">resize</button></div>',
  },
  'el-drawer': {
    props: ['modelValue'],
    emits: ['update:modelValue', 'close'],
    template: '<aside v-if="modelValue"><button class="drawer-close" @click="$emit(\'close\')">close</button><button class="drawer-model-close" @click="$emit(\'update:modelValue\', false)">update close</button><slot /></aside>',
  },
  'el-input': {
    props: ['modelValue', 'placeholder'],
    emits: ['update:modelValue'],
    template: '<textarea :placeholder="placeholder" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
  },
}

function mountPage() {
  return mount(Pending, {
    global: {
      stubs,
      directives: {
        permission: { mounted() {}, updated() {} },
        loading: { mounted() {}, updated() {} },
      },
    },
  })
}

describe('approval queue page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.pendingApprovals.mockResolvedValue(page())
    mocks.approve.mockResolvedValue(undefined)
    mocks.batchApprove.mockResolvedValue(undefined)
    mocks.reject.mockResolvedValue(undefined)
  })

  it('renders approval facts, falls back for missing applicant details, and shows empty and truncated states', async () => {
    mocks.pendingApprovals.mockResolvedValueOnce(page([
      item(),
      item({ id: 12, userId: 8, username: '  ', realName: '', purpose: '', slotCount: 0, startTime: '', endTime: '' }),
    ], { total: 120, truncated: true, pages: 3 }))
    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.text()).toContain('共 120 条待处理')
    expect(wrapper.text()).toContain('林同学')
    expect(wrapper.text()).toContain('用户 #8')
    expect(wrapper.text()).toContain('2026-10-01')
    expect(wrapper.text()).toContain('未填写用途')
    expect(wrapper.text()).toContain('—')
    expect(wrapper.find('.depth').text()).toBe('120')
    expect(wrapper.findAll('.approval__cell')).toHaveLength(2)
    expect(mocks.reveal).toHaveBeenCalled()
    await wrapper.findAll('.approval__card')[1].trigger('click')
    expect(wrapper.find('aside').text()).toContain('申请人未填写用途。')
    await wrapper.find('aside .drawer-close').trigger('click')
    await wrapper.find('.approval__card').trigger('click')
    expect(wrapper.find('aside').text()).toContain('student-seven')
    await wrapper.find('aside .drawer-model-close').trigger('click')
    expect(wrapper.find('aside').exists()).toBe(false)

    mocks.pendingApprovals.mockResolvedValueOnce(page([], { total: 0 }))
    await wrapper.find('.next').trigger('click')
    await flushPromises()
    expect(wrapper.find('.empty').text()).toContain('暂无待审批申请')
    expect(wrapper.find('.approval__pager').exists()).toBe(false)

    mocks.pendingApprovals.mockResolvedValueOnce(page([item()], { total: 100, truncated: true, pages: 0 }))
    const setup = (wrapper.vm as unknown as { $: { setupState: Record<string, unknown> } }).$.setupState
    await (setup.onSizeChange as (size: number) => Promise<void>)(18)
    await flushPromises()
    expect(wrapper.find('.depth').text()).toBe('100')
  })

  it('selects and prunes visible rows, changes page size, and performs batch approval', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('.checkbox').trigger('click')
    expect(wrapper.text()).toContain('批量通过 (1)')
    await wrapper.find('.checkbox').trigger('click')
    expect(wrapper.text()).toContain('批量通过 (0)')
    await wrapper.find('.checkbox').trigger('click')
    const setup = (wrapper.vm as unknown as { $: { setupState: Record<string, unknown> } }).$.setupState
    const onRowCheck = setup.onRowCheck as (row: ReturnType<typeof item>, checked: boolean) => void
    onRowCheck(item(), true)
    expect(wrapper.text()).toContain('批量通过 (1)')

    await wrapper.find('.resize').trigger('click')
    await flushPromises()
    expect(mocks.pendingApprovals).toHaveBeenLastCalledWith(1, 18)

    await wrapper.find('header .ghost').trigger('click')
    await flushPromises()
    expect(mocks.batchApprove).toHaveBeenCalledWith([11])
    expect(mocks.success).toHaveBeenCalledWith('已批量通过 1 条，预约进入设备交接队列')
    expect(mocks.loadUnread).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('批量通过 (0)')

    await wrapper.find('.checkbox').trigger('click')
    mocks.pendingApprovals.mockResolvedValueOnce(page([item({ id: 99 })]))
    await wrapper.find('.next').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('批量通过 (0)')
  })

  it('opens detail and approves from both the list and detail while refreshing notifications', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('.approval__card').trigger('click')
    expect(wrapper.find('aside').text()).toContain('申请详情')
    expect(wrapper.find('aside').text()).toContain('林同学')
    expect(wrapper.find('aside').text()).toContain('样本分离')
    await wrapper.find('aside .approval__reject-btn').trigger('click')
    expect(wrapper.find('textarea').exists()).toBe(true)
    await wrapper.find('aside .ghost').trigger('click')
    expect(wrapper.find('textarea').exists()).toBe(false)

    await wrapper.find('aside .gradient').trigger('click')
    await flushPromises()
    expect(mocks.approve).toHaveBeenCalledWith(11)
    expect(mocks.success).toHaveBeenCalledWith('已通过，预约进入设备交接队列')
    expect(mocks.loadUnread).toHaveBeenCalledOnce()
    expect(wrapper.find('aside').exists()).toBe(false)

    const setup = (wrapper.vm as unknown as { $: { setupState: Record<string, unknown> } }).$.setupState
    const onApprove = setup.onApprove as (row: ReturnType<typeof item>) => Promise<void>
    await onApprove(item({ id: 12 }))
    await flushPromises()
    expect(mocks.approve).toHaveBeenCalledWith(12)

    await wrapper.find('.approval__card .gradient').trigger('click')
    await flushPromises()
    expect(mocks.approve).toHaveBeenCalledTimes(3)
  })

  it('validates rejection reason, trims it before submission, and supports cancelling or closing the drawer', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('.approval__card .ghost').trigger('click')
    expect(wrapper.find('aside').exists()).toBe(true)
    expect(wrapper.find('textarea').exists()).toBe(true)

    await wrapper.find('aside .gradient').trigger('click')
    expect(mocks.warning).toHaveBeenCalledWith('请填写驳回理由')
    await wrapper.find('textarea').setValue('   ')
    await wrapper.find('aside .gradient').trigger('click')
    expect(mocks.reject).not.toHaveBeenCalled()

    await wrapper.find('textarea').setValue('  时间冲突  ')
    await wrapper.find('aside .gradient').trigger('click')
    await flushPromises()
    expect(mocks.reject).toHaveBeenCalledWith(11, '时间冲突')
    expect(mocks.success).toHaveBeenCalledWith('已驳回')
    expect(mocks.loadUnread).toHaveBeenCalledOnce()
    expect(wrapper.find('aside').exists()).toBe(false)

    await wrapper.find('.approval__card .ghost').trigger('click')
    await wrapper.find('aside .ghost').trigger('click')
    expect(wrapper.find('textarea').exists()).toBe(false)
    await wrapper.find('.approval__card').trigger('click')
    await wrapper.find('aside .drawer-close').trigger('click')
    expect(wrapper.find('aside').exists()).toBe(false)
  })

  it('warns when batch selection is empty and preserves state after API failures', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const setup = (wrapper.vm as unknown as { $: { setupState: Record<string, unknown> } }).$.setupState
    await (setup.onBatchApprove as () => Promise<void>)()
    expect(mocks.warning).toHaveBeenCalledWith('请先勾选要批量通过的预约')

    mocks.approve.mockRejectedValueOnce(new Error('approval failed'))
    await wrapper.find('.approval__card .gradient').trigger('click')
    await flushPromises()
    expect(mocks.success).not.toHaveBeenCalled()

    await wrapper.find('.approval__card .ghost').trigger('click')
    await wrapper.find('textarea').setValue('理由')
    mocks.reject.mockRejectedValueOnce(new Error('rejection failed'))
    await wrapper.find('aside .gradient').trigger('click')
    await flushPromises()
    expect(wrapper.find('aside').exists()).toBe(true)

    await wrapper.find('.checkbox').trigger('click')
    mocks.batchApprove.mockRejectedValueOnce(new Error('batch failed'))
    await (setup.onBatchApprove as () => Promise<void>)()
    expect(wrapper.text()).toContain('批量通过 (1)')
  })

  it('clears a rejection draft when its row disappears and tolerates list request failures', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.find('.approval__card .ghost').trigger('click')
    await wrapper.find('textarea').setValue('draft')
    mocks.pendingApprovals.mockResolvedValueOnce(page([]))
    const setup = (wrapper.vm as unknown as { $: { setupState: Record<string, unknown> } }).$.setupState
    await (setup.load as () => Promise<void>)()
    await flushPromises()
    expect(wrapper.find('aside').text()).not.toContain('draft')

    mocks.pendingApprovals.mockRejectedValueOnce(new Error('network unavailable'))
    await (setup.load as () => Promise<void>)()
    expect(mocks.reveal).toHaveBeenCalled()
  })
})
