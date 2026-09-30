import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import EmptyState from '../EmptyState.vue'

describe('EmptyState', () => {
  it('renders the status container with optional title, description, icon and action', () => {
    const plain = mount(EmptyState)
    expect(plain.attributes('role')).toBe('status')
    expect(plain.attributes('aria-live')).toBe('polite')
    expect(plain.find('.empty-state__title').exists()).toBe(false)
    expect(plain.find('.empty-state__description').exists()).toBe(false)
    expect(plain.find('.empty-state__action').exists()).toBe(false)

    const configured = mount(EmptyState, {
      props: { icon: 'Inbox', title: 'No devices', description: 'Try again later' },
      slots: { action: '<button>Browse</button>' },
      global: { stubs: { 'el-icon': { template: '<i class="icon-stub"><slot /></i>' } } },
    })
    expect(configured.find('.empty-state__title').text()).toBe('No devices')
    expect(configured.find('.empty-state__description').text()).toBe('Try again later')
    expect(configured.find('.icon-stub').exists()).toBe(true)
    expect(configured.find('.empty-state__action').text()).toBe('Browse')
  })

  it('uses a provided icon slot instead of rendering the icon prop', () => {
    const wrapper = mount(EmptyState, {
      props: { icon: 'Inbox' },
      slots: { icon: '<span class="custom-icon">Custom</span>' },
      global: { stubs: { 'el-icon': true } },
    })
    expect(wrapper.find('.custom-icon').text()).toBe('Custom')
    expect(wrapper.findComponent({ name: 'ElIcon' }).exists()).toBe(false)
  })
})
