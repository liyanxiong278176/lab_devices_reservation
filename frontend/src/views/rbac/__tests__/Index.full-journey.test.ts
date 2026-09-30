import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { cloneVNode, defineComponent, h, nextTick } from 'vue'

const api = vi.hoisted(() => ({
  createRole: vi.fn(),
  deleteRole: vi.fn(),
  listPermissions: vi.fn(),
  listRoles: vi.fn(),
  renameRole: vi.fn(),
  updateRolePermissions: vi.fn(),
}))
const messages = vi.hoisted(() => ({ success: vi.fn() }))
const dialogs = vi.hoisted(() => ({ confirm: vi.fn() }))
vi.mock('@/api/rbac', () => api)
vi.mock('element-plus', () => ({ ElMessage: messages, ElMessageBox: dialogs }))

import RbacIndex from '../Index.vue'

const systemRole = { id: 1, code: 'SYS_ADMIN', name: '系统管理员', is_system: true, permissions: ['system:read'] }
const customRole = {
  id: 2,
  code: 'SAFETY_OFFICER',
  name: '安全员',
  is_system: false,
  permissions: ['device:read', 'reservation:read', 'user:read', 'report:read', 'repair:read', 'handover:read'],
}
const roles = [systemRole, customRole]
const permissions = [
  { code: 'device:read', name: '查看设备', module: '设备' },
  { code: 'device:manage', name: '管理设备', module: '设备' },
  { code: 'reservation:approve', name: '审批预约', module: '预约' },
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
  props: ['row'],
  setup(props, { slots }) {
    return () => h('div', slots.default?.({ row: props.row }))
  },
})
const CheckboxGroupStub = defineComponent({
  name: 'ElCheckboxGroupStub',
  props: { modelValue: { type: Array, default: () => [] } },
  emits: ['update:modelValue'],
  setup(props, { emit, slots }) {
    return () => h('div', {
      class: 'checkbox-group-stub',
      onClick: (event: MouseEvent) => {
        const code = (event.target as HTMLElement).closest<HTMLButtonElement>('[data-permission]')?.dataset.permission
        if (!code) return
        const selected = [...props.modelValue] as string[]
        const index = selected.indexOf(code)
        if (index >= 0) selected.splice(index, 1)
        else selected.push(code)
        emit('update:modelValue', selected)
      },
    }, slots.default?.())
  },
})

const stubs = {
  PageHeader: { props: ['title'], template: '<header>{{ title }}<slot name="actions" /></header>' },
  GradientButton: { props: ['loading'], emits: ['click'], template: '<button class="gradient-button" :disabled="loading" @click="$emit(\'click\')"><slot /></button>' },
  GhostButton: { props: ['disabled'], emits: ['click'], template: '<button class="ghost-button" :disabled="disabled" @click="$emit(\'click\')"><slot /></button>' },
  'el-table': TableStub,
  'el-table-column': ColumnStub,
  'el-dialog': { props: ['modelValue', 'title'], emits: ['update:modelValue'], template: '<div v-if="modelValue" class="dialog-stub"><h2>{{ title }}</h2><button class="dialog-dismiss" @click="$emit(\'update:modelValue\', false)">关闭</button><slot /><footer class="dialog-footer"><slot name="footer" /></footer></div>' },
  'el-form': { template: '<form><slot /></form>' },
  'el-form-item': { props: ['label'], template: '<label>{{ label }}<slot /></label>' },
  'el-input': { props: ['modelValue'], template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
  'el-checkbox-group': CheckboxGroupStub,
  'el-checkbox': { props: ['value'], template: '<button type="button" :data-permission="value"><slot /></button>' },
}

function mountPage() {
  return mount(RbacIndex, { global: { stubs, directives: { loading: () => {} } } })
}

async function loadPage() {
  const wrapper = mountPage()
  await flushPromises()
  return wrapper
}

describe('RBAC administration full user journeys', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listRoles.mockResolvedValue(roles)
    api.listPermissions.mockResolvedValue(permissions)
    api.createRole.mockResolvedValue(undefined)
    api.renameRole.mockResolvedValue(undefined)
    api.updateRolePermissions.mockResolvedValue(undefined)
    api.deleteRole.mockResolvedValue(undefined)
    dialogs.confirm.mockResolvedValue('confirm')
  })

  it('creates a normalized role and reloads authoritative role data', async () => {
    const wrapper = await loadPage()
    expect(wrapper.text()).toContain('角色与权限')
    expect(wrapper.findAll('.table-row')).toHaveLength(2)
    expect(wrapper.text()).toContain('+1')

    await wrapper.get('.gradient-button').trigger('click')
    await wrapper.get('.dialog-footer .ghost-button').trigger('click')
    expect(wrapper.find('.dialog-stub').exists()).toBe(false)
    await wrapper.get('.gradient-button').trigger('click')
    await wrapper.findAll('input')[0].setValue('  safety_helper ')
    await wrapper.findAll('input')[1].setValue('  实验室安全协助员  ')
    await wrapper.get('.dialog-footer .gradient-button').trigger('click')
    await flushPromises()

    expect(api.createRole).toHaveBeenCalledWith({
      role_code: 'SAFETY_HELPER',
      role_name: '实验室安全协助员',
      permission_codes: [],
    })
    expect(messages.success).toHaveBeenCalledWith('角色已创建')
    expect(api.listRoles.mock.calls.length).toBeGreaterThan(1)
  })

  it('updates a custom role permission set grouped by module', async () => {
    const wrapper = await loadPage()
    await wrapper.findAll('.rbac-page__actions')[1].find('.ghost-button').trigger('click')
    expect(wrapper.findAll('.rbac-page__permission-groups h3').map((node) => node.text())).toEqual(['设备', '预约'])
    await wrapper.find('[data-permission="reservation:approve"]').trigger('click')
    await wrapper.get('.dialog-footer .gradient-button').trigger('click')
    await flushPromises()

    expect(api.updateRolePermissions).toHaveBeenCalledWith(2, [...customRole.permissions, 'reservation:approve'])
    expect(messages.success).toHaveBeenCalledWith('角色权限已更新，用户下次请求立即生效')
  })

  it('renames a custom role after trimming the new display name', async () => {
    const wrapper = await loadPage()
    await wrapper.findAll('.rbac-page__actions')[1].findAll('.ghost-button')[1].trigger('click')
    await wrapper.find('input').setValue('  实验室安全负责人  ')
    await wrapper.get('.dialog-footer .gradient-button').trigger('click')
    await flushPromises()

    expect(api.renameRole).toHaveBeenCalledWith(2, '实验室安全负责人')
    expect(messages.success).toHaveBeenCalledWith('角色名称已更新')
  })

  it('deletes a custom role only after confirmation and treats cancellation as a no-op', async () => {
    const wrapper = await loadPage()
    await wrapper.findAll('.rbac-page__actions')[1].find('.rbac-page__delete').trigger('click')
    await flushPromises()
    expect(dialogs.confirm).toHaveBeenCalledWith(expect.stringContaining('删除角色“安全员”'), '删除角色', expect.any(Object))
    expect(api.deleteRole).toHaveBeenCalledWith(2)
    expect(messages.success).toHaveBeenCalledWith('角色已删除')

    dialogs.confirm.mockRejectedValueOnce(new Error('cancel'))
    await wrapper.findAll('.rbac-page__actions')[1].find('.rbac-page__delete').trigger('click')
    await flushPromises()
    expect(api.deleteRole).toHaveBeenCalledOnce()
  })

  it('retains all system role protections even if a disabled action receives a click', async () => {
    const wrapper = await loadPage()
    const systemActions = wrapper.findAll('.rbac-page__actions')[0]
    const buttons = systemActions.findAll('button')

    for (const button of buttons) {
      ;(button.element as HTMLButtonElement).disabled = false
      await button.trigger('click')
    }
    await flushPromises()

    expect(wrapper.find('.dialog-stub').exists()).toBe(false)
    expect(dialogs.confirm).not.toHaveBeenCalled()
    expect(api.renameRole).not.toHaveBeenCalled()
    expect(api.updateRolePermissions).not.toHaveBeenCalled()
    expect(api.deleteRole).not.toHaveBeenCalled()
  })

  it('handles a dialog close event and stale permission-editor state without a role', async () => {
    const wrapper = await loadPage()
    const state = (wrapper.vm as any).$.setupState as Record<string, any>
    state.editorMode = 'permissions'
    state.activeRole = null
    state.editorVisible = true
    await nextTick()

    expect(wrapper.find('.dialog-stub h2').text()).toBe('配置权限 ·')
    await wrapper.get('.dialog-dismiss').trigger('click')
    expect(wrapper.find('.dialog-stub').exists()).toBe(false)

    state.editorVisible = true
    await nextTick()
    await wrapper.get('.dialog-footer .gradient-button').trigger('click')
    await flushPromises()

    expect(api.updateRolePermissions).not.toHaveBeenCalled()
    expect(api.renameRole).not.toHaveBeenCalled()
  })
})
