import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { cloneVNode, defineComponent, h, nextTick } from 'vue'

const api = vi.hoisted(() => ({
  createBlackout: vi.fn(),
  deleteBlackout: vi.fn(),
  listBlackouts: vi.fn(),
  listColleges: vi.fn(),
  listAllLabs: vi.fn(),
  deleteReservationRule: vi.fn(),
  listReservationRules: vi.fn(),
  saveReservationRule: vi.fn(),
}))
const messages = vi.hoisted(() => ({ warning: vi.fn(), success: vi.fn() }))
const dialogs = vi.hoisted(() => ({ confirm: vi.fn() }))
const remote = vi.hoisted(() => ({
  loadInitial: vi.fn(),
  search: vi.fn(),
  options: [
    { id: 101, name: 'DEV-101 · 显微镜 · 光学实验室', assetCode: 'DEV-101', collegeId: 1, labId: 11, labName: '光学实验室' },
    { id: 102, name: '设备 #102 · 光谱仪 · 未分配实验室', assetCode: '', collegeId: null, labId: null, labName: null },
    { id: 103, name: '设备 #103 · 电子显微镜 · 光学实验室', assetCode: '', collegeId: null, labId: 11, labName: '光学实验室' },
    { id: 104, name: '设备 #104 · 离线设备', assetCode: 'DEV-104', collegeId: 2, labId: 999, labName: null },
    { id: 105, name: '设备 #105 · 未关联设备', assetCode: 'DEV-105', collegeId: undefined, labId: undefined, labName: null },
  ],
  devices: [
    { id: 101, name: '显微镜', collegeId: 1, labId: 11, labName: '光学实验室' },
    { id: 102, name: '光谱仪', collegeId: null, labId: null, labName: null },
    { id: 103, collegeId: null, labId: 11, labName: '光学实验室' },
  ],
}))
const user = vi.hoisted(() => ({ userId: 11, roles: ['SYS_ADMIN'] as string[] }))
vi.mock('@/api/college', () => ({ listColleges: api.listColleges }))
vi.mock('@/api/lab', () => ({ listAllLabs: api.listAllLabs }))
vi.mock('@/api/scheduling', () => ({ createBlackout: api.createBlackout, deleteBlackout: api.deleteBlackout, listBlackouts: api.listBlackouts }))
vi.mock('@/api/reservationRules', () => ({ deleteReservationRule: api.deleteReservationRule, listReservationRules: api.listReservationRules, saveReservationRule: api.saveReservationRule }))
vi.mock('@/composables/useRemoteDeviceOptions', async () => {
  const { ref } = await import('vue')
  return {
    useRemoteDeviceOptions: () => ({
      devices: ref(remote.devices),
      options: ref(remote.options),
      loading: ref(false),
      loadInitial: remote.loadInitial,
      search: remote.search,
    }),
  }
})
vi.mock('@/stores/user', async () => {
  const { reactive } = await import('vue')
  return { useUserStore: () => reactive(user) }
})
vi.mock('element-plus', () => ({ ElMessage: messages, ElMessageBox: dialogs }))

import SchedulingIndex from '../Index.vue'
import RulesPanel from '../RulesPanel.vue'

const colleges = [
  { id: 1, code: 'OPT', name: '光电学院', managerId: 11 },
  { id: 2, code: 'CHEM', name: '化学学院', managerId: 22 },
]
const labs = [
  { id: 11, collegeId: 1, name: '光学实验室', managerId: 22 },
  { id: 12, collegeId: 2, name: '化学实验室', managerId: 11 },
  { id: 13, collegeId: null, name: '未归属实验室', managerId: 22 },
]
const ruleRows = [
  { id: 1, scopeType: 'GLOBAL', scopeId: 0, scopeName: '全校默认', userCategory: 'ALL', maxBookingDays: null, maxAdvanceDays: 90, approvalRequired: null },
  { id: 2, scopeType: 'COLLEGE', scopeId: 1, scopeName: '光电学院', userCategory: 'STUDENT', maxBookingDays: 3, maxAdvanceDays: null, approvalRequired: true },
  { id: 3, scopeType: 'LAB', scopeId: 11, scopeName: '光学实验室', userCategory: 'LAB_ADMIN', maxBookingDays: null, maxAdvanceDays: null, approvalRequired: false },
  { id: 4, scopeType: 'DEVICE', scopeId: 101, scopeName: '显微镜', userCategory: 'STUDENT', maxBookingDays: 1, maxAdvanceDays: 14, approvalRequired: true },
]
const blackoutRows = [
  { id: 31, scopeType: 'COLLEGE', scopeId: 1, scopeName: '光电学院', blockedDate: '2026-10-01', reason: '校庆' },
  { id: 35, scopeType: 'COLLEGE', scopeId: 1, scopeName: '', blockedDate: '2026-10-04', reason: '学院调整' },
  { id: 32, scopeType: 'LAB', scopeId: 11, scopeName: '', blockedDate: '2026-09-30', reason: '实验室维护' },
  { id: 33, scopeType: 'DEVICE', scopeId: 102, scopeName: '', blockedDate: '2026-10-02', reason: '年度校准' },
  { id: 36, scopeType: 'DEVICE', scopeId: 103, scopeName: '', blockedDate: '2026-10-05', reason: '实验室设备校准' },
  { id: 34, scopeType: 'DEVICE', scopeId: 999, scopeName: '', blockedDate: '2026-10-03', reason: '未知设备' },
]

const TableStub = defineComponent({
  name: 'ElTableStub',
  props: ['data'],
  setup(props, { slots }) {
    return () => {
      const rows = props.data as unknown[]
      if (rows.length === 0) return h('div', { class: 'table-stub' }, slots.empty?.())
      return h('div', { class: 'table-stub' }, rows.map((row) =>
        h('div', { class: 'table-row' }, (slots.default?.() ?? []).map((column) => cloneVNode(column, { row }))),
      ))
    }
  },
})
const ColumnStub = defineComponent({
  name: 'ElTableColumnStub',
  props: ['row', 'prop'],
  setup(props, { slots }) {
    return () => h('div', { class: 'table-cell' }, slots.default?.({ row: props.row }) ?? String((props.row as Record<string, unknown>)?.[String(props.prop)] ?? ''))
  },
})
const SelectStub = defineComponent({
  name: 'ElSelectStub',
  props: ['modelValue'],
  emits: ['update:modelValue', 'change'],
  setup(_, { emit, slots }) {
    const onChange = (event: Event) => {
      const raw = (event.target as HTMLSelectElement).value
      const value = raw === 'true' ? true : raw === 'false' ? false : /^\d+$/.test(raw) ? Number(raw) : raw
      emit('update:modelValue', value)
      emit('change', value)
    }
    return () => h('select', { value: _.modelValue ?? '', onChange }, slots.default?.())
  },
})

const stubs = {
  PageHeader: { props: ['title'], template: '<header>{{ title }}<slot name="actions" /></header>' },
  GradientButton: { props: ['loading'], emits: ['click'], template: '<button class="gradient-button" :disabled="loading" @click="$emit(\'click\')"><slot /></button>' },
  TextButton: { emits: ['click'], template: '<button class="text-button" @click="$emit(\'click\')"><slot /></button>' },
  Tag: { template: '<span class="tag-stub"><slot /></span>' },
  'el-tabs': { props: ['modelValue'], emits: ['update:modelValue'], template: '<div class="tabs-stub"><button class="open-blackouts" @click="$emit(\'update:modelValue\', \'blackouts\')">不可预约日</button><slot /></div>' },
  'el-tab-pane': { props: ['name'], template: '<section class="tab-pane-stub"><slot /></section>' },
  'el-form': { template: '<form><slot /></form>' },
  'el-form-item': { props: ['label'], template: '<label>{{ label }}<slot /></label>' },
  'el-select': SelectStub,
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
  'el-input': { props: ['modelValue'], emits: ['update:modelValue', 'change'], template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" @change="$emit(\'change\')" />' },
  'el-date-picker': { props: ['modelValue'], emits: ['update:modelValue'], template: '<input type="date" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
  'el-input-number': { props: ['modelValue'], emits: ['update:modelValue'], template: '<input type="number" :value="modelValue" @input="$emit(\'update:modelValue\', Number($event.target.value))" />' },
  'el-table': TableStub,
  'el-table-column': ColumnStub,
  'el-pagination': { props: ['currentPage'], emits: ['current-change'], template: '<button class="next-page" @click="$emit(\'current-change\', currentPage + 1)">下一页</button>' },
}

function mountRules() {
  return mount(RulesPanel, { global: { stubs, directives: { loading: () => {} } } })
}
function mountScheduling() {
  return mount(SchedulingIndex, { global: { stubs, directives: { loading: () => {} } } })
}
function setup(wrapper: ReturnType<typeof mount>) {
  return (wrapper.vm as unknown as { $: { setupState: Record<string, any> } }).$.setupState
}

describe('reservation policy and blackout administration journeys', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    user.userId = 11
    user.roles = ['SYS_ADMIN']
    api.listColleges.mockResolvedValue(colleges)
    api.listAllLabs.mockResolvedValue(labs)
    api.listBlackouts.mockResolvedValue(blackoutRows)
    api.createBlackout.mockImplementation(async (payload: Record<string, unknown>) => ({ id: 40, scopeName: '', ...payload }))
    api.deleteBlackout.mockResolvedValue(undefined)
    api.listReservationRules.mockResolvedValue({ items: ruleRows, page: 1, pages: 3, total: 45, truncated: true })
    api.saveReservationRule.mockResolvedValue(undefined)
    api.deleteReservationRule.mockResolvedValue(undefined)
    remote.loadInitial.mockResolvedValue(undefined)
    remote.search.mockResolvedValue(undefined)
    dialogs.confirm.mockResolvedValue('confirm')
  })

  it('loads policy catalogs, renders every scope/category, and pages to the requested result', async () => {
    const wrapper = mountRules()
    await flushPromises()
    const state = setup(wrapper)
    expect(api.listReservationRules).toHaveBeenCalledWith(1, 20, { scopeType: undefined, userCategory: undefined, scopeId: undefined })
    expect(wrapper.text()).toContain('全校')
    expect(wrapper.text()).toContain('学院')
    expect(wrapper.text()).toContain('实验室')
    expect(wrapper.text()).toContain('设备')
    expect(wrapper.text()).toContain('所有用户')
    expect(wrapper.text()).toContain('普通用户')
    expect(wrapper.text()).toContain('实验室负责人')
    expect(wrapper.text()).toContain('自动确认')
    expect(wrapper.text()).toContain('需审批')
    expect(wrapper.text()).toContain('继承')
    expect(wrapper.find('.rules-panel__limit-hint').exists()).toBe(true)
    expect(state.reachableTotal).toBe(45)
    state.form.scopeType = 'LAB'
    expect(state.visibleLabs.map((row: any) => row.id)).toEqual([11, 12, 13])
    expect(state.scopeOptions.map((row: any) => row.id)).toEqual([11, 12, 13])
    state.form.scopeType = 'DEVICE'
    expect(state.visibleDevices.map((row: any) => row.id)).toEqual([101, 102, 103, 104, 105])
    expect(state.scopeOptions.find((row: any) => row.id === 102).name).toContain('未分配实验室')
    await wrapper.get('.next-page').trigger('click')
    await flushPromises()
    expect(api.listReservationRules).toHaveBeenLastCalledWith(2, 20, expect.any(Object))

    state.pages = 1
    state.truncated = false
    state.rows = []
    await nextTick()
    expect(wrapper.find('.rules-panel__limit-hint').exists()).toBe(false)
    expect(wrapper.find('.rules-panel__pagination').exists()).toBe(false)
    expect(wrapper.text()).toContain('当前范围尚无显式规则')
  })

  it('drives every policy editor and filter control through its emitted UI event', async () => {
    const wrapper = mountRules()
    await flushPromises()
    const state = setup(wrapper)
    const selects = wrapper.findAll('select')
    expect(selects.length).toBeGreaterThanOrEqual(6)

    await selects[0].setValue('DEVICE')
    await nextTick()
    expect(state.form.scopeType).toBe('DEVICE')
    await selects[1].setValue('101')
    await selects[2].setValue('ALL')
    const numericInputs = wrapper.findAll('.rules-panel__grid input')
    await numericInputs[0].setValue('6')
    await numericInputs[1].setValue('30')
    await selects[3].setValue('false')
    await nextTick()
    expect(state.form.maxBookingDays).toBe(6)
    expect(state.form.maxAdvanceDays).toBe(30)
    expect(state.form.approvalRequired).toBe(false)

    await wrapper.findAll('.rules-panel__inherit')[0].trigger('click')
    await wrapper.findAll('.rules-panel__inherit')[0].trigger('click')
    expect(state.form.maxBookingDays).toBeUndefined()
    expect(state.form.maxAdvanceDays).toBeUndefined()

    await selects[4].setValue('LAB')
    await selects[5].setValue('STUDENT')
    const filterInput = wrapper.get('.rules-panel__filters input')
    await filterInput.setValue('12')
    await filterInput.trigger('keyup.enter')
    await flushPromises()
    expect(api.listReservationRules).toHaveBeenLastCalledWith(1, 20, { scopeType: 'LAB', userCategory: 'STUDENT', scopeId: 12 })

    const firstRowButtons = wrapper.findAll('.rules-panel__table .table-row')[0].findAll('.text-button')
    await firstRowButtons[1].trigger('click')
    await flushPromises()
    expect(api.deleteReservationRule).toHaveBeenCalledWith(1)
  })

  it('filters manager scope catalogs and protects inaccessible global or foreign resources', async () => {
    user.roles = ['LAB_ADMIN']
    const wrapper = mountRules()
    await flushPromises()
    const state = setup(wrapper)

    expect(state.visibleColleges.map((row: any) => row.id)).toEqual([1])
    expect(state.visibleLabs.map((row: any) => row.id)).toEqual([11, 12])
    expect(state.visibleDevices.map((row: any) => row.id)).toEqual([101, 103])
    state.form.scopeType = 'GLOBAL'
    await state.load()
    expect(state.form.scopeType).toBe('COLLEGE')
    expect(state.scopeOptions.map((row: any) => row.id)).toEqual([1])
    state.clearForm()
    expect(state.form.scopeType).toBe('COLLEGE')
  })

  it('defaults an administrator with no managed college to laboratory scope', async () => {
    user.roles = []
    user.userId = 999
    const wrapper = mountRules()
    await flushPromises()
    const state = setup(wrapper)
    expect(state.visibleColleges).toEqual([])
    expect(state.form.scopeType).toBe('LAB')
    expect(state.scopeOptions).toEqual([])
    state.clearForm()
    expect(state.form.scopeType).toBe('LAB')
  })

  it('validates, saves, edits and clears rules while preserving inheritance semantics', async () => {
    const wrapper = mountRules()
    await flushPromises()
    const state = setup(wrapper)

    state.form.scopeId = undefined
    await state.save()
    expect(messages.warning).toHaveBeenCalledWith('当前范围没有可配置对象')
    state.form.scopeId = 1
    await state.save()
    expect(messages.warning).toHaveBeenCalledWith('至少设置一项规则，未设置的项目会继承上级')

    state.form.maxBookingDays = 4
    state.form.approvalRequired = false
    await state.save()
    expect(api.saveReservationRule).toHaveBeenCalledWith({
      scopeType: 'COLLEGE', scopeId: 1, userCategory: 'STUDENT',
      maxBookingDays: 4, maxAdvanceDays: null, approvalRequired: false,
    })
    expect(messages.success).toHaveBeenCalledWith('预约规则已保存')

    state.form.maxBookingDays = undefined
    state.form.maxAdvanceDays = 14
    await state.save()
    expect(api.saveReservationRule).toHaveBeenLastCalledWith({
      scopeType: 'COLLEGE', scopeId: 1, userCategory: 'STUDENT',
      maxBookingDays: null, maxAdvanceDays: 14, approvalRequired: false,
    })

    state.edit(ruleRows[2])
    expect(state.form.scopeType).toBe('LAB')
    expect(state.form.scopeId).toBe(11)
    expect(state.form.maxBookingDays).toBeUndefined()
    expect(state.form.approvalRequired).toBe(false)
    state.form.scopeType = 'GLOBAL'
    state.clearForm()
    expect(state.form.scopeType).toBe('GLOBAL')
    expect(state.form.scopeId).toBe(0)
    expect(state.form.maxBookingDays).toBeUndefined()
    expect(state.form.approvalRequired).toBeUndefined()
    state.form.scopeType = 'DEVICE'
    state.onScopeChange()
    expect(state.form.scopeId).toBe(101)
    state.form.maxBookingDays = 4
    state.form.maxAdvanceDays = 10
    await nextTick()
    const inheritButtons = wrapper.findAll('.rules-panel__inherit')
    expect(inheritButtons.length).toBeGreaterThan(0)
    for (const button of inheritButtons) await button.trigger('click')
    expect(state.form.maxBookingDays).toBeUndefined()
  })

  it('handles rule persistence failures, invalid filters, confirm cancellation and delete paging', async () => {
    const wrapper = mountRules()
    await flushPromises()
    const state = setup(wrapper)
    state.form.maxBookingDays = 5
    api.saveReservationRule.mockRejectedValueOnce(new Error('save failed'))
    await state.save()
    expect(state.saving).toBe(false)

    state.filterScopeId = 'abc'
    state.onFilterChange()
    expect(messages.warning).toHaveBeenCalledWith('范围 ID 只能填写非负整数')
    state.filterScopeId = '11'
    state.filterScopeType = 'LAB'
    state.filterUserCategory = 'LAB_ADMIN'
    state.onFilterChange()
    await flushPromises()
    expect(api.listReservationRules).toHaveBeenLastCalledWith(1, 20, { scopeType: 'LAB', userCategory: 'LAB_ADMIN', scopeId: 11 })

    dialogs.confirm.mockRejectedValueOnce(new Error('cancel'))
    await state.remove(ruleRows[0])
    expect(api.deleteReservationRule).not.toHaveBeenCalled()

    state.page = 2
    state.rows = [ruleRows[0]]
    await state.remove(ruleRows[0])
    await flushPromises()
    expect(api.deleteReservationRule).toHaveBeenCalledWith(1)
    expect(api.listReservationRules).toHaveBeenLastCalledWith(1, 20, expect.any(Object))
    expect(messages.success).toHaveBeenCalledWith('规则已移除，预约将继承上级设置')

    state.rows = [ruleRows[0], ruleRows[1]]
    state.page = 1
    api.deleteReservationRule.mockResolvedValueOnce(undefined)
    await state.remove(ruleRows[0])
    await flushPromises()
    expect(api.listReservationRules).toHaveBeenLastCalledWith(1, 20, expect.any(Object))

    state.rows = [ruleRows[0], ruleRows[1]]
    state.page = 1
    api.deleteReservationRule.mockRejectedValueOnce(new Error('delete failed'))
    await state.remove(ruleRows[0])
    expect(state.loading).toBe(false)

    api.listReservationRules.mockRejectedValueOnce(new Error('list failed'))
    await state.load()
    expect(state.loading).toBe(false)
    await nextTick()
    await wrapper.find('.rules-panel__table .table-row .text-button').trigger('click')
    expect(state.form.scopeType).toBe('GLOBAL')
  })

  it('loads blackouts on first tab visit, resolves names, and avoids repeated option requests', async () => {
    const wrapper = mountScheduling()
    const state = setup(wrapper)
    await wrapper.get('.open-blackouts').trigger('click')
    await flushPromises()
    await nextTick()

    expect(api.listBlackouts).toHaveBeenCalledOnce()
    expect(api.listColleges).toHaveBeenCalled()
    expect(remote.loadInitial).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('光电学院')
    expect(wrapper.text()).toContain('光学实验室')
    expect(wrapper.text()).toContain('光谱仪')
    expect(wrapper.text()).toContain('#999')
    expect(wrapper.text()).toContain('学院')
    expect(wrapper.text()).toContain('实验室')
    expect(wrapper.text()).toContain('设备')

    const collegeRequests = api.listColleges.mock.calls.length
    await state.load()
    expect(api.listColleges).toHaveBeenCalledTimes(collegeRequests)
    state.form.scopeType = 'LAB'
    state.onScopeTypeChange()
    expect(state.form.scopeId).toBe(11)
    state.form.scopeType = 'DEVICE'
    expect(state.scopeOptions.map((option: any) => option.id)).toEqual([101, 102, 103, 104, 105])
    expect(state.typeLabel('DEVICE')).toBe('设备')

    state.form.scopeId = 2
    state.optionsLoaded = false
    await state.loadOptions()
    expect(state.form.scopeId).toBe(2)

    state.activeTab = 'policies'
    await nextTick()
    state.activeTab = 'blackouts'
    await flushPromises()
    expect(api.listBlackouts).toHaveBeenCalledTimes(2)
  })

  it('validates, creates sorted blackout dates, and recovers from create failures', async () => {
    const wrapper = mountScheduling()
    const state = setup(wrapper)
    state.activeTab = 'blackouts'
    await flushPromises()
    state.form.scopeId = undefined
    state.form.blockedDate = ''
    state.form.reason = 'x'
    await state.submit()
    expect(messages.warning).toHaveBeenCalledWith('请完整填写范围、日期和原因')

    state.form.scopeType = 'COLLEGE'
    state.form.scopeId = 1
    state.form.blockedDate = ''
    state.form.reason = '有效原因'
    await state.submit()
    state.form.blockedDate = '2026-10-03'
    state.form.reason = 'x'
    await state.submit()
    expect(api.createBlackout).not.toHaveBeenCalled()

    state.form.blockedDate = '2026-10-04'
    state.form.reason = '  临时封闭  '
    await state.submit()
    expect(api.createBlackout).toHaveBeenCalledWith({ scopeType: 'COLLEGE', scopeId: 1, blockedDate: '2026-10-04', reason: '临时封闭' })
    expect(state.rows[0].blockedDate).toBe('2026-09-30')
    expect(state.rows[state.rows.length - 1].blockedDate).toBe('2026-10-05')
    expect(state.form.blockedDate).toBe('')
    expect(messages.success).toHaveBeenCalledWith('不可预约日期已生效')

    api.createBlackout.mockResolvedValueOnce({ id: 41, scopeType: 'COLLEGE', scopeId: 1, scopeName: '服务器返回的名称', blockedDate: '2026-10-06', reason: '系统停机' })
    state.form.blockedDate = '2026-10-06'
    state.form.reason = '系统停机'
    await state.submit()
    expect(state.rows.some((row: any) => row.scopeName === '服务器返回的名称')).toBe(true)

    api.createBlackout.mockRejectedValueOnce(new Error('create failed'))
    state.form.blockedDate = '2026-10-05'
    state.form.reason = '年度维护'
    await state.submit()
    expect(state.submitting).toBe(false)
  })

  it('submits a blackout through the visible scope, date, and reason controls', async () => {
    const wrapper = mountScheduling()
    await wrapper.get('.open-blackouts').trigger('click')
    await flushPromises()
    const state = setup(wrapper)
    const formSelects = wrapper.findAll('.schedule-page__form select')
    await formSelects[0].setValue('LAB')
    await nextTick()
    await formSelects[1].setValue('11')
    await wrapper.get('.schedule-page__form input[type="date"]').setValue('2026-11-01')
    await wrapper.find('.schedule-page__form input:not([type="date"])').setValue('设备检修')
    await wrapper.get('.schedule-page__form-actions .gradient-button').trigger('click')
    await flushPromises()

    expect(state.form.scopeType).toBe('LAB')
    expect(state.form.scopeId).toBe(11)
    expect(api.createBlackout).toHaveBeenCalledWith({ scopeType: 'LAB', scopeId: 11, blockedDate: '2026-11-01', reason: '设备检修' })
  })

  it('treats blackout confirmation cancellation and delete failures safely', async () => {
    const wrapper = mountScheduling()
    const state = setup(wrapper)
    state.activeTab = 'blackouts'
    await flushPromises()

    dialogs.confirm.mockRejectedValueOnce(new Error('cancel'))
    await state.remove(blackoutRows[0])
    expect(api.deleteBlackout).not.toHaveBeenCalled()

    await state.remove(blackoutRows[0])
    expect(api.deleteBlackout).toHaveBeenCalledWith(31)
    expect(messages.success).toHaveBeenCalledWith('日期限制已解除')

    await nextTick()
    const firstTableButton = wrapper.find('.schedule-page__table .table-row .text-button')
    await firstTableButton.trigger('click')
    await flushPromises()
    expect(api.deleteBlackout).toHaveBeenCalledTimes(2)

    api.deleteBlackout.mockRejectedValueOnce(new Error('delete failed'))
    await state.remove(blackoutRows[1])
    expect(state.rows.some((row: any) => row.id === 32)).toBe(true)
  })

  it('keeps the blackout form usable when its initial data request fails', async () => {
    api.listBlackouts.mockRejectedValueOnce(new Error('list failed'))
    const wrapper = mountScheduling()
    const state = setup(wrapper)
    state.activeTab = 'blackouts'
    await flushPromises()
    expect(state.loading).toBe(false)
    expect(state.rows).toEqual([])
    expect(wrapper.find('.schedule-page__empty').exists()).toBe(true)
  })
})
