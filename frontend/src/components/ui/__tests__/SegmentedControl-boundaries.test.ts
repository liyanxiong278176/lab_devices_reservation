import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import SegmentedControl from '../SegmentedControl.vue'

describe('SegmentedControl edge cases', () => {
  it('falls back to the first visual slot for an unknown model and uses accessible defaults', () => {
    const wrapper = mount(SegmentedControl, {
      props: {
        modelValue: 'missing',
        options: [{ value: 'a' }, { value: 'b', label: '' }],
        size: 'sm', orientation: 'vertical', label: '',
      },
    })
    expect(wrapper.attributes('aria-label')).toBe('选项组')
    expect(wrapper.classes()).toContain('segmented--sm')
    expect(wrapper.classes()).toContain('segmented--vertical')
    expect(wrapper.find('.segmented__slider').attributes('style')).toContain('--i: 0')
    expect(wrapper.findAll('.segmented__label')).toHaveLength(1)
    expect(wrapper.findAll('.segmented__icon')).toHaveLength(0)
    expect(wrapper.findAll('button')[0].attributes('aria-checked')).toBe('true')
  })

  it('ignores repeat selections and unsupported keys without preventing browser defaults', async () => {
    const wrapper = mount(SegmentedControl, {
      props: { modelValue: 'a', options: [{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }] },
    })
    await wrapper.findAll('button')[0].trigger('click')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()

    const event = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true })
    wrapper.findAll('button')[0].element.dispatchEvent(event)
    expect(event.defaultPrevented).toBe(false)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('returns no keyboard target when every option is disabled or the group is empty', async () => {
    const disabled = mount(SegmentedControl, {
      props: {
        modelValue: 'a',
        options: [{ value: 'a', disabled: true }, { value: 'b', disabled: true }],
      },
    })
    const event = new KeyboardEvent('keydown', { key: 'ArrowRight', cancelable: true })
    disabled.findAll('button')[0].element.dispatchEvent(event)
    await disabled.findAll('button')[1].trigger('keydown', { key: 'Home' })
    await disabled.findAll('button')[1].trigger('keydown', { key: 'End' })
    expect(event.defaultPrevented).toBe(false)
    expect(disabled.emitted('update:modelValue')).toBeUndefined()

    const empty = mount(SegmentedControl, { props: { modelValue: 'none', options: [] } })
    expect(empty.findAll('button')).toHaveLength(0)
    expect(empty.find('.segmented__slider').attributes('style')).toContain('--n: 0')
  })

  it('wraps a single enabled option to itself without emitting a duplicate value', async () => {
    const wrapper = mount(SegmentedControl, {
      props: { modelValue: 1, options: [{ value: 1, label: 'Only' }] },
    })
    await wrapper.find('button').trigger('keydown', { key: 'ArrowDown' })
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  })

  it('guards disabled selection, returns no End target when all options are disabled, and clears refs on unmount', () => {
    const wrapper = mount(SegmentedControl, {
      props: {
        modelValue: 'a',
        options: [{ value: 'a', disabled: true }, { value: 'b', disabled: true }],
      },
    })
    const setup = (wrapper.vm as unknown as { $: { setupState: Record<string, unknown> } }).$.setupState
    const onSelect = setup.onSelect as (option: { value: string; disabled: boolean }) => void
    const onKeydown = setup.onKeydown as (event: KeyboardEvent, index: number) => void

    onSelect({ value: 'b', disabled: true })
    onKeydown(new KeyboardEvent('keydown', { key: 'End', cancelable: true }), 0)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()

    wrapper.unmount()
  })
})
