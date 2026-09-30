import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { searchAllDevices, searchDevices } from '@/api/device'
import { useRemoteDeviceOptions } from '../useRemoteDeviceOptions'

vi.mock('@/api/device', () => ({
  searchAllDevices: vi.fn(),
  searchDevices: vi.fn(),
}))

const mockedSearchAllDevices = vi.mocked(searchAllDevices)
const mockedSearchDevices = vi.mocked(searchDevices)

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

const Harness = defineComponent({
  setup() {
    return useRemoteDeviceOptions()
  },
  template: '<div />',
})

describe('useRemoteDeviceOptions', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.resetAllMocks()
  })

  afterEach(() => vi.useRealTimers())

  it('does not let a late initial page overwrite newer search results', async () => {
    const initialRequest = deferred<Awaited<ReturnType<typeof searchDevices>>>()
    const initialDevice = { id: 1, name: 'Initial device' }
    const matchingDevice = { id: 2, name: 'Matched device' }
    mockedSearchDevices.mockReturnValue(initialRequest.promise as never)
    mockedSearchAllDevices.mockResolvedValue([matchingDevice] as never)

    const wrapper = mount(Harness)
    const initialLoad = wrapper.vm.loadInitial()
    const search = wrapper.vm.search('matched')

    initialRequest.resolve({ records: [initialDevice] } as never)
    await initialLoad
    expect(wrapper.vm.options).toEqual([])

    await vi.advanceTimersByTimeAsync(250)
    await search

    expect(wrapper.vm.options).toEqual([matchingDevice])
    wrapper.unmount()
  })
})
