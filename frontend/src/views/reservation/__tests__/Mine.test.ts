import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  cancelReservation: vi.fn(),
  checkOutReservation: vi.fn(),
  cancelWaitlist: vi.fn(),
  confirmWaitlistOffer: vi.fn(),
  myWaitlist: vi.fn(),
  myReservations: vi.fn(),
  uploadRepairImage: vi.fn(),
  confirm: vi.fn(),
  success: vi.fn(),
  warning: vi.fn(),
  push: vi.fn(),
  reveal: vi.fn(),
}))

vi.mock('@/api/reservation', () => ({
  cancelReservation: mocks.cancelReservation,
  checkOutReservation: mocks.checkOutReservation,
  cancelWaitlist: mocks.cancelWaitlist,
  confirmWaitlistOffer: mocks.confirmWaitlistOffer,
  myWaitlist: mocks.myWaitlist,
  myReservations: mocks.myReservations,
}))
vi.mock('@/api/repair', () => ({ uploadRepairImage: mocks.uploadRepairImage }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: mocks.push }) }))
vi.mock('@/router', () => ({ readSpaDepth: () => 0 }))
vi.mock('element-plus', () => ({
  ElMessage: { success: mocks.success, warning: mocks.warning },
  ElMessageBox: { confirm: mocks.confirm },
}))
vi.mock('@/composables/useStagger', () => ({ useStagger: () => ({ reveal: mocks.reveal }) }))

import Mine from '../Mine.vue'

const reservation = (id: number, status: string, overrides: Record<string, unknown> = {}) => ({
  id,
  userId: 1,
  deviceId: id + 100,
  purpose: '常规实验',
  deviceName: `设备-${id}`,
  startDate: '2026-10-01',
  endDate: '2026-10-02',
  startTime: '2026-10-01T00:00:00',
  endTime: '2026-10-02T23:59:59',
  slotCount: 2,
  status,
  createdAt: '2026-09-28T09:00:00',
  ...overrides,
})

const rows = [
  reservation(1, 'PENDING', { deviceAssetCode: 'ASSET-1', deviceLabName: '光学实验室' }),
  reservation(2, 'APPROVED', { requiresHandover: true }),
  reservation(3, 'IN_USE'),
  reservation(4, 'IN_USE', { handoverStatus: 'RETURN_PENDING' }),
  reservation(5, 'COMPLETED', { deviceName: '', purpose: '', startDate: '', endDate: '', startTime: '', endTime: '', createdAt: '' }),
  reservation(6, 'REJECTED', { handoverStatus: 'RETURN_PENDING' }),
]

const page = (records = rows, overrides: Record<string, unknown> = {}) => ({
  records,
  total: records.length,
  size: 9,
  current: 1,
  pages: 1,
  truncated: false,
  ...overrides,
})

const waitlistRows = [
  { id: 71, deviceId: 8, deviceName: '', reservationDate: '2026-10-03', purpose: '等待设备', status: 'WAITING' },
  { id: 72, deviceId: 9, deviceName: '光谱仪', reservationDate: '2026-10-04', purpose: '确认时段', status: 'OFFERED', offeredUntil: '2026-09-29T12:00:00' },
]

const stubs = {
  PageHeader: { props: ['title', 'subtitle'], template: '<header><h1>{{ title }}</h1><span>{{ subtitle }}</span></header>' },
  SegmentedControl: {
    props: ['modelValue', 'options'],
    emits: ['update:modelValue'],
    template: '<div class="segments"><button v-for="option in options" :key="option.value" @click="$emit(\'update:modelValue\', option.value)">{{ option.label }}</button></div>',
  },
  GlowCard: { template: '<article class="glow-card"><slot /></article>' },
  Tag: { props: ['variant'], template: '<span class="tag" :data-variant="variant"><slot /></span>' },
  TextButton: { emits: ['click'], template: '<button class="text" @click="$emit(\'click\', $event)"><slot /></button>' },
  GhostButton: { emits: ['click'], template: '<button class="ghost" @click="$emit(\'click\', $event)"><slot /></button>' },
  GradientButton: { emits: ['click'], template: '<button class="gradient" @click="$emit(\'click\', $event)"><slot /></button>' },
  EmptyState: { props: ['title', 'description'], template: '<div class="empty"><strong>{{ title }}</strong><span>{{ description }}</span></div>' },
  PageDepthNotice: { props: ['total'], template: '<div class="depth">{{ total }}</div>' },
  PageSizeControl: { props: ['modelValue'], emits: ['change'], template: '<button class="page-size" @click="$emit(\'change\', 18)">size</button>' },
  'el-pagination': {
    emits: ['current-change', 'size-change'],
    template: '<div class="pagination"><button class="next" @click="$emit(\'current-change\', 3)">next</button><button class="resize" @click="$emit(\'size-change\', 36)">resize</button></div>',
  },
  'el-dialog': {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template: '<section v-if="modelValue" class="dialog"><button class="dialog-close" @click="$emit(\'update:modelValue\', false)">close</button><slot /><footer><slot name="footer" /></footer></section>',
  },
  'el-radio-group': {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template: '<div class="radio-group"><slot /><button class="damaged" @click="$emit(\'update:modelValue\', \'DAMAGED\')">损坏</button></div>',
  },
  'el-radio': { props: ['value'], template: '<span>{{ value }}<slot /></span>' },
  'el-input': {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template: '<textarea :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
  },
}

function mountPage() {
  return mount(Mine, {
    global: {
      stubs,
      directives: { loading: { mounted() {}, updated() {} } },
    },
  })
}

function setFiles(input: HTMLInputElement, files: File[] | null) {
  Object.defineProperty(input, 'files', { configurable: true, value: files })
}

describe('my reservations page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.myReservations.mockResolvedValue(page())
    mocks.myWaitlist.mockResolvedValue(waitlistRows)
    mocks.confirm.mockResolvedValue(undefined)
    mocks.cancelReservation.mockResolvedValue(undefined)
    mocks.cancelWaitlist.mockResolvedValue(undefined)
    mocks.confirmWaitlistOffer.mockResolvedValue(undefined)
    mocks.uploadRepairImage.mockResolvedValue({ url: '/uploads/return.png' })
    mocks.checkOutReservation.mockResolvedValue(undefined)
  })

  it('loads reservation and waitlist cards with state-specific actions and fallbacks', async () => {
    const wrapper = mountPage()
    await flushPromises()

    expect(mocks.myReservations).toHaveBeenCalledWith({ page: 1, size: 9, status: '', handoverStatus: '' })
    expect(mocks.myWaitlist).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('我的候补申请')
    expect(wrapper.text()).toContain('设备 #8')
    expect(wrapper.text()).toContain('保留至 2026-09-29')
    expect(wrapper.text()).toContain('ASSET-1')
    expect(wrapper.text()).toContain('光学实验室')
    expect(wrapper.text()).toContain('等待负责人交接')
    expect(wrapper.text()).toContain('待负责人验收')
    expect(wrapper.text()).toContain('设备 #105')
    expect(wrapper.findAll('.mine__cell')).toHaveLength(6)
    expect(wrapper.findAll('.mine__cell')[0].findAll('.ghost')).toHaveLength(1)
    expect(wrapper.findAll('.mine__cell')[2].findAll('.ghost')).toHaveLength(1)
    expect(wrapper.findAll('.mine__cell')[3].findAll('.ghost')).toHaveLength(0)
    expect(wrapper.find('.depth').exists()).toBe(false)
    expect(mocks.reveal).toHaveBeenCalled()
  })

  it('filters by ordinary and return-handover state, changes both pagination controls, and navigates to details', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const filters = wrapper.find('.segments')
    await filters.findAll('button').find((button) => button.text() === '待验收')!.trigger('click')
    await flushPromises()
    expect(mocks.myReservations).toHaveBeenLastCalledWith({ page: 1, size: 9, status: '', handoverStatus: 'RETURN_PENDING' })

    await filters.findAll('button').find((button) => button.text() === '已通过')!.trigger('click')
    await flushPromises()
    expect(mocks.myReservations).toHaveBeenLastCalledWith({ page: 1, size: 9, status: 'APPROVED', handoverStatus: '' })

    await wrapper.findAll('.pagination button')[0].trigger('click')
    await flushPromises()
    expect(mocks.myReservations).toHaveBeenLastCalledWith({ page: 3, size: 9, status: 'APPROVED', handoverStatus: '' })
    await wrapper.find('.page-size').trigger('click')
    await flushPromises()
    expect(mocks.myReservations).toHaveBeenLastCalledWith({ page: 1, size: 18, status: 'APPROVED', handoverStatus: '' })
    await wrapper.findAll('.pagination button')[1].trigger('click')
    await flushPromises()
    expect(mocks.myReservations).toHaveBeenLastCalledWith({ page: 1, size: 36, status: 'APPROVED', handoverStatus: '' })

    await wrapper.findAll('.mine__cell')[0].find('.text').trigger('click')
    expect(mocks.push).toHaveBeenCalledWith({ name: 'reservation-detail', params: { id: 1 } })
  })

  it('cancels a reservation after confirmation and leaves it unchanged when the user declines', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.findAll('.mine__cell')[0].find('.mine__cancel-btn').trigger('click')
    await flushPromises()
    expect(mocks.confirm).toHaveBeenCalledWith('确认取消预约 #1？', '取消预约', expect.any(Object))
    expect(mocks.cancelReservation).toHaveBeenCalledWith(1)
    expect(mocks.success).toHaveBeenCalledWith('已取消')

    mocks.confirm.mockRejectedValueOnce(new Error('cancelled by user'))
    await wrapper.findAll('.mine__cell')[1].find('.mine__cancel-btn').trigger('click')
    await flushPromises()
    expect(mocks.cancelReservation).toHaveBeenCalledTimes(1)

    await wrapper.findAll('.mine__cell')[0].find('.mine__cancel-btn').trigger('click')
    mocks.cancelReservation.mockRejectedValueOnce(new Error('server failure'))
    await flushPromises()
    expect(mocks.cancelReservation).toHaveBeenCalledTimes(2)
  })

  it('confirms an offered waitlist spot, removes cancelled entries, and handles confirmation/API failures', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.findAll('.mine__waitlist-row')[1].find('.gradient').trigger('click')
    await flushPromises()
    expect(mocks.confirmWaitlistOffer).toHaveBeenCalledWith(72)
    expect(mocks.success).toHaveBeenCalledWith('候补已确认，预约已按设备规则创建')
    expect(mocks.myWaitlist).toHaveBeenCalledTimes(2)

    await wrapper.findAll('.mine__waitlist-row')[0].find('.text').trigger('click')
    await flushPromises()
    expect(mocks.confirm).toHaveBeenCalledWith('确认取消 2026-10-03 的候补申请？', '取消候补', expect.any(Object))
    expect(mocks.cancelWaitlist).toHaveBeenCalledWith(71)
    expect(wrapper.findAll('.mine__waitlist-row')).toHaveLength(1)

    mocks.confirm.mockRejectedValueOnce(new Error('keep waitlist'))
    await wrapper.find('.mine__waitlist-row .text').trigger('click')
    expect(mocks.cancelWaitlist).toHaveBeenCalledTimes(1)

    mocks.cancelWaitlist.mockRejectedValueOnce(new Error('failed'))
    await wrapper.find('.mine__waitlist-row .text').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.mine__waitlist-row')).toHaveLength(1)

    mocks.confirmWaitlistOffer.mockRejectedValueOnce(new Error('expired offer'))
    await wrapper.find('.mine__waitlist-row .gradient').trigger('click')
    await flushPromises()
    expect(mocks.confirmWaitlistOffer).toHaveBeenCalledTimes(2)
  })

  it('validates return photos, opens and closes the return form, and submits uploaded evidence', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.findAll('.mine__cell')[2].find('.ghost').trigger('click')
    expect(wrapper.find('.dialog').exists()).toBe(true)
    expect(wrapper.text()).toContain('0 张已选择')
    expect(wrapper.find('.radio-group').text()).toContain('设备状态正常')
    expect(wrapper.find('.radio-group').text()).toContain('设备缺失')

    await wrapper.find('.dialog-close').trigger('click')
    expect(wrapper.find('.dialog').exists()).toBe(false)
    await wrapper.findAll('.mine__cell')[2].find('.ghost').trigger('click')
    await wrapper.findAll('.dialog .ghost')[0].trigger('click')
    expect(wrapper.find('.dialog').exists()).toBe(false)
    await wrapper.findAll('.mine__cell')[2].find('.ghost').trigger('click')

    const input = wrapper.get('input[type="file"]').element as HTMLInputElement
    setFiles(input, null)
    await wrapper.get('input[type="file"]').trigger('change')
    expect(mocks.warning).toHaveBeenCalledWith('请上传 1 至 6 张归还现场照片')

    setFiles(input, [])
    await wrapper.get('input[type="file"]').trigger('change')
    expect(mocks.warning).toHaveBeenCalledWith('请上传 1 至 6 张归还现场照片')

    const tooMany = Array.from({ length: 7 }, (_, index) => new File([String(index)], `${index}.png`, { type: 'image/png' }))
    setFiles(input, tooMany)
    await wrapper.get('input[type="file"]').trigger('change')
    expect(mocks.warning).toHaveBeenLastCalledWith('请上传 1 至 6 张归还现场照片')

    setFiles(input, [new File(['large'], 'large.png', { type: 'application/octet-stream' })])
    await wrapper.get('input[type="file"]').trigger('change')
    expect(mocks.warning).toHaveBeenLastCalledWith('照片仅支持 5 MB 以内 JPG、PNG 或 WebP')

    setFiles(input, [new File([new Uint8Array(5 * 1024 * 1024 + 1)], 'oversized.png', { type: 'image/png' })])
    await wrapper.get('input[type="file"]').trigger('change')
    expect(mocks.warning).toHaveBeenLastCalledWith('照片仅支持 5 MB 以内 JPG、PNG 或 WebP')

    const photo = new File(['image'], 'return.png', { type: 'image/png' })
    setFiles(input, [photo])
    await wrapper.get('input[type="file"]').trigger('change')
    await wrapper.find('.damaged').trigger('click')
    await wrapper.find('.dialog textarea').setValue('  外壳损坏  ')
    expect(wrapper.text()).toContain('1 张已选择')
    await wrapper.findAll('.dialog .ghost')[1].trigger('click')
    await flushPromises()

    expect(mocks.uploadRepairImage).toHaveBeenCalledWith(photo)
    expect(mocks.checkOutReservation).toHaveBeenCalledWith(3, {
      condition: 'DAMAGED',
      note: '外壳损坏',
      imageUrls: ['/uploads/return.png'],
    })
    expect(mocks.success).toHaveBeenCalledWith('已提交归还，等待负责人验收')
    expect(wrapper.find('.dialog').exists()).toBe(false)
  })

  it('requires evidence before returning and keeps the form open when upload or return fails', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const setup = (wrapper.vm as unknown as { $: { setupState: Record<string, unknown> } }).$.setupState
    await (setup.submitReturn as () => Promise<void>)()
    expect(mocks.warning).not.toHaveBeenCalled()

    await wrapper.findAll('.mine__cell')[2].find('.ghost').trigger('click')
    await wrapper.findAll('.dialog .ghost')[1].trigger('click')
    await flushPromises()
    expect(mocks.warning).toHaveBeenCalledWith('请先上传 1 至 6 张归还现场照片')
    expect(mocks.checkOutReservation).not.toHaveBeenCalled()

    const input = wrapper.get('input[type="file"]').element as HTMLInputElement
    setFiles(input, [new File(['image'], 'return.jpg', { type: 'image/jpeg' })])
    await wrapper.get('input[type="file"]').trigger('change')
    mocks.uploadRepairImage.mockRejectedValueOnce(new Error('upload failed'))
    await wrapper.findAll('.dialog .ghost')[1].trigger('click')
    await flushPromises()
    expect(wrapper.find('.dialog').exists()).toBe(true)

    mocks.checkOutReservation.mockRejectedValueOnce(new Error('return failed'))
    await wrapper.findAll('.dialog .ghost')[1].trigger('click')
    await flushPromises()
    expect(wrapper.find('.dialog').exists()).toBe(true)
  })

  it('renders empty and truncated pages, resets on filtering, and tolerates list loading failures', async () => {
    mocks.myReservations.mockResolvedValueOnce(page([], { total: 0 }))
    mocks.myWaitlist.mockRejectedValueOnce(new Error('waitlist unavailable'))
    const wrapper = mountPage()
    await flushPromises()
    expect(wrapper.find('.empty').text()).toContain('暂无预约记录')
    expect(wrapper.find('.mine__pager').exists()).toBe(false)

    const setup = (wrapper.vm as unknown as { $: { setupState: Record<string, unknown> } }).$.setupState
    ;(setup.query as { page: number }).page = 0
    await (setup.load as () => Promise<void>)()
    await flushPromises()
    expect(mocks.myReservations).toHaveBeenLastCalledWith({ page: 1, size: 9, status: '', handoverStatus: '' })
    await (setup.onStatusChange as (value: string) => void)(undefined as unknown as string)
    await flushPromises()
    expect(mocks.myReservations).toHaveBeenLastCalledWith({ page: 1, size: 9, status: '', handoverStatus: '' })

    mocks.myReservations.mockResolvedValueOnce(page([reservation(10, 'CANCELLED')], { total: 100, truncated: true, pages: 0 }))
    await wrapper.find('.segments').findAll('button').find((button) => button.text() === '已取消')!.trigger('click')
    await flushPromises()
    expect(wrapper.find('.depth').text()).toBe('100')
    expect(mocks.myReservations).toHaveBeenLastCalledWith({ page: 1, size: 9, status: 'CANCELLED', handoverStatus: '' })

    mocks.myReservations.mockRejectedValueOnce(new Error('reservations unavailable'))
    await (setup.load as (page?: number) => Promise<void>)(2)
    expect(wrapper.findAll('.mine__cell')).toHaveLength(1)
  })
})
