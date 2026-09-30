import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { cloneVNode, defineComponent, h, nextTick } from 'vue'

const api = vi.hoisted(() => ({
  createCollege: vi.fn(),
  listColleges: vi.fn(),
  listManagers: vi.fn(),
  updateCollege: vi.fn(),
  createLab: vi.fn(),
  listLabs: vi.fn(),
  updateLab: vi.fn(),
}))
const messages = vi.hoisted(() => ({ success: vi.fn() }))
const validation = vi.hoisted(() => vi.fn())
vi.mock('@/api/college', () => ({ createCollege: api.createCollege, listColleges: api.listColleges, listManagers: api.listManagers, updateCollege: api.updateCollege }))
vi.mock('@/api/lab', () => ({ createLab: api.createLab, listLabs: api.listLabs, updateLab: api.updateLab }))
vi.mock('element-plus', () => ({ ElMessage: messages }))

import OrganizationIndex from '../Index.vue'

const colleges = [
  { id: 1, code: 'OPT', name: '光电学院', managerId: 11, managerName: '林老师' },
  { id: 2, code: 'CHEM', name: '化学学院', managerId: null, managerName: '' },
]
const labs = [
  { id: 10, collegeId: 1, collegeName: '光电学院', name: '光学实验室', location: 'A1-201', managerId: 11, managerName: '林老师', description: '激光与成像' },
  { id: 11, collegeId: 2, collegeName: '', name: '化学实验室', location: '', managerId: null, managerName: '', description: '' },
  { id: 12, collegeId: 999, collegeName: '', name: '临时实验室', location: '', managerId: undefined, managerName: '', description: '' },
]
const managers = [
  { id: 11, username: 'lin', realName: '林老师' },
  { id: 12, username: 'chen', realName: '' },
]

const TableStub = defineComponent({
  name: 'ElTableStub',
  props: ['data'],
  setup(props, { slots }) {
    return () => h('div', { class: 'table-stub' }, (props.data as unknown[]).map((row) =>
      h('div', { class: 'table-row' }, (slots.default?.() ?? []).map((column) => cloneVNode(column, { row }))),
    ))
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

const stubs = {
  PageHeader: { props: ['title'], template: '<header>{{ title }}<slot name="actions" /></header>' },
  GradientButton: { emits: ['click'], props: ['loading'], template: '<button class="gradient-button" :disabled="loading" @click="$emit(\'click\')"><slot /></button>' },
  GhostButton: { emits: ['click'], template: '<button class="ghost-button" @click="$emit(\'click\')"><slot /></button>' },
  TextButton: { emits: ['click'], template: '<button class="text-button" @click="$emit(\'click\')"><slot /></button>' },
  Tag: { template: '<span class="tag-stub"><slot /></span>' },
  'el-tabs': { props: ['modelValue'], emits: ['update:modelValue'], template: '<div><button class="show-colleges" @click="$emit(\'update:modelValue\', \'colleges\')">学院配置</button><button class="show-labs" @click="$emit(\'update:modelValue\', \'labs\')">实验室配置</button><slot /></div>' },
  'el-tab-pane': { template: '<section><slot /></section>' },
  'el-table': TableStub,
  'el-table-column': ColumnStub,
  'el-drawer': { props: ['modelValue'], emits: ['update:modelValue'], template: '<aside v-if="modelValue" class="drawer-stub"><button class="drawer-update-close" @click="$emit(\'update:modelValue\', false)">遮罩关闭</button><slot /><footer class="drawer-footer"><slot name="footer" /></footer></aside>' },
  'el-form': FormStub,
  'el-form-item': { props: ['label'], template: '<label>{{ label }}<slot /></label>' },
  'el-select': SelectStub,
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
  'el-input': { props: ['modelValue', 'disabled'], emits: ['update:modelValue'], template: '<input :value="modelValue" :disabled="disabled" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
}

function mountPage() {
  return mount(OrganizationIndex, { global: { stubs, directives: { loading: () => {} } } })
}
function setup(wrapper: ReturnType<typeof mount>) {
  return (wrapper.vm as unknown as { $: { setupState: Record<string, any> } }).$.setupState
}

describe('organization directory full CRUD journeys', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    validation.mockResolvedValue(true)
    api.listColleges.mockResolvedValue(colleges)
    api.listLabs.mockResolvedValue({ records: labs, total: labs.length })
    api.listManagers.mockResolvedValue(managers)
    api.createCollege.mockResolvedValue(undefined)
    api.updateCollege.mockResolvedValue(undefined)
    api.createLab.mockResolvedValue(undefined)
    api.updateLab.mockResolvedValue(undefined)
  })

  it('loads the organization overview and both college and lab table presentations', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(api.listColleges).toHaveBeenCalledOnce()
    expect(api.listLabs).toHaveBeenCalledWith(1, 200)
    expect(wrapper.text()).toContain('2个学院')
    expect(wrapper.text()).toContain('3间实验室')
    expect(wrapper.text()).toContain('暂未配置')

    const collegeEdit = wrapper.findAll('.organization__table')[0].find('.text-button')
    await collegeEdit.trigger('click')
    await flushPromises()
    expect(wrapper.find('.drawer-stub h2').text()).toBe('编辑学院')
    await wrapper.get('.drawer-update-close').trigger('click')
    await collegeEdit.trigger('click')
    await flushPromises()
    await wrapper.get('.drawer-footer .ghost-button').trigger('click')

    await wrapper.get('.show-labs').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('光电学院')
    expect(wrapper.text()).toContain('化学学院')
    expect(wrapper.text()).toContain('—')
    await wrapper.findAll('.organization__table')[1].find('.text-button').trigger('click')
    await flushPromises()
    expect(wrapper.find('.drawer-stub h2').text()).toBe('编辑实验室')
    await wrapper.get('.organization__drawer-close').trigger('click')
    expect(wrapper.find('.drawer-stub').exists()).toBe(false)
  })

  it('creates a college with an optional manager and reloads the directory', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('.gradient-button').trigger('click')
    expect(wrapper.find('.drawer-stub h2').text()).toBe('新增学院')
    await wrapper.findAll('.drawer-stub input')[0].setValue('BIO')
    await wrapper.findAll('.drawer-stub input')[1].setValue('生物学院')
    await wrapper.get('.drawer-footer .gradient-button').trigger('click')
    await flushPromises()

    expect(api.createCollege).toHaveBeenCalledWith({ code: 'BIO', name: '生物学院', managerId: null })
    expect(messages.success).toHaveBeenCalledWith('组织配置已保存')
    expect(api.listColleges).toHaveBeenCalledTimes(2)
  })

  it('updates a college and accepts an unset manager as null', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const state = setup(wrapper)
    state.openCollegeEdit(colleges[1])
    await flushPromises()
    expect(state.dialogTitle).toBe('编辑学院')
    state.collegeForm.name = '化学与材料学院'
    await wrapper.get('.drawer-stub select').setValue('12')
    await state.onSubmit()
    await flushPromises()

    expect(api.updateCollege).toHaveBeenCalledWith(2, { code: 'CHEM', name: '化学与材料学院', managerId: 12 })
    expect(api.listManagers).toHaveBeenCalledWith(2)

    state.openCollegeEdit(colleges[1])
    await flushPromises()
    state.collegeForm.managerId = undefined
    await state.onSubmit()
    await flushPromises()
    expect(api.updateCollege).toHaveBeenLastCalledWith(2, { code: 'CHEM', name: '化学学院', managerId: null })
  })

  it('creates a lab, refreshes managers when its college changes, and submits the selected owner', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const state = setup(wrapper)
    await wrapper.get('.show-labs').trigger('click')
    await wrapper.get('.gradient-button').trigger('click')
    await flushPromises()
    expect(state.dialogTitle).toBe('新增实验室')
    expect(state.labForm.collegeId).toBe(1)
    const selects = wrapper.findAll('.drawer-stub select')
    await selects[1].setValue('11')
    await selects[0].setValue('2')
    await flushPromises()
    expect(state.labForm.managerId).toBeUndefined()
    expect(api.listManagers).toHaveBeenLastCalledWith(2)
    await wrapper.findAll('.drawer-stub input')[0].setValue('生物成像实验室')
    await wrapper.findAll('.drawer-stub input')[1].setValue('B2-101')
    await selects[1].setValue('12')
    await wrapper.findAll('.drawer-stub input')[2].setValue('荧光显微成像')
    await wrapper.get('.drawer-footer .gradient-button').trigger('click')
    await flushPromises()

    expect(api.createLab).toHaveBeenCalledWith({
      collegeId: 2, name: '生物成像实验室', location: 'B2-101', managerId: 12, description: '荧光显微成像',
    })
  })

  it('updates an existing lab and normalizes absent location and description', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const state = setup(wrapper)
    state.openLabEdit({ id: 12, collegeId: 2, name: '临时实验室', location: undefined, managerId: null, description: undefined } as any)
    await flushPromises()
    expect(state.dialogTitle).toBe('编辑实验室')
    expect(state.labForm.location).toBe('')
    expect(state.labForm.description).toBe('')
    await state.onSubmit()
    await flushPromises()

    expect(api.updateLab).toHaveBeenCalledWith(12, {
      collegeId: 2, name: '临时实验室', location: '', managerId: null, description: '',
    })

    state.openLabEdit({ id: 13, collegeId: null, name: '孤立实验室', location: null, managerId: null, description: null } as any)
    await flushPromises()
    expect(state.labForm.collegeId).toBeUndefined()
    expect(state.labForm.location).toBe('')
    expect(state.labForm.description).toBe('')
  })

  it('stops before mutation on invalid forms or a lab without a college and always resets submitting state', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const state = setup(wrapper)
    state.openCollegeCreate()
    await nextTick()
    validation.mockRejectedValueOnce(new Error('invalid'))
    await state.onSubmit()
    expect(api.createCollege).not.toHaveBeenCalled()
    expect(state.submitting).toBe(false)

    state.openLabCreate()
    await flushPromises()
    await nextTick()
    state.labForm.collegeId = undefined
    validation.mockResolvedValueOnce(true)
    await state.onSubmit()
    expect(api.createLab).not.toHaveBeenCalled()
    expect(messages.success).toHaveBeenCalledWith('组织配置已保存')

    state.openCollegeCreate()
    await nextTick()
    state.collegeForm.code = 'FAIL'
    state.collegeForm.name = '失败学院'
    api.createCollege.mockRejectedValueOnce(new Error('create failed'))
    await expect(state.onSubmit()).rejects.toThrow('create failed')
    expect(state.submitting).toBe(false)
  })

  it('clears manager lists without a college and reports directory load failures while releasing loading state', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const state = setup(wrapper)
    await state.loadManagers(undefined)
    expect(state.managers).toEqual([])
    expect(api.listManagers).not.toHaveBeenCalled()

    api.listColleges.mockRejectedValueOnce(new Error('offline'))
    await expect(state.load()).rejects.toThrow('offline')
    expect(state.loading).toBe(false)
  })

  it('does not mutate records when an editor mode has lost its target identifier', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const state = setup(wrapper)
    state.dialogMode = 'college-edit'
    state.editingId = null
    state.dialogVisible = true
    await nextTick()
    await state.onSubmit()
    expect(api.updateCollege).not.toHaveBeenCalled()

    state.dialogMode = 'lab-edit'
    state.editingId = null
    state.labForm.collegeId = 1
    state.dialogVisible = true
    await nextTick()
    await state.onSubmit()
    expect(api.updateLab).not.toHaveBeenCalled()
    expect(api.createLab).not.toHaveBeenCalled()

    state.openLabCreate()
    await nextTick()
    state.labForm.collegeId = 1
    state.labForm.name = '无负责人实验室'
    state.labForm.managerId = undefined
    await state.onSubmit()
    await flushPromises()
    expect(api.createLab).toHaveBeenCalledWith({
      collegeId: 1, name: '无负责人实验室', location: '', managerId: null, description: '',
    })
  })
})
