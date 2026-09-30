import { onBeforeUnmount, ref } from 'vue'
import { searchAllDevices, searchDevices } from '@/api/device'
import type { DeviceVO } from '@/types/device'

const INITIAL_DEVICE_PAGE_SIZE = 100
const SEARCH_DEBOUNCE_MS = 250

export function useRemoteDeviceOptions() {
  const devices = ref<DeviceVO[]>([])
  const options = ref<DeviceVO[]>([])
  const loading = ref(false)
  let sequence = 0
  let debounceTimer: ReturnType<typeof setTimeout> | undefined
  let cancelDebounce: (() => void) | undefined
  let initialLoaded = false
  let initialLoad: Promise<void> | null = null
  let initialOptions: DeviceVO[] = []
  let activeQuery = ''

  function cancelPendingDebounce() {
    if (debounceTimer !== undefined) clearTimeout(debounceTimer)
    debounceTimer = undefined
    const finish = cancelDebounce
    cancelDebounce = undefined
    finish?.()
  }

  function mergeDevices(incoming: DeviceVO[]) {
    const merged = new Map(devices.value.map((device) => [device.id, device]))
    for (const device of incoming) merged.set(device.id, device)
    devices.value = [...merged.values()]
  }

  async function loadInitial() {
    if (initialLoaded) return
    if (!initialLoad) {
      initialLoad = (async () => {
        try {
          const page = await searchDevices({ page: 1, size: INITIAL_DEVICE_PAGE_SIZE })
          initialOptions = page.records
          if (!activeQuery) options.value = initialOptions
          mergeDevices(initialOptions)
          initialLoaded = true
        } catch {
          // The shared request interceptor presents API errors.
        } finally {
          initialLoad = null
        }
      })()
    }
    await initialLoad
  }

  async function search(keyword: string) {
    const requestSequence = ++sequence
    cancelPendingDebounce()
    const normalized = keyword.trim()
    activeQuery = normalized
    if (!normalized) {
      options.value = initialOptions
      loading.value = false
      return
    }

    loading.value = true
    await new Promise<void>((resolve) => {
      const finish = () => {
        debounceTimer = undefined
        cancelDebounce = undefined
        resolve()
      }
      cancelDebounce = finish
      debounceTimer = setTimeout(finish, SEARCH_DEBOUNCE_MS)
    })
    if (requestSequence !== sequence) return

    try {
      const matches = await searchAllDevices(normalized)
      if (requestSequence === sequence) {
        options.value = matches
        mergeDevices(matches)
      }
    } catch {
      // The shared request interceptor presents API errors.
    } finally {
      if (requestSequence === sequence) loading.value = false
    }
  }

  onBeforeUnmount(() => {
    sequence += 1
    cancelPendingDebounce()
  })

  return { devices, options, loading, loadInitial, search }
}
