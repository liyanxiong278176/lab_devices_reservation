import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { cloneVNode, defineComponent, h, nextTick } from 'vue'

const api = vi.hoisted(() => ({
  archiveDeviceDocument: vi.fn(),
  deviceCalendar: vi.fn(),
  devicePoolAvailability: vi.fn(),
  downloadDeviceDocument: vi.fn(),
  getDevice: vi.fn(),
  getDevicePool: vi.fn(),
  joinWaitlist: vi.fn(),
  listDeviceDocuments: vi.fn(),
  uploadDeviceDocument: vi.fn(),
}))
const messages = vi.hoisted(() => ({ warning: vi.fn(), success: vi.fn() }))
const dialogs = vi.hoisted(() => ({ confirm: vi.fn(), prompt: vi.fn() }))
const route = vi.hoisted(() => ({ params: { id: '42' }, query: {} as Record<string, unknown> }))
const router = vi.hoisted(() => ({ push: vi.fn() }))

vi.mock('@/api/device', () => ({
  archiveDeviceDocument: api.archiveDeviceDocument,
  deviceCalendar: api.deviceCalendar,
  devicePoolAvailability: api.devicePoolAvailability,
  downloadDeviceDocument: api.downloadDeviceDocument,
  getDevice: api.getDevice,
  getDevicePool: api.getDevicePool,
  listDeviceDocuments: api.listDeviceDocuments,
  uploadDeviceDocument: api.uploadDeviceDocument,
}))
vi.mock('@/api/reservation', () => ({ joinWaitlist: api.joinWaitlist }))
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => router }))
vi.mock('@/router', () => ({ readSpaDepth: () => 0 }))
vi.mock('element-plus', () => ({ ElMessage: messages, ElMessageBox: dialogs }))

import DeviceDetail from '../Detail.vue'

const baseDevice = {
  id: 42, name: '激光显微镜', status: 'IDLE', brand: 'Olympus', model: 'BX-1', labName: '光学实验室',
  categoryName: '显微镜', maxReservationDays: 5, needApproval: 1, description: '高精度成像设备',
  assetCode: 'LAB-042', serialNumber: 'SN-42', specs: '100x', riskLevel: 'HIGH', allowExternalLoan: true,
}
const documents = [
  { id: 1, documentType: 'MANUAL', title: '设备手册', originalName: 'manual.pdf', sizeBytes: 5120 },
  { id: 2, documentType: 'SOP', title: '操作规程', originalName: 'sop.md', sizeBytes: 1024 * 1024 },
  { id: 3, documentType: 'SAFETY', title: '安全须知', originalName: 'safety.txt', sizeBytes: 512 },
]
const calendarRows = [
  { date: '2026-09-28', status: 'IN_USE', reservationId: 100, reason: '现场使用中' },
  { date: '2026-09-29', status: 'APPROVED', reservationId: 101 },
  { date: '2026-09-30', status: 'PENDING', reservationId: 102 },
  { date: '2026-10-01', status: 'MAINTENANCE_RESTRICTION', reason: '计划停机' },
  { date: '2026-10-02', status: 'BLACKOUT' },
  { date: '2026-10-03', status: 'UNKNOWN' },
]

const TableStub = defineComponent({
  name: 'ElTableStub',
  props: ['data'],
  setup(props, { slots }) {
    return () => {
      const rows = props.data as unknown[]
      if (!rows.length) return h('div', { class: 'table-empty' }, slots.empty?.())
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
    return () => h('div', { class: 'table-cell' }, slots.default?.({ row: props.row }) ?? String((props.row as any)?.[props.prop] ?? ''))
  },
})
const SelectStub = defineComponent({
  name: 'ElSelectStub',
  props: ['modelValue'],
  emits: ['update:modelValue', 'change'],
  setup(props, { emit, slots }) {
    return () => h('select', {
      value: props.modelValue ?? '',
      onChange: (event: Event) => {
        const value = (event.target as HTMLSelectElement).value
        emit('update:modelValue', value)
        emit('change', value)
      },
    }, slots.default?.())
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
const stubs = {
  PageHeader: { props: ['title', 'subtitle'], template: '<header><h1>{{ title }}</h1><span>{{ subtitle }}</span><slot name="actions" /></header>' },
  StatusDot: { props: ['status', 'label'], template: '<span class="status-dot">{{ status }}</span>' },
  GradientButton: { props: ['disabled', 'loading'], emits: ['click'], template: '<button class="gradient-button" :disabled="disabled || loading" @click="$emit(\'click\')"><slot /></button>' },
  GhostButton: { emits: ['click'], template: '<button class="ghost-button" @click="$emit(\'click\')"><slot /></button>' },
  TextButton: { emits: ['click'], template: '<button class="text-button" @click="$emit(\'click\')"><slot /></button>' },
  Panel: { template: '<section><slot /></section>' },
  Tag: { props: ['variant'], template: '<span class="tag" :data-variant="variant"><slot /></span>' },
  'el-tabs': { props: ['modelValue'], emits: ['update:modelValue'], template: '<div><button class="calendar-tab" @click="$emit(\'update:modelValue\', \'calendar\')">日历</button><slot /></div>' },
  'el-tab-pane': { template: '<section><slot /></section>' },
  'el-alert': { props: ['title'], template: '<aside>{{ title }}</aside>' },
  'el-table': TableStub,
  'el-table-column': ColumnStub,
  'el-date-picker': { emits: ['update:modelValue'], template: '<input class="date-picker" @input="$emit(\'update:modelValue\', new Date($event.target.value + \'T12:00:00\'))" />' },
  'el-dialog': { props: ['modelValue', 'title'], emits: ['update:modelValue'], template: '<aside v-if="modelValue" class="dialog"><h2>{{ title }}</h2><slot /><button class="dialog-model-close" @click="$emit(\'update:modelValue\', false)">close</button><footer><slot name="footer" /></footer></aside>' },
  'el-form': { template: '<form><slot /></form>' },
  'el-form-item': { props: ['label'], template: '<label>{{ label }}<slot /></label>' },
  'el-radio-group': RadioGroupStub,
  'el-radio': { props: ['value'], template: '<button type="button" :data-radio-value="value"><slot /></button>' },
  'el-switch': { props: ['modelValue'], emits: ['update:modelValue'], template: '<input type="checkbox" :checked="modelValue" @change="$emit(\'update:modelValue\', $event.target.checked)" />' },
  'el-input': { props: ['modelValue', 'placeholder'], emits: ['update:modelValue'], template: '<input :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
  'el-select': SelectStub,
}

function mountPage() {
  return mount(DeviceDetail, { global: { stubs, directives: { loading: () => {}, permission: () => {} } } })
}
function setup(wrapper: ReturnType<typeof mount>) {
  return (wrapper.vm as any).$?.setupState as Record<string, any>
}
async function settledPage() {
  const wrapper = mountPage()
  await flushPromises()
  return wrapper
}

describe('device detail booking, calendar, and document journeys', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    route.params.id = '42'
    route.query = {}
    router.push.mockResolvedValue(undefined)
    api.getDevice.mockResolvedValue(baseDevice)
    api.getDevicePool.mockResolvedValue(baseDevice)
    api.deviceCalendar.mockResolvedValue(calendarRows)
    api.devicePoolAvailability.mockResolvedValue([])
    api.listDeviceDocuments.mockResolvedValue(structuredClone(documents))
    api.archiveDeviceDocument.mockResolvedValue(undefined)
    api.downloadDeviceDocument.mockResolvedValue(undefined)
    api.uploadDeviceDocument.mockResolvedValue({ id: 4, documentType: 'SAFETY', title: '新文档', originalName: 'new.pdf', sizeBytes: 1024 })
    api.joinWaitlist.mockResolvedValue(undefined)
    dialogs.confirm.mockResolvedValue('confirm')
    dialogs.prompt.mockResolvedValue({ value: '  课程实验  ' })
  })

  it('renders device facts, status, documents, and navigates to booking and repair', async () => {
    const wrapper = await settledPage()
    expect(api.getDevice).toHaveBeenCalledWith(42)
    expect(api.deviceCalendar).toHaveBeenCalledOnce()
    expect(api.listDeviceDocuments).toHaveBeenCalledWith(42)
    expect(wrapper.text()).toContain('激光显微镜')
    expect(wrapper.text()).toContain('Olympus · BX-1 · 光学实验室')
    expect(wrapper.text()).toContain('需审批')
    expect(wrapper.text()).toContain('LAB-042')
    expect(wrapper.text()).toContain('允许外借')
    expect(wrapper.text()).toContain('1.0 MB')
    expect(wrapper.text()).toContain('操作规程')
    await wrapper.get('.device-detail__actionbar .gradient-button').trigger('click')
    await wrapper.get('.device-detail__actionbar .ghost-button').trigger('click')
    expect(router.push).toHaveBeenNthCalledWith(1, { name: 'reservation-create', query: { deviceId: '42' } })
    expect(router.push).toHaveBeenNthCalledWith(2, { name: 'repair-submit', query: { deviceId: '42' } })
    await wrapper.findAll('.device-document .text-button')[0].trigger('click')
    expect(api.downloadDeviceDocument).toHaveBeenCalledWith(documents[0])
  })

  it('loads a grouped resource pool and sends booking to the pool allocation flow', async () => {
    route.query = { poolId: '17' }
    api.getDevicePool.mockResolvedValue({
      ...baseDevice,
      poolId: 17,
      poolQuantity: 2,
      poolIdleQuantity: 2,
    })
    const wrapper = await settledPage()
    expect(api.getDevicePool).toHaveBeenCalledWith(17)
    expect(api.getDevice).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('2 台')
    await wrapper.get('.device-detail__actionbar .gradient-button').trigger('click')
    expect(router.push).toHaveBeenCalledWith({
      name: 'reservation-create',
      query: { poolId: '17' },
    })
  })

  it('handles missing device fields, unknown status, and a maintenance warning that blocks booking', async () => {
    api.getDevice.mockResolvedValueOnce({ id: 42, name: '无品牌设备', status: 'CALIBRATING', maintenanceWarning: '校准逾期' })
    api.listDeviceDocuments.mockResolvedValueOnce([])
    const wrapper = await settledPage()
    expect(wrapper.text()).toContain('未填写品牌 / 型号')
    expect(wrapper.text()).toContain('CALIBRATING')
    expect(wrapper.text()).toContain('校准逾期')
    expect(wrapper.text()).toContain('未分类')
    expect(wrapper.text()).toContain('STANDARD')
    expect(wrapper.text()).toContain('限实验室内使用')
    expect(wrapper.text()).toContain('暂无设备文档')
    expect(wrapper.get('.device-detail__actionbar .gradient-button').attributes('disabled')).toBeDefined()
    await wrapper.get('.device-detail__actionbar .gradient-button').trigger('click')
    expect(router.push).not.toHaveBeenCalled()
  })

  it('loads the Monday-to-Sunday calendar, formats status/reasons, and joins or cancels a waitlist', async () => {
    const wrapper = await settledPage()
    await wrapper.get('.calendar-tab').trigger('click')
    await nextTick()
    await wrapper.get('.date-picker').setValue('2026-09-27')
    await flushPromises()
    expect(api.deviceCalendar).toHaveBeenLastCalledWith(42, '2026-09-21', '2026-09-27')
    expect(wrapper.text()).toContain('现场使用中')
    expect(wrapper.text()).toContain('已预约')
    expect(wrapper.text()).toContain('预约待审批')
    expect(wrapper.text()).toContain('计划停机')
    expect(wrapper.text()).toContain('不可预约日')
    expect(wrapper.text()).toContain('UNKNOWN')
    expect(wrapper.findAll('.table-row')).toHaveLength(calendarRows.length)
    await wrapper.findAll('.table-row')[1].find('.text-button').trigger('click')
    await flushPromises()
    expect(api.joinWaitlist).toHaveBeenCalledWith({ deviceId: 42, reservationDate: '2026-09-29', purpose: '课程实验' })
    expect(messages.success).toHaveBeenCalledWith('已加入候补队列')
    dialogs.prompt.mockRejectedValueOnce('cancel')
    await wrapper.findAll('.table-row')[2].find('.text-button').trigger('click')
    await flushPromises()
    expect(messages.success).toHaveBeenCalledOnce()
  })

  it('supports waitlist request failures and clears calendar data when its request fails', async () => {
    api.deviceCalendar.mockResolvedValueOnce(calendarRows).mockRejectedValueOnce(new Error('offline'))
    const wrapper = await settledPage()
    const state = setup(wrapper)
    await wrapper.get('.calendar-tab').trigger('click')
    await wrapper.get('.date-picker').setValue('2026-09-27')
    await flushPromises()
    expect(state.calendar).toEqual([])
    dialogs.prompt.mockResolvedValueOnce({ value: 'valid purpose' })
    api.joinWaitlist.mockRejectedValueOnce(new Error('offline'))
    state.joinWaitlistForDate('2026-09-28')
    await flushPromises()
    expect(api.joinWaitlist).toHaveBeenCalledOnce()
  })

  it('validates and uploads a document, normalizes the version, and handles upload errors', async () => {
    const wrapper = await settledPage()
    const state = setup(wrapper)
    await wrapper.get('.device-detail__documents-head .ghost-button').trigger('click')
    await wrapper.get('.dialog-model-close').trigger('click')
    expect(state.documentDialogVisible).toBe(false)
    await wrapper.get('.device-detail__documents-head .ghost-button').trigger('click')
    await wrapper.get('.dialog footer .ghost-button').trigger('click')
    expect(state.documentDialogVisible).toBe(false)
    await wrapper.get('.device-detail__documents-head .ghost-button').trigger('click')
    await wrapper.get('.dialog .gradient-button').trigger('click')
    expect(messages.warning).toHaveBeenCalledWith('请填写文档标题并选择文件')
    const dialog = wrapper.get('.dialog')
    const textInputs = dialog.findAll('input:not([type="file"]):not([type="checkbox"])')
    await textInputs[0].setValue('A')
    const file = new File(['test'], 'manual.pdf', { type: 'application/pdf' })
    const fileInput = dialog.get('input[type="file"]')
    Object.defineProperty(fileInput.element, 'files', { configurable: true, value: [file] })
    await fileInput.trigger('change')
    await state.submitDocument()
    expect(api.uploadDeviceDocument).not.toHaveBeenCalled()
    await textInputs[0].setValue('  安全手册  ')
    await textInputs[1].setValue('   ')
    await wrapper.get('[data-radio-value="SAFETY"]').trigger('click')
    await dialog.get('input[type="checkbox"]').setValue(true)
    await nextTick()
    await state.submitDocument()
    expect(api.uploadDeviceDocument).toHaveBeenCalledWith(42, {
      documentType: 'SAFETY', title: '安全手册', version: '1.0', requiresAck: true, file,
    })
    expect(state.documents[0].title).toBe('新文档')
    expect(state.documentUploading).toBe(false)

    await wrapper.get('.device-detail__documents-head .ghost-button').trigger('click')
    const retryDialog = wrapper.get('.dialog')
    await retryDialog.findAll('input:not([type="file"]):not([type="checkbox"])')[0].setValue('错误上传文档')
    const retryFile = new File(['test'], 'error.pdf', { type: 'application/pdf' })
    const retryInput = retryDialog.get('input[type="file"]')
    Object.defineProperty(retryInput.element, 'files', { configurable: true, value: [retryFile] })
    await retryInput.trigger('change')
    api.uploadDeviceDocument.mockRejectedValueOnce(new Error('offline'))
    await state.submitDocument()
    expect(state.documentUploading).toBe(false)
  })

  it('archives documents with confirmation, cancellation, and request failure paths', async () => {
    const wrapper = await settledPage()
    const state = setup(wrapper)
    dialogs.confirm.mockRejectedValueOnce(new Error('cancel'))
    await state.removeDocument(documents[0] as any)
    expect(api.archiveDeviceDocument).not.toHaveBeenCalled()
    api.archiveDeviceDocument.mockRejectedValueOnce(new Error('offline'))
    dialogs.confirm.mockResolvedValueOnce('confirm')
    await state.removeDocument(documents[1] as any)
    expect(state.documents).toHaveLength(3)
    dialogs.confirm.mockResolvedValueOnce('confirm')
    await wrapper.findAll('.device-document .text-button')[1].trigger('click')
    await flushPromises()
    expect(api.archiveDeviceDocument).toHaveBeenCalledWith(42, 1)
    expect(state.documents.map((item: any) => item.id)).toEqual([2, 3])
    expect(messages.success).toHaveBeenCalledWith('文档已归档')
  })

  it('reports load failures and reads selected files through the file input', async () => {
    api.getDevice.mockRejectedValueOnce(new Error('offline'))
    api.listDeviceDocuments.mockRejectedValueOnce(new Error('offline'))
    const wrapper = await settledPage()
    const state = setup(wrapper)
    expect(state.device).toBeNull()
    expect(state.loading).toBe(false)
    expect(state.documents).toEqual([])
    expect(state.statusLabelText).toBe('')
    expect(state.keyChips).toEqual([])
    await wrapper.get('.device-detail__documents-head .ghost-button').trigger('click')
    const file = new File(['doc'], 'guide.pdf', { type: 'application/pdf' })
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
    await input.trigger('change')
    expect(state.documentFile).toBe(file)
    Object.defineProperty(input.element, 'files', { configurable: true, value: [] })
    await input.trigger('change')
    expect(state.documentFile).toBeNull()
  })
})
