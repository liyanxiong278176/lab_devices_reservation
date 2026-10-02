import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { cloneVNode, defineComponent, h, nextTick } from 'vue'

const api = vi.hoisted(() => ({
  categoryTree: vi.fn(),
  createDevice: vi.fn(),
  deleteDevice: vi.fn(),
  listLabs: vi.fn(),
  listDevicePoolOptions: vi.fn(),
  patchDeviceStatus: vi.fn(),
  searchDevices: vi.fn(),
  updateDevice: vi.fn(),
}))
const messages = vi.hoisted(() => ({ success: vi.fn() }))
const dialogs = vi.hoisted(() => ({ confirm: vi.fn() }))
const router = vi.hoisted(() => ({ push: vi.fn() }))
const validation = vi.hoisted(() => vi.fn())
vi.mock('@/api/device', () => ({ createDevice: api.createDevice, deleteDevice: api.deleteDevice, listDevicePoolOptions: api.listDevicePoolOptions, patchDeviceStatus: api.patchDeviceStatus, searchDevices: api.searchDevices, updateDevice: api.updateDevice }))
vi.mock('@/api/category', () => ({ categoryTree: api.categoryTree }))
vi.mock('@/api/lab', () => ({ listLabs: api.listLabs }))
vi.mock('vue-router', () => ({ useRouter: () => router }))
vi.mock('@/router', () => ({ readSpaDepth: () => 0 }))
vi.mock('element-plus', () => ({ ElMessage: messages, ElMessageBox: dialogs }))

import DeviceManage from '../Manage.vue'

const records = [
  {
    id: 1, name: '激光显微镜', categoryId: 2, categoryName: '显微镜', labId: 10, labName: '光学实验室',
    brand: 'Olympus', model: 'BX-1', specs: '100x', imageUrl: '/device.png', status: 'IDLE', needApproval: 1,
    maxReservationDays: 5, tags: ['光学', '精密'], accessoryChecklist: ['电源线', '数据线'], description: '荧光成像', createdAt: '2026-08-02T10:00:00',
  },
  {
    id: 2, name: '使用中设备', categoryId: null, categoryName: '', labId: null, labName: '', brand: '', model: '', specs: '', imageUrl: '',
    status: 'IN_USE', needApproval: 0, maxReservationDays: null, tags: [], accessoryChecklist: [], description: '', createdAt: undefined,
  },
  { id: 3, name: '维修设备', categoryId: 1, categoryName: '显微设备', labId: 10, labName: '光学实验室', status: 'MAINTENANCE', needApproval: 0, tags: [], accessoryChecklist: [] },
  { id: 4, name: '离线设备', categoryId: 1, categoryName: '显微设备', labId: 10, labName: '光学实验室', status: 'OFFLINE', needApproval: 0, tags: [], accessoryChecklist: [] },
  { id: 5, name: '停用设备', categoryId: 1, categoryName: '显微设备', labId: 10, labName: '光学实验室', status: 'DISABLED', needApproval: 0, tags: [], accessoryChecklist: [] },
  { id: 6, name: '退役设备', categoryId: 1, categoryName: '显微设备', labId: 10, labName: '光学实验室', status: 'RETIRED', needApproval: 0, tags: [], accessoryChecklist: [] },
  { id: 7, name: '未知状态设备', categoryId: 1, categoryName: '显微设备', labId: 10, labName: '光学实验室', status: 'BROKEN', needApproval: 0, tags: [], accessoryChecklist: [] },
]
function page(items = records, overrides: Record<string, unknown> = {}) {
  return { records: items, total: 57, size: 10, current: 1, pages: 6, truncated: true, ...overrides }
}
const categories = [{ id: 1, name: '光学设备', children: [{ id: 2, name: '显微镜', children: [] }] }]
const labs = [{ id: 10, name: '光学实验室' }, { id: 11, name: '精密仪器室' }]

const TableStub = defineComponent({
  name: 'ElTableStub',
  props: ['data'],
  setup(props, { slots }) {
    return () => {
      const rows = props.data as unknown[]
      if (!rows.length) return h('div', { class: 'table-stub' }, slots.empty?.())
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
const FormStub = defineComponent({
  name: 'ElFormStub',
  setup(_, { expose, slots }) {
    expose({ validate: () => validation() })
    return () => h('form', slots.default?.())
  },
})
const SelectStub = defineComponent({
  name: 'ElSelectStub',
  props: ['modelValue', 'disabled'],
  emits: ['update:modelValue', 'change'],
  setup(props, { emit, slots }) {
    const onChange = (event: Event) => {
      const raw = (event.target as HTMLSelectElement).value
      const value = /^\d+$/.test(raw) ? Number(raw) : raw
      emit('update:modelValue', value)
      emit('change', value)
    }
    return () => h('select', { value: props.modelValue ?? '', disabled: props.disabled, onChange }, slots.default?.())
  },
})
const TreeSelectStub = defineComponent({
  name: 'ElTreeSelectStub',
  props: ['modelValue', 'data'],
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    const flatten = (nodes: Array<Record<string, any>>): Array<Record<string, any>> => nodes.flatMap((node) => [node, ...flatten(node.children ?? [])])
    return () => h('select', {
      value: props.modelValue ?? '',
      onChange: (event: Event) => {
        const raw = (event.target as HTMLSelectElement).value
        emit('update:modelValue', raw ? Number(raw) : undefined)
      },
    }, flatten(props.data).map((node) => h('option', { value: node.id }, node.name)))
  },
})
const DropdownStub = defineComponent({
  name: 'ElDropdownStub',
  emits: ['command'],
  setup(_, { emit, slots }) {
    return () => h('div', {
      class: 'dropdown-stub',
      onClick: (event: MouseEvent) => {
        const raw = (event.target as HTMLElement).closest<HTMLButtonElement>('[data-command]')?.dataset.command
        if (raw) emit('command', raw)
      },
    }, [slots.default?.(), slots.dropdown?.()])
  },
})

const stubs = {
  PageHeader: { props: ['title'], template: '<header>{{ title }}<slot name="actions" /></header>' },
  GradientButton: { props: ['loading'], emits: ['click'], template: '<button class="gradient-button" :disabled="loading" @click="$emit(\'click\')"><slot /></button>' },
  GhostButton: { emits: ['click'], template: '<button class="ghost-button" @click="$emit(\'click\')"><slot /></button>' },
  TextButton: { emits: ['click'], template: '<button class="text-button" @click="$emit(\'click\')"><slot /></button>' },
  Tag: { props: ['variant'], template: '<span class="tag-stub" :data-variant="variant"><slot /></span>' },
  PageDepthNotice: { props: ['total'], template: '<div class="depth-notice">深页 {{ total }}</div>' },
  'el-table': TableStub,
  'el-table-column': ColumnStub,
  'el-pagination': { props: ['currentPage', 'pageSize'], emits: ['current-change', 'size-change'], template: '<div><button class="next-page" @click="$emit(\'current-change\', currentPage + 1)">下一页</button><button class="change-size" @click="$emit(\'size-change\', 20)">每页20条</button></div>' },
  'el-drawer': { props: ['modelValue'], emits: ['update:modelValue'], template: '<aside v-if="modelValue" class="drawer-stub"><slot /><button class="drawer-model-close" @click="$emit(\'update:modelValue\', false)">drawer close</button><footer class="drawer-footer"><slot name="footer" /></footer></aside>' },
  'el-form': FormStub,
  'el-form-item': { props: ['label'], template: '<label>{{ label }}<slot /></label>' },
  'el-input': { props: ['modelValue', 'placeholder'], emits: ['update:modelValue', 'keyup.enter', 'clear'], template: '<span><input :value="modelValue" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" @keyup.enter="$emit(\'keyup.enter\')"/><button class="clear-input" @click="$emit(\'clear\')">clear</button></span>' },
  'el-select': SelectStub,
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
  'el-tree-select': TreeSelectStub,
  'el-switch': { props: ['modelValue', 'activeValue', 'inactiveValue'], emits: ['update:modelValue'], template: '<input type="checkbox" :checked="modelValue === activeValue" @change="$emit(\'update:modelValue\', $event.target.checked ? activeValue : inactiveValue)" />' },
  'el-input-number': { props: ['modelValue'], emits: ['update:modelValue'], template: '<input type="number" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value ? Number($event.target.value) : null)" />' },
  'el-dropdown': DropdownStub,
  'el-dropdown-menu': { template: '<div><slot /></div>' },
  'el-dropdown-item': { props: ['command'], template: '<button type="button" :data-command="command"><slot /></button>' },
  'el-icon': { template: '<i><slot /></i>' },
  'el-button': { emits: ['click'], template: '<button class="el-button-stub" @click="$emit(\'click\')"><slot /></button>' },
}

function mountPage() {
  return mount(DeviceManage, { global: { stubs, directives: { loading: () => {}, permission: () => {} } } })
}
function setup(wrapper: ReturnType<typeof mount>) {
  return (wrapper.vm as unknown as { $: { setupState: Record<string, any> } }).$.setupState
}
async function settledPage() {
  const wrapper = mountPage()
  await flushPromises()
  return wrapper
}

describe('device management full CRUD journeys', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    records[0].status = 'IDLE'
    validation.mockResolvedValue(true)
    router.push.mockResolvedValue(undefined)
    dialogs.confirm.mockResolvedValue('confirm')
    api.categoryTree.mockResolvedValue(categories)
    api.listLabs.mockResolvedValue({ records: labs, total: labs.length })
    api.listDevicePoolOptions.mockResolvedValue([])
    api.searchDevices.mockResolvedValue(page())
    api.createDevice.mockResolvedValue(undefined)
    api.updateDevice.mockResolvedValue(undefined)
    api.deleteDevice.mockResolvedValue(undefined)
    api.patchDeviceStatus.mockResolvedValue(undefined)
  })

  it('loads catalog options and renders status, approval, truncation, and date labels', async () => {
    const wrapper = await settledPage()
    const state = setup(wrapper)
    expect(api.searchDevices).toHaveBeenCalledWith({ page: 1, size: 10, keyword: '' })
    expect(api.categoryTree).toHaveBeenCalledOnce()
    expect(api.listLabs).toHaveBeenCalledWith(1, 100)
    expect(api.listDevicePoolOptions).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('使用中')
    expect(wrapper.text()).toContain('维护中')
    expect(wrapper.text()).toContain('空闲')
    expect(wrapper.text()).toContain('深页 57')
    expect(wrapper.text()).toContain('2026-08-02')
    expect(wrapper.text()).toContain('否')
    expect(state.statusMeta('BROKEN').label).toBe('BROKEN')
    expect(state.statusVariant('IN_USE')).toBe('accent')
    expect(state.statusVariant('MAINTENANCE')).toBe('warning')
    expect(state.statusVariant('OFFLINE')).toBe('danger')
    expect(state.statusVariant('DISABLED')).toBe('default')
    expect(state.fmt()).toBe('—')
    api.searchDevices.mockResolvedValueOnce(page(records, { pages: 0, truncated: true }))
    await state.load()
    await nextTick()
    expect(wrapper.find('.depth-notice').text()).toContain('57')
  })

  it('searches, paginates, falls back from page zero, and shows an empty result state', async () => {
    api.searchDevices
      .mockResolvedValueOnce(page())
      .mockResolvedValueOnce(page())
      .mockResolvedValueOnce(page())
      .mockResolvedValueOnce(page())
      .mockResolvedValueOnce(page())
      .mockResolvedValueOnce(page([], { total: 0, truncated: false }))
    const wrapper = await settledPage()
    const state = setup(wrapper)
    await wrapper.get('.dmanage__search input').setValue('  microscope  ')
    await wrapper.get('.dmanage__search input').trigger('keyup.enter')
    await flushPromises()
    expect(api.searchDevices).toHaveBeenLastCalledWith({ page: 1, size: 10, keyword: '  microscope  ' })

    await wrapper.get('.change-size').trigger('click')
    await flushPromises()
    expect(state.query.size).toBe(20)
    await wrapper.get('.next-page').trigger('click')
    await flushPromises()
    expect(state.query.page).toBe(2)

    state.query.page = 0
    await state.load()
    expect(api.searchDevices).toHaveBeenLastCalledWith({ page: 1, size: 20, keyword: '  microscope  ' })
    await wrapper.get('.dmanage__search .clear-input').trigger('click')
    await flushPromises()
    expect(wrapper.find('.dmanage__empty').exists()).toBe(true)
  })

  it('opens create mode, builds a normalized payload, and creates through the drawer form', async () => {
    const wrapper = await settledPage()
    await wrapper.get('.gradient-button').trigger('click')
    expect(wrapper.find('.dmanage__drawer h2').text()).toBe('新建设备')
    const state = setup(wrapper)
    state.form.name = '  高精度相机  '
    state.form.categoryId = 2
    state.form.labId = 10
    state.form.brand = ''
    state.form.model = 'CAM-X'
    state.form.specs = ''
    state.form.imageUrl = ''
    state.form.needApproval = 1
    state.form.maxReservationDays = null
    state.form.tagsText = ' optics, ,精密, optics '
    state.form.accessoriesText = '电源线\n数据线，电源线, 镜头'
    state.form.description = ''
    await wrapper.get('.drawer-footer .gradient-button').trigger('click')
    await flushPromises()

    expect(api.createDevice).toHaveBeenCalledWith({
      name: '高精度相机', categoryId: 2, labId: 10, brand: undefined, model: 'CAM-X', specs: undefined,
      imageUrl: undefined, needApproval: 1, maxReservationDays: undefined,
      tags: ['optics', '精密', 'optics'], accessoryChecklist: ['电源线', '数据线', '镜头'], description: undefined,
      poolId: null,
    })
    expect(messages.success).toHaveBeenCalledWith('已新建')
  })

  it('updates every visible form control and closes the drawer through its model event', async () => {
    const wrapper = await settledPage()
    await wrapper.get('.gradient-button').trigger('click')
    const drawer = wrapper.get('.dmanage__drawer')
    const inputs = drawer.findAll('input')
    await inputs[0].setValue('相机')
    await drawer.findAll('select')[0].setValue('2')
    await drawer.findAll('select')[1].setValue('10')
    await drawer.findAll('select')[2].setValue('RETIRED')
    await inputs[1].setValue('佳能')
    await inputs[2].setValue('R5')
    await inputs[3].setValue('全画幅')
    await inputs[4].setValue('/camera.png')
    await inputs[5].setValue(true)
    await inputs[6].setValue('12')
    await inputs[7].setValue('影像, 实验')
    await inputs[8].setValue('电源适配器')
    await inputs[9].setValue('实验室相机')
    await nextTick()

    const state = setup(wrapper)
    expect(state.form).toMatchObject({
      name: '相机', categoryId: 2, labId: 10, brand: '佳能', model: 'R5', specs: '全画幅',
      imageUrl: '/camera.png', status: 'RETIRED', needApproval: 1, maxReservationDays: 12, tagsText: '影像, 实验',
      accessoriesText: '电源适配器', description: '实验室相机',
    })
    await wrapper.get('.drawer-footer .ghost-button').trigger('click')
    expect(state.dialogVisible).toBe(false)
    await wrapper.get('.gradient-button').trigger('click')
    await wrapper.get('.dmanage__drawer-close').trigger('click')
    expect(state.dialogVisible).toBe(false)
    await wrapper.get('.gradient-button').trigger('click')
    await wrapper.get('.drawer-model-close').trigger('click')
    expect(state.dialogVisible).toBe(false)
  })

  it('edits an existing device and normalizes null catalog and optional fields', async () => {
    const wrapper = await settledPage()
    const state = setup(wrapper)
    await wrapper.findAll('.table-row')[1].find('.text-button').trigger('click')
    await nextTick()
    expect(state.dialogTitle).toBe('编辑设备')
    expect(state.form.categoryId).toBeUndefined()
    expect(state.form.labId).toBeUndefined()
    expect(state.form.maxReservationDays).toBeNull()
    expect(state.form.accessoriesText).toBe('')
    state.form.categoryId = 2
    state.form.labId = 11
    state.form.tagsText = 'new'
    state.form.accessoriesText = 'adapter\nadapter，battery'
    await wrapper.get('.drawer-footer .gradient-button').trigger('click')
    await flushPromises()

    expect(api.updateDevice).toHaveBeenCalledWith(2, expect.objectContaining({
      name: '使用中设备', categoryId: 2, labId: 11, poolId: null, tags: ['new'], accessoryChecklist: ['adapter', 'battery'],
    }))
    expect(messages.success).toHaveBeenCalledWith('已更新')
  })

  it('opens legacy edit rows whose tag and accessory lists are missing', async () => {
    const wrapper = await settledPage()
    const state = setup(wrapper)
    state.openEdit({ ...records[1], tags: null, accessoryChecklist: null } as any)
    await nextTick()
    expect(state.form.tagsText).toBe('')
    expect(state.form.accessoriesText).toBe('')
  })

  it('validates forms, handles stale edit state, catches API errors, and resets submitting state', async () => {
    const wrapper = await settledPage()
    const state = setup(wrapper)
    state.openCreate()
    await nextTick()
    validation.mockRejectedValueOnce(new Error('invalid'))
    await state.onSubmit()
    expect(api.createDevice).not.toHaveBeenCalled()
    validation.mockResolvedValueOnce(false)
    await state.onSubmit()
    expect(state.submitting).toBe(false)

    state.dialogMode = 'edit'
    state.editingId = null
    validation.mockResolvedValueOnce(true)
    await state.onSubmit()
    expect(api.updateDevice).not.toHaveBeenCalled()

    state.openCreate()
    await nextTick()
    state.form.name = '失败设备'
    state.form.categoryId = 2
    state.form.labId = 10
    api.createDevice.mockRejectedValueOnce(new Error('offline'))
    await state.onSubmit()
    expect(state.submitting).toBe(false)

    api.searchDevices.mockRejectedValueOnce(new Error('offline'))
    await state.load()
    expect(state.loading).toBe(false)
    api.categoryTree.mockRejectedValueOnce(new Error('offline'))
    await state.loadOptions()
    expect(state.categories).toEqual(categories)
  })

  it('changes statuses through the dropdown and skips redundant updates', async () => {
    const wrapper = await settledPage()
    const state = setup(wrapper)
    const statusTag = wrapper.findAll('.table-row')[0].find('.tag-stub')
    expect(statusTag.text()).toContain('空闲')
    await wrapper.findAll('.table-row')[0].find('[data-command="MAINTENANCE"]').trigger('click')
    await flushPromises()
    expect(api.patchDeviceStatus).toHaveBeenCalledWith(1, 'MAINTENANCE')
    expect(records[0].status).toBe('MAINTENANCE')
    expect(messages.success).toHaveBeenCalledWith('状态已更新')

    await state.onChangeStatus(records[0] as any, 'MAINTENANCE')
    expect(api.patchDeviceStatus).toHaveBeenCalledOnce()
    api.patchDeviceStatus.mockRejectedValueOnce(new Error('offline'))
    await state.onChangeStatus(records[0] as any, 'OFFLINE')
    expect(records[0].status).toBe('MAINTENANCE')
  })

  it('confirms deletion, handles cancellation and failures, and navigates to policy setup', async () => {
    const wrapper = await settledPage()
    const state = setup(wrapper)
    await wrapper.find('.ghost-button').trigger('click')
    expect(router.push).toHaveBeenCalledWith({ name: 'reservation-rules' })

    dialogs.confirm.mockRejectedValueOnce(new Error('cancel'))
    await state.onDelete(records[0] as any)
    expect(api.deleteDevice).not.toHaveBeenCalled()

    await wrapper.findAll('.table-row')[0].find('.el-button-stub').trigger('click')
    await flushPromises()
    expect(api.deleteDevice).toHaveBeenCalledWith(1)
    expect(messages.success).toHaveBeenCalledWith('已删除')

    api.deleteDevice.mockRejectedValueOnce(new Error('offline'))
    await state.onDelete(records[1] as any)
    expect(api.deleteDevice).toHaveBeenCalledTimes(2)
  })
})
