import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, nextTick, type SetupContext } from 'vue'
import dayjs from 'dayjs'

const api = vi.hoisted(() => ({
  acceptReservationReturn: vi.fn(),
  cancelHandoverException: vi.fn(),
  handoverReservation: vi.fn(),
  pendingHandovers: vi.fn(),
  uploadRepairImage: vi.fn(),
}))
const messages = vi.hoisted(() => ({ warning: vi.fn(), success: vi.fn() }))
const dialogs = vi.hoisted(() => ({ confirm: vi.fn() }))
vi.mock('@/api/reservation', () => ({
  acceptReservationReturn: api.acceptReservationReturn,
  cancelHandoverException: api.cancelHandoverException,
  handoverReservation: api.handoverReservation,
  pendingHandovers: api.pendingHandovers,
}))
vi.mock('@/api/repair', () => ({ uploadRepairImage: api.uploadRepairImage }))
vi.mock('element-plus', () => ({ ElMessage: messages, ElMessageBox: dialogs }))

import HandoverPage from './Index.vue'

const today = dayjs().format('YYYY-MM-DD')
const future = dayjs().add(2, 'day').format('YYYY-MM-DD')
function reservation(overrides: Record<string, unknown> = {}) {
  return {
    id: 11, deviceId: 5, deviceAssetCode: 'LAB-005', deviceName: '光谱仪', deviceLabName: '物理实验室',
    userId: 20, startDate: today, endDate: today, purpose: '光谱实验', accessorySnapshot: ['电源线', '数据线'],
    returnImageUrls: [], faultRepairId: 71, ...overrides,
  }
}
function page(records: unknown[], overrides: Record<string, unknown> = {}) {
  return { records, total: records.length, size: 12, current: 1, pages: 1, truncated: false, ...overrides }
}

const SegmentStub = defineComponent({
  name: 'SegmentedControlStub',
  props: ['options', 'modelValue'],
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () => h('div', { class: 'segments' }, (props.options as Array<{ label: string; value: string }>).map((option) =>
      h('button', { 'data-tab': option.value, onClick: () => emit('update:modelValue', option.value) }, option.label),
    ))
  },
})
const stubs = {
  PageHeader: { props: ['title', 'subtitle'], template: '<header>{{ title }} {{ subtitle }}<slot name="actions" /></header>' },
  SegmentedControl: SegmentStub,
  GlowCard: { template: '<article class="handover-card"><slot /></article>' },
  Tag: { props: ['variant'], template: '<span class="tag" :data-variant="variant"><slot /></span>' },
  GradientButton: { props: ['disabled', 'loading'], emits: ['click'], template: '<button class="gradient-button" :disabled="disabled || loading" @click="$emit(\'click\')"><slot /></button>' },
  GhostButton: { emits: ['click'], template: '<button class="ghost-button" @click="$emit(\'click\')"><slot /></button>' },
  EmptyState: { props: ['title', 'description'], template: '<div class="empty-state">{{ title }} {{ description }}</div>' },
  PageDepthNotice: { props: ['total'], template: '<div class="depth-notice">{{ total }}</div>' },
  'el-pagination': { props: ['currentPage'], emits: ['current-change'], template: '<button class="next-page" @click="$emit(\'current-change\', currentPage + 1)">next</button>' },
  'el-dialog': { props: ['modelValue', 'title'], emits: ['update:modelValue'], template: '<aside v-if="modelValue" class="dialog"><h2>{{ title }}</h2><slot /><button class="dialog-model-close" @click="$emit(\'update:modelValue\', false)">close</button><footer><slot name="footer" /></footer></aside>' },
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
  'el-select': {
    props: ['modelValue'], emits: ['update:modelValue', 'change'],
    template: '<select aria-label="配件状态" :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value); $emit(\'change\', $event.target.value)"><slot /></select>',
  },
  'el-radio-group': {
    emits: ['update:modelValue'],
    setup(_props: any, { emit, slots }: SetupContext) {
      return () => h('div', { class: 'radio-group', onClick: (event: MouseEvent) => {
        const value = (event.target as HTMLElement).closest<HTMLElement>('[data-value]')?.dataset.value
        if (value) emit('update:modelValue', value)
      } }, slots.default?.())
    },
  },
  'el-radio': { props: ['value'], template: '<button type="button" :data-value="value"><slot /></button>' },
  'el-input': { props: ['modelValue'], emits: ['update:modelValue'], template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
}
function mountPage() {
  return mount(HandoverPage, { global: { stubs, directives: { loading: () => {} } } })
}
function setup(wrapper: ReturnType<typeof mount>) {
  return (wrapper.vm as any).$?.setupState as Record<string, any>
}
async function settledPage() {
  const wrapper = mountPage()
  await flushPromises()
  return wrapper
}

describe('handover and return acceptance full user journeys', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.pendingHandovers.mockImplementation(async () => page([reservation(), reservation({ id: 12, startDate: future, endDate: undefined, deviceAssetCode: '', deviceLabName: '', purpose: '', accessorySnapshot: undefined })], { total: 37, pages: 0, truncated: true }))
    api.uploadRepairImage.mockImplementation(async (file: File) => ({ url: `/uploads/${file.name}` }))
    api.handoverReservation.mockResolvedValue(undefined)
    api.acceptReservationReturn.mockResolvedValue(undefined)
    api.cancelHandoverException.mockResolvedValue(undefined)
    dialogs.confirm.mockResolvedValue('confirm')
  })

  it('loads pending reservations, enforces start date, and navigates across tabs and pages', async () => {
    const wrapper = await settledPage()
    const state = setup(wrapper)
    expect(api.pendingHandovers).toHaveBeenCalledWith('PENDING', 1, 12)
    expect(wrapper.text()).toContain('当前范围内 37 条记录')
    expect(wrapper.text()).toContain('预约开始日')
    expect(wrapper.findAll('.handover-card')).toHaveLength(2)
    expect(wrapper.findAll('.handover-card .gradient-button')[0].attributes('disabled')).toBeUndefined()
    expect(wrapper.findAll('.handover-card .gradient-button')[1].attributes('disabled')).toBeDefined()
    expect(wrapper.find('.depth-notice').exists()).toBe(true)
    expect(wrapper.text()).toContain(`${future} 至 —`)
    await wrapper.get('.next-page').trigger('click')
    await flushPromises()
    expect(state.query.page).toBe(2)
    expect(api.pendingHandovers).toHaveBeenLastCalledWith('PENDING', 2, 12)

    api.pendingHandovers.mockImplementationOnce(async () => page([], { total: 0 }))
    await wrapper.get('[data-tab="RETURN_PENDING"]').trigger('click')
    await flushPromises()
    expect(state.activeStatus).toBe('RETURN_PENDING')
    expect(state.query.page).toBe(1)
    expect(wrapper.text()).toContain('暂无待验收设备')
    api.pendingHandovers.mockImplementationOnce(async () => page([]))
    await wrapper.get('[data-tab="EXCEPTION"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('暂无待处理交接异常')
  })

  it('completes handover without photos and still requires notes for damage', async () => {
    const wrapper = await settledPage()
    await wrapper.findAll('.handover-card .gradient-button')[0].trigger('click')
    expect(wrapper.find('input[type="file"]').exists()).toBe(false)
    await wrapper.get('.dialog .radio-group [data-value="DAMAGED"]').trigger('click')
    await wrapper.get('.dialog .gradient-button').trigger('click')
    expect(messages.warning).toHaveBeenCalledWith('发现损坏或缺失时，请补充验收说明')
    expect(api.handoverReservation).not.toHaveBeenCalled()
    await wrapper.get('.dialog .radio-group [data-value="NORMAL"]').trigger('click')
    await wrapper.get('.dialog .gradient-button').trigger('click')
    await flushPromises()
    expect(api.uploadRepairImage).not.toHaveBeenCalled()
    expect(api.handoverReservation).toHaveBeenCalledWith(11, {
      condition: 'NORMAL', note: undefined,
      checklist: [{ name: '电源线', condition: 'NORMAL' }, { name: '数据线', condition: 'NORMAL' }],
    })
    expect(messages.success).toHaveBeenCalledWith('设备已完成交接，用户可以开始使用')
    expect(setup(wrapper).dialogVisible).toBe(false)
  })

  it('preserves the form on handover failure and records accessory damage without photos', async () => {
    const wrapper = await settledPage()
    const state = setup(wrapper)
    state.openAction(reservation(), 'handover')
    await nextTick()
    await wrapper.findAll('.dialog select')[0].setValue('DAMAGED')
    await wrapper.findAll('.dialog input')[0].setValue('接头损坏')
    api.handoverReservation.mockRejectedValueOnce(new Error('设备不可用'))
    await state.submitAction()
    expect(state.dialogVisible).toBe(true)
    expect(state.saving).toBe(false)
    await state.submitAction()
    expect(messages.warning).toHaveBeenCalledWith('已记录交接异常，设备已转维修并生成关联工单')
    expect(api.uploadRepairImage).not.toHaveBeenCalled()
  })

  it('accepts a returned device with damage notes and preserves the users return photos', async () => {
    api.pendingHandovers.mockImplementation(async (status: string) => status === 'RETURN_PENDING'
      ? page([reservation({ id: 31, startDate: future, returnImageUrls: ['/return/a.jpg', '/return/b.jpg'], accessorySnapshot: ['三脚架'] })])
      : page([]))
    const wrapper = await settledPage()
    await wrapper.get('[data-tab="RETURN_PENDING"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('用户归还现场（2 张）')
    expect(wrapper.findAll('.handover-card__evidence a')).toHaveLength(2)
    await wrapper.get('.handover-card .gradient-button').trigger('click')
    const state = setup(wrapper)
    expect(state.dialogMode).toBe('return')
    expect(wrapper.find('.handover-dialog__photos').text()).toContain('打开照片')
    await wrapper.get('.dialog .radio-group [data-value="DAMAGED"]').trigger('click')
    await wrapper.get('.dialog input:not([type="file"])').setValue('镜头外壳破损')
    await wrapper.get('.dialog .gradient-button').trigger('click')
    await flushPromises()
    expect(api.acceptReservationReturn).toHaveBeenCalledWith(31, {
      condition: 'DAMAGED', note: '镜头外壳破损', checklist: [{ name: '三脚架', condition: 'NORMAL' }],
    })
    expect(messages.success).toHaveBeenCalledWith('异常已记录，设备已转维修并生成关联工单')
  })

  it('handles empty accessory snapshots, missing targets, missing return photos, and return cancellation', async () => {
    const wrapper = await settledPage()
    const state = setup(wrapper)
    state.openAction(reservation({ deviceAssetCode: undefined, accessorySnapshot: undefined }), 'return')
    await nextTick()
    expect(state.checklist).toEqual([])
    expect(wrapper.text()).toContain('未配置配件清单')
    expect(wrapper.text()).toContain('设备：光谱仪（#5）')
    await state.submitAction()
    api.acceptReservationReturn.mockClear()
    state.target = null
    await state.submitAction()
    expect(api.acceptReservationReturn).not.toHaveBeenCalled()

    api.pendingHandovers.mockImplementation(async (status: string) => status === 'RETURN_PENDING'
      ? page([reservation({ id: 32, returnImageUrls: [] })])
      : page([]))
    await wrapper.get('[data-tab="RETURN_PENDING"]').trigger('click')
    await flushPromises()
    await wrapper.get('.handover-card .gradient-button').trigger('click')
    expect(wrapper.text()).not.toContain('缺少照片')
    await wrapper.get('.dialog .gradient-button').trigger('click')
    await flushPromises()
    expect(api.acceptReservationReturn).toHaveBeenCalledWith(32, expect.objectContaining({ condition: 'NORMAL' }))
    state.openAction(reservation({ id: 32 }), 'return')
    await nextTick()
    await wrapper.get('.dialog .ghost-button').trigger('click')
    expect(state.dialogVisible).toBe(false)
  })

  it('cancels exception reservations only after confirmation and handles both API outcomes', async () => {
    api.pendingHandovers.mockImplementation(async (status: string) => status === 'EXCEPTION'
      ? page([reservation({ id: 41, faultRepairId: null }), reservation({ id: 42, faultRepairId: 88 })])
      : page([]))
    const wrapper = await settledPage()
    await wrapper.get('[data-tab="EXCEPTION"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('处理中')
    expect(wrapper.text()).toContain('报修单：#88')
    const state = setup(wrapper)
    dialogs.confirm.mockRejectedValueOnce(new Error('cancel'))
    await wrapper.findAll('.handover-card .ghost-button')[0].trigger('click')
    expect(api.cancelHandoverException).not.toHaveBeenCalled()
    dialogs.confirm.mockResolvedValueOnce('confirm')
    await wrapper.findAll('.handover-card .ghost-button')[1].trigger('click')
    await flushPromises()
    expect(api.cancelHandoverException).toHaveBeenCalledWith(42, '领用交接发现设备异常，取消预约并释放日期；关联报修工单继续处理')
    expect(messages.success).toHaveBeenCalledWith('预约已取消并释放日期，关联设备已保持维修状态')
    api.cancelHandoverException.mockRejectedValueOnce(new Error('conflict'))
    dialogs.confirm.mockResolvedValueOnce('confirm')
    await state.cancelException(reservation({ id: 41 }))
    expect(api.cancelHandoverException).toHaveBeenCalledTimes(2)
  })
})
