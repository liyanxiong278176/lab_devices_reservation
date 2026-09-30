import { defineComponent, h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const mocks = vi.hoisted(() => ({
  searchDevices: vi.fn(),
  createRepair: vi.fn(),
  uploadRepairImage: vi.fn(),
  push: vi.fn(),
  back: vi.fn(),
  success: vi.fn(),
  warning: vi.fn(),
  valid: true,
  validationThrows: false,
}))

vi.mock('vue-router', () => ({ useRouter: () => ({ push: mocks.push, back: mocks.back }) }))
vi.mock('@/router', () => ({ readSpaDepth: () => 0 }))
vi.mock('element-plus', () => ({ ElMessage: { success: mocks.success, warning: mocks.warning } }))
vi.mock('@/api/device', () => ({ searchDevices: mocks.searchDevices }))
vi.mock('@/api/repair', () => ({ createRepair: mocks.createRepair, uploadRepairImage: mocks.uploadRepairImage }))

import Submit from '../Submit.vue'

const device = (id: number, labName?: string) => ({
  id, name: `设备-${id}`, categoryId: 1, labId: 2, labName, status: 'IDLE', needApproval: 1,
})
const page = (records = [device(1, '光学实验室'), device(2)], pages = 1) => ({
  records, total: records.length, size: 100, current: 1, pages, truncated: false,
})

const FormStub = defineComponent({
  props: ['model', 'rules', 'labelPosition'],
  setup(_props, { expose, slots }) {
    expose({ validate: async () => {
      if (mocks.validationThrows) throw new Error('invalid form')
      return mocks.valid
    } })
    return () => h('form', { class: 'form-stub' }, slots.default?.())
  },
})

const stubs = {
  PageHeader: { template: '<header><slot /></header>' },
  GlowCard: { template: '<section class="glow-card"><slot /></section>' },
  GradientButton: { props: ['loading'], emits: ['click'], template: '<button class="gradient" :disabled="loading" @click="$emit(\'click\', $event)"><slot /></button>' },
  GhostButton: { emits: ['click'], template: '<button class="ghost" @click="$emit(\'click\', $event)"><slot /></button>' },
  'el-form': FormStub,
  'el-form-item': { props: ['label'], template: '<label><span>{{ label }}</span><slot /></label>' },
  'el-select': {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template: '<select :value="modelValue" @change="$emit(\'update:modelValue\', Number($event.target.value))"><slot /></select>',
  },
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
  'el-input': { props: ['modelValue'], emits: ['update:modelValue'], template: '<textarea :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
}

function mountPage() {
  return mount(Submit, { global: { stubs } })
}

function setFiles(input: HTMLInputElement, files: File[] | null) {
  Object.defineProperty(input, 'files', { configurable: true, value: files })
}

const setupOf = (wrapper: ReturnType<typeof mount>) =>
  (wrapper.vm as unknown as { $: { setupState: Record<string, unknown> } }).$.setupState

describe('repair submission page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.valid = true
    mocks.validationThrows = false
    mocks.searchDevices.mockResolvedValue(page())
    mocks.createRepair.mockResolvedValue(undefined)
    mocks.uploadRepairImage.mockImplementation(async (file: File) => ({ url: `/uploads/${file.name}` }))
    mocks.push.mockResolvedValue(undefined)
  })

  it('loads idle devices in bounded batches, labels locations and keeps selector empty on load failure', async () => {
    mocks.searchDevices.mockResolvedValueOnce(page([device(1, '光学实验室')], 8))
    mocks.searchDevices.mockImplementation(async (query: { page: number }) => page([device(query.page)]))
    const wrapper = mountPage()
    await flushPromises()

    expect(mocks.searchDevices).toHaveBeenNthCalledWith(1, { page: 1, size: 100, status: 'IDLE' })
    expect(mocks.searchDevices).toHaveBeenCalledTimes(8)
    expect(mocks.searchDevices).toHaveBeenNthCalledWith(2, { page: 2, size: 100, status: 'IDLE' })
    expect(mocks.searchDevices).toHaveBeenNthCalledWith(8, { page: 8, size: 100, status: 'IDLE' })
    expect(wrapper.findAll('option').map((option) => option.text())).toContain('#1 · 设备-1 · 光学实验室')
    expect(wrapper.findAll('option').map((option) => option.text())).toContain('#2 · 设备-2')

    const setup = setupOf(wrapper)
    const label = setup.deviceOptionLabel as (row: ReturnType<typeof device>) => string
    expect(label(device(3))).toBe('#3 · 设备-3')
    mocks.searchDevices.mockRejectedValueOnce(new Error('catalog unavailable'))
    await (setup.loadDevices as () => Promise<void>)()
    expect(setup.devices).toEqual([device(1, '光学实验室'), ...Array.from({ length: 7 }, (_, index) => device(index + 2))])

    mocks.searchDevices.mockResolvedValueOnce(page([device(20)], 0))
    await (setup.loadDevices as () => Promise<void>)()
    expect(mocks.searchDevices).toHaveBeenLastCalledWith({ page: 1, size: 100, status: 'IDLE' })
    expect(setup.devices).toEqual([device(20)])

    mocks.searchDevices.mockRejectedValueOnce(new Error('offline'))
    const failedLoad = mountPage()
    await flushPromises()
    expect(failedLoad.exists()).toBe(true)
    expect(failedLoad.findAll('option')).toHaveLength(0)
  })

  it('validates file count, image MIME and size, and clears invalid selections', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const setup = setupOf(wrapper)
    const input = wrapper.get('input[type="file"]').element as HTMLInputElement
    const onFilesChange = setup.onFilesChange as (event: Event) => void

    setFiles(input, null)
    onFilesChange({ target: input } as unknown as Event)
    expect(setup.selectedFiles).toEqual([])

    const tooMany = Array.from({ length: 7 }, (_, index) => new File([String(index)], `${index}.png`, { type: 'image/png' }))
    setFiles(input, tooMany)
    await wrapper.get('input[type="file"]').trigger('change')
    expect(mocks.warning).toHaveBeenCalledWith('故障图片最多选择 6 张')
    expect(setup.selectedFiles).toEqual([])

    setFiles(input, [new File(['invalid'], 'notes.txt', { type: 'text/plain' })])
    await wrapper.get('input[type="file"]').trigger('change')
    expect(mocks.warning).toHaveBeenLastCalledWith('只支持 JPG、PNG、WebP，且单张图片不能超过 5 MB')

    setFiles(input, [new File([new Uint8Array(5 * 1024 * 1024 + 1)], 'large.png', { type: 'image/png' })])
    await wrapper.get('input[type="file"]').trigger('change')
    expect(mocks.warning).toHaveBeenLastCalledWith('只支持 JPG、PNG、WebP，且单张图片不能超过 5 MB')

    const valid = new File(['image'], 'photo.webp', { type: 'image/webp' })
    setFiles(input, [valid])
    await wrapper.get('input[type="file"]').trigger('change')
    expect(setup.selectedFiles).toEqual([valid])
    expect(wrapper.text()).toContain('已选择 1 张图片')
  })

  it('submits trimmed repair details with uploaded images and external URLs', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('select').setValue('1')
    const fields = wrapper.findAll('textarea')
    await fields[0].setValue('  设备无法启动  ')
    await fields[1].setValue('  开机后无显示  ')
    await fields[2].setValue(' https://img.example/a.png, , https://img.example/b.png ')
    const file = new File(['image'], 'motor.png', { type: 'image/png' })
    const input = wrapper.get('input[type="file"]').element as HTMLInputElement
    setFiles(input, [file])
    await wrapper.get('input[type="file"]').trigger('change')
    await wrapper.find('.gradient').trigger('click')
    await flushPromises()

    expect(mocks.uploadRepairImage).toHaveBeenCalledWith(file)
    expect(mocks.createRepair).toHaveBeenCalledWith({
      deviceId: 1,
      title: '设备无法启动',
      description: '开机后无显示',
      imageUrls: ['https://img.example/a.png', 'https://img.example/b.png', '/uploads/motor.png'],
    })
    expect(mocks.success).toHaveBeenCalledWith('报修已提交')
    expect(mocks.push).toHaveBeenCalledWith({ name: 'repair-mine' })
  })

  it('guards invalid form and payload values, excessive URLs, and combined image limits', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const setup = setupOf(wrapper)
    const onSubmit = setup.onSubmit as () => Promise<void>
    mocks.valid = false
    await onSubmit()
    expect(mocks.createRepair).not.toHaveBeenCalled()

    mocks.valid = true
    setup.form = { deviceId: 0, title: '故障描述', description: '', imageUrlsText: '' }
    await onSubmit()
    expect(mocks.warning).toHaveBeenCalledWith('请选择需要报修的设备')
    setup.form = { deviceId: 1.5, title: '故障描述', description: '', imageUrlsText: '' }
    await onSubmit()
    setup.form = { deviceId: 1, title: ' ', description: '', imageUrlsText: '' }
    await onSubmit()
    expect(mocks.warning).toHaveBeenCalledWith('标题至少填写 2 个字符')
    setup.form = { deviceId: 1, title: '短', description: '', imageUrlsText: '' }
    await onSubmit()
    expect(mocks.warning).toHaveBeenCalledWith('标题至少填写 2 个字符')

    setup.form = { deviceId: 1, title: '设备损坏', description: '', imageUrlsText: Array.from({ length: 7 }, (_, i) => `https://img/${i}`).join(',') }
    await onSubmit()
    expect(mocks.warning).toHaveBeenCalledWith('图片 URL 最多填写 6 个')

    setup.form = { deviceId: 1, title: '设备损坏', description: '', imageUrlsText: 'https://img/1' }
    setup.selectedFiles = Array.from({ length: 6 }, (_, i) => new File([String(i)], `${i}.png`, { type: 'image/png' }))
    await onSubmit()
    expect(mocks.warning).toHaveBeenCalledWith('图片最多提交 6 个')
    expect(mocks.uploadRepairImage).not.toHaveBeenCalled()
  })

  it('handles absent form refs, upload and create failures, optional text, and cancel navigation', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const setup = setupOf(wrapper)
    const onSubmit = setup.onSubmit as () => Promise<void>
    const formRef = setup.formRef
    setup.formRef = undefined
    await onSubmit()
    expect(mocks.createRepair).not.toHaveBeenCalled()

    setup.formRef = formRef
    setup.form = { deviceId: 1, title: '设备故障', description: '   ', imageUrlsText: '' }
    setup.selectedFiles = [new File(['image'], 'broken.png', { type: 'image/png' })]
    mocks.validationThrows = true
    await onSubmit()
    expect(mocks.createRepair).not.toHaveBeenCalled()
    mocks.validationThrows = false
    mocks.uploadRepairImage.mockRejectedValueOnce(new Error('upload failed'))
    await onSubmit()
    expect(mocks.createRepair).not.toHaveBeenCalled()
    expect(setup.uploading).toBe(false)

    setup.selectedFiles = []
    mocks.createRepair.mockRejectedValueOnce(new Error('create failed'))
    await onSubmit()
    expect(mocks.createRepair).toHaveBeenCalledWith({
      deviceId: 1, title: '设备故障', description: undefined, imageUrls: undefined,
    })
    expect(setup.submitting).toBe(false)
    expect(mocks.push).not.toHaveBeenCalled()

    await wrapper.find('.ghost').trigger('click')
    expect(mocks.back).toHaveBeenCalledOnce()
  })
})
