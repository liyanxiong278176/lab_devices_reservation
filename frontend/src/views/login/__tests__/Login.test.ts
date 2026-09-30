import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'

const mocks = vi.hoisted(() => ({
  route: { path: '/login', query: {} as Record<string, unknown> },
  router: { push: vi.fn(), replace: vi.fn() },
  login: vi.fn(),
  register: vi.fn(),
  colleges: vi.fn(),
  messageSuccess: vi.fn(),
  reveal: vi.fn(),
  valid: true,
}))

vi.mock('vue-router', () => ({ useRoute: () => mocks.route, useRouter: () => mocks.router }))
vi.mock('@/stores/user', () => ({ useUserStore: () => ({ login: mocks.login, register: mocks.register }) }))
vi.mock('@/api/auth', () => ({ listRegistrationColleges: mocks.colleges }))
vi.mock('@/composables/useStagger', () => ({ useStagger: () => ({ reveal: mocks.reveal }) }))
vi.mock('element-plus', () => ({ ElMessage: { success: mocks.messageSuccess } }))

import Login from '../Login.vue'

const FormStub = defineComponent({
  props: ['model', 'rules', 'labelPosition', 'size'],
  setup(_props, { slots, expose }) {
    expose({ validate: async (callback: (valid: boolean) => void) => callback(mocks.valid) })
    return () => h('form', slots.default?.())
  },
})

const stubs = {
  'el-form': FormStub,
  'el-form-item': { props: ['label', 'prop'], template: '<label><span>{{ label }}</span><slot /></label>' },
  'el-input': {
    props: ['modelValue', 'placeholder'],
    emits: ['update:modelValue'],
    template: '<input :placeholder="placeholder" :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
  },
  'el-select': {
    props: ['modelValue'],
    emits: ['update:modelValue'],
    template: '<select :value="modelValue" @change="$emit(\'update:modelValue\', Number($event.target.value))"><slot /></select>',
  },
  'el-option': { props: ['value', 'label'], template: '<option :value="value">{{ label }}</option>' },
  GradientButton: {
    props: ['loading'],
    emits: ['click'],
    template: '<button class="gradient-button" :disabled="loading" @click="$emit(\'click\')"><slot /></button>',
  },
}

function mountLogin() {
  return mount(Login, { global: { stubs } })
}

describe('login and registration screen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.route.path = '/login'
    mocks.route.query = {}
    mocks.valid = true
    mocks.login.mockResolvedValue(undefined)
    mocks.register.mockResolvedValue(undefined)
    mocks.colleges.mockResolvedValue([
      { id: 5, name: '计算机学院' },
      { id: 8, name: '生命学院' },
    ])
  })

  it('submits a valid login and honors a requested redirect', async () => {
    mocks.route.query = { redirect: '/devices' }
    const wrapper = mountLogin()
    await wrapper.findAll('input')[0].setValue('student-1')
    await wrapper.findAll('input')[1].setValue('secret-password')
    await wrapper.find('.gradient-button').trigger('click')
    await flushPromises()

    expect(mocks.login).toHaveBeenCalledWith({ username: 'student-1', password: 'secret-password' })
    expect(mocks.register).not.toHaveBeenCalled()
    expect(mocks.messageSuccess).toHaveBeenCalledWith('登录成功')
    expect(mocks.router.push).toHaveBeenCalledWith('/devices')
    expect(wrapper.text()).toContain('欢迎回来')
    expect(wrapper.findComponent(FormStub).props('rules').username).toHaveLength(1)
  })

  it('does not submit invalid form data and clears loading state after a failed login', async () => {
    mocks.valid = false
    const wrapper = mountLogin()
    await wrapper.find('.gradient-button').trigger('click')
    await flushPromises()
    expect(mocks.login).not.toHaveBeenCalled()
    expect(mocks.router.push).not.toHaveBeenCalled()

    mocks.valid = true
    mocks.login.mockRejectedValueOnce(new Error('authentication failed'))
    await wrapper.find('.gradient-button').trigger('click')
    await flushPromises()
    expect(mocks.login).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.gradient-button').attributes('disabled')).toBeUndefined()
    expect(mocks.messageSuccess).not.toHaveBeenCalled()
  })

  it('switches into registration, loads colleges once, and submits tenant-bound details', async () => {
    const wrapper = mountLogin()
    await wrapper.find('.login-card__mode').trigger('click')
    await flushPromises()

    expect(mocks.router.replace).toHaveBeenCalledWith({ path: '/register', query: {} })
    expect(mocks.colleges).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('创建账号')
    expect(wrapper.findAll('input')).toHaveLength(3)
    expect(wrapper.find('select').findAll('option')).toHaveLength(2)
    const rules = wrapper.findComponent(FormStub).props('rules')
    expect(rules.username).toHaveLength(2)
    expect(rules.real_name).toHaveLength(1)
    expect(rules.college_id).toHaveLength(1)

    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('真实姓名')
    await inputs[1].setValue('new-student')
    await inputs[2].setValue('strong-password')
    await wrapper.find('select').setValue('5')
    await wrapper.find('.gradient-button').trigger('click')
    await flushPromises()

    expect(mocks.register).toHaveBeenCalledWith({
      username: 'new-student',
      password: 'strong-password',
      real_name: '真实姓名',
      college_id: 5,
    })
    expect(mocks.messageSuccess).toHaveBeenCalledWith('注册并登录成功')
    expect(mocks.router.push).toHaveBeenCalledWith('/dashboard')
    expect(mocks.colleges).toHaveBeenCalledTimes(1)
  })

  it('loads colleges on a direct registration visit and rejects a missing college selection', async () => {
    mocks.route.path = '/register'
    mocks.route.query = { from: 'invite' }
    const wrapper = mountLogin()
    await flushPromises()
    expect(mocks.colleges).toHaveBeenCalledTimes(1)

    await wrapper.findAll('input')[0].setValue('真实姓名')
    await wrapper.findAll('input')[1].setValue('new-student')
    await wrapper.findAll('input')[2].setValue('strong-password')
    await wrapper.find('.gradient-button').trigger('click')
    await flushPromises()

    expect(mocks.register).not.toHaveBeenCalled()
    expect(mocks.router.push).not.toHaveBeenCalled()
    await wrapper.find('.login-card__mode').trigger('click')
    expect(mocks.router.replace).toHaveBeenCalledWith({ path: '/login', query: { from: 'invite' } })
    await wrapper.find('.login-card__mode').trigger('click')
    expect(mocks.colleges).toHaveBeenCalledTimes(1)
  })

  it('does not duplicate an in-flight college list request and safely returns without a form ref', async () => {
    let resolveColleges: ((items: { id: number; name: string }[]) => void) | undefined
    mocks.colleges.mockImplementationOnce(
      () => new Promise((resolve) => { resolveColleges = resolve }),
    )
    const wrapper = mountLogin()
    await wrapper.find('.login-card__mode').trigger('click')
    await wrapper.find('.login-card__mode').trigger('click')
    await wrapper.find('.login-card__mode').trigger('click')
    expect(mocks.colleges).toHaveBeenCalledTimes(1)
    resolveColleges?.([{ id: 5, name: '计算机学院' }])
    await flushPromises()

    const instance = wrapper.vm as unknown as { $: { setupState: Record<string, unknown> } }
    const setup = instance.$.setupState
    const formRef = setup.formRef
    setup.formRef = undefined
    await (setup.onSubmit as () => Promise<void>)()
    expect(mocks.login).not.toHaveBeenCalled()
    setup.formRef = formRef
  })
})
