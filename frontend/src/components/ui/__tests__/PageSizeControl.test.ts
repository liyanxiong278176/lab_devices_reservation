import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import PageSizeControl from '../PageSizeControl.vue'

describe('PageSizeControl', () => {
  it('emits the numeric page size for both model update and change', async () => {
    const wrapper = mount(PageSizeControl, {
      props: { modelValue: 20, options: [10, 20, 50], label: '预约每页数量' },
    })

    expect(wrapper.get('select').attributes('aria-label')).toBe('预约每页数量')
    await wrapper.get('select').setValue('50')

    expect(wrapper.emitted('update:modelValue')).toEqual([[50]])
    expect(wrapper.emitted('change')).toEqual([[50]])
  })

  it('ignores a change event whose target is not a select element', () => {
    const wrapper = mount(PageSizeControl, {
      props: { modelValue: 20, options: [10, 20, 50], label: '预约每页数量' },
    })
    const internal = wrapper.vm.$ as unknown as {
      setupState: { onChange: (event: Event) => void }
    }

    internal.setupState.onChange(new Event('change'))

    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(wrapper.emitted('change')).toBeUndefined()
  })
})
