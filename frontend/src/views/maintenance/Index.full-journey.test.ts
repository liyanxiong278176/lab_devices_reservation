import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { cloneVNode, defineComponent, h, nextTick } from 'vue'

const api = vi.hoisted(() => ({
  completeMaintenanceCycle: vi.fn(),
  createMaintenancePlan: vi.fn(),
  downloadMaintenanceEvidence: vi.fn(),
  listMaintenanceDevices: vi.fn(),
  listMaintenancePlans: vi.fn(),
  listMaintenanceRecords: vi.fn(),
  updateMaintenancePlan: vi.fn(),
  uploadMaintenanceEvidence: vi.fn(),
}))
const messages = vi.hoisted(() => ({ warning: vi.fn(), success: vi.fn() }))
const dialogs = vi.hoisted(() => ({ confirm: vi.fn() }))
const router = vi.hoisted(() => ({ push: vi.fn() }))
const uuid = vi.hoisted(() => vi.fn())
vi.mock('@/api/maintenance', () => api)
vi.mock('element-plus', () => ({ ElMessage: messages, ElMessageBox: dialogs }))
vi.mock('vue-router', () => ({ useRouter: () => router }))
vi.mock('@/router', () => ({ readSpaDepth: () => 0 }))
vi.mock('@/utils/uuid', () => ({ uuid }))

import MaintenancePage from './Index.vue'

const devices = [
  { id: 1, name: '光谱仪', status: 'IDLE', assetCode: 'LAB-001', labName: '物理实验室' },
  { id: 2, name: '显微镜', status: 'IDLE', assetCode: null, labName: '生物实验室' },
]
function plan(overrides: Record<string, unknown> = {}) {
  return {
    id: 10, deviceId: 1, deviceName: '光谱仪', deviceAssetCode: 'LAB-001', collegeId: 3,
    planType: 'ROUTINE', title: '年度清洁', intervalValue: 1, intervalUnit: 'DAY', dueDate: '2026-10-10',
    downtimeStart: '2026-10-11', downtimeEnd: '2026-10-12', active: true,
    temporarilyUnbookable: true, unbookableReason: '校准记录逾期', ...overrides,
  }
}
const defaultPlans = [
  plan(),
  plan({ id: 11, deviceId: 2, deviceName: '显微镜', deviceAssetCode: null, planType: 'CALIBRATION', title: '精度校准', intervalValue: 6, intervalUnit: 'MONTH', downtimeStart: null, downtimeEnd: null, active: false, temporarilyUnbookable: false, unbookableReason: null }),
  plan({ id: 12, planType: 'SAFETY_CHECK', title: '年度安全检查', intervalValue: 1, intervalUnit: 'YEAR', active: true, temporarilyUnbookable: false, downtimeStart: null, downtimeEnd: null }),
]
function listResult(items = defaultPlans, overrides: Record<string, unknown> = {}) {
  return { items: structuredClone(items), total: 63, page: 1, page_size: 20, pages: 0, truncated: true, ...overrides }
}
const historyRecords = [
  { id: 100, result: 'PASSED', completedDate: '2026-09-01', notes: '已更换滤芯', performedBy: 20, performedByName: '李老师', evidenceUrl: '/evidence/cert.pdf', evidenceName: 'cert.pdf', repairReportId: 88 },
  { id: 101, result: 'FAILED', completedDate: '2026-08-01', notes: null, performedBy: 21, performedByName: null, evidenceUrl: '/evidence/missing-name.pdf', evidenceName: null, repairReportId: null },
]

const TableStub = defineComponent({
  name: 'ElTableStub',
  props: ['data'],
  setup(props, { slots }) {
    return () => {
      const rows = props.data as unknown[]
      if (!rows.length) return h('div', { class: 'table-empty' }, slots.empty?.())
      return h('div', { class: 'table-stub' }, rows.map((row) =>
        h('div', { class: 'plan-row' }, (slots.default?.() ?? []).map((column) => cloneVNode(column, { row }))),
      ))
    }
  },
})
const ColumnStub = defineComponent({
  name: 'ElTableColumnStub',
  props: ['row', 'prop'],
  setup(props, { slots }) {
    return () => h('div', { class: 'table-cell' }, slots.default?.({ row: props.row }) ?? String((props.row as any)?.[props.prop] ?? ''))
  },
})
const SegmentStub = defineComponent({
  name: 'SegmentedControlStub',
  props: ['options', 'modelValue'],
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () => h('div', { class: 'segments' }, (props.options as Array<{ label: string; value: string }>).map((item) =>
      h('button', { 'data-status': item.value, onClick: () => emit('update:modelValue', item.value) }, item.label),
    ))
  },
})
const SelectStub = defineComponent({
  name: 'ElSelectStub',
  props: ['modelValue', 'remoteMethod', 'disabled'],
  emits: ['update:modelValue', 'change'],
  setup(props, { emit, slots }) {
    return () => h('div', { class: 'select-stub' }, [
      props.remoteMethod ? h('input', { class: 'remote-input', onInput: (event: Event) => props.remoteMethod((event.target as HTMLInputElement).value) }) : null,
      h('select', {
        class: 'select-control', value: props.modelValue ?? '', disabled: props.disabled,
        onChange: (event: Event) => {
          const raw = (event.target as HTMLSelectElement).value
          const value = /^\d+$/.test(raw) ? Number(raw) : raw
          emit('update:modelValue', value)
          emit('change', value)
        },
      }, slots.default?.()),
    ])
  },
})
const RadioGroupStub = defineComponent({
  name: 'ElRadioGroupStub',
  emits: ['update:modelValue'],
  setup(_, { emit, slots }) {
    return () => h('div', { class: 'radio-group', onClick: (event: MouseEvent) => {
      const value = (event.target as HTMLElement).closest<HTMLElement>('[data-radio-value]')?.dataset.radioValue
      if (value) emit('update:modelValue', value)
    } }, slots.default?.())
  },
})
const PaginationStub = defineComponent({
  name: 'ElPaginationStub',
  props: ['currentPage', 'pageSize'],
  emits: ['current-change', 'size-change'],
  template: '<div class="pagination"><button class="next-page" @click="$emit(\'current-change\', (currentPage || 1) + 1)">下一页</button><button class="size-page" @click="$emit(\'size-change\', 50)">每页50条</button></div>',
})
const stubs = {
  PageHeader: { props: ['title', 'subtitle'], template: '<header>{{ title }} {{ subtitle }}<slot name="actions" /></header>' },
  GradientButton: { props: ['disabled', 'loading'], emits: ['click'], template: '<button class="gradient-button" :disabled="disabled || loading" @click="$emit(\'click\')"><slot /></button>' },
  GhostButton: { emits: ['click'], template: '<button class="ghost-button" @click="$emit(\'click\')"><slot /></button>' },
  TextButton: { emits: ['click'], template: '<button class="text-button" @click="$emit(\'click\')"><slot /></button>' },
  Tag: { props: ['variant'], template: '<span class="tag" :data-variant="variant"><slot /></span>' },
  EmptyState: { props: ['title', 'description'], template: '<div class="empty-state">{{ title }} {{ description }}</div>' },
  PageDepthNotice: { props: ['total'], template: '<div class="depth-notice">{{ total }}</div>' },
  SegmentedControl: SegmentStub,
  'el-table': TableStub,
  'el-table-column': ColumnStub,
  'el-pagination': PaginationStub,
  'el-dialog': { props: ['modelValue', 'title'], emits: ['update:modelValue'], template: '<aside v-if="modelValue" class="dialog" :data-title="title"><h2>{{ title }}</h2><slot /><button class="dialog-model-close" @click="$emit(\'update:modelValue\', false)">close</button><footer><slot name="footer" /></footer></aside>' },
  'el-form': { template: '<form><slot /></form>' },
  'el-form-item': { props: ['label'], template: '<label>{{ label }}<slot /></label>' },
  'el-select': SelectStub,
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
  'el-input': { props: ['modelValue'], emits: ['update:modelValue'], template: '<input class="input-control" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
  'el-input-number': { props: ['modelValue'], emits: ['update:modelValue'], template: '<input class="number-control" type="number" :value="modelValue" @input="$emit(\'update:modelValue\', Number($event.target.value))" />' },
  'el-date-picker': { props: ['modelValue'], emits: ['update:modelValue'], template: '<input class="date-control" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
  'el-switch': { props: ['modelValue'], emits: ['update:modelValue'], template: '<input class="switch-control" type="checkbox" :checked="modelValue" @change="$emit(\'update:modelValue\', $event.target.checked)" />' },
  'el-radio-group': RadioGroupStub,
  'el-radio-button': { props: ['value'], template: '<button type="button" :data-radio-value="value"><slot /></button>' },
  'el-alert': { props: ['title'], template: '<aside>{{ title }}</aside>' },
}

function mountPage() {
  return mount(MaintenancePage, { global: { stubs, directives: { loading: () => {} } } })
}
function setup(wrapper: ReturnType<typeof mount>) {
  return (wrapper.vm as any).$?.setupState as Record<string, any>
}
function fileInput(wrapper: ReturnType<typeof mount>) {
  return wrapper.get('.dialog input[type="file"]')
}
async function chooseFile(input: ReturnType<typeof mount>['get'] extends (...args: any) => infer T ? T : never, files: File[]) {
  Object.defineProperty(input.element, 'files', { configurable: true, value: files })
  await input.trigger('change')
}
async function settledPage() {
  const wrapper = mountPage()
  await flushPromises()
  return wrapper
}

describe('maintenance plan, completion, and history full journeys', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    uuid.mockReturnValue('idem-key-1')
    router.push.mockResolvedValue(undefined)
    dialogs.confirm.mockResolvedValue('confirm')
    api.listMaintenanceDevices.mockResolvedValue({ records: structuredClone(devices), total: devices.length })
    api.listMaintenancePlans.mockResolvedValue(listResult())
    api.createMaintenancePlan.mockResolvedValue(undefined)
    api.updateMaintenancePlan.mockResolvedValue(undefined)
    api.listMaintenanceRecords.mockResolvedValue({ items: structuredClone(historyRecords), total: 45, page: 1, page_size: 20, pages: 3, truncated: false })
    api.downloadMaintenanceEvidence.mockResolvedValue(undefined)
    api.uploadMaintenanceEvidence.mockResolvedValue({ asset_token: 'evidence-token-1', url: '/evidence/1.pdf' })
    api.completeMaintenanceCycle.mockResolvedValue({ id: 200, repairReportId: null })
  })

  it('loads options and plans, renders labels/warnings, filters, searches, and paginates', async () => {
    const wrapper = await settledPage()
    const state = setup(wrapper)
    expect(api.listMaintenanceDevices).toHaveBeenCalledWith({ page: 1, pageSize: 100, search: '' })
    expect(api.listMaintenancePlans).toHaveBeenCalledWith({ page: 1, pageSize: 20, deviceId: undefined, active: true })
    expect(wrapper.text()).toContain('周期保养')
    expect(wrapper.text()).toContain('仪器校准')
    expect(wrapper.text()).toContain('安全检查')
    expect(wrapper.text()).toContain('每 1 天')
    expect(wrapper.text()).toContain('每 6 个月')
    expect(wrapper.text()).toContain('每 1 年')
    expect(wrapper.text()).toContain('校准记录逾期')
    expect(wrapper.text()).toContain('2026-10-11 — 2026-10-12')
    expect(wrapper.text()).toContain('未安排')
    expect(wrapper.text()).toContain('设备 #2')
    expect(wrapper.find('.depth-notice').text()).toBe('63')
    expect(state.activeValue).toBe(true)

    const remote = wrapper.findAll('.remote-input')[0]
    await remote.setValue('显微')
    await flushPromises()
    expect(api.listMaintenanceDevices).toHaveBeenLastCalledWith({ page: 1, pageSize: 100, search: '显微' })
    await wrapper.findAll('.select-control')[0].setValue('2')
    await flushPromises()
    expect(state.deviceFilter).toBe(2)
    expect(state.page.current).toBe(1)
    await wrapper.get('[data-status="INACTIVE"]').trigger('click')
    await flushPromises()
    expect(api.listMaintenancePlans).toHaveBeenLastCalledWith({ page: 1, pageSize: 20, deviceId: 2, active: false })
    await wrapper.get('[data-status="ALL"]').trigger('click')
    await flushPromises()
    expect(state.activeValue).toBeNull()
    state.setStatusFilter('invalid')
    expect(state.statusFilter).toBe('ALL')
    await wrapper.get('.next-page').trigger('click')
    await flushPromises()
    await wrapper.get('.size-page').trigger('click')
    await flushPromises()
    expect(api.listMaintenancePlans).toHaveBeenLastCalledWith({ page: 1, pageSize: 50, deviceId: 2, active: null })
    api.listMaintenancePlans.mockResolvedValueOnce(listResult(defaultPlans, { truncated: false, pages: 2 }))
    await state.load()
    await nextTick()
    expect(wrapper.find('.depth-notice').exists()).toBe(false)
  })

  it('shows the empty state and recovers from option/list request failures', async () => {
    api.listMaintenanceDevices.mockRejectedValueOnce(new Error('offline'))
    api.listMaintenancePlans.mockResolvedValueOnce(listResult([], { total: 0, truncated: false }))
    const wrapper = await settledPage()
    const state = setup(wrapper)
    expect(wrapper.text()).toContain('还没有维护计划')
    expect(wrapper.get('header .gradient-button').attributes('disabled')).toBeDefined()
    expect(state.deviceLoading).toBe(false)
    expect(state.loading).toBe(false)
    state.searchDeviceOptions('retry')
    api.listMaintenanceDevices.mockRejectedValueOnce(new Error('offline'))
    await state.searchDeviceOptions('error')
    expect(state.deviceLoading).toBe(false)
    api.listMaintenancePlans.mockRejectedValueOnce(new Error('offline'))
    await state.load()
    expect(state.loading).toBe(false)
    expect(state.page.records).toEqual([])
    expect(state.maxPage).toBe(0)
  })

  it('creates plans through visible controls and validates required fields and downtime pairs', async () => {
    const wrapper = await settledPage()
    const state = setup(wrapper)
    await wrapper.get('header .gradient-button').trigger('click')
    expect(wrapper.get('.dialog').attributes('data-title')).toBe('新建维护计划')
    await wrapper.get('.dialog .gradient-button').trigger('click')
    expect(messages.warning).toHaveBeenCalledWith('请选择设备、填写计划名称和下次到期日')
    state.planForm.deviceId = 1
    state.planForm.title = 'A'
    await state.savePlan()
    state.planForm.title = '年度清洁'
    await state.savePlan()
    expect(api.createMaintenancePlan).not.toHaveBeenCalled()

    const selects = wrapper.findAll('.dialog .select-control')
    await selects[0].setValue('2')
    await selects[1].setValue('CALIBRATION')
    await wrapper.get('.dialog .input-control').setValue('  显微镜校准  ')
    await wrapper.get('.dialog .number-control').setValue('9')
    await selects[2].setValue('YEAR')
    await wrapper.findAll('.dialog .date-control')[0].setValue('2027-01-01')
    await wrapper.get('.dialog .switch-control').setValue(false)
    await wrapper.findAll('.dialog .date-control')[1].setValue('2026-12-01')
    await wrapper.get('.dialog .gradient-button').trigger('click')
    expect(messages.warning).toHaveBeenLastCalledWith('计划停机开始和结束日期需要同时填写')
    await wrapper.findAll('.dialog .date-control')[2].setValue('2026-12-02')
    await wrapper.get('.dialog .gradient-button').trigger('click')
    await flushPromises()
    expect(api.createMaintenancePlan).toHaveBeenCalledWith(2, {
      planType: 'CALIBRATION', title: '显微镜校准', intervalValue: 9, intervalUnit: 'YEAR',
      dueDate: '2027-01-01', downtimeStart: '2026-12-01', downtimeEnd: '2026-12-02', active: false,
    })
    expect(messages.success).toHaveBeenCalledWith('维护计划已创建')
    expect(state.submitting).toBe(false)

    await wrapper.get('header .gradient-button').trigger('click')
    await wrapper.get('.dialog-model-close').trigger('click')
    expect(state.planDialog).toBe(false)
    await wrapper.get('header .gradient-button').trigger('click')
    await wrapper.get('.dialog .ghost-button').trigger('click')
    expect(state.planDialog).toBe(false)
  })

  it('creates without downtime, edits existing and unavailable-device plans, and catches save failures', async () => {
    const wrapper = await settledPage()
    const state = setup(wrapper)
    state.openCreate()
    await nextTick()
    state.planForm.deviceId = 1
    state.planForm.title = '季度保养'
    state.planForm.dueDate = '2026-11-01'
    state.planForm.downtimeStart = ''
    state.planForm.downtimeEnd = ''
    api.createMaintenancePlan.mockRejectedValueOnce(new Error('conflict'))
    await state.savePlan()
    expect(state.submitting).toBe(false)
    expect(state.planDialog).toBe(true)

    const edit = wrapper.findAll('.plan-row')[1].findAll('.text-button')[1]
    await edit.trigger('click')
    expect(state.planMode).toBe('edit')
    expect(state.editingDeviceOption).toBeNull()
    expect(state.planForm.downtimeStart).toBe('')
    expect(wrapper.get('.dialog').attributes('data-title')).toBe('编辑维护计划')
    await wrapper.get('.dialog .input-control').setValue('更精确的校准')
    api.updateMaintenancePlan.mockResolvedValueOnce(undefined)
    await wrapper.get('.dialog .gradient-button').trigger('click')
    await flushPromises()
    expect(api.updateMaintenancePlan).toHaveBeenCalledWith(11, expect.objectContaining({ title: '更精确的校准', downtimeStart: null, downtimeEnd: null }))
    expect(messages.success).toHaveBeenCalledWith('维护计划已更新')

    state.openEdit(plan({ id: 99, deviceId: 999, deviceName: '已退役设备', deviceAssetCode: null, downtimeStart: null, downtimeEnd: null }) as any)
    await nextTick()
    expect(state.editingDeviceOption).toEqual({ id: 999, name: '已退役设备', assetCode: undefined, labName: undefined })
    expect(state.planDeviceOptions.some((item: any) => item.id === 999)).toBe(true)
  })

  it('toggles active and inactive plans with confirmation, persistence, and failure handling', async () => {
    const wrapper = await settledPage()
    const state = setup(wrapper)
    dialogs.confirm.mockRejectedValueOnce(new Error('cancel'))
    await wrapper.findAll('.plan-row')[0].findAll('.text-button')[2].trigger('click')
    expect(api.updateMaintenancePlan).not.toHaveBeenCalled()
    await wrapper.findAll('.plan-row')[0].findAll('.text-button')[2].trigger('click')
    await flushPromises()
    expect(api.updateMaintenancePlan).toHaveBeenCalledWith(10, expect.objectContaining({ active: false, downtimeStart: '2026-10-11' }))
    expect(messages.success).toHaveBeenCalledWith('维护计划已停用')
    await wrapper.findAll('.plan-row')[1].findAll('.text-button')[2].trigger('click')
    await flushPromises()
    expect(messages.success).toHaveBeenCalledWith('维护计划已启用')
    api.updateMaintenancePlan.mockRejectedValueOnce(new Error('offline'))
    await state.toggleActive(defaultPlans[0] as any)
    expect(api.updateMaintenancePlan).toHaveBeenCalledTimes(3)
  })

  it('registers routine maintenance, validates failed results, and persists notes', async () => {
    const wrapper = await settledPage()
    const state = setup(wrapper)
    await wrapper.findAll('.plan-row')[0].findAll('.text-button')[3].trigger('click')
    await wrapper.get('.dialog-model-close').trigger('click')
    expect(state.completionDialog).toBe(false)
    await wrapper.findAll('.plan-row')[0].findAll('.text-button')[3].trigger('click')
    await wrapper.get('.dialog .ghost-button').trigger('click')
    expect(state.completionDialog).toBe(false)
    await wrapper.findAll('.plan-row')[0].findAll('.text-button')[3].trigger('click')
    expect(wrapper.get('.dialog').attributes('data-title')).toBe('登记维护完成')
    expect(wrapper.text()).toContain('完成凭证（可选）')
    await wrapper.get('.dialog .radio-group [data-radio-value="FAILED"]').trigger('click')
    expect(wrapper.text()).toContain('未通过情况（必填）')
    expect(wrapper.text()).toContain('提交后设备会进入维护状态')
    await wrapper.get('.dialog .date-control').setValue('2026-09-28')
    await wrapper.get('.dialog .gradient-button').trigger('click')
    expect(messages.warning).toHaveBeenCalledWith('不合格时请填写至少 2 个字的情况说明')
    await wrapper.get('.dialog .input-control').setValue('过滤器破损')
    const notes = wrapper.get('.dialog .input-control')
    await notes.setValue('过滤器破损，需更换')
    await wrapper.get('.dialog .gradient-button').trigger('click')
    await flushPromises()
    expect(api.completeMaintenanceCycle).toHaveBeenCalledWith(10, expect.objectContaining({
      cycleDueDate: '2026-10-10', result: 'FAILED', notes: '过滤器破损，需更换', evidenceAssetToken: undefined,
    }), 'idem-key-1')
    expect(messages.success).toHaveBeenCalledWith('完成记录已保存，下次到期日已按实际完成日期顺延')
    expect(state.completionSubmitting).toBe(false)
    expect(state.disableFutureDate(new Date(Date.now() + 60_000))).toBe(true)
    expect(state.disableFutureDate(new Date(Date.now() - 60_000))).toBe(false)
  })

  it('requires calibration evidence and retries completion idempotently after a lost response', async () => {
    const wrapper = await settledPage()
    const state = setup(wrapper)
    state.openCompletion(defaultPlans[1] as any)
    await nextTick()
    expect(state.evidenceRequired).toBe(true)
    await wrapper.get('.dialog .gradient-button').trigger('click')
    expect(messages.warning).toHaveBeenCalledWith('校准与安全检查必须上传证书或检查记录')
    const evidence = new File(['certificate'], 'certificate.pdf', { type: 'application/pdf' })
    await chooseFile(fileInput(wrapper), [evidence])
    const stableKey = state.completionIdempotencyKey
    api.completeMaintenanceCycle.mockRejectedValueOnce(new Error('response lost'))
    await state.submitCompletion()
    expect(api.uploadMaintenanceEvidence).toHaveBeenCalledWith(2, evidence)
    expect(state.completionEvidenceToken).toBe('evidence-token-1')
    expect(state.completionIdempotencyKey).toBe(stableKey)
    api.completeMaintenanceCycle.mockResolvedValueOnce({ id: 201, repairReportId: 93 })
    await state.submitCompletion()
    await flushPromises()
    expect(api.uploadMaintenanceEvidence).toHaveBeenCalledOnce()
    expect(api.completeMaintenanceCycle).toHaveBeenLastCalledWith(11, expect.objectContaining({ evidenceAssetToken: 'evidence-token-1' }), stableKey)
    expect(messages.success).toHaveBeenCalledWith('检查已记录，并自动创建报修工单 #93')

    state.openCompletion(defaultPlans[1] as any)
    await nextTick()
    const input = fileInput(wrapper)
    await chooseFile(input, [])
    expect(state.completionFile).toBeNull()
    expect(state.completionEvidenceToken).toBeNull()
    expect(state.completionIdempotencyKey).toBe('idem-key-1')
    state.completingPlan = null
    await state.submitCompletion()
    expect(api.completeMaintenanceCycle).toHaveBeenCalledTimes(2)
  })

  it('shows history, downloads evidence, follows repair links, paginates, and handles empty/error states', async () => {
    const wrapper = await settledPage()
    const state = setup(wrapper)
    await wrapper.findAll('.plan-row')[0].findAll('.text-button')[0].trigger('click')
    await flushPromises()
    expect(api.listMaintenanceRecords).toHaveBeenCalledWith(10, 1)
    expect(wrapper.text()).toContain('检查通过')
    expect(wrapper.text()).toContain('检查未通过')
    expect(wrapper.text()).toContain('未填写备注')
    expect(wrapper.text()).toContain('用户 #21')
    expect(wrapper.text()).toContain('下载凭证')
    expect(wrapper.findAll('.pagination')).toHaveLength(2)
    const evidenceButtons = wrapper.findAll('.history-card .text-button')
    await evidenceButtons[0].trigger('click')
    await evidenceButtons[1].trigger('click')
    expect(api.downloadMaintenanceEvidence).toHaveBeenCalledWith('/evidence/cert.pdf', 'cert.pdf')
    expect(api.downloadMaintenanceEvidence).toHaveBeenCalledTimes(1)
    await wrapper.find('.history-card .text-button').trigger('click')
    expect(router.push).toHaveBeenCalledWith({ name: 'repairs-admin' })
    await wrapper.findAll('.pagination').at(-1)!.get('.next-page').trigger('click')
    await flushPromises()
    expect(api.listMaintenanceRecords).toHaveBeenLastCalledWith(10, 2)
    expect(state.historyPage).toBe(2)

    api.downloadMaintenanceEvidence.mockRejectedValueOnce(new Error('offline'))
    await state.downloadEvidence({ evidenceUrl: '/evidence/x', evidenceName: 'x.pdf' } as any)
    await state.downloadEvidence({ evidenceUrl: undefined, evidenceName: 'x.pdf' } as any)

    api.listMaintenanceRecords.mockResolvedValueOnce({ items: [], total: 0 })
    await state.showHistory(plan({ id: 77 }) as any)
    expect(wrapper.text()).toContain('暂无完成记录')
    api.listMaintenanceRecords.mockRejectedValueOnce(new Error('offline'))
    await state.showHistory(plan({ id: 78 }) as any)
    expect(state.historyLoading).toBe(false)
    expect(state.historyRecords).toEqual([])
    await wrapper.get('.dialog-model-close').trigger('click')
    expect(state.historyDialog).toBe(false)
  })
})
