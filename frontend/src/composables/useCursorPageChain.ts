import { ref } from 'vue'
import type { Page } from '@/types/common'

/**
 * Keeps a page-number UI while the API is driven by keyset cursors.
 *
 * Page N is only requested after page N-1 has supplied its cursor.  Changing
 * filters, sorting or page size must call reset(), which prevents a cursor
 * from one query shape leaking into another query shape.
 */
export function useCursorPageChain<T>(
  fetchPage: (cursor: number | null) => Promise<Page<T>>,
) {
  const pages = ref<Record<number, Page<T>>>({})
  const cursorBefore = ref<Record<number, number | null>>({ 1: null })

  function reset() {
    pages.value = {}
    cursorBefore.value = { 1: null }
  }

  async function load(targetPage: number): Promise<Page<T>> {
    const target = Math.max(1, targetPage)
    for (let pageNumber = 1; pageNumber <= target; pageNumber += 1) {
      if (pages.value[pageNumber]) continue
      const cursor = cursorBefore.value[pageNumber] ?? null
      const result = await fetchPage(cursor)
      result.current = pageNumber
      pages.value[pageNumber] = result
      cursorBefore.value[pageNumber + 1] = result.nextCursor ?? null
      if (!result.hasMore && pageNumber < target) break
    }
    return pages.value[target] || pages.value[target - 1] || {
      records: [],
      total: 0,
      size: 0,
      current: target,
      pages: 0,
      nextCursor: null,
      hasMore: false,
    }
  }

  return { pages, cursorBefore, reset, load }
}
