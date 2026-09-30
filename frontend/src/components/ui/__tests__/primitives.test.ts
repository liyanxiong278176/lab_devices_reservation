import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import Badge from '../Badge.vue'
import GhostButton from '../GhostButton.vue'
import GlowCard from '../GlowCard.vue'
import GradientButton from '../GradientButton.vue'
import PageDepthNotice from '../PageDepthNotice.vue'
import Panel from '../Panel.vue'
import Skeleton from '../Skeleton.vue'
import StatusDot from '../StatusDot.vue'
import Tag from '../Tag.vue'
import TextButton from '../TextButton.vue'
import Timeline from '../Timeline.vue'

const stubs = {
  'el-badge': { template: '<div class="badge-stub"><slot /></div>' },
  'el-tag': { inheritAttrs: false, template: '<span class="tag-stub" v-bind="$attrs"><slot /></span>' },
  'el-button': {
    inheritAttrs: false,
    template: '<button class="button-stub" v-bind="$attrs"><slot /></button>',
  },
}

describe('shared UI primitives', () => {
  it('renders badge variants and forwards value and slot content', () => {
    for (const variant of ['accent', 'success', 'warning', 'danger', 'info'] as const) {
      const wrapper = mount(Badge, {
        props: { variant },
        attrs: { value: 3, 'data-testid': 'count' },
        slots: { default: 'Unread' },
        global: { stubs },
      })
      expect(wrapper.find('.lab-badge').classes()).toContain(`lab-badge--${variant}`)
      expect(wrapper.find('.badge-stub').attributes('value')).toBe('3')
      expect(wrapper.text()).toContain('Unread')
    }
    const defaultBadge = mount(Badge, { slots: { default: 'default' }, global: { stubs } })
    expect(defaultBadge.find('.lab-badge').classes()).toContain('lab-badge--accent')
  })

  it('renders tags for every semantic variant and uses default when omitted', () => {
    for (const variant of ['default', 'success', 'warning', 'danger', 'info', 'accent'] as const) {
      const wrapper = mount(Tag, { props: { variant }, slots: { default: 'Approved' }, global: { stubs } })
      expect(wrapper.find('.lab-tag').classes()).toContain(`lab-tag--${variant}`)
      expect(wrapper.text()).toBe('Approved')
    }
    expect(mount(Tag, { slots: { default: 'Tag' }, global: { stubs } }).classes()).toContain('lab-tag--default')
  })

  it('forwards attributes and content through the three button wrappers', () => {
    const cases = [
      [TextButton, 'text-btn'],
      [GhostButton, 'ghost-btn'],
      [GradientButton, 'gradient-btn'],
    ] as const
    for (const [component, className] of cases) {
      const wrapper = mount(component, {
        attrs: { type: 'button', disabled: true, 'aria-label': 'Save record' },
        slots: { default: 'Save' },
        global: { stubs },
      })
      const button = wrapper.find(`.${className}`)
      expect(button.exists()).toBe(true)
      expect(button.attributes('type')).toBe('button')
      expect(button.attributes('disabled')).toBeDefined()
      expect(button.attributes('aria-label')).toBe('Save record')
      expect(button.text()).toBe('Save')
    }
  })

  it('supports polymorphic panel tags and accent styling', () => {
    const base = mount(Panel, { slots: { default: 'Card' } })
    expect(base.element.tagName).toBe('DIV')
    expect(base.classes()).toContain('panel')
    expect(base.classes()).not.toContain('panel--accent')
    const accent = mount(Panel, {
      props: { as: 'section', accent: true },
      slots: { default: 'Section' },
    })
    expect(accent.element.tagName).toBe('SECTION')
    expect(accent.classes()).toContain('panel--accent')
    expect(accent.text()).toBe('Section')

    const article = mount(GlowCard, { props: { as: 'article', accent: true }, slots: { default: 'Glow' } })
    expect(article.element.tagName).toBe('ARTICLE')
    expect(article.classes()).toContain('glow-card--accent')
    expect(article.text()).toBe('Glow')
  })

  it('renders status-dot accessibility labels, labels, overrides, sizes and status classes', () => {
    const cases = [
      ['IDLE', 'status-dot--idle', '空闲'],
      ['IN_USE', 'status-dot--in-use', '使用中'],
      ['MAINTENANCE', 'status-dot--maintenance', '维护中'],
      ['BROKEN', 'status-dot--broken', '故障'],
      ['DISABLED', 'status-dot--disabled', '已停用'],
      ['OFFLINE', 'status-dot--offline', '离线'],
      ['RETIRED', 'status-dot--retired', '已退役'],
    ] as const
    for (const [status, className, label] of cases) {
      const wrapper = mount(StatusDot, { props: { status } })
      expect(wrapper.classes()).toContain(className)
      expect(wrapper.attributes('role')).toBe('img')
      expect(wrapper.attributes('aria-label')).toBe(label)
      expect(wrapper.attributes('data-status')).toBe(status)
      expect(wrapper.find('.status-dot__dot').attributes('style')).toContain('8px')
    }
    const labeled = mount(StatusDot, {
      props: { status: 'IN_USE', label: true, size: 12, labelText: 'In progress' },
    })
    expect(labeled.attributes('role')).toBeUndefined()
    expect(labeled.attributes('aria-label')).toBeUndefined()
    expect(labeled.text()).toContain('In progress')
    expect(labeled.find('.status-dot__dot').attributes('style')).toContain('12px')
  })

  it('renders timeline statuses, optional details, stable keys and connector lines', () => {
    const wrapper = mount(Timeline, {
      props: {
        items: [
          { id: 'created', title: 'Created', desc: 'Request received', time: '09:00', status: 'done' },
          { title: 'Review', status: 'current' },
          { id: 3, title: 'Complete', time: 'later', status: 'todo' },
        ],
      },
    })
    expect(wrapper.findAll('.timeline__item')).toHaveLength(3)
    expect(wrapper.findAll('.timeline__line')).toHaveLength(2)
    expect(wrapper.findAll('.timeline__item')[0].attributes('data-status')).toBe('done')
    expect(wrapper.findAll('.timeline__item')[1].classes()).toContain('timeline__item--current')
    expect(wrapper.findAll('.timeline__item')[2].classes()).toContain('timeline__item--todo')
    expect(wrapper.text()).toContain('Request received')
    expect(wrapper.text()).toContain('09:00')
    expect(wrapper.text()).toContain('Review')
    expect(wrapper.text()).toContain('later')
    expect(wrapper.findAll('.timeline__desc')).toHaveLength(1)
  })

  it('renders each skeleton shape and marks only the final row of multi-line text', () => {
    const one = mount(Skeleton)
    expect(one.findAll('.skeleton')).toHaveLength(1)
    expect(one.find('.skeleton').classes()).toContain('skeleton--rect')
    const text = mount(Skeleton, { props: { variant: 'text', rows: 3, width: '50%', height: '12px' } })
    expect(text.findAll('.skeleton')).toHaveLength(3)
    expect(text.findAll('.skeleton--last')).toHaveLength(1)
    expect(text.findAll('.skeleton')[2].classes()).toContain('skeleton--last')
    expect(text.find('.skeleton-root').attributes('style')).toContain('50%')
    expect(mount(Skeleton, { props: { variant: 'circle' } }).find('.skeleton').classes())
      .toContain('skeleton--circle')
  })

  it('formats the bounded deep-page notice using the current locale', () => {
    const wrapper = mount(PageDepthNotice, { props: { total: 123456 } })
    expect(wrapper.attributes('role')).toBe('status')
    expect(wrapper.text()).toContain((123456).toLocaleString())
    expect(wrapper.text()).toContain('100,000')
  })
})
