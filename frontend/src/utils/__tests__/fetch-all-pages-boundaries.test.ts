import { describe, expect, it, vi } from 'vitest'
import { fetchAllPages } from '../fetch-all-pages'
import type { Page } from '@/types/common'

const page = <T>(records: T[], size: number, total: number, pages?: number): Page<T> => ({
  records, size, total, current: records.length ? 1 : 0, pages, truncated: false,
})

describe('fetchAllPages pagination boundaries', () => {
  it('derives page count from total and falls back to the requested page size', async () => {
    const fetch = vi.fn(async (index: number, size: number) => {
      expect(size).toBe(2)
      return index === 1 ? page([1], 0, 3) : page([2, 3], 2, 3)
    })

    await expect(fetchAllPages(fetch, 2)).resolves.toEqual([1, 2, 3])
    expect(fetch).toHaveBeenCalledTimes(2)
  })

  it('honors an explicit zero page count without issuing follow-up requests', async () => {
    const fetch = vi.fn().mockResolvedValue(page(['first'], 10, 50, 0))
    await expect(fetchAllPages(fetch, 10)).resolves.toEqual(['first'])
    expect(fetch).toHaveBeenCalledOnce()
  })

  it('fetches large result sets in bounded parallel batches and flattens all records', async () => {
    const fetch = vi.fn(async (index: number, size: number) => page([index], size, 10, 10))
    await expect(fetchAllPages(fetch, 4)).resolves.toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
    expect(fetch).toHaveBeenCalledTimes(10)
    expect(fetch.mock.calls.slice(1).every(([, size]) => size === 4)).toBe(true)
  })
})
