import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import App from './App.vue'

const RoutePage = defineComponent({ render: () => h('main', { class: 'route-page' }, 'Current page') })
const RouterViewStub = defineComponent({
  setup(_props, { slots }) {
    return () => slots.default?.({ Component: RoutePage })
  },
})

describe('root application shell', () => {
  it('keeps the routed page above the decorative aura layer', () => {
    const wrapper = mount(App, {
      global: { stubs: { 'router-view': RouterViewStub, transition: true } },
    })
    expect(wrapper.find('.app-shell').exists()).toBe(true)
    expect(wrapper.find('.aurora-bg').attributes('aria-hidden')).toBe('true')
    expect(wrapper.find('.route-page').text()).toBe('Current page')
  })
})
