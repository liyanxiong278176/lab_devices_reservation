import { describe, expect, it, vi } from 'vitest'
import { useCursorPageChain } from '../useCursorPageChain'

describe('useCursorPageChain', () => {
  it('按顺序建立页码到主键游标的链路', async () => {
    const calls: Array<number | null> = []
    const fetchPage = vi.fn(async (cursor: number | null) => {
      calls.push(cursor)
      const page = cursor === null ? 1 : cursor === 90 ? 2 : 3
      return {
        records: [page],
        total: 3,
        size: 1,
        current: 1,
        pages: 3,
        nextCursor: page < 3 ? (page === 1 ? 90 : 80) : null,
        hasMore: page < 3,
      }
    })
    const pager = useCursorPageChain<number>(fetchPage)

    const third = await pager.load(3)

    expect(calls).toEqual([null, 90, 80])
    expect(third.current).toBe(3)
    expect(third.records).toEqual([3])
  })

  it('重置后不会复用旧筛选条件的游标', async () => {
    const fetchPage = vi.fn(async (cursor: number | null) => ({
      records: [cursor],
      total: 2,
      size: 1,
      current: 1,
      nextCursor: cursor === null ? 10 : null,
      hasMore: cursor === null,
    }))
    const pager = useCursorPageChain<number | null>(fetchPage)

    await pager.load(2)
    pager.reset()
    await pager.load(2)

    expect(fetchPage.mock.calls).toEqual([[null], [10], [null], [10]])
  })
})
