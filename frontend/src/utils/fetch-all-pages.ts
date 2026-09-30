import type { Page } from '@/types/common'

export const PAGE_FETCH_BATCH_SIZE = 8

export async function fetchAllPages<T>(
  fetchPage: (page: number, pageSize: number) => Promise<Page<T>>,
  pageSize: number,
): Promise<T[]> {
  const first = await fetchPage(1, pageSize)
  const effectivePageSize = first.size || pageSize
  const pageCount = first.pages ?? Math.ceil(first.total / effectivePageSize)
  const records = [...first.records]

  for (let start = 2; start <= pageCount; start += PAGE_FETCH_BATCH_SIZE) {
    const end = Math.min(pageCount, start + PAGE_FETCH_BATCH_SIZE - 1)
    const pages = await Promise.all(
      Array.from({ length: end - start + 1 }, (_, index) =>
        fetchPage(start + index, effectivePageSize),
      ),
    )
    records.push(...pages.flatMap((page) => page.records))
  }

  return records
}
