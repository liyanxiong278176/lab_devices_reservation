import { beforeEach, describe, expect, it, vi } from 'vitest'

import request from '../request'
import { searchAllDevices } from '../device'
import { listAllLabs } from '../lab'

vi.mock('../request', () => ({ default: { get: vi.fn() } }))

const mockedGet = vi.mocked(request.get)

describe('paged scope option loaders', () => {
  beforeEach(() => vi.resetAllMocks())

  it('loads every page for a device search instead of limiting options to page one', async () => {
    const device = (id: number) => ({
      id,
      name: `Device ${id}`,
      status: 'IDLE',
      need_approval: false,
      max_reservation_days: 1,
    })
    mockedGet
      .mockResolvedValueOnce({
        items: [device(1)], total: 3, page: 1, page_size: 1, pages: 3, truncated: false,
      } as never)
      .mockResolvedValueOnce({
        items: [device(2)], total: 3, page: 2, page_size: 1, pages: 3, truncated: false,
      } as never)
      .mockResolvedValueOnce({
        items: [device(3)], total: 3, page: 3, page_size: 1, pages: 3, truncated: false,
      } as never)

    const result = await searchAllDevices('scope', 1)

    expect(result.map((row) => row.id)).toEqual([1, 2, 3])
    expect(mockedGet).toHaveBeenCalledTimes(3)
  })

  it('loads labs beyond the first page for the scope picker', async () => {
    const lab = (id: number) => ({ id, name: `Lab ${id}`, status: 'ACTIVE' })
    mockedGet
      .mockResolvedValueOnce({
        records: [lab(1)], total: 2, size: 1, current: 1, pages: 2, truncated: false,
      } as never)
      .mockResolvedValueOnce({
        records: [lab(2)], total: 2, size: 1, current: 2, pages: 2, truncated: false,
      } as never)

    const result = await listAllLabs(1)

    expect(result.map((row) => row.id)).toEqual([1, 2])
    expect(mockedGet).toHaveBeenCalledTimes(2)
  })
})
