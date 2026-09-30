import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'

const router = vi.hoisted(() => ({ back: vi.fn(), push: vi.fn() }))
const readSpaDepth = vi.hoisted(() => vi.fn())
vi.mock('vue-router', () => ({ useRouter: () => router }))
vi.mock('@/router', () => ({ readSpaDepth }))

import PageHeader from '../PageHeader.vue'

describe('PageHeader', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders required title and optional subtitle, breadcrumb and actions', () => {
    const plain = mount(PageHeader, { props: { title: 'Reservations' } })
    expect(plain.find('h1').text()).toBe('Reservations')
    expect(plain.find('.page-header__subtitle').exists()).toBe(false)
    expect(plain.find('.page-header__breadcrumb').exists()).toBe(false)
    expect(plain.find('.page-header__actions').exists()).toBe(false)

    const full = mount(PageHeader, {
      props: { title: 'Device', subtitle: 'Manage assets' },
      slots: { breadcrumb: '<span>Home / Devices</span>', actions: '<button>Add</button>' },
    })
    expect(full.find('.page-header__subtitle').text()).toBe('Manage assets')
    expect(full.find('.page-header__breadcrumb').text()).toContain('Home / Devices')
    expect(full.find('.page-header__actions').text()).toBe('Add')
  })

  it('uses browser back for positive SPA depth and dashboard fallback at depth zero', async () => {
    readSpaDepth.mockReturnValue(2)
    const internal = mount(PageHeader, { props: { title: 'Detail', back: true } })
    await internal.get('button[aria-label="返回上一级"]').trigger('click')
    expect(router.back).toHaveBeenCalledOnce()
    expect(router.push).not.toHaveBeenCalled()

    readSpaDepth.mockReturnValue(0)
    const direct = mount(PageHeader, { props: { title: 'Detail', back: true } })
    await direct.get('button[aria-label="返回上一级"]').trigger('click')
    expect(router.push).toHaveBeenCalledWith('/')
  })
})
