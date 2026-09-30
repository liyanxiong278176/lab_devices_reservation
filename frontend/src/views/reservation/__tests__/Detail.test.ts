import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  route: { params: { id: '55' } },
  getReservation: vi.fn(),
  getReservationFeedback: vi.fn(),
  submitReservationFeedback: vi.fn(),
  getDevice: vi.fn(),
  cancelReservation: vi.fn(),
  checkOutReservation: vi.fn(),
  uploadRepairImage: vi.fn(),
  confirm: vi.fn(),
  success: vi.fn(),
  warning: vi.fn(),
}))

vi.mock('vue-router', () => ({ useRoute: () => mocks.route }))
vi.mock('@/router', () => ({ readSpaDepth: () => 0 }))
vi.mock('element-plus', () => ({
  ElMessage: { success: mocks.success, warning: mocks.warning },
  ElMessageBox: { confirm: mocks.confirm },
}))
vi.mock('@/api/reservation', () => ({
  cancelReservation: mocks.cancelReservation,
  checkOutReservation: mocks.checkOutReservation,
  getReservationFeedback: mocks.getReservationFeedback,
  getReservation: mocks.getReservation,
  submitReservationFeedback: mocks.submitReservationFeedback,
}))
vi.mock('@/api/repair', () => ({ uploadRepairImage: mocks.uploadRepairImage }))
vi.mock('@/api/device', () => ({ getDevice: mocks.getDevice }))

import Detail from '../Detail.vue'

const reservation = (status: string, overrides: Record<string, unknown> = {}) => ({
  id: 55,
  userId: 7,
  deviceId: 101,
  purpose: '材料强度测试',
  deviceName: '显微镜',
  startDate: '2026-10-01',
  endDate: '2026-10-02',
  startTime: '2026-10-01T00:00:00',
  endTime: '2026-10-02T23:59:59',
  slotCount: 2,
  status,
  createdAt: '2026-09-28T09:00:00',
  handoverStatus: 'PENDING',
  ...overrides,
})

const device = { id: 101, name: '高倍显微镜', status: 'IDLE', needApproval: 1 }
const feedback = { id: 8, reservation_id: 55, device_id: 101, user_id: 7, rating: 4, comment: '成像清晰' }

const stubs = {
  PageHeader: { props: ['title', 'subtitle'], template: '<header><h1>{{ title }}</h1><span>{{ subtitle }}</span><slot name="actions" /></header>' },
  GlowCard: { template: '<section class="glow-card"><slot /></section>' },
  Tag: { props: ['variant'], template: '<span class="tag" :data-variant="variant"><slot /></span>' },
  Timeline: {
    props: ['items'],
    template: '<ol class="timeline"><li v-for="item in items" :key="item.id" :data-status="item.status">{{ item.title }} {{ item.desc }} {{ item.time }}</li></ol>',
  },
  GradientButton: { props: ['loading', 'disabled'], emits: ['click'], template: '<button class="gradient" :disabled="loading || disabled" @click="$emit(\'click\', $event)"><slot /></button>' },
  GhostButton: { emits: ['click'], template: '<button class="ghost" @click="$emit(\'click\', $event)"><slot /></button>' },
  'el-dialog': {
    props: ['modelValue', 'title'],
    emits: ['update:modelValue'],
    template: '<section v-if="modelValue" class="dialog"><button class="dialog-model-close" @click="$emit(\'update:modelValue\', false)">close</button><h2>{{ title }}</h2><slot /><footer><slot name="footer" /></footer></section>',
  },
  'el-radio-group': {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template: '<div class="radio-group"><slot /><button class="missing-condition" @click="$emit(\'update:modelValue\', \'MISSING\')">设备缺失</button></div>',
  },
  'el-radio': { props: ['value'], template: '<span>{{ value }}<slot /></span>' },
  'el-input': { props: ['modelValue'], emits: ['update:modelValue'], template: '<textarea :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
  'el-rate': { props: ['modelValue'], emits: ['update:modelValue'], template: '<button class="rate" @click="$emit(\'update:modelValue\', 4)">{{ modelValue }}</button>' },
}

function mountPage() {
  return mount(Detail, { global: { stubs, directives: { loading: { mounted() {}, updated() {} } } } })
}

function setFiles(input: HTMLInputElement, files: File[] | null) {
  Object.defineProperty(input, 'files', { configurable: true, value: files })
}

describe('reservation detail lifecycle page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.route.params = { id: '55' }
    mocks.getReservation.mockResolvedValue(reservation('PENDING'))
    mocks.getReservationFeedback.mockResolvedValue(null)
    mocks.getDevice.mockResolvedValue(device)
    mocks.cancelReservation.mockResolvedValue(undefined)
    mocks.checkOutReservation.mockResolvedValue(undefined)
    mocks.uploadRepairImage.mockResolvedValue({ url: '/return/photo.png' })
    mocks.submitReservationFeedback.mockResolvedValue(feedback)
    mocks.confirm.mockResolvedValue(undefined)
  })

  it('loads a pending reservation, renders fallback details, and handles cancellation confirmation and API results', async () => {
    mocks.getDevice.mockRejectedValueOnce(new Error('device catalog offline'))
    mocks.getReservation.mockResolvedValueOnce(reservation('PENDING', {
      createdAt: undefined,
      deviceName: undefined,
      purpose: '',
      inspectionCondition: undefined,
      inspectionNote: '',
      handoverStatus: undefined,
    }))
    const wrapper = mountPage()
    await flushPromises()

    expect(mocks.getReservation).toHaveBeenCalledWith(55)
    expect(mocks.getDevice).toHaveBeenCalledWith(101)
    expect(wrapper.text()).toContain('设备 #101')
    expect(wrapper.text()).toContain('等待审批')
    expect(wrapper.text()).toContain('待负责人交接')
    expect(wrapper.text()).toContain('用户 #7')
    expect(wrapper.find('.timeline').text()).toContain('预约已提交,等待管理员审批')
    expect(wrapper.findAll('.rsv-detail__actions button').map((button) => button.text())).toContain('取消预约')

    mocks.confirm.mockRejectedValueOnce(new Error('user kept reservation'))
    await wrapper.find('.rsv-detail__cancel').trigger('click')
    await flushPromises()
    expect(mocks.cancelReservation).not.toHaveBeenCalled()

    await wrapper.find('.rsv-detail__cancel').trigger('click')
    await flushPromises()
    expect(mocks.confirm).toHaveBeenLastCalledWith('确认取消预约 #55？', '取消预约', expect.any(Object))
    expect(mocks.cancelReservation).toHaveBeenCalledWith(55)
    expect(mocks.success).toHaveBeenCalledWith('已取消')

    mocks.cancelReservation.mockRejectedValueOnce(new Error('conflict'))
    await wrapper.find('.rsv-detail__cancel').trigger('click')
    await flushPromises()
    expect(mocks.cancelReservation).toHaveBeenCalledTimes(2)
  })

  it('shows timeline branches for approval, handover, return and terminal reservation states', async () => {
    const cases = [
      { status: 'APPROVED', extras: { handoverStatus: 'PENDING', startDate: '' }, text: '等待负责人交接' },
      { status: 'IN_USE', extras: { handoverStatus: 'HANDED_OVER', checkInAt: '2026-10-01T10:00:00', endDate: '' }, text: '使用中，待归还' },
      { status: 'IN_USE', extras: { handoverStatus: 'RETURN_PENDING', endDate: '' }, text: '设备已归还，等待验收' },
      { status: 'IN_USE', extras: { handoverStatus: 'LEGACY_IN_USE' }, text: '规则调整前已开始使用' },
      { status: 'COMPLETED', extras: { handoverStatus: 'RETURNED', checkOutAt: '2026-10-02T18:00:00', inspectionCondition: 'DAMAGED', inspectionNote: '外壳划痕' }, text: '负责人已完成验收' },
      { status: 'CANCELLED', extras: {}, text: '预约已取消' },
      { status: 'REJECTED', extras: { rejectReason: '用途不明确' }, text: '审批未通过' },
      { status: 'REJECTED', extras: { rejectReason: '' }, text: '审批未通过' },
      { status: 'NO_SHOW', extras: {}, text: '未按时办理交接' },
      { status: 'VIOLATED', extras: { rejectReason: '' }, text: '预约已违规终止' },
    ]

    for (const item of cases) {
      mocks.getReservation.mockResolvedValueOnce(reservation(item.status, item.extras))
      const wrapper = mountPage()
      await flushPromises()
      expect(wrapper.find('.timeline').text()).toContain(item.text)
      if (item.status === 'REJECTED') {
        expect(wrapper.text()).toContain(item.extras.rejectReason ? '用途不明确' : '负责人未填写原因')
      }
      wrapper.unmount()
    }
  })

  it('submits an evidence-backed return and validates file count, type, size and server failure', async () => {
    mocks.getReservation.mockResolvedValue(reservation('IN_USE', { handoverStatus: 'HANDED_OVER' }))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.findAll('.rsv-detail__actions button').map((button) => button.text())).toContain('归还')
    await wrapper.find('.rsv-detail__actions .gradient').trigger('click')
    expect(wrapper.find('.dialog').exists()).toBe(true)
    await wrapper.find('.dialog .gradient').trigger('click')
    expect(mocks.warning).toHaveBeenCalledWith('请先上传 1 至 6 张归还现场照片')
    await wrapper.find('.dialog-model-close').trigger('click')
    expect(wrapper.find('.dialog').exists()).toBe(false)
    await wrapper.find('.rsv-detail__actions .gradient').trigger('click')
    await wrapper.find('.dialog .ghost').trigger('click')
    expect(wrapper.find('.dialog').exists()).toBe(false)
    await wrapper.find('.rsv-detail__actions .gradient').trigger('click')

    const input = wrapper.get('input[type="file"]').element as HTMLInputElement
    setFiles(input, null)
    await wrapper.get('input[type="file"]').trigger('change')
    expect(mocks.warning).toHaveBeenCalledWith('请上传 1 至 6 张归还现场照片')
    const tooMany = Array.from({ length: 7 }, (_, index) => new File([String(index)], `${index}.jpg`, { type: 'image/jpeg' }))
    setFiles(input, tooMany)
    await wrapper.get('input[type="file"]').trigger('change')
    expect(mocks.warning).toHaveBeenLastCalledWith('请上传 1 至 6 张归还现场照片')
    setFiles(input, [new File(['bad'], 'bad.txt', { type: 'text/plain' })])
    await wrapper.get('input[type="file"]').trigger('change')
    expect(mocks.warning).toHaveBeenLastCalledWith('照片仅支持 5 MB 以内 JPG、PNG 或 WebP')
    setFiles(input, [new File([new Uint8Array(5 * 1024 * 1024 + 1)], 'large.png', { type: 'image/png' })])
    await wrapper.get('input[type="file"]').trigger('change')
    expect(mocks.warning).toHaveBeenLastCalledWith('照片仅支持 5 MB 以内 JPG、PNG 或 WebP')

    const photo = new File(['evidence'], 'return.webp', { type: 'image/webp' })
    setFiles(input, [photo])
    await wrapper.get('input[type="file"]').trigger('change')
    await wrapper.find('.radio-group .missing-condition').trigger('click')
    await wrapper.find('.dialog textarea').setValue('  外壳破损  ')
    await wrapper.find('.dialog .gradient').trigger('click')
    await flushPromises()
    expect(mocks.uploadRepairImage).toHaveBeenCalledWith(photo)
    expect(mocks.checkOutReservation).toHaveBeenCalledWith(55, {
      condition: 'MISSING', note: '外壳破损', imageUrls: ['/return/photo.png'],
    })
    expect(mocks.success).toHaveBeenCalledWith('已提交归还，等待负责人验收')
    expect(wrapper.find('.dialog').exists()).toBe(false)

    mocks.getReservation.mockResolvedValueOnce(reservation('IN_USE'))
    const failedReturn = mountPage()
    await flushPromises()
    await failedReturn.find('.rsv-detail__actions .gradient').trigger('click')
    const secondInput = failedReturn.get('input[type="file"]').element as HTMLInputElement
    setFiles(secondInput, [new File(['evidence'], 'return.png', { type: 'image/png' })])
    await failedReturn.get('input[type="file"]').trigger('change')
    mocks.uploadRepairImage.mockRejectedValueOnce(new Error('upload failure'))
    await failedReturn.find('.dialog .gradient').trigger('click')
    await flushPromises()
    expect(failedReturn.find('.dialog').exists()).toBe(true)

    mocks.checkOutReservation.mockRejectedValueOnce(new Error('return request failed'))
    await failedReturn.find('.dialog .gradient').trigger('click')
    await flushPromises()
    expect(mocks.checkOutReservation).toHaveBeenCalledWith(55, {
      condition: 'NORMAL', note: undefined, imageUrls: ['/return/photo.png'],
    })
    expect(failedReturn.find('.dialog').exists()).toBe(true)
  })

  it('allows one feedback submission after completion and keeps the dialog open after failure', async () => {
    mocks.getReservation.mockResolvedValue(reservation('COMPLETED', {
      handoverStatus: 'RETURNED', checkOutAt: '2026-10-02T18:00:00', inspectionCondition: 'NORMAL',
    }))
    const wrapper = mountPage()
    await flushPromises()
    await flushPromises()
    expect(mocks.getReservationFeedback).toHaveBeenCalledWith(55)
    expect(wrapper.find('.timeline').text()).toContain('负责人已完成验收')
    expect(wrapper.text()).toContain('验收正常')
    expect(wrapper.findAll('.rsv-detail__actions button').map((button) => button.text())).toContain('评价设备')

    await wrapper.find('.rsv-detail__actions .ghost').trigger('click')
    expect(wrapper.find('.dialog').text()).toContain('评价本次使用')
    await wrapper.find('.dialog-model-close').trigger('click')
    expect(wrapper.find('.dialog').exists()).toBe(false)
    await wrapper.find('.rsv-detail__actions .ghost').trigger('click')
    await wrapper.find('.dialog .ghost').trigger('click')
    expect(wrapper.find('.dialog').exists()).toBe(false)
    await wrapper.find('.rsv-detail__actions .ghost').trigger('click')
    await wrapper.find('.dialog .rate').trigger('click')
    await wrapper.find('.dialog textarea').setValue('设备状态良好')
    mocks.submitReservationFeedback.mockResolvedValueOnce({ ...feedback, comment: '设备状态良好' })
    await wrapper.find('.dialog .gradient').trigger('click')
    await flushPromises()
    expect(mocks.submitReservationFeedback).toHaveBeenCalledWith(55, { rating: 4, comment: '设备状态良好' })
    expect(mocks.success).toHaveBeenCalledWith('评价已提交')
    expect(wrapper.find('.dialog').exists()).toBe(false)
    expect(wrapper.text()).toContain('4 / 5 · 设备状态良好')

    mocks.getReservationFeedback.mockResolvedValueOnce({ ...feedback, comment: '' })
    const existingFeedback = mountPage()
    await flushPromises()
    expect(existingFeedback.findAll('.rsv-detail__actions button').map((button) => button.text())).not.toContain('评价设备')
    expect(existingFeedback.text()).toContain('4 / 5')

    mocks.getReservation.mockResolvedValueOnce(reservation('COMPLETED'))
    mocks.getReservationFeedback.mockResolvedValueOnce(null)
    const failedFeedback = mountPage()
    await flushPromises()
    await failedFeedback.find('.rsv-detail__actions .ghost').trigger('click')
    mocks.submitReservationFeedback.mockRejectedValueOnce(new Error('feedback write failed'))
    await failedFeedback.find('.dialog .gradient').trigger('click')
    await flushPromises()
    expect(mocks.submitReservationFeedback).toHaveBeenCalledWith(55, { rating: 5, comment: undefined })
    expect(failedFeedback.find('.dialog').exists()).toBe(true)
  })

  it('covers detail load failures, feedback failures, condition labels and defensive no-record actions', async () => {
    mocks.getReservation.mockRejectedValueOnce(new Error('reservation unavailable'))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('.rsv-detail__layout').exists()).toBe(false)

    const setup = (wrapper.vm as unknown as { $: { setupState: Record<string, unknown> } }).$.setupState
    expect(setup.timelineItems).toEqual([])
    expect(setup.specRows).toEqual([])
    const inspectionLabel = setup.inspectionLabel as (condition?: string) => string
    expect(inspectionLabel('NORMAL')).toBe('验收正常')
    expect(inspectionLabel('DAMAGED')).toBe('发现损坏')
    expect(inspectionLabel('MISSING')).toBe('设备缺失')
    expect(inspectionLabel()).toBe('—')
    const handoverLabel = setup.handoverLabel as (status?: string) => string
    expect(handoverLabel()).toBe('待负责人交接')
    expect(handoverLabel('UNKNOWN')).toBe('UNKNOWN')
    expect((setup.canCancel as () => boolean)()).toBe(false)
    expect((setup.canCheckOut as () => boolean)()).toBe(false)

    await (setup.openReturnDialog as () => void)()
    await (setup.submitReturn as () => Promise<void>)()
    await (setup.submitFeedback as () => Promise<void>)()
    await (setup.onCancel as () => Promise<void>)()
    expect(mocks.cancelReservation).not.toHaveBeenCalled()
    expect(mocks.checkOutReservation).not.toHaveBeenCalled()
    expect(mocks.submitReservationFeedback).not.toHaveBeenCalled()

    mocks.getReservation.mockResolvedValueOnce(reservation('COMPLETED'))
    mocks.getReservationFeedback.mockRejectedValueOnce(new Error('feedback unavailable'))
    const feedbackFailure = mountPage()
    await flushPromises()
    expect(feedbackFailure.find('.rsv-detail__layout').exists()).toBe(true)
  })
})
