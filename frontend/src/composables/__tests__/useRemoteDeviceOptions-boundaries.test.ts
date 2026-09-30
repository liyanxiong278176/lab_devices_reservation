import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'

const api = vi.hoisted(() => ({ searchAllDevices: vi.fn(), searchDevices: vi.fn() }))
vi.mock('@/api/device', () => api)

import { useRemoteDeviceOptions } from '../useRemoteDeviceOptions'

const Harness = defineComponent({ setup: () => useRemoteDeviceOptions(), template: '<div />' })
const device = (id: number, name = `device-${id}`) => ({ id, name })
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<T>((ok, fail) => { resolve = ok; reject = fail })
  return { promise, resolve, reject }
}

afterEach(() => vi.useRealTimers())

describe('remote device picker boundary conditions', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.resetAllMocks()
  })

  it('loads initial pages once, merges refreshed IDs, and restores defaults on blank searches', async () => {
    const wrapper = mount(Harness)
    api.searchDevices.mockResolvedValue({ records: [device(1, 'old'), device(2)], total: 2 })
    await wrapper.vm.loadInitial()
    await wrapper.vm.loadInitial()
    expect(api.searchDevices).toHaveBeenCalledOnce()
    expect(wrapper.vm.options).toEqual([device(1, 'old'), device(2)])

    api.searchAllDevices.mockResolvedValue([device(1, 'new'), device(3)])
    const search = wrapper.vm.search('  scope  ')
    expect(wrapper.vm.loading).toBe(true)
    await vi.advanceTimersByTimeAsync(250)
    await search
    expect(api.searchAllDevices).toHaveBeenCalledWith('scope')
    expect(wrapper.vm.options).toEqual([device(1, 'new'), device(3)])
    expect(wrapper.vm.devices).toEqual([device(1, 'new'), device(2), device(3)])

    await wrapper.vm.search('   ')
    expect(wrapper.vm.options).toEqual([device(1, 'old'), device(2)])
    expect(wrapper.vm.loading).toBe(false)
    expect(api.searchAllDevices).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('coalesces initial requests without overwriting options during an active query', async () => {
    const wrapper = mount(Harness)
    const initial = deferred<{ records: ReturnType<typeof device>[] }>()
    api.searchDevices.mockReturnValue(initial.promise)
    const firstLoad = wrapper.vm.loadInitial()
    const duplicateLoad = wrapper.vm.loadInitial()
    const search = wrapper.vm.search('active')
    initial.resolve({ records: [device(1)] })
    await Promise.all([firstLoad, duplicateLoad])
    expect(api.searchDevices).toHaveBeenCalledOnce()
    expect(wrapper.vm.options).toEqual([])

    api.searchAllDevices.mockResolvedValue([device(2)])
    await vi.advanceTimersByTimeAsync(250)
    await search
    expect(wrapper.vm.options).toEqual([device(2)])
    expect(wrapper.vm.devices).toEqual([device(1), device(2)])
    wrapper.unmount()
  })

  it('recovers from initial and search failures and clears the loading state', async () => {
    const wrapper = mount(Harness)
    api.searchDevices.mockRejectedValueOnce(new Error('initial failed'))
    await expect(wrapper.vm.loadInitial()).resolves.toBeUndefined()
    expect(wrapper.vm.loading).toBe(false)

    api.searchDevices.mockResolvedValueOnce({ records: [device(4)] })
    await wrapper.vm.loadInitial()
    expect(wrapper.vm.options).toEqual([device(4)])

    api.searchAllDevices.mockRejectedValue(new Error('search failed'))
    const search = wrapper.vm.search('broken')
    await vi.advanceTimersByTimeAsync(250)
    await expect(search).resolves.toBeUndefined()
    expect(wrapper.vm.loading).toBe(false)
    expect(wrapper.vm.options).toEqual([device(4)])
    wrapper.unmount()
  })

  it('lets the newest completed search win and cancels pending debounce work at unmount', async () => {
    const wrapper = mount(Harness)
    const firstResult = deferred<ReturnType<typeof device>[]>()
    const secondResult = deferred<ReturnType<typeof device>[]>()
    api.searchAllDevices.mockReturnValueOnce(firstResult.promise).mockReturnValueOnce(secondResult.promise)

    const first = wrapper.vm.search('first')
    await vi.advanceTimersByTimeAsync(250)
    await flushPromises()
    const second = wrapper.vm.search('second')
    await vi.advanceTimersByTimeAsync(250)
    await flushPromises()
    secondResult.resolve([device(2)])
    await second
    firstResult.resolve([device(1)])
    await first
    expect(wrapper.vm.options).toEqual([device(2)])
    expect(wrapper.vm.loading).toBe(false)

    const pending = wrapper.vm.search('will-unmount')
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(300)
    await expect(pending).resolves.toBeUndefined()
    expect(api.searchAllDevices).toHaveBeenCalledTimes(2)
  })
})
