import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import dayjs from 'dayjs'

const mocks = vi.hoisted(() => ({
  route: { query: { deviceId: '42', startDate: '2026-10-01', endDate: '2026-10-02' } as Record<string, unknown> },
  push: vi.fn(),
  back: vi.fn(),
  getDevice: vi.fn(),
  getDevicePool: vi.fn(),
  listSafetyDocuments: vi.fn(),
  myQualification: vi.fn(),
  submitQualification: vi.fn(),
  uploadQualificationMaterial: vi.fn(),
  acknowledgeSafety: vi.fn(),
  deviceAvailability: vi.fn(),
  devicePoolAvailability: vi.fn(),
  createReservation: vi.fn(),
  joinWaitlist: vi.fn(),
  preflightReservation: vi.fn(),
  success: vi.fn(),
  warning: vi.fn(),
  valid: true,
  validationThrows: false,
}))

vi.mock('vue-router', () => ({
  useRoute: () => mocks.route,
  useRouter: () => ({ push: mocks.push, back: mocks.back }),
}))
vi.mock('@/router', () => ({ readSpaDepth: () => 0 }))
vi.mock('element-plus', () => ({ ElMessage: { success: mocks.success, warning: mocks.warning } }))
vi.mock('@/api/device', () => ({
  getDevice: mocks.getDevice,
  getDevicePool: mocks.getDevicePool,
  listSafetyDocuments: mocks.listSafetyDocuments,
  myQualification: mocks.myQualification,
  submitQualification: mocks.submitQualification,
  uploadQualificationMaterial: mocks.uploadQualificationMaterial,
  acknowledgeSafety: mocks.acknowledgeSafety,
  deviceAvailability: mocks.deviceAvailability,
  devicePoolAvailability: mocks.devicePoolAvailability,
}))
vi.mock('@/api/reservation', () => ({
  createReservation: mocks.createReservation,
  joinWaitlist: mocks.joinWaitlist,
  preflightReservation: mocks.preflightReservation,
}))

import Create from '../Create.vue'

const device = (overrides: Record<string, unknown> = {}) => ({
  id: 42,
  name: '电子显微镜',
  categoryId: 2,
  categoryName: '成像设备',
  labId: 6,
  labName: '材料实验室',
  status: 'IDLE',
  needApproval: 1,
  maxReservationDays: 3,
  ...overrides,
})

const preflight = (overrides: Record<string, unknown> = {}) => ({
  device: device(),
  requested_dates: ['2026-10-01', '2026-10-02'],
  available_dates: ['2026-10-01', '2026-10-02'],
  conflicts: [],
  all_available: true,
  safety_required: false,
  safety_acknowledged: false,
  qualification_required: false,
  qualification_approved: false,
  safety_document_version: null,
  same_device_suggestions: [],
  similar_device_suggestions: [],
  ...overrides,
})

const FormStub = defineComponent({
  props: ['model', 'rules', 'labelPosition'],
  setup(_props, { expose, slots }) {
    expose({ validate: async () => {
      if (mocks.validationThrows) throw new Error('form validation failed')
      return mocks.valid
    } })
    return () => h('form', { class: 'el-form-stub' }, slots.default?.())
  },
})

const stubs = {
  PageHeader: { template: '<header><slot /></header>' },
  GradientButton: {
    props: ['disabled', 'loading'],
    emits: ['click'],
    template: '<button class="gradient" :class="$attrs.class" :disabled="disabled || loading" @click="$emit(\'click\', $event)"><slot /></button>',
  },
  GhostButton: {
    emits: ['click'],
    template: '<button class="ghost" :class="$attrs.class" @click="$emit(\'click\', $event)"><slot /></button>',
  },
  StatusDot: { props: ['status'], template: '<span class="status-dot">{{ status }}</span>' },
  Tag: { props: ['variant'], template: '<span class="tag" :data-variant="variant"><slot /></span>' },
  'el-form': FormStub,
  'el-form-item': { props: ['label'], template: '<label><span>{{ label }}</span><slot /></label>' },
  'el-date-picker': {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template: '<button class="date-picker" @click="$emit(\'update:modelValue\', [\'2026-10-03\', \'2026-10-04\'])">{{ modelValue }}</button>',
  },
  'el-input': {
    props: ['modelValue', 'placeholder'],
    emits: ['update:modelValue'],
    template: '<textarea :placeholder="placeholder" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
  },
  'el-select': {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template: '<select :value="modelValue" @change="$emit(\'update:modelValue\', $event.target.value)"><slot /></select>',
  },
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
  'el-icon': { template: '<span><slot /></span>' },
}

function mountPage() {
  return mount(Create, {
    global: { stubs, directives: { loading: { mounted() {}, updated() {} } } },
  })
}

const setupOf = (wrapper: ReturnType<typeof mount>) =>
  (wrapper.vm as unknown as { $: { setupState: Record<string, unknown> } }).$.setupState

describe('reservation creation page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.route.query = { deviceId: '42', startDate: '2026-10-01', endDate: '2026-10-02' }
    mocks.valid = true
    mocks.validationThrows = false
    mocks.push.mockResolvedValue(undefined)
    mocks.getDevice.mockResolvedValue(device())
    mocks.getDevicePool.mockResolvedValue(device())
    mocks.deviceAvailability.mockImplementation(async (_id: number, start: string) => [
      { date: start, available: true },
      { date: dayjs(start).add(1, 'day').format('YYYY-MM-DD'), available: false, status: 'IN_USE' },
      { date: dayjs(start).add(2, 'day').format('YYYY-MM-DD'), available: true },
    ])
    mocks.devicePoolAvailability.mockResolvedValue([])
    mocks.preflightReservation.mockResolvedValue(preflight())
    mocks.listSafetyDocuments.mockResolvedValue([{ id: 5, title: '设备安全规范', version: '2', url: '/safety.pdf' }])
    mocks.myQualification.mockResolvedValue(null)
    mocks.submitQualification.mockResolvedValue({ id: 3, deviceId: 42, userId: 7, status: 'PENDING' })
    mocks.uploadQualificationMaterial.mockResolvedValue({ asset_id: 88 })
    mocks.acknowledgeSafety.mockResolvedValue(undefined)
    mocks.createReservation.mockResolvedValue({ created: [{ id: 9 }], skipped_conflicts: [] })
    mocks.joinWaitlist.mockResolvedValue(undefined)
  })

  it('loads a device and its calendar, restores a valid route range, and renders preflight data', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await flushPromises()

    expect(mocks.getDevice).toHaveBeenCalledWith(42)
    expect(mocks.deviceAvailability).toHaveBeenCalledWith(
      42,
      dayjs().startOf('day').format('YYYY-MM-DD'),
      dayjs().startOf('day').add(2, 'day').format('YYYY-MM-DD'),
    )
    expect(mocks.preflightReservation).toHaveBeenCalledWith(expect.objectContaining({
      deviceId: 42,
      startDate: '2026-10-01',
      endDate: '2026-10-02',
      purpose: '设备使用',
    }))
    expect(wrapper.text()).toContain('电子显微镜')
    expect(wrapper.text()).toContain('2026-10-01 至 2026-10-02')
    expect(wrapper.text()).toContain('2 天可用')
    expect(wrapper.findAll('.availability-calendar__day')).toHaveLength(3)
    expect(wrapper.findAll('.availability-calendar__day')[1].attributes('disabled')).toBeDefined()
    expect(wrapper.find('.submit-button').attributes('disabled')).toBeDefined()
    await wrapper.findAll('textarea')[0].setValue('设备标定实验')
    await wrapper.findAll('textarea')[1].setValue('COURSE-42')
    expect((setupOf(wrapper).form as { purpose: string; projectReference: string })).toMatchObject({
      purpose: '设备标定实验',
      projectReference: 'COURSE-42',
    })

    await wrapper.find('button.date-picker').trigger('click')
    await flushPromises()
    expect(setupOf(wrapper).selectedDates).toEqual(['2026-10-03', '2026-10-04'])
    await wrapper.find('.availability-calendar__day.is-available').trigger('click')
    await flushPromises()
    const today = dayjs().startOf('day').format('YYYY-MM-DD')
    expect(setupOf(wrapper).selectedDates).toEqual([today, today])
    await wrapper.find('select').setValue('RESEARCH')
    expect((setupOf(wrapper).form as { purposeCategory: string }).purposeCategory).toBe('RESEARCH')
  })

  it('validates route dates and device identifiers while covering date selection and disabled-day rules', async () => {
    mocks.route.query = { deviceId: '42', startDate: 'bad-date', endDate: '2026-09-30' }
    const wrapper = mountPage()
    await flushPromises()
    await flushPromises()
    const setup = setupOf(wrapper)

    expect(wrapper.text()).toContain('尚未选择')
    expect((setup.preflight as unknown)).toBeNull()
    const isDisabledDate = setup.isDisabledDate as (date: Date) => boolean
    expect(isDisabledDate(new Date('2026-09-27T12:00:00'))).toBe(true)
    expect(isDisabledDate(new Date(dayjs().startOf('day').format('YYYY-MM-DD')))).toBe(false)
    expect(isDisabledDate(new Date(dayjs().add(1, 'day').format('YYYY-MM-DD')))).toBe(true)
    expect(isDisabledDate(new Date('2026-11-30T12:00:00'))).toBe(false)

    const selectDate = setup.selectAvailableDate as (date: string) => void
    selectDate('2026-10-05')
    expect(setup.selectedDates).toEqual(['2026-10-05', '2026-10-05'])
    selectDate('2026-10-08')
    expect(setup.selectedDates).toEqual(['2026-10-05', '2026-10-08'])
    setup.selectedDates = ['2026-10-05', '2026-10-05']
    selectDate('2026-10-03')
    expect(setup.selectedDates).toEqual(['2026-10-03', '2026-10-05'])
    await flushPromises()
    expect(wrapper.text()).toContain('2026-10-03 至 2026-10-05')

    setup.selectedDates = null
    await (setup.runPreflight as () => Promise<void>)()
    expect(setup.preflight).toBeNull()
    setup.device = device({ maxReservationDays: 0 })
    await (setup.loadAvailability as () => Promise<void>)()
    expect(mocks.deviceAvailability).toHaveBeenLastCalledWith(
      42,
      dayjs().startOf('day').format('YYYY-MM-DD'),
      dayjs().startOf('day').add(30, 'day').format('YYYY-MM-DD'),
    )
    setup.device = null
    await (setup.loadAvailability as () => Promise<void>)()
    await (setup.runPreflight as () => Promise<void>)()
    expect(setup.preflight).toBeNull()
    expect(mocks.deviceAvailability).toHaveBeenCalledTimes(2)

    mocks.route.query = { deviceId: '0' }
    const missingDevice = mountPage()
    await flushPromises()
    expect(mocks.getDevice).toHaveBeenCalledOnce()
    expect(missingDevice.text()).toContain('加载设备中…')
  })

  it('displays date conflicts and suggestions, joins eligible single-day waitlists, and navigates to alternatives', async () => {
    mocks.route.query = { deviceId: '42', startDate: '2026-10-01', endDate: '2026-10-01' }
    mocks.preflightReservation.mockResolvedValue(preflight({
      available_dates: [],
      conflicts: [
        { date: '2026-10-01', reason: '已有预约', status: 'PENDING' },
        { date: '2026-10-02', reason: '设备维护', status: 'MAINTENANCE' },
      ],
      all_available: false,
      same_device_suggestions: [
        { start_date: '2026-10-06', end_date: '2026-10-07' },
        { start_date: '2026-10-08', end_date: '2026-10-08' },
      ],
      similar_device_suggestions: [
        { device_id: 43, name: '备用显微镜', lab_name: '成像实验室' },
        { device_id: 44, name: '高分辨显微镜' },
      ],
    }))
    const wrapper = mountPage()
    await flushPromises()
    await flushPromises()
    const setup = setupOf(wrapper)

    expect(wrapper.text()).toContain('2 天冲突')
    expect(wrapper.text()).toContain('同设备可用日期')
    expect(wrapper.text()).toContain('本学院同类设备')
    expect(wrapper.findAll('.conflict-list .ghost')).toHaveLength(1)
    setup.form = { purpose: '显微观察', purposeCategory: 'RESEARCH', projectReference: 'P-1' }
    await wrapper.find('.conflict-list .ghost').trigger('click')
    await flushPromises()
    expect(mocks.joinWaitlist).toHaveBeenCalledWith(expect.objectContaining({
      deviceId: 42, reservationDate: '2026-10-01', purpose: '显微观察', projectReference: 'P-1',
    }))
    expect(mocks.success).toHaveBeenCalledWith('2026-10-01 候补申请已提交；轮到后会为你保留 24 小时')

    await wrapper.find('.preflight-options .ghost').trigger('click')
    expect(setup.selectedDates).toEqual(['2026-10-06', '2026-10-07'])
    await wrapper.findAll('.preflight-options')[1].find('.ghost').trigger('click')
    expect(mocks.push).toHaveBeenCalledWith({
      name: 'reservation-create',
      query: { deviceId: '43', startDate: '2026-10-06', endDate: '2026-10-07' },
    })
    expect(wrapper.text()).toContain('高分辨显微镜')

    const canWaitlist = setup.canWaitlist as (conflict: { date: string; status?: string | null }) => boolean
    setup.selectedDates = ['2026-10-06', '2026-10-06']
    expect(canWaitlist({ date: '2026-10-06', status: 'APPROVED' })).toBe(true)
    expect(canWaitlist({ date: '2026-10-06', status: 'IN_USE' })).toBe(true)
    expect(canWaitlist({ date: '2026-10-06', status: 'CANCELLED' })).toBe(false)
    expect(canWaitlist({ date: '2026-10-05', status: 'PENDING' })).toBe(false)
    expect(canWaitlist({ date: '2026-10-06' })).toBe(false)
  })

  it('gates booking on safety acknowledgement and qualification status, then submits qualification material', async () => {
    mocks.preflightReservation.mockResolvedValue(preflight({
      safety_required: true,
      safety_acknowledged: false,
      qualification_required: true,
      qualification_approved: false,
    }))
    mocks.myQualification.mockResolvedValue({ id: 6, deviceId: 42, userId: 7, status: 'REJECTED' })
    const wrapper = mountPage()
    await flushPromises()
    await flushPromises()
    const setup = setupOf(wrapper)

    expect(wrapper.text()).toContain('阅读并确认安全须知')
    expect(wrapper.text()).toContain('设备安全规范 · v2')
    expect(wrapper.text()).toContain('上次申请未通过')
    expect(wrapper.find('.submit-button').attributes('disabled')).toBeDefined()

    const file = new File(['certificate'], 'certificate.pdf', { type: 'application/pdf' })
    const fileInput = wrapper.get('input[type="file"]').element as HTMLInputElement
    Object.defineProperty(fileInput, 'files', { configurable: true, value: [file] })
    await wrapper.get('input[type="file"]').trigger('change')
    expect(setup.qualificationFile).toBe(file)
    await wrapper.find('.access-card__apply textarea').setValue('  已完成设备培训  ')
    await wrapper.findAll('.access-card__item .gradient')[1].trigger('click')
    await flushPromises()
    expect(mocks.uploadQualificationMaterial).toHaveBeenCalledWith(42, file)
    expect(mocks.submitQualification).toHaveBeenCalledWith(42, { assetId: 88, note: '已完成设备培训' })
    expect(mocks.success).toHaveBeenCalledWith('资质申请已提交，请等待负责人审核')
    expect(setup.qualificationNote).toBe('')
    expect(setup.qualificationFile).toBeNull()
    setup.form = { purpose: '预约测试', purposeCategory: 'RESEARCH', projectReference: '' }
    setup.preflight = preflight({
      safety_required: true,
      safety_acknowledged: true,
      qualification_required: true,
      qualification_approved: true,
    })
    await flushPromises()
    expect(wrapper.find('.access-card__state').text()).toBe('已满足')
    expect(wrapper.find('.submit-button').attributes('disabled')).toBeUndefined()

    setup.preflight = preflight({
      safety_required: true, safety_acknowledged: false,
      qualification_required: true, qualification_approved: false,
    })
    await flushPromises()
    mocks.preflightReservation.mockResolvedValue(preflight({
      safety_required: true, safety_acknowledged: true,
      qualification_required: true, qualification_approved: false,
    }))
    await wrapper.find('.access-card__item .gradient').trigger('click')
    await flushPromises()
    expect(mocks.acknowledgeSafety).toHaveBeenCalledWith(42)
    expect(mocks.success).toHaveBeenCalledWith('已记录安全须知确认')
    expect(wrapper.text()).toContain('已确认')

    const acknowledge = setup.acknowledgeCurrentSafety as () => Promise<void>
    const onQualificationFileChange = setup.onQualificationFileChange as (event: Event) => void
    onQualificationFileChange({ target: { files: null } } as unknown as Event)
    expect(setup.qualificationFile).toBeNull()
    setup.device = null
    await acknowledge()
    expect(mocks.acknowledgeSafety).toHaveBeenCalledOnce()
    await (setup.applyQualification as () => Promise<void>)()
    expect(mocks.submitQualification).toHaveBeenCalledOnce()
  })

  it('handles pending and approved qualifications, optional uploads, and resource failures', async () => {
    mocks.preflightReservation.mockResolvedValue(preflight({
      safety_required: false, qualification_required: true, qualification_approved: false,
    }))
    mocks.myQualification.mockResolvedValue({ id: 8, deviceId: 42, userId: 7, status: 'PENDING' })
    const wrapper = mountPage()
    await flushPromises()
    await flushPromises()
    expect(wrapper.text()).toContain('申请已提交，等待实验室负责人审核')
    expect(wrapper.text()).toContain('审核中')

    mocks.myQualification.mockResolvedValueOnce({ id: 9, deviceId: 42, userId: 7, status: 'APPROVED', validUntil: '2026-09-30' })
    mocks.preflightReservation.mockResolvedValueOnce(preflight({ qualification_required: true, qualification_approved: false }))
    const setup = setupOf(wrapper)
    await (setup.runPreflight as () => Promise<void>)()
    await flushPromises()
    expect(wrapper.text()).toContain('未覆盖本次预约结束日')

    mocks.myQualification.mockResolvedValueOnce(null)
    mocks.preflightReservation.mockResolvedValueOnce(preflight({ qualification_required: true, qualification_approved: false }))
    await (setup.runPreflight as () => Promise<void>)()
    await flushPromises()
    expect(wrapper.text()).toContain('该设备需要先提交培训或操作资质')

    setup.qualificationFile = null
    setup.qualificationNote = '   '
    await (setup.applyQualification as () => Promise<void>)()
    expect(mocks.uploadQualificationMaterial).not.toHaveBeenCalled()
    expect(mocks.submitQualification).toHaveBeenLastCalledWith(42, { assetId: undefined, note: undefined })

    mocks.myQualification.mockResolvedValueOnce({ id: 10, deviceId: 42, userId: 7, status: 'APPROVED', validUntil: null })
    mocks.preflightReservation.mockResolvedValueOnce(preflight({ qualification_required: true, qualification_approved: true }))
    await (setup.runPreflight as () => Promise<void>)()
    await flushPromises()
    expect(wrapper.text()).toContain('长期有效')
    expect(wrapper.text()).toContain('已通过')

    mocks.listSafetyDocuments.mockRejectedValueOnce(new Error('documents unavailable'))
    await expect((setup.runPreflight as () => Promise<void>)()).rejects.toThrow('documents unavailable')
    mocks.uploadQualificationMaterial.mockRejectedValueOnce(new Error('upload failed'))
    setup.qualificationFile = new File(['x'], 'x.pdf', { type: 'application/pdf' })
    await expect((setup.applyQualification as () => Promise<void>)()).rejects.toThrow('upload failed')
    expect(setup.qualificationSubmitting).toBe(false)
  })

  it('validates and submits a complete reservation, preserving the form after conflicts or network errors', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await flushPromises()
    const setup = setupOf(wrapper)
    setup.form = { purpose: '  材料拉伸测试  ', purposeCategory: 'TEACHING', projectReference: '  LAB-2026  ' }
    const onSubmit = setup.onSubmit as () => Promise<void>
    mocks.validationThrows = true
    await onSubmit()
    expect(mocks.createReservation).not.toHaveBeenCalled()
    mocks.validationThrows = false
    mocks.valid = false
    await onSubmit()
    expect(mocks.createReservation).not.toHaveBeenCalled()

    mocks.valid = true
    setup.preflight = null
    await onSubmit()
    await flushPromises()
    expect(mocks.createReservation).toHaveBeenCalledWith({
      deviceId: 42,
      startDate: '2026-10-01',
      endDate: '2026-10-02',
      purpose: '材料拉伸测试',
      purposeCategory: 'TEACHING',
      projectReference: 'LAB-2026',
      commitMode: 'all_or_nothing',
    }, expect.any(String))
    expect(mocks.success).toHaveBeenCalledWith('已提交 1 条预约')
    expect(mocks.push).toHaveBeenCalledWith({ name: 'reservation-mine' })

    setup.form = { purpose: '再次测试', purposeCategory: 'OTHER', projectReference: '   ' }
    await onSubmit()
    await flushPromises()
    expect(mocks.createReservation).toHaveBeenLastCalledWith(
      expect.objectContaining({ projectReference: undefined }),
      expect.any(String),
    )

    mocks.preflightReservation.mockResolvedValueOnce(preflight({ all_available: false, conflicts: [{ date: '2026-10-01' }] }))
    setup.preflight = null
    await onSubmit()
    await flushPromises()
    expect(mocks.warning).toHaveBeenCalledWith('存在冲突日期，请重新选择一段完全可用的连续日期')

    mocks.preflightReservation.mockResolvedValueOnce(preflight())
    mocks.createReservation.mockRejectedValueOnce(new Error('race conflict'))
    setup.preflight = null
    await onSubmit()
    await flushPromises()
    expect(setup.submitting).toBe(false)

    const formRef = setup.formRef
    setup.formRef = undefined
    await onSubmit()
    expect(mocks.warning).toHaveBeenCalledWith('请选择设备和完整的预约日期')
    setup.formRef = formRef
    setup.selectedDates = null
    await onSubmit()
    expect(mocks.warning).toHaveBeenLastCalledWith('请选择设备和完整的预约日期')
    setup.selectedDates = ['2026-10-01', '2026-10-02']
    setup.device = null
    await onSubmit()
    expect(mocks.warning).toHaveBeenLastCalledWith('请选择设备和完整的预约日期')
  })

  it('validates waitlist purpose, handles submission failure, applies date suggestions, and supports back navigation', async () => {
    mocks.route.query = { deviceId: '42', startDate: '2026-10-01', endDate: '2026-10-01' }
    mocks.preflightReservation.mockResolvedValue(preflight({
      all_available: false,
      available_dates: [],
      conflicts: [{ date: '2026-10-01', reason: '已被预约', status: 'IN_USE' }],
    }))
    const wrapper = mountPage()
    await flushPromises()
    await flushPromises()
    const setup = setupOf(wrapper)
    const join = setup.onJoinWaitlist as (date: string) => Promise<void>

    await join('2026-10-01')
    expect(mocks.warning).toHaveBeenCalledWith('请先填写至少 2 个字的使用用途，再加入候补')
    setup.form = { purpose: '光谱分析', purposeCategory: 'RESEARCH', projectReference: '' }
    await join('2026-10-01')
    expect(mocks.joinWaitlist).toHaveBeenCalledWith(expect.objectContaining({
      deviceId: 42, reservationDate: '2026-10-01', purpose: '光谱分析', projectReference: undefined,
    }))

    mocks.joinWaitlist.mockRejectedValueOnce(new Error('already queued'))
    await join('2026-10-01')
    expect(mocks.joinWaitlist).toHaveBeenCalledTimes(2)

    const applyDateSuggestion = setup.applyDateSuggestion as (range: { start_date: string; end_date: string }) => void
    applyDateSuggestion({ start_date: '2026-10-05', end_date: '2026-10-06' })
    expect(setup.selectedDates).toEqual(['2026-10-05', '2026-10-06'])
    await wrapper.find('.cancel-button').trigger('click')
    expect(mocks.back).toHaveBeenCalledOnce()

    mocks.route.query = {}
    const noDevice = mountPage()
    await flushPromises()
    const noDeviceSetup = setupOf(noDevice)
    await (noDeviceSetup.onJoinWaitlist as (date: string) => Promise<void>)('2026-10-01')
    expect(mocks.warning).toHaveBeenLastCalledWith('请先填写至少 2 个字的使用用途，再加入候补')
    })
  })

  it('previews a pool and lets the server allocate a currently free physical unit', async () => {
    mocks.route.query = { poolId: '17', startDate: '2026-10-01', endDate: '2026-10-02' }
    mocks.getDevicePool.mockResolvedValue(device({ id: 42, poolId: 17, poolQuantity: 2, poolIdleQuantity: 2 }))
    mocks.devicePoolAvailability.mockResolvedValue([
      { date: '2026-10-01', available: true, availableUnits: 2 },
      { date: '2026-10-02', available: true, availableUnits: 1 },
    ])
    mocks.preflightReservation.mockResolvedValue(preflight({
      device: device({ id: 43, poolId: 17 }),
    }))

    const wrapper = mountPage()
    await flushPromises()
    await flushPromises()

    expect(mocks.getDevicePool).toHaveBeenCalledWith(17)
    expect(mocks.devicePoolAvailability).toHaveBeenCalledOnce()
    expect(mocks.preflightReservation).toHaveBeenCalledWith(expect.objectContaining({
      poolId: 17,
      startDate: '2026-10-01',
      endDate: '2026-10-02',
    }))

    const setup = setupOf(wrapper)
    setup.form = { purpose: '材料拉伸测试', purposeCategory: 'RESEARCH', projectReference: '' }
    await (setup.onSubmit as () => Promise<void>)()
    await flushPromises()
    expect(mocks.createReservation).toHaveBeenCalledWith(expect.objectContaining({
      poolId: 17,
      startDate: '2026-10-01',
      endDate: '2026-10-02',
    }), expect.any(String))
    expect(mocks.createReservation.mock.lastCall?.[0]).not.toHaveProperty('preferredDeviceId')
  })
