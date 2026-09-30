import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { cloneVNode, defineComponent, h, nextTick } from 'vue'

const api = vi.hoisted(() => ({
  createUser: vi.fn(),
  deleteUser: vi.fn(),
  listColleges: vi.fn(),
  listRoles: vi.fn(),
  listUsers: vi.fn(),
  patchUserStatus: vi.fn(),
  updateUser: vi.fn(),
}))
const messages = vi.hoisted(() => ({ success: vi.fn() }))
const dialogs = vi.hoisted(() => ({ confirm: vi.fn() }))
const validation = vi.hoisted(() => vi.fn())
vi.mock('@/api/college', () => ({ listColleges: api.listColleges }))
vi.mock('@/api/user', () => ({ createUser: api.createUser, deleteUser: api.deleteUser, listUsers: api.listUsers, patchUserStatus: api.patchUserStatus, updateUser: api.updateUser }))
vi.mock('@/api/rbac', () => ({ listRoles: api.listRoles }))
vi.mock('element-plus', () => ({ ElMessage: messages, ElMessageBox: dialogs }))

import UserIndex from '../Index.vue'

const users = [
  {
    id: 1, username: 'root', realName: '管理员', phone: '13800000001', email: 'root@example.test', deptName: '信息中心',
    userType: 'STAFF', roles: ['SYS_ADMIN', 'LAB_ADMIN', 'TEACHER', 'STAFF', 'STUDENT', 'CUSTOM_ROLE', 'UNKNOWN_ROLE'],
    status: 1, collegeId: 1, createdAt: '2026-08-01T10:00:00',
  },
  {
    id: 2, username: 'inactive', realName: '', phone: '', email: '', deptName: '', userType: '', roles: [],
    status: 0, collegeId: null, createdAt: undefined,
  },
]
const colleges = [
  { id: 1, code: 'OPT', name: '光电学院' },
  { id: 2, code: 'CHEM', name: '化学学院' },
]
const roles = [
  { id: 1, code: 'SYS_ADMIN', name: '系统管理员' },
  { id: 2, code: 'LAB_ADMIN', name: '实验室管理员' },
  { id: 3, code: 'TEACHER', name: '教师' },
  { id: 4, code: 'STAFF', name: '职工' },
  { id: 5, code: 'STUDENT', name: '学生' },
  { id: 6, code: 'CUSTOM_ROLE', name: '业务审核员' },
]
function page(records = users, overrides: Record<string, unknown> = {}) {
  return { records, total: 46, size: 10, current: 1, pages: 5, truncated: true, ...overrides }
}

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
  props: ['modelValue', 'multiple', 'disabled'],
  emits: ['update:modelValue', 'change'],
  setup(props, { emit, slots }) {
    const toValue = (raw: string) => /^\d+$/.test(raw) ? Number(raw) : raw
    const onChange = (event: Event) => {
      const target = event.target as HTMLSelectElement
      const value = target.multiple ? Array.from(target.selectedOptions).map((option) => option.value) : toValue(target.value)
      emit('update:modelValue', value)
      emit('change', value)
    }
    return () => h('select', { value: props.modelValue ?? (props.multiple ? [] : ''), multiple: props.multiple, disabled: props.disabled, onChange }, slots.default?.())
  },
})

const stubs = {
  PageHeader: { props: ['title'], template: '<header>{{ title }}<slot name="actions" /></header>' },
  GradientButton: { props: ['loading'], emits: ['click'], template: '<button class="gradient-button" :disabled="loading" @click="$emit(\'click\')"><slot /></button>' },
  GhostButton: { emits: ['click'], template: '<button class="ghost-button" @click="$emit(\'click\')"><slot /></button>' },
  TextButton: { emits: ['click'], template: '<button class="text-button" @click="$emit(\'click\')"><slot /></button>' },
  Tag: { props: ['variant'], template: '<span class="tag-stub" :data-variant="variant"><slot /></span>' },
  PageDepthNotice: { props: ['total'], template: '<div class="depth-notice">深页总数 {{ total }}</div>' },
  'el-table': TableStub,
  'el-table-column': ColumnStub,
  'el-pagination': { props: ['currentPage', 'pageSize'], emits: ['current-change', 'size-change'], template: '<div class="pagination-stub"><button class="next-page" @click="$emit(\'current-change\', currentPage + 1)">下一页</button><button class="change-size" @click="$emit(\'size-change\', 20)">每页 20 条</button></div>' },
  'el-drawer': { props: ['modelValue', 'title'], emits: ['update:modelValue'], template: '<aside v-if="modelValue" class="drawer-stub"><h2>{{ title }}</h2><button class="drawer-dismiss" @click="$emit(\'update:modelValue\', false)">关闭</button><slot /><footer class="drawer-footer"><slot name="footer" /></footer></aside>' },
  'el-form': FormStub,
  'el-form-item': { props: ['label'], template: '<label>{{ label }}<slot /></label>' },
  'el-input': { props: ['modelValue', 'disabled', 'placeholder'], emits: ['update:modelValue', 'keyup.enter', 'clear'], template: '<span class="input-stub"><input :value="modelValue" :disabled="disabled" :placeholder="placeholder" @input="$emit(\'update:modelValue\', $event.target.value)" @keyup.enter="$emit(\'keyup.enter\')"/><button class="clear-input" @click="$emit(\'clear\')">clear</button></span>' },
  'el-select': SelectStub,
  'el-option': { props: ['label', 'value'], template: '<option :value="value">{{ label }}</option>' },
}

function mountPage() {
  return mount(UserIndex, { global: { stubs, directives: { loading: () => {} } } })
}
function setup(wrapper: ReturnType<typeof mount>) {
  return (wrapper.vm as unknown as { $: { setupState: Record<string, any> } }).$.setupState
}

describe('user directory full CRUD and authorization journeys', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    users[0].status = 1
    users[1].status = 0
    validation.mockResolvedValue(true)
    api.listUsers.mockResolvedValue(page())
    api.listColleges.mockResolvedValue(colleges)
    api.listRoles.mockResolvedValue(roles)
    api.createUser.mockResolvedValue(undefined)
    api.updateUser.mockResolvedValue(undefined)
    api.patchUserStatus.mockResolvedValue(undefined)
    api.deleteUser.mockResolvedValue(undefined)
    dialogs.confirm.mockResolvedValue('confirm')
  })

  it('loads users, labels all role variants, shows depth limits and renders empty contact fallbacks', async () => {
    const wrapper = mountPage()
    await flushPromises()
    expect(api.listUsers).toHaveBeenCalledWith({ page: 1, size: 10, username: '', realName: '' })
    expect(wrapper.findAll('.table-row')).toHaveLength(2)
    expect(wrapper.text()).toContain('系统管理员')
    expect(wrapper.text()).toContain('实验室管理员')
    expect(wrapper.text()).toContain('教师')
    expect(wrapper.text()).toContain('职工')
    expect(wrapper.text()).toContain('学生')
    expect(wrapper.text()).toContain('业务审核员')
    expect(wrapper.text()).toContain('UNKNOWN_ROLE')
    expect(wrapper.text()).toContain('深页总数 46')
    expect(wrapper.text()).toContain('个账号')
    expect(wrapper.text()).toContain('—')
    expect(wrapper.text()).toContain('2026-08-01')

    await wrapper.findAll('.table-row')[1].findAll('.text-button')[1].trigger('click')
    await flushPromises()
    expect(api.patchUserStatus).toHaveBeenCalledWith(2, 1)
    await wrapper.findAll('.table-row')[1].findAll('.text-button')[0].trigger('click')
    await nextTick()
    expect(wrapper.find('.drawer-stub h2').text()).toBe('编辑用户')
    await wrapper.get('.drawer-dismiss').trigger('click')
  })

  it('waits for college names before showing fetched user rows', async () => {
    let resolveColleges!: (value: typeof colleges) => void
    api.listColleges.mockImplementation(() => new Promise((resolve) => {
      resolveColleges = resolve
    }))

    const wrapper = mountPage()
    await flushPromises()

    expect(wrapper.findAll('.table-row')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('全局')

    resolveColleges(colleges)
    await flushPromises()

    expect(wrapper.findAll('.table-row')).toHaveLength(2)
    expect(wrapper.text()).toContain('光电学院')
    wrapper.unmount()
  })

  it('searches by username and real name and uses the empty table state', async () => {
    api.listUsers
      .mockResolvedValueOnce(page())
      .mockResolvedValueOnce(page())
      .mockResolvedValueOnce(page())
      .mockResolvedValueOnce(page([], { total: 0, truncated: false }))
    const wrapper = mountPage()
    await flushPromises()
    const inputs = wrapper.findAll('.umanage__toolbar input')
    await inputs[0].setValue('  root  ')
    await inputs[0].trigger('keyup.enter')
    await flushPromises()
    expect(api.listUsers).toHaveBeenLastCalledWith({ page: 1, size: 10, username: '  root  ', realName: '' })
    await inputs[1].setValue('林老师')
    await inputs[1].trigger('keyup.enter')
    await flushPromises()
    expect(api.listUsers).toHaveBeenLastCalledWith({ page: 1, size: 10, username: '  root  ', realName: '林老师' })
    await wrapper.findAll('.umanage__toolbar .clear-input')[0].trigger('click')
    await flushPromises()
    expect(wrapper.find('.umanage__empty').exists()).toBe(true)
  })

  it('changes page size and current page with the truncated reachable range', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const state = setup(wrapper)
    await wrapper.get('.change-size').trigger('click')
    await flushPromises()
    expect(state.query.size).toBe(20)
    expect(state.query.page).toBe(1)
    expect(api.listUsers).toHaveBeenLastCalledWith({ page: 1, size: 20, username: '', realName: '' })
    await wrapper.get('.next-page').trigger('click')
    await flushPromises()
    expect(state.query.page).toBe(2)
    expect(api.listUsers).toHaveBeenLastCalledWith({ page: 2, size: 20, username: '', realName: '' })
    expect(state.totalLabel).toBe('共 46 条')
    state.page.pages = 0
    await nextTick()
    state.query.page = 0
    await state.load()
    expect(api.listUsers).toHaveBeenLastCalledWith({ page: 1, size: 20, username: '', realName: '' })
  })

  it('creates a user with optional profile fields, college, user type, and roles', async () => {
    const wrapper = mountPage()
    await flushPromises()
    await wrapper.get('.gradient-button').trigger('click')
    expect(wrapper.find('.drawer-stub h2').text()).toBe('新增用户')
    await wrapper.get('.drawer-footer .ghost-button').trigger('click')
    expect(wrapper.find('.drawer-stub').exists()).toBe(false)
    await wrapper.get('.gradient-button').trigger('click')
    const inputs = wrapper.findAll('.drawer-stub input')
    await inputs[0].setValue('  new_user  ')
    await inputs[1].setValue('strong-password')
    await inputs[2].setValue('新用户')
    await inputs[3].setValue('13812345678')
    await inputs[4].setValue('new@example.test')
    await inputs[5].setValue('实验中心')
    const selects = wrapper.findAll('.drawer-stub select')
    await selects[0].setValue('TEACHER')
    await selects[1].setValue('2')
    await selects[2].setValue(['LAB_ADMIN', 'TEACHER'])
    await wrapper.get('.drawer-footer .gradient-button').trigger('click')
    await flushPromises()

    expect(api.createUser).toHaveBeenCalledWith({
      username: 'new_user', password: 'strong-password', realName: '新用户', phone: '13812345678',
      email: 'new@example.test', userType: 'TEACHER', deptName: '实验中心', roleCodes: ['LAB_ADMIN', 'TEACHER'], collegeId: 2,
    })
    expect(messages.success).toHaveBeenCalledWith('已创建')
  })

  it('updates an account while leaving blank password and optional profile fields unset', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const state = setup(wrapper)
    state.openEdit({ ...users[1], roles: undefined } as any)
    await nextTick()
    expect(state.drawerTitle).toBe('编辑用户')
    expect(state.form.username).toBe('inactive')
    expect(state.form.userType).toBe('STUDENT')
    expect(state.form.roleCodes).toEqual([])
    expect(state.form.collegeId).toBeUndefined()
    await state.onSubmit()
    await flushPromises()

    expect(api.updateUser).toHaveBeenCalledWith(2, expect.objectContaining({
      username: 'inactive', password: undefined, realName: undefined, phone: undefined, email: undefined,
      deptName: undefined, roleCodes: [], collegeId: undefined,
    }))
    expect(messages.success).toHaveBeenCalledWith('已更新')
  })

  it('validates password and college requirements differently for create, edit, and system administrators', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const state = setup(wrapper)
    const passwordRule = state.rules.password[0].validator
    const collegeRule = state.rules.collegeId[0].validator
    const error = vi.fn()
    state.drawerMode = 'create'
    state.form.password = ''
    passwordRule({}, '', error)
    expect(error.mock.calls[0][0].message).toBe('请输入密码')
    state.drawerMode = 'edit'
    passwordRule({}, '', error)
    expect(error.mock.calls[1][0]).toBeUndefined()

    state.form.collegeId = undefined
    state.form.roleCodes = []
    collegeRule({}, undefined, error)
    expect(error.mock.calls[2][0].message).toBe('业务用户必须绑定学院')
    state.form.roleCodes = ['SYS_ADMIN']
    collegeRule({}, undefined, error)
    expect(error.mock.calls[3][0]).toBeUndefined()
  })

  it('handles toggling disabled users, confirmation cancellation, and patch failures', async () => {
    const wrapper = await settledPage()
    const state = setup(wrapper)
    const priorStatusCallCount = api.patchUserStatus.mock.calls.length
    users[1].status = 0
    dialogs.confirm.mockRejectedValueOnce(new Error('cancel'))
    await state.onToggleStatus(users[1])
    expect(api.patchUserStatus).toHaveBeenCalledTimes(priorStatusCallCount)

    await state.onToggleStatus(users[1])
    expect(api.patchUserStatus).toHaveBeenCalledWith(2, 1)
    expect(users[1].status).toBe(1)
    expect(messages.success).toHaveBeenCalledWith('已启用')

    api.patchUserStatus.mockRejectedValueOnce(new Error('offline'))
    await state.onToggleStatus(users[0])
    expect(users[0].status).toBe(1)
    expect(messages.success).toHaveBeenLastCalledWith('已启用')
  })

  it('disables accounts with a separate confirmation and retains state on failure', async () => {
    const wrapper = await settledPage()
    const state = setup(wrapper)
    await wrapper.findAll('.table-row')[0].findAll('.text-button')[1].trigger('click')
    await flushPromises()
    expect(api.deleteUser).toHaveBeenCalledWith(1)
    expect(users[0].status).toBe(0)

    dialogs.confirm.mockRejectedValueOnce(new Error('cancel'))
    users[0].status = 1
    await state.onDisable(users[0])
    expect(api.deleteUser).toHaveBeenCalledTimes(1)

    api.deleteUser.mockRejectedValueOnce(new Error('offline'))
    await state.onDisable(users[0])
    expect(users[0].status).toBe(1)
    expect(messages.success).toHaveBeenCalledWith('账号已停用，历史记录已保留')
  })

  it('handles form validation, stale edit state, list errors, and refreshes without stale loading state', async () => {
    const wrapper = mountPage()
    await flushPromises()
    const state = setup(wrapper)
    state.openCreate()
    await nextTick()
    validation.mockRejectedValueOnce(new Error('validation failed'))
    await state.onSubmit()
    expect(api.createUser).not.toHaveBeenCalled()
    expect(state.submitting).toBe(false)

    validation.mockResolvedValueOnce(false)
    await state.onSubmit()
    expect(api.createUser).not.toHaveBeenCalled()
    expect(state.submitting).toBe(false)

    state.drawerMode = 'edit'
    state.editingId = null
    validation.mockResolvedValueOnce(true)
    await state.onSubmit()
    expect(api.updateUser).not.toHaveBeenCalled()

    api.listUsers.mockRejectedValueOnce(new Error('offline'))
    await state.load()
    expect(state.loading).toBe(false)
  })
})

async function settledPage() {
  const wrapper = mountPage()
  await flushPromises()
  return wrapper
}
