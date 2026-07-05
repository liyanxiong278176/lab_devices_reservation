import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import SegmentedControl from '../SegmentedControl.vue'

/**
 * SegmentedControl — 段控件(底槽 pill + 跟随选中项的青色滑块)
 * 滑块用 CSS Grid 等宽 + transform 百分比方案(`translateX(calc(var(--i) * 100%))`),
 * jsdom 不做真 layout(offsetLeft=0),所以测 --i CSS 变量与 data-active 标记,
 * 而不是 px 测量。
 */

const OPTS = [
  { value: 'a', label: 'A' },
  { value: 'b', label: 'B' },
  { value: 'c', label: 'C' },
]

describe('SegmentedControl', () => {
  it('mount + modelValue="a" 渲染全部 options 文本', () => {
    const wrapper = mount(SegmentedControl, {
      props: { modelValue: 'a', options: OPTS },
    })
    expect(wrapper.text()).toContain('A')
    expect(wrapper.text()).toContain('B')
    expect(wrapper.text()).toContain('C')
  })

  it('modelValue="a" → 值=a 的选项带 active 标记(data-active)', () => {
    const wrapper = mount(SegmentedControl, {
      props: { modelValue: 'a', options: OPTS },
    })
    const active = wrapper.find('[data-active="true"]')
    expect(active.exists()).toBe(true)
    expect(active.text()).toBe('A')
  })

  it('点击第二项 → emit update:modelValue payload "b"', async () => {
    const wrapper = mount(SegmentedControl, {
      props: { modelValue: 'a', options: OPTS },
    })
    const buttons = wrapper.findAll('button')
    await buttons[1].trigger('click')
    expect(wrapper.emitted('update:modelValue')).toBeTruthy()
    expect(wrapper.emitted('update:modelValue')![0]).toEqual(['b'])
  })

  it('disabled 选项点击不 emit', async () => {
    const opts = [
      { value: 'a', label: 'A' },
      { value: 'b', label: 'B', disabled: true },
    ]
    const wrapper = mount(SegmentedControl, {
      props: { modelValue: 'a', options: opts },
    })
    const buttons = wrapper.findAll('button')
    await buttons[1].trigger('click')
    expect(wrapper.emitted('update:modelValue')).toBeFalsy()
  })

  it('受控更新:父改 modelValue="b" → active 标记移到第二项', async () => {
    const wrapper = mount(SegmentedControl, {
      props: { modelValue: 'a', options: OPTS },
    })
    await wrapper.setProps({ modelValue: 'b' })
    const active = wrapper.find('[data-active="true"]')
    expect(active.exists()).toBe(true)
    expect(active.text()).toBe('B')
  })

  it('滑块元素存在 + --i 反映选中 index', () => {
    const wrapper = mount(SegmentedControl, {
      props: { modelValue: 'b', options: OPTS },
    })
    const slider = wrapper.find('.segmented__slider')
    expect(slider.exists()).toBe(true)
    // b 是第 1 项(0-based index=1)
    const i = (slider.element as HTMLElement).style.getPropertyValue('--i')
    expect(i.trim()).toBe('1')
  })

  it('受控更新:--i 跟随 modelValue 变化', async () => {
    const wrapper = mount(SegmentedControl, {
      props: { modelValue: 'a', options: OPTS },
    })
    await wrapper.setProps({ modelValue: 'c' })
    const slider = wrapper.find('.segmented__slider')
    const i = (slider.element as HTMLElement).style.getPropertyValue('--i')
    expect(i.trim()).toBe('2')
  })

  it('number 值也能工作:modelValue=1 选中第二项', () => {
    const opts = [
      { value: 0, label: '零' },
      { value: 1, label: '壹' },
    ]
    const wrapper = mount(SegmentedControl, {
      props: { modelValue: 1, options: opts },
    })
    const active = wrapper.find('[data-active="true"]')
    expect(active.text()).toBe('壹')
  })

  it('icon 选项渲染 icon 节点', () => {
    const wrapper = mount(SegmentedControl, {
      props: {
        modelValue: 'a',
        options: [
          { value: 'a', label: 'A', icon: 'Monitor' },
          { value: 'b', label: 'B' },
        ],
      },
    })
    expect(wrapper.find('.segmented__icon').exists()).toBe(true)
  })

  // ---- radiogroup 键盘 a11y(WAI-ARIA radiogroup 模式)----
  it('容器 role=radiogroup + aria-label;选项 role=radio + aria-checked', () => {
    const wrapper = mount(SegmentedControl, {
      props: { modelValue: 'a', options: OPTS, label: '状态筛选' },
    })
    expect(wrapper.find('[role="radiogroup"]').exists()).toBe(true)
    expect(wrapper.find('[role="radiogroup"]').attributes('aria-label')).toBe('状态筛选')
    const radios = wrapper.findAll('[role="radio"]')
    expect(radios).toHaveLength(3)
    expect(radios[0].attributes('aria-checked')).toBe('true') // a 选中
    expect(radios[1].attributes('aria-checked')).toBe('false')
  })

  it('ArrowRight 在 a → emit b(下一项)', async () => {
    const wrapper = mount(SegmentedControl, { props: { modelValue: 'a', options: OPTS } })
    await wrapper.findAll('button')[0].trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.emitted('update:modelValue')![0]).toEqual(['b'])
  })

  it('ArrowLeft 在 a → emit c(回绕到末项)', async () => {
    const wrapper = mount(SegmentedControl, { props: { modelValue: 'a', options: OPTS } })
    await wrapper.findAll('button')[0].trigger('keydown', { key: 'ArrowLeft' })
    expect(wrapper.emitted('update:modelValue')![0]).toEqual(['c'])
  })

  it('Home/End → emit 首项/末项', async () => {
    const wEnd = mount(SegmentedControl, { props: { modelValue: 'b', options: OPTS } })
    await wEnd.findAll('button')[1].trigger('keydown', { key: 'End' })
    expect(wEnd.emitted('update:modelValue')![0]).toEqual(['c'])

    const wHome = mount(SegmentedControl, { props: { modelValue: 'c', options: OPTS } })
    await wHome.findAll('button')[2].trigger('keydown', { key: 'Home' })
    expect(wHome.emitted('update:modelValue')![0]).toEqual(['a'])
  })

  it('ArrowRight 跳过 disabled 项(b disabled → a 直接到 c)', async () => {
    const opts = [
      { value: 'a', label: 'A' },
      { value: 'b', label: 'B', disabled: true },
      { value: 'c', label: 'C' },
    ]
    const wrapper = mount(SegmentedControl, { props: { modelValue: 'a', options: opts } })
    await wrapper.findAll('button')[0].trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.emitted('update:modelValue')![0]).toEqual(['c'])
  })

  it('roving tabindex:选中项 tabindex=0,其余 -1', () => {
    const wrapper = mount(SegmentedControl, { props: { modelValue: 'b', options: OPTS } })
    const buttons = wrapper.findAll('button')
    expect(buttons[0].attributes('tabindex')).toBe('-1')
    expect(buttons[1].attributes('tabindex')).toBe('0') // b 选中
    expect(buttons[2].attributes('tabindex')).toBe('-1')
  })
})
